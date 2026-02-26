"""
User profile generation for the recommendation system.
Analyzes liked posts to create a profile of user interests using tag aggregation.
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Post, PostTag, AppSettings, IgnoredTag

logger = logging.getLogger(__name__)

# Minimum liked posts required to generate profile
MIN_LIKED_POSTS = 10


def get_setting(db: Session, key: str) -> Optional[str]:
    """Get a setting value from app_settings."""
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    return row.value if row else None


def set_setting(db: Session, key: str, value: str):
    """Set a setting value in app_settings."""
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    if row:
        row.value = value
        row.updated_at = datetime.utcnow()
    else:
        db.add(AppSettings(key=key, value=value))


def get_user_profile(db: Session) -> Optional[Dict]:
    """
    Get the current user profile from settings.

    Returns:
        Dict with 'profile' (text) and 'tags' (list) or None if not generated
    """
    profile = get_setting(db, "user_interest_profile")
    tags_json = get_setting(db, "user_interest_tags")

    if not profile or not tags_json:
        return None

    try:
        tags = json.loads(tags_json)
    except json.JSONDecodeError:
        tags = []

    return {
        "profile": profile,
        "tags": tags,
        "updated_at": get_setting(db, "user_profile_updated_at"),
    }


def invalidate_user_profile(db: Session):
    """
    Mark the user profile as stale, triggering regeneration on next job run.
    Call this when likes change.
    """
    set_setting(db, "user_profile_stale", "1")
    db.commit()
    logger.debug("User profile marked as stale")


def is_profile_stale(db: Session) -> bool:
    """Check if the profile needs regeneration."""
    return get_setting(db, "user_profile_stale") == "1"


def get_liked_posts_count(db: Session) -> int:
    """Get count of liked posts."""
    return db.query(Post).filter(Post.is_liked == 1).count()


def generate_user_profile(db: Session) -> Optional[Dict]:
    """
    Generate user interest profile based on tags from liked posts.
    Uses tag frequency aggregation — no LLM calls.

    Returns:
        Dict with 'profile' and 'tags', or None if not enough data
    """
    liked_count = get_liked_posts_count(db)
    if liked_count < MIN_LIKED_POSTS:
        logger.info(
            f"Not enough liked posts for profile: {liked_count}/{MIN_LIKED_POSTS}"
        )
        return None

    # Aggregate all unique tags from liked posts by frequency
    tag_counts = (
        db.query(PostTag.tag, func.count(PostTag.tag).label("cnt"))
        .join(Post, PostTag.post_id == Post.id)
        .filter(Post.is_liked == 1)
        .group_by(PostTag.tag)
        .order_by(func.count(PostTag.tag).desc())
        .all()
    )

    if not tag_counts:
        logger.info("No tags found for liked posts")
        return None

    # Filter out ignored tags
    ignored = {row.tag for row in db.query(IgnoredTag.tag).all()}
    tag_counts = [row for row in tag_counts if row.tag.lower() not in ignored]

    if not tag_counts:
        logger.info("All liked post tags are ignored")
        return None

    tags = [row.tag.lower() for row in tag_counts]
    profile_text = "User interests: " + ", ".join(tags)

    # Save to settings
    set_setting(db, "user_interest_profile", profile_text)
    set_setting(db, "user_interest_tags", json.dumps(tags))
    set_setting(db, "user_profile_updated_at", datetime.utcnow().isoformat())
    set_setting(db, "user_profile_stale", "0")
    db.commit()

    logger.info(f"User profile generated with {len(tags)} interest tags")

    return {
        "profile": profile_text,
        "tags": tags,
    }
