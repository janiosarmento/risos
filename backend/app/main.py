"""
Aplicação FastAPI principal.
Backend do RSS Reader com IA.
"""
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.config import settings
from app.database import engine

# Configurar logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(settings.log_file),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def run_migrations():
    """
    Executa migrations do Alembic automaticamente.
    Falha crítica se não conseguir aplicar.
    """
    try:
        # Encontrar alembic.ini relativo ao diretório do projeto
        base_dir = Path(__file__).resolve().parent.parent
        alembic_cfg = Config(str(base_dir / "alembic.ini"))
        alembic_cfg.set_main_option("script_location", str(base_dir / "alembic"))

        logger.info("Running database migrations...")
        command.upgrade(alembic_cfg, "head")
        logger.info("Migrations completed successfully")

    except Exception as e:
        logger.critical(f"Failed to run migrations: {e}")
        sys.exit(1)


def check_database_integrity():
    """
    Verifica integridade do banco SQLite.
    - DB > 100MB: PRAGMA quick_check (mais rápido)
    - DB <= 100MB: PRAGMA integrity_check (completo)
    Falha crítica se detectar corrupção.
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
                logger.info(f"Database size: {db_size_mb:.1f}MB - running integrity_check")
                result = conn.execute(text("PRAGMA integrity_check;")).fetchone()

            if result[0] != "ok":
                logger.critical(f"Database integrity check failed: {result[0]}")
                sys.exit(1)

            logger.info("Database integrity check passed")

    except Exception as e:
        logger.critical(f"Failed to check database integrity: {e}")
        sys.exit(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager para startup e shutdown.
    Executa verificações críticas no startup.
    """
    from app.services.scheduler import scheduler

    # Startup
    logger.info("Starting RSS Reader application")
    logger.info(f"Database: {settings.database_path}")
    logger.info(f"Log level: {settings.log_level}")

    # Garantir que o diretório data existe
    Path(settings.database_path).parent.mkdir(parents=True, exist_ok=True)

    # Verificar integridade do banco (se existir)
    check_database_integrity()

    # Executar migrations
    run_migrations()

    # Iniciar scheduler de background jobs
    await scheduler.start()

    yield

    # Shutdown
    logger.info("Shutting down RSS Reader application")
    await scheduler.stop()


# Criar app FastAPI
app = FastAPI(
    title="RSS Reader API",
    description="RSS Reader com resumos em IA",
    version="1.0.0",
    lifespan=lifespan
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint (sem autenticação)
@app.get("/health")
async def health_check():
    """Health check básico"""
    return {"status": "ok"}


# Incluir routers
from app.routes import auth, categories, feeds, posts, proxy, admin
app.include_router(auth.router, prefix="/api")
app.include_router(categories.router, prefix="/api")
app.include_router(feeds.router, prefix="/api")
app.include_router(posts.router, prefix="/api")
app.include_router(proxy.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
