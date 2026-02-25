"""
Cerebras client for AI summary generation.
API calls, tag translation, model fallback, and orchestration.
"""

import json
import logging
from datetime import datetime
from typing import Optional, List

import httpx

from app.config import settings
from app.database import SessionLocal
from app.services.cerebras._types import (
    CerebrasError,
    TemporaryError,
    PermanentError,
    ModelSpecificError,
    SummaryResult,
)
from app.services.cerebras._constants import (
    CEREBRAS_API_URL,
    MODELS_CACHE_TTL,
    MODELS_FETCH_TIMEOUT,
    TAG_TRANSLATION_MODEL,
    TAG_TRANSLATION_TEMPERATURE,
    TAG_TRANSLATION_MAX_TOKENS,
    TAG_TRANSLATION_TIMEOUT,
    SUMMARY_TEMPERATURE,
    SUMMARY_MAX_TOKENS,
    MAX_CONTENT_LENGTH,
    MAX_ONE_LINE_LENGTH,
    MAX_TAGS,
    RATE_LIMIT_COOLDOWN_SECONDS,
)
from app.services.cerebras._parsing import (
    is_garbage_content,  # noqa: F401
    normalize_tags,
    normalize_tag,
    parse_json_response,
)
from app.services.cerebras._infrastructure import (  # noqa: F401
    api_key_rotator,
    circuit_breaker,
)


from app.services.cerebras._prompts import get_system_prompt, get_user_prompt  # noqa: F401

logger = logging.getLogger(__name__)


# Cache for available models (shared with admin routes)
_available_models_cache: Optional[List[str]] = None
_available_models_cache_time: Optional[datetime] = None


async def get_available_models() -> List[str]:
    """Fetch available model IDs from Cerebras API (cached 30 min)."""
    global _available_models_cache, _available_models_cache_time

    now = datetime.utcnow()
    if _available_models_cache and _available_models_cache_time:
        if now - _available_models_cache_time < MODELS_CACHE_TTL:
            return _available_models_cache

    api_keys = api_key_rotator._get_keys()
    if not api_keys:
        return []

    try:
        async with httpx.AsyncClient(timeout=MODELS_FETCH_TIMEOUT) as client:
            response = await client.get(
                "https://api.cerebras.ai/v1/models",
                headers={"Authorization": f"Bearer {api_keys[0]}"},
            )
            if response.status_code == 200:
                data = response.json()
                models = [m["id"] for m in data.get("data", [])]
                _available_models_cache = models
                _available_models_cache_time = now
                return models
    except Exception as e:
        logger.warning(f"Failed to fetch available models: {e}")

    return _available_models_cache or []


async def _translate_tags(tags: list, api_key: str, key_index: int) -> list:
    """
    Translate non-English tags to English using a fast, small model.
    Returns translated tags or original tags on failure.
    """
    if not tags:
        return tags

    tags_str = ", ".join(tags)
    messages = [
        {"role": "system", "content": "You translate tags to English. Reply with ONLY the comma-separated translated tags, nothing else."},
        {"role": "user", "content": f"Translate these tags to English (keep brand names, proper nouns, and already-English tags exactly as-is; use lowercase hyphens): {tags_str}"},
    ]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": TAG_TRANSLATION_MODEL,
        "messages": messages,
        "temperature": TAG_TRANSLATION_TEMPERATURE,
        "max_tokens": TAG_TRANSLATION_MAX_TOKENS,
    }

    try:
        async with httpx.AsyncClient(timeout=TAG_TRANSLATION_TIMEOUT) as client:
            response = await client.post(CEREBRAS_API_URL, headers=headers, json=payload)
            if response.status_code != 200:
                logger.warning(f"Tag translation failed: HTTP {response.status_code}")
                return tags

            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            translated = [normalize_tag(t) for t in content.split(",")]
            # Basic validation: similar count, no empty
            translated = [t for t in translated if t]
            if len(translated) >= len(tags) // 2:
                logger.info(f"Tags translated: [{tags_str}] -> [{', '.join(translated)}]")
                return translated
            else:
                logger.warning(f"Tag translation gave too few results: {len(translated)} from {len(tags)}")
                return tags
    except Exception as e:
        logger.warning(f"Tag translation error: {e}")
        return tags


async def _call_model(
    model: str, api_key: str, key_index: int, messages: list
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

    # Minimize reasoning tokens for thinking models
    if "gpt-oss" in model:
        payload["reasoning_effort"] = "low"

    try:
        async with httpx.AsyncClient(
            timeout=settings.cerebras_timeout
        ) as client:
            response = await client.post(
                CEREBRAS_API_URL,
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
                api_key_rotator.set_key_cooldown(api_key, seconds=RATE_LIMIT_COOLDOWN_SECONDS)
                raise TemporaryError(
                    f"Rate limit reached on key {key_index + 1}"
                )

            # Handle server errors
            if response.status_code >= 500:
                circuit_breaker.record_failure()
                raise TemporaryError(
                    f"Server error: HTTP {response.status_code}"
                )

            # Handle client errors
            if response.status_code >= 400:
                raise ModelSpecificError(
                    f"Request error: HTTP {response.status_code}"
                )

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
                logger.warning(
                    "Response truncated by API (finish_reason=length)"
                )

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

                # Non gpt-oss models often generate tags in the summary language;
                # use a cheap llama call to translate them to English
                if tags and "gpt-oss" not in model:
                    tags = await _translate_tags(tags, api_key, key_index)

                # Allow both empty (error pages) or both filled
                if bool(summary_pt) != bool(one_line):
                    raise ValueError(
                        "Inconsistent fields (one empty, other not)"
                    )

                # Truncate one_line if needed
                if len(one_line) > MAX_ONE_LINE_LENGTH:
                    one_line = one_line[:MAX_ONE_LINE_LENGTH - 3] + "..."

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

                circuit_breaker.record_success()

                return SummaryResult(
                    summary_pt=summary_pt,
                    one_line_summary=one_line,
                    translated_title=translated_title,
                    tags=tags,
                    model=model,  # Use requested model (API response field is unreliable)
                )

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Error parsing response from model {model}: {e}")
                logger.error(f"Raw response: {content_response[:500]}")
                raise ModelSpecificError(f"Invalid response: {e}")

    except httpx.TimeoutException:
        circuit_breaker.record_failure()
        raise TemporaryError(f"Timeout after {settings.cerebras_timeout}s")

    except httpx.RequestError as e:
        circuit_breaker.record_failure()
        raise TemporaryError(f"Connection error: {e}")


async def generate_summary(content: str, title: str = "", title_only: bool = False) -> SummaryResult:
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
        logger.info(
            "Content detected as error/session page, returning empty"
        )
        return SummaryResult(
            summary_pt="", one_line_summary="", translated_title=None
        )

    # Check circuit breaker
    can_call, reason = circuit_breaker.can_call()
    if not can_call:
        raise TemporaryError(f"Circuit breaker: {reason}")

    # Get next available API key (load balancing)
    api_key, key_index = api_key_rotator.get_next_key()
    if not api_key:
        raise TemporaryError("All API keys are in cooldown")

    # Truncate content if too large
    max_content_len = MAX_CONTENT_LENGTH
    if len(content) > max_content_len:
        content = content[:max_content_len] + "..."

    # Get effective settings
    from app.routes.preferences import (
        get_effective_summary_language,
        get_effective_cerebras_model,
    )

    db = SessionLocal()
    try:
        preferred_model = get_effective_cerebras_model(db)
        effective_language = get_effective_summary_language(db)

        # Build message list (reused across model attempts)
        messages = [
            {"role": "system", "content": get_system_prompt(db)},
            {"role": "user", "content": get_user_prompt(content, title, effective_language, db)},
        ]
    finally:
        db.close()

    # Build model list: preferred first, then others as fallback
    models_to_try = [preferred_model]
    try:
        available = await get_available_models()
        for m in available:
            if m != preferred_model:
                models_to_try.append(m)
    except Exception:
        pass  # If we can't fetch models, just try the preferred one

    last_error = None
    for model in models_to_try:
        try:
            result = await _call_model(model, api_key, key_index, messages)
            if model != preferred_model:
                logger.info(
                    f"Fallback model {result.model} succeeded "
                    f"(preferred {preferred_model} failed)"
                )
            return result

        except ModelSpecificError as e:
            logger.warning(
                f"Model {model} failed: {e}"
                + (f", trying next model..." if model != models_to_try[-1] else "")
            )
            last_error = e
            continue

        except (TemporaryError, PermanentError):
            # Infrastructure errors — don't try other models
            raise

    # All models failed with model-specific errors
    circuit_breaker.record_failure()
    raise PermanentError(f"All models failed. Last error: {last_error}")
