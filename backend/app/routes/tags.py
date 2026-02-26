"""
Ignored tags management routes.
Allows user to mark tags as irrelevant for the suggestion system.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import IgnoredTag
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
