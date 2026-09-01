# Project Instructions for AI Agents

This file provides instructions and context for AI coding agents working on this project.

## Session Completion

When wrapping up a change:

1. **Run quality gates** (if code changed) — tests, linters, builds
2. **Regenerate static HTML** (if front-end changed) — `cd backend && python -m app.html_assembler` to sync `index.html` and `manifest.json` from `index.template.html`
3. **Commit and push** — work is not done until `git push` succeeds

## Build & Test

```bash
# Backend — from backend/
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt            # pins `-e /opt/jano` (prod-only secret manager)
uvicorn app.main:app --reload --port 8100  # migrations + HTML assembler run on startup

# Lint — config in backend/pyproject.toml (ruff, line-length 88, rules E/F/I/W)
ruff check .
ruff check --fix .

# Tests — from backend/, venv active
pytest
```

Caveats (verified, not guesses):

- `requirements.txt` has an editable dep on `/opt/jano` that only exists on the
  deployment host, so a clean `pip install` off that host fails. Review/verify
  pure logic by reading, or by importing a single module with stubbed constants
  (`app.services.ai._constants` is the usual stub point).
- `pytest` needs `APP_PASSWORD` set and can't collect the full suite off the prod
  host (same `/opt/jano` reason). Real tests that exist: `tests/test_language_gate.py`,
  `tests/test_feed_parser_fallback.py`, `tests/test_ssh_fallback.py` (async via
  `@pytest.mark.asyncio`).
- No JS build and no JS test runner. Check frontend edits with
  `node --check htdocs/static/js/<file>.js`.

Front-end change checklist:

1. Edit `htdocs/index.template.html` and/or `htdocs/static/js/*`.
   **`index.template.html` is the source of truth**; `index.html` is generated.
2. Bump `APP_VERSION` in `htdocs/index.template.html` (format `YYYYMMDD[letra]`,
   see Versioning below).
3. `cd backend && python -m app.html_assembler` — regenerates `htdocs/index.html`
   and `htdocs/manifest.json`. **Never run the assembler on the server** (systemd
   hardening makes the checkout read-only).
4. Commit + push.

Deploy (run on the server): `./deploy.sh` — `git fetch` + `reset --hard
origin/main` as the checkout owner, restart the systemd service, poll HTTP
health. Env overrides are documented in the script header.

## Architecture Overview

Risos is a single-user, self-hosted RSS reader: FastAPI + SQLite backend, a
zero-build Alpine.js frontend, and an OpenAI-compatible LLM used for per-article
summaries/tags and for grouping tags into topics.

### Backend (`backend/app/`)

- **Entrypoint** `main.py` — builds the FastAPI app, mounts every router under
  `/api`, and a `lifespan` that (1) runs the HTML assembler, (2) runs Alembic
  migrations to `head` under an `flock` (safe with >1 gunicorn worker), (3) starts
  the APScheduler background jobs. Exception handlers map the AI subsystem's typed
  errors (`TemporaryError`, `RateLimited`, `PermanentError`, `CircuitBreakerOpen`,
  …) to HTTP 502.
- **Routes** `app/routes/*.py` — one module per resource: `auth`, `feeds`,
  `categories`, `posts` (the large one: list/filter/read-state/curation), `tags`,
  `topics`, `preferences`, `admin`, `suggestions`, `proxy` (image/CORS proxy).
  All runtime settings live in the `app_settings` table and are read through
  `get_effective_*` helpers in `preferences.py`.
- **Services** `app/services/*` — feed fetch/parse (`feed_parser`,
  `feed_ingestion`, `content_extractor`, `html_sanitizer`, `ssh_fallback` for
  Cloudflare-blocked feeds); `scheduler.py` (feed refresh, summary-queue worker,
  retention cleanup, DB-size guard — serialized across workers via the
  `scheduler_lock` row); and `ai/`.
- **AI subsystem** `app/services/ai/` — `_api.py` orchestrates OpenAI-compatible
  calls (`generate_summary`, `call_llm_json`, `call_llm_text`) with key rotation,
  a circuit breaker (`_infrastructure.py`), and per-model cooldowns; `_parsing.py`
  hardens JSON extraction from weaker models (strips reasoning wrappers, tolerates
  unclosed fences, repairs truncated JSON); `_language_gate.py` re-translates
  summary sentences that came back in the wrong language. Endpoint, key(s), model,
  and timeout all come from `preferences` (`pref_api_base_url`,
  `pref_ai_api_keys`, `pref_ai_model`, …). The "Cerebras" naming in this code is
  historical — any OpenAI-compatible endpoint works, but the base URL and the key
  must belong to the same provider.
- **Data** `models.py` + Alembic (`backend/alembic/versions/`). SQLite in WAL
  mode; connection pragmas and covering indexes are set in `database.py`. Key
  tables: `feeds`/`categories`; `posts` + `post_tags` (per-article tags from the
  LLM); `topics` + `topic_tags` (named groups of tags — a post is "in" a topic if
  it shares any of the topic's tags, so one post can be in several topics);
  `ai_summaries` keyed by `content_hash`; `summary_queue`; `app_settings`;
  `user_sessions`.
- **Topic count cache** `app/topics_cache.py` — the sidebar's per-topic
  post/unread counts come from an expensive `GROUP BY` over `post_tags`, cached
  in-process for 60s. **Anything that mutates post read-state or topic/tag
  membership must call `topics_cache.invalidate()`** — the post routes, the topic
  routes, and the retention cleanup job already do.

### Frontend (`htdocs/`)

- **Zero build.** `index.template.html` is authored by hand (Tailwind + Alpine.js
  via CDN); `backend/app/html_assembler.py` resolves `<!-- INCLUDE ... -->`
  directives and substitutes `APP_VERSION` into every `?v=` cache-buster,
  producing `index.html` + `manifest.json`. The committed `index.html` is what
  production serves.
- **JS layout** (`htdocs/static/js/`, ordered `<script defer>`): `stores/` =
  `Alpine.store()` for shared/framework state (`auth` incl. `fetchApi()` with
  transient-retry, `i18n`, `ui`, `prefs`); `components/` = plain objects spread
  into `app()` as mixins (`postDetail`, `settings`, `curation`) so `this` stays
  the app scope; `app.js` = the `app()` factory and orchestration. Rationale in
  `htdocs/static/js/ARCHITECTURE.md`.
- **i18n** `htdocs/static/locales/{en-US,pt-BR}.json`, referenced as `t('a.b.c')`.

### Deploy / ops

Production is a single box: gunicorn (`uvicorn.workers.UvicornWorker`, 2 workers)
behind nginx + a Cloudflare tunnel; the systemd unit is generated by `install.sh`
(hardened — `ProtectSystem=strict`, `ProtectHome`, read-only FS except
`backend/data/`, `PYTHONUNBUFFERED=1` so tracebacks reach the log immediately).
Deploys via `./deploy.sh`.

## Conventions & Patterns

### Commit Messages

Use [Conventional Commits](https://www.conventionalcommits.org):

```
<type>: <descrição imperativa em inglês>
```

Types: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`

Exemplos:
- `feat: add keyboard shortcut for marking all as read`
- `fix: resolve relative URLs in feed entries`
- `docs: document versioning convention`
- `refactor: extract URL resolution to helper function`

### Versioning

A versão do app fica em `htdocs/index.html`:

```html
<script>var APP_VERSION = 'YYYYMMDD[letra]';</script>
```

Formato: data do dia (`YYYYMMDD`) + sufixo de letra incrementado a cada build do dia (`a`, `b`, `c`, ...).

**A cada commit com mudança de código, atualizar a versão antes de commitar.**

Exemplos:
- Primeiro build do dia 2026-05-09 → `20260509a`
- Segundo build no mesmo dia → `20260509b`
- Primeiro build do dia seguinte → `20260510a`
