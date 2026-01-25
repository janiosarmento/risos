"""
Full content extraction service.
Uses readability-lxml to extract articles from web pages.
Falls back to curl-impersonate for Cloudflare-protected sites (if installed).
"""

import logging
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Optional, Tuple

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

# Cloudflare detection patterns
CLOUDFLARE_PATTERNS = [
    "cloudflare",
    "cf-browser-verification",
    "cf-challenge",
    "checking your browser",
    "ray id:",
    "__cf_bm",
    "challenge-platform",
]


def _is_curl_impersonate_available() -> bool:
    """Check if curl-impersonate-chrome is installed."""
    return shutil.which("curl-impersonate-chrome") is not None


def _is_cloudflare_blocked(status_code: int, html: str) -> bool:
    """
    Detect if response is a Cloudflare challenge/block.

    Args:
        status_code: HTTP status code
        html: Response body

    Returns:
        True if response appears to be a Cloudflare block
    """
    html_lower = html.lower()

    # Check for "Just a moment" challenge page (often returns 200)
    if "just a moment" in html_lower and "cloudflare" in html_lower:
        return True

    # Cloudflare typically returns 403 or 503 for hard blocks
    if status_code in (403, 503):
        matches = sum(1 for pattern in CLOUDFLARE_PATTERNS if pattern in html_lower)
        if matches >= 2:
            return True

    # Also check for challenge patterns regardless of status code
    challenge_patterns = ["cf-challenge", "cf-browser-verification", "challenge-platform"]
    if any(p in html_lower for p in challenge_patterns):
        return True

    return False


def _fetch_with_curl_impersonate(url: str) -> Tuple[bool, str, Optional[str]]:
    """
    Fetch URL using curl-impersonate-chrome.

    Args:
        url: URL to fetch

    Returns:
        Tuple of (success, html_content, error_message)
    """
    try:
        result = subprocess.run(
            [
                "curl-impersonate-chrome",
                "-s",  # Silent mode
                "-L",  # Follow redirects
                "--max-time", "30",  # Timeout
                "--max-redirs", "5",  # Max redirects
                url,
            ],
            capture_output=True,
            text=True,
            timeout=35,  # subprocess timeout (slightly higher than curl)
        )

        if result.returncode != 0:
            return False, "", f"curl-impersonate failed with code {result.returncode}"

        html = result.stdout
        if not html or len(html) < 100:
            return False, "", "Empty response from curl-impersonate"

        # Check if we still got a Cloudflare block
        html_lower = html.lower()
        if any(p in html_lower for p in ["checking your browser", "cf-challenge", "just a moment"]):
            return False, "", "Cloudflare JavaScript challenge (requires browser)"

        logger.info(f"Successfully fetched with curl-impersonate: {url}")
        return True, html, None

    except subprocess.TimeoutExpired:
        return False, "", "curl-impersonate timeout"
    except Exception as e:
        return False, "", str(e)


@dataclass
class ExtractedContent:
    """Content extraction result."""

    title: str
    content: str
    success: bool
    error: Optional[str] = None


def _extract_from_html(html: str) -> ExtractedContent:
    """
    Extract content from HTML using readability.

    Args:
        html: Raw HTML content

    Returns:
        ExtractedContent with title and sanitized HTML content
    """
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


async def extract_full_content(url: str) -> ExtractedContent:
    """
    Extract full content from a URL using readability.
    Falls back to curl-impersonate for Cloudflare-protected sites.

    Args:
        url: Page URL to extract from

    Returns:
        ExtractedContent with title and sanitized HTML content
    """
    html = None
    use_curl_fallback = False

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

            # Check for non-200 status first
            if response.status_code != 200:
                # Check if it's a Cloudflare block
                if _is_cloudflare_blocked(response.status_code, response.text):
                    logger.info(f"Cloudflare block detected for {url} (HTTP {response.status_code})")
                    use_curl_fallback = True
                else:
                    return ExtractedContent(
                        title="",
                        content="",
                        success=False,
                        error=f"HTTP {response.status_code}",
                    )
            # Check for Cloudflare challenge on 200 responses (e.g., "Just a moment...")
            elif _is_cloudflare_blocked(response.status_code, response.text):
                logger.info(f"Cloudflare challenge page detected for {url}")
                use_curl_fallback = True
            else:
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

    except httpx.TimeoutException:
        logger.info(f"Timeout fetching {url}, will try curl-impersonate fallback")
        use_curl_fallback = True
    except httpx.RequestError as e:
        logger.error(f"Error fetching {url}: {e}")
        use_curl_fallback = True
    except Exception as e:
        logger.error(f"Error extracting content from {url}: {e}")
        return ExtractedContent(
            title="", content="", success=False, error=str(e)
        )

    # Try curl-impersonate fallback if needed and available
    if use_curl_fallback:
        if not _is_curl_impersonate_available():
            return ExtractedContent(
                title="",
                content="",
                success=False,
                error="Cloudflare block detected (curl-impersonate not available)",
            )

        success, html, error = _fetch_with_curl_impersonate(url)
        if not success:
            return ExtractedContent(
                title="",
                content="",
                success=False,
                error=error or "curl-impersonate fallback failed",
            )

    # Extract content from HTML
    if html:
        return _extract_from_html(html)

    return ExtractedContent(
        title="",
        content="",
        success=False,
        error="No content fetched",
    )
