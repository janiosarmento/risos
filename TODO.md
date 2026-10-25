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
- [ ] **Partial indexes on `is_starred`/`is_suggested`/`is_liked` are never
  used.** They are declared `WHERE x = 1`, but SQLAlchemy's `.is_(True)` emits
  `x IS 1`, and SQLite only picks a partial index when the query repeats its
  WHERE term exactly. Recreate them as `WHERE x IS 1` (as
  `idx_posts_keep_unread` already is) after checking `EXPLAIN QUERY PLAN` for
  the starred/suggested queries.
- [ ] **Story grouping costs ~1s of CPU per rebuild** (most of it in
  `_add_summary_pairs`). It now runs off the request path, but still holds the
  GIL while it runs. Either speed it up or compute it in the scheduler and
  store the story ids.
