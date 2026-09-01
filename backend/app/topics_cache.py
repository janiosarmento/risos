"""Process-local cache for the computed topic list.

Lives in its own module so post- and feed-mutation handlers can invalidate
it after a commit without importing the topics router (which would be a
circular-ish dependency and pull in unrelated code).

Computing per-topic post/unread counts scans a large post_tags table; the
sidebar polls the endpoint often, so the result is cached briefly. Any write
that can change those counts must call invalidate().
"""

import time

_TTL_SECONDS = 60.0
_cache: dict = {"data": None, "ts": 0.0}


def get_cached():
    """Return the cached topic list, or None if absent or expired."""
    if (
        _cache["data"] is not None
        and time.monotonic() - _cache["ts"] < _TTL_SECONDS
    ):
        return _cache["data"]
    return None


def set_cached(data) -> None:
    _cache["data"] = data
    _cache["ts"] = time.monotonic()


def invalidate() -> None:
    _cache["data"] = None
    _cache["ts"] = 0.0
