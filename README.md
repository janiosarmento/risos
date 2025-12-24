# Risos

A self-hosted RSS reader with AI-powered article summaries.

> **Risos** = RSS in Portuguese. Also means "laughs" — because reading news should be enjoyable.

## Features

- **RSS/Atom Feed Support** - Subscribe to any RSS or Atom feed
- **AI Summaries** - Automatic article summarization using Cerebras AI
- **Categories** - Organize feeds into categories
- **OPML Import/Export** - Migrate from other readers
- **Keyboard Shortcuts** - Navigate with J/K, mark read with M
- **Dark/Light Theme** - Follows system preference or manual selection
- **Multi-language** - English and Portuguese (Brazilian)
- **Mobile Friendly** - Responsive design

## Screenshots

![Main screen with post list and sidebar](screenshots/1-main_screen.png)

![Settings panel with feeds and categories](screenshots/2-settings.png)

![Post view with original content and AI summary](screenshots/3-post.png)

## Installation

### Option 1: Docker (Recommended for beginners)

1. Clone the repository:
   ```bash
   git clone https://github.com/janiosarmento/risos.git
   cd risos
   ```

2. Copy and edit the environment file:
   ```bash
   cp backend/.env.example backend/.env
   nano backend/.env
   ```

3. Start with Docker Compose:
   ```bash
   docker-compose up -d
   ```

4. Access at `http://localhost:8100`

### Option 2: Native Installation (systemd)

The installer automatically:
- Creates a Python virtual environment
- Installs dependencies
- Runs database migrations
- Creates a systemd service
- **On WordOps**: Configures nginx automatically
- **On other setups**: Shows nginx configuration instructions

#### Installation Steps

1. Clone to your web directory:
   ```bash
   # WordOps example
   cd /var/www/rss.your-domain.com
   git clone https://github.com/janiosarmento/risos.git .

   # Standard nginx example
   git clone https://github.com/janiosarmento/risos.git /var/www/risos
   cd /var/www/risos
   ```

2. Run the installer:
   ```bash
   sudo ./install.sh
   ```

3. Edit the configuration:
   ```bash
   sudo nano backend/.env
   # Set: APP_PASSWORD, JWT_SECRET, CEREBRAS_API_KEY
   ```

4. Restart the service:
   ```bash
   sudo systemctl restart risos
   ```

#### WordOps Users

If WordOps is detected, the installer automatically creates `conf/nginx/custom.conf` with the correct configuration and reloads nginx. No manual nginx setup required.

#### Standard Nginx Users

For non-WordOps setups, configure nginx manually (see Web Server Configuration below).

### Multiple Instances

The app is single-user by design. To run separate instances for different people on the same server, install multiple times with different service names and ports.

The installer automatically detects used ports and suggests the next available one:

```bash
# First instance (you)
cd /var/www/rss.your-domain.com
sudo ./install.sh
# Service name: risos
# Port: 8100 (suggested automatically)

# Second instance (friend) - clone to a different directory first
cd /var/www/rss.friend-domain.com
sudo ./install.sh
# Service name: risos-friend
# Port: 8101 (suggested automatically since 8100 is in use)
```

Each instance has its own:
- Database (`backend/data/reader.db`)
- Configuration (`backend/.env`)
- Systemd service
- Port
- Nginx configuration (auto-generated on WordOps)

## Configuration

### Required Settings

Edit `backend/.env` with:

```bash
# Application password for login
APP_PASSWORD=your_secure_password

# JWT secret (generate with: openssl rand -hex 32)
JWT_SECRET=your_secret_key_minimum_32_characters

# Cerebras AI API key (from https://cloud.cerebras.ai/)
CEREBRAS_API_KEY=your_api_key
```

### Optional Settings

```bash
# Summary language (default: Brazilian Portuguese)
SUMMARY_LANGUAGE=English

# Feed update interval in minutes (default: 30)
FEED_UPDATE_INTERVAL_MINUTES=30

# See .env.example for all options
```

### Web Server Configuration

The application consists of two parts:
- **Frontend** (static files in `htdocs/`) - served directly by your web server
- **Backend** (Python API in `backend/`) - runs on port 8100, proxied via `/api`

You can install this anywhere on your system. Common locations:

| Stack | Typical Path |
|-------|--------------|
| WordOps | `/var/www/your-domain.com/htdocs` (frontend) |
| Standard nginx | `/var/www/html` or `/var/www/your-site` |
| Apache | `/var/www/html` |
| Custom | Anywhere you prefer |

#### Nginx Example

```nginx
server {
    listen 80;
    server_name your-domain.com;

    root /path/to/risos/htdocs;
    index index.html;

    # Frontend - SPA routing (serves index.html for all routes)
    location / {
        try_files $uri $uri/ /index.html;
        expires 1h;
    }

    # Backend API (proxy to Python backend)
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

    # Static assets caching
    location /static/ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
}
```

**Important:** The `try_files $uri $uri/ /index.html` directive is essential for SPA routing. It ensures that direct navigation to any URL (e.g., bookmarks, page refresh) serves the frontend, which then handles routing client-side.

#### Apache Example

```apache
<VirtualHost *:80>
    ServerName your-domain.com
    DocumentRoot /path/to/risos/htdocs

    <Directory /path/to/risos/htdocs>
        AllowOverride All
        Require all granted

        # SPA routing - serve index.html for all routes
        FallbackResource /index.html
    </Directory>

    # Backend API proxy
    ProxyPreserveHost On
    ProxyPass /api http://127.0.0.1:8100/api
    ProxyPassReverse /api http://127.0.0.1:8100/api
</VirtualHost>
```

**Note:** For Apache, enable required modules: `a2enmod proxy proxy_http rewrite`

## Customization

### AI Prompts

Edit `backend/prompts.yaml` to customize how summaries are generated:

```yaml
system_prompt: |
  Your custom system prompt here...

user_prompt: |
  Summarize in {language}:
  {content}
```

### Translations

Add or edit translations in `htdocs/static/locales/`:
- `en-US.json` - English
- `pt-BR.json` - Portuguese (Brazilian)

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `J` | Next post |
| `K` | Previous post |
| `M` | Toggle read/unread |
| `S` | Toggle star/favorite |
| `R` | Regenerate AI summary |
| `Enter` | Open selected post |
| `Escape` | Close modal |

## Tech Stack

- **Backend**: Python, FastAPI, SQLite
- **Frontend**: Alpine.js, Tailwind CSS
- **AI**: Cerebras API (Llama 3.3 70B)

## About This Project: 100% Vibe Coded

This entire project was developed through **Vibe Coding** using [Claude Code](https://claude.ai/claude-code) — not a single line of code was written or edited manually. Every file, every function, every CSS rule was generated through AI-assisted development.

This is both a testament to how far AI coding tools have come, and a reminder of what it actually takes to use them effectively.

### The Tools Are Impressive, But...

Modern LLMs can write excellent code. They understand patterns, follow best practices, and can implement complex features in seconds. But here's what this project taught us:

**AI doesn't replace expertise — it amplifies it.**

The quality of AI-generated code is directly proportional to the quality of the guidance it receives. Knowing *what* to ask for, *how* to structure a system, *when* to push back on a suggestion, and *which* patterns to follow — these still require deep technical knowledge.

Without understanding software architecture, you can't evaluate if the AI's suggestion is sound. Without knowing security principles, you won't catch vulnerabilities. Without experience debugging production systems, you won't ask the right questions when things break.

### What Vibe Coding Actually Requires

- **Clear architectural vision** — The AI can build what you describe, but you need to know what to describe
- **Pattern recognition** — Spotting when generated code is heading in the wrong direction
- **Technical vocabulary** — Communicating precisely what you need
- **Quality judgment** — Knowing good code from bad, even if you didn't write it
- **Debugging skills** — When it doesn't work, you still need to understand why

### The Bottom Line

AI coding assistants are extraordinary tools that can 10x productivity for experienced developers. But they're not magic wands that let anyone build production software.

The future isn't "AI replaces programmers" — it's "programmers who master AI tools outperform those who don't."

This project exists because of excellent AI tools *and* years of accumulated knowledge about how software should be built.

---

## Development

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8100
```

### Frontend

The frontend uses CDN-hosted Alpine.js and Tailwind CSS, so no build step is required. Just edit the files in `htdocs/`.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/login` | Login |
| GET | `/api/feeds` | List feeds |
| POST | `/api/feeds` | Add feed |
| GET | `/api/posts` | List posts |
| POST | `/api/posts/{id}/read` | Mark as read |
| GET | `/api/categories` | List categories |
| POST | `/api/feeds/import-opml` | Import OPML |
| GET | `/api/feeds/export-opml` | Export OPML |

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
