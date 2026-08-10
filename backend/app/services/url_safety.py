"""
URL safety validation shared by the image proxy and post redirect.
Blocks SSRF / open-redirect targets: private, loopback, link-local and
reserved IP ranges (v4 and v6), with DNS resolution so hostnames that
merely point at internal IPs are also rejected.
"""

import ipaddress
import logging
import socket
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_BLOCKED_HOSTNAMES = {"localhost"}

# Cloud instance-metadata endpoints. These are never a legitimate AI API
# base URL, unlike other private/loopback addresses which are — self-hosted
# backends (e.g. LM Studio) intentionally run on localhost or the LAN, so
# api_base_url can't use the general is_safe_external_url() guard.
_METADATA_HOSTNAMES = {
    "169.254.169.254",  # AWS / GCP / Azure / DigitalOcean / OCI
    "169.254.170.2",  # AWS ECS task metadata
    "100.100.100.200",  # Alibaba Cloud
    "metadata.google.internal",
    "fd00:ec2::254",  # AWS IMDSv2 IPv6
}


def _is_blocked_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return True  # unparsable — fail closed

    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def is_safe_external_url(url: str) -> bool:
    """
    Validate that a URL is safe to fetch or redirect to server-side.

    - Only http/https schemes.
    - Rejects localhost and any private/loopback/link-local/reserved IP,
      including IPv6 and non-dotted IPv4 notations.
    - Resolves the hostname and validates every resolved address, so a
      public hostname that resolves to an internal IP is also rejected.
    """
    try:
        parsed = urlparse(url)

        if parsed.scheme not in ("http", "https"):
            return False

        hostname = parsed.hostname or ""
        if not hostname or hostname.lower() in _BLOCKED_HOSTNAMES:
            return False

        # If the hostname is already a literal IP, validate it directly.
        try:
            ipaddress.ip_address(hostname)
            return not _is_blocked_ip(hostname)
        except ValueError:
            pass  # Not a literal IP — resolve it below.

        # Otherwise resolve and validate every returned address (blocks
        # DNS rebinding to internal IPs).
        try:
            addrinfo = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False

        resolved_ips = {info[4][0] for info in addrinfo}
        if not resolved_ips:
            return False

        return not any(_is_blocked_ip(ip) for ip in resolved_ips)

    except Exception:
        return False


def is_cloud_metadata_url(url: str) -> bool:
    """
    True if the URL's host is a known cloud instance-metadata endpoint.

    Narrower than is_safe_external_url(): deliberately allows other
    private/loopback addresses (self-hosted AI backends like LM Studio
    legitimately run on localhost or the LAN), and only blocks the handful
    of hosts that only ever serve credential-leaking metadata.
    """
    try:
        parsed = urlparse(url)
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False
        if hostname in _METADATA_HOSTNAMES:
            return True

        # A hostname could still resolve to a metadata IP even if typed
        # differently (e.g. decimal/octal IP notation, or a DNS name an
        # attacker controls that they've pointed at 169.254.169.254).
        try:
            ipaddress.ip_address(hostname)
            return hostname in _METADATA_HOSTNAMES
        except ValueError:
            pass

        try:
            addrinfo = socket.getaddrinfo(hostname, None)
        except socket.gaierror:
            return False
        resolved_ips = {info[4][0] for info in addrinfo}
        return any(ip in _METADATA_HOSTNAMES for ip in resolved_ips)

    except Exception:
        return False
