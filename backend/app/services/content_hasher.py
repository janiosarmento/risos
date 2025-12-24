"""
Content hashing for deduplication.
Normalizes content before computing hash.
"""
import hashlib
import re
from typing import Optional

from app.services.html_sanitizer import extract_text

# Boilerplate patterns to remove
BOILERPLATE_PATTERNS = [
    # Timestamps and dates
    r'\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b',
    r'\b\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM|am|pm)?\b',
    # "Read more", "Continue reading", etc.
    r'\b(leia|read|continue|ver|see)\s+(mais|more|reading|lendo)\b',
    r'\b(clique|click)\s+(aqui|here)\b',
    # Sharing
    r'\b(share|compartilh[ae]|tweet|retweet)\b',
    # Cookie/newsletter notices
    r'\b(newsletter|subscribe|inscreva-se|cadastre-se)\b',
]

# Maximum size for hash (bytes)
MAX_HASH_SIZE = 200 * 1024  # 200KB


def normalize_for_hash(text: str) -> str:
    """
    Normalize text for consistent hashing.

    - Remove boilerplate
    - Normalize whitespace
    - Lowercase
    """
    if not text:
        return ""

    # Lowercase
    text = text.lower()

    # Remove boilerplate
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # Normalize whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def compute_content_hash(
    content: Optional[str],
    title: Optional[str] = None,
    url: Optional[str] = None
) -> Optional[str]:
    """
    Compute SHA-256 hash of content + title + URL.

    Args:
        content: HTML content or plain text
        title: Article title
        url: Article URL

    Returns:
        SHA-256 hash in hexadecimal or None if empty
    """
    if not content:
        return None

    # Extract plain text from HTML
    text = extract_text(content)
    if not text:
        return None

    # Include title and URL in hash to avoid collisions
    # (e.g., HN posts with same minimal content but different titles/URLs)
    parts = [p for p in [title, url, text] if p]
    text = "\n".join(parts)

    # Normalize
    normalized = normalize_for_hash(text)
    if not normalized:
        return None

    # Truncate if too large
    if len(normalized) > MAX_HASH_SIZE:
        # Use start + end to capture variations
        half = MAX_HASH_SIZE // 2
        normalized = normalized[:half] + normalized[-half:]

    # Compute hash
    hash_bytes = hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    return hash_bytes
