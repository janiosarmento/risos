#!/usr/bin/env python3
"""
Regenerate summaries for the N most recent posts without tags.
Processes in batches with circuit breaker reset and key rotation.
"""

import asyncio
import hashlib
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import not_

from app.database import SessionLocal
from app.models import AISummary, Post, PostTag
from app.services.cerebras import circuit_breaker, generate_summary
from app.services.cerebras._infrastructure import api_key_rotator
from app.services.tags import save_post_tags


BATCH_SIZE = 6
TOTAL_POSTS = 48
DELAY_BETWEEN_CALLS = 20  # seconds between calls to avoid rate limits


def log(msg):
    """Print with immediate flush for background execution."""
    print(msg, flush=True)


def compute_content_hash(content, title="", url=""):
    raw = f"{title}|{url}|{content[:500]}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def clear_rate_limits():
    """Reset circuit breaker timing and clear all key cooldowns."""
    circuit_breaker.last_call = None
    circuit_breaker._save_state()
    for key in api_key_rotator._get_keys():
        api_key_rotator.clear_cooldown(key)


async def regenerate_one(db, post):
    """Regenerate summary for a single post. Returns True on success."""
    content = post.full_content or post.content
    if not content or len(content.strip()) < 100:
        log(f"  #{post.id}: SKIP (insufficient content)")
        return False

    try:
        result = await generate_summary(content, title=post.title)
    except Exception as e:
        log(f"  #{post.id}: ERROR ({e})")
        return False

    # Save summary
    content_hash = compute_content_hash(content, post.title, post.url)
    if post.content_hash != content_hash:
        post.content_hash = content_hash

    existing = (
        db.query(AISummary)
        .filter(AISummary.content_hash == content_hash)
        .first()
    )

    summary_text = result.summary_pt
    if summary_text and result.model:
        summary_text += f"\n\n— {result.model}"

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
    return True


async def main():
    db = SessionLocal()

    # Find posts without tags, most recent first
    posts_with_tags = db.query(PostTag.post_id).distinct()
    posts = (
        db.query(Post)
        .filter(not_(Post.id.in_(posts_with_tags)))
        .order_by(Post.id.desc())
        .limit(TOTAL_POSTS)
        .all()
    )

    log(f"Found {len(posts)} posts without tags to process\n")

    # Clear all rate limits at start
    clear_rate_limits()

    success_count = 0
    skip_count = 0
    error_count = 0

    for batch_start in range(0, len(posts), BATCH_SIZE):
        batch = posts[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(posts) + BATCH_SIZE - 1) // BATCH_SIZE
        log(f"--- Batch {batch_num}/{total_batches} ---")

        for i, post in enumerate(batch):
            # Reset circuit breaker before each call
            circuit_breaker.last_call = None
            circuit_breaker._save_state()

            if i > 0:
                await asyncio.sleep(DELAY_BETWEEN_CALLS)

            ok = await regenerate_one(db, post)
            if ok:
                success_count += 1
            elif not (post.full_content or post.content) or len(
                (post.full_content or post.content or "").strip()
            ) < 100:
                skip_count += 1
            else:
                error_count += 1

        log("")

    db.close()
    log(
        f"Done! Success: {success_count}, "
        f"Skipped: {skip_count}, "
        f"Errors: {error_count}"
    )


if __name__ == "__main__":
    asyncio.run(main())
