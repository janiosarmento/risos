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
library the most common tags are near-universal ("2026" was on 12.8k of
64k tagged posts when this was written), so almost every pair of posts
shares a few. Weighting by inverse frequency — the same
`1 / log(freq + 1)` used by the related-posts search in
`routes/posts.py::_tag_search_related` — and ignoring tags that are too
common to mean anything is what turns this from noise into signal. On the
library this was developed against, that took 331 starred posts from
"299 of them look related to something" down to 20 posts in a handful of
genuinely overlapping groups (three DMARC/SPF articles, seven
WireGuard/Tailscale ones, and so on).
"""

import logging
import math
from collections import defaultdict
from typing import Iterable

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import PostTag

logger = logging.getLogger(__name__)

# A tag on more than this share of the tagged corpus is treated as a topic
# label rather than a distinguishing feature, and is ignored when looking
# for overlap. Expressed as a ratio so it holds on libraries of any size.
GENERIC_TAG_RATIO = 0.005

# ...but on a small or brand-new library that ratio lands on a handful of
# posts and would throw away everything, so never call a tag generic below
# this absolute count.
GENERIC_TAG_MIN_FREQ = 20

# A pair needs at least this many discriminative tags in common before it is
# even considered. One shared specific tag is usually a coincidence.
MIN_SHARED_TAGS = 2

# ...and the inverse-frequency weight of those shared tags has to clear this.
# Deliberately tuned for recall, not precision. Ranking the real candidate
# pairs on the library this was developed against showed the two axes do not
# line up: a false positive ("Bash wrapper for LLM API" + "shell exclamation
# mark", two tags in common, 0.56) outranks a true one (two articles about
# the same Tailcat release, 0.50). Score can tell "these are about the same
# subject" from "these are unrelated", but it cannot tell "same subject" from
# "actually supersedes" — that judgement is the LLM's remaining job. So the
# cut is set low enough to keep the real groups (the WireGuard/Tailscale
# component bottoms out at 0.44), and a few extra candidates per run cost
# almost nothing: they are a line each in a prompt the model was going to be
# sent anyway.
MIN_PAIR_SCORE = 0.40

# Clusters bigger than this are split for prompting: past a dozen articles
# the adjudication prompt stops being small, which is the whole point here.
MAX_CLUSTER_SIZE = 12

# Chunk size for `IN (...)` lookups, kept well under SQLite's variable limit.
_ID_CHUNK = 400


def _chunks(items: list, size: int) -> Iterable[list]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def tag_weight(freq: int) -> float:
    """Inverse-frequency weight for a tag, matching _tag_search_related."""
    return 1.0 / math.log(freq + 1) if freq > 0 else 0.1


class _UnionFind:
    """Groups candidate pairs into connected components.

    Redundancy is transitive in practice: if A is covered by B and B by C,
    all three belong in one group for the LLM to sort out, even when A and
    C share no tags directly.
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

    total_tagged = (
        db.query(func.count(func.distinct(PostTag.post_id))).scalar() or 0
    )
    generic_cutoff = max(
        GENERIC_TAG_MIN_FREQ, int(total_tagged * GENERIC_TAG_RATIO)
    )

    # Inverted index over the posts in scope, generic tags dropped.
    posts_by_tag: dict[str, list[int]] = defaultdict(list)
    for post_id, tags in tags_by_post.items():
        for tag in tags:
            if freqs.get(tag, 0) <= generic_cutoff:
                posts_by_tag[tag].append(post_id)

    # Accumulate per-pair overlap. Only tags shared by 2+ in-scope posts can
    # contribute, so this stays far smaller than all-pairs.
    pair_score: dict[tuple[int, int], float] = defaultdict(float)
    pair_shared: dict[tuple[int, int], int] = defaultdict(int)
    pair_tags: dict[tuple[int, int], list[str]] = defaultdict(list)

    for tag, members in posts_by_tag.items():
        if len(members) < 2:
            continue
        weight = tag_weight(freqs.get(tag, 1))
        members.sort()
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                key = (a, b)
                pair_score[key] += weight
                pair_shared[key] += 1
                pair_tags[key].append(tag)

    uf = _UnionFind()
    kept_pairs: list[tuple[int, int]] = []
    for key, shared in pair_shared.items():
        if shared < MIN_SHARED_TAGS:
            continue
        if pair_score[key] < MIN_PAIR_SCORE:
            continue
        uf.union(*key)
        kept_pairs.append(key)

    clusters = [c for c in uf.groups() if len(c) >= 2]

    # Split oversized clusters so no single adjudication prompt gets large.
    sized_ids: list[list[int]] = []
    for cluster in clusters:
        if len(cluster) <= MAX_CLUSTER_SIZE:
            sized_ids.append(cluster)
        else:
            for part in _chunks(cluster, MAX_CLUSTER_SIZE):
                if len(part) >= 2:
                    sized_ids.append(part)

    # The tags that caused each grouping are worth carrying through: they go
    # into the adjudication prompt so the model can see on what grounds these
    # articles were put side by side.
    sized: list[dict] = []
    for members in sized_ids:
        member_set = set(members)
        tags: set[str] = set()
        for (a, b) in kept_pairs:
            if a in member_set and b in member_set:
                tags.update(pair_tags[(a, b)])
        sized.append({"post_ids": members, "shared_tags": sorted(tags)})

    diagnostics = {
        "posts_in_scope": len(post_ids),
        "generic_tag_cutoff": generic_cutoff,
        "candidate_pairs": len(kept_pairs),
        "clusters": len(sized),
        "posts_clustered": sum(len(c["post_ids"]) for c in sized),
    }
    logger.info(
        "Curation clustering: %d posts in scope, generic cutoff %d, "
        "%d candidate pairs, %d clusters covering %d posts",
        len(post_ids),
        generic_cutoff,
        len(kept_pairs),
        len(sized),
        diagnostics["posts_clustered"],
    )
    return sized, diagnostics
