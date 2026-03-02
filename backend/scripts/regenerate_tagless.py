#!/usr/bin/env python3
"""
Regenerate summaries for the N most recent posts without tags.
Processes in batches with circuit breaker reset and key rotation.
Skips posts marked as skip_summary.

Usage:
    python scripts/regenerate_tagless.py                    # Cerebras, all posts
    python scripts/regenerate_tagless.py --local            # Ollama local model
    python scripts/regenerate_tagless.py --unread --starred  # Only unread/starred
    python scripts/regenerate_tagless.py --local --batch-size 500
"""

import argparse
import asyncio
import hashlib
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import not_, or_

from app.database import SessionLocal
from app.models import AISummary, Post, PostTag
from app.services.cerebras import circuit_breaker, generate_summary, GarbageContentError
from app.services.cerebras._infrastructure import api_key_rotator
from app.services.tags import save_post_tags


BATCH_SIZE = 6
TOTAL_POSTS = 100
DELAY_BETWEEN_CALLS = 20  # seconds between Cerebras calls to avoid rate limits
DELAY_LOCAL = 1  # seconds between local calls (no rate limit, just breathing room)


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


async def regenerate_one(db, post, use_local=False):
    """Regenerate summary for a single post. Returns True on success."""
    content = post.full_content or post.content
    if not content or len(content.strip()) < 100:
        post.skip_summary = True
        db.commit()
        log(f"  #{post.id}: SKIP (insufficient content, marked skip_summary)")
        return False

    try:
        if use_local:
            from app.services.ollama import generate_summary_local

            result = await generate_summary_local(content, title=post.title, db=db)
        else:
            result = await generate_summary(content, title=post.title)
    except GarbageContentError as e:
        post.skip_summary = True
        db.commit()
        log(f"  #{post.id}: SKIP ({e})")
        return False
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


def parse_args():
    parser = argparse.ArgumentParser(description="Regenerate summaries/tags for posts without tags.")
    parser.add_argument("--batch-size", type=int, default=TOTAL_POSTS, help="Max posts to process")
    parser.add_argument("--unread", action="store_true", help="Only unread posts")
    parser.add_argument("--starred", action="store_true", help="Only starred posts")
    parser.add_argument("--local", action="store_true", help="Use local Ollama model instead of Cerebras")
    return parser.parse_args()


async def main():
    args = parse_args()
    db = SessionLocal()

    # Find posts without tags, excluding skipped, most recent first
    posts_with_tags = db.query(PostTag.post_id).distinct()
    query = db.query(Post).filter(
        not_(Post.id.in_(posts_with_tags)),
        Post.skip_summary == False,  # noqa: E712
    )

    # Apply optional filters (OR logic: unread OR starred)
    filters = []
    if args.unread:
        filters.append(Post.is_read == False)  # noqa: E712
    if args.starred:
        filters.append(Post.is_starred == True)  # noqa: E712
    if filters:
        query = query.filter(or_(*filters))

    posts = query.order_by(Post.id.desc()).limit(args.batch_size).all()

    parts = []
    if args.local:
        parts.append("local/Ollama")
    if args.unread and args.starred:
        parts.append("unread OR starred")
    elif args.unread:
        parts.append("unread only")
    elif args.starred:
        parts.append("starred only")
    filter_desc = f" ({', '.join(parts)})" if parts else ""

    log(f"Found {len(posts)} posts without tags to process{filter_desc}\n")

    if not posts:
        db.close()
        return

    delay = DELAY_LOCAL if args.local else DELAY_BETWEEN_CALLS

    # Only reset Cerebras rate limits when using Cerebras
    if not args.local:
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
            if not args.local:
                # Reset circuit breaker before each Cerebras call
                circuit_breaker.last_call = None
                circuit_breaker._save_state()

            if i > 0:
                await asyncio.sleep(delay)

            ok = await regenerate_one(db, post, use_local=args.local)
            if ok:
                success_count += 1
            elif post.skip_summary:
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
