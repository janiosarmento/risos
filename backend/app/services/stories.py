"""
Story grouping: collapse posts that report the *same event* into one card.

This is deliberately not the same question as curation's redundancy
clustering (`app.services.curation`). Curation asks "do these articles cover
the same ground?", which tag overlap answers well enough for an LLM to
adjudicate afterwards. Here there is no LLM and the result is shown directly
in the main list, so precision matters far more than recall: two articles that
merely both mention macOS must NOT be folded together, while two feeds
reporting the same launch should.

Tuned for recall over precision (the user would rather see a few unrelated
posts folded together than miss real duplicates): a wrongly folded post is one
click away, a missed duplicate is invisible.

Three signals must agree, cheapest first:

1. **Time.** Posts must be within `MAX_GAP` of each other. A story is an
   event; two articles months apart are never the same story, and this alone
   removes almost every false positive from the topic-level tags.
2. **Title.** TF-IDF cosine over title tokens. Titles carry the proper nouns
   and numbers ("Starship", "v2.1") that tags generalise away.
3. **Tags.** The IDF-weighted tag cosine curation already uses, as a
   confirmation. It rescues paraphrased titles and vetoes coincidental
   headline overlap.

Grouping is transitive (union-find) like curation, so chains are broken the
same way: an oversized component is re-clustered at a stricter title bar.
"""

import logging
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AISummary, Post, PostTag
from app.services.curation import (
    _chunks,
    _load_global_tag_frequencies,
    _load_tags_for_posts,
    _UnionFind,
    tag_idf,
)

logger = logging.getLogger(__name__)

# Bump when scoring or grouping changes so any cached grouping is discarded.
STORY_ALGO_VERSION = 7

# Two posts further apart than this are never the same story.
MAX_GAP = timedelta(hours=48)

# Only posts this recent are grouped at all; older ones are left alone so the
# comparison set (and the cost) stays bounded.
LOOKBACK = timedelta(days=7)

# Title tokens shorter than this carry no identity.
MIN_TOKEN_LEN = 3

# A title token present in more than this share of titles is not used to seed
# candidate pairs (performance guard, like curation's PAIR_SEED_MAX_RATIO).
SEED_MAX_RATIO = 0.05
SEED_MIN_FREQ = 20

# A pair needs this many title tokens in common, so one shared word
# ("Apple", "Linux") is never enough on its own.
MIN_SHARED_TOKENS = 2

# Title cosine a pair must reach outright, or in combination with tags below.
TITLE_SCORE_STRONG = 0.55
# Weaker title agreement is accepted only when the tags confirm it, and the
# weaker the title, the more the tags must agree. Headlines on one event often
# share few words ("Three New Apple Smart Home Products" / "Apple Smart Home
# Hub to Feature iMac G4-Style Design") while sharing most of their tags.
TITLE_SCORE_WEAK = 0.30
TAG_SCORE_CONFIRM = 0.40
# Titles that already agree well (a distinctive name plus context, like
# "DoorDash ... Apple Messages") need only a sanity check from the tags: the
# LLM often tags one event quite differently from one article to the next.
TITLE_SCORE_MID = 0.35
TAG_SCORE_CONFIRM_LOOSE = 0.15
TITLE_SCORE_VERY_WEAK = 0.15
TAG_SCORE_CONFIRM_STRONG = 0.50
# ...and then only with this many title tokens in common, not just two.
WEAK_MIN_SHARED_TOKENS = 2

# A feed rarely reports one event twice; what it does do is post recurring
# series ("Daily", "Deals", "Oferta: ...") whose titles overlap heavily. Two
# posts from the same feed therefore need clearly agreeing titles. Tags cannot
# tell these apart: measured on a real week, same-feed pairs that are one story
# and pairs that are two items of a series overlap in tag score. The bar is set
# low on purpose (see the recall note above) so a feed's own follow-ups group.
SAME_FEED_TITLE_SCORE = 0.55

# Pairs that name the same date ("October 13") may agree on much less of the
# title, since the date is the identifying part.
DATE_TITLE_SCORE = 0.12

# Oversized components are re-clustered at a stricter title bar.
MAX_GROUP_SIZE = 8
SPLIT_STEP = 0.05
SPLIT_MAX_SCORE = 0.95

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Words that appear in headlines of every story. Kept small on purpose: the
# IDF weighting already discounts common words, this just stops them seeding
# pairs and counting toward MIN_SHARED_TOKENS.
_STOPWORDS = frozenset(
    """
    the and for with from that this these those into over under about after
    before have has had are was were will would could should can not but you
    your our their its his her how why what when where who which than then
    new now says say said via out off all any more most just one two get gets
    got use uses using used vs review report reports latest update updates
    uma uns para com por que como mais sobre entre seus suas nos nas dos das
    """.split()
)


# Summary similarity: a third, independent route to the same conclusion. Two
# feeds covering one event word their headlines differently but the AI summaries
# are all in one language and repeat the concrete facts (names, figures, models).
# Measured as *containment*, not plain cosine: a two-line summary of a short
# post shares most of its words with a long summary of the same event, which
# cosine dilutes (0.12) and containment keeps (0.21+).
SUMMARY_CONTAIN_SCORE = 0.40
# Same-feed pairs are mostly series ("Daily", "Deals: ..."), whose summaries
# overlap heavily too, so they need a clearly higher bar.
SUMMARY_SAME_FEED_SCORE = 0.65
SUMMARY_SEED_MAX_RATIO = 0.05
SUMMARY_SEED_MIN_FREQ = 20

_SUMMARY_STOPWORDS = _STOPWORDS | frozenset(
    """
    não uma dos das para com por mais como seu sua são foi está também entre
    sobre segundo artigo modelo modelos novo nova novos nova ainda até pelo pela
    nas nos mas ser tem além ela ele eles elas isso essa esse esta este deve
    pode podem sendo tendo foram será cada quando onde quer outros outras
    """.split()
)


def tokenize_summary(text: str | None) -> set[str]:
    if not text:
        return set()
    # The generating model appends a "— model name / timestamp" footer.
    body = text.split("\n—")[0].lower()
    return {
        t
        for t in _TOKEN_RE.findall(body)
        if (len(t) >= MIN_TOKEN_LEN or t.isdigit()) and t not in _SUMMARY_STOPWORDS
    }


class StoryPost(NamedTuple):
    id: int
    feed_id: int
    sort_date: datetime
    title: str


_MONTHS = {
    "jan": "january", "feb": "february", "mar": "march", "apr": "april",
    "jun": "june", "jul": "july", "aug": "august", "sep": "september",
    "sept": "september", "oct": "october", "nov": "november", "dec": "december",
    "january": "january", "february": "february", "march": "march",
    "april": "april", "may": "may", "june": "june", "july": "july",
    "august": "august", "september": "september", "october": "october",
    "november": "november", "december": "december",
}  # fmt: skip

# "October 13" / "Oct. 13" / "Oct 13th": a date in a headline names the event
# ("...launching October 13") far better than any word around it does, so it is
# folded into one token that survives the length filter and IDF then treats as
# the rare, high-signal term it is.
_DATE_RE = re.compile(r"\b([a-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b")


def tokenize_title(title: str | None) -> set[str]:
    if not title:
        return set()
    lowered = title.lower()
    tokens = {
        t
        for t in _TOKEN_RE.findall(lowered)
        if len(t) >= MIN_TOKEN_LEN and t not in _STOPWORDS
    }
    for word, day in _DATE_RE.findall(lowered):
        month = _MONTHS.get(word)
        if month:
            tokens.add(f"{month}_{int(day)}")
    return tokens


def _title_idf(token_sets: dict[int, set[str]]) -> dict[str, float]:
    n = len(token_sets)
    df: Counter = Counter()
    for tokens in token_sets.values():
        df.update(tokens)
    return {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}


def group_stories(
    posts: list[StoryPost],
    tags_by_post: dict[int, set[str]],
    tag_idf_map: dict[str, float],
    summaries: dict[int, str] | None = None,
) -> list[list[int]]:
    """Pure grouping logic over already-loaded data. Returns id groups (size>=2)."""
    if len(posts) < 2:
        return []

    by_id = {p.id: p for p in posts}
    token_sets = {p.id: tokenize_title(p.title) for p in posts}
    tidf = _title_idf(token_sets)

    title_norm = {
        pid: math.sqrt(sum(tidf[t] ** 2 for t in toks))
        for pid, toks in token_sets.items()
    }
    tag_norm = {
        pid: math.sqrt(sum(tag_idf_map.get(t, 0.0) ** 2 for t in tags))
        for pid, tags in tags_by_post.items()
    }

    seed_cutoff = max(SEED_MIN_FREQ, int(len(posts) * SEED_MAX_RATIO))
    posts_by_token: dict[str, list[int]] = defaultdict(list)
    for pid, toks in token_sets.items():
        for t in toks:
            posts_by_token[t].append(pid)

    # Common tokens are skipped when seeding, so a pair only needs to share one
    # *distinctive* token to be looked at; the real overlap is counted below.
    candidates: set[tuple[int, int]] = set()
    for tok, members in posts_by_token.items():
        if len(members) < 2 or len(members) > seed_cutoff:
            continue
        members.sort()
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                candidates.add((a, b))

    scores: dict[tuple[int, int], float] = {}
    for a, b in candidates:
        if abs(by_id[a].sort_date - by_id[b].sort_date) > MAX_GAP:
            continue
        shared = token_sets[a] & token_sets[b]
        n_shared = len(shared)
        if n_shared < MIN_SHARED_TOKENS:
            continue
        denom = title_norm[a] * title_norm[b]
        if denom <= 0:
            continue
        t_score = sum(tidf[t] ** 2 for t in shared) / denom
        shares_date = any("_" in t for t in shared)
        if t_score < (DATE_TITLE_SCORE if shares_date else TITLE_SCORE_VERY_WEAK):
            continue
        if by_id[a].feed_id == by_id[b].feed_id and t_score < SAME_FEED_TITLE_SCORE:
            continue
        if t_score < TITLE_SCORE_STRONG:
            # Naming the same date is itself strong evidence of the same event,
            # so it stands in for tag confirmation when the title also agrees.
            if shares_date and n_shared >= WEAK_MIN_SHARED_TOKENS:
                if t_score >= TITLE_SCORE_VERY_WEAK:
                    scores[(a, b)] = t_score
                    continue
            if n_shared < (
                MIN_SHARED_TOKENS if shares_date else WEAK_MIN_SHARED_TOKENS
            ):
                continue
            tags_a = tags_by_post.get(a, set())
            tags_b = tags_by_post.get(b, set())
            tag_denom = tag_norm.get(a, 0.0) * tag_norm.get(b, 0.0)
            if tag_denom <= 0:
                continue
            tag_score = (
                sum(tag_idf_map.get(t, 0.0) ** 2 for t in tags_a & tags_b) / tag_denom
            )
            if shares_date:
                needed = TAG_SCORE_CONFIRM
            elif t_score >= TITLE_SCORE_MID:
                needed = TAG_SCORE_CONFIRM_LOOSE
            elif t_score >= TITLE_SCORE_WEAK:
                needed = TAG_SCORE_CONFIRM
            else:
                needed = TAG_SCORE_CONFIRM_STRONG
            if tag_score < needed:
                continue
        scores[(a, b)] = t_score

    _add_summary_pairs(scores, by_id, summaries or {})

    return _split_until_small(list(scores), scores, TITLE_SCORE_VERY_WEAK)


def _add_summary_pairs(
    scores: dict[tuple[int, int], float],
    by_id: dict[int, "StoryPost"],
    summaries: dict[int, str],
) -> None:
    """Add pairs whose AI summaries largely contain each other's content."""
    token_sets = {
        pid: toks
        for pid, text in summaries.items()
        if pid in by_id and (toks := tokenize_summary(text))
    }
    if len(token_sets) < 2:
        return

    n = len(token_sets)
    df: Counter = Counter()
    for toks in token_sets.values():
        df.update(toks)
    idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
    weight = {pid: sum(idf[t] ** 2 for t in toks) for pid, toks in token_sets.items()}

    seed_cutoff = max(SUMMARY_SEED_MIN_FREQ, int(n * SUMMARY_SEED_MAX_RATIO))
    posts_by_token: dict[str, list[int]] = defaultdict(list)
    for pid, toks in token_sets.items():
        for t in toks:
            if df[t] <= seed_cutoff:
                posts_by_token[t].append(pid)

    # Pairs are enumerated along the time axis and stop as soon as the gap is
    # exceeded: most pairs sharing a word are days apart and never qualify.
    candidates: set[tuple[int, int]] = set()
    for members in posts_by_token.values():
        if len(members) < 2:
            continue
        members.sort(key=lambda pid: by_id[pid].sort_date)
        for i, a in enumerate(members):
            for b in members[i + 1 :]:
                if by_id[b].sort_date - by_id[a].sort_date > MAX_GAP:
                    break
                candidates.add((a, b) if a < b else (b, a))

    for a, b in candidates:
        if abs(by_id[a].sort_date - by_id[b].sort_date) > MAX_GAP:
            continue
        smaller = min(weight[a], weight[b])
        if smaller <= 0:
            continue
        shared = token_sets[a] & token_sets[b]
        score = sum(idf[t] ** 2 for t in shared) / smaller
        needed = (
            SUMMARY_SAME_FEED_SCORE
            if by_id[a].feed_id == by_id[b].feed_id
            else SUMMARY_CONTAIN_SCORE
        )
        if score >= needed:
            scores[(a, b)] = max(score, scores.get((a, b), 0.0))


def _split_until_small(
    pairs: list[tuple[int, int]],
    scores: dict[tuple[int, int], float],
    threshold: float,
) -> list[list[int]]:
    uf = _UnionFind()
    for pair in pairs:
        uf.union(*pair)

    out: list[list[int]] = []
    for component in uf.groups():
        if len(component) < 2:
            continue
        if len(component) <= MAX_GROUP_SIZE:
            out.append(component)
            continue
        if threshold >= SPLIT_MAX_SCORE:
            out.extend(
                part for part in _chunks(component, MAX_GROUP_SIZE) if len(part) >= 2
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


def find_stories(db: Session, now: datetime | None = None) -> list[list[int]]:
    """Group recent posts into stories. Returns lists of post ids (size >= 2)."""
    now = now or datetime.utcnow()
    since = now - LOOKBACK
    rows = (
        db.query(Post.id, Post.feed_id, Post.sort_date, Post.title)
        .filter(Post.sort_date >= since, Post.title.isnot(None))
        .all()
    )
    posts = [
        StoryPost(r.id, r.feed_id, r.sort_date, r.title) for r in rows if r.sort_date
    ]
    if len(posts) < 2:
        return []

    ids = [p.id for p in posts]
    tags_by_post = _load_tags_for_posts(db, ids)
    all_tags = {t for tags in tags_by_post.values() for t in tags}
    freqs = _load_global_tag_frequencies(db, all_tags)
    total_tagged = db.query(func.count(func.distinct(PostTag.post_id))).scalar() or 0
    idf = {t: tag_idf(freqs.get(t, 1), total_tagged) for t in all_tags}

    summaries = {
        pid: text
        for pid, text in db.query(Post.id, AISummary.summary_pt)
        .join(AISummary, AISummary.content_hash == Post.content_hash)
        .filter(Post.sort_date >= since)
        .all()
        if text
    }
    groups = group_stories(posts, tags_by_post, idf, summaries)
    logger.info(
        "Story grouping: %d posts, %d stories covering %d posts",
        len(posts),
        len(groups),
        sum(len(g) for g in groups),
    )
    return groups


# The grouping scans a week of posts on every list request otherwise, and the
# list endpoint is hit on every scroll. A minute of staleness is invisible: a
# new post just joins its story on the next refresh. Grouping is derived purely
# from post content, so nothing needs to invalidate it.
_CACHE_TTL_SECONDS = 60.0
_cache: dict = {"data": None, "members": {}, "ts": 0.0}


def get_story_map(db: Session) -> dict[int, tuple[int, int]]:
    """post_id -> (story_id, story_size), cached briefly.

    `story_id` is the lowest post id in the group, which is stable as the group
    grows and lets the client fold siblings that arrive on different pages.
    """
    now = time.monotonic()
    if _cache["data"] is not None and now - _cache["ts"] < _CACHE_TTL_SECONDS:
        return _cache["data"]
    story_map: dict[int, tuple[int, int]] = {}
    members: dict[int, list[int]] = {}
    for group in find_stories(db):
        story_id = min(group)
        members[story_id] = group
        for pid in group:
            story_map[pid] = (story_id, len(group))
    _cache["data"] = story_map
    _cache["members"] = members
    _cache["ts"] = now
    return story_map


def get_story_read_counts(
    db: Session, story_map: dict[int, tuple[int, int]], post_ids: list[int]
) -> dict[int, int]:
    """post_id -> how many *other* posts of its story are already read.

    Read state changes on every click, so unlike the grouping this is queried
    fresh, only for the stories present on the page being served.
    """
    story_ids = {story_map[pid][0] for pid in post_ids if pid in story_map}
    if not story_ids:
        return {}
    members = _cache["members"]
    all_ids = [pid for sid in story_ids for pid in members.get(sid, [])]
    read_ids = {
        row.id
        for row in db.query(Post.id).filter(
            Post.id.in_(all_ids), Post.is_read.is_(True)
        )
    }
    counts: dict[int, int] = {}
    for pid in post_ids:
        if pid not in story_map:
            continue
        group = members.get(story_map[pid][0], [])
        counts[pid] = sum(1 for other in group if other != pid and other in read_ids)
    return counts
