# Risos — AI Developer Guide

This document provides everything an AI assistant (or human developer) needs to understand and extend this codebase.

## Project Overview

**Risos** is a self-hosted RSS reader with AI-powered summaries. Single-user, designed for simplicity and reliability.

**Key characteristics:**
- Single-user (no accounts, just a password)
- Single-worker backend (SQLite + APScheduler)
- AI summaries via Cerebras API
- Bilingual UI (English/Portuguese)
- 100% vibe-coded with Claude Code

---

## How to Work with Claude Code on This Project

### Starting a Session

Begin your session by telling Claude to read this file:

```
Read AI.md to understand the project structure.
```

For complex features that touch internal systems (circuit breaker, rate limiting, queue processing), also read the detailed spec:

```
Read PROJECT.md for technical details on [topic].
```

### Writing Effective Prompts

**Be specific about what you want:**

| Bad | Good |
|-----|------|
| "Add search" | "Add search for posts by title. Add a search input in the post list header. Filter posts client-side as user types." |
| "Fix the bug" | "When I press J in split view, two posts are marked as read. Debug the keyboard handler." |
| "Make it faster" | "The post list is slow with 500+ posts. Add virtual scrolling or pagination." |

**Ask Claude to read existing code first:**

```
I want to add a "mark all as unread" feature.
First, read how "mark all as read" is implemented in posts.py and app.js.
Then implement "mark all as unread" following the same pattern.
```

**Reference specific locations:**

```
In handleKeyboard() in app.js, the J key handler has a bug.
When isSplitMode is true and currentPost exists, it calls both
nextPost() and selectNext(). Fix this.
```

### Patterns That Work Well

1. **One feature at a time** — Don't ask for multiple unrelated changes in one prompt.

2. **Describe the user experience** — "When the user clicks X, Y should happen" is clearer than implementation details.

3. **Mention affected files** — "This will need changes in preferences.py, app.js, and the locale files."

4. **Ask for testing** — "After implementing, show me curl commands to test the new endpoint."

5. **Request cache busting** — "Update APP_VERSION after frontend changes."

### Common Requests and How to Phrase Them

**Adding a new preference:**
```
Add a new user preference called "compact_mode" (boolean, default false).
Follow the pattern used for "reading_mode" in preferences.py and app.js.
Add a toggle in Settings > Appearance with translations in both locales.
```

**Adding a new keyboard shortcut:**
```
Add keyboard shortcut "N" to create a new feed.
Add it to handleKeyboard() following the existing pattern.
Show the shortcut hint on the "Add Feed" button like other shortcuts.
```

**Fixing a bug:**
```
Bug: When I delete a category, feeds in that category disappear from the UI.
Expected: Feeds should move to "Uncategorized".
Check the DELETE /api/categories/:id endpoint and the frontend refresh logic.
```

**Adding a new API endpoint:**
```
Add GET /api/stats endpoint that returns:
- total_posts, unread_posts, total_feeds, feeds_with_errors
Follow the pattern in admin.py. Add frontend call to display in Settings.
```

### What Claude Will Do Automatically

- Read relevant files before making changes
- Follow existing code patterns
- Update APP_VERSION in index.html when changing frontend (single source of truth)
- Add translations to both locale files
- Test API endpoints with curl
- Commit with descriptive messages

### What You Should Verify

- Test the feature in the browser (Claude can't see the UI)
- Check mobile responsiveness if UI changed
- Verify translations make sense in context
- Test edge cases Claude might miss

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | Alpine.js 3.x, Tailwind CSS (CDN), i18n with full tooltip coverage, SVG sprite sheet |
| **Backend** | FastAPI, SQLAlchemy, SQLite (WAL mode) |
| **AI** | Cerebras API (configurable model with fallback) |
| **Scheduler** | APScheduler |
| **Server** | Gunicorn + Uvicorn workers, Nginx reverse proxy |

---

## Directory Structure

```
/var/www/rss.sarmento.org/
├── htdocs/                         # Frontend (served by Nginx)
│   ├── index.html                  # Single-page app (Alpine.js)
│   └── static/
│       ├── css/app.css             # Custom styles
│       ├── js/app.js               # Main app logic (~3500 lines)
│       └── locales/                # i18n files
│           ├── en-US.json
│           └── pt-BR.json
│
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI app entry + lifespan
│   │   ├── config.py               # Settings via pydantic-settings
│   │   ├── database.py             # SQLite + SQLAlchemy setup
│   │   ├── models.py               # ORM models
│   │   ├── schemas.py              # Pydantic schemas
│   │   ├── dependencies.py         # Auth middleware
│   │   ├── routes/
│   │   │   ├── auth.py             # Login/logout
│   │   │   ├── categories.py       # CRUD for categories
│   │   │   ├── feeds.py            # CRUD + refresh + OPML
│   │   │   ├── posts.py            # List/read posts, mark read, skip summary, export starred, tag/topic filter, curation, batch-unstar
│   │   │   ├── preferences.py      # User preferences API
│   │   │   ├── suggestions.py      # Suggestion system admin endpoints
│   │   │   ├── tags.py             # Tag management: popular tags, tag search, ignored tags API
│   │   │   ├── topics.py           # Topics CRUD, AI topic suggestion
│   │   │   ├── admin.py            # Admin endpoints (locales, models, circuit breaker reset)
│   │   │   └── proxy.py            # SSRF-safe content proxy
│   │   └── services/
│   │       ├── cerebras/            # AI client package
│   │       │   ├── __init__.py      # Public API exports
│   │       │   ├── _api.py          # generate_summary, call_llm_json, model fallback
│   │       │   ├── _types.py        # SummaryResult, error classes, GarbageContentError
│   │       │   ├── _infrastructure.py # CircuitBreaker, APIKeyRotator
│   │       │   ├── _constants.py    # Shared constants
│   │       │   ├── _prompts.py      # Prompt loading and formatting
│   │       │   └── _legacy.py       # Legacy compatibility
│   │       ├── scheduler.py        # APScheduler jobs
│   │       ├── suggestions.py      # Tag overlap scoring, clear/reprocess
│   │       ├── user_profile.py     # User interest profile from liked posts
│   │       ├── tags.py             # Post tag saving
│   │       ├── feed_parser.py      # RSS/Atom parsing
│   │       ├── feed_ingestion.py   # Post insertion logic
│   │       ├── content_extractor.py # Readability extraction
│   │       ├── html_sanitizer.py   # XSS prevention
│   │       ├── content_hasher.py   # Content deduplication
│   │       └── url_normalizer.py   # URL normalization
│   │
│   ├── alembic/                    # Database migrations
│   │   └── versions/               # Migration files
│   ├── data/
│   │   └── reader.db               # SQLite database
│   ├── scripts/
│   │   ├── lib.py                  # Shared utilities (log, compute_content_hash, etc.)
│   │   ├── regenerate.py           # Unified regeneration (--starred, --unread, --local)
│   │   ├── smart_merge_tags.py     # 3-phase tag dedup (stem + LLM)
│   │   └── translate_all_tags.py   # Batch tag translation to English
│   ├── prompts.yaml                # AI prompts (gitignored)
│   └── .env                        # Config (gitignored)
│
├── screenshots/                    # README images
├── README.md                       # Public documentation
├── PROGRESSO.md                    # Development progress log (Portuguese)
└── AI.md                           # This file
```

---

## Key Files to Understand

### Frontend (`htdocs/static/js/app.js`)

The entire frontend is in one file using Alpine.js. Key sections:

```javascript
// APP_VERSION is defined in index.html (single source of truth for cache busting)
// Format: YYYYMMDD + letter suffix (a, b, c...). Increment letter for each change on same day.

// Main Alpine.js data object
document.addEventListener('alpine:init', () => {
    Alpine.data('app', () => ({
        // State
        token: null,
        posts: [],
        feeds: [],
        categories: [],
        currentPost: null,
        selectedIndex: -1,

        // Computed properties use getters
        get isSplitMode() { ... },
        get unreadCount() { ... },

        // Methods
        async init() { ... },
        async login(password) { ... },
        async loadPosts() { ... },
        openPost(post) { ... },
        handleKeyboard(e) { ... },
        // ... etc
    }));
});
```

**Important patterns:**
- State is reactive via Alpine.js
- API calls use `fetch()` with `Authorization: Bearer ${token}`
- Preferences sync to server via `savePreferencesToServer()`
- Keyboard handler at `handleKeyboard(e)` manages all shortcuts

### Backend Entry (`backend/app/main.py`)

```python
app = FastAPI()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: run migrations, start scheduler
    yield
    # Shutdown: stop scheduler

# Routes mounted here
app.include_router(auth.router, prefix="/api/auth")
app.include_router(posts.router, prefix="/api/posts")
# ... etc
```

### Preferences (`backend/app/routes/preferences.py`)

User preferences stored in `app_settings` table. Key preferences:
- `locale` - UI language (en-US, pt-BR)
- `theme` - light/dark/system
- `reading_mode` - fullscreen/split
- `split_ratio` - percentage for split view (20-80)
- `summary_language` - AI summary language
- `cerebras_model` - AI model selection
- `suggestion_min_tags` - minimum tag overlap for suggestions (1 to tags_per_post)
- `tags_per_post` - number of tags per AI summary (3-15)
- `model_cooldown_minutes` - grace period before retrying failed models
- `blocked_terms` - newline-separated terms to flag noisy posts (with % wildcard)
- Plus data retention settings

### AI Service (`backend/app/services/cerebras/`)

Refactored into a package with clear separation of concerns:
- `_api.py` — Summary generation with prompts, model fallback, `GarbageContentError` for unusable content
- `_types.py` — `SummaryResult` dataclass, error hierarchy (`TemporaryError`, `PermanentError`, `ModelSpecificError`, `GarbageContentError`)
- `_infrastructure.py` — `CircuitBreaker` (persistent state in DB), `APIKeyRotator` (round-robin with per-key cooldowns)
- `_constants.py` — Shared constants
- `_prompts.py` — Prompt loading from `prompts.yaml` or DB overrides

Key patterns:
- `GarbageContentError` is raised for paywalls, error pages, or empty AI responses — callers catch it to mark `skip_summary = True`
- Model fallback: on `ModelSpecificError`, tries other available models automatically
- Rate limiting respects per-key cooldowns and circuit breaker state

---

## Coding Patterns & Conventions

### Frontend (JavaScript)

1. **Alpine.js reactive state**: Use `this.property = value` and the UI updates automatically.

2. **API calls pattern**:
```javascript
async apiCall(endpoint, options = {}) {
    const response = await fetch(`/api/${endpoint}`, {
        headers: {
            'Authorization': `Bearer ${this.token}`,
            'Content-Type': 'application/json',
            ...options.headers
        },
        ...options
    });
    if (!response.ok) throw new Error(await response.text());
    return response.json();
}
```

3. **i18n translation**:
```javascript
t(key, params = {}) {
    let text = this.getNestedValue(this.translations, key) || key;
    // Replace {param} with values
    Object.entries(params).forEach(([k, v]) => {
        text = text.replace(`{${k}}`, v);
    });
    return text;
}
```

4. **Keyboard shortcuts** are centralized in `handleKeyboard(e)`. Pattern:
```javascript
if (this.isKey(e, 'j')) {
    this.selectNext();
    return;  // Important: return to prevent bubbling
}
```

5. **Cache busting**: When changing frontend, update `APP_VERSION` in the inline `<script>` in index.html (single source of truth — CSS and JS tags are generated from it). Format: `YYYYMMDD[a-z]`.

### Backend (Python)

1. **Dependency injection**:
```python
@router.get("/posts")
async def get_posts(db: Session = Depends(get_db), token: str = Depends(get_current_user)):
    ...
```

2. **Settings access**:
```python
# In app_settings table
def _get_setting(db: Session, key: str, default: str = None) -> str:
    row = db.query(AppSetting).filter_by(key=key).first()
    return row.value if row else default
```

3. **Error responses**:
```python
raise HTTPException(status_code=404, detail="Feed not found")
# Frontend translates "Feed_not_found" via backendErrors in locales
```

4. **Database transactions**: SQLAlchemy sessions auto-commit. Use `db.rollback()` on error.

---

## How to Test Changes

### Backend API Testing

```bash
# 1. Login and get token
curl -s -X POST http://127.0.0.1:8100/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password":"YOUR_PASSWORD"}' | jq

# 2. Use token for authenticated requests
TOKEN="eyJ..."
curl -s "http://127.0.0.1:8100/api/posts?page_size=5" \
  -H "Authorization: Bearer $TOKEN" | jq

# 3. Test specific endpoints
curl -s "http://127.0.0.1:8100/api/preferences" \
  -H "Authorization: Bearer $TOKEN" | jq
```

### Frontend Testing

1. **Hard refresh**: Ctrl+Shift+R (bypasses cache)
2. **Cache busting**: Update `APP_VERSION` in the inline `<script>` in `index.html`
3. **Browser console**: Check for errors, use `Alpine.$data(document.querySelector('[x-data]'))` to inspect state

### Service Restart

```bash
# Restart the backend service
sudo systemctl restart rss-reader

# Check status/logs
sudo systemctl status rss-reader
journalctl -u rss-reader -f
```

---

## Current Features

### Core
- RSS/Atom feed subscription with auto-discovery
- Category organization with drag-and-drop
- Read/unread tracking with batch operations
- Starred posts with ZIP export (individual markdown files per post, grouped by feed)
- OPML import/export

### AI
- Automatic article summarization (Cerebras, configurable model)
- Automatic model fallback on response errors
- Title translation for foreign-language articles (including title-only posts)
- Configurable summary language, model, and model cooldown
- Rate limiting and circuit breaker (with manual reset via Settings)
- Auto-skip garbage content (`GarbageContentError` — paywalls, error pages, empty results)
- Skip summary toggle per post (manual or automatic after permanent failures)
- Skip summary indicator icon in post list (prohibition icon before title)
- Tags extracted per post (configurable 3-15, shown as clickable chips on all posts)
- Tags auto-translated to English for non-GPT models
- Ignored tags system — exclude irrelevant tags from suggestions
- Blocked terms — flag posts matching user-defined title patterns (with % wildcard support)

### Suggestions
- Like-based user profile (aggregated tags from liked posts)
- Tag overlap scoring (no extra AI calls)
- Dynamic sensitivity threshold (1 to tags_per_post)
- Auto-clear suggestions when threshold changes
- Ignored tags — user can click any tag to exclude it from scoring and profile
- Blocked posts excluded — posts matching blocked terms are never suggested
- Hourly automatic processing + manual regeneration

### Topics
- Named groups of tags for organizing content (e.g., "Self-Hosting", "Machine Learning")
- Full CRUD: create, rename, delete, reorder
- Add/remove tags from topics (manual or AI-assisted); only existing tags allowed (validated server-side)
- Tag autocomplete in topic editor: prefix search via `GET /tags/search?q=...`, excludes already-assigned tags, keyboard navigation
- AI topic suggestion: analyzes top 150 unassigned tags and proposes 5-12 groupings
- Per-topic AI tag suggestion: suggests which unassigned tags fit a specific topic
- Sidebar section with unread count badges; click to filter posts by topic
- Topic filter: OR across topic tags, composes with starred/unread/feed filters
- Topic and tag filters are mutually exclusive
- Post tags belonging to selected topic are highlighted in purple
- "Add tag to topic" shortcut from tag filter indicator

### Curation
- AI-powered analysis of starred posts to identify essential vs redundant articles
- Respects current view context: filters by feed, category, topic, or tag
- Three classifications: essential (green), redundant (red), situational (yellow)
- Inline badges on posts with hover-to-see-reason
- Persistent stats panel with disclaimer (no AI-generated summary — AI can't do math reliably)
- Stats computed client-side from actual badges assigned to posts (always accurate)
- Unclassified posts (missed by AI) shown as gray badge; sum always equals total
- User manually selects posts to archive (badges are advisory, not prescriptive)
- "Download selected" exports as ZIP of markdown (backup before archiving)
- "Archive selected" batch-unstars with confirmation dialog
- AI classification reasons respect user's summary language preference
- Post limits: soft warning at 50 posts (`CURATION_WARN_THRESHOLD` in app.js), hard limit at 100 (`CURATION_MAX_POSTS` in posts.py) — beyond this, prompt exceeds model context window
- Curation results auto-clear when switching feed, category, topic, or tag

### UI/UX
- Fullscreen modal or split-view reading modes
- Resizable split view (20-80% ratio)
- Dark/light theme (system preference or manual)
- Keyboard navigation (J/K/Enter, [/] for feeds)
- SVG sprite sheet — all icons defined once as `<symbol>`, referenced via `<use href="#icon-name"/>`; `icon-sparkles` (✨) used consistently for all AI actions
- Post search — search titles and AI summaries with 300ms debounce, `/` shortcut to focus
- Blocked post indicator — red left border on posts matching blocked terms
- Split dropdown "Mark as read" — option to dismiss all or only blocked posts
- Date separators in post list (visual grouping by relative date)
- Drag-and-drop feeds between categories in sidebar (desktop only, native HTML5)
- Mobile responsive (Top Tags, Topics, post tags, Curate, and drag-and-drop hidden on mobile for cleaner UX)
- Login screen mobile hint for desktop/tablet recommendation
- Bilingual (EN/PT)

### Settings
- UI language and theme
- AI model and summary language
- Data retention (posts per feed, age limits)
- Toast notification duration
- Auto-refresh interval
- Topics management tab (CRUD + AI suggestions)

---

## Common Pitfalls

### 1. Cache Issues
**Problem**: Frontend changes don't appear.
**Solution**: Update `APP_VERSION` in the inline `<script>` in `index.html` `<head>`:
```html
<script>var APP_VERSION = '20260227c';</script>
```
CSS and JS tags are generated automatically from this value via `document.write`.

**Version format**: Use today's date + letter suffix: `20260108a`, `20260108b`, etc.
Increment the letter for each change on the same day.

### 2. Double Event Handling
**Problem**: Action fires twice.
**Solution**: In keyboard handler, ensure `return` after handling. Check for both modal and split-view conditions.

### 3. Preferences Not Saving
**Problem**: Settings revert after reload.
**Solution**: Ensure `savePreferencesToServer()` is called after state change. Check backend logs for errors.

### 4. Split View Mode Issues
**Problem**: Split view behaves differently than expected.
**Solution**:
- Split mode only works on screens ≥1024px
- `isSplitMode` is a computed getter that checks both preference AND screen width
- J/K navigation auto-opens posts in split mode

### 5. Database Locked
**Problem**: SQLite "database is locked" error.
**Solution**: Only one worker should run. Check with `pgrep -f gunicorn`. Kill duplicates.

### 6. AI Summaries Not Generating
**Problem**: Queue stuck, no summaries appearing.
**Solution**: Use the "Reset AI" button in Settings footer to reset the circuit breaker. Also check Cerebras API key and rate limits. The system will automatically try fallback models if the preferred model returns invalid responses.

---

## Adding New Features

### New Preference

1. **Backend** (`preferences.py`):
```python
PREF_NEW_SETTING = "pref_new_setting"

# Add to PreferencesResponse
new_setting: Optional[str] = None

# Add to get_preferences
new_setting=prefs[PREF_NEW_SETTING] or 'default',

# Add to update_preferences
if prefs.new_setting is not None:
    _set_setting(db, PREF_NEW_SETTING, prefs.new_setting)
```

2. **Frontend** (`app.js`):
```javascript
// Add to state
newSetting: 'default',

// Apply in syncPreferences
if (prefs.new_setting) this.newSetting = prefs.new_setting;

// Save in savePreferencesToServer
new_setting: this.newSetting,
```

3. **Add to settings UI** in `index.html`.

4. **Add translations** to both locale files.

### New API Endpoint

1. Create route in appropriate file under `routes/`
2. Add Pydantic schemas in `schemas.py`
3. Register router in `main.py` if new file
4. Add frontend API call

### New Locale String

1. Add to `en-US.json`:
```json
"section": {
    "newKey": "English text"
}
```

2. Add same path to `pt-BR.json`:
```json
"section": {
    "newKey": "Texto em português"
}
```

3. Use in HTML:
```html
<span x-text="t('section.newKey')"></span>
```

---

## Database Schema (Key Tables)

```sql
-- Posts
posts (id, feed_id, guid, url, title, content, full_content,
       content_hash, published_at, is_read, is_starred,
       is_liked, is_suggested, suggestion_score, skip_summary, ...)

-- Feeds
feeds (id, category_id, title, url, last_fetched_at, error_count, ...)

-- Categories
categories (id, name, parent_id, position)

-- AI Summaries (keyed by content hash, not post)
ai_summaries (id, content_hash, summary_pt, one_line_summary, translated_title, ...)

-- Post Tags (extracted by AI, used for suggestions)
post_tags (id, post_id, tag, created_at)

-- Ignored Tags (user-excluded from suggestion scoring)
ignored_tags (id, tag, created_at)

-- Topics (named tag groups)
topics (id, name, position, created_at)

-- Topic Tags (many-to-many: topic <-> tag)
topic_tags (topic_id, tag)  -- composite PK

-- Settings (key-value store)
app_settings (key, value, updated_at)

-- Summary Queue (ordered by priority DESC, created_at DESC — newest first)
summary_queue (id, post_id, content_hash, priority, attempts, ...)
```

---

## Multiple Instances

This codebase runs multiple instances for different users:

| Instance | URL | Port | Service |
|----------|-----|------|---------|
| Main | rss.sarmento.org | 8100 | rss-reader |
| Israel | israel.sarmento.org | 8101 | risos_israel |
| Michael | michael.sarmento.org | 8102 | risos_michael |

Each has its own database, config, and systemd service.

---

## Development Workflow

1. **Make changes** to relevant files
2. **Test locally** via curl or browser
3. **Update version** if frontend changed (in `index.html` inline `<script>` — single source of truth)
4. **Restart service** if backend changed
5. **Update `PROGRESSO.md`** with session notes
6. **Commit and push** with descriptive message

```bash
git add -A
git commit -m "$(cat <<'EOF'
Brief description of changes

- Detail 1
- Detail 2

🤖 Generated with [Claude Code](https://claude.com/claude-code)

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Backlog / Future Ideas

- [ ] Full-text search for posts
- [ ] PWA with service worker
- [ ] Reading statistics
- [ ] Multi-profile with Authelia (see REFACTOR.md)

---

## Getting Help

- **Code patterns**: Search existing code for similar features
- **Alpine.js**: https://alpinejs.dev/
- **FastAPI**: https://fastapi.tiangolo.com/
- **Cerebras**: https://inference-docs.cerebras.ai/

---

*Last updated: 2026-03-08 (Post search, drag-and-drop feeds)*

---

## Reference Documents

- **AI.md** (this file) — Quick start guide for AI-assisted development
- **PROJECT.md** — Detailed technical specification (circuit breaker, rate limiting, security, etc.)
- **README.md** — Public documentation for end users
- **PROGRESSO.md** — Development session notes (Portuguese)
