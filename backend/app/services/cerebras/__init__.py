"""Cerebras AI client for summary generation."""

# Re-export everything from submodules during refactoring
from app.services.cerebras._types import (  # noqa: F401
    CircuitState,
    CerebrasError,
    TemporaryError,
    PermanentError,
    ModelSpecificError,
    SummaryResult,
)
from app.services.cerebras._prompts import (  # noqa: F401
    get_system_prompt,
    get_user_prompt,
)
from app.services.cerebras._parsing import (  # noqa: F401
    is_garbage_content,
)
from app.services.cerebras._infrastructure import (  # noqa: F401
    circuit_breaker,
    api_key_rotator,
)
from app.services.cerebras._legacy import (  # noqa: F401
    generate_summary,
    get_available_models,
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
