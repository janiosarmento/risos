"""
Main FastAPI application.
RSS Reader backend with AI.
"""

import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app.config import settings
from app.database import engine
from app.rate_limiter import limiter

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler(settings.log_file), logging.StreamHandler()],
)

logger = logging.getLogger(__name__)


def run_migrations():
    """
    Run Alembic migrations automatically.
    Critical failure if unable to apply.
    """
    try:
        # Find alembic.ini relative to project directory
        base_dir = Path(__file__).resolve().parent.parent
        alembic_cfg = Config(str(base_dir / "alembic.ini"))
        alembic_cfg.set_main_option(
            "script_location", str(base_dir / "alembic")
        )

        logger.info("Running database migrations...")
        command.upgrade(alembic_cfg, "head")
        logger.info("Migrations completed successfully")

    except Exception as e:
        logger.critical(f"Failed to run migrations: {e}")
        sys.exit(1)


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
            logger.info(
                "Database does not exist yet, skipping integrity check"
            )
            return

        db_size_mb = db_path.stat().st_size / (1024 * 1024)

        with engine.connect() as conn:
            if db_size_mb > 100:
                logger.info(
                    f"Database size: {db_size_mb:.1f}MB - running quick_check"
                )
                result = conn.execute(text("PRAGMA quick_check;")).fetchone()
            else:
                logger.info(
                    f"Database size: {db_size_mb:.1f}MB - running integrity_check"
                )
                result = conn.execute(
                    text("PRAGMA integrity_check;")
                ).fetchone()

            if result[0] != "ok":
                logger.critical(
                    f"Database integrity check failed: {result[0]}"
                )
                sys.exit(1)

            logger.info("Database integrity check passed")

    except Exception as e:
        logger.critical(f"Failed to check database integrity: {e}")
        sys.exit(1)


def reset_ai_state():
    """
    Reset all AI-related state on startup.
    Clears circuit breaker, API key cooldowns, and queue cooldowns.
    This ensures a fresh start after service restart.
    """
    from app.database import SessionLocal
    from app.models import AppSettings, SummaryQueue

    db = SessionLocal()
    try:
        # Reset circuit breaker state
        db.query(AppSettings).filter(
            AppSettings.key.in_([
                "cerebras_state",
                "cerebras_failures",
                "cerebras_half_successes",
                "cerebras_last_failure",
                "cerebras_last_call",
            ])
        ).delete()

        # Reset queue cooldowns and attempts
        db.query(SummaryQueue).update({
            "cooldown_until": None,
            "attempts": 0,
            "locked_at": None,
        })

        db.commit()
        logger.info("AI state reset: circuit breaker, queue cooldowns cleared")

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

    # Ensure data directory exists
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)

    # Check database integrity (if exists)
    check_database_integrity()

    # Run migrations
    run_migrations()

    # Reset AI state (circuit breaker, cooldowns) for fresh start
    reset_ai_state()

    # Start background jobs scheduler
    await scheduler.start()

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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint (no authentication)
@app.get("/health")
async def health_check():
    """Basic health check"""
    return {"status": "ok"}


# Include routers
from app.routes import auth, categories, feeds, posts, proxy, admin, preferences, suggestions

app.include_router(auth.router, prefix="/api")
app.include_router(categories.router, prefix="/api")
app.include_router(feeds.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(proxy.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(preferences.router, prefix="/api")
app.include_router(suggestions.router, prefix="/api")
