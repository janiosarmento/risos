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


@router.get("/popular")
def get_popular_tags(
    limit: int = Query(
        10, ge=1, le=50, description="Number of tags to return"
    ),
    min_count: int = Query(
        1, ge=1, description="Minimum post count to include"
    ),
    unread_only: bool = Query(False, description="Only count unread posts"),
    starred_only: bool = Query(False, description="Only count starred posts"),
    feed_id: Optional[int] = Query(
        None, description="Scope to a specific feed"
    ),
    category_id: Optional[int] = Query(
        None, description="Scope to a category"
    ),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get most popular tags by post count, excluding ignored tags."""
    ignored = {row.tag for row in db.query(IgnoredTag.tag).all()}

    query = db.query(
        PostTag.tag, func.count(PostTag.post_id).label("count")
    ).join(Post, Post.id == PostTag.post_id)

    if unread_only:
        query = query.filter(Post.is_read.is_(False))
    if starred_only:
        query = query.filter(Post.is_starred.is_(True))
    if feed_id is not None:
        query = query.filter(Post.feed_id == feed_id)
    elif category_id is not None:
        feed_ids = (
            db.query(Feed.id)
            .filter(Feed.category_id == category_id)
            .subquery()
        )
        query = query.filter(Post.feed_id.in_(feed_ids))

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
        existing = db.query(TopicTag.tag).filter(
            TopicTag.topic_id == exclude_topic_id
        )
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
    from app.services.cerebras._api import call_llm_json

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

    tags_list = "\n".join(f"- {row.tag} ({row.count} posts)" for row in rows)

    system_prompt = (
        "You are a tag consolidation assistant for an RSS reader. "
        "Tags are lowercase, hyphenated English terms (e.g. 'machine-learning'). "
        "Your job is to identify groups of near-duplicate or synonym tags that "
        "should be merged into a single canonical tag."
    )

    user_prompt = f"""Here are {len(rows)} tags with their post counts:

{tags_list}

Group any tags that are synonyms or near-duplicates (e.g. career-advice / career-tips / career-guidance). For each group:
- Choose the most descriptive, commonly-used tag as the canonical form
- Only group tags that truly mean the same thing
- Tags that are distinct concepts should NOT be grouped (e.g. 'ai' and 'ai-ethics' are different)
- A tag with no duplicates should be omitted entirely

Respond ONLY in JSON:
{{
  "groups": [
    {{"canonical": "best-tag", "merge": ["synonym1", "synonym2"]}}
  ]
}}

If no duplicates are found, return {{"groups": []}}"""

    result = await call_llm_json(system_prompt, user_prompt)

    # Validate: only include tags that actually exist in the batch
    available = {row.tag for row in rows}
    groups = []
    for g in result.get("groups", []):
        canonical = g.get("canonical", "")
        merge = [
            t
            for t in g.get("merge", [])
            if isinstance(t, str) and t in available
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
                text(
                    "UPDATE post_tags SET tag = :canonical WHERE tag = :source"
                ),
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
                text(
                    "UPDATE topic_tags SET tag = :canonical WHERE tag = :source"
                ),
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
                yield json_line(
                    {"type": "done", "tags_removed": 0, "rows_deleted": 0}
                )
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
