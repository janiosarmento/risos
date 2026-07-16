"""Tests for the direct-fetch → SSH-fallback retry behavior in feed_parser."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from app.services import feed_parser
from app.services.feed_parser import FeedFetchError


@asynccontextmanager
async def _fake_tunnel(proxy_url):
    yield proxy_url


@pytest.mark.asyncio
async def test_fetch_feed_content_succeeds_direct_without_touching_fallback(
    monkeypatch,
):
    monkeypatch.setattr(feed_parser, "is_safe_external_url", lambda url: True)
    once_mock = AsyncMock(return_value=(b"<rss></rss>", None))
    monkeypatch.setattr(feed_parser, "_fetch_feed_content_once", once_mock)

    def _tunnel_should_not_be_called():
        raise AssertionError("socks_tunnel should not be entered on direct success")

    monkeypatch.setattr(
        feed_parser, "socks_tunnel", lambda: _tunnel_should_not_be_called()
    )

    content, final_url = await feed_parser.fetch_feed_content("https://example.com/feed")

    assert content == b"<rss></rss>"
    assert final_url is None
    once_mock.assert_awaited_once_with("https://example.com/feed", proxy=None)


@pytest.mark.asyncio
async def test_fetch_feed_content_retries_via_fallback_and_succeeds(monkeypatch):
    monkeypatch.setattr(feed_parser, "is_safe_external_url", lambda url: True)

    async def _once(url, proxy=None):
        if proxy is None:
            raise FeedFetchError("Timeout after 30s")
        return (b"<rss>ok</rss>", None)

    monkeypatch.setattr(feed_parser, "_fetch_feed_content_once", _once)
    monkeypatch.setattr(
        feed_parser, "socks_tunnel", lambda: _fake_tunnel("socks5://127.0.0.1:1080")
    )

    content, final_url = await feed_parser.fetch_feed_content("https://example.com/feed")

    assert content == b"<rss>ok</rss>"
    assert final_url is None


@pytest.mark.asyncio
async def test_fetch_feed_content_reraises_original_error_when_fallback_not_configured(
    monkeypatch,
):
    monkeypatch.setattr(feed_parser, "is_safe_external_url", lambda url: True)

    async def _once(url, proxy=None):
        raise FeedFetchError("Connection error: boom")

    monkeypatch.setattr(feed_parser, "_fetch_feed_content_once", _once)
    monkeypatch.setattr(feed_parser, "socks_tunnel", lambda: _fake_tunnel(None))

    with pytest.raises(FeedFetchError) as exc_info:
        await feed_parser.fetch_feed_content("https://example.com/feed")

    assert str(exc_info.value) == "Connection error: boom"


@pytest.mark.asyncio
async def test_fetch_feed_content_combines_errors_when_both_fail(monkeypatch):
    monkeypatch.setattr(feed_parser, "is_safe_external_url", lambda url: True)

    async def _once(url, proxy=None):
        if proxy is None:
            raise FeedFetchError("Timeout after 30s")
        raise FeedFetchError("Connection error: proxy unreachable")

    monkeypatch.setattr(feed_parser, "_fetch_feed_content_once", _once)
    monkeypatch.setattr(
        feed_parser, "socks_tunnel", lambda: _fake_tunnel("socks5://127.0.0.1:1080")
    )

    with pytest.raises(FeedFetchError) as exc_info:
        await feed_parser.fetch_feed_content("https://example.com/feed")

    assert str(exc_info.value) == (
        "Timeout after 30s; fallback also failed: Connection error: proxy unreachable"
    )


@pytest.mark.asyncio
async def test_fetch_feed_content_unsafe_url_skips_fetch_and_fallback(monkeypatch):
    monkeypatch.setattr(feed_parser, "is_safe_external_url", lambda url: False)
    once_mock = AsyncMock()
    monkeypatch.setattr(feed_parser, "_fetch_feed_content_once", once_mock)

    def _tunnel_should_not_be_called():
        raise AssertionError("socks_tunnel should not be entered for an unsafe URL")

    monkeypatch.setattr(
        feed_parser, "socks_tunnel", lambda: _tunnel_should_not_be_called()
    )

    with pytest.raises(FeedFetchError, match="Unsafe or internal URL"):
        await feed_parser.fetch_feed_content("http://169.254.169.254/")

    once_mock.assert_not_awaited()
