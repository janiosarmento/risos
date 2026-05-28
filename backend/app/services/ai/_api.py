"""
Cerebras client for AI summary generation.
API calls, tag translation, model fallback, and orchestration.
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

import httpx

from app.config import USER_AGENT
from app.database import SessionLocal
from app.services.ai._constants import (
    MAX_CONTENT_LENGTH,
    MAX_ONE_LINE_LENGTH,
    MAX_TAGS,
    MODELS_FETCH_TIMEOUT,
    RATE_LIMIT_COOLDOWN_SECONDS,
    SUMMARY_MAX_TOKENS,
    SUMMARY_TEMPERATURE,
)
from app.services.ai._infrastructure import (  # noqa: F401
    api_key_rotator,
)
from app.services.ai._parsing import (
    is_garbage_content,  # noqa: F401
    normalize_tags,
    parse_json_response,
)
from app.services.ai._prompts import (
    get_system_prompt,
    get_user_prompt,
)  # noqa: F401
from app.services.ai._types import (
    GarbageContentError,
    ModelSpecificError,
    PermanentError,
    SummaryResult,
    TemporaryError,
)

logger = logging.getLogger(__name__)

# Global lock: only one AI API call at a time (LM Studio limitation)
_api_lock = asyncio.Lock()


def _get_api_base_url() -> str:
    """Get the effective API base URL from preferences."""
    from app.routes.preferences import get_effective_api_base_url

    db = SessionLocal()
    try:
        return get_effective_api_base_url(db)
    finally:
        db.close()


# Model cooldown: models that returned errors are paused for a grace period
_model_cooldowns: Dict[str, datetime] = {}  # model_id -> cooldown_until


def clear_models_cache():
    """Clear model cooldowns."""
    _model_cooldowns.clear()
    logger.info("Model cooldowns cleared")


async def get_available_models() -> List[str]:
    """Fetch available model IDs from API. No cache — always fresh."""
    from app.routes.preferences import get_effective_ai_api_key

    db = SessionLocal()
    try:
        api_key = get_effective_ai_api_key(db)
    finally:
        db.close()

    if not api_key:
        return []

    api_url = f"{_get_api_base_url()}/models"

    try:
        async with httpx.AsyncClient(
            timeout=MODELS_FETCH_TIMEOUT,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.get(
                api_url,
                headers={"Authorization": f"Bearer {api_key}"},
            )
            if response.status_code == 200:
                data = response.json()
                return [m["id"] for m in data.get("data", [])]
            else:
                logger.error(f"Failed to fetch models: HTTP {response.status_code}")
    except Exception as e:
        logger.warning(f"Failed to fetch available models: {e}")

    return []


async def _call_model(
    model: str, api_key: str, key_index: int, messages: list, timeout: int = 30
) -> SummaryResult:
    """
    Make a single API call to a specific model and parse the response.

    Raises:
        TemporaryError: Infrastructure error (rate limit, timeout, server error)
        ModelSpecificError: Error likely caused by the model (bad response format)
        PermanentError: Other permanent errors
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "messages": messages,
        "temperature": SUMMARY_TEMPERATURE,
        "max_tokens": SUMMARY_MAX_TOKENS,
    }

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.post(
                f"{_get_api_base_url()}/chat/completions",
                headers=headers,
                json=payload,
            )

            # Handle rate limit (cooldown specific to this key, does not affect circuit breaker)
            if response.status_code == 429:
                retry_after = response.headers.get("retry-after", "unknown")
                logger.warning(
                    f"Rate limit 429 on key {key_index + 1}: "
                    f"retry-after={retry_after}, "
                    f"headers={dict(response.headers)}"
                )
                api_key_rotator.set_key_cooldown(
                    api_key, seconds=RATE_LIMIT_COOLDOWN_SECONDS
                )
                raise TemporaryError(f"Rate limit reached on key {key_index + 1}")

            # Handle server errors
            if response.status_code >= 500:
                raise TemporaryError(f"Server error: HTTP {response.status_code}")

            # Handle client errors
            if response.status_code >= 400:
                import sys

                print(
                    f"[API] HTTP {response.status_code} "
                    f"from {_get_api_base_url()}: "
                    f"{response.text[:500]}",
                    flush=True,
                    file=sys.stderr,
                )
                raise ModelSpecificError(f"Request error: HTTP {response.status_code}")

            # Parse response
            data = response.json()
            logger.debug(f"API response keys: {data.keys()}")

            if "choices" not in data or not data["choices"]:
                logger.error(f"Response without choices: {data}")
                raise ModelSpecificError("Empty API response")

            choice = data["choices"][0]
            logger.debug(f"Choice keys: {choice.keys()}")

            # Check if response was truncated
            was_truncated = choice.get("finish_reason") == "length"
            if was_truncated:
                logger.warning("Response truncated by API (finish_reason=length)")

            # Try different response structures
            message = choice.get("message", {})
            if "content" in message:
                content_response = message["content"]
            elif "reasoning" in message:
                content_response = message["reasoning"]
            elif "text" in choice:
                content_response = choice["text"]
            elif "content" in choice:
                content_response = choice["content"]
            else:
                logger.error(f"Unknown response structure: {choice}")
                raise ModelSpecificError(
                    f"Unknown response structure: {list(choice.keys())}"
                )

            # Parse JSON from response
            try:
                result = parse_json_response(content_response)

                summary_pt = result.get("summary_pt", "").strip()
                one_line = result.get("one_line_summary", "").strip()
                translated_title = result.get("translated_title")

                # Fix double-escaped newlines
                summary_pt = summary_pt.replace("\\n", "\n")
                one_line = one_line.replace("\\n", "\n")

                # Clean translated_title if "null" string or empty
                if translated_title and isinstance(translated_title, str):
                    translated_title = translated_title.strip()
                    if translated_title.lower() in ("null", "none", ""):
                        translated_title = None

                # Extract and normalize tags
                tags = normalize_tags(result.get("tags", []), MAX_TAGS)

                # Allow both empty (error pages) or both filled
                if bool(summary_pt) != bool(one_line):
                    raise ValueError("Inconsistent fields (one empty, other not)")

                # Truncate one_line if needed
                if len(one_line) > MAX_ONE_LINE_LENGTH:
                    one_line = one_line[: MAX_ONE_LINE_LENGTH - 3] + "..."

                # Detect incomplete/truncated summaries
                if summary_pt:
                    last_char = summary_pt.rstrip()[-1] if summary_pt.strip() else ""
                    ends_properly = last_char in ".!?:;)\"'»"
                    if was_truncated or (not ends_properly and not tags):
                        raise ModelSpecificError(
                            f"Incomplete summary: "
                            f"truncated={was_truncated}, "
                            f"tags={len(tags)}, "
                            f"ends_with='{last_char}'"
                        )

                # Use actual model from response (proxy may fallback)
                actual_model = data.get("model", model)
                if "oxit_model" in data:
                    logger.info(
                        f"Proxy fallback: requested {model}, used {data['oxit_model']}"
                    )

                return SummaryResult(
                    summary_pt=summary_pt,
                    one_line_summary=one_line,
                    translated_title=translated_title,
                    tags=tags,
                    model=actual_model,
                )

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Error parsing response from model {model}: {e}")
                logger.error(f"Raw response: {content_response[:500]}")
                raise ModelSpecificError(f"Invalid response: {e}")

    except httpx.TimeoutException:
        raise TemporaryError(f"Timeout after {timeout}s")

    except httpx.RequestError as e:
        raise TemporaryError(f"Connection error: {e}")


async def generate_summary(
    content: str, title: str = "", title_only: bool = False
) -> SummaryResult:
    """
    Generate summary using Cerebras API with model fallback.

    Tries the user's preferred model first. If it fails with a model-specific
    error (bad response format, unknown structure), falls back to other
    available models. Infrastructure errors (rate limit, timeout) are NOT
    retried with different models.

    Args:
        content: Article content to summarize
        title: Article title (for translation if needed)
        title_only: If True, skip garbage check (content is just the title)

    Returns:
        SummaryResult with summaries

    Raises:
        TemporaryError: Temporary error (retry possible)
        PermanentError: Permanent error (do not retry)
    """
    # Check if content is garbage (error, session, paywall)
    if not title_only and is_garbage_content(content):
        raise GarbageContentError("Content detected as error/session page")

    import time

    start_time = time.time()
    async with _api_lock:
        result = await _generate_summary_locked(content, title, title_only)
    result.duration = time.time() - start_time
    return result


async def _generate_summary_locked(
    content: str, title: str, title_only: bool
) -> SummaryResult:
    """Inner implementation, called under _api_lock."""
    # Get API key
    api_key, key_index = api_key_rotator.get_next_key()
    if not api_key:
        raise TemporaryError("No API key configured")

    # Truncate content if too large
    max_content_len = MAX_CONTENT_LENGTH
    if len(content) > max_content_len:
        content = content[:max_content_len] + "..."

    # Get effective settings
    from app.routes.preferences import (
        get_effective_ai_model,
        get_effective_ai_timeout,
        get_effective_summary_language,
    )

    db = SessionLocal()
    try:
        preferred_model = get_effective_ai_model(db)
        effective_language = get_effective_summary_language(db)
        ai_timeout = get_effective_ai_timeout(db)

        # Build message list (reused across model attempts).
        # System content uses array format so Anthropic prompt caching works.
        # LiteLLM flattens this to a plain string for non-Anthropic backends.
        messages = [
            {
                "role": "system",
                "content": [
                    {
                        "type": "text",
                        "text": get_system_prompt(db),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
            },
            {
                "role": "user",
                "content": get_user_prompt(content, title, effective_language, db),
            },
        ]
    finally:
        db.close()

    # Use preferred model only (proxy handles fallback)
    result = await _call_model(
        preferred_model, api_key, key_index, messages, ai_timeout
    )

    # Empty result means the model deemed the content unusable
    if not result.summary_pt and not result.tags:
        raise GarbageContentError("Model returned empty result (unusable content)")

    return result


async def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> dict:
    """
    Generic LLM call expecting a JSON response.
    Used for topic suggestions, curation, etc.

    Returns:
        Parsed JSON dict from the LLM response.

    Raises:
        TemporaryError: Temporary error (retry possible)
        PermanentError: Permanent error
    """
    async with _api_lock:
        return await _call_llm_json_locked(
            system_prompt, user_prompt, max_tokens, temperature
        )


async def _call_llm_json_locked(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
) -> dict:
    """Inner implementation, called under _api_lock."""
    # Get API key
    api_key, key_index = api_key_rotator.get_next_key()
    if not api_key:
        raise TemporaryError("No API key configured")

    # Get preferred model (proxy handles fallback)
    from app.routes.preferences import get_effective_ai_model, get_effective_ai_timeout

    db = SessionLocal()
    try:
        model = get_effective_ai_model(db)
        ai_timeout = get_effective_ai_timeout(db)
    finally:
        db.close()

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    try:
        async with httpx.AsyncClient(
            timeout=ai_timeout,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.post(
                f"{_get_api_base_url()}/chat/completions",
                headers=headers,
                json=payload,
            )

            if response.status_code == 429:
                api_key_rotator.set_key_cooldown(
                    api_key, seconds=RATE_LIMIT_COOLDOWN_SECONDS
                )
                raise TemporaryError("Rate limit reached")

            if response.status_code != 200:
                raise PermanentError(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )

            data = response.json()
            content = data["choices"][0]["message"]["content"]

        result = parse_json_response(content)
        actual_model = data.get("model", model)
        if "oxit_model" in data:
            logger.info(f"Proxy fallback: requested {model}, used {data['oxit_model']}")
        logger.info(f"call_llm_json succeeded with model {actual_model}")
        return result

    except (TemporaryError, PermanentError):
        raise
    except Exception as e:
        raise PermanentError(f"LLM call failed: {e}")
