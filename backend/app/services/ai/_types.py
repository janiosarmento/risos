"""Types, exceptions, and data classes for the Cerebras client."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List


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


class ModelSpecificError(PermanentError):
    """Error likely caused by the model (bad response format, unknown structure).
    Triggers model fallback when other models are available."""

    pass


class GarbageContentError(PermanentError):
    """Content is garbage (error page, paywall, empty result).
    Post should be marked as skip_summary."""

    pass


@dataclass
class SummaryResult:
    """Summary generation result."""

    summary_pt: str
    one_line_summary: str
    translated_title: str = None
    tags: List[str] = field(default_factory=list)
    model: str = ""
