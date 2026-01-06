"""
Admin routes.
Summary reprocessing and database maintenance.
"""

import json
import os
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import SummaryQueue, SummaryFailure, AISummary, Post

router = APIRouter(prefix="/admin", tags=["admin"])

# Path to locales directory (relative to backend)
LOCALES_DIR = Path(__file__).parent.parent.parent.parent / "htdocs" / "static" / "locales"


class ReprocessRequest(BaseModel):
    content_hash: str


@router.post("/reprocess-summary")
def reprocess_summary(
    request: ReprocessRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Requeue a summary for processing.

    - Find post by content_hash
    - Remove from summary_failures if exists
    - Remove existing summary from ai_summaries
    - Create entry in summary_queue
    """
    content_hash = request.content_hash

    # Find post with this hash
    post = db.query(Post).filter(Post.content_hash == content_hash).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No post found with this content_hash",
        )

    # Check if already in queue
    existing_queue = (
        db.query(SummaryQueue)
        .filter(SummaryQueue.content_hash == content_hash)
        .first()
    )
    if existing_queue:
        # Reset existing entry
        existing_queue.attempts = 0
        existing_queue.last_error = None
        existing_queue.error_type = None
        existing_queue.locked_at = None
        existing_queue.cooldown_until = None
        existing_queue.priority = 10  # High priority
        db.commit()
        return {"ok": True, "queued": True, "action": "reset_existing"}

    # Remove from failures if exists
    db.query(SummaryFailure).filter(
        SummaryFailure.content_hash == content_hash
    ).delete()

    # Remove existing summary (force reprocessing)
    db.query(AISummary).filter(AISummary.content_hash == content_hash).delete()

    # Create queue entry
    queue_entry = SummaryQueue(
        post_id=post.id,
        content_hash=content_hash,
        priority=10,  # High priority
    )
    db.add(queue_entry)
    db.commit()

    return {"ok": True, "queued": True, "action": "created_new"}


@router.post("/vacuum")
def vacuum_database(
    db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Execute VACUUM on SQLite database.

    - Frees space from unused pages
    - Returns bytes freed
    """
    db_path = settings.database_path

    # Get size before
    size_before = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    # Execute VACUUM (must be outside transaction)
    # SQLAlchemy 2.x requires commit first
    db.commit()

    # VACUUM cannot run inside a transaction
    connection = db.get_bind().raw_connection()
    try:
        connection.execute("VACUUM")
    finally:
        connection.close()

    # Get size after
    size_after = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    freed_bytes = size_before - size_after

    return {
        "ok": True,
        "size_before_mb": round(size_before / (1024 * 1024), 2),
        "size_after_mb": round(size_after / (1024 * 1024), 2),
        "freed_bytes": max(0, freed_bytes),
        "freed_mb": round(max(0, freed_bytes) / (1024 * 1024), 2),
    }


@router.get("/config")
def get_public_config():
    """
    Return public config for the frontend.
    Does not require authentication.
    """
    return {
        "toast_timeout_seconds": settings.toast_timeout_seconds,
        "idle_refresh_seconds": settings.idle_refresh_seconds,
    }


class LocaleInfo(BaseModel):
    code: str
    name: str


@router.get("/locales", response_model=List[LocaleInfo])
def get_available_locales():
    """
    Return list of available locales.
    Scans the locales directory and reads meta.languageName from each file.
    Does not require authentication.
    """
    locales = []

    if not LOCALES_DIR.exists():
        return locales

    for file_path in sorted(LOCALES_DIR.glob("*.json")):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                code = file_path.stem  # e.g., "pt-BR" from "pt-BR.json"
                name = data.get("meta", {}).get("languageName", code)
                locales.append(LocaleInfo(code=code, name=name))
        except (json.JSONDecodeError, IOError):
            # Skip invalid files
            continue

    return locales


@router.get("/status")
def get_status(
    db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Return detailed system status.

    Includes counters, database size, circuit breaker state, etc.
    """
    from app.models import Feed, Post, AppSettings

    # Counters
    feeds_count = db.query(Feed).count()
    posts_count = db.query(Post).count()
    unread_count = db.query(Post).filter(Post.is_read == False).count()
    queue_size = db.query(SummaryQueue).count()
    summaries_count = db.query(AISummary).count()
    failures_count = db.query(SummaryFailure).count()

    # Database size
    db_path = settings.database_path
    db_size_mb = (
        round(os.path.getsize(db_path) / (1024 * 1024), 2)
        if os.path.exists(db_path)
        else 0
    )

    # Circuit breaker
    circuit_state = "unknown"
    health_warning = None

    for row in (
        db.query(AppSettings)
        .filter(AppSettings.key.in_(["cerebras_state", "health_warning"]))
        .all()
    ):
        if row.key == "cerebras_state":
            circuit_state = row.value
        elif row.key == "health_warning":
            health_warning = row.value

    return {
        "feeds_count": feeds_count,
        "posts_count": posts_count,
        "unread_count": unread_count,
        "queue_size": queue_size,
        "summaries_count": summaries_count,
        "failures_count": failures_count,
        "circuit_breaker": circuit_state,
        "health_warning": health_warning,
        "db_size_mb": db_size_mb,
    }
