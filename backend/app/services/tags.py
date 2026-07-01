"""
Tag management for the post suggestions system.
"""

import logging
from typing import List

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import PostTag

logger = logging.getLogger(__name__)


def apply_tag_merge(db: Session, source: str, canonical: str) -> int:
    """Merge *source* tag into *canonical* across all tables that reference tags.

    - post_tags: delete rows where the same post already has both tags, then
      rename remaining source → canonical.
    - topic_tags: same dedup-then-rename.
    - ignored_tags: delete source (the canonical may or may not be in
      ignored_tags; we don't touch it).

    Returns the number of post_tags rows updated (0 if the source didn't
    exist at all).  The caller owns the transaction — this function does NOT
    commit.
    """
    # --- post_tags ---
    db.execute(
        text(
            "DELETE FROM post_tags WHERE tag = :source "
            "AND post_id IN ("
            "  SELECT post_id FROM post_tags WHERE tag = :canonical"
            ")"
        ),
        {"source": source, "canonical": canonical},
    )
    result = db.execute(
        text("UPDATE post_tags SET tag = :canonical WHERE tag = :source"),
        {"source": source, "canonical": canonical},
    )
    posts_affected = result.rowcount

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

    return posts_affected


def save_post_tags(db: Session, post_id: int, tags: List[str]) -> int:
    """
    Save tags for a post, replacing any existing tags.

    Args:
        db: Database session
        post_id: The post ID to save tags for
        tags: List of tag strings (should already be normalized)

    Returns:
        Number of tags saved
    """
    if not tags:
        return 0

    # Delete existing tags for this post (in case of regeneration)
    db.query(PostTag).filter(PostTag.post_id == post_id).delete()

    # Insert new tags
    count = 0
    seen = set()
    for tag in tags:
        # Normalize and dedupe
        tag = tag.lower().strip().replace(" ", "-").replace("_", "-")
        while "--" in tag:
            tag = tag.replace("--", "-")
        tag = tag.strip("-")
        if tag and tag not in seen and len(tag) <= 50:
            seen.add(tag)
            db.add(PostTag(post_id=post_id, tag=tag))
            count += 1

    # Don't commit here - let the caller handle the transaction
    return count
