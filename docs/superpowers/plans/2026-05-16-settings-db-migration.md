# Settings Migration: Env Vars → Database

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove all operational settings from environment variables, keeping only true bootstrap settings (app_password, jwt_secret, database_path, log_level, cors_origins) in `.env`.

**Architecture:** Settings already in DB drop their `env_settings` fallback (hardcode the defaults instead). New operational settings (ai_timeout) get PREF constants, `get_effective_*` functions, and UI. Internal tuning params (circuit breaker, scheduler timing) move to hardcoded constants in `_constants.py` — no env, no UI. Result: `.env` becomes a 5-line bootstrap file.

**Tech Stack:** Python/FastAPI, SQLite via SQLAlchemy, pydantic-settings (kept only for bootstrap), Alpine.js frontend.

---

## File Map

| File | Change |
|---|---|
| `backend/app/config.py` | Remove 15+ operational fields; keep only bootstrap |
| `backend/app/routes/preferences.py` | Add `PREF_AI_TIMEOUT`, `get_effective_ai_timeout`; remove all `env_settings.xxx` fallbacks |
| `backend/app/routes/admin.py` | Replace `settings.toast_timeout_seconds` / `settings.idle_refresh_seconds` with `get_effective_*` calls |
| `backend/app/services/cerebras/_constants.py` | Add `CB_*` circuit breaker constants, `AI_MAX_RPM`, `SUMMARY_LOCK_TIMEOUT_SECONDS`, `CLEANUP_HOUR` |
| `backend/app/services/cerebras/_api.py` | Pass `timeout` param to `_call_model`; read from `get_effective_ai_timeout(db)` |
| `backend/app/services/cerebras/_infrastructure.py` | Replace `settings.failure_threshold`, `settings.recovery_timeout_seconds`, `settings.half_open_max_requests`, `settings.cerebras_max_rpm` with constants |
| `backend/app/services/scheduler.py` | Replace `settings.summary_lock_timeout_seconds`, `settings.cleanup_hour` with constants |
| `htdocs/static/js/stores/prefs.js` | Add `aiTimeout: 30` |
| `htdocs/static/js/app.js` | Add `aiTimeout` getter/setter |
| `htdocs/static/js/components/settings.js` | Add `aiTimeout` to save and load |
| `htdocs/index.html` | Add timeout number input in AI settings section; bump APP_VERSION |
| `htdocs/static/locales/en-US.json` | Add `"aiTimeout"` key |
| `htdocs/static/locales/pt-BR.json` | Add `"aiTimeout"` key |

---

## Task 1: Add PREF_AI_TIMEOUT to preferences.py

**Files:**
- Modify: `backend/app/routes/preferences.py`

- [ ] **Step 1: Add PREF constant**

  After the existing PREF block (around line 46), add:
  ```python
  PREF_AI_TIMEOUT = "pref_ai_timeout"
  ```

- [ ] **Step 2: Add field to response and update schemas**

  In `PreferencesResponse` (the class with `cerebras_model`, `feed_update_interval`, etc.), add:
  ```python
  ai_timeout: int = 30
  ```

  In `PreferencesUpdate` (the class with `Optional` fields for save), add:
  ```python
  ai_timeout: Optional[int] = None
  ```

- [ ] **Step 3: Include PREF_AI_TIMEOUT in the batch fetch**

  In `get_preferences()`, where the list of keys is passed to the bulk-fetch call (around line 140-160), add `PREF_AI_TIMEOUT` to the list.

- [ ] **Step 4: Populate field in get_preferences() response**

  In the `PreferencesResponse(...)` constructor call, add:
  ```python
  ai_timeout=int_or_default(prefs[PREF_AI_TIMEOUT], 30),
  ```

- [ ] **Step 5: Add save logic in save_preferences()**

  In `save_preferences()` / `update_ai_settings()` (whichever handles AI settings), add:
  ```python
  if prefs.ai_timeout is not None:
      _set_setting(db, PREF_AI_TIMEOUT, str(prefs.ai_timeout))
  ```

- [ ] **Step 6: Add get_effective_ai_timeout function**

  After `get_effective_cerebras_model`, add:
  ```python
  def get_effective_ai_timeout(db: Session) -> int:
      """Get AI request timeout from app_settings or default 30s."""
      saved = _get_setting(db, PREF_AI_TIMEOUT)
      return int(saved) if saved else 30
  ```

- [ ] **Step 7: Commit**
  ```bash
  git add backend/app/routes/preferences.py
  git commit -m "feat: add ai_timeout preference to database"
  ```

---

## Task 2: Update _api.py to use db-stored timeout

**Files:**
- Modify: `backend/app/services/cerebras/_api.py`

Currently `_call_model` reads `settings.cerebras_timeout` directly. We'll pass timeout as a parameter.

- [ ] **Step 1: Update _call_model signature**

  Change:
  ```python
  async def _call_model(
      model: str, api_key: str, key_index: int, messages: list
  ) -> SummaryResult:
  ```
  To:
  ```python
  async def _call_model(
      model: str, api_key: str, key_index: int, messages: list, timeout: int = 30
  ) -> SummaryResult:
  ```

- [ ] **Step 2: Replace settings.cerebras_timeout in _call_model**

  Line ~214 — replace:
  ```python
  timeout=settings.cerebras_timeout,
  ```
  With:
  ```python
  timeout=timeout,
  ```

  Line ~364 — replace:
  ```python
  raise TemporaryError(f"Timeout after {settings.cerebras_timeout}s")
  ```
  With:
  ```python
  raise TemporaryError(f"Timeout after {timeout}s")
  ```

- [ ] **Step 3: Read timeout in _generate_summary_locked and pass to _call_model**

  In `_generate_summary_locked`, where the DB session is open and `get_effective_cerebras_model` is called, add:
  ```python
  from app.routes.preferences import (
      get_effective_summary_language,
      get_effective_cerebras_model,
      get_effective_ai_timeout,
  )
  # ...
  ai_timeout = get_effective_ai_timeout(db)
  ```

  Then update the call:
  ```python
  result = await _call_model(preferred_model, api_key, key_index, messages, ai_timeout)
  ```

- [ ] **Step 4: Read timeout in _call_llm_json_locked**

  In `_call_llm_json_locked`, where the DB session is open and `get_effective_cerebras_model` is called, add:
  ```python
  from app.routes.preferences import get_effective_cerebras_model, get_effective_ai_timeout
  # ...
  ai_timeout = get_effective_ai_timeout(db)
  ```

  Replace `timeout=settings.cerebras_timeout` with `timeout=ai_timeout` in the httpx client.

- [ ] **Step 5: Remove settings import if no longer used**

  Search for remaining `settings.` usages in `_api.py`. Remove the `from app.config import settings` import if it's now unused.

- [ ] **Step 6: Commit**
  ```bash
  git add backend/app/services/cerebras/_api.py
  git commit -m "fix: read ai_timeout from database instead of env var"
  ```

---

## Task 3: Move circuit breaker + scheduler params to constants

**Files:**
- Modify: `backend/app/services/cerebras/_constants.py`
- Modify: `backend/app/services/cerebras/_infrastructure.py`
- Modify: `backend/app/services/scheduler.py`

- [ ] **Step 1: Add constants to _constants.py**

  Add after the existing constants:
  ```python
  # Circuit breaker
  CB_FAILURE_THRESHOLD = 5
  CB_RECOVERY_TIMEOUT_SECONDS = 300
  CB_HALF_OPEN_MAX_REQUESTS = 3

  # Scheduler jobs
  SUMMARY_LOCK_TIMEOUT_SECONDS = 300
  CLEANUP_HOUR = 3

  # API rate limiting
  AI_MAX_RPM = 20
  ```

- [ ] **Step 2: Update _infrastructure.py**

  Read the file to find every occurrence of:
  - `settings.failure_threshold`
  - `settings.recovery_timeout_seconds`
  - `settings.half_open_max_requests`
  - `settings.cerebras_max_rpm`
  - `settings.model_cooldown_minutes` (if present — might already use PREF)

  Replace each with the corresponding constant imported from `_constants`:
  ```python
  from app.services.cerebras._constants import (
      CB_FAILURE_THRESHOLD,
      CB_RECOVERY_TIMEOUT_SECONDS,
      CB_HALF_OPEN_MAX_REQUESTS,
      AI_MAX_RPM,
      # ... others already imported
  )
  ```

  Remove `from app.config import settings` from `_infrastructure.py` if it becomes unused.

- [ ] **Step 3: Update scheduler.py**

  Find and replace:
  - `settings.summary_lock_timeout_seconds` → `SUMMARY_LOCK_TIMEOUT_SECONDS`
  - `settings.cleanup_hour` → `CLEANUP_HOUR`

  Add import:
  ```python
  from app.services.cerebras._constants import (
      SUMMARY_LOCK_TIMEOUT_SECONDS,
      CLEANUP_HOUR,
  )
  ```

  Remove the `settings` import from scheduler.py if no longer used there.

- [ ] **Step 4: Commit**
  ```bash
  git add backend/app/services/cerebras/_constants.py \
          backend/app/services/cerebras/_infrastructure.py \
          backend/app/services/scheduler.py
  git commit -m "refactor: move circuit breaker and scheduler params to constants"
  ```

---

## Task 4: Remove env_settings fallbacks from preferences.py

All settings that already have a `PREF_*` key in the DB no longer need `env_settings` as fallback. Replace with hardcoded defaults.

**Files:**
- Modify: `backend/app/routes/preferences.py`

- [ ] **Step 1: Replace each env_settings fallback in get_preferences()**

  In the `PreferencesResponse(...)` constructor:

  | Old | New |
  |---|---|
  | `or env_settings.summary_language` | `or "Brazilian Portuguese"` |
  | `env_settings.feed_update_interval_minutes` | `30` |
  | `env_settings.max_posts_per_feed` | `500` |
  | `env_settings.max_post_age_days` | `365` |
  | `env_settings.max_unread_days` | `90` |
  | `env_settings.toast_timeout_seconds` | `2` |
  | `env_settings.idle_refresh_seconds` | `180` |
  | `env_settings.cerebras_model` | `"llama-3.3-70b"` |
  | `env_settings.cerebras_api_key` | `""` |
  | `env_settings.model_cooldown_minutes` | `30` |

- [ ] **Step 2: Update get_effective_* functions**

  Replace each `return saved or env_settings.xxx` pattern:

  ```python
  def get_effective_summary_language(db: Session) -> str:
      saved = _get_setting(db, PREF_SUMMARY_LANGUAGE)
      return saved or "Brazilian Portuguese"

  def get_effective_cerebras_model(db: Session) -> str:
      saved = _get_setting(db, PREF_CEREBRAS_MODEL)
      return saved or "llama-3.3-70b"

  def get_effective_feed_update_interval(db: Session) -> int:
      saved = _get_setting(db, PREF_FEED_UPDATE_INTERVAL)
      return int(saved) if saved else 30

  def get_effective_max_posts_per_feed(db: Session) -> int:
      saved = _get_setting(db, PREF_MAX_POSTS_PER_FEED)
      return int(saved) if saved else 500

  def get_effective_max_post_age_days(db: Session) -> int:
      saved = _get_setting(db, PREF_MAX_POST_AGE_DAYS)
      return int(saved) if saved else 365

  def get_effective_max_unread_days(db: Session) -> int:
      saved = _get_setting(db, PREF_MAX_UNREAD_DAYS)
      return int(saved) if saved else 90

  def get_effective_toast_timeout(db: Session) -> int:
      saved = _get_setting(db, PREF_TOAST_TIMEOUT)
      return int(saved) if saved else 2

  def get_effective_idle_refresh(db: Session) -> int:
      saved = _get_setting(db, PREF_IDLE_REFRESH)
      return int(saved) if saved else 180

  def get_effective_model_cooldown(db: Session) -> int:
      saved = _get_setting(db, PREF_MODEL_COOLDOWN)
      return int(saved) if saved else 30
  ```

- [ ] **Step 3: Clean up get_effective_cerebras_api_keys**

  Remove the auto-migration block that wrote `env_settings.cerebras_api_key` to DB on first run — it's no longer needed:
  ```python
  def get_effective_cerebras_api_keys(db: Session) -> list:
      saved = _get_setting(db, PREF_CEREBRAS_API_KEYS)
      if not saved:
          return []
      return [k.strip() for k in saved.split(",") if k.strip()]
  ```

- [ ] **Step 4: Remove env_settings import**

  Remove: `from app.config import settings as env_settings`
  (Verify no other references remain first with a quick search.)

- [ ] **Step 5: Commit**
  ```bash
  git add backend/app/routes/preferences.py
  git commit -m "refactor: remove env var fallbacks from preferences, hardcode defaults"
  ```

---

## Task 5: Fix admin.py direct settings usages

**Files:**
- Modify: `backend/app/routes/admin.py`

`admin.py` reads `settings.toast_timeout_seconds` and `settings.idle_refresh_seconds` directly. After removing them from config.py, this will break.

- [ ] **Step 1: Read the relevant section of admin.py**

  Find the block around line 152 where `toast_timeout_seconds` and `idle_refresh_seconds` are used. Identify the function name and whether it has a `db: Session` parameter.

- [ ] **Step 2: Add db parameter if missing, use get_effective_***

  Import:
  ```python
  from app.routes.preferences import get_effective_toast_timeout, get_effective_idle_refresh
  ```

  Replace:
  ```python
  "toast_timeout_seconds": settings.toast_timeout_seconds,
  "idle_refresh_seconds": settings.idle_refresh_seconds,
  ```
  With:
  ```python
  "toast_timeout_seconds": get_effective_toast_timeout(db),
  "idle_refresh_seconds": get_effective_idle_refresh(db),
  ```

  If no `db` session is available in this function, add `db: Session = Depends(get_db)` to the route signature.

- [ ] **Step 3: Commit**
  ```bash
  git add backend/app/routes/admin.py
  git commit -m "fix: use db-stored settings in admin route instead of env vars"
  ```

---

## Task 6: Slim down config.py

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Remove all non-bootstrap fields**

  Fields to **remove** from the `Settings` class:
  - `cerebras_api_key`, `cerebras_model`, `cerebras_api_keys` (property)
  - `cerebras_max_rpm`, `cerebras_timeout`
  - `summary_language`
  - `failure_threshold`, `recovery_timeout_seconds`, `half_open_max_requests`, `model_cooldown_minutes`
  - `max_posts_per_feed`, `max_post_age_days`, `max_unread_days`
  - `feed_update_interval_minutes`, `summary_lock_timeout_seconds`, `cleanup_hour`
  - `toast_timeout_seconds`, `idle_refresh_seconds`

  Fields to **keep**:
  - `database_path`
  - `app_password`, `jwt_secret`, `jwt_expiration_hours`
  - `login_rate_limit`, `api_rate_limit`, `feeds_refresh_rate_limit`
  - `max_db_size_mb`
  - `proxy_timeout_seconds`, `proxy_max_size_bytes`
  - `log_level`, `log_file`
  - `cors_origins`

  The resulting `Settings` class should look like:
  ```python
  class Settings(BaseSettings):
      """Bootstrap configuration — operational settings live in the database."""

      # Database
      database_path: str = "./data/reader.db"

      # Authentication
      app_password: str
      jwt_secret: str
      jwt_expiration_hours: int = 24

      # Rate Limiting HTTP
      login_rate_limit: int = 5
      api_rate_limit: int = 100
      feeds_refresh_rate_limit: int = 10

      # Retention cap (infra-level, not user-configurable)
      max_db_size_mb: int = 1024

      # Proxy
      proxy_timeout_seconds: int = 10
      proxy_max_size_bytes: int = 5_242_880  # 5MB

      # Logging
      log_level: str = "INFO"
      log_file: str = "./data/app.log"

      # Security
      cors_origins: str = "https://rss.sarmento.org"

      model_config = SettingsConfigDict(
          env_file=".env",
          env_file_encoding="utf-8",
          case_sensitive=False,
          extra="ignore",
      )

      def __init__(self, **kwargs):
          super().__init__(**kwargs)
          if len(self.jwt_secret) < 32:
              raise ValueError(
                  f"JWT_SECRET must be at least 32 characters long. "
                  f"Current length: {len(self.jwt_secret)}"
              )
  ```

- [ ] **Step 2: Verify no remaining broken references**

  ```bash
  grep -rn 'settings\.' backend/app --include="*.py" | grep -v '__pycache__' | grep -v '# '
  ```

  Check every hit. Each should reference only a field that still exists in Settings. Fix any that don't.

- [ ] **Step 3: Start the backend and verify it boots**

  ```bash
  cd backend && python -m uvicorn app.main:app --reload
  ```

  Expected: server starts without AttributeError.

- [ ] **Step 4: Commit**
  ```bash
  git add backend/app/config.py
  git commit -m "refactor: slim config.py to bootstrap-only settings"
  ```

---

## Task 7: Add ai_timeout UI to frontend

**Files:**
- Modify: `htdocs/static/js/stores/prefs.js`
- Modify: `htdocs/static/js/app.js`
- Modify: `htdocs/static/js/components/settings.js`
- Modify: `htdocs/index.html`
- Modify: `htdocs/static/locales/en-US.json`
- Modify: `htdocs/static/locales/pt-BR.json`

- [ ] **Step 1: Add state to prefs.js**

  In the `Alpine.store('prefs', { ... })` object, add:
  ```javascript
  aiTimeout: 30,
  ```

- [ ] **Step 2: Add getter/setter to app.js**

  In the `data()` return object (alongside `cerebrasModel` getter/setter), add:
  ```javascript
  get aiTimeout() { return Alpine.store('prefs').aiTimeout; },
  set aiTimeout(v) { Alpine.store('prefs').aiTimeout = v; },
  ```

- [ ] **Step 3: Include in settings.js save**

  In `saveAiSettings()` (or whichever function saves AI settings via PUT), add to the payload:
  ```javascript
  ai_timeout: parseInt(this.aiTimeout) || 30,
  ```

- [ ] **Step 4: Load from server preferences in settings.js**

  In `loadPreferences()` (or wherever `serverPrefs.cerebras_model` is read), add:
  ```javascript
  if (serverPrefs.ai_timeout) this.aiTimeout = serverPrefs.ai_timeout;
  ```

- [ ] **Step 5: Add input to index.html**

  In the AI settings section, after the model selector, add:
  ```html
  <div class="flex flex-col gap-1">
      <label class="text-xs text-zinc-400"
          x-text="$store('i18n').t('settings.aiTimeout')"></label>
      <div class="flex items-center gap-2">
          <input type="number" min="5" max="600"
              x-model.number="aiTimeout"
              @change="saveAiSettings()"
              class="bg-zinc-800 border border-zinc-700 rounded px-3 py-1.5 text-sm text-zinc-100 w-24" />
          <span class="text-xs text-zinc-500">s</span>
      </div>
  </div>
  ```

- [ ] **Step 6: Add i18n keys**

  `en-US.json` — in the `settings` object:
  ```json
  "aiTimeout": "AI Timeout"
  ```

  `pt-BR.json` — in the `settings` object:
  ```json
  "aiTimeout": "Timeout da IA"
  ```

- [ ] **Step 7: Bump APP_VERSION in index.html**

  Current format is `YYYYMMDD[letter]`. If today's date is already used, increment the letter.

- [ ] **Step 8: Commit**
  ```bash
  git add htdocs/
  git commit -m "feat: add AI timeout setting to UI"
  ```

---

## Task 8: Final verification + push

- [ ] **Step 1: Grep for any remaining settings.cerebras_* or env_settings references**
  ```bash
  grep -rn 'settings\.cerebras\|env_settings\.' backend/app --include="*.py" | grep -v '__pycache__'
  ```
  Expected: no output.

- [ ] **Step 2: Verify .env content**

  The `.env` file on the server should now only need:
  ```
  DATABASE_PATH=./data/reader.db
  APP_PASSWORD=<password>
  JWT_SECRET=<secret>
  LOG_LEVEL=INFO
  CORS_ORIGINS=https://rss.sarmento.org
  ```
  Any CEREBRAS_* or other operational vars can be removed.

- [ ] **Step 3: Deploy and smoke test**
  - Load settings page → AI Timeout field appears with current value
  - Change timeout value → saves without error
  - Change model → still works
  - Backend logs show no AttributeError on startup

- [ ] **Step 4: Push**
  ```bash
  git pull --rebase && git push
  ```
