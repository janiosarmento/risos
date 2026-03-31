"""Infrastructure: API key rotation and circuit breaker for the Cerebras client."""

import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict

from app.config import settings
from app.database import SessionLocal
from app.models import AppSettings
from app.services.cerebras._constants import DEFAULT_KEY_COOLDOWN_SECONDS
from app.services.cerebras._types import CircuitState

logger = logging.getLogger(__name__)


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

    def _get_keys(self) -> list:
        """Get API keys from DB settings or env fallback."""
        from app.routes.preferences import get_effective_cerebras_api_keys

        db = SessionLocal()
        try:
            return get_effective_cerebras_api_keys(db)
        finally:
            db.close()

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
                num_keys = len(self._get_keys())
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
        Return the first available API key.

        Returns:
            Tuple of (api_key, key_index) or (None, None) if none available
        """
        keys = self._get_keys()
        if not keys:
            return None, None
        return keys[0], 0

    def set_key_cooldown(
        self, key: str, seconds: int = DEFAULT_KEY_COOLDOWN_SECONDS
    ):
        """Put a key in cooldown after rate limit."""
        with self._lock:
            self._key_cooldowns[key] = datetime.utcnow() + timedelta(
                seconds=seconds
            )
            keys = self._get_keys()
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

    def has_available_key(self) -> bool:
        """
        Check if any API key is available (not in cooldown).
        Does NOT advance the index - use for pre-checks.
        """
        keys = self._get_keys()
        if not keys:
            return False

        now = datetime.utcnow()
        with self._lock:
            for key in keys:
                cooldown_until = self._key_cooldowns.get(key)
                if not cooldown_until or now >= cooldown_until:
                    return True
            return False

    def get_status(self) -> dict:
        """Return status of all keys."""
        keys = self._get_keys()
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
