# SSH SOCKS Fallback for Feed Fetch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a feed fetch fails directly, retry it once through an on-demand SOCKS5 tunnel over SSH to a remote server, so feeds blocked/throttled from the homelab's network still get fetched via a working network path.

**Architecture:** A new `ssh_fallback.py` module wraps `asyncssh` to open a per-attempt SOCKS5 tunnel (no persistent tunnel, no subprocess). `feed_parser.py`'s fetch function is split into a single-attempt helper (parameterized by an optional proxy URL) and a public wrapper that tries direct first, then retries through the tunnel on failure, combining both error messages if both fail.

**Tech Stack:** `asyncssh` (new dependency, pure-Python async SSH client), `httpx[socks]` (adds `socksio`, needed for `httpx.AsyncClient(proxy="socks5://...")`), `pytest` + `pytest-asyncio` + `unittest.mock` (already in the project) for tests.

## Global Constraints

- Fallback must be fully optional: if any of `SSH_FALLBACK_HOST`/`SSH_FALLBACK_USER`/`SSH_FALLBACK_KEY_PATH` is unset, behavior is identical to today (direct fetch, direct error on failure).
- No Docker changes — this deployment is native (venv + systemd via `install.sh`), not containerized.
- Host key verification is disabled (`known_hosts=None`) — accepted tech debt, tracked via a follow-up bd issue (Task 1, final step).
- Tunnel lifecycle is per-feed (open + close around a single retry), never persistent across an ingestion cycle.
- Combined error format on double failure: `"{direct_error}; fallback also failed: {proxy_error}"` (exact string, used by a test assertion).
- Tests cannot be executed in this environment (broken editable dependency `-e /opt/jano` in `requirements.txt` blocks local `pip install`) — must be run and verified on the user's homelab or CI before this is considered shipped.

---

### Task 1: SSH fallback tunnel module

**Files:**
- Create: `backend/app/services/ssh_fallback.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Modify: `backend/requirements.txt`
- Test: `backend/tests/test_ssh_fallback.py`

**Interfaces:**
- Produces: `app.services.ssh_fallback.socks_tunnel()` — async context manager, `async with socks_tunnel() as proxy_url:` where `proxy_url` is `Optional[str]`. Yields `None` when the fallback isn't configured (any of host/user/key_path missing). Yields `"socks5://127.0.0.1:{port}"` when configured, tearing the tunnel down on exit.
- Consumes: `app.config.settings.ssh_fallback_host` (`Optional[str]`), `.ssh_fallback_user` (`Optional[str]`), `.ssh_fallback_port` (`int`, default `22`), `.ssh_fallback_key_path` (`Optional[str]`).

- [ ] **Step 1: Add SSH fallback settings to `config.py`**

Modify `backend/app/config.py`. Change the top imports from:

```python
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict
```

to:

```python
from pathlib import Path
from typing import Optional

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict
```

Then add the new settings fields right after the existing `proxy_max_size_bytes` line (which reads `proxy_max_size_bytes: int = 5_242_880  # 5MB`):

```python
    # Proxy
    proxy_timeout_seconds: int = 10
    proxy_max_size_bytes: int = 5_242_880  # 5MB

    # SSH Fallback (feed fetch) — retry via SOCKS tunnel when direct fetch fails.
    # Unset (default) disables the fallback entirely.
    ssh_fallback_host: Optional[str] = None
    ssh_fallback_user: Optional[str] = None
    ssh_fallback_port: int = 22
    ssh_fallback_key_path: Optional[str] = None
```

- [ ] **Step 2: Document the new env vars in `.env.example`**

Modify `backend/.env.example`. Insert a new section between the existing `Proxy` section and the `Authentication` section. Find:

```
# Maximum size for fetched content (bytes)
PROXY_MAX_SIZE_BYTES=5242880

# -----------------------------------------------------------------------------
# Authentication
# -----------------------------------------------------------------------------
```

Replace with:

```
# Maximum size for fetched content (bytes)
PROXY_MAX_SIZE_BYTES=5242880

# -----------------------------------------------------------------------------
# SSH Fallback (feed fetch)
# -----------------------------------------------------------------------------

# When a feed fetch fails directly (timeout, connection error, HTTP error,
# etc.), retry once through a SOCKS5 tunnel over SSH to this host. Leave all
# four unset to disable (default) — direct-fetch errors are reported as-is.
SSH_FALLBACK_HOST=
SSH_FALLBACK_USER=
SSH_FALLBACK_PORT=22
SSH_FALLBACK_KEY_PATH=

# -----------------------------------------------------------------------------
# Authentication
# -----------------------------------------------------------------------------
```

- [ ] **Step 3: Add dependencies to `requirements.txt`**

Modify `backend/requirements.txt`. Find:

```
# Parsing de feeds e conteúdo
feedparser>=6.0.0
httpx>=0.26.0
readability-lxml>=0.8.0
lxml>=5.0.0
lxml-html-clean>=0.1.0
bleach>=6.1.0
```

Replace with:

```
# Parsing de feeds e conteúdo
feedparser>=6.0.0
httpx[socks]>=0.26.0
readability-lxml>=0.8.0
lxml>=5.0.0
lxml-html-clean>=0.1.0
bleach>=6.1.0

# SSH SOCKS fallback for blocked feed fetches (opened on demand, per attempt)
asyncssh>=2.14.0
```

- [ ] **Step 4: Write the failing tests**

Create `backend/tests/test_ssh_fallback.py`:

```python
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
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_ssh_fallback.py -v`
Expected: FAIL / ERROR — `ModuleNotFoundError: No module named 'app.services.ssh_fallback'` (module doesn't exist yet).

Note: if this environment can't run pytest at all (see Global Constraints — broken `-e /opt/jano` editable dependency), skip execution here and run this step on the homelab/CI instead. Do not skip *writing* the test.

- [ ] **Step 6: Implement `ssh_fallback.py`**

Create `backend/app/services/ssh_fallback.py`:

```python
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
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_ssh_fallback.py -v`
Expected: 2 passed (run on homelab/CI if this environment can't install deps locally).

- [ ] **Step 8: File the host-key-pinning follow-up**

Run: `bd create --title="Pin SSH host key for feed-fetch fallback instead of known_hosts=None" --description="ssh_fallback.py disables host key verification (known_hosts=None) as a deliberate shortcut when the feature shipped (see docs/superpowers/specs/2026-07-16-ssh-fallback-fetch-design.md). Follow up by pinning the remote server's actual host key fingerprint instead of trusting blindly." --type=task --priority=3`

- [ ] **Step 9: Commit**

```bash
cd /Users/janiosarmento/projects/risos
git add backend/app/services/ssh_fallback.py backend/app/config.py backend/.env.example backend/requirements.txt backend/tests/test_ssh_fallback.py
git commit -m "feat: add on-demand SSH SOCKS fallback tunnel for blocked feed fetches"
```

---

### Task 2: Wire fallback retry into `feed_parser.py`

**Files:**
- Modify: `backend/app/services/feed_parser.py`
- Test: `backend/tests/test_feed_parser_fallback.py`

**Interfaces:**
- Consumes: `app.services.ssh_fallback.socks_tunnel()` (from Task 1) — async context manager yielding `Optional[str]`.
- Produces: `fetch_feed_content(url: str) -> Tuple[bytes, Optional[str]]` (unchanged public signature) now retries via the fallback tunnel on failure. Internal helper `_fetch_feed_content_once(url: str, proxy: Optional[str] = None) -> Tuple[bytes, Optional[str]]` — same body as the current `fetch_feed_content`, minus the `is_safe_external_url` check, plus `proxy=proxy` passed to `httpx.AsyncClient`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_feed_parser_fallback.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_feed_parser_fallback.py -v`
Expected: FAIL — `AttributeError: module 'app.services.feed_parser' has no attribute '_fetch_feed_content_once'` (and no `socks_tunnel` import yet).

Note: if this environment can't run pytest locally, run this on the homelab/CI instead. Do not skip writing the tests.

- [ ] **Step 3: Refactor `feed_parser.py` to extract the single-attempt helper and wire the retry**

Modify `backend/app/services/feed_parser.py`. Add the import, right after the existing imports:

```python
# Configuration
from app.config import USER_AGENT
from app.services.ssh_fallback import socks_tunnel
from app.services.url_safety import is_safe_external_url
```

Then replace the entire `fetch_feed_content` function (currently lines 120-203) with:

```python
async def _fetch_feed_content_once(
    url: str, proxy: Optional[str] = None
) -> Tuple[bytes, Optional[str]]:
    """
    Make a single fetch attempt for feed content via HTTP.

    Args:
        url: Feed URL
        proxy: Optional proxy URL (e.g. "socks5://127.0.0.1:1080") to route
            this attempt through

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
        headers={"User-Agent": USER_AGENT},
        proxy=proxy,
    ) as client:
        current_url = url

        while redirects_followed <= MAX_REDIRECTS:
            try:
                response = await client.get(current_url)

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


async def fetch_feed_content(url: str) -> Tuple[bytes, Optional[str]]:
    """
    Fetch feed content via HTTP, retrying once through an SSH SOCKS fallback
    tunnel if the direct attempt fails.

    Returns:
        Tuple of (content in bytes, final URL after redirects)

    Raises:
        FeedFetchError: If unable to fetch the feed directly and (if
            configured) via the fallback tunnel
    """
    if not is_safe_external_url(url):
        raise FeedFetchError("Unsafe or internal URL")

    try:
        return await _fetch_feed_content_once(url, proxy=None)
    except FeedFetchError as direct_error:
        async with socks_tunnel() as proxy_url:
            if proxy_url is None:
                raise
            try:
                return await _fetch_feed_content_once(url, proxy=proxy_url)
            except FeedFetchError as proxy_error:
                raise FeedFetchError(
                    f"{direct_error}; fallback also failed: {proxy_error}"
                ) from proxy_error
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_feed_parser_fallback.py -v`
Expected: 5 passed (run on homelab/CI if this environment can't install deps locally).

- [ ] **Step 5: Run the full backend test suite to check for regressions**

Run: `cd backend && python -m pytest tests/ -v`
Expected: all tests pass, including the pre-existing `tests/test_language_gate.py` and both new test files (7 tests total across the two new files). Run on homelab/CI if this environment can't install deps locally.

- [ ] **Step 6: Commit**

```bash
cd /Users/janiosarmento/projects/risos
git add backend/app/services/feed_parser.py backend/tests/test_feed_parser_fallback.py
git commit -m "feat: retry feed fetch through SSH fallback tunnel on failure"
```

---

## Post-Implementation

- Bump `APP_VERSION` in `htdocs/index.template.html` only if this change also touches frontend files (it doesn't — backend-only change, no version bump needed).
- Set the four `SSH_FALLBACK_*` values in the homelab's real `backend/.env` (not committed) to actually enable the fallback — this plan ships it disabled by default everywhere until that's done.
- Session close protocol: push after the final commit (`git pull --rebase && git push`).
