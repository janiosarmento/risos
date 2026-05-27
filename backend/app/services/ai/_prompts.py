"""Prompt construction for the Cerebras client."""

import logging
import time
from datetime import datetime
from typing import List, Optional

from app.config import load_prompts

logger = logging.getLogger(__name__)

# In-memory cache for popular tags
_popular_tags_cache: Optional[List[str]] = None
_popular_tags_cache_time: float = 0
_POPULAR_TAGS_TTL = 3600  # 1 hour


def _get_popular_tags(db, limit: int = 200) -> List[str]:
    """Return the most frequent tags, cached in memory for 1 hour."""
    global _popular_tags_cache, _popular_tags_cache_time

    now = time.monotonic()
    if (
        _popular_tags_cache is not None
        and (now - _popular_tags_cache_time) < _POPULAR_TAGS_TTL
    ):
        return _popular_tags_cache

    from sqlalchemy import func

    from app.models import PostTag

    rows = (
        db.query(PostTag.tag)
        .group_by(PostTag.tag)
        .order_by(func.count(PostTag.post_id).desc())
        .limit(limit)
        .all()
    )
    tags = [row.tag for row in rows]
    _popular_tags_cache = tags
    _popular_tags_cache_time = now
    logger.info("Refreshed popular tags cache: %d tags", len(tags))
    return tags


def get_system_prompt(db=None) -> str:
    """Returns the system prompt from DB settings or prompts.yaml fallback."""
    if db:
        from app.routes.preferences import get_effective_system_prompt

        return get_effective_system_prompt(db)
    prompts = load_prompts()
    return prompts.get(
        "system_prompt",
        "You are a helpful assistant that summarizes articles.",
    )


def get_user_prompt(
    content: str, title: str = "", language: str = None, db=None
) -> str:
    """
    Returns the user prompt with content, title, language, and date interpolated.
    Reads template from DB settings or prompts.yaml fallback.
    If language is not provided, uses "Brazilian Portuguese" as fallback.
    """
    if db:
        from app.routes.preferences import (
            get_effective_tags_per_post,
            get_effective_user_prompt,
        )

        template = get_effective_user_prompt(db)
        tags_count = get_effective_tags_per_post(db)
    else:
        prompts = load_prompts()
        template = prompts.get(
            "user_prompt", "Summarize this article in {language}:\n\n{content}"
        )
        tags_count = 7
    prompt = template.format(
        language=language or "Brazilian Portuguese",
        content=content,
        title=title or "Untitled",
        date=datetime.now().strftime("%Y-%m-%d"),
        tags_count=tags_count,
    )

    # Always append tag language enforcement (models ignore it when buried in system prompt)
    prompt += (
        "\n\nIMPORTANT: All tags MUST be in English, using lowercase hyphens "
        '(e.g. "open-source", "artificial-intelligence"). '
        "NEVER use tags in other languages."
        "\n\nStrongly prefer SHORT, broad tags (1-2 words) over long compound tags. "
        'For example, use "ai" instead of "artificial-intelligence-ethics", '
        '"privacy" instead of "data-privacy-regulations", '
        '"security" instead of "cybersecurity-vulnerabilities". '
        "Only use multi-word tags when a single word would be too ambiguous."
    )

    # Inject popular existing tags to encourage reuse
    if db:
        popular = _get_popular_tags(db)
        if popular:
            tags_str = ", ".join(popular)
            prompt += (
                "\n\nPREFERRED TAGS — reuse these when they fit the article's topics "
                "(only create a new tag if none of these adequately describe a topic):\n"
                f"{tags_str}"
            )

    return prompt
