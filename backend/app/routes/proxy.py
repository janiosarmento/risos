"""
Proxy routes.
Image proxy to avoid mixed content and tracking.
"""

import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from app.config import settings
from app.rate_limiter import limiter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["proxy"])

# Configuration
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/avif",
}
TIMEOUT = 15.0  # seconds


def is_valid_image_url(url: str) -> bool:
    """Validate if URL is safe for proxying."""
    try:
        parsed = urlparse(url)

        # Must be http or https
        if parsed.scheme not in ("http", "https"):
            return False

        # Don't allow localhost or private IPs
        hostname = parsed.hostname or ""
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
            return False

        # Don't allow common private IPs
        if hostname.startswith(
            ("10.", "192.168.", "172.16.", "172.17.", "172.18.")
        ):
            return False

        return True

    except Exception:
        return False


@router.get("/image")
@limiter.limit("60/minute")
async def proxy_image(request: Request, url: str = Query(..., description="Image URL to proxy")):
    """
    Proxy external images.

    - Rate limited: 60 requests/minute per IP
    - Validates URL (http/https, not localhost)
    - Limits size (10MB)
    - Verifies Content-Type
    - Adds Cache-Control
    """
    if not is_valid_image_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or disallowed URL",
        )

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            max_redirects=3,
        ) as client:
            # Make request with appropriate headers
            response = await client.get(
                url,
                headers={
                    "User-Agent": "RSSReader/1.0 ImageProxy",
                    "Accept": "image/*",
                },
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Upstream returned {response.status_code}",
                )

            # Check Content-Type
            content_type = (
                response.headers.get("content-type", "").split(";")[0].strip()
            )
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Content type not allowed: {content_type}",
                )

            # Check size
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_IMAGE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Image too large",
                )

            # Return image with cache headers
            return Response(
                content=response.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=86400",  # 1 day
                    "X-Content-Type-Options": "nosniff",
                },
            )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout fetching image",
        )
    except httpx.RequestError as e:
        logger.error(f"Error fetching image {url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Error fetching image",
        )
