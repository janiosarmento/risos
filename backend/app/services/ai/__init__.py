"""AI client for summary generation."""

# Public API re-exported from submodules
from app.services.ai._api import (  # noqa: F401
    call_llm_text,
    clear_models_cache,
    generate_summary,
    get_available_models,
)
from app.services.ai._infrastructure import (  # noqa: F401
    api_key_rotator,
)
from app.services.ai._parsing import (  # noqa: F401
    is_garbage_content,
)
from app.services.ai._prompts import (  # noqa: F401
    get_system_prompt,
    get_user_prompt,
)
from app.services.ai._types import (  # noqa: F401
    AIError,
    CerebrasError,  # legacy alias
    GarbageContentError,
    ModelNotFound,
    ModelSpecificError,
    PermanentError,
    RateLimited,
    SummaryResult,
    TemporaryError,
)

__all__ = [
    "generate_summary",
    "get_available_models",
    "clear_models_cache",
    "call_llm_text",
    "api_key_rotator",
    "AIError",
    "CerebrasError",
    "TemporaryError",
    "RateLimited",
    "PermanentError",
    "ModelNotFound",
    "ModelSpecificError",
    "GarbageContentError",
    "SummaryResult",
    "is_garbage_content",
    "get_system_prompt",
    "get_user_prompt",
]
