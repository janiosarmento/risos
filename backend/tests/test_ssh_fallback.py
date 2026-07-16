"""Tests for the on-demand SSH SOCKS fallback tunnel."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import ssh_fallback


@pytest.mark.asyncio
async def test_socks_tunnel_is_noop_when_not_configured(monkeypatch):
    monkeypatch.setattr(ssh_fallback.settings, "ssh_fallback_host", None)
    monkeypatch.setattr(ssh_fallback.settings, "ssh_fallback_user", None)
    monkeypatch.setattr(ssh_fallback.settings, "ssh_fallback_key_path", None)
    connect_mock = AsyncMock()
    monkeypatch.setattr(ssh_fallback.asyncssh, "connect", connect_mock)

    async with ssh_fallback.socks_tunnel() as proxy_url:
        assert proxy_url is None

    connect_mock.assert_not_called()


@pytest.mark.asyncio
async def test_socks_tunnel_opens_and_closes_when_configured(monkeypatch):
    monkeypatch.setattr(ssh_fallback.settings, "ssh_fallback_host", "137.184.104.65")
    monkeypatch.setattr(ssh_fallback.settings, "ssh_fallback_user", "janio")
    monkeypatch.setattr(ssh_fallback.settings, "ssh_fallback_port", 22)
    monkeypatch.setattr(
        ssh_fallback.settings, "ssh_fallback_key_path", "/home/janio/.ssh/id_ed25519"
    )

    listener = MagicMock()
    listener.get_port.return_value = 41234
    listener.close = MagicMock()
    listener.wait_closed = AsyncMock()

    conn = MagicMock()
    conn.forward_socks = AsyncMock(return_value=listener)
    conn.close = MagicMock()
    conn.wait_closed = AsyncMock()

    connect_mock = AsyncMock(return_value=conn)
    monkeypatch.setattr(ssh_fallback.asyncssh, "connect", connect_mock)

    async with ssh_fallback.socks_tunnel() as proxy_url:
        assert proxy_url == "socks5://127.0.0.1:41234"

    connect_mock.assert_called_once_with(
        "137.184.104.65",
        port=22,
        username="janio",
        client_keys=["/home/janio/.ssh/id_ed25519"],
        known_hosts=None,
    )
    conn.forward_socks.assert_called_once_with("127.0.0.1", 0)
    listener.close.assert_called_once()
    listener.wait_closed.assert_awaited_once()
    conn.close.assert_called_once()
    conn.wait_closed.assert_awaited_once()
