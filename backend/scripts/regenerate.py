#!/usr/bin/env python3
"""
Regenerate summaries and tags for posts.

Usage:
    python scripts/regenerate.py                          # tagless posts (default)
    python scripts/regenerate.py --starred                # ALL starred (force re-gen)
    python scripts/regenerate.py --unread                 # unread without tags
    python scripts/regenerate.py --unread --starred       # unread OR starred, without tags
    python scripts/regenerate.py --local                  # use Ollama
    python scripts/regenerate.py --batch-size 200         # limit total posts
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import not_, or_

from app.database import SessionLocal
from app.models import Post, PostTag
from scripts.lib import clear_rate_limits, log, run_batch_loop

DELAY_CEREBRAS = 20
DELAY_LOCAL = 1
DEFAULT_BATCH_SIZE = 100


def parse_args():
    parser = argparse.ArgumentParser(description="Regenerate summaries/tags for posts.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Max posts to process (default: 100)",
    )
    parser.add_argument(
        "--unread",
        action="store_true",
        help="Only unread posts (without tags)",
    )
    parser.add_argument(
        "--starred",
        action="store_true",
        help="Only starred posts (alone = force re-gen ALL starred; "
        "with --unread = starred OR unread without tags)",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Use local Ollama model instead of Cerebras",
    )
    return parser.parse_args()


async def main():
    args = parse_args()
    db = SessionLocal()

    starred_only = args.starred and not args.unread
    delete_existing_tags = starred_only

    if starred_only:
        # --starred alone: ALL starred posts, force re-generate
        posts = (
            db.query(Post)
            .filter(Post.is_starred == True)  # noqa: E712
            .order_by(Post.starred_at.desc())
            .limit(args.batch_size)
            .all()
        )
        mode_desc = "starred (force re-gen)"
    else:
        # Default / --unread / --unread --starred: posts WITHOUT tags
        posts_with_tags = db.query(PostTag.post_id).distinct()
        query = db.query(Post).filter(
            not_(Post.id.in_(posts_with_tags)),
            Post.skip_summary == False,  # noqa: E712
        )

        filters = []
        if args.unread:
            filters.append(Post.is_read == False)  # noqa: E712
        if args.starred:
            filters.append(Post.is_starred == True)  # noqa: E712
        if filters:
            query = query.filter(or_(*filters))

        posts = query.order_by(Post.id.desc()).limit(args.batch_size).all()

        if args.unread and args.starred:
            mode_desc = "unread OR starred, without tags"
        elif args.unread:
            mode_desc = "unread, without tags"
        else:
            mode_desc = "without tags"

    engine = "local/Ollama" if args.local else "Cerebras"
    log(f"Found {len(posts)} posts to process ({mode_desc}, {engine})\n")

    if not posts:
        db.close()
        return

    delay = DELAY_LOCAL if args.local else DELAY_CEREBRAS

    if not args.local:
        clear_rate_limits()

    success, skipped, errors = await run_batch_loop(
        db,
        posts,
        use_local=args.local,
        delay=delay,
        delete_existing_tags=delete_existing_tags,
    )

    db.close()
    log(f"Done! Success: {success}, Skipped: {skipped}, Errors: {errors}")


if __name__ == "__main__":
    asyncio.run(main())
