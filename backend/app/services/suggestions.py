"""
Suggestion system for recommending posts based on user interests.
Uses tag overlap between user profile and post tags — no LLM calls.
"""

import logging
from datetime import datetime
from typing import List, Tuple

from sqlalchemy.orm import Session, joinedload

from app.models import Post, AISummary
from app.services.user_profile import get_user_profile

logger = logging.getLogger(__name__)

# Default minimum tag overlap (can be overridden in preferences)
DEFAULT_MIN_TAG_OVERLAP = 3

# Maximum candidates to process per batch
MAX_CANDIDATES_PER_BATCH = 50


def get_suggestion_candidates(
    db: Session, min_tag_overlap: int = None
) -> List[Tuple[Post, int]]:
    """
    Get posts that are potential suggestions based on tag overlap with user profile.

    Returns posts that:
    - Have an AI summary
    - Are not already suggested, read, or liked
    - Have at least min_tag_overlap tags in common with user's interest tags

    Args:
        db: Database session
        min_tag_overlap: Minimum tags in common (default: from preferences or 3)

    Returns:
        List of (Post, tag_overlap_count) tuples, sorted by overlap (highest first)
    """
    # Get minimum tag overlap from preferences if not specified
    if min_tag_overlap is None:
        from app.routes.preferences import get_effective_suggestion_min_tags

        min_tag_overlap = get_effective_suggestion_min_tags(db)

    # Get user's interest tags from profile
    profile = get_user_profile(db)
    if not profile or not profile.get("tags"):
        logger.debug("No user profile tags available for suggestions")
        return []

    profile_tags = set(t.lower() for t in profile["tags"])
    if not profile_tags:
        return []

    logger.debug(
        f"Finding candidates with min {min_tag_overlap} tags overlap (profile has {len(profile_tags)} tags)"
    )

    # Get unread posts with their tags
    # Posts must have a summary (join with AISummary)
    unread_posts = (
        db.query(Post)
        .join(AISummary, Post.content_hash == AISummary.content_hash)
        .options(joinedload(Post.tags))
        .filter(
            Post.is_suggested == 0,
            Post.is_read == 0,
            Post.is_liked == 0,  # Don't suggest posts user already liked
        )
        .all()
    )

    logger.debug(f"Found {len(unread_posts)} unread posts to check")

    # Find posts with sufficient tag overlap
    candidates = []
    for post in unread_posts:
        post_tags = {t.tag.lower() for t in post.tags}
        if not post_tags:
            continue

        common_tags = post_tags.intersection(profile_tags)
        overlap_count = len(common_tags)

        if overlap_count >= min_tag_overlap:
            candidates.append((post, overlap_count))
            logger.debug(
                f"Candidate: '{post.title[:50]}...' with {overlap_count} tags in common: {common_tags}"
            )

    # Sort by overlap count (highest first)
    candidates.sort(key=lambda x: x[1], reverse=True)

    # Limit to max candidates
    candidates = candidates[:MAX_CANDIDATES_PER_BATCH]

    logger.info(f"Found {len(candidates)} suggestion candidates")
    return candidates


def process_suggestion_candidates(db: Session) -> int:
    """
    Process suggestion candidates using tag overlap scoring.
    No LLM calls — score is based on tag overlap percentage.

    Returns:
        Number of posts marked as suggested
    """
    from app.routes.preferences import get_effective_tags_per_post

    # Get user profile
    profile = get_user_profile(db)
    if not profile or not profile.get("tags"):
        logger.info("No user profile available, skipping suggestion processing")
        return 0

    tags_per_post = get_effective_tags_per_post(db)

    # Get candidates
    candidates = get_suggestion_candidates(db)
    if not candidates:
        logger.info("No suggestion candidates found")
        return 0

    logger.info(f"Processing {len(candidates)} suggestion candidates")

    suggested_count = 0
    now = datetime.utcnow().isoformat()

    for post, overlap_count in candidates:
        # Score = percentage of tags_per_post matched by overlap
        score = min(100, round((overlap_count / tags_per_post) * 100))

        post.is_suggested = 1
        post.suggestion_score = score
        post.suggested_at = now
        suggested_count += 1
        logger.info(
            f"Suggested: '{post.title[:50]}...' (score: {score}, overlap: {overlap_count})"
        )

    db.commit()
    logger.info(f"Marked {suggested_count} posts as suggested")
    return suggested_count


def get_suggestion_stats(db: Session) -> dict:
    """
    Get statistics about the suggestion system.

    Returns:
        Dict with suggestion system statistics
    """
    from app.services.user_profile import get_liked_posts_count, is_profile_stale

    # Count suggested posts (not read)
    suggested_unread = (
        db.query(Post).filter(Post.is_suggested == 1, Post.is_read == 0).count()
    )

    # Total suggested posts
    suggested_total = db.query(Post).filter(Post.is_suggested == 1).count()

    # Get profile info
    profile = get_user_profile(db)

    return {
        "liked_count": get_liked_posts_count(db),
        "profile_ready": profile is not None,
        "profile_stale": is_profile_stale(db),
        "profile_tags_count": len(profile.get("tags", [])) if profile else 0,
        "suggested_unread": suggested_unread,
        "suggested_total": suggested_total,
        "last_profile_update": profile.get("updated_at") if profile else None,
    }
