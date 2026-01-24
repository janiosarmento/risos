"""
User profile generation for the recommendation system.
Analyzes liked posts to create a profile of user interests.
"""

import json
import logging
from datetime import datetime
from typing import Optional, Dict, List

from sqlalchemy.orm import Session

from app.models import Post, AISummary, AppSettings

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


async def generate_user_profile(db: Session) -> Optional[Dict]:
    """
    Generate user interest profile based on liked posts.

    Returns:
        Dict with 'profile' and 'tags', or None if not enough data
    """
    from app.services.cerebras import generate_summary, TemporaryError, PermanentError
    from app.config import load_prompts

    # Get liked posts with summaries (most recent first)
    liked_posts = (
        db.query(Post, AISummary)
        .join(AISummary, Post.content_hash == AISummary.content_hash)
        .filter(Post.is_liked == 1)
        .order_by(Post.liked_at.desc())
        .limit(50)
        .all()
    )

    if len(liked_posts) < MIN_LIKED_POSTS:
        logger.info(
            f"Not enough liked posts for profile: {len(liked_posts)}/{MIN_LIKED_POSTS}"
        )
        return None

    # Build summaries text
    summaries_list = []
    for post, summary in liked_posts:
        summaries_list.append(
            f"Title: {post.title}\nSummary: {summary.summary_pt}"
        )
    summaries_text = "\n---\n".join(summaries_list)

    # Load prompt
    prompts = load_prompts()
    profile_prompt = prompts.get("profile_prompt", "")

    if not profile_prompt:
        logger.error("profile_prompt not found in prompts.yaml")
        return None

    # Call Cerebras API
    try:
        from app.services.cerebras import (
            api_key_rotator,
            circuit_breaker,
            _parse_json_response,
            CEREBRAS_API_URL,
        )
        from app.routes.preferences import get_effective_cerebras_model
        import httpx

        # Check circuit breaker
        can_call, reason = circuit_breaker.can_call()
        if not can_call:
            logger.warning(f"Cannot generate profile: {reason}")
            return None

        # Get API key
        api_key, key_index = api_key_rotator.get_next_key()
        if not api_key:
            logger.warning("Cannot generate profile: all API keys in cooldown")
            return None

        # Prepare request
        effective_model = get_effective_cerebras_model(db)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": effective_model,
            "messages": [
                {"role": "user", "content": profile_prompt.format(summaries=summaries_text)},
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
        }

        logger.info(f"Generating user profile from {len(liked_posts)} liked posts...")

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                CEREBRAS_API_URL,
                headers=headers,
                json=payload,
            )

            if response.status_code == 429:
                api_key_rotator.set_key_cooldown(api_key, seconds=300)
                logger.warning("Rate limit hit during profile generation")
                return None

            if response.status_code >= 400:
                circuit_breaker.record_failure()
                logger.error(f"API error during profile generation: {response.status_code}")
                return None

            data = response.json()

            if "choices" not in data or not data["choices"]:
                logger.error("Empty response during profile generation")
                return None

            content = data["choices"][0].get("message", {}).get("content", "")
            result = _parse_json_response(content)

            circuit_breaker.record_success()

        profile_text = result.get("profile", "").strip()
        tags = result.get("tags", [])

        # Normalize tags
        if isinstance(tags, list):
            tags = [t.lower().strip() for t in tags if isinstance(t, str) and t.strip()]
        else:
            tags = []

        if not profile_text:
            logger.error("Empty profile generated")
            return None

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

    except Exception as e:
        logger.error(f"Error generating user profile: {e}")
        return None
