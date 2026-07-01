"""
Admin routes.
Summary reprocessing and database maintenance.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import load_prompts, settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    AISummary,
    AppSettings,
    Post,
    SummaryFailure,
    SummaryQueue,
)
from app.routes.preferences import (
    get_effective_idle_refresh,
    get_effective_toast_timeout,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

# Path to locales directory (relative to backend)
LOCALES_DIR = (
    Path(__file__).parent.parent.parent.parent / "htdocs" / "static" / "locales"
)


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
        db.query(SummaryQueue).filter(SummaryQueue.content_hash == content_hash).first()
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
def get_public_config(db: Session = Depends(get_db)):
    """
    Return public config for the frontend.
    Does not require authentication.
    """
    return {
        "toast_timeout_seconds": get_effective_toast_timeout(db),
        "idle_refresh_seconds": get_effective_idle_refresh(db),
    }


@router.get("/prompt-defaults")
def get_prompt_defaults(user: dict = Depends(get_current_user)):
    """Return default prompts from prompts.yaml (for Reset to defaults)."""
    prompts = load_prompts()
    return {
        "system_prompt": prompts.get("system_prompt", ""),
        "user_prompt": prompts.get("user_prompt", ""),
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
def get_status(db: Session = Depends(get_db), user: dict = Depends(get_current_user)):
    """
    Return detailed system status.

    Includes counters, database size, circuit breaker state, etc.
    """
    from datetime import timedelta

    from sqlalchemy import func

    from app.models import AppSettings, Feed, Post, SchedulerLock
    from app.routes.preferences import get_effective_feed_update_interval

    # Counters
    feeds_count = db.query(Feed).count()
    posts_count = db.query(Post).count()
    unread_count = db.query(Post).filter(Post.is_read.is_(False)).count()
    queue_size = db.query(SummaryQueue).count()
    unread_queue_size = (
        db.query(SummaryQueue).join(Post).filter(Post.is_read.is_(False)).count()
    )
    starred_count = db.query(Post).filter(Post.is_starred.is_(True)).count()
    summaries_count = db.query(AISummary).count()
    failures_count = db.query(SummaryFailure).count()

    # Fetching metrics
    feed_update_interval = get_effective_feed_update_interval(db)

    # Last successful fetch time
    last_fetched_val = db.query(func.max(Feed.last_fetched_at)).scalar()
    last_fetched_date = last_fetched_val.isoformat() if last_fetched_val else None

    # Check background scheduler status
    lock = db.query(SchedulerLock).filter(SchedulerLock.id == 1).first()
    scheduler_active = False
    if lock:
        # lock heartbeat is updated every 30 seconds
        scheduler_active = lock.heartbeat_at > datetime.utcnow() - timedelta(seconds=90)

    # Oldest post date
    oldest_post = db.query(Post).order_by(Post.sort_date.asc()).first()
    oldest_post_date = (
        oldest_post.published_at.isoformat()
        if oldest_post and oldest_post.published_at
        else (oldest_post.sort_date.isoformat() if oldest_post else None)
    )

    # Database size
    db_path = settings.database_path
    db_size_mb = (
        round(os.path.getsize(db_path) / (1024 * 1024), 2)
        if os.path.exists(db_path)
        else 0
    )

    # Circuit breaker
    circuit_state = "closed"
    health_warning = None

    for row in (
        db.query(AppSettings)
        .filter(AppSettings.key.in_(["ai_state", "health_warning"]))
        .all()
    ):
        if row.key == "ai_state":
            circuit_state = row.value
        elif row.key == "health_warning":
            health_warning = row.value

    return {
        "feeds_count": feeds_count,
        "posts_count": posts_count,
        "unread_count": unread_count,
        "queue_size": queue_size,
        "unread_queue_size": unread_queue_size,
        "starred_count": starred_count,
        "summaries_count": summaries_count,
        "failures_count": failures_count,
        "circuit_breaker": circuit_state,
        "health_warning": health_warning,
        "db_size_mb": db_size_mb,
        "oldest_post_date": oldest_post_date,
        "feed_update_interval": feed_update_interval,
        "last_fetched_date": last_fetched_date,
        "scheduler_active": scheduler_active,
    }


@router.get("/queue-status")
def get_queue_status(
    db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Return detailed queue status including items with cooldowns.
    Also shows API key rotator status.
    """
    from app.services.ai import api_key_rotator

    now = datetime.utcnow()

    # Queue stats
    total = db.query(SummaryQueue).count()
    in_cooldown = (
        db.query(SummaryQueue).filter(SummaryQueue.cooldown_until > now).count()
    )
    locked = db.query(SummaryQueue).filter(SummaryQueue.locked_at.isnot(None)).count()
    ready = total - in_cooldown - locked

    # Get items in cooldown (first 10)
    cooldown_items = (
        db.query(SummaryQueue)
        .filter(SummaryQueue.cooldown_until > now)
        .order_by(SummaryQueue.cooldown_until.asc())
        .limit(10)
        .all()
    )

    cooldown_list = [
        {
            "id": item.id,
            "post_id": item.post_id,
            "attempts": item.attempts,
            "last_error": item.last_error,
            "cooldown_remaining_hours": round(
                (item.cooldown_until - now).total_seconds() / 3600, 1
            ),
        }
        for item in cooldown_items
    ]

    # API key status
    api_key_status = api_key_rotator.get_status()

    return {
        "queue": {
            "total": total,
            "ready": ready,
            "in_cooldown": in_cooldown,
            "locked": locked,
            "cooldown_items": cooldown_list,
        },
        "api_keys": api_key_status,
    }


@router.post("/clear-queue-cooldowns")
def clear_queue_cooldowns(
    db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Clear all cooldowns from queue items.
    This allows stuck items to be retried immediately.
    """
    now = datetime.utcnow()

    # Count items in cooldown
    in_cooldown = (
        db.query(SummaryQueue).filter(SummaryQueue.cooldown_until > now).count()
    )

    # Clear cooldowns
    db.query(SummaryQueue).filter(SummaryQueue.cooldown_until > now).update(
        {"cooldown_until": None, "attempts": 0}
    )
    db.commit()

    return {"ok": True, "cleared": in_cooldown}


@router.post("/reset-circuit-breaker")
def reset_circuit_breaker(
    db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Reset circuit breaker, API key cooldowns, and queue cooldowns.
    """
    from app.services.ai import circuit_breaker

    # Reset circuit breaker in DB
    db.query(AppSettings).filter(
        AppSettings.key.in_(
            [
                "ai_state",
                "ai_failures",
                "ai_half_successes",
                "ai_last_failure",
                "ai_last_call",
            ]
        )
    ).delete()

    # Reset queue cooldowns
    in_cooldown = (
        db.query(SummaryQueue)
        .filter(SummaryQueue.cooldown_until > datetime.utcnow())
        .count()
    )
    db.query(SummaryQueue).update(
        {"cooldown_until": None, "attempts": 0, "locked_at": None}
    )

    db.commit()

    # Reload in-memory state
    circuit_breaker._load_state()

    return {"ok": True, "queue_cooldowns_cleared": in_cooldown}


@router.delete("/summaries/unread")
def delete_unread_summaries(
    db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Delete AI summaries for all unread posts, forcing LLM regeneration.
    Also clears their queue entries so they are re-enqueued fresh.
    """
    unread_hashes = [
        row[0]
        for row in db.query(Post.content_hash)
        .filter(Post.is_read.is_(False), Post.content_hash.isnot(None))
        .all()
    ]

    if not unread_hashes:
        return {"ok": True, "deleted": 0}

    deleted = (
        db.query(AISummary)
        .filter(AISummary.content_hash.in_(unread_hashes))
        .delete(synchronize_session=False)
    )

    # Clear queue entries so posts are re-enqueued without old error state
    db.query(SummaryQueue).filter(
        SummaryQueue.content_hash.in_(unread_hashes)
    ).delete(synchronize_session=False)

    db.commit()

    logger.info("Deleted %d AI summaries for unread posts", deleted)
    return {"ok": True, "deleted": deleted}


@router.post("/clear-models-cache")
def clear_models_cache_endpoint(
    user: dict = Depends(get_current_user),
):
    """Clear models cache and model cooldowns."""
    from app.services.ai import clear_models_cache

    clear_models_cache()
    return {"ok": True}


# =============================================================================
# AI Models and Languages
# =============================================================================


class ModelInfo(BaseModel):
    id: str
    owned_by: str


@router.get("/validate-secret")
def validate_secret(
    name: str,
    engine: str = "ondemand",
    user: dict = Depends(get_current_user),
):
    """
    Validate that a Jano secret exists and can be resolved.
    Use ?engine=background to validate against the background engine.
    Returns masked key preview so user can verify it's the right one.
    Only secrets under the app's own namespace can be probed.
    """
    # Resolve the named secret directly (not the saved preference)
    from app.services.jano_client import get_jano_secret

    # Restrict to this app's namespace — prevents probing other apps' secrets
    if not name.startswith(settings.jano_secret_prefix):
        return {"valid": False, "masked_key": None}

    try:
        val = get_jano_secret(name)
        if val and val.strip():
            key = val.strip()
            masked = key[:5] + "****" + key[-4:] if len(key) > 12 else "****"
            return {"valid": True, "masked_key": masked}
    except Exception as e:
        logger.debug("Secret validation skipped: %s", e)

    return {"valid": False, "masked_key": None}


@router.get("/models")
async def list_available_models(
    engine: str = "ondemand",
    user: dict = Depends(get_current_user),
):
    """
    Fetch available models from AI API.
    Use ?engine=background to list models from the background engine.
    Requires authentication.
    """
    from fastapi.responses import JSONResponse

    from app.routes.preferences import (
        get_effective_ai_api_key,
        get_effective_api_base_url,
        get_effective_background_ai_api_key,
        get_effective_background_api_base_url,
    )

    db = next(get_db())
    try:
        if engine == "background":
            api_key = get_effective_background_ai_api_key(db)
            api_url = get_effective_background_api_base_url(db)
        else:
            api_key = get_effective_ai_api_key(db)
            api_url = get_effective_api_base_url(db)
    finally:
        db.close()

    if not api_key:
        return JSONResponse(
            content={"error": "no_api_key", "detail": "Jano secret not resolved"},
            status_code=500,
            headers={"Cache-Control": "no-store"},
        )

    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                f"{api_url}/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if response.status_code != 200:
                return JSONResponse(
                    content={"error": "api_error", "status": response.status_code, "detail": response.text[:300], "url": f"{api_url}/models"},
                    status_code=502,
                    headers={"Cache-Control": "no-store"},
                )
            data = response.json()
            models = [
                ModelInfo(
                    id=m["id"].removeprefix("models/"),
                    owned_by=m.get("owned_by", "provider"),
                ).model_dump()
                for m in data.get("data", [])
            ]
            return JSONResponse(content=models, headers={"Cache-Control": "no-store"})
    except Exception as e:
        return JSONResponse(
            content={"error": "exception", "detail": f"{type(e).__name__}: {e}", "url": f"{api_url}/models"},
            status_code=502,
            headers={"Cache-Control": "no-store"},
        )


# Static list of target languages for AI summaries
# Key: English name (used in prompts), Value: Native name (for display)
SUMMARY_LANGUAGES = {
    "Arabic": "العربية",
    "Brazilian Portuguese": "Português (Brasil)",
    "Chinese (Simplified)": "简体中文",
    "Chinese (Traditional)": "繁體中文",
    "Dutch": "Nederlands",
    "English": "English",
    "French": "Français",
    "German": "Deutsch",
    "Hebrew": "עברית",
    "Hindi": "हिन्दी",
    "Italian": "Italiano",
    "Japanese": "日本語",
    "Korean": "한국어",
    "Polish": "Polski",
    "Portuguese": "Português",
    "Russian": "Русский",
    "Spanish": "Español",
    "Thai": "ไทย",
    "Turkish": "Türkçe",
    "Ukrainian": "Українська",
    "Vietnamese": "Tiếng Việt",
}


class LanguageInfo(BaseModel):
    code: str  # English name (used in prompts)
    name: str  # Native name (for display)


@router.get("/languages", response_model=List[LanguageInfo])
def get_summary_languages():
    """
    Return list of available target languages for AI summaries.
    Does not require authentication.
    """
    return [
        LanguageInfo(code=code, name=name)
        for code, name in sorted(SUMMARY_LANGUAGES.items(), key=lambda x: x[1])
    ]
