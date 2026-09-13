"""
Local (non-LLM) redundancy analysis for starred-post curation.

Curation used to hand the whole starred library to the LLM and ask it to
work out, from one-line summaries alone, which articles cover the same
ground. That is the expensive half of the job — it is quadratic in
nature, it is what forces a large prompt, and it is what made the
feature scale badly (a hard 100-post ceiling, and an output long enough
to take minutes on a small model).

But the app already has the signal needed to answer it: the tags the AI
assigns to every post at summary time. Two articles that cover the same
ground share several *specific* tags. So the candidate pairs can be found
here, in one pass over an indexed table, and the LLM only has to
adjudicate the handful of groups that come out of it.

The catch is that raw shared-tag counts do not discriminate: on a real
library the most common tags are near-universal ("open-source" was on
11.7k of 64k tagged posts when this was written), so almost every pair of
posts shares a few. Two articles are similar when they share tags that
are *rare*, in proportion to how specific each of them is overall — which
is cosine similarity over IDF-weighted tag vectors, the standard answer:

    sim(A, B) = Σ idf(t)² for t in A∩B  /  (‖A‖ · ‖B‖)

Measured on a real library, this separates cleanly: an article saved
twice from two feeds scores 0.95, three articles about self-hosted
NotebookLM alternatives land around 0.6-0.7, and two articles that merely
both mention macOS sit below 0.4.

Two earlier attempts are worth not repeating:

- **`1 / log(freq + 1)` weighting plus a hard "ignore tags above 0.5% of
  the corpus" cutoff.** Both halves failed. The cutoff (320 posts here)
  discarded `malware` (534) and `data-security` (484) — tags that are
  plainly specific — so a duplicate article saved twice scored *zero*.
  And the weight itself barely discriminates: across freq 10 → 12800 it
  only moves from 0.42 to 0.11, while true IDF moves from 8.8 to 1.6.
- **Transitive clustering at a single threshold.** Redundancy chains, so
  connected components snowball: at 0.55 across 334 starred posts one
  component swallowed 39 unrelated articles. Components are therefore
  re-clustered at a higher threshold until they are small enough to
  adjudicate (`_split_until_small`), which is a cheap stand-in for proper
  hierarchical clustering and needs no extra passes over the data.
"""

import logging
import math
from collections import defaultdict
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import PostTag

logger = logging.getLogger(__name__)

# Tags this common are not used to *find* candidate pairs — enumerating every
# pair that shares "open-source" is all cost and no signal. They still count
# in the similarity score itself, where IDF already makes them near-weightless.
# This is a performance guard, not a judgement about the tag: set far above
# the range where real subject tags live (`malware` is 0.8% of this corpus).
PAIR_SEED_MAX_RATIO = 0.20

# ...but on a small or brand-new library that ratio lands on a handful of
# posts and would refuse to seed any pair at all, so never treat a tag as
# too common below this absolute count.
PAIR_SEED_MIN_FREQ = 50

# A pair needs at least this many tags in common before it is considered at
# all. One shared tag is usually a coincidence, however rare that tag is.
MIN_SHARED_TAGS = 2

# Cosine similarity a pair must reach to be grouped. Tuned for recall against
# a real 334-post library: 0.45 catches the article saved twice (0.95), the
# three self-hosted NotebookLM write-ups (~0.6), and the "run an LLM on Apple
# silicon" family (~0.45), while leaving out pairs that merely share a
# platform. Precision is the LLM's job — an extra candidate costs one line in
# a prompt it was being sent anyway, while a missed one is invisible.
MIN_PAIR_SCORE = 0.45

# Clusters bigger than this are re-clustered at a stricter threshold: past a
# dozen articles the adjudication prompt stops being small, which is the whole
# point here, and a group that large is usually a chain rather than a topic.
MAX_CLUSTER_SIZE = 12

# How much stricter each re-clustering round gets, and where to give up and
# just chop the component into fixed-size pieces.
SPLIT_STEP = 0.05
SPLIT_MAX_SCORE = 0.90

# Chunk size for `IN (...)` lookups, kept well under SQLite's variable limit.
_ID_CHUNK = 400


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def tag_idf(freq: int, total_tagged: int) -> float:
    """How much a tag says about a post, by how rare it is.

    A tag on every post says almost nothing (idf → 0); one on a handful
    says a lot. Smoothed so that a brand-new library, where every tag is
    on "all" two of its posts, still produces usable weights instead of
    collapsing to zero everywhere. Clamped at zero so a frequency larger
    than the corpus — possible only from a stale count — cannot flip the
    sign of a similarity.
    """
    if freq <= 0 or total_tagged <= 0:
        return 0.0
    return max(0.0, math.log((total_tagged + 1) / (min(freq, total_tagged) + 0.5)))


class _UnionFind:
    """Groups candidate pairs into connected components.

    Redundancy is transitive in practice: if A is covered by B and B by C,
    all three belong in one group for the LLM to sort out, even when A and
    C share no tags directly. Chains that run too far are broken up again
    by `_split_until_small`.
    """

    def __init__(self) -> None:
        self._parent: dict[int, int] = {}

    def find(self, x: int) -> int:
        self._parent.setdefault(x, x)
        root = x
        while self._parent[root] != root:
            root = self._parent[root]
        # Path compression
        while self._parent[x] != root:
            self._parent[x], x = root, self._parent[x]
        return root

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self._parent[rb] = ra

    def groups(self) -> list[list[int]]:
        out: dict[int, list[int]] = defaultdict(list)
        for node in self._parent:
            out[self.find(node)].append(node)
        return [sorted(members) for members in out.values()]


def _load_tags_for_posts(db: Session, post_ids: list[int]) -> dict[int, set[str]]:
    tags_by_post: dict[int, set[str]] = defaultdict(set)
    for chunk in _chunks(post_ids, _ID_CHUNK):
        rows = (
            db.query(PostTag.post_id, PostTag.tag)
            .filter(PostTag.post_id.in_(chunk))
            .all()
        )
        for post_id, tag in rows:
            tags_by_post[post_id].add(tag)
    return tags_by_post


def _load_global_tag_frequencies(db: Session, tags: set[str]) -> dict[str, int]:
    freqs: dict[str, int] = {}
    tag_list = list(tags)
    for chunk in _chunks(tag_list, _ID_CHUNK):
        rows = (
            db.query(PostTag.tag, func.count(PostTag.post_id))
            .filter(PostTag.tag.in_(chunk))
            .group_by(PostTag.tag)
            .all()
        )
        for tag, freq in rows:
            freqs[tag] = freq
    return freqs


def find_redundancy_clusters(
    db: Session,
    post_ids: list[int],
) -> tuple[list[dict], dict]:
    """Group posts that plausibly cover the same ground.

    Returns (clusters, diagnostics), where each cluster is
    ``{"post_ids": [...], "shared_tags": [...]}``. Only posts that landed in
    a cluster are candidates for "redundant" — a post sharing no
    discriminative tags with anything else in scope cannot be covered by
    another post in the set, so it needs no LLM judgement at all.
    """
    if len(post_ids) < 2:
        return [], {"reason": "not enough posts to compare"}

    tags_by_post = _load_tags_for_posts(db, post_ids)
    if not tags_by_post:
        return [], {"reason": "no tags on any post in scope"}

    all_tags: set[str] = set()
    for tags in tags_by_post.values():
        all_tags.update(tags)

    freqs = _load_global_tag_frequencies(db, all_tags)

    total_tagged = db.query(func.count(func.distinct(PostTag.post_id))).scalar() or 0
    idf = {tag: tag_idf(freqs.get(tag, 1), total_tagged) for tag in all_tags}

    # Each post's tag vector length, for the cosine denominator. A post whose
    # tags are all generic has a short vector, so sharing those tags with
    # another such post still does not add up to similarity.
    norms = {
        post_id: math.sqrt(sum(idf.get(t, 0.0) ** 2 for t in tags)) or 0.0
        for post_id, tags in tags_by_post.items()
    }

    # Inverted index used only to enumerate pairs worth scoring. Tags common
    # enough to connect a large share of the corpus are skipped here: they
    # would generate O(n²) pairs that the score then rejects anyway.
    seed_cutoff = max(PAIR_SEED_MIN_FREQ, int(total_tagged * PAIR_SEED_MAX_RATIO))
    posts_by_tag: dict[str, list[int]] = defaultdict(list)
    for post_id, tags in tags_by_post.items():
        for tag in tags:
            if freqs.get(tag, 0) <= seed_cutoff:
                posts_by_tag[tag].append(post_id)

    candidates: set[tuple[int, int]] = set()
    for members in posts_by_tag.values():
        if len(members) < 2:
            continue
        members.sort()
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                candidates.add((a, b))

    # Score each candidate pair properly: full cosine over both tag vectors,
    # generic tags included (IDF makes them count for almost nothing).
    scores: dict[tuple[int, int], float] = {}
    shared_by_pair: dict[tuple[int, int], list[str]] = {}
    for a, b in candidates:
        shared = tags_by_post[a] & tags_by_post[b]
        if len(shared) < MIN_SHARED_TAGS:
            continue
        denom = norms.get(a, 0.0) * norms.get(b, 0.0)
        if denom <= 0:
            continue
        score = sum(idf.get(t, 0.0) ** 2 for t in shared) / denom
        if score < MIN_PAIR_SCORE:
            continue
        scores[(a, b)] = score
        shared_by_pair[(a, b)] = sorted(shared, key=lambda t: -idf.get(t, 0.0))

    clusters = _split_until_small(list(scores), scores, MIN_PAIR_SCORE)

    # The tags that caused each grouping are worth carrying through: they go
    # into the adjudication prompt so the model can see on what grounds these
    # articles were put side by side. Rarest first — those are the ones that
    # actually explain the grouping.
    sized: list[dict] = []
    for members in clusters:
        member_set = set(members)
        tags_ranked: list[str] = []
        for (a, b), shared in shared_by_pair.items():
            if a in member_set and b in member_set:
                tags_ranked.extend(t for t in shared if t not in tags_ranked)
        sized.append({"post_ids": members, "shared_tags": tags_ranked[:8]})

    diagnostics = {
        "posts_in_scope": len(post_ids),
        "tagged_corpus": total_tagged,
        "candidate_pairs": len(scores),
        "clusters": len(sized),
        "posts_clustered": sum(len(c["post_ids"]) for c in sized),
    }
    logger.info(
        "Curation clustering: %d posts in scope, %d pairs above %.2f, "
        "%d clusters covering %d posts",
        len(post_ids),
        len(scores),
        MIN_PAIR_SCORE,
        len(sized),
        diagnostics["posts_clustered"],
    )
    return sized, diagnostics


def _split_until_small(
    pairs: list[tuple[int, int]],
    scores: dict[tuple[int, int], float],
    threshold: float,
) -> list[list[int]]:
    """Connected components, re-clustered until none is too large.

    Grouping by "A is similar to B" chains: a component can grow through a
    long series of weak links until it holds articles with nothing to do
    with each other. Raising the bar inside an oversized component breaks
    exactly those weak links while leaving tight groups intact.
    """
    uf = _UnionFind()
    for pair in pairs:
        uf.union(*pair)

    out: list[list[int]] = []
    for component in uf.groups():
        if len(component) < 2:
            continue
        if len(component) <= MAX_CLUSTER_SIZE:
            out.append(component)
            continue
        if threshold >= SPLIT_MAX_SCORE:
            # Genuinely dense: nothing left to do but chop it up.
            out.extend(
                part for part in _chunks(component, MAX_CLUSTER_SIZE) if len(part) >= 2
            )
            continue
        members = set(component)
        stricter = threshold + SPLIT_STEP
        inner = [
            p
            for p in pairs
            if p[0] in members and p[1] in members and scores[p] >= stricter
        ]
        out.extend(_split_until_small(inner, scores, stricter))
    return out
