"""
Rotas de proxy.
Proxy de imagens para evitar mixed content e tracking.
"""
import logging
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/proxy", tags=["proxy"])

# Configurações
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
ALLOWED_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/svg+xml",
    "image/avif",
}
TIMEOUT = 15.0  # segundos


def is_valid_image_url(url: str) -> bool:
    """Valida se a URL é segura para proxy."""
    try:
        parsed = urlparse(url)

        # Deve ser http ou https
        if parsed.scheme not in ("http", "https"):
            return False

        # Não permitir localhost ou IPs privados
        hostname = parsed.hostname or ""
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0"):
            return False

        # Não permitir IPs privados comuns
        if hostname.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.")):
            return False

        return True

    except Exception:
        return False


@router.get("/image")
async def proxy_image(
    url: str = Query(..., description="URL da imagem para proxy")
):
    """
    Proxy de imagens externas.

    - Valida URL (http/https, não localhost)
    - Limita tamanho (10MB)
    - Verifica Content-Type
    - Adiciona Cache-Control
    """
    if not is_valid_image_url(url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or disallowed URL"
        )

    try:
        async with httpx.AsyncClient(
            timeout=TIMEOUT,
            follow_redirects=True,
            max_redirects=3,
        ) as client:
            # Fazer request com headers apropriados
            response = await client.get(
                url,
                headers={
                    "User-Agent": "RSSReader/1.0 ImageProxy",
                    "Accept": "image/*",
                }
            )

            if response.status_code != 200:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Upstream returned {response.status_code}"
                )

            # Verificar Content-Type
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if content_type not in ALLOWED_CONTENT_TYPES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Content type not allowed: {content_type}"
                )

            # Verificar tamanho
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_IMAGE_SIZE:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Image too large"
                )

            # Retornar imagem com cache headers
            return Response(
                content=response.content,
                media_type=content_type,
                headers={
                    "Cache-Control": "public, max-age=86400",  # 1 dia
                    "X-Content-Type-Options": "nosniff",
                }
            )

    except httpx.TimeoutException:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Timeout fetching image"
        )
    except httpx.RequestError as e:
        logger.error(f"Error fetching image {url}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Error fetching image"
        )
