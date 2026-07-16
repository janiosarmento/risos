# SSH SOCKS Fallback for Feed Fetch

**Date:** 2026-07-16
**Status:** Approved

## Problem

Feeds are fetched directly from the homelab's residential/home connection, which
some feed origins block, throttle, or route poorly to — causing timeouts and
connection errors. The same origins respond immediately (HTTP 200) when
reached from the user's remote server in Canada (`137.184.104.65`). This is a
network/routing issue, not an application bug — raising the fetch timeout
(10s → 30s, already shipped) doesn't fix it, it just waits longer before
failing the same way.

## Solution

When the direct fetch fails (any `FeedFetchError`), retry once through a SOCKS5
proxy tunneled over SSH to the remote server. The tunnel is opened on demand
for that single retry and torn down immediately after — no persistent tunnel,
no background process. This is expected to trigger rarely (only on feeds the
homelab can't reach directly).

## Design Decisions

### Library: asyncssh (not system `ssh` binary)
Pure Python, async-native, integrates directly with the existing
`asyncio`/`httpx` fetch flow. No external binary, no subprocess lifecycle
management (no waiting for a port to open, no killing zombie processes), no
deployment changes beyond adding a pip dependency. The app has no Docker
dependency in this user's deployment (native systemd via `install.sh`), so
there's no container/apt concern either way, but avoiding a subprocess is
still the simpler, more robust choice.

### Tunnel lifecycle: per-feed, not per-cycle
Each failed feed opens and closes its own tunnel (SSH handshake ~1-2s), rather
than one tunnel reused across a whole ingestion cycle. Simpler lifecycle, no
risk of a leaked/orphaned tunnel if the job crashes mid-cycle. Acceptable
overhead since this is expected to be rare per the "Problem" section.

### Fallback trigger: any fetch failure
Not limited to timeout/connection errors — any `FeedFetchError` (including
HTTP 4xx which could indicate geo-blocking) triggers the proxy retry.

### Host key verification: disabled (tech debt, tracked)
Container/process is ephemeral with no persisted `known_hosts`. Using
`known_hosts=None` in asyncssh disables host key verification — accepted
risk for now (user's own infrastructure, single-purpose outbound fallback).
**Follow-up needed:** pin the remote server's host key fingerprint instead of
trusting blindly. File a bd issue for this before considering the feature
fully hardened.

### Configuration: env vars, off by default
```
SSH_FALLBACK_HOST=137.184.104.65
SSH_FALLBACK_USER=janio
SSH_FALLBACK_PORT=22
SSH_FALLBACK_KEY_PATH=/home/janio/.ssh/id_ed25519
```
Added to `backend/.env.example` (with placeholder values) and `config.py`
(`Settings`). If any required var is unset, the fallback is a no-op — direct
fetch failures propagate as before, no behavior change for anyone who hasn't
configured it. No key path since this deploy is native (no container to mount
into) — the path is read directly from the host filesystem, no Docker changes.

### Error message on double failure
If both direct and proxy attempts fail, `last_error` (shown in the sidebar
tooltip) combines both:
```
{direct_error}; fallback also failed: {proxy_error}
```
If the fallback isn't configured, the direct error is reported as-is (no
mention of a fallback that was never attempted).

## Implementation Scope

1. **`backend/app/services/ssh_fallback.py`** (new) — async context manager
   `socks_tunnel()`:
   - Reads `SSH_FALLBACK_*` settings; if any required value is missing,
     yields `None` (no-op fallback).
   - Otherwise connects via `asyncssh.connect(host, port, username, client_keys=[key_path], known_hosts=None)`.
   - Opens a dynamic SOCKS listener on an OS-assigned local port
     (`forward_socks('127.0.0.1', 0)`), yields the proxy URL
     `socks5://127.0.0.1:{port}`.
   - Closes the listener and connection on exit (context manager `finally`).
2. **`backend/app/services/feed_parser.py`** — extract the current fetch
   logic into a helper parameterized by an optional `proxy: str | None`
   (passed to `httpx.AsyncClient(proxy=...)`). On `FeedFetchError` from the
   no-proxy attempt, retry once inside `socks_tunnel()`; if that also raises,
   combine both messages per the format above.
3. **`backend/app/config.py`** — add `ssh_fallback_host`, `ssh_fallback_user`,
   `ssh_fallback_port` (default `22`), `ssh_fallback_key_path` settings
   (all optional/`None` by default).
4. **`backend/.env.example`** — document the four env vars under a new
   "SSH Fallback (feed fetch)" section, following the existing
   `PROXY_TIMEOUT_SECONDS`-style comments.
5. **`backend/requirements.txt`** — add `asyncssh` and change `httpx>=0.26.0`
   to `httpx[socks]>=0.26.0` (pulls in `socksio`, required for
   `httpx.AsyncClient(proxy="socks5://...")`).
6. **Tests** — unit tests for `ssh_fallback.py` (mocking `asyncssh.connect`)
   and for the retry-on-failure path in `feed_parser.py`. Cannot be executed
   in this environment (local backend has a broken editable dependency in
   `requirements.txt` — known, pre-existing limitation); must be verified on
   the user's homelab or via CI before considering this shipped.
7. **Follow-up bd issue**: pin SSH host key fingerprint instead of
   `known_hosts=None`.

## Out of Scope

- Persistent/always-on tunnel (autossh or similar)
- Host key pinning (tracked as follow-up, not blocking)
- UI indication that a post/feed succeeded via fallback vs. direct
- Retrying more than once per feed per cycle (still governed by existing
  `next_retry_at` backoff for the *next* scheduled cycle)
