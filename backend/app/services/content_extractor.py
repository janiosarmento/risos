"""
Full content extraction service.
Uses readability-lxml to extract articles from web pages.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional

import httpx
from lxml.html.clean import Cleaner
from readability import Document

from app.services.html_sanitizer import sanitize_html

logger = logging.getLogger(__name__)

# Non-article content patterns to remove before extraction
NON_ARTICLE_PATTERNS = [
    # Donation appeals
    r'<div[^>]*class="[^"]*appeal[^"]*"[^>]*>.*?</div>',
    r'<div[^>]*class="[^"]*donation[^"]*"[^>]*>.*?</div>',
    r'<div[^>]*class="[^"]*donate[^"]*"[^>]*>.*?</div>',
    r'<div[^>]*class="[^"]*fundrais[^"]*"[^>]*>.*?</div>',
    # Cookie notices
    r'<div[^>]*class="[^"]*cookie[^"]*"[^>]*>.*?</div>',
    r'<div[^>]*class="[^"]*gdpr[^"]*"[^>]*>.*?</div>',
    r'<div[^>]*class="[^"]*consent[^"]*"[^>]*>.*?</div>',
    # Newsletter popups
    r'<div[^>]*class="[^"]*newsletter[^"]*"[^>]*>.*?</div>',
    r'<div[^>]*class="[^"]*subscribe[^"]*"[^>]*>.*?</div>',
    # Modals and overlays
    r'<div[^>]*class="[^"]*modal[^"]*"[^>]*>.*?</div>',
    r'<div[^>]*class="[^"]*overlay[^"]*"[^>]*>.*?</div>',
    r'<div[^>]*class="[^"]*popup[^"]*"[^>]*>.*?</div>',
]

# Texts indicating non-article content
NON_ARTICLE_TEXTS = [
    "please don't scroll past this",
    "can you chip in",
    "please donate",
    "support us",
    "we need your help",
    "chip in today",
    "make a donation",
    "please pitch in",
]


def _clean_non_article_content(html: str) -> str:
    """Remove elements that are not part of the main article."""
    # Remove known non-article content patterns
    for pattern in NON_ARTICLE_PATTERNS:
        html = re.sub(pattern, "", html, flags=re.DOTALL | re.IGNORECASE)
    return html


def _is_non_article_content(text: str) -> bool:
    """Check if extracted text is non-article content (donation, etc)."""
    text_lower = text.lower()
    matches = sum(1 for phrase in NON_ARTICLE_TEXTS if phrase in text_lower)
    # If 2+ non-article phrases found, probably spam
    return matches >= 2


# Configuration
TIMEOUT = 20.0  # seconds
MAX_CONTENT_SIZE = 5 * 1024 * 1024  # 5MB


@dataclass
class ExtractedContent:
    """Content extraction result."""

    title: str
    content: str
    success: bool
    error: Optional[str] = None


async def extract_full_content(url: str) -> ExtractedContent:
    """
    Extract full content from a URL using readability.

    Args:
        url: Page URL to extract from

    Returns:
        ExtractedContent with title and sanitized HTML content
    """
    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            max_redirects=5,
        ) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,pt;q=0.7",
                    "Accept-Encoding": "gzip, deflate",  # No brotli (br) - httpx doesn't support it
                    "DNT": "1",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                    "Sec-Fetch-Dest": "document",
                    "Sec-Fetch-Mode": "navigate",
                    "Sec-Fetch-Site": "none",
                    "Sec-Fetch-User": "?1",
                    "Cache-Control": "max-age=0",
                },
            )

            if response.status_code != 200:
                return ExtractedContent(
                    title="",
                    content="",
                    success=False,
                    error=f"HTTP {response.status_code}",
                )

            # Check Content-Type
            content_type = response.headers.get("content-type", "")
            if (
                "text/html" not in content_type
                and "application/xhtml" not in content_type
            ):
                return ExtractedContent(
                    title="",
                    content="",
                    success=False,
                    error=f"Invalid content type: {content_type}",
                )

            # Check size
            if len(response.content) > MAX_CONTENT_SIZE:
                return ExtractedContent(
                    title="",
                    content="",
                    success=False,
                    error="Content too large",
                )

            html = response.text

            # Clean non-article content before extraction
            html = _clean_non_article_content(html)

            # Extract with readability
            doc = Document(html)
            title = doc.title()
            content_html = doc.summary()

            # Sanitize extracted HTML
            clean_content = sanitize_html(content_html, truncate=False)

            if not clean_content or len(clean_content.strip()) < 100:
                return ExtractedContent(
                    title=title or "",
                    content="",
                    success=False,
                    error="Could not extract meaningful content",
                )

            # Check if extracted content is spam/donation
            if _is_non_article_content(clean_content):
                return ExtractedContent(
                    title=title or "",
                    content="",
                    success=False,
                    error="Extracted content appears to be non-article (donation appeal, etc)",
                )

            return ExtractedContent(
                title=title or "",
                content=clean_content,
                success=True,
            )

    except httpx.TimeoutException:
        return ExtractedContent(
            title="", content="", success=False, error="Timeout"
        )
    except httpx.RequestError as e:
        logger.error(f"Error fetching {url}: {e}")
        return ExtractedContent(
            title="", content="", success=False, error=str(e)
        )
    except Exception as e:
        logger.error(f"Error extracting content from {url}: {e}")
        return ExtractedContent(
            title="", content="", success=False, error=str(e)
        )
