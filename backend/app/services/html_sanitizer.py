"""
HTML sanitization for post content.
Removes scripts, event handlers and dangerous URLs.
"""

import re
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
    "a": ["href", "title", "rel", "target"],
    "img": ["src", "alt", "title", "width", "height"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

# Maximum length for content (summary)
MAX_CONTENT_LENGTH = 500


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


def _add_link_attributes(attrs, new=False):
    """
    Callback to add rel and target to links.
    """
    # Add/overwrite rel and target
    attrs[(None, "rel")] = "noopener noreferrer"
    attrs[(None, "target")] = "_blank"
    return attrs


def sanitize_html(html: Optional[str], truncate: bool = True) -> Optional[str]:
    """
    Sanitize HTML removing dangerous content.

    Rules:
    - Remove disallowed tags
    - Remove event handlers (onclick, onerror, etc.)
    - Remove javascript:, data: (except images), vbscript:
    - Remove http:// in image src (mixed content)
    - Add rel="noopener noreferrer" target="_blank" to links
    - Truncate to MAX_CONTENT_LENGTH if truncate=True

    Args:
        html: HTML to sanitize
        truncate: If True, truncate to MAX_CONTENT_LENGTH

    Returns:
        Sanitized HTML or None if empty
    """
    if not html:
        return None

    # First pass: remove scripts and styles
    html = re.sub(
        r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE
    )
    html = re.sub(
        r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE
    )

    # Remove HTML comments
    html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

    # Sanitize with bleach
    cleaner = bleach.Cleaner(
        tags=ALLOWED_TAGS,
        attributes=_filter_attributes,
        strip=True,
        strip_comments=True,
    )

    sanitized = cleaner.clean(html)

    # Add rel and target to links using linkify with callback
    # First, process existing links manually
    def fix_links(match):
        tag = match.group(0)
        # Remove existing rel and target
        tag = re.sub(r'\s+rel="[^"]*"', "", tag)
        tag = re.sub(r'\s+target="[^"]*"', "", tag)
        # Add new ones
        tag = tag.replace(
            "<a ", '<a rel="noopener noreferrer" target="_blank" '
        )
        return tag

    sanitized = re.sub(r"<a\s[^>]*>", fix_links, sanitized)

    # Truncate if needed
    if truncate and len(sanitized) > MAX_CONTENT_LENGTH:
        # Try to truncate at a safe point (not in the middle of a tag)
        truncated = sanitized[:MAX_CONTENT_LENGTH]

        # Close open tags (simplified)
        # Remove last incomplete tag
        last_lt = truncated.rfind("<")
        last_gt = truncated.rfind(">")
        if last_lt > last_gt:
            truncated = truncated[:last_lt]

        sanitized = truncated + "..."

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
