"""
RSS/Atom feed parser.
Uses feedparser + httpx for fetch and parse.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple
from urllib.parse import urlparse

import feedparser
import httpx

logger = logging.getLogger(__name__)

# Configuration
USER_AGENT = "Risos/1.0 (+https://github.com/janiosarmento/risos; like Miniflux)"
TIMEOUT_SECONDS = 10
MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
MAX_REDIRECTS = 3


@dataclass
class ParsedEntry:
    """Parsed entry from a feed."""

    guid: Optional[str]
    url: Optional[str]
    title: Optional[str]
    author: Optional[str]
    content: Optional[str]
    published_at: Optional[datetime]


@dataclass
class ParsedFeed:
    """Parsed feed."""

    title: Optional[str]
    site_url: Optional[str]
    entries: List[ParsedEntry]


class FeedParseError(Exception):
    """Error parsing feed."""

    pass


class FeedFetchError(Exception):
    """Error fetching feed."""

    pass


def _parse_date(entry: dict) -> Optional[datetime]:
    """Extract publication date from an entry."""
    # feedparser converts to struct_time in published_parsed or updated_parsed
    for field in ["published_parsed", "updated_parsed", "created_parsed"]:
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6])
            except (TypeError, ValueError):
                continue
    return None


def _extract_content(entry: dict) -> Optional[str]:
    """Extract content from an entry (content or summary)."""
    # Try content first (usually more complete)
    if "content" in entry and entry["content"]:
        contents = entry["content"]
        if isinstance(contents, list) and contents:
            # Prefer text/html
            for c in contents:
                if c.get("type") == "text/html":
                    return c.get("value", "")
            # Fallback to first content
            return contents[0].get("value", "")

    # Fallback to summary
    if "summary" in entry:
        return entry["summary"]

    # Fallback to description
    if "description" in entry:
        return entry["description"]

    return None


def _is_same_domain(url1: str, url2: str) -> bool:
    """Check if two URLs are from the same domain."""
    try:
        parsed1 = urlparse(url1)
        parsed2 = urlparse(url2)
        return parsed1.netloc.lower() == parsed2.netloc.lower()
    except Exception:
        return False


def _is_http_to_https(original: str, redirect: str) -> bool:
    """Check if it's a redirect from http to https."""
    try:
        parsed_orig = urlparse(original)
        parsed_redir = urlparse(redirect)
        return (
            parsed_orig.scheme == "http"
            and parsed_redir.scheme == "https"
            and parsed_orig.netloc.lower() == parsed_redir.netloc.lower()
        )
    except Exception:
        return False


async def fetch_feed_content(url: str) -> Tuple[bytes, Optional[str]]:
    """
    Fetch feed content via HTTP.

    Returns:
        Tuple of (content in bytes, final URL after redirects)

    Raises:
        FeedFetchError: If unable to fetch the feed
    """
    final_url = url
    redirects_followed = 0

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,  # Manual redirect control
    ) as client:
        current_url = url

        while redirects_followed <= MAX_REDIRECTS:
            try:
                response = await client.get(
                    current_url,
                    headers={"User-Agent": USER_AGENT},
                )

                # Check redirect
                if response.status_code in (301, 302, 303, 307, 308):
                    redirect_url = response.headers.get("location")
                    if not redirect_url:
                        raise FeedFetchError("Redirect without Location header")

                    # Validate redirect
                    is_safe = _is_http_to_https(
                        current_url, redirect_url
                    ) or _is_same_domain(current_url, redirect_url)

                    if not is_safe:
                        logger.warning(
                            f"Redirect to different domain: {current_url} -> {redirect_url}"
                        )

                    if response.status_code == 301:
                        logger.info(
                            f"Permanent redirect (301): {current_url} -> {redirect_url}. "
                            "Consider updating the feed URL manually."
                        )

                    current_url = redirect_url
                    final_url = redirect_url
                    redirects_followed += 1
                    continue

                # Check status
                if response.status_code >= 400:
                    raise FeedFetchError(
                        f"HTTP {response.status_code}: {response.reason_phrase}"
                    )

                # Check size via streaming
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_SIZE_BYTES:
                    raise FeedFetchError(
                        f"Feed too large: {int(content_length)} bytes (max: {MAX_SIZE_BYTES})"
                    )

                # Read content with limit
                content = b""
                async for chunk in response.aiter_bytes():
                    content += chunk
                    if len(content) > MAX_SIZE_BYTES:
                        raise FeedFetchError(
                            f"Feed too large: > {MAX_SIZE_BYTES} bytes"
                        )

                return content, final_url if final_url != url else None

            except httpx.TimeoutException:
                raise FeedFetchError(f"Timeout after {TIMEOUT_SECONDS}s")
            except httpx.RequestError as e:
                raise FeedFetchError(f"Connection error: {e}")

        raise FeedFetchError(f"Too many redirects (> {MAX_REDIRECTS})")


def parse_feed_content(content: bytes) -> ParsedFeed:
    """
    Parse RSS/Atom feed content.

    Args:
        content: Feed XML bytes

    Returns:
        ParsedFeed with entries

    Raises:
        FeedParseError: If unable to parse
    """
    try:
        feed = feedparser.parse(content)
    except Exception as e:
        raise FeedParseError(f"Error parsing XML: {e}")

    # Check if there was a parse error
    if feed.bozo and not feed.entries:
        bozo_exception = getattr(feed, "bozo_exception", None)
        raise FeedParseError(f"Invalid feed XML: {bozo_exception}")

    # Extract feed metadata
    feed_title = feed.feed.get("title")
    site_url = feed.feed.get("link")

    # Parse entries
    entries = []
    for entry in feed.entries:
        parsed_entry = ParsedEntry(
            guid=entry.get("id") or entry.get("guid"),
            url=entry.get("link"),
            title=entry.get("title"),
            author=entry.get("author"),
            content=_extract_content(entry),
            published_at=_parse_date(entry),
        )
        entries.append(parsed_entry)

    return ParsedFeed(
        title=feed_title,
        site_url=site_url,
        entries=entries,
    )


async def fetch_and_parse(url: str) -> Tuple[ParsedFeed, Optional[str]]:
    """
    Fetch and parse a feed.

    Args:
        url: Feed URL

    Returns:
        Tuple of (ParsedFeed, final URL if there was redirect)

    Raises:
        FeedFetchError: If unable to fetch
        FeedParseError: If unable to parse
    """
    content, final_url = await fetch_feed_content(url)
    parsed = parse_feed_content(content)
    return parsed, final_url
