"""
Tag management routes.
Includes popular tags listing, ignored tags management, and AI-powered
tag consolidation (merge near-duplicate tags).
"""

import json
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Feed, IgnoredTag, Post, PostTag, TopicTag
from app.services.suggestions import clear_all_suggestions
from app.services.user_profile import invalidate_user_profile

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tags", tags=["tags"])


class TagRequest(BaseModel):
    tag: str


class SuggestMergesRequest(BaseModel):
    offset: int = 0
    batch_size: int = 100


class MergeGroup(BaseModel):
    canonical: str
    merge: List[str]


class ApplyMergesRequest(BaseModel):
    merges: List[MergeGroup]


class PurgeRareRequest(BaseModel):
    max_count: int = 1  # Delete tags appearing in at most this many posts


def _normalize_tag(tag: str) -> str:
    """Normalize a tag: lowercase, hyphens, strip, max 50 chars."""
    tag = tag.strip().lower()
    tag = tag.replace(" ", "-").replace("_", "-")
    return tag[:50]


def _edit_dist(s1: str, s2: str) -> int:
    """Standard space-optimized Levenshtein distance."""
    if len(s1) > len(s2):
        s1, s2 = s2, s1
    distances = range(len(s1) + 1)
    for i2, c2 in enumerate(s2):
        distances_ = [i2 + 1]
        for i1, c1 in enumerate(s1):
            if c1 == c2:
                distances_.append(distances[i1])
            else:
                distances_.append(
                    1 + min((distances[i1], distances[i1 + 1], distances_[-1]))
                )
        distances = distances_
    return distances[-1]


def _get_digits(s: str) -> str:
    """Extract all digits from a string."""
    return "".join(c for c in s if c.isdigit())


def _get_initials(tag: str) -> str:
    """Get the initials of a hyphenated tag."""
    parts = [p for p in tag.split("-") if p]
    if len(parts) > 1:
        return "".join(p[0] for p in parts)
    return ""


@router.get("/popular")
def get_popular_tags(
    limit: int = Query(10, ge=1, le=50, description="Number of tags to return"),
    min_count: int = Query(1, ge=1, description="Minimum post count to include"),
    unread_only: bool = Query(False, description="Only count unread posts"),
    starred_only: bool = Query(False, description="Only count starred posts"),
    suggested_only: bool = Query(False, description="Only count suggested posts"),
    feed_id: Optional[int] = Query(None, description="Scope to a specific feed"),
    category_id: Optional[int] = Query(None, description="Scope to a category"),
    topic_id: Optional[int] = Query(
        None, description="Scope to posts matching a topic's tags"
    ),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get most popular tags by post count, excluding ignored tags."""
    ignored = {row.tag for row in db.query(IgnoredTag.tag).all()}

    query = db.query(PostTag.tag, func.count(PostTag.post_id).label("count")).join(
        Post, Post.id == PostTag.post_id
    )

    if unread_only:
        query = query.filter(Post.is_read.is_(False))
    if starred_only:
        query = query.filter(Post.is_starred.is_(True))
    if suggested_only:
        query = query.filter(Post.is_suggested.is_(True))
    if feed_id is not None:
        query = query.filter(Post.feed_id == feed_id)
    elif category_id is not None:
        feed_ids = db.query(Feed.id).filter(Feed.category_id == category_id).subquery()
        query = query.filter(Post.feed_id.in_(feed_ids))

    # Scope to posts that have at least one of the topic's tags
    if topic_id is not None:
        topic_tags = [
            row.tag
            for row in db.query(TopicTag.tag)
            .filter(TopicTag.topic_id == topic_id)
            .all()
        ]
        if topic_tags:
            topic_post_ids = (
                db.query(PostTag.post_id)
                .filter(PostTag.tag.in_(topic_tags))
                .distinct()
                .subquery()
            )
            query = query.filter(Post.id.in_(topic_post_ids))

    rows = (
        query.group_by(PostTag.tag)
        .having(func.count(PostTag.post_id) >= min_count)
        .order_by(func.count(PostTag.post_id).desc())
        .all()
    )

    tags = []
    for row in rows:
        if row.tag in ignored:
            continue
        tags.append({"tag": row.tag, "count": row.count})
        if len(tags) >= limit:
            break

    return {"tags": tags}


@router.get("/search")
def search_tags(
    q: str = Query("", min_length=1, description="Tag prefix to search"),
    limit: int = Query(15, ge=1, le=50),
    exclude_topic_id: Optional[int] = Query(
        None, description="Exclude tags already in this topic"
    ),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Search tags by prefix, returning matches with post counts."""
    prefix = q.strip().lower()
    if not prefix:
        return {"tags": []}

    query = (
        db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
        .filter(PostTag.tag.like(f"{prefix}%"))
        .group_by(PostTag.tag)
        .order_by(func.count(PostTag.post_id).desc())
    )

    if exclude_topic_id is not None:
        existing = db.query(TopicTag.tag).filter(TopicTag.topic_id == exclude_topic_id)
        query = query.filter(~PostTag.tag.in_(existing))

    rows = query.limit(limit).all()
    return {"tags": [{"tag": row.tag, "count": row.count} for row in rows]}


@router.get("/ignored")
def get_ignored_tags(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get all ignored tags."""
    rows = db.query(IgnoredTag.tag).order_by(IgnoredTag.tag).all()
    return {"tags": [row.tag for row in rows]}


@router.post("/ignored")
def add_ignored_tag(
    body: TagRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Add a tag to the ignored list."""
    tag = _normalize_tag(body.tag)
    if not tag:
        raise HTTPException(status_code=400, detail="Tag cannot be empty")

    existing = db.query(IgnoredTag).filter(IgnoredTag.tag == tag).first()
    if not existing:
        db.add(IgnoredTag(tag=tag))
        db.commit()
        clear_all_suggestions(db)
        invalidate_user_profile(db)

    return {"success": True, "tag": tag}


@router.delete("/ignored/{tag}")
def remove_ignored_tag(
    tag: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Remove a tag from the ignored list."""
    tag = _normalize_tag(tag)
    row = db.query(IgnoredTag).filter(IgnoredTag.tag == tag).first()
    if row:
        db.delete(row)
        db.commit()
        clear_all_suggestions(db)
        invalidate_user_profile(db)

    return {"success": True}


@router.post("/suggest-merges")
async def suggest_merges(
    body: SuggestMergesRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Use AI to suggest near-duplicate tags that should be merged."""
    from app.services.ai._api import call_llm_json

    total_tags = db.query(func.count(func.distinct(PostTag.tag))).scalar() or 0

    rows = (
        db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
        .group_by(PostTag.tag)
        .order_by(PostTag.tag)
        .offset(body.offset)
        .limit(body.batch_size)
        .all()
    )

    if not rows:
        return {
            "groups": [],
            "total_tags": total_tags,
            "offset": body.offset,
            "batch_size": body.batch_size,
        }

    # Load all tags to find candidate synonyms from the entire database
    all_rows = (
        db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
        .group_by(PostTag.tag)
        .all()
    )

    # Pre-compute tag metadata ONCE to avoid heavy string/regex overhead in the O(N*M) search loop
    tag_metadata = {}
    for r in all_rows:
        t = r.tag
        t_clean = t.strip().lower()
        tag_metadata[t] = {
            "count": r.count,
            "clean": t_clean,
            "digits": _get_digits(t_clean),
            "initials": _get_initials(t_clean),
            "parts": [p for p in t_clean.split("-") if p],
        }

    # Build clean_to_original map for fast direct O(1) lookups
    clean_to_original = {meta["clean"]: tag for tag, meta in tag_metadata.items()}

    # Index segments to identify high-fan-out (generic) categories
    from collections import defaultdict

    segment_to_tags = defaultdict(set)
    for tag, meta in tag_metadata.items():
        for p in meta["parts"]:
            if len(p) >= 3:
                segment_to_tags[p].add(tag)

    # Segments that appear in more than 5 tags are considered generic category suffixes/prefixes
    generic_segments = {seg for seg, tags in segment_to_tags.items() if len(tags) > 5}

    # Build hyphenless_to_tags index (For exact hyphen difference)
    hyphenless_to_tags = defaultdict(set)
    for tag, meta in tag_metadata.items():
        hyphenless_to_tags[meta["clean"].replace("-", "")].add(tag)

    # Build initials_to_tags index (For acronym matching)
    initials_to_tags = defaultdict(set)
    for tag, meta in tag_metadata.items():
        initials = meta["initials"]
        if initials:
            initials_to_tags[initials].add(tag)

    # Build tags_by_len_and_first_char index (Massive Levenshtein optimization)
    tags_by_len_and_first_char = defaultdict(list)
    for tag, meta in tag_metadata.items():
        clean = meta["clean"]
        if clean:
            tags_by_len_and_first_char[(len(clean), clean[0])].append(tag)

    # Find candidate groups for the active batch using O(1) index lookups
    groups_to_eval = []
    seen_groups = set()

    for row in rows:
        t1 = row.tag
        if t1 not in tag_metadata:
            continue
        meta1 = tag_metadata[t1]
        t1_clean = meta1["clean"]
        t1_parts = meta1["parts"]
        t1_initials = meta1["initials"]
        t1_digits = meta1["digits"]

        candidate_pool = set()

        # --- INDEX LOOKUPS (No full database scan!) ---

        # Heuristic 1: Exact hyphen difference (O(1))
        hyphenless = t1_clean.replace("-", "")
        if hyphenless in hyphenless_to_tags:
            candidate_pool.update(hyphenless_to_tags[hyphenless])

        # Heuristic 2: Plural/singular difference (O(1))
        # e.g., tool -> tools
        for p in [t1_clean + "s", t1_clean + "es"]:
            if p in clean_to_original:
                candidate_pool.add(clean_to_original[p])
        # e.g., tools -> tool
        if t1_clean.endswith("s"):
            s1 = t1_clean[:-1]
            if s1 in clean_to_original:
                candidate_pool.add(clean_to_original[s1])
        if t1_clean.endswith("es"):
            s2 = t1_clean[:-2]
            if s2 in clean_to_original:
                candidate_pool.add(clean_to_original[s2])

        # Heuristic 3: Acronym / initials matching (O(1))
        # If t1 is an acronym (like "ai"), find all matching tags
        if len(t1_clean) in [2, 3] and t1_clean in initials_to_tags:
            candidate_pool.update(initials_to_tags[t1_clean])
        # If t1 is long (like "artificial-intelligence"), look up acronym tag
        if t1_initials and t1_initials in clean_to_original:
            candidate_pool.add(clean_to_original[t1_initials])

        # Heuristic 4: Shared specific segments matching (O(1) per segment)
        for p in t1_parts:
            if len(p) >= 3 and p not in generic_segments:
                if p in segment_to_tags:
                    candidate_pool.update(segment_to_tags[p])

        # Heuristic 5: Levenshtein spelling check (restricted strictly to distance <= 1)
        # Only checked against tags of similar length starting with the same first character
        if len(t1_clean) >= 4:
            first_char = t1_clean[0]
            for l in [len(t1_clean) - 1, len(t1_clean), len(t1_clean) + 1]:
                for t2 in tags_by_len_and_first_char[(l, first_char)]:
                    t2_clean = tag_metadata[t2]["clean"]
                    # Strict distance <= 1 check
                    if _edit_dist(t1_clean, t2_clean) <= 1:
                        candidate_pool.add(t2)

        # Verify and filter candidates from candidate_pool
        candidates = []
        for t2 in candidate_pool:
            if t2 == t1:
                continue
            meta2 = tag_metadata[t2]

            # Digit mismatch early reject
            if t1_digits != meta2["digits"]:
                continue

            candidates.append(t2)

        if candidates:
            # Form a candidate group and sort it
            group = sorted([t1] + candidates)
            group_key = tuple(group)
            if group_key not in seen_groups:
                seen_groups.add(group_key)
                groups_to_eval.append(group)

    # Short-circuit and return empty list if no candidate groups are found
    if not groups_to_eval:
        return {
            "groups": [],
            "total_tags": total_tags,
            "offset": body.offset,
            "batch_size": body.batch_size,
        }

    # Format the candidate groups for the LLM prompt
    group_lines = []
    for i, g in enumerate(groups_to_eval, 1):
        group_lines.append(f"Group {i}:")
        for tag in g:
            count = tag_metadata.get(tag, {}).get("count", 0)
            group_lines.append(f"- {tag} ({count} posts)")
        group_lines.append("")

    groups_list = "\n".join(group_lines)

    system_prompt = (
        "You are a tag consolidation assistant for an RSS reader. "
        "Tags are lowercase, hyphenated English terms (e.g. 'machine-learning'). "
        "Your job is to identify groups of near-duplicate or synonym tags that "
        "should be merged into a single canonical tag."
    )

    user_prompt = f"""I have pre-grouped some tags that are potential synonyms or near-duplicates. For each group, evaluate if they are indeed true synonyms or duplicates.

IMPORTANT Rules:
- Choose the most descriptive, commonly-used tag as the canonical form (prefer the one with the higher post count).
- Only group tags that truly mean the same thing.
- Tags that are distinct concepts should NOT be grouped (e.g. 'ai' and 'ai-ethics' are different).
- Do NOT merge different versions, generations, or numerical values (e.g., '4g' and '5g' are different, 'ipv4' and 'ipv6' are different, '2k' and '4k' are different, 'react-17' and 'react-18' are different, 'python2' and 'python3' are different).
- If a group contains no true duplicates/synonyms, skip it entirely.

Here are the candidate groups to evaluate:

{groups_list}

Respond ONLY in JSON format:
{{
  "groups": [
    {{"canonical": "best-tag", "merge": ["synonym1", "synonym2"]}}
  ]
}}

If no true duplicates/synonyms are found, return {{"groups": []}}"""

    result = await call_llm_json(system_prompt, user_prompt)

    # Validate: only include tags that actually existed in the generated candidate groups
    available = {tag for g in groups_to_eval for tag in g}
    groups = []
    for g in result.get("groups", []):
        canonical = g.get("canonical", "")
        merge = [
            t
            for t in g.get("merge", [])
            if isinstance(t, str) and t in available and t != canonical
        ]
        if canonical in available and merge:
            groups.append({"canonical": canonical, "merge": merge})

    return {
        "groups": groups,
        "total_tags": total_tags,
        "offset": body.offset,
        "batch_size": body.batch_size,
    }


@router.post("/apply-merges")
def apply_merges(
    body: ApplyMergesRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Apply tag merges: rename source tags to canonical in all tables."""
    tags_removed = 0
    posts_affected = 0

    for group in body.merges:
        canonical = _normalize_tag(group.canonical)
        if not canonical:
            continue

        for source in group.merge:
            source = _normalize_tag(source)
            if not source or source == canonical:
                continue

            # --- post_tags ---
            # Delete rows where the canonical already exists for the same post
            db.execute(
                text(
                    "DELETE FROM post_tags WHERE tag = :source "
                    "AND post_id IN ("
                    "  SELECT post_id FROM post_tags WHERE tag = :canonical"
                    ")"
                ),
                {"source": source, "canonical": canonical},
            )
            # Rename remaining source → canonical
            result = db.execute(
                text("UPDATE post_tags SET tag = :canonical WHERE tag = :source"),
                {"source": source, "canonical": canonical},
            )
            posts_affected += result.rowcount

            # --- topic_tags ---
            db.execute(
                text(
                    "DELETE FROM topic_tags WHERE tag = :source "
                    "AND topic_id IN ("
                    "  SELECT topic_id FROM topic_tags WHERE tag = :canonical"
                    ")"
                ),
                {"source": source, "canonical": canonical},
            )
            db.execute(
                text("UPDATE topic_tags SET tag = :canonical WHERE tag = :source"),
                {"source": source, "canonical": canonical},
            )

            # --- ignored_tags ---
            db.execute(
                text("DELETE FROM ignored_tags WHERE tag = :source"),
                {"source": source},
            )

            tags_removed += 1

    db.commit()

    if tags_removed > 0:
        clear_all_suggestions(db)
        invalidate_user_profile(db)

    logger.info(
        "Tag merge applied: %d tags removed, %d posts affected",
        tags_removed,
        posts_affected,
    )

    return {
        "success": True,
        "tags_merged": tags_removed,
        "posts_affected": posts_affected,
    }


@router.get("/rare-preview")
def preview_rare_tags(
    max_count: int = Query(
        1, ge=1, le=10, description="Max post count to consider rare"
    ),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Preview how many tags would be removed at each threshold."""
    total_tags = db.query(func.count(func.distinct(PostTag.tag))).scalar() or 0

    # Count tags at each threshold 1..max_count
    breakdowns = []
    for threshold in range(1, max_count + 1):
        count = (
            db.query(func.count())
            .select_from(
                db.query(PostTag.tag)
                .group_by(PostTag.tag)
                .having(func.count(PostTag.post_id) <= threshold)
                .subquery()
            )
            .scalar()
        ) or 0
        breakdowns.append({"max_count": threshold, "tag_count": count})

    # Sample tags at the requested threshold (for preview)
    sample_rows = (
        db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
        .group_by(PostTag.tag)
        .having(func.count(PostTag.post_id) <= max_count)
        .order_by(PostTag.tag)
        .limit(50)
        .all()
    )

    return {
        "total_tags": total_tags,
        "breakdowns": breakdowns,
        "sample": [{"tag": r.tag, "count": r.count} for r in sample_rows],
    }


@router.post("/purge-rare")
def purge_rare_tags(
    body: PurgeRareRequest,
    user: dict = Depends(get_current_user),
):
    """Delete tags that appear in at most N posts, streaming progress."""
    BATCH_SIZE = 500

    # Get our own db session so it persists across the generator
    db = next(get_db())

    # Collect rare tags up front (fast query)
    rare_tags_q = (
        db.query(PostTag.tag)
        .group_by(PostTag.tag)
        .having(func.count(PostTag.post_id) <= body.max_count)
    )
    rare_tags = [row.tag for row in rare_tags_q.all()]
    total = len(rare_tags)

    def json_line(obj):
        return json.dumps(obj) + "\n"

    def generate():
        try:
            if total == 0:
                yield json_line({"type": "done", "tags_removed": 0, "rows_deleted": 0})
                return

            yield json_line({"type": "start", "total_tags": total})

            deleted = 0
            total_rows = 0

            for i in range(0, total, BATCH_SIZE):
                batch = rare_tags[i : i + BATCH_SIZE]

                # Delete from post_tags
                rows = (
                    db.query(PostTag)
                    .filter(PostTag.tag.in_(batch))
                    .delete(synchronize_session=False)
                )
                total_rows += rows

                # Delete from topic_tags
                rows = (
                    db.query(TopicTag)
                    .filter(TopicTag.tag.in_(batch))
                    .delete(synchronize_session=False)
                )
                total_rows += rows

                # Delete from ignored_tags
                rows = (
                    db.query(IgnoredTag)
                    .filter(IgnoredTag.tag.in_(batch))
                    .delete(synchronize_session=False)
                )
                total_rows += rows

                db.commit()
                deleted += len(batch)
                yield json_line(
                    {
                        "type": "progress",
                        "deleted": deleted,
                        "total": total,
                        "rows": total_rows,
                    }
                )

            clear_all_suggestions(db)
            invalidate_user_profile(db)

            logger.info(
                "Purged %d rare tags (max_count=%d), %d rows deleted",
                total,
                body.max_count,
                total_rows,
            )

            yield json_line(
                {
                    "type": "done",
                    "tags_removed": deleted,
                    "rows_deleted": total_rows,
                }
            )
        finally:
            db.close()

    return StreamingResponse(generate(), media_type="application/x-ndjson")
