"""
Cerebras client for AI summary generation.
Includes circuit breaker, rate limiting and API key load balancing.
"""

import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Tuple, Dict

import httpx

from app.config import load_prompts, settings
from app.database import SessionLocal
from app.models import AppSettings

logger = logging.getLogger(__name__)

# Configuration
CEREBRAS_API_URL = "https://api.cerebras.ai/v1/chat/completions"


class ApiKeyRotator:
    """
    API key rotator with round-robin and per-key cooldown.
    Persists current index in the database.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._key_cooldowns: Dict[str, datetime] = {}  # key -> cooldown_until
        self._current_index = 0
        self._load_state()

    def _load_state(self):
        """Load current index from database."""
        db = SessionLocal()
        try:
            row = (
                db.query(AppSettings)
                .filter(AppSettings.key == "api_key_index")
                .first()
            )
            if row:
                saved_index = int(row.value)
                # Apply modulo in case number of keys changed
                num_keys = len(settings.cerebras_api_keys)
                if num_keys > 0:
                    self._current_index = saved_index % num_keys
                else:
                    self._current_index = 0
                logger.info(
                    f"API key rotator loaded: index={self._current_index}, "
                    f"total_keys={num_keys}"
                )
        finally:
            db.close()

    def _save_state(self):
        """Save current index to database."""
        db = SessionLocal()
        try:
            existing = (
                db.query(AppSettings)
                .filter(AppSettings.key == "api_key_index")
                .first()
            )
            if existing:
                existing.value = str(self._current_index)
            else:
                db.add(
                    AppSettings(
                        key="api_key_index", value=str(self._current_index)
                    )
                )
            db.commit()
        except Exception as e:
            logger.error(f"Error saving API key index: {e}")
            db.rollback()
        finally:
            db.close()

    def get_next_key(self) -> Tuple[Optional[str], Optional[int]]:
        """
        Return the next available API key (round-robin).
        Skips keys in cooldown.

        Returns:
            Tuple of (api_key, key_index) or (None, None) if none available
        """
        keys = settings.cerebras_api_keys
        if not keys:
            return None, None

        now = datetime.utcnow()

        with self._lock:
            # Try to find an available key
            for _ in range(len(keys)):
                key_index = self._current_index
                key = keys[key_index]

                # Advance to next (round-robin)
                self._current_index = (self._current_index + 1) % len(keys)

                # Check cooldown
                cooldown_until = self._key_cooldowns.get(key)
                if cooldown_until and now < cooldown_until:
                    remaining = (cooldown_until - now).total_seconds()
                    logger.debug(
                        f"Key {key_index + 1}/{len(keys)} in cooldown"
                        f"({remaining:.0f}s)"
                    )
                    continue

                # Key available
                self._save_state()
                logger.info(f"Using API key {key_index + 1}/{len(keys)}")
                return key, key_index

            # All keys in cooldown
            return None, None

    def set_key_cooldown(self, key: str, seconds: int = 60):
        """Put a key in cooldown after rate limit."""
        with self._lock:
            self._key_cooldowns[key] = datetime.utcnow() + timedelta(
                seconds=seconds
            )
            keys = settings.cerebras_api_keys
            if key in keys:
                key_index = keys.index(key) + 1
                logger.warning(
                    f"API key {key_index}/{len(keys)} in cooldown for "
                    f"{seconds}s"
                )

    def clear_cooldown(self, key: str):
        """Remove cooldown from a key."""
        with self._lock:
            self._key_cooldowns.pop(key, None)

    def get_status(self) -> dict:
        """Return status of all keys."""
        keys = settings.cerebras_api_keys
        now = datetime.utcnow()
        status = {
            "total_keys": len(keys),
            "current_index": self._current_index % len(keys) if keys else 0,
            "keys": [],
        }
        for i, key in enumerate(keys):
            cooldown_until = self._key_cooldowns.get(key)
            key_status = {
                "index": i + 1,
                "available": not (cooldown_until and now < cooldown_until),
            }
            if cooldown_until and now < cooldown_until:
                key_status["cooldown_remaining"] = int(
                    (cooldown_until - now).total_seconds()
                )
            status["keys"].append(key_status)
        return status


# Global rotator instance
api_key_rotator = ApiKeyRotator()


class CircuitState(Enum):
    CLOSED = "closed"  # Normal, allowing calls
    OPEN = "open"  # Blocked after many failures
    HALF = "half"  # Testing if service recovered


class CerebrasError(Exception):
    """Base Cerebras client error."""

    pass


class TemporaryError(CerebrasError):
    """Temporary error (timeout, 429, 5xx)."""

    pass


class PermanentError(CerebrasError):
    """Permanent error (invalid payload, empty response after retries)."""

    pass


@dataclass
class SummaryResult:
    """Summary generation result."""

    summary_pt: str
    one_line_summary: str
    translated_title: str = (
        None  # Translated title (if not in target language)
    )


class CircuitBreaker:
    """
    Circuit breaker to protect against API failures.

    States:
    - CLOSED: Normal, allowing calls
    - OPEN: Blocked after FAILURE_THRESHOLD failures
    - HALF: Testing after RECOVERY_TIMEOUT_SECONDS
    """

    def __init__(self):
        self._load_state()

    def _load_state(self):
        """Load state from database."""
        db = SessionLocal()
        try:
            self.state = CircuitState.CLOSED
            self.failures = 0
            self.half_successes = 0
            self.last_failure = None
            self.last_call = None

            # Load from database
            for row in (
                db.query(AppSettings)
                .filter(
                    AppSettings.key.in_(
                        [
                            "cerebras_state",
                            "cerebras_failures",
                            "cerebras_half_successes",
                            "cerebras_last_failure",
                            "cerebras_last_call",
                        ]
                    )
                )
                .all()
            ):
                if row.key == "cerebras_state":
                    self.state = CircuitState(row.value)
                elif row.key == "cerebras_failures":
                    self.failures = int(row.value)
                elif row.key == "cerebras_half_successes":
                    self.half_successes = int(row.value)
                elif row.key == "cerebras_last_failure":
                    self.last_failure = datetime.fromisoformat(row.value)
                elif row.key == "cerebras_last_call":
                    self.last_call = datetime.fromisoformat(row.value)

        finally:
            db.close()

    def _save_state(self):
        """Save state to database."""
        db = SessionLocal()
        try:
            updates = {
                "cerebras_state": self.state.value,
                "cerebras_failures": str(self.failures),
                "cerebras_half_successes": str(self.half_successes),
            }

            if self.last_failure:
                updates["cerebras_last_failure"] = (
                    self.last_failure.isoformat()
                )
            if self.last_call:
                updates["cerebras_last_call"] = self.last_call.isoformat()

            for key, value in updates.items():
                existing = (
                    db.query(AppSettings)
                    .filter(AppSettings.key == key)
                    .first()
                )
                if existing:
                    existing.value = value
                else:
                    db.add(AppSettings(key=key, value=value))

            db.commit()

        except Exception as e:
            logger.error(f"Error saving circuit breaker state: {e}")
            db.rollback()
        finally:
            db.close()

    def can_call(self) -> Tuple[bool, Optional[str]]:
        """
        Check if API call can be made.

        Returns:
            Tuple of (can_call, reason_if_not)
        """
        now = datetime.utcnow()

        # Note: Per-key rate limit is managed by ApiKeyRotator
        # Circuit breaker only blocks on actual API failures

        # Check minimum interval
        min_interval = 60.0 / settings.cerebras_max_rpm
        if self.last_call:
            elapsed = (now - self.last_call).total_seconds()
            if elapsed < min_interval:
                return (
                    False,
                    "Waiting for minimum interval "
                    f"({min_interval - elapsed:.1f}s)",
                )

        # Check circuit breaker
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure:
                elapsed = (now - self.last_failure).total_seconds()
                if elapsed >= settings.recovery_timeout_seconds:
                    # Transition to HALF
                    self.state = CircuitState.HALF
                    self.half_successes = 0
                    self._save_state()
                    logger.info("Circuit breaker: OPEN -> HALF")
                else:
                    return (
                        False,
                        "Circuit breaker OPEN (recovery in "
                        f"{settings.recovery_timeout_seconds - elapsed:.0f}s)",
                    )

        return True, None

    def record_success(self):
        """Record successful call."""
        now = datetime.utcnow()
        self.last_call = now

        if self.state == CircuitState.HALF:
            self.half_successes += 1
            if self.half_successes >= settings.half_open_max_requests:
                # Transition to CLOSED
                self.state = CircuitState.CLOSED
                self.failures = 0
                logger.info("Circuit breaker: HALF -> CLOSED")
        else:
            self.failures = 0

        self._save_state()

    def record_failure(self):
        """
        Record call failure (server errors, timeout, etc).
        Note: Rate limits (429) are managed by ApiKeyRotator, not here.
        """
        now = datetime.utcnow()
        self.last_call = now
        self.last_failure = now

        if self.state == CircuitState.HALF:
            # One failure in HALF reopens the circuit
            self.state = CircuitState.OPEN
            logger.warning("Circuit breaker: HALF -> OPEN (failure)")
        else:
            self.failures += 1
            if self.failures >= settings.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker: CLOSED -> OPEN "
                    f"({self.failures} failures)"
                )

        self._save_state()


# Global circuit breaker instance
circuit_breaker = CircuitBreaker()


def get_system_prompt() -> str:
    """Returns the system prompt from prompts.yaml (loaded dynamically)."""
    prompts = load_prompts()
    return prompts.get(
        "system_prompt",
        "You are a helpful assistant that summarizes articles.",
    )


def get_user_prompt(content: str, title: str = "", language: str = None) -> str:
    """
    Returns the user prompt with content, title, and language interpolated.
    Prompts are loaded dynamically from prompts.yaml.
    If language is not provided, uses settings.summary_language as fallback.
    """
    prompts = load_prompts()
    template = prompts.get(
        "user_prompt", "Summarize this article in {language}:\n\n{content}"
    )
    return template.format(
        language=language or settings.summary_language,
        content=content,
        title=title or "Untitled",
    )


def _parse_json_response(content: str) -> dict:
    """
    Parse JSON response robustly.
    Handles markdown code blocks, incorrect escapes, etc.
    """

    # Remove markdown code blocks if present
    # Pattern: ```json ... ``` or ``` ... ```
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", content)
    if code_block_match:
        content = code_block_match.group(1)

    # Try direct parse first
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # Try to extract JSON from within text
    json_start = content.find("{")
    json_end = content.rfind("}") + 1

    if json_start < 0 or json_end <= json_start:
        raise ValueError("JSON not found in response")

    json_str = content[json_start:json_end]

    # Try parse
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # Try to fix common escape issues
    # Literal newlines inside strings
    json_str_fixed = json_str

    # Replace real newlines inside strings with \n
    # This is a hack but helps with some models
    def fix_string_newlines(match):
        s = match.group(0)
        # Replace real newlines with escape
        s = s.replace("\n", "\\n").replace("\r", "\\r")
        return s

    # Find JSON strings and fix
    json_str_fixed = re.sub(r'"[^"]*"', fix_string_newlines, json_str)

    try:
        return json.loads(json_str_fixed)
    except json.JSONDecodeError:
        pass

    # Last attempt: extract fields manually with regex
    summary_match = re.search(
        r'"summary_pt"\s*:\s*"((?:[^"\\]|\\.)*)"|"summary_pt"\s*:\s*"([^"]*)"',
        json_str,
        re.DOTALL,
    )
    one_line_match = re.search(
        r'"one_line_summary"\s*:\s*"((?:[^"\\]|\\.)*)"|"one_line_summary"\s*:\s*"([^"]*)"',
        json_str,
        re.DOTALL,
    )

    if summary_match and one_line_match:
        summary = summary_match.group(1) or summary_match.group(2) or ""
        one_line = one_line_match.group(1) or one_line_match.group(2) or ""
        # Decode basic escapes
        summary = (
            summary.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace('\\"', '"')
        )
        one_line = (
            one_line.replace("\\n", "\n")
            .replace("\\r", "\r")
            .replace('\\"', '"')
        )
        return {"summary_pt": summary, "one_line_summary": one_line}

    raise ValueError(f"Could not parse JSON: {json_str[:200]}...")


# Patterns that indicate error/garbage pages (no real content)
GARBAGE_PATTERNS = [
    # GitHub session errors
    "reload to refresh your session",
    "you signed in with another tab",
    "you signed out in another tab",
    "you switched accounts on another tab",
    "you can't perform that action at this time",
    "octocat-spinner",
    # Common error pages
    "access denied",
    "403 forbidden",
    "404 not found",
    "500 internal server error",
    "502 bad gateway",
    "503 service unavailable",
    "page not found",
    # Paywalls/login walls
    "subscribe to continue reading",
    "create an account to continue",
    "sign in to continue",
    "this content is for subscribers only",
    # Cookie/GDPR walls
    "we use cookies",
    "accept all cookies",
    "manage cookie preferences",
]


def is_garbage_content(content: str) -> bool:
    """
    Detect if content is an error/session/paywall page
    that should not be sent to AI.
    """
    if not content or len(content.strip()) < 50:
        return True

    content_lower = content.lower()

    # Check for garbage patterns
    matches = sum(
        1 for pattern in GARBAGE_PATTERNS if pattern in content_lower
    )

    # If multiple patterns match or content is very short with one match
    if matches >= 2:
        return True
    if matches >= 1 and len(content.strip()) < 200:
        return True

    return False


async def generate_summary(content: str, title: str = "") -> SummaryResult:
    """
    Generate summary using Cerebras API.

    Args:
        content: Article content to summarize
        title: Article title (for translation if needed)

    Returns:
        SummaryResult with summaries

    Raises:
        TemporaryError: Temporary error (retry possible)
        PermanentError: Permanent error (do not retry)
    """
    # Check if content is garbage (error, session, paywall)
    if is_garbage_content(content):
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

    # Truncate content if too large (max ~4000 tokens ≈ 16000 chars)
    max_content_len = 12000
    if len(content) > max_content_len:
        content = content[:max_content_len] + "..."

    # Get effective settings from app_settings (with env fallback)
    from app.routes.preferences import (
        get_effective_summary_language,
        get_effective_cerebras_model,
    )

    db = SessionLocal()
    try:
        effective_model = get_effective_cerebras_model(db)
        effective_language = get_effective_summary_language(db)
    finally:
        db.close()

    # Prepare request
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": effective_model,
        "messages": [
            {"role": "system", "content": get_system_prompt()},
            {"role": "user", "content": get_user_prompt(content, title, effective_language)},
        ],
        "temperature": 0.3,
        "max_tokens": 1000,
    }

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
                api_key_rotator.set_key_cooldown(api_key, seconds=60)
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
                circuit_breaker.record_failure()
                raise PermanentError(
                    f"Request error: HTTP {response.status_code}"
                )

            # Parse response
            data = response.json()
            logger.debug(f"API response keys: {data.keys()}")

            if "choices" not in data or not data["choices"]:
                circuit_breaker.record_failure()
                logger.error(f"Response without choices: {data}")
                raise PermanentError("Empty API response")

            choice = data["choices"][0]
            logger.debug(f"Choice keys: {choice.keys()}")

            # Check if response was truncated
            if choice.get("finish_reason") == "length":
                logger.warning(
                    "Response truncated by API (finish_reason=length)"
                )

            # Try different response structures
            message = choice.get("message", {})
            if "content" in message:
                content_response = message["content"]
            elif "reasoning" in message:
                # Some models return 'reasoning' instead of 'content'
                content_response = message["reasoning"]
            elif "text" in choice:
                content_response = choice["text"]
            elif "content" in choice:
                content_response = choice["content"]
            else:
                logger.error(f"Unknown response structure: {choice}")
                circuit_breaker.record_failure()
                raise PermanentError(
                    f"Unknown response structure: {list(choice.keys())}"
                )

            # Parse JSON from response
            try:
                result = _parse_json_response(content_response)

                summary_pt = result.get("summary_pt", "").strip()
                one_line = result.get("one_line_summary", "").strip()
                translated_title = result.get("translated_title")

                # Clean translated_title if "null" string or empty
                if translated_title and isinstance(translated_title, str):
                    translated_title = translated_title.strip()
                    if translated_title.lower() in ("null", "none", ""):
                        translated_title = None

                # Allow both empty (error pages) or both filled
                # But not one empty and other filled
                if bool(summary_pt) != bool(one_line):
                    raise ValueError(
                        "Inconsistent fields (one empty, other not)"
                    )

                # Truncate one_line if needed
                if len(one_line) > 150:
                    one_line = one_line[:147] + "..."

                circuit_breaker.record_success()

                return SummaryResult(
                    summary_pt=summary_pt,
                    one_line_summary=one_line,
                    translated_title=translated_title,
                )

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"Error parsing response: {e}")
                logger.error(f"Raw response: {content_response[:500]}")
                circuit_breaker.record_failure()
                raise PermanentError(f"Invalid response: {e}")

    except httpx.TimeoutException:
        circuit_breaker.record_failure()
        raise TemporaryError(f"Timeout after {settings.cerebras_timeout}s")

    except httpx.RequestError as e:
        circuit_breaker.record_failure()
        raise TemporaryError(f"Connection error: {e}")
