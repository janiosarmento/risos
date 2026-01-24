"""
Suggestion system for recommending posts based on user interests.
Uses tag overlap for pre-filtering and AI comparison for final scoring.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

from sqlalchemy.orm import Session, joinedload

from app.models import Post, AISummary, PostTag
from app.services.user_profile import get_setting, set_setting, get_user_profile

logger = logging.getLogger(__name__)

# Minimum tag overlap to consider a post as candidate
MIN_TAG_OVERLAP = 3

# Maximum candidates to process per batch
MAX_CANDIDATES_PER_BATCH = 50

# How far back to look for posts (hours)
CANDIDATE_WINDOW_HOURS = 24


def get_suggestion_candidates(db: Session) -> List[Tuple[Post, int]]:
    """
    Get posts that are potential suggestions based on tag overlap with user profile.

    Returns posts that:
    - Were fetched in the last 24 hours
    - Have an AI summary
    - Are not already suggested
    - Are not read
    - Have at least MIN_TAG_OVERLAP tags in common with user's interest tags

    Returns:
        List of (Post, tag_overlap_count) tuples, sorted by overlap (highest first)
    """
    # Get user's interest tags from profile
    profile = get_user_profile(db)
    if not profile or not profile.get("tags"):
        logger.debug("No user profile tags available for suggestions")
        return []

    profile_tags = set(t.lower() for t in profile["tags"])
    if not profile_tags:
        return []

    logger.debug(f"Finding candidates with overlap to {len(profile_tags)} profile tags")

    # Calculate time threshold
    time_threshold = (datetime.utcnow() - timedelta(hours=CANDIDATE_WINDOW_HOURS)).isoformat()

    # Get recent posts with their tags
    # Posts must have a summary (join with AISummary)
    recent_posts = (
        db.query(Post)
        .join(AISummary, Post.content_hash == AISummary.content_hash)
        .options(joinedload(Post.tags))
        .filter(
            Post.fetched_at > time_threshold,
            Post.is_suggested == 0,
            Post.is_read == 0,
            Post.is_liked == 0,  # Don't suggest posts user already liked
        )
        .all()
    )

    logger.debug(f"Found {len(recent_posts)} recent unread posts to check")

    # Find posts with sufficient tag overlap
    candidates = []
    for post in recent_posts:
        post_tags = {t.tag.lower() for t in post.tags}
        if not post_tags:
            continue

        common_tags = post_tags.intersection(profile_tags)
        overlap_count = len(common_tags)

        if overlap_count >= MIN_TAG_OVERLAP:
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


def get_candidates_for_ai_comparison(db: Session) -> List[Post]:
    """
    Get candidate posts ready for AI comparison.
    This is a simpler interface that just returns the posts.

    Returns:
        List of Post objects that are candidates for suggestions
    """
    candidates = get_suggestion_candidates(db)
    return [post for post, _ in candidates]


async def process_suggestion_candidates(db: Session) -> int:
    """
    Process suggestion candidates using AI comparison.

    Gets candidates with tag overlap, sends them to AI for scoring,
    and marks posts with score >= 80 as suggested.

    Returns:
        Number of posts marked as suggested
    """
    from app.config import load_prompts
    from app.services.cerebras import (
        api_key_rotator,
        circuit_breaker,
        _parse_json_response,
        CEREBRAS_API_URL,
    )
    from app.routes.preferences import get_effective_cerebras_model
    import httpx

    # Get user profile
    profile = get_user_profile(db)
    if not profile or not profile.get("profile"):
        logger.info("No user profile available, skipping suggestion processing")
        return 0

    # Get candidates
    candidates = get_suggestion_candidates(db)
    if not candidates:
        logger.info("No suggestion candidates found")
        return 0

    logger.info(f"Processing {len(candidates)} suggestion candidates")

    # Load prompt
    prompts = load_prompts()
    comparison_prompt = prompts.get("comparison_prompt", "")
    if not comparison_prompt:
        logger.error("comparison_prompt not found in prompts.yaml")
        return 0

    # Format articles for the prompt (need to get one_line_summary from AISummary)
    articles_parts = []
    for post, overlap in candidates:
        summary = db.query(AISummary).filter(
            AISummary.content_hash == post.content_hash
        ).first()
        one_line = summary.one_line_summary if summary else "No summary"
        articles_parts.append(f"ID: {post.id}\nTitle: {post.title}\nSummary: {one_line}")

    articles_text = "\n---\n".join(articles_parts)

    # Check circuit breaker
    can_call, reason = circuit_breaker.can_call()
    if not can_call:
        logger.warning(f"Cannot process suggestions: {reason}")
        return 0

    # Get API key
    api_key, key_index = api_key_rotator.get_next_key()
    if not api_key:
        logger.warning("Cannot process suggestions: all API keys in cooldown")
        return 0

    # Prepare request
    effective_model = get_effective_cerebras_model(db)

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": effective_model,
        "messages": [
            {
                "role": "user",
                "content": comparison_prompt.format(
                    profile=profile["profile"],
                    articles=articles_text
                )
            },
        ],
        "temperature": 0.3,
        "max_tokens": 2000,
    }

    try:
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                CEREBRAS_API_URL,
                headers=headers,
                json=payload,
            )

            if response.status_code == 429:
                api_key_rotator.set_key_cooldown(api_key, seconds=300)
                logger.warning("Rate limit hit during suggestion processing")
                return 0

            if response.status_code >= 400:
                circuit_breaker.record_failure()
                logger.error(f"API error during suggestion processing: {response.status_code}")
                return 0

            data = response.json()

            if "choices" not in data or not data["choices"]:
                logger.error("Empty response during suggestion processing")
                return 0

            content = data["choices"][0].get("message", {}).get("content", "")
            result = _parse_json_response(content)

            circuit_breaker.record_success()

        # Process matches
        matches = result.get("matches", [])
        suggested_count = 0
        now = datetime.utcnow().isoformat()

        for match in matches:
            post_id = match.get("id")
            score = match.get("score", 0)

            if not post_id or score < 80:
                continue

            post = db.query(Post).filter(Post.id == post_id).first()
            if post and not post.is_suggested:
                post.is_suggested = 1
                post.suggestion_score = score
                post.suggested_at = now
                suggested_count += 1
                logger.info(
                    f"Suggested: '{post.title[:50]}...' (score: {score})"
                )

        db.commit()
        logger.info(f"Marked {suggested_count} posts as suggested")
        return suggested_count

    except Exception as e:
        logger.error(f"Error processing suggestions: {e}")
        return 0


def get_suggestion_stats(db: Session) -> dict:
    """
    Get statistics about the suggestion system.

    Returns:
        Dict with suggestion system statistics
    """
    from app.services.user_profile import get_liked_posts_count, is_profile_stale

    # Count suggested posts (not read)
    suggested_unread = (
        db.query(Post)
        .filter(Post.is_suggested == 1, Post.is_read == 0)
        .count()
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
