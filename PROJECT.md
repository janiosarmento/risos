# RSS Reader with AI — Final Project Specification

## Overview

A Feedly-style web application for reading RSS feeds, with automatic AI-generated summaries (Cerebras API). The system is single-user, runs on a self-hosted server, focusing on operational predictability, cost control, and architectural simplicity.

The project prioritizes:
- Robustness with SQLite
- Controlled asynchronous processing
- Defensive security (especially XSS and SSRF)
- Controlled data growth
- No critical external dependencies in production


## Architectural Principles

1. Only one database write process at a time
2. All queues and critical state persist in the database
3. No essential logic depends solely on memory
4. External content is never trusted
5. Data retention is finite and configurable
6. Background jobs never compete with the API for resources


## General Architecture

### Components

- Frontend: Static HTML + Alpine.js + Tailwind (local assets)
- Backend: FastAPI (1 worker)
- Database: SQLite in WAL mode
- Jobs: APScheduler (single-instance mode, persistent)
- AI: Cerebras API with rate limiting, persistent queue, and circuit breaker
- Proxy: Nginx (WordOps)


## Directory Structure

```
/var/www/rss.sarmento.org/
├── htdocs/                         # Served by Nginx
│   ├── index.html                  # Main app
│   └── static/
│       ├── css/
│       │   └── app.css             # Compiled Tailwind
│       └── js/
│           ├── app.js              # Alpine.js logic
│           └── alpine.min.js       # Local Alpine.js
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI app + lifespan
│   │   ├── config.py               # Settings via pydantic-settings
│   │   ├── database.py             # SQLite + SQLAlchemy
│   │   ├── models.py               # ORM models
│   │   ├── schemas.py              # Pydantic schemas
│   │   ├── dependencies.py         # Auth, rate limiting
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py
│   │   │   ├── categories.py
│   │   │   ├── feeds.py
│   │   │   ├── posts.py
│   │   │   └── system.py           # Health, status
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── feed_parser.py
│   │       ├── content_extractor.py
│   │       ├── html_sanitizer.py
│   │       ├── cerebras.py         # AI client + circuit breaker
│   │       └── scheduler.py        # APScheduler + jobs
│   ├── alembic/                    # Migrations
│   │   ├── versions/
│   │   └── env.py
│   ├── alembic.ini
│   ├── requirements.txt
│   ├── data/                       # Runtime data
│   │   ├── reader.db
│   │   └── app.log
│   └── .env
└── PROJECT.md
```


## Database (SQLite)

### Required Configuration

- journal_mode = WAL
- synchronous = NORMAL
- busy_timeout = 5000
- Single write connection at a time (via SQLAlchemy session scoping)
- Uvicorn/ASGI with 1 worker (avoids duplicate scheduler and concurrent writes)

### Concurrency Strategy

- API: mostly reads
- Writes:
  - feed ingestion
  - read marking
  - summary persistence
- Background jobs never run in parallel with each other

### Integrity Check on Startup

When starting the application:
1. If DB > 100MB: run `PRAGMA quick_check;` (fast)
2. Otherwise: run `PRAGMA integrity_check;`
3. If failed: critical log, don't start, exit code 1
4. If passed: run pending migrations via Alembic
5. If migration fails: critical log, don't start, exit code 1

Migrations:
- Versioned with Alembic
- Run automatically on startup
- Manual rollback only (not automatic)
- Migrations should be idempotent and minimize long operations


## Complete SQL Schema

```sql
-- Categories
CREATE TABLE categories (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    parent_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    position INTEGER DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_categories_parent ON categories(parent_id);

-- Feeds
CREATE TABLE feeds (
    id INTEGER PRIMARY KEY,
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    url TEXT UNIQUE NOT NULL,
    site_url TEXT,
    last_fetched_at DATETIME,
    -- Error handling
    error_count INTEGER DEFAULT 0,
    last_error TEXT,
    last_error_at DATETIME,
    next_retry_at DATETIME,
    disabled_at DATETIME,
    disable_reason TEXT,
    -- Unstable GUID detection
    guid_unreliable BOOLEAN DEFAULT 0,
    guid_collision_count INTEGER DEFAULT 0,
    -- URL deduplication bypass (for problematic feeds)
    allow_duplicate_urls BOOLEAN DEFAULT 0,
    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_feeds_category ON feeds(category_id);
CREATE INDEX idx_feeds_next_retry ON feeds(next_retry_at) WHERE disabled_at IS NULL;

-- Posts
CREATE TABLE posts (
    id INTEGER PRIMARY KEY,
    feed_id INTEGER NOT NULL REFERENCES feeds(id) ON DELETE CASCADE,
    guid TEXT,
    url TEXT,
    normalized_url TEXT,
    title TEXT,
    author TEXT,
    content TEXT,                   -- Summary up to 500 chars for listings
    full_content TEXT,              -- Full content (on demand)
    content_hash TEXT,
    published_at DATETIME,
    fetched_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    sort_date DATETIME,             -- Sorting: published_at or fetched_at
    is_read BOOLEAN DEFAULT 0,
    read_at DATETIME,
    fetch_full_attempted_at DATETIME -- Cooldown for full_content retry
    -- No UNIQUE constraints; deduplication via partial indexes
);

-- Partial indexes for deduplication (NULL doesn't violate)
CREATE UNIQUE INDEX idx_posts_guid ON posts(feed_id, guid) WHERE guid IS NOT NULL;
CREATE UNIQUE INDEX idx_posts_url ON posts(feed_id, normalized_url)
    WHERE normalized_url IS NOT NULL;

CREATE INDEX idx_posts_feed ON posts(feed_id);
CREATE INDEX idx_posts_read ON posts(is_read);
CREATE INDEX idx_posts_sort ON posts(sort_date DESC);
CREATE INDEX idx_posts_hash ON posts(content_hash);
CREATE INDEX idx_posts_read_at ON posts(read_at) WHERE is_read = 1;

-- Partial index for content_hash deduplication (final fallback)
CREATE UNIQUE INDEX idx_posts_content_hash ON posts(feed_id, content_hash)
    WHERE content_hash IS NOT NULL AND guid IS NULL AND normalized_url IS NULL;

-- AI summary cache (by content_hash)
CREATE TABLE ai_summaries (
    id INTEGER PRIMARY KEY,
    content_hash TEXT UNIQUE NOT NULL,
    summary_pt TEXT NOT NULL,
    one_line_summary TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_summaries_hash ON ai_summaries(content_hash);

-- Pending summaries queue (by post)
CREATE TABLE summary_queue (
    id INTEGER PRIMARY KEY,
    post_id INTEGER UNIQUE NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    content_hash TEXT NOT NULL,
    priority INTEGER DEFAULT 0,     -- 0=background, 10=user opened
    attempts INTEGER DEFAULT 0,
    last_error TEXT,
    error_type TEXT,                -- 'temporary' or 'permanent'
    locked_at DATETIME,
    cooldown_until DATETIME,        -- For temporary errors after 5 attempts
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_queue_priority ON summary_queue(priority DESC, created_at);
CREATE INDEX idx_queue_pending ON summary_queue(locked_at, cooldown_until);

-- Permanent summary failures
CREATE TABLE summary_failures (
    id INTEGER PRIMARY KEY,
    content_hash TEXT NOT NULL,
    last_error TEXT,
    failed_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_failures_hash ON summary_failures(content_hash);

-- Application settings (key-value)
CREATE TABLE app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- JWT token blacklist
CREATE TABLE token_blacklist (
    jti TEXT PRIMARY KEY,
    expires_at DATETIME NOT NULL
);

CREATE INDEX idx_blacklist_expires ON token_blacklist(expires_at);

-- Scheduler lock
CREATE TABLE scheduler_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    locked_by TEXT NOT NULL,
    locked_at DATETIME NOT NULL,
    heartbeat_at DATETIME NOT NULL
);

-- Cleanup logs
CREATE TABLE cleanup_logs (
    id INTEGER PRIMARY KEY,
    executed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    posts_removed INTEGER DEFAULT 0,
    full_content_cleared INTEGER DEFAULT 0,
    summaries_cleared INTEGER DEFAULT 0,
    unread_removed INTEGER DEFAULT 0,
    bytes_freed INTEGER DEFAULT 0,
    duration_seconds REAL,
    notes TEXT
);

CREATE INDEX idx_cleanup_executed ON cleanup_logs(executed_at DESC);
```


## Data Model

### Posts — Robust Deduplication

Deduplication follows this order:

1. (feed_id, guid) when GUID is stable
2. (feed_id, normalized_url) as fallback
3. (feed_id, content_hash) as last resort

#### URL Normalization (for dedup)

Goal: remove noise without "gluing" different URLs together.

Rules:
- Normalize only the hostname to lowercase
- Remove fragment (#...)
- Remove default port (:80 for http, :443 for https)
- Reject URLs with userinfo (user:pass@host) — log warning and ignore post
- Remove only known tracking query params:
  - utm_* (any parameter starting with utm_)
  - fbclid
  - gclid
- Remove trailing slash only when path is not "/"
- Preserve scheme (http/https) in dedup key
- Preserve generic params like `ref`, `source`, `id`

Example:
```
https://Site.com:443/Article?utm_source=rss&id=123#comments
→ https://site.com/Article?id=123
```

#### Unstable GUID Detection

Field in feeds: `guid_unreliable BOOLEAN DEFAULT 0`

Detection at insertion time:
1. When inserting post, if post already exists with same (feed_id, guid) but different URL:
   - Increment `guid_collision_count` on feed
   - If `guid_collision_count >= 3`: mark `guid_unreliable = 1`
   - Log warning on first marking

Additional heuristic (optional, applied on first fetch):
- If GUID contains only digits and has more than 10 characters: suspicious
- If GUID contains Unix timestamp pattern (10 digits starting with 17...): suspicious
- If suspicious: increment guid_collision_count by 1

When `guid_unreliable = 1`:
- Deduplication ignores GUID, uses only normalized_url and content_hash
- UNIQUE(feed_id, guid) is not violated since guid can be NULL for new posts

#### URL Deduplication Bypass

Field in feeds: `allow_duplicate_urls BOOLEAN DEFAULT 0`

For feeds that legitimately reuse URLs (live blogs, updated landing pages):
- When `allow_duplicate_urls = 1`: deduplication ignores normalized_url
- Dedup depends only on GUID (if reliable) or content_hash
- Manual toggle via API or admin

**Documented consequence**: feeds that reuse URLs will have items deduplicated by default. This is accepted behavior within project scope. For problematic feeds, the operator can manually enable `allow_duplicate_urls`.

### Content

- `content`: sanitized and truncated version (max 500 chars), used in listings
- `full_content`: stored only when:
  - user opens the post (on-demand fetch), or
  - feed doesn't provide enough content (< 200 chars in RSS)

**On-demand fetch with cooldown**:
- `fetch_full_attempted_at`: records when full_content fetch was attempted
- If fetch fails: don't retry for 24 hours
- Condition to try: `full_content IS NULL AND content < 200 chars AND (fetch_full_attempted_at IS NULL OR fetch_full_attempted_at < now - 24h)`

### Content Hash (AI cache)

Goal: reduce reprocessing without causing collisions that result in wrong summaries.

**Hash source**: always use the best available content version:
1. If `full_content` exists: hash of normalized full_content
2. Otherwise: hash of feed `content`

**Update when receiving full_content**:
- If post is still in queue (no summary): recalculate content_hash
- If summary already exists for new hash in ai_summaries: mark as ready
- If not: update summary_queue.content_hash to reprocess

Normalization pipeline before hashing:
1. Extract text from HTML (strip tags)
2. Remove known ad blocks (hardcoded CSS selectors)
3. Normalize whitespace (collapse multiple spaces/breaks into one)
4. Remove lines that look like boilerplate:
   - Isolated timestamps (regex: `^\d{4}-\d{2}-\d{2}.*$`)
   - "Read more", "Continues after ad", etc.

CSS selectors for ad removal:

Safe selectors (always applied):
```python
SAFE_AD_SELECTORS = [
    '.ad', '.ads', '.advertisement', '.advertising',
    '.sponsored', '.promo', '.promotion',
    '.social-share', '.share-buttons',
    '.newsletter-signup', '.subscribe-box',
]
```

Aggressive selectors (may remove legitimate content):
```python
AGGRESSIVE_AD_SELECTORS = [
    '[class*="ad-"]', '[class*="ads-"]',
    '[id*="ad-"]', '[id*="ads-"]',
    '.related-posts', '.recommended',
]
```

**Important**: selector removal is applied only to post-Readability content (inside the main article), not the entire document.

**Fallback to avoid poor text**:
1. Apply all selectors (safe + aggressive)
2. If resulting text < 400 characters:
   - Redo with only safe selectors
   - Use the longer version

Hash algorithm:
- If normalized content <= 200KB: SHA-256 of entire content
- If > 200KB: SHA-256 of (first 100KB + last 100KB)

Note:
- Don't apply lowercase to avoid increasing collisions


## Data Retention

### Configuration via .env

```
MAX_POSTS_PER_FEED=500
MAX_POST_AGE_DAYS=365
MAX_UNREAD_DAYS=90
MAX_DB_SIZE_MB=1024
```

### Cleanup Policy

Executed daily at 03:00 (configurable via CLEANUP_HOUR).

Execution order:
1. Remove posts read more than MAX_POST_AGE_DAYS ago
2. For each feed, remove read posts exceeding MAX_POSTS_PER_FEED (oldest first)
3. Clear full_content of posts read more than 30 days ago
4. Remove unread posts older than MAX_UNREAD_DAYS
5. Remove summary_failures entries older than 90 days
6. Remove cleanup_logs entries older than 90 days
7. Remove expired tokens from blacklist

#### Behavior When Reaching MAX_DB_SIZE_MB

Checked after main cleanup:

1. If DB > MAX_DB_SIZE_MB:
   - Run VACUUM
   - Recalculate size
2. If still > limit:
   - Temporarily reduce MAX_POST_AGE_DAYS by 30 days
   - Run cleanup again
   - Repeat until it fits or reaches minimum of 30 days
3. If still > limit with minimum age:
   - Critical alert log
   - Continue operating (don't block)
   - Set app_settings: `db_size_warning = "DB exceeds configured limit"`

#### Cleanup Logs

Each execution logs to cleanup_logs:
- posts_removed
- full_content_cleared
- summaries_cleared (from summary_failures)
- unread_removed (unread posts removed by MAX_UNREAD_DAYS)
- bytes_freed (calculated via page_count * page_size difference)
- duration_seconds
- notes (details or warnings)

Frontend shows discreet warning if unread_removed > 0 in last cleanup.


## AI — Summary Cache and Processing

### Summary Cache

Table `ai_summaries` stores summaries by content_hash (not by post).

Benefit: posts with identical content share the same summary without additional AI cost.

### Persistent Queue (by post)

Table `summary_queue` with one entry per post_id.

Field `content_hash` stored to avoid recalculation during processing (local cache).

Worker flow:
1. Fetch next eligible item from queue (see query below)
2. Check if content_hash already exists in ai_summaries
   - If yes: remove from queue, finish (0 AI calls)
3. Call Cerebras API
4. If success: save to ai_summaries, remove from queue
5. If error: classify and handle (see Retry Policy)

Query to fetch next item:
```sql
SELECT * FROM summary_queue
WHERE (locked_at IS NULL OR locked_at < datetime('now', '-300 seconds'))
  AND (cooldown_until IS NULL OR cooldown_until < datetime('now'))
ORDER BY priority DESC, created_at ASC
LIMIT 1
```

#### Atomic Lock Acquisition

To avoid race conditions, lock must be acquired in a single operation:

```sql
UPDATE summary_queue
SET locked_at = datetime('now')
WHERE id = :candidate_id
  AND (locked_at IS NULL OR locked_at < datetime('now', '-300 seconds'))
  AND (cooldown_until IS NULL OR cooldown_until < datetime('now'))
```

Check `rowcount == 1` to confirm acquisition. If `rowcount == 0`, another worker got the item; fetch next candidate.

### Retry Policy

Maximum 5 attempts per cycle, with differentiated handling by error type.

Temporary errors (error_type = 'temporary'):
- Timeout
- Connection error
- HTTP 429 (rate limit)
- HTTP 5xx

When failing with temporary error:
- attempts += 1
- If attempts < 5: release lock, will be reprocessed next cycle
- If attempts >= 5: enter cooldown
  - cooldown_until = now + 24 hours
  - attempts = 0 (reset for new cycle after cooldown)

Permanent errors (error_type = 'permanent'):
- Invalid payload
- Empty AI response (3x consecutive)
- Response parsing error

When failing with permanent error:
- attempts += 1
- If attempts >= 5: remove from queue, log to summary_failures

### Persistent Circuit Breaker (Cerebras)

State saved in app_settings:
- cerebras_state: CLOSED | OPEN | HALF
- cerebras_failures: consecutive failure counter
- cerebras_half_successes: success counter in HALF mode
- cerebras_last_failure: timestamp
- cerebras_last_success: timestamp

Parameters (.env):
```
FAILURE_THRESHOLD=5
RECOVERY_TIMEOUT_SECONDS=300
HALF_OPEN_MAX_REQUESTS=3
```

Transitions:

| From | To | Condition |
|------|-----|----------|
| CLOSED | OPEN | cerebras_failures >= 5 |
| OPEN | HALF | now - cerebras_last_failure >= 300s |
| HALF | CLOSED | cerebras_half_successes >= 3 |
| HALF | OPEN | any failure |

On transition:
- CLOSED → OPEN: log warning
- OPEN → HALF: reset cerebras_half_successes = 0
- HALF → CLOSED: reset cerebras_failures = 0, log info
- HALF → OPEN: log warning

Note on 429:
- HTTP 429 does NOT count toward opening circuit
- 429 activates rate_limited_until (see Rate Limiting)


## AI Rate Limiting

Rules:
- No AI calls occur within HTTP requests
- Requests only insert into queue
- Worker ensures spacing between calls

Implementation:
```python
MIN_INTERVAL_SECONDS = 60 / CEREBRAS_MAX_RPM  # 3s for 20 RPM
```

The worker:
1. Checks rate_limited_until in app_settings
   - If now < rate_limited_until: don't call, wait for next cycle
2. Checks time since last call (cerebras_last_call in app_settings)
   - If elapsed < MIN_INTERVAL_SECONDS: don't call
3. Updates cerebras_last_call = now **before** the call (ensures pacing even on fast failure)
4. Executes call
5. Updates cerebras_last_success or cerebras_last_failure based on result

Note: `cerebras_last_call` is updated **whenever an attempt is made**, regardless of success or failure. This prevents bursts in case of instant errors.

429 handling:
- On receiving 429: rate_limited_until = now + 60s
- Doesn't count as failure for circuit breaker
- Worker respects rate_limited_until on next cycle


## Feeds — Error Handling

### Fields in feeds

```sql
error_count INTEGER DEFAULT 0,
last_error TEXT,
last_error_at DATETIME,
next_retry_at DATETIME,
disabled_at DATETIME,
disable_reason TEXT
```

### Progressive Backoff

Interval calculated when logging error:

| error_count | Interval until next attempt |
|-------------|----------------------------|
| 1 | 1 hour |
| 2 | 4 hours |
| 3 | 12 hours |
| 4 | 24 hours |
| 5+ | 48 hours |

Formula: `min(48, 2^(error_count-1))` hours

When logging error:
```python
feed.error_count += 1
feed.last_error = str(error)
feed.last_error_at = now
feed.next_retry_at = now + timedelta(hours=backoff_hours)
```

On success:
```python
feed.error_count = 0
feed.last_error = None
feed.last_error_at = None
feed.next_retry_at = None
```

### Automatic Disabling

When error_count >= 10:
```python
feed.disabled_at = now
feed.disable_reason = f"Consecutive failures: {feed.last_error}"
```

Disabled feed:
- Not updated by update_feeds job
- Appears highlighted in UI with option to re-enable

Manual re-enabling (via API):
```python
feed.error_count = 0
feed.disabled_at = None
feed.disable_reason = None
feed.next_retry_at = None
# Tries immediate fetch; if fails, returns to normal backoff
```

### Errors Considered

Increment error_count:
- Timeout (10s)
- HTTP 4xx/5xx
- Invalid XML/RSS
- SSL/TLS failed
- DNS didn't resolve
- Connection refused

Don't increment:
- Empty but valid feed (0 posts)
- No new posts (all duplicates)
- Individual post parsing errors (feed itself ok)


## Security

### HTML and XSS

Sanitization via bleach with strict whitelist.

```python
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'b', 'i', 'u',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
    'a', 'img', 'figure', 'figcaption',
    'table', 'thead', 'tbody', 'tr', 'th', 'td'
]

ALLOWED_ATTRS = {
    'a': ['href', 'title', 'rel', 'target'],
    'img': ['src', 'alt', 'title'],
    'th': ['colspan', 'rowspan'],
    'td': ['colspan', 'rowspan'],
}
```

Additional processing after bleach:
- Links (`<a>`): add `rel="noopener noreferrer" target="_blank"`
- Validate href: only http/https, block javascript:, data:
- Validate img src: only https and data: (inline images)

### CSP in Nginx

```nginx
add_header Content-Security-Policy "
    default-src 'self';
    script-src 'self';
    style-src 'self';
    img-src 'self' https: data:;
    font-src 'self';
    connect-src 'self';
    frame-ancestors 'none';
    base-uri 'self';
    form-action 'self';
" always;
```

### Content Proxy (SSRF-safe)

Goal: allow fetching article content without exposing SSRF.

#### Usage Restriction

The proxy `/api/proxy` only accepts URLs that match existing posts:
- The requested URL must match `posts.url` or `posts.normalized_url` of some post in the database
- This prevents using the proxy as a generic fetch tool

#### Hostname Whitelist (additional validation)

Dynamically maintained based on registered feeds:
- Hostname extracted from feed.url
- Hostname extracted from feed.site_url (if filled)

Exact match by normalized hostname (IDN → punycode).

#### Validations Before Fetch

1. URL hostname is in whitelist
2. Protocol is http or https
3. Port is 80, 443, or omitted
4. Host is not an IP literal (regex: `^\d+\.\d+\.\d+\.\d+$` or IPv6)
5. Resolve DNS and verify IP is not:
   - 127.0.0.0/8 (loopback)
   - 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16 (private)
   - 169.254.0.0/16 (link-local)
   - ::1, fe80::/10 (IPv6 loopback/link-local)

#### Fetch Behavior

```python
async with httpx.AsyncClient() as client:
    # Real streaming: doesn't download body before iterating
    async with client.stream(
        "GET",
        url,
        timeout=10.0,
        follow_redirects=False,
        headers={'User-Agent': 'RSSReader/1.0'}
    ) as response:
        if response.status_code >= 300:
            raise HTTPException(400, "Resource not available")

        # Streaming with real limit
        content = b""
        async for chunk in response.aiter_bytes():
            content += chunk
            if len(content) > 5_242_880:  # 5MB
                raise HTTPException(413, "Content too large")

        return content
```

### Authentication

#### JWT

- Algorithm: HS256
- Expiration: 24h (configurable)
- Payload: `{ "sub": "user", "exp": timestamp, "jti": uuid }`
- Secret: minimum 32 characters, validated on startup

#### Password Validation

Password is compared directly with APP_PASSWORD from .env (constant-time comparison).
No stored hash — single-user scope doesn't justify additional complexity.

#### Token Blacklist

Logout adds jti to token_blacklist with expires_at.

Token validation:
1. Decode and verify signature
2. Verify exp not expired
3. Verify jti not in blacklist

Cleanup: daily job removes `WHERE expires_at < now()`.

#### Frontend Storage

- Token kept only in JavaScript variable (memory)
- Sent via header `Authorization: Bearer {token}`
- Lost when closing/reloading tab (intentional behavior)
- User logs in again when needed

### HTTP Rate Limiting

```python
from slowapi import Limiter

def get_real_ip(request: Request) -> str:
    # Trust X-Forwarded-For only if request comes from local Nginx
    if request.client.host == "127.0.0.1":
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host

limiter = Limiter(key_func=get_real_ip)
```

Limits:
- Login: 5/minute per IP
- General API: 100/minute per IP
- Feed refresh: 10/minute per IP


## Background Jobs

### Single Instance Guarantee

Table scheduler_lock with fixed id = 1.

On startup:
1. Generate instance_id = uuid4()
2. Try to acquire lock:
   ```sql
   INSERT OR REPLACE INTO scheduler_lock (id, locked_by, locked_at, heartbeat_at)
   SELECT 1, :instance_id, :now, :now
   WHERE NOT EXISTS (
       SELECT 1 FROM scheduler_lock
       WHERE heartbeat_at > datetime('now', '-60 seconds')
   )
   ```
3. If inserted: scheduler active, start jobs
4. If not inserted: another scheduler active, don't start jobs (API continues working)

Heartbeat: every 30s update `heartbeat_at = now` where `locked_by = instance_id`.

Clean shutdown: try `DELETE FROM scheduler_lock WHERE locked_by = instance_id`.

### Defined Jobs

| Job | Interval | Description |
|-----|----------|-------------|
| update_feeds | 30 min | Updates eligible feeds (next_retry_at <= now, not disabled) |
| process_summaries | 1 min | Processes 1 queue item respecting rate limit |
| cleanup_retention | daily 03:00 | Applies complete retention policy |
| health_check | 5 min | Verifies system integrity |

### Internal Health Checks

Verifications:
1. Database responds: `SELECT 1`
2. Disk space > 100MB on DB volume
3. Database size < MAX_DB_SIZE_MB
4. Queue not stuck: no items with locked_at > 1 hour without progress
5. Circuit breaker not OPEN for more than 1 hour

If any check fails:
- Log warning with details
- Set app_settings: `health_warning = "problem description"`

If all pass:
- Remove health_warning from app_settings (if exists)

Frontend displays health_warning when present.


## API Endpoints

### Authentication

```
POST /api/auth/login
  Body: { "password": "..." }
  Response: { "token": "...", "expires_at": "..." }

POST /api/auth/logout
  Header: Authorization: Bearer {token}
  Response: { "ok": true }

GET /api/auth/me
  Header: Authorization: Bearer {token}
  Response: { "authenticated": true }
```

### System

```
GET /api/health
  (no auth)
  Response: { "status": "ok", "db": "ok" }

GET /api/status
  Header: Authorization: Bearer {token}
  Response: {
    "feeds_count": 10,
    "posts_count": 5000,
    "unread_count": 150,
    "queue_size": 5,
    "circuit_breaker": "CLOSED",
    "health_warning": null,
    "db_size_mb": 50
  }
```

### Categories

```
GET /api/categories
  Response: [{ "id": 1, "name": "Tech", "parent_id": null, "unread_count": 50 }, ...]

POST /api/categories
  Body: { "name": "...", "parent_id": null }
  Response: { "id": 1, ... }

PUT /api/categories/:id
  Body: { "name": "...", "parent_id": null }
  Response: { "id": 1, ... }

DELETE /api/categories/:id
  Response: { "ok": true }

PATCH /api/categories/reorder
  Body: [{ "id": 1, "position": 0 }, { "id": 2, "position": 1 }]
  Response: { "ok": true }
```

### Feeds

```
GET /api/feeds
  Query: ?category_id=1&include_disabled=false
  Response: [{ "id": 1, "title": "...", "url": "...", "unread_count": 10, "error_count": 0 }, ...]

POST /api/feeds
  Body: { "url": "...", "category_id": 1 }
  Response: { "id": 1, "title": "..." }

PUT /api/feeds/:id
  Body: { "title": "...", "category_id": 2 }
  Response: { "id": 1, ... }

DELETE /api/feeds/:id
  Response: { "ok": true }

POST /api/feeds/:id/refresh
  Response: { "new_posts": 5, "errors": [] }
  Note: ignores next_retry_at and tries immediately.
        If feed was disabled and refresh succeeds, re-enables automatically.

POST /api/feeds/:id/enable
  Response: { "ok": true }
  Note: resets error_count, disabled_at, next_retry_at. Tries immediate fetch.

POST /api/feeds/import-opml
  Body: multipart/form-data with OPML file
  Response: { "imported": 10, "errors": ["..."] }

GET /api/feeds/export-opml
  Response: application/xml (OPML file)
```

### Posts

```
GET /api/posts
  Query: ?feed_id=1&category_id=1&unread_only=true&search=term&limit=50&offset=0
  Response: {
    "posts": [{ "id": 1, "title": "...", "one_line_summary": "...", "published_at": "...", "is_read": false }, ...],
    "total": 500,
    "has_more": true
  }

GET /api/posts/:id
  Response: {
    "id": 1,
    "title": "...",
    "content": "...",
    "full_content": "...",
    "summary_pt": "...",
    "summary_status": "ready" | "pending" | "failed",
    ...
  }

PATCH /api/posts/:id/read
  Body: { "is_read": true }
  Response: { "ok": true }

POST /api/posts/mark-read
  Body: { "post_ids": [1, 2, 3] }
    or { "feed_id": 1 }
    or { "category_id": 1 }
    or { "all": true }
  Response: { "marked": 50 }
```

### Proxy

```
GET /api/proxy?url=https://example.com/article
  Response: Article HTML (sanitized)
```

### Admin (protected)

```
POST /api/admin/reprocess-summary
  Body: { "content_hash": "..." }
  Response: { "ok": true, "queued": true }

POST /api/admin/vacuum
  Response: { "ok": true, "freed_bytes": 1000000 }
```

### Post Ordering

Posts are ordered by `sort_date DESC` (most recent first).

The `sort_date` field is populated on insert:
- `sort_date = published_at` if published_at is not NULL
- `sort_date = fetched_at` otherwise

This simplifies queries and allows a single index for sorting.

### Pagination

- `limit`: default 50, maximum 200
- `offset`: default 0
- Response includes `total` and `has_more` for navigation


## Frontend

### Technologies

- Alpine.js 3.x (reactivity)
- Tailwind CSS (compiled, not CDN in production)
- Vanilla JS for utilities

### Assets

- Always local in production
- CDN only in development (via flag)
- No document.write, eval, or inline scripts

### Behaviors

- JWT token kept in JavaScript variable (memory)
- On page reload: requires login
- Full content (full_content) loaded on demand when opening post
- Visual indicator for pending summary: "Generating summary..."
- Visual indicator for failed summary: "Summary unavailable"
- Visual alert when health_warning present (banner at top)
- Keyboard shortcuts:
  - j/k: navigate between posts
  - Enter: open selected post
  - m: toggle read/unread
  - Esc: close modal


## Nginx

```nginx
server {
    listen 443 ssl http2;
    server_name rss.sarmento.org;

    # SSL via WordOps (Let's Encrypt certificates)
    # ... SSL configuration ...

    root /var/www/rss.sarmento.org/htdocs;

    client_max_body_size 1m;

    # Proxy buffers
    proxy_buffering on;
    proxy_buffer_size 4k;
    proxy_buffers 8 16k;

    # Security headers
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # CSP
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https: data:; font-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self';" always;

    # Static frontend
    location / {
        try_files $uri $uri/ /index.html;
        expires 1h;
    }

    # Assets with long cache
    location /static/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # API backend
    location /api/ {
        proxy_pass http://127.0.0.1:8100;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 30s;
        proxy_read_timeout 60s;
    }
}
```


## Backup

The WordOps/host environment is responsible for system backups.

Recommendation: daily backup of `/var/www/rss.sarmento.org/backend/data/` directory containing:
- reader.db (SQLite database)
- app.log (application logs)

SQLite in WAL mode: for consistent backup, use `sqlite3 reader.db ".backup backup.db"` or ensure no writes during copy.


## Complete Configuration (.env)

```env
# === Database ===
DATABASE_PATH=./data/reader.db

# === Authentication ===
APP_PASSWORD=your_secure_password_here
JWT_SECRET=random_string_minimum_32_characters
JWT_EXPIRATION_HOURS=24

# === Cerebras AI ===
CEREBRAS_API_KEY=your_api_key_here
CEREBRAS_MAX_RPM=20
CEREBRAS_TIMEOUT=30

# === Circuit Breaker ===
FAILURE_THRESHOLD=5
RECOVERY_TIMEOUT_SECONDS=300
HALF_OPEN_MAX_REQUESTS=3

# === HTTP Rate Limiting ===
LOGIN_RATE_LIMIT=5
API_RATE_LIMIT=100
FEEDS_REFRESH_RATE_LIMIT=10

# === Retention ===
MAX_POSTS_PER_FEED=500
MAX_POST_AGE_DAYS=365
MAX_UNREAD_DAYS=90
MAX_DB_SIZE_MB=1024

# === Jobs ===
FEED_UPDATE_INTERVAL_MINUTES=30
SUMMARY_LOCK_TIMEOUT_SECONDS=300
CLEANUP_HOUR=3

# === Proxy ===
PROXY_TIMEOUT_SECONDS=10
PROXY_MAX_SIZE_BYTES=5242880

# === Logging ===
LOG_LEVEL=INFO
LOG_FILE=./data/app.log

# === Security ===
CORS_ORIGINS=https://rss.sarmento.org
```


## Dependencies (requirements.txt)

```
fastapi>=0.109.0
uvicorn[standard]>=0.27.0
sqlalchemy>=2.0.0
alembic>=1.13.0
pydantic-settings>=2.0.0
feedparser>=6.0.0
httpx>=0.26.0
readability-lxml>=0.8.0
lxml>=5.0.0
lxml-html-clean>=0.1.0
bleach>=6.1.0
apscheduler>=3.10.0
python-jose[cryptography]>=3.3.0
python-multipart>=0.0.6
slowapi>=0.1.9
```


## Assumed Limitations

- Single-user (no multi-tenancy)
- No multi-worker (1 uvicorn process)
- No HA (high availability)
- No advanced full-text search (only LIKE on title)
- AI failures don't block the app
- External images are not cached/proxied
- No push notifications
- No offline mode


## Expected Result

The system:
- Doesn't lose state on restart
- Doesn't duplicate jobs
- Doesn't grow indefinitely
- Doesn't expose obvious XSS or SSRF
- Has predictable AI cost
- Is maintainable by a single person
- Degrades gracefully when AI fails
- Recovers automatically from temporary failures
- Provides visibility about problems (health warnings)
