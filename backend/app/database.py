"""
SQLite database configuration with SQLAlchemy.
WAL mode enabled for better concurrency.
"""

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.engine import Engine

from app.config import settings


# Build database URL
DATABASE_URL = f"sqlite:///{settings.database_path}"

# Engine with SQLite settings
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,  # Allow use in multiple threads
    },
    echo=False,  # Change to True for query debug
)


# Configure WAL mode and busy_timeout via PRAGMA
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """
    Configure SQLite PRAGMAs on connect:
    - WAL mode for better concurrency
    - busy_timeout to wait for locks
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


# Declarative base for ORM models
Base = declarative_base()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """
    Dependency injection for FastAPI.
    Provides a database session and ensures it's closed after use.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
