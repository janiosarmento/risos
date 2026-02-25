"""Cerebras AI client for summary generation."""

# Re-export everything from legacy module during refactoring
from app.services.cerebras._legacy import (  # noqa: F401
    # Public API
    generate_summary,
    get_available_models,
    # Global instances
    circuit_breaker,
    api_key_rotator,
    # Exceptions
    CerebrasError,
    TemporaryError,
    PermanentError,
    ModelSpecificError,
    # Types
    SummaryResult,
    CircuitState,
    # Functions used elsewhere
    is_garbage_content,
    get_system_prompt,
    get_user_prompt,
)

__all__ = [
    "generate_summary",
    "get_available_models",
    "circuit_breaker",
    "api_key_rotator",
    "CerebrasError",
    "TemporaryError",
    "PermanentError",
    "ModelSpecificError",
    "SummaryResult",
    "CircuitState",
    "is_garbage_content",
    "get_system_prompt",
    "get_user_prompt",
]
