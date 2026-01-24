"""
Tag management for the post suggestions system.
"""

import logging
from typing import List

from sqlalchemy.orm import Session

from app.models import PostTag

logger = logging.getLogger(__name__)


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
        tag = tag.lower().strip()
        if tag and tag not in seen and len(tag) <= 50:
            seen.add(tag)
            db.add(PostTag(post_id=post_id, tag=tag))
            count += 1

    # Don't commit here - let the caller handle the transaction
    return count
