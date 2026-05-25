"""
Shared utilities for batch-processing scripts.

Provides:
- log()                  — flushed print with optional timestamp
- compute_content_hash() — SHA-256 content hash for dedup
- clear_rate_limits()    — reset Cerebras circuit breaker + key cooldowns
- regenerate_one()       — regenerate summary/tags for a single post
- run_batch_loop()       — batch processing loop with delay + counting
"""

import hashlib
import time
from datetime import datetime

from app.models import AISummary, PostTag
from app.services.ai import (
    circuit_breaker,
    generate_summary,
    GarbageContentError,
)
from app.services.ai._infrastructure import api_key_rotator
from app.services.tags import save_post_tags


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
def log(msg, timestamp=False):
    """Print with immediate flush for background execution."""
    if timestamp:
        ts = time.strftime("%H:%M:%S")
        print(f"[{ts}] {msg}", flush=True)
    else:
        print(msg, flush=True)


# ---------------------------------------------------------------------------
# Content hashing
# ---------------------------------------------------------------------------
def compute_content_hash(content, title="", url=""):
    raw = f"{title}|{url}|{content[:500]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Rate limit management
# ---------------------------------------------------------------------------
def clear_rate_limits():
    """Reset circuit breaker timing and clear all key cooldowns."""
    circuit_breaker.last_call = None
    circuit_breaker._save_state()
    for key in api_key_rotator._get_keys():
        api_key_rotator.clear_cooldown(key)


# ---------------------------------------------------------------------------
# Single post regeneration
# ---------------------------------------------------------------------------
async def regenerate_one(
    db, post, use_local=False, delete_existing_tags=False
):
    """
    Regenerate summary and tags for a single post.

    Args:
        db: SQLAlchemy session
        post: Post model instance
        use_local: Use Ollama instead of Cerebras
        delete_existing_tags: Delete existing tags before regenerating
            (True for starred/force mode, False for tagless/unread)

    Returns:
        (success: bool, called_api: bool)
    """
    content = post.full_content or post.content
    if not content or len(content.strip()) < 100:
        post.skip_summary = True
        db.commit()
        log(f"  #{post.id}: SKIP (insufficient content, marked skip_summary)")
        return False, False

    if delete_existing_tags:
        db.query(PostTag).filter(PostTag.post_id == post.id).delete()
        db.commit()

    try:
        if use_local:
            from app.services.ollama import generate_summary_local

            result = await generate_summary_local(
                content, title=post.title, db=db
            )
        else:
            result = await generate_summary(content, title=post.title)
    except GarbageContentError as e:
        post.skip_summary = True
        db.commit()
        log(f"  #{post.id}: SKIP ({e})")
        return False, True
    except Exception as e:
        log(f"  #{post.id}: ERROR ({e})")
        return False, True

    # Save summary
    content_hash = compute_content_hash(content, post.title, post.url)
    if post.content_hash != content_hash:
        post.content_hash = content_hash

    if post.skip_summary:
        post.skip_summary = False

    summary_text = result.get_summary_with_signature()

    existing = (
        db.query(AISummary)
        .filter(AISummary.content_hash == content_hash)
        .first()
    )
    if existing:
        existing.summary_pt = summary_text
        existing.one_line_summary = result.one_line_summary
        existing.translated_title = result.translated_title
        existing.created_at = datetime.utcnow()
    else:
        db.add(
            AISummary(
                content_hash=content_hash,
                summary_pt=summary_text,
                one_line_summary=result.one_line_summary,
                translated_title=result.translated_title,
            )
        )

    if result.tags:
        save_post_tags(db, post.id, result.tags)

    db.commit()
    tags_str = ", ".join(result.tags) if result.tags else "(none)"
    log(f"  #{post.id}: OK [{result.model}] tags=[{tags_str}]")
    return True, True


# ---------------------------------------------------------------------------
# Batch processing loop
# ---------------------------------------------------------------------------
INTERNAL_BATCH_SIZE = 6  # Posts per visual batch group


async def run_batch_loop(
    db, posts, use_local=False, delay=20, delete_existing_tags=False
):
    """
    Process a list of posts in batches, with delay between API calls.

    Returns:
        (success_count, skip_count, error_count)
    """
    import asyncio

    total = len(posts)
    success_count = 0
    skip_count = 0
    error_count = 0

    for batch_start in range(0, total, INTERNAL_BATCH_SIZE):
        batch = posts[batch_start : batch_start + INTERNAL_BATCH_SIZE]
        batch_num = batch_start // INTERNAL_BATCH_SIZE + 1
        total_batches = (
            total + INTERNAL_BATCH_SIZE - 1
        ) // INTERNAL_BATCH_SIZE
        log(
            f"--- Batch {batch_num}/{total_batches} ({success_count} OK so far) ---"
        )

        last_called_api = False
        for post in batch:
            if not use_local:
                circuit_breaker.last_call = None
                circuit_breaker._save_state()

            if last_called_api:
                await asyncio.sleep(delay)

            ok, called_api = await regenerate_one(
                db,
                post,
                use_local=use_local,
                delete_existing_tags=delete_existing_tags,
            )
            last_called_api = called_api
            if ok:
                success_count += 1
            elif post.skip_summary:
                skip_count += 1
            else:
                error_count += 1

        log("")

    return success_count, skip_count, error_count
