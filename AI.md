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
- Update APP_VERSION when changing frontend
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
| **Frontend** | Alpine.js 3.x, Tailwind CSS (CDN) |
| **Backend** | FastAPI, SQLAlchemy, SQLite (WAL mode) |
| **AI** | Cerebras API (Llama 3.3 70B) |
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
│   │   │   ├── posts.py            # List/read posts, mark read
│   │   │   ├── preferences.py      # User preferences API
│   │   │   ├── admin.py            # Admin endpoints (locales, models)
│   │   │   └── proxy.py            # SSRF-safe content proxy
│   │   └── services/
│   │       ├── cerebras.py         # AI client + circuit breaker + queue
│   │       ├── scheduler.py        # APScheduler jobs
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
// Cache busting - UPDATE this when deploying changes
const APP_VERSION = '20260106j';

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
- Plus data retention settings

### AI Service (`backend/app/services/cerebras.py`)

Handles all AI operations:
- Summary generation with prompts from `prompts.yaml`
- Title translation for foreign articles
- Circuit breaker (CLOSED → OPEN → HALF states)
- Rate limiting (respects Cerebras RPM limits)
- Queue processing with priority system

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

5. **Cache busting**: When changing CSS/JS/locales, update `APP_VERSION`.

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
2. **Cache busting**: Update `APP_VERSION` in app.js
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
- Starred posts
- OPML import/export

### AI
- Automatic article summarization (Cerebras/Llama)
- Title translation for foreign-language articles
- Configurable summary language and model
- Rate limiting and circuit breaker

### UI/UX
- Fullscreen modal or split-view reading modes
- Resizable split view (20-80% ratio)
- Dark/light theme (system preference or manual)
- Keyboard navigation (J/K/Enter, [/] for feeds)
- Mobile responsive
- Bilingual (EN/PT)

### Settings
- UI language and theme
- AI model and summary language
- Data retention (posts per feed, age limits)
- Toast notification duration
- Auto-refresh interval

---

## Common Pitfalls

### 1. Cache Issues
**Problem**: Frontend changes don't appear.
**Solution**: Update `APP_VERSION` in app.js, hard refresh browser.

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
**Solution**: Check circuit breaker state in database, verify Cerebras API key, check rate limits.

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
       content_hash, published_at, is_read, is_starred, ...)

-- Feeds
feeds (id, category_id, title, url, last_fetched_at, error_count, ...)

-- Categories
categories (id, name, parent_id, position)

-- AI Summaries (keyed by content hash, not post)
ai_summaries (id, content_hash, summary_pt, translated_title, ...)

-- Settings (key-value store)
app_settings (key, value, updated_at)

-- Summary Queue
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
3. **Update `APP_VERSION`** if frontend changed
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

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>
EOF
)"
git push
```

---

## Backlog / Future Ideas

- [ ] Full-text search for posts
- [ ] Custom tags/labels
- [ ] PWA with service worker
- [ ] Reading statistics
- [ ] Bookmark sync
- [ ] Feed health monitoring dashboard

---

## Getting Help

- **Code patterns**: Search existing code for similar features
- **Alpine.js**: https://alpinejs.dev/
- **FastAPI**: https://fastapi.tiangolo.com/
- **Cerebras**: https://inference-docs.cerebras.ai/

---

*Last updated: 2026-01-06*

---

## Reference Documents

- **AI.md** (this file) — Quick start guide for AI-assisted development
- **PROJECT.md** — Detailed technical specification (circuit breaker, rate limiting, security, etc.)
- **README.md** — Public documentation for end users
- **PROGRESSO.md** — Development session notes (Portuguese)
