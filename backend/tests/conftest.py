"""Make the backend package importable when running pytest from anywhere."""

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importing a route module pulls in the sanitizer, and therefore bleach, which
# a developer machine may not have (requirements.txt pins an editable dep that
# only exists on the deploy host, so a clean local install fails). Nothing in
# the test suite sanitizes HTML, so a stub keeps collection working without
# pretending to provide the real behaviour.
try:  # pragma: no cover - depends on the local environment
    import bleach  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    stub = types.ModuleType("bleach")

    def _unavailable(*args, **kwargs):
        raise RuntimeError("bleach is stubbed out in tests; install it to use it")

    stub.clean = _unavailable
    stub.linkify = _unavailable
    css_sanitizer = types.ModuleType("bleach.css_sanitizer")
    css_sanitizer.CSSSanitizer = _unavailable
    stub.css_sanitizer = css_sanitizer
    sys.modules["bleach"] = stub
    sys.modules["bleach.css_sanitizer"] = css_sanitizer
