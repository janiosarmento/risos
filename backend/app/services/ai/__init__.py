"""Cerebras AI client for summary generation."""

# Public API re-exported from submodules
from app.services.ai._types import (  # noqa: F401
    CircuitState,
    CerebrasError,
    TemporaryError,
    PermanentError,
    ModelSpecificError,
    GarbageContentError,
    SummaryResult,
)
from app.services.ai._prompts import (  # noqa: F401
    get_system_prompt,
    get_user_prompt,
)
from app.services.ai._parsing import (  # noqa: F401
    is_garbage_content,
)
from app.services.ai._infrastructure import (  # noqa: F401
    circuit_breaker,
    api_key_rotator,
)
from app.services.ai._api import (  # noqa: F401
    generate_summary,
    get_available_models,
    clear_models_cache,
)

__all__ = [
    "generate_summary",
    "get_available_models",
    "clear_models_cache",
    "circuit_breaker",
    "api_key_rotator",
    "CerebrasError",
    "TemporaryError",
    "PermanentError",
    "ModelSpecificError",
    "GarbageContentError",
    "SummaryResult",
    "CircuitState",
    "is_garbage_content",
    "get_system_prompt",
    "get_user_prompt",
]
