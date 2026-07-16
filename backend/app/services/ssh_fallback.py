"""On-demand SSH SOCKS5 tunnel fallback for feed fetches blocked from the
home network.

Opens a fresh tunnel per fetch attempt and tears it down immediately after —
no persistent tunnel, no background process. Disabled (no-op) unless all of
SSH_FALLBACK_HOST, SSH_FALLBACK_USER, and SSH_FALLBACK_KEY_PATH are set.
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator, Optional

import asyncssh

from app.config import settings

logger = logging.getLogger(__name__)


def _fallback_configured() -> bool:
    return bool(
        settings.ssh_fallback_host
        and settings.ssh_fallback_user
        and settings.ssh_fallback_key_path
    )


@asynccontextmanager
async def socks_tunnel() -> AsyncIterator[Optional[str]]:
    """Open a SOCKS5 tunnel over SSH to the configured fallback host.

    Yields the proxy URL (e.g. "socks5://127.0.0.1:PORT"), or None if the
    fallback isn't configured. The tunnel is closed on exit regardless of
    whether the caller's code raises.
    """
    if not _fallback_configured():
        yield None
        return

    logger.info(
        f"Opening SSH SOCKS fallback tunnel to "
        f"{settings.ssh_fallback_user}@{settings.ssh_fallback_host}:{settings.ssh_fallback_port}"
    )
    conn = await asyncssh.connect(
        settings.ssh_fallback_host,
        port=settings.ssh_fallback_port,
        username=settings.ssh_fallback_user,
        client_keys=[settings.ssh_fallback_key_path],
        known_hosts=None,
    )
    try:
        listener = await conn.forward_socks("127.0.0.1", 0)
        try:
            yield f"socks5://127.0.0.1:{listener.get_port()}"
        finally:
            listener.close()
            await listener.wait_closed()
    finally:
        conn.close()
        await conn.wait_closed()
