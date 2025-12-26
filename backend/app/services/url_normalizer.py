"""
URL normalization for deduplication.
Applies consistent rules to compare URLs.
"""

import logging
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

logger = logging.getLogger(__name__)

# Tracking parameters to remove
TRACKING_PARAMS = {
    # UTM
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "utm_source_platform",
    "utm_creative_format",
    # Facebook
    "fbclid",
    "fb_action_ids",
    "fb_action_types",
    "fb_source",
    "fb_ref",
    # Google
    "gclid",
    "gclsrc",
    "dclid",
    # Twitter
    "twclid",
    # Microsoft/Bing
    "msclkid",
    # Mailchimp
    "mc_cid",
    "mc_eid",
    # HubSpot
    "hsa_acc",
    "hsa_cam",
    "hsa_grp",
    "hsa_ad",
    "hsa_src",
    "hsa_tgt",
    "hsa_kw",
    "hsa_mt",
    "hsa_net",
    "hsa_ver",
    # Other common
    "_ga",
    "_gl",
    "ref",
    "source",
    "via",
}

# Default ports by scheme
DEFAULT_PORTS = {
    "http": 80,
    "https": 443,
}


def normalize_url(url: Optional[str]) -> Optional[str]:
    """
    Normalize URL for consistent comparison.

    Rules applied:
    - Hostname to lowercase
    - Remove fragment (#...)
    - Remove default port (80 for http, 443 for https)
    - Remove tracking parameters (utm_*, fbclid, gclid, etc.)
    - Remove trailing slash (except for root "/")
    - Reject URLs with userinfo (user:password@)

    Args:
        url: URL to normalize

    Returns:
        Normalized URL or None if invalid

    Examples:
        >>> normalize_url("https://Site.com:443/Article?utm_source=rss&id=123#comments")
        "https://site.com/Article?id=123"

        >>> normalize_url("http://user:pass@example.com/page")
        None  # URLs with userinfo are rejected
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception as e:
        logger.warning(f"Invalid URL: {url} - {e}")
        return None

    # Reject URLs with userinfo (security)
    if parsed.username or parsed.password:
        logger.warning(f"URL with userinfo rejected: {url}")
        return None

    # Check valid scheme
    if parsed.scheme not in ("http", "https"):
        logger.warning(f"URL with invalid scheme: {url}")
        return None

    # Hostname to lowercase
    hostname = parsed.hostname
    if not hostname:
        return None
    hostname = hostname.lower()

    # Remove default port
    port = parsed.port
    default_port = DEFAULT_PORTS.get(parsed.scheme)
    if port == default_port:
        port = None

    # Rebuild netloc
    if port:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    # Process path
    path = parsed.path

    # Remove trailing slash (except for root)
    if path and path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    # If path empty, use /
    if not path:
        path = "/"

    # Process query string - remove tracking parameters
    query_params = parse_qs(parsed.query, keep_blank_values=True)

    # Filter tracking parameters
    filtered_params = {
        k: v
        for k, v in query_params.items()
        if k.lower() not in TRACKING_PARAMS
    }

    # Rebuild sorted query string (for consistency)
    if filtered_params:
        # Flatten: parse_qs returns lists, we need single values
        flat_params = []
        for k, v in sorted(filtered_params.items()):
            for val in v:
                flat_params.append((k, val))
        query = urlencode(flat_params)
    else:
        query = ""

    # Rebuild URL without fragment
    normalized = urlunparse(
        (
            parsed.scheme,
            netloc,
            path,
            "",  # params (rarely used)
            query,
            "",  # fragment removed
        )
    )

    return normalized


def extract_domain(url: str) -> Optional[str]:
    """
    Extract domain from a URL.

    Args:
        url: URL to extract domain from

    Returns:
        Domain in lowercase or None if invalid
    """
    try:
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname.lower()
    except Exception:
        pass
    return None
