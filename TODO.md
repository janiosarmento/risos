# TODO

- [ ] **`install.sh` generates a systemd `PATH` without `/usr/local/bin`.** The
  unit gets `Environment="PATH=$BACKEND_DIR/venv/bin"`, so `sops` (used by Jano
  to decrypt secrets) isn't found after a restart and AI summaries stop working.
  Prod was patched by hand in the drop-in `override.conf`
  (`/usr/local/bin:/usr/bin:/bin`); a fresh install would regress. Fix
  `install.sh` and document it in the README's deploy notes.
- [ ] **Document that `ProtectHome=true` hides `/home` from the service.** Any
  file the backend must read belongs under `/etc/risos/` (or an explicit
  `ReadWritePaths`/exception), never the deploying user's home. Add this to the
  README's deploy notes.

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
- [ ] **10. Remove unused i18n keys** (after 1, 5 and 7, which orphan more
  strings — re-scan first). As of the analysis: `modal.closeEsc`,
  `modal.markRead`, `modal.markUnread`, `modal.starShortcut`,
  `modal.navShortcuts`, `modal.selectAllRelated`, `modal.selectNoneRelated`,
  `settings.aiSummaries`, `settings.backgroundAiModelPlaceholder`,
  `settings.checkSecretName`, `tags.filterTooltip`, and the stale
  `backendErrors.Feed_is_disabled`. `backendErrors.*` keys are looked up
  dynamically from the error text, so check them against backend messages.
- [ ] **11. Clean up stray repo files.** `reasonix.toml` and
  `install-litellm.sh` (unreferenced; the latter installs a LiteLLM proxy for
  the Anthropic API, unrelated to Risos), `.superpowers/brainstorm/` (tool
  state, even a `server.pid`), finished plans in `docs/superpowers/` and
  `docs/history/`. `AI.md` (May 2026 developer guide superseded by
  CLAUDE.md; still says single-worker + APScheduler). `screenshots/` (2025-12) predates the Material 3 redesign —
  retake or drop, then fix the README.
- [ ] **12. Translate remaining Portuguese in backend code to English.** Error
  messages (e.g. "Nenhum post selecionado para consolidar", "Posts não
  encontrados", "Erro ao processar consolidação no LLM") and comments.
  Earlier items delete some of it, so do this late and re-grep. Translated
  error messages need matching `backendErrors.*` keys in both locales.
- [ ] **13. Re-run the dead-code scan** to catch what the cleanup exposed:
  `vulture app scripts --min-confidence 60` (ignore route handlers and
  Pydantic fields), routes vs. frontend `fetchApi` calls, unused i18n keys,
  unread model columns, unimported requirements.
- [ ] **14. Silence gunicorn's control-server error.** Every start logs
  `Control server error: [Errno 30] Read-only file system:
  '/var/www/.gunicorn'` (841 times since 2026-04). gunicorn 25's control
  socket defaults to the user's home, which systemd hardening makes read-only.
  Harmless noise: disable the control server or point it at a writable path
  (e.g. under `backend/data/`) in `install.sh` and the prod drop-in.
- [ ] **15. Find what leaves orphan `post_tags` rows.** `post_tags` has 8 rows
  whose `post_id` no longer exists (same 8 locally and in prod, out of ~552k,
  found by `PRAGMA foreign_key_check` on 2026-10-26). Some path deletes posts
  without their tags — SQLite runs without `PRAGMA foreign_keys`, so only the
  ORM cascade or explicit deletes clean up. Suspects: the retention cleanup's
  bulk `query(Post).delete()` and other bulk deletes. Find the path, fix it,
  delete the orphans.
