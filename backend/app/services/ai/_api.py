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
    DEFAULT_API_BASE_URL,
    MAX_CONTENT_LENGTH,
    MAX_ONE_LINE_LENGTH,
    MAX_TAGS,
    MODELS_FETCH_TIMEOUT,
    RATE_LIMIT_COOLDOWN_SECONDS,
    SUMMARY_TEMPERATURE,
)

# Sentinel key used for local endpoints (e.g. LM Studio) that don't require auth.
_LOCAL_API_KEY_SENTINEL = "lm-studio"


def _resolve_api_key(api_key: Optional[str], base_url: str) -> Optional[str]:
    """Return api_key, falling back to sentinel for non-default (local) endpoints."""
    if api_key:
        return api_key
    if base_url and base_url.rstrip("/") != DEFAULT_API_BASE_URL.rstrip("/"):
        return _LOCAL_API_KEY_SENTINEL
    return None
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
    RateLimited,
    SummaryResult,
    TemporaryError,
)

logger = logging.getLogger(__name__)

# Global locks: separate locks so background batch processing doesn't block on-demand calls
_api_lock_ondemand = asyncio.Lock()
_api_lock_background = asyncio.Lock()


def _get_api_base_url() -> str:
    """Get the effective API base URL from preferences."""
    from app.routes.preferences import get_effective_api_base_url

    db = SessionLocal()
    try:
        return get_effective_api_base_url(db)
    finally:
        db.close()


async def _resolve_engine_settings(engine: str) -> tuple:
    """Resolve API key, model, base URL, and timeout for the given engine.

    When saved model is "auto", fetches available models and uses the first one.
    Returns (api_key, model, base_url, timeout).
    """
    from app.routes.preferences import (
        get_effective_ai_api_key,
        get_effective_ai_model,
        get_effective_api_base_url,
        get_effective_ai_timeout,
        get_effective_background_ai_api_key,
        get_effective_background_ai_model,
        get_effective_background_api_base_url,
    )

    db = SessionLocal()
    try:
        if engine == "background":
            api_key = get_effective_background_ai_api_key(db)
            model = get_effective_background_ai_model(db)
            base_url = get_effective_background_api_base_url(db)
        else:
            api_key = get_effective_ai_api_key(db)
            model = get_effective_ai_model(db)
            base_url = get_effective_api_base_url(db)
        timeout = get_effective_ai_timeout(db)
    finally:
        db.close()

    api_key = _resolve_api_key(api_key, base_url)

    if model == "auto":
        available = await get_available_models(engine)
        model = available[0] if available else model

    return (api_key, model, base_url, timeout)


# Model cooldown: models that returned errors are paused for a grace period
_model_cooldowns: Dict[str, datetime] = {}  # model_id -> cooldown_until


def clear_models_cache():
    """Clear model cooldowns."""
    _model_cooldowns.clear()
    logger.info("Model cooldowns cleared")


async def get_available_models(engine: str = "ondemand") -> List[str]:
    """Fetch available model IDs from API. No cache — always fresh."""
    from app.routes.preferences import (
        get_effective_ai_api_key,
        get_effective_api_base_url,
        get_effective_background_ai_api_key,
        get_effective_background_api_base_url,
    )

    db = SessionLocal()
    try:
        if engine == "background":
            api_key = get_effective_background_ai_api_key(db)
            api_base = get_effective_background_api_base_url(db)
        else:
            api_key = get_effective_ai_api_key(db)
            api_base = get_effective_api_base_url(db)
    finally:
        db.close()

    api_key = _resolve_api_key(api_key, api_base)
    if not api_key:
        return []

    api_url = f"{api_base}/models"

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


def _extract_content_from_choice(choice: dict) -> str:
    """Pull the text content from any of the known OpenAI-compatible response
    shapes. Skips empty values so a reasoning model that leaves `content` null
    but fills `reasoning` still yields text."""
    message = choice.get("message", {})
    for key in ("content", "reasoning", "reasoning_content"):
        value = message.get(key)
        if value:
            return value
    for key in ("text", "content"):
        if choice.get(key):
            return choice[key]
    raise ModelSpecificError(f"Unknown response structure: {list(choice.keys())}")


def _parse_summary_result(
    content_response: str, was_truncated: bool, model: str
) -> SummaryResult:
    """Parse the JSON payload inside the LLM response into a SummaryResult."""
    result = parse_json_response(content_response)

    summary_pt = result.get("summary_pt", "").strip().replace("\\n", "\n")
    one_line = result.get("one_line_summary", "").strip().replace("\\n", "\n")

    translated_title = result.get("translated_title")
    if translated_title and isinstance(translated_title, str):
        translated_title = translated_title.strip()
        if translated_title.lower() in ("null", "none", ""):
            translated_title = None

    tags = normalize_tags(result.get("tags", []), MAX_TAGS)

    if bool(summary_pt) != bool(one_line):
        raise ValueError("Inconsistent fields (one empty, other not)")

    if len(one_line) > MAX_ONE_LINE_LENGTH:
        one_line = one_line[: MAX_ONE_LINE_LENGTH - 3] + "..."

    if summary_pt:
        last_char = summary_pt.rstrip()[-1] if summary_pt.strip() else ""
        ends_properly = last_char in ".!?:;)\"'»"
        if was_truncated or (not ends_properly and not tags):
            raise ModelSpecificError(
                f"Incomplete summary: truncated={was_truncated}, "
                f"tags={len(tags)}, ends_with='{last_char}'"
            )

    return SummaryResult(
        summary_pt=summary_pt,
        one_line_summary=one_line,
        translated_title=translated_title,
        tags=tags,
        model=model,
    )


async def _call_model(
    model: str,
    api_key: str,
    key_index: int,
    messages: list,
    timeout: int = 30,
    max_tokens: int = 8192,
    base_url: str = None,
    temperature: float = SUMMARY_TEMPERATURE,
    presence_penalty: float = 0.0,
) -> SummaryResult:
    """Make a single API call to a specific model and parse the response."""
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
    # Omitted unless explicitly set: some backends (e.g. Gemini's OpenAI-compat
    # endpoint) reject this field outright on models that don't support it.
    if presence_penalty:
        payload["presence_penalty"] = presence_penalty

    try:
        async with httpx.AsyncClient(
            timeout=timeout, headers={"User-Agent": USER_AGENT}
        ) as client:
            target_url = (base_url or _get_api_base_url()).rstrip("/")
            response = await client.post(
                f"{target_url}/chat/completions", headers=headers, json=payload
            )

            # Some backends (e.g. Gemini's OpenAI-compat endpoint) 400 outright
            # on presence_penalty for models that don't support it. Retry once
            # without it rather than failing the whole summary.
            if response.status_code == 400 and "presence_penalty" in payload:
                logger.warning(
                    "HTTP 400 with presence_penalty set (base_url=%s), "
                    "retrying without it: %s",
                    target_url, response.text[:300],
                )
                payload = {
                    k: v for k, v in payload.items() if k != "presence_penalty"
                }
                response = await client.post(
                    f"{target_url}/chat/completions", headers=headers, json=payload
                )

            if response.status_code == 429:
                retry_after = response.headers.get("retry-after", "unknown")
                logger.warning(
                    "Rate limit 429 on key %s: retry-after=%s, headers=%s",
                    key_index + 1, retry_after, dict(response.headers),
                )
                api_key_rotator.set_key_cooldown(
                    api_key, seconds=RATE_LIMIT_COOLDOWN_SECONDS
                )
                raise RateLimited(f"Rate limit reached on key {key_index + 1}")

            if response.status_code >= 500:
                raise TemporaryError(f"Server error: HTTP {response.status_code}")

            if response.status_code >= 400:
                logger.error(
                    "[API] HTTP %s from %s: %s",
                    response.status_code, target_url, response.text[:500],
                )
                raise ModelSpecificError(f"Request error: HTTP {response.status_code}")

            data = response.json()
            if "choices" not in data or not data["choices"]:
                logger.error("Response without choices: %s", data)
                raise ModelSpecificError("Empty API response")

            choice = data["choices"][0]
            was_truncated = choice.get("finish_reason") == "length"
            if was_truncated:
                logger.warning("Response truncated by API (finish_reason=length)")

            content_response = _extract_content_from_choice(choice)

            try:
                actual_model = data.get("model", model)
                if "oxit_model" in data:
                    logger.info(
                        "Proxy fallback: requested %s, used %s",
                        model, data["oxit_model"],
                    )
                return _parse_summary_result(content_response, was_truncated, actual_model)
            except (json.JSONDecodeError, ValueError) as e:
                logger.error("Error parsing response from model %s: %s", model, e)
                logger.error("Raw response: %s", content_response[:500])
                raise ModelSpecificError(f"Invalid response: {e}")

    except httpx.TimeoutException:
        raise TemporaryError(f"Timeout after {timeout}s")
    except httpx.RequestError as e:
        raise TemporaryError(f"Connection error: {e}")


async def generate_summary(
    content: str, title: str = "", title_only: bool = False, engine: str = "ondemand"
) -> SummaryResult:
    """
    Generate summary using AI API.

    Args:
        content: Article content to summarize
        title: Article title (for translation if needed)
        title_only: If True, skip garbage check (content is just the title)
        engine: "ondemand" (default) or "background" — determines which
                API key, model, and endpoint to use

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

    api_key, model, base_url, timeout = await _resolve_engine_settings(engine)
    if not api_key:
        raise TemporaryError("No API key configured")

    start_time = time.time()
    lock = _api_lock_background if engine == "background" else _api_lock_ondemand
    async with lock:
        result = await _generate_summary_locked(
            content, title, title_only,
            api_key=api_key, model=model, base_url=base_url, timeout=timeout,
        )

    # Post-process: ensure the summary body is entirely in the target language.
    # Runs outside the lock because the cleanup makes its own locked LLM call.
    # No-op (detection only) when the body is already clean.
    if result.summary_pt:
        result.summary_pt = await _enforce_summary_language(
            result.summary_pt, engine
        )

    result.duration = time.time() - start_time
    return result


async def _enforce_summary_language(summary: str, engine: str) -> str:
    """Run the language gate on a summary body using the engine's own model."""
    from app.routes.preferences import get_effective_summary_language
    from app.services.ai._constants import (
        LANGUAGE_GATE_CLEANUP_MAX_TOKENS,
        LANGUAGE_GATE_CLEANUP_TEMPERATURE,
    )
    from app.services.ai._language_gate import enforce_language

    db = SessionLocal()
    try:
        language = get_effective_summary_language(db)
    finally:
        db.close()

    async def _translate(system_prompt: str, user_prompt: str) -> str:
        return await call_llm_text(
            system_prompt,
            user_prompt,
            max_tokens=LANGUAGE_GATE_CLEANUP_MAX_TOKENS,
            temperature=LANGUAGE_GATE_CLEANUP_TEMPERATURE,
            engine=engine,
        )

    return await enforce_language(summary, language, _translate)


async def _generate_summary_locked(
    content: str, title: str, title_only: bool,
    api_key: str, model: str, base_url: str, timeout: int,
) -> SummaryResult:
    """Inner implementation, called under the appropriate lock."""
    # Truncate content if too large
    max_content_len = MAX_CONTENT_LENGTH
    if len(content) > max_content_len:
        content = content[:max_content_len] + "..."

    # Get remaining settings (not engine-specific)
    from app.routes.preferences import (
        get_effective_ai_max_tokens,
        get_effective_summary_language,
        get_effective_summary_presence_penalty,
        get_effective_summary_temperature,
    )

    db = SessionLocal()
    try:
        effective_language = get_effective_summary_language(db)
        ai_max_tokens = get_effective_ai_max_tokens(db)
        temperature = get_effective_summary_temperature(db)
        presence_penalty = get_effective_summary_presence_penalty(db)

        # Build message list (reused across model attempts).
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
        model, api_key, 0, messages, timeout, ai_max_tokens, base_url=base_url,
        temperature=temperature, presence_penalty=presence_penalty,
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
    engine: str = "ondemand",
) -> dict:
    """
    Generic LLM call expecting a JSON response.
    Used for topic suggestions, curation, etc.

    Args:
        engine: "ondemand" (default) or "background"

    Returns:
        Parsed JSON dict from the LLM response.

    Raises:
        TemporaryError: Temporary error (retry possible)
        PermanentError: Permanent error
    """
    api_key, model, base_url, timeout = await _resolve_engine_settings(engine)
    if not api_key:
        raise TemporaryError("No API key configured")

    lock = _api_lock_background if engine == "background" else _api_lock_ondemand
    async with lock:
        return await _call_llm_json_locked(
            system_prompt, user_prompt, max_tokens, temperature,
            api_key=api_key, model=model, base_url=base_url, timeout=timeout,
        )


async def _call_llm_json_locked(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    api_key: str,
    model: str,
    base_url: str,
    timeout: int,
) -> dict:
    """Inner implementation, called under the appropriate lock."""
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
        # Ask the backend to constrain output to JSON. Providers that support
        # it (OpenAI, Gemini, DeepSeek, most OpenRouter routes) stop wrapping
        # the object in prose or markdown; those that don't 400, handled below.
        "response_format": {"type": "json_object"},
    }

    target_url = base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.post(
                f"{target_url}/chat/completions",
                headers=headers,
                json=payload,
            )

            # Some models/providers reject response_format outright. Retry once
            # without it rather than failing the whole request.
            if response.status_code == 400 and "response_format" in payload:
                logger.warning(
                    "HTTP 400 with response_format set (model=%s), retrying "
                    "without it: %s",
                    model, response.text[:300],
                )
                payload = {
                    k: v for k, v in payload.items() if k != "response_format"
                }
                response = await client.post(
                    f"{target_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )

            if response.status_code == 429:
                api_key_rotator.set_key_cooldown(
                    api_key, seconds=RATE_LIMIT_COOLDOWN_SECONDS
                )
                raise RateLimited("Rate limit reached")

            if response.status_code != 200:
                raise PermanentError(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )

            data = response.json()
            content = _extract_content_from_choice(data["choices"][0])

        try:
            result = parse_json_response(content)
        except ValueError as e:
            finish = data["choices"][0].get("finish_reason")
            logger.error(
                "call_llm_json parse failure (model=%s, finish_reason=%s): %s\n"
                "Raw response: %s",
                data.get("model", model), finish, e, (content or "")[:800],
            )
            hint = (
                " — response was truncated (raise the token limit or pick a "
                "model with a larger output budget)"
                if finish == "length"
                else " — the model did not return valid JSON"
            )
            raise PermanentError(f"LLM returned unparseable JSON{hint}")

        actual_model = data.get("model", model)
        if "oxit_model" in data:
            logger.info(f"Proxy fallback: requested {model}, used {data['oxit_model']}")
        logger.info(f"call_llm_json succeeded with model {actual_model}")
        return result

    except (TemporaryError, PermanentError):
        raise
    except Exception as e:
        raise PermanentError(f"LLM call failed: {e}")


async def call_llm_text(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    engine: str = "ondemand",
) -> str:
    """
    Generic LLM call returning plain text content.
    Used for general summaries, consolidation, etc.

    Args:
        engine: "ondemand" (default) or "background"
    """
    api_key, model, base_url, timeout = await _resolve_engine_settings(engine)
    if not api_key:
        raise TemporaryError("No API key configured")

    lock = _api_lock_background if engine == "background" else _api_lock_ondemand
    async with lock:
        return await _call_llm_text_locked(
            system_prompt, user_prompt, max_tokens, temperature,
            api_key=api_key, model=model, base_url=base_url, timeout=timeout,
        )


async def _call_llm_text_locked(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    temperature: float,
    api_key: str,
    model: str,
    base_url: str,
    timeout: int,
) -> str:
    """Inner implementation of call_llm_text, called under the appropriate lock."""
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

    target_url = base_url.rstrip("/")

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            response = await client.post(
                f"{target_url}/chat/completions",
                headers=headers,
                json=payload,
            )

            if response.status_code == 429:
                api_key_rotator.set_key_cooldown(
                    api_key, seconds=RATE_LIMIT_COOLDOWN_SECONDS
                )
                raise RateLimited("Rate limit reached")

            if response.status_code != 200:
                raise PermanentError(
                    f"HTTP {response.status_code}: {response.text[:200]}"
                )

            data = response.json()
            content = _extract_content_from_choice(data["choices"][0])

        actual_model = data.get("model", model)
        if "oxit_model" in data:
            logger.info(f"Proxy fallback: requested {model}, used {data['oxit_model']}")
        logger.info(f"call_llm_text succeeded with model {actual_model}")
        return content

    except (TemporaryError, PermanentError):
        raise
    except Exception as e:
        raise PermanentError(f"LLM call failed: {e}")

