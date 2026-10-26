"""
Main FastAPI application.
RSS Reader backend with AI.
"""

import fcntl
import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from alembic import command
from app.config import settings
from app.database import engine
from app.rate_limiter import limiter
from app.routes import (
    admin,
    auth,
    categories,
    feeds,
    posts,
    preferences,
    suggestions,
    tags,
    topics,
)
from app.services.ai._types import (
    ModelNotFound,
    PermanentError,
    RateLimited,
    TemporaryError,
)

# Configure logging — force=True ensures this overrides any prior config
# (e.g. from uvicorn or alembic importing first)
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(settings.log_file),
        logging.StreamHandler(),
    ],
    force=True,
)

logger = logging.getLogger(__name__)


def run_migrations():
    """
    Run Alembic migrations automatically.
    Critical failure if unable to apply.

    Serialized with a file lock so that with more than one gunicorn worker
    only one process migrates at a time; the others block briefly and then
    find the schema already at head.
    """
    data_dir = Path(settings.database_path).parent
    data_dir.mkdir(parents=True, exist_ok=True)
    lock_path = data_dir / ".migrate.lock"

    # alembic/env.py calls logging.config.fileConfig() on import, which
    # reconfigures the ROOT logger's level and handlers per alembic.ini's own
    # [logger_root] section (level=WARNING, a bare console handler) — fine for
    # the standalone `alembic upgrade` CLI this .ini is meant for, but here
    # command.upgrade() runs it inside our already-running app, and it
    # clobbers logging.basicConfig()'s setup from module import time. Left
    # unguarded, every logger.info() call anywhere in the app — not just this
    # function — goes silent for the rest of that worker process's life the
    # moment migrations finish: confirmed in prod, "Running database
    # migrations..." appears hundreds of times in the log, "Migrations
    # completed successfully" (the very next line below) never once. Save
    # and restore the root logger's own config around the upgrade call so our
    # own logging survives; found 2026-09-13 investigating an unrelated "AI
    # curation looks broken" report — didn't cause that one, but its
    # info-log silencing is exactly why that investigation had no
    # diagnostic breadcrumbs to go on.
    root_logger = logging.getLogger()
    saved_level = root_logger.level
    saved_handlers = list(root_logger.handlers)

    with open(lock_path, "w") as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        try:
            # Find alembic.ini relative to project directory
            base_dir = Path(__file__).resolve().parent.parent
            alembic_cfg = Config(str(base_dir / "alembic.ini"))
            alembic_cfg.set_main_option("script_location", str(base_dir / "alembic"))

            logger.info("Running database migrations...")
            command.upgrade(alembic_cfg, "head")
            # Restore before this next log call, not just in `finally` below —
            # alembic's fileConfig already clobbered the root logger by the
            # time command.upgrade() returns, so this line would otherwise be
            # the one log call still lost to it.
            root_logger.setLevel(saved_level)
            root_logger.handlers = saved_handlers
            logger.info("Migrations completed successfully")

        except Exception as e:
            logger.critical(f"Failed to run migrations: {e}")
            sys.exit(1)
        finally:
            root_logger.setLevel(saved_level)
            root_logger.handlers = saved_handlers
            fcntl.flock(lock_file, fcntl.LOCK_UN)


def check_database_integrity():
    """
    Check SQLite database integrity.
    - DB > 100MB: PRAGMA quick_check (faster)
    - DB <= 100MB: PRAGMA integrity_check (complete)
    Critical failure if corruption detected.
    """
    try:
        db_path = Path(settings.database_path)

        if not db_path.exists():
            logger.info("Database does not exist yet, skipping integrity check")
            return

        db_size_mb = db_path.stat().st_size / (1024 * 1024)

        with engine.connect() as conn:
            if db_size_mb > 100:
                logger.info(f"Database size: {db_size_mb:.1f}MB - running quick_check")
                result = conn.execute(text("PRAGMA quick_check;")).fetchone()
            else:
                logger.info(
                    f"Database size: {db_size_mb:.1f}MB - running integrity_check"
                )
                result = conn.execute(text("PRAGMA integrity_check;")).fetchone()

            if result[0] != "ok":
                logger.critical(f"Database integrity check failed: {result[0]}")
                sys.exit(1)

            logger.info("Database integrity check passed")

        # Release every physical connection in the SQLite pool so no stale
        # lock survives into the Alembic run
        engine.dispose()

    except Exception as e:
        logger.critical(f"Failed to check database integrity: {e}")
        sys.exit(1)


def reset_ai_state():
    """
    Reset the summary queue's cooldowns, attempts and locks on startup, so a
    service restart gives every queued item a fresh start.
    """
    from app.database import SessionLocal
    from app.models import SummaryQueue

    db = SessionLocal()
    try:
        db.query(SummaryQueue).update(
            {
                "cooldown_until": None,
                "attempts": 0,
                "locked_at": None,
            }
        )

        db.commit()
        logger.info("AI state reset: queue cooldowns cleared")

    except Exception as e:
        logger.error(f"Error resetting AI state: {e}")
        db.rollback()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown.
    Runs critical checks on startup.
    """
    from app.services.scheduler import scheduler

    # Startup
    logger.info("Starting RSS Reader application")
    logger.info(f"Database: {settings.database_path}")
    logger.info(f"Log level: {settings.log_level}")

    # index.html is generated locally (python -m app.html_assembler) before
    # committing. Never run it on the server: the checkout is read-only there.

    # Ensure data directory exists
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)

    # Check database integrity (if exists)
    check_database_integrity()

    # Run migrations
    run_migrations()

    # Reset queue cooldowns for a fresh start
    reset_ai_state()

    # Start background jobs scheduler
    await scheduler.start()

    # Build the story grouping now, so the first post list doesn't wait on it
    from app.database import engine
    from app.services.stories import refresh_story_map_in_background

    refresh_story_map_in_background(engine)

    yield

    # Shutdown
    logger.info("Shutting down RSS Reader application")
    await scheduler.stop()


# Create FastAPI app
app = FastAPI(
    title="RSS Reader API",
    description="RSS Reader with AI summaries",
    version="1.0.0",
    lifespan=lifespan,
)

# Rate limiter setup
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# AI error handlers — log technical detail, return user-friendly message
@app.exception_handler(RateLimited)
async def handle_rate_limited(request: Request, exc: RateLimited):
    logger.warning(f"RateLimited on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=502,
        content={"detail": "AI rate limit reached. Try again in a few minutes."},
    )


@app.exception_handler(TemporaryError)
async def handle_temporary_error(request: Request, exc: TemporaryError):
    logger.warning(f"AI TemporaryError on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=502,
        content={"detail": "AI temporarily unavailable. Try again shortly."},
    )


@app.exception_handler(ModelNotFound)
async def handle_model_not_found(request: Request, exc: ModelNotFound):
    logger.error(f"ModelNotFound on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=502,
        content={
            "detail": "The configured AI model is unavailable. Check Settings > AI."
        },
    )


@app.exception_handler(PermanentError)
async def handle_permanent_error(request: Request, exc: PermanentError):
    logger.error(f"AI PermanentError on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=502,
        content={"detail": "AI could not process this request."},
    )


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(categories.router, prefix="/api")
app.include_router(feeds.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(suggestions.router, prefix="/api")
app.include_router(tags.router, prefix="/api")
app.include_router(topics.router, prefix="/api")
