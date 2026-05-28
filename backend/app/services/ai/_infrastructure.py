"""Infrastructure: chave de API única e circuit breaker para o cliente de AI."""

import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

from app.database import SessionLocal
from app.models import AppSettings
from app.services.ai._constants import (
    AI_MAX_RPM,
    CB_FAILURE_THRESHOLD,
    CB_HALF_OPEN_MAX_REQUESTS,
    CB_RECOVERY_TIMEOUT_SECONDS,
)
from app.services.ai._types import CircuitState

logger = logging.getLogger(__name__)


class ApiKeyRotator:
    """
    Wrapper simples para a chave de API configurada via Jano.
    Não há rotação — existe uma única chave. A interface é mantida
    para compatibilidade com os callers existentes.
    """

    def _get_key(self) -> Optional[str]:
        """Obtém a chave de API do Jano via preferências."""
        from app.routes.preferences import get_effective_ai_api_key

        db = SessionLocal()
        try:
            return get_effective_ai_api_key(db)
        finally:
            db.close()

    # Compatibilidade com callers que usam _get_keys() (retorna lista)
    def _get_keys(self) -> list:
        key = self._get_key()
        return [key] if key else []

    def get_next_key(self) -> Tuple[Optional[str], Optional[int]]:
        """Retorna a chave configurada, ou (None, None) se não configurada."""
        key = self._get_key()
        if not key:
            logger.warning("Nenhuma chave de API configurada no Jano")
            return None, None
        return key, 0

    def has_available_key(self) -> bool:
        """Verifica se há chave disponível."""
        return bool(self._get_key())

    # Métodos de cooldown mantidos como no-op (sem rotação, sem cooldown por chave)
    def set_key_cooldown(self, key: str, seconds: int = 60):
        logger.warning(f"Rate limit atingido (sem rotação, aguardando {seconds}s)")

    def clear_cooldown(self, key: str):
        pass

    def get_status(self) -> dict:
        key = self._get_key()
        return {
            "total_keys": 1 if key else 0,
            "keys": [{"index": 1, "available": True}] if key else [],
        }


# Instância global (compatibilidade com todos os callers)
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
                            "ai_state",
                            "ai_failures",
                            "ai_half_successes",
                            "ai_last_failure",
                            "ai_last_call",
                        ]
                    )
                )
                .all()
            ):
                if row.key == "ai_state":
                    self.state = CircuitState(row.value)
                elif row.key == "ai_failures":
                    self.failures = int(row.value)
                elif row.key == "ai_half_successes":
                    self.half_successes = int(row.value)
                elif row.key == "ai_last_failure":
                    self.last_failure = datetime.fromisoformat(row.value)
                elif row.key == "ai_last_call":
                    self.last_call = datetime.fromisoformat(row.value)

        finally:
            db.close()

    def _save_state(self):
        """Save state to database."""
        db = SessionLocal()
        try:
            updates = {
                "ai_state": self.state.value,
                "ai_failures": str(self.failures),
                "ai_half_successes": str(self.half_successes),
            }

            if self.last_failure:
                updates["ai_last_failure"] = self.last_failure.isoformat()
            if self.last_call:
                updates["ai_last_call"] = self.last_call.isoformat()

            for key, value in updates.items():
                existing = db.query(AppSettings).filter(AppSettings.key == key).first()
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
        min_interval = 60.0 / AI_MAX_RPM
        if self.last_call:
            elapsed = (now - self.last_call).total_seconds()
            if elapsed < min_interval:
                return (
                    False,
                    f"Waiting for minimum interval ({min_interval - elapsed:.1f}s)",
                )

        # Check circuit breaker
        if self.state == CircuitState.OPEN:
            # Check if recovery timeout has passed
            if self.last_failure:
                elapsed = (now - self.last_failure).total_seconds()
                if elapsed >= CB_RECOVERY_TIMEOUT_SECONDS:
                    # Transition to HALF
                    self.state = CircuitState.HALF
                    self.half_successes = 0
                    self._save_state()
                    logger.info("Circuit breaker: OPEN -> HALF")
                else:
                    return (
                        False,
                        "Circuit breaker OPEN (recovery in "
                        f"{CB_RECOVERY_TIMEOUT_SECONDS - elapsed:.0f}s)",
                    )

        return True, None

    def record_success(self):
        """Record successful call."""
        now = datetime.utcnow()
        self.last_call = now

        if self.state == CircuitState.HALF:
            self.half_successes += 1
            if self.half_successes >= CB_HALF_OPEN_MAX_REQUESTS:
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
            if self.failures >= CB_FAILURE_THRESHOLD:
                self.state = CircuitState.OPEN
                logger.warning(
                    f"Circuit breaker: CLOSED -> OPEN ({self.failures} failures)"
                )

        self._save_state()


# Global circuit breaker instance
circuit_breaker = CircuitBreaker()
