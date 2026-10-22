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
