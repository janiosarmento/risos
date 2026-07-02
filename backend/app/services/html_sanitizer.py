"""
HTML sanitization for post content.
Removes scripts, event handlers and dangerous URLs.
"""

import re
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse

import bleach

# Allowed tags
ALLOWED_TAGS = [
    "p",
    "br",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "blockquote",
    "pre",
    "code",
    "a",
    "img",
    "strong",
    "b",
    "em",
    "i",
    "u",
    "s",
    "strike",
    "del",
    "ins",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "figure",
    "figcaption",
    "div",
    "span",
    "sub",
    "sup",
]

# Allowed attributes per tag
ALLOWED_ATTRIBUTES = {
    "*": ["class", "id"],
    "a": ["href", "title"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

# Maximum length for content (summary)
MAX_CONTENT_LENGTH = 500

_VOID_ELEMENTS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
)


class _OpenTagTracker(HTMLParser):
    """Collects the stack of currently-open tags in an HTML fragment."""

    def __init__(self):
        super().__init__()
        self._stack: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in _VOID_ELEMENTS:
            self._stack.append(tag)

    def handle_endtag(self, tag):
        # Pop the nearest matching tag (handles malformed nesting)
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i] == tag:
                self._stack = self._stack[:i]
                return


def _is_safe_href(url: str) -> bool:
    """
    Check if href is safe.
    Only http:// and https:// are allowed.
    """
    if not url:
        return False

    url_lower = url.lower().strip()

    # Block dangerous protocols
    dangerous_prefixes = [
        "javascript:",
        "data:",
        "vbscript:",
        "file:",
        "about:",
    ]

    for prefix in dangerous_prefixes:
        if url_lower.startswith(prefix):
            return False

    # Allow relative URLs
    if url.startswith("/") or url.startswith("#"):
        return True

    # Allow only http and https
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("http", "https", "")
    except Exception:
        return False


def _is_safe_img_src(url: str) -> bool:
    """
    Check if image src is safe.
    Only https:// and data: (for inline images) are allowed.
    http:// is blocked to avoid mixed content.
    """
    if not url:
        return False

    url_lower = url.lower().strip()

    # Block http (insecure for images)
    if url_lower.startswith("http://"):
        return False

    # Allow data: only for images
    if url_lower.startswith("data:image/"):
        return True

    # Block other data:
    if url_lower.startswith("data:"):
        return False

    # Block dangerous protocols
    dangerous_prefixes = [
        "javascript:",
        "vbscript:",
        "file:",
    ]

    for prefix in dangerous_prefixes:
        if url_lower.startswith(prefix):
            return False

    # Allow https and relative URLs
    try:
        parsed = urlparse(url)
        return parsed.scheme in ("https", "")
    except Exception:
        return False


def _filter_attributes(tag: str, name: str, value: str) -> bool:
    """
    Custom filter for attributes.
    Validates URLs in href and src.
    """
    # Check if attribute is allowed
    allowed = ALLOWED_ATTRIBUTES.get(tag, [])
    global_allowed = ALLOWED_ATTRIBUTES.get("*", [])

    if name not in allowed and name not in global_allowed:
        return False

    # Validate href
    if name == "href":
        return _is_safe_href(value)

    # Validate src
    if name == "src":
        return _is_safe_img_src(value)

    return True


def _close_open_tags(html: str) -> str:
    """Append closing tags for any elements that are still open."""
    tracker = _OpenTagTracker()
    tracker.feed(html)
    return html + "".join(f"</{t}>" for t in reversed(tracker._stack))


def sanitize_html(html: Optional[str], truncate: bool = True) -> Optional[str]:
    """
    Sanitize HTML removing dangerous content.

    Rules:
    - Remove disallowed tags, event handlers, comments (bleach)
    - Remove javascript:, data: (except images), vbscript: from href/src
    - Remove http:// in image src (mixed content)
    - Add rel="noopener noreferrer" target="_blank" to every <a>
    - Truncate to MAX_CONTENT_LENGTH if truncate=True, safely closing
      any open tags so formatting doesn't leak into surrounding content.

    Args:
        html: HTML to sanitize
        truncate: If True, truncate to MAX_CONTENT_LENGTH

    Returns:
        Sanitized HTML or None if empty
    """
    if not html:
        return None

    sanitized = bleach.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes=_filter_attributes,
        strip=True,
        strip_comments=True,
    )

    # Add rel/target to every <a>.  rel / target are already stripped by
    # _filter_attributes (they're no longer in ALLOWED_ATTRIBUTES for <a>),
    # so there is no old value to clean up — we just insert ours.
    sanitized = re.sub(
        r"<a\s", '<a rel="noopener noreferrer" target="_blank" ', sanitized
    )

    # Truncate if needed, keeping tag structure intact
    if truncate and len(sanitized) > MAX_CONTENT_LENGTH:
        truncated = sanitized[:MAX_CONTENT_LENGTH]
        # Snip any trailing incomplete tag
        last_lt = truncated.rfind("<")
        last_gt = truncated.rfind(">")
        if last_lt > last_gt:
            truncated = truncated[:last_lt]
        # Close any tags that were left open by the truncation
        sanitized = _close_open_tags(truncated) + "&#8202;…"

    # Clean excessive whitespace
    sanitized = re.sub(r"\s+", " ", sanitized).strip()

    return sanitized if sanitized else None


def extract_text(html: Optional[str]) -> Optional[str]:
    """
    Extract plain text from HTML (removes all tags).

    Args:
        html: HTML to extract text from

    Returns:
        Plain text or None if empty
    """
    if not html:
        return None

    # Remove all tags
    text = bleach.clean(html, tags=[], strip=True)

    # Clean whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text if text else None
