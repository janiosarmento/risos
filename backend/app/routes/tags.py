"""
Tag management routes.
Includes popular tags listing and ignored tags management.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Feed, IgnoredTag, Post, PostTag
from app.services.suggestions import clear_all_suggestions
from app.services.user_profile import invalidate_user_profile

router = APIRouter(prefix="/tags", tags=["tags"])


class TagRequest(BaseModel):
    tag: str


def _normalize_tag(tag: str) -> str:
    """Normalize a tag: lowercase, hyphens, strip, max 50 chars."""
    tag = tag.strip().lower()
    tag = tag.replace(" ", "-").replace("_", "-")
    return tag[:50]


@router.get("/popular")
def get_popular_tags(
    limit: int = Query(10, ge=1, le=50, description="Number of tags to return"),
    min_count: int = Query(1, ge=1, description="Minimum post count to include"),
    unread_only: bool = Query(False, description="Only count unread posts"),
    starred_only: bool = Query(False, description="Only count starred posts"),
    feed_id: Optional[int] = Query(None, description="Scope to a specific feed"),
    category_id: Optional[int] = Query(None, description="Scope to a category"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Get most popular tags by post count, excluding ignored tags."""
    ignored = {row.tag for row in db.query(IgnoredTag.tag).all()}

    query = (
        db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
        .join(Post, Post.id == PostTag.post_id)
    )

    if unread_only:
        query = query.filter(Post.is_read == False)  # noqa: E712
    if starred_only:
        query = query.filter(Post.is_starred == True)  # noqa: E712
    if feed_id is not None:
        query = query.filter(Post.feed_id == feed_id)
    elif category_id is not None:
        feed_ids = (
            db.query(Feed.id).filter(Feed.category_id == category_id).subquery()
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
