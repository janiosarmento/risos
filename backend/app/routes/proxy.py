"""
Proxy routes.
Image proxy to avoid mixed content and tracking.
"""

import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status

from app.config import USER_AGENT, settings
from app.dependencies import get_current_user
from app.rate_limiter import limiter
from app.services.url_safety import is_safe_external_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["proxy"])

# Configuration
MAX_IMAGE_SIZE = settings.proxy_max_size_bytes
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/avif",
    # image/svg+xml intentionally excluded: SVG can embed <script> and would
    # execute same-origin if the proxy URL is opened directly.
}
TIMEOUT = settings.proxy_timeout_seconds


@router.get("/image")
@limiter.limit("60/minute")
async def proxy_image(
    request: Request,
    url: str = Query(..., description="Image URL to proxy"),
    user: dict = Depends(get_current_user),
):
    """
    Proxy external images.

    - Rate limited: 60 requests/minute per IP
    - Validates URL and every redirect hop (blocks SSRF, DNS rebinding)
    - Streams the body with a hard size cap (ignores a spoofed/missing
      Content-Length header)
    - Verifies Content-Type
    - Adds Cache-Control
    """
    if not is_safe_external_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or disallowed URL",
        )

    max_redirects = 3
    current_url = url

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=False,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            for _ in range(max_redirects + 1):
                async with client.stream(
                    "GET",
                    current_url,
                    headers={
                        "User-Agent": "RSSReader/1.0 ImageProxy",
                        "Accept": "image/*",
                    },
                ) as response:
                    if response.is_redirect:
                        next_url = response.headers.get("location")
                        if not next_url:
                            raise HTTPException(
                                status_code=status.HTTP_502_BAD_GATEWAY,
                                detail="Redirect without location",
                            )
                        # Resolve relative redirects and revalidate the target
                        # before following it (blocks SSRF via redirect hop).
                        current_url = str(response.url.join(next_url))
                        if not is_safe_external_url(current_url):
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Redirect target is invalid or disallowed",
                            )
                        continue

                    if response.status_code != 200:
                        raise HTTPException(
                            status_code=status.HTTP_502_BAD_GATEWAY,
                            detail=f"Upstream returned {response.status_code}",
                        )

                    content_type = (
                        response.headers.get("content-type", "").split(";")[0].strip()
                    )
                    if content_type not in ALLOWED_CONTENT_TYPES:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Content type not allowed: {content_type}",
                        )

                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_IMAGE_SIZE:
                            raise HTTPException(
                                status_code=status.HTTP_400_BAD_REQUEST,
                                detail="Image too large",
                            )

                    return Response(
                        content=bytes(body),
                        media_type=content_type,
                        headers={
                            "Cache-Control": "public, max-age=86400",  # 1 day
                            "X-Content-Type-Options": "nosniff",
                        },
                    )

            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Too many redirects",
            )

    except HTTPException:
        raise
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
