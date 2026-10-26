# TODO

- [x] **`install.sh` systemd `PATH` and `ProtectHome` notes.** The unit's
  `PATH` now includes `/usr/local/bin` (for sops); the README's Quick Start
  documents the hardening and that backend-read files belong in `/etc/risos/`.

## Dead-code cleanup (analysis of 2026-10-26)

Ordered for execution. Items interact: removing one often deletes code (or
strings) another item mentions. Before starting each item, re-check its notes
against the current code, and update this list as items land.

- [x] **1. Remove the circuit breaker.** Disabled in `5eea6f7` (2026-04) but
  still mostly present: `CircuitBreaker` in `services/ai/_infrastructure.py`
  (~170 lines, `record_success`/`record_failure` never called, no state ever
  persisted in prod), `CircuitBreakerOpen` (never raised) and its handler in
  `main.py`, the `can_call()` gate in the scheduler's summary worker,
  `POST /admin/reset-circuit-breaker`, the reset button in settings, and the
  "AI state" dot on the status screen (always shows "normal" — misleading).
  `scripts/lib.py`'s `clear_rate_limits()` touches it too. Remove the related
  i18n keys in both locales.
- [x] **2. Collapse `ApiKeyRotator` to a plain key getter.** There is one key
  and no rotation: `get_next_key` is unused, `set_key_cooldown` only logs,
  `clear_cooldown` is a no-op. Callers: `_api.py` (3 cooldown calls),
  `admin.py` queue status (`get_status()`), `scheduler.py`
  (`has_available_key`), `scripts/translate_all_tags.py` (`_get_keys`),
  `scripts/lib.py`. Its comments are in Portuguese — rewrite in English.
  CLAUDE.md's AI-subsystem bullet still says "key rotation" — fix it too.
- [x] **3. Delete the dead `recover_orphaned_queue()` in `main.py`** (~65
  lines, never called; the endpoint uses its own copy in `admin.py`). Drop the
  `NOTE` comment that points at it.
- [x] **4. Drop unused dependencies `apscheduler` and `psutil`** from
  `requirements.txt` (never imported by the app, scripts, tests, or Jano on
  the server). Keep `lxml`, `lxml-html-clean`, `python-multipart` (indirect).
  Translate the Portuguese section comments in the file while there.
  README (tech stack) and CLAUDE.md (`lifespan` bullet) still name
  APScheduler — the scheduler is plain asyncio loops; fix both.
- [x] **5. Drop the `summary_failures` table.** Nothing writes to it anymore
  (594 stale rows in prod). Remove the model, the `failures_count` in
  `GET /admin/status` and its UI, the delete in `reprocess-summary`, and add an
  Alembic migration that drops the table.
- [x] **6. Drop unused columns/relationships.** `Feed.allow_duplicate_urls`
  (no API/UI sets it, 0 everywhere in prod — also remove its branch in
  `feed_ingestion.py`), `Feed.last_error_at` (written, never read),
  `Post.summary_queue_entry` (relationship, unused — KEPT: it is the ORM
  cascade that deletes queue entries when a feed is deleted). Decide on `cleanup_logs`
  (written on every cleanup, 1,278 rows, never read): drop it, or show it on
  the status screen. One Alembic migration for the schema changes.
- [x] **7. Remove API routes the frontend never calls.** Removed the image
  proxy, `posts/{id}/redirect`, `categories/reorder`, `suggestions/status`,
  and the curl-only ops tools (`reprocess-summary`, `vacuum`, `queue-status`,
  `recover-orphaned-queue`, `diagnose-queue`) with their schemas, helpers and
  error strings. `clear-queue-cooldowns` stays (Settings' "Reset AI queue").
- [x] **8. Delete broken maintenance scripts.** Deleted
  `scripts/smart_merge_tags.py` (tag merging lives in Settings) and the Ollama
  `--local` mode of `regenerate.py`/`lib.py`. Also fixed `lib.py` hashing
  posts with its own formula instead of the app's `compute_content_hash`.
- [x] **9. Remove the Docker setup.** Deleted `backend/Dockerfile`,
  `docker-compose.yml`, the README's Docker section and `GET /health`.
- [x] **10. Remove unused i18n keys.** Removed 18 keys from both locales
  (`modal.*` shortcut hints, `time.daysAgo`/`hoursAgo`, `settings.status.title`,
  `backendErrors.Feed_is_disabled`, …). `meta.languageName` stays: the
  backend's `GET /admin/locales` reads it.
- [x] **11. Clean up stray repo files.** Deleted `reasonix.toml`,
  `install-litellm.sh`, `.superpowers/`, `docs/superpowers/`, `docs/history/`,
  `AI.md` and `screenshots/` (README section removed; retake after the docs
  review). Dropped the stale `JWT_SECRET` from the README, `CEREBRAS_API_KEY`
  from `install.sh`, and rewrote `backend/.env.example` to the variables
  `config.py` actually reads.
- [x] **12. Translate remaining Portuguese in backend code to English.**
  The related-posts consolidation endpoint (errors, prompt — which now follows
  the summary-language setting instead of hardcoding Brazilian Portuguese —
  and comments; AI errors now reach the app's AI error handlers), `schemas.py`
  docstrings, `alembic/env.py`, `main.py`, `preferences.py`. Added
  `backendErrors.*` keys for every backend error message that lacked one.
- [ ] **13. Re-run the dead-code scan** to catch what the cleanup exposed:
  `vulture app scripts --min-confidence 60` (ignore route handlers and
  Pydantic fields), routes vs. frontend `fetchApi` calls, unused i18n keys,
  unread model columns, unimported requirements.
- [x] **14. Silence gunicorn's control-server error.** `install.sh` passes
  `--no-control-socket` (gunicorn pinned to >=25.3.0); prod's unit file was
  patched the same way (backup at `risos.service.bak-20261026`).
- [x] **15. Find what leaves orphan `post_tags` rows.** The 8 rows all
  belonged to one post (95744, fetched and tagged 2026-09-09, deleted soon
  after). No code path explains that one; retention can't have (the post was
  too new) and feed deletes cascade, so it was most likely a manual delete.
  Retention's bulk deletes did skip the cascade, though — a latent source of
  orphan tags and queue entries. `delete_posts()` in the scheduler now deletes
  them explicitly, and migration `a7d2e9c41f03` removes the existing orphans.
