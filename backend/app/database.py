"""
SQLite database configuration with SQLAlchemy.
WAL mode enabled for better concurrency.
"""

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import declarative_base, sessionmaker

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
    - cache_size / mmap_size / temp_store to keep the working set in RAM.
      The DB is ~500MB and the host has spare memory; without this only a
      couple of MB are cached and heavy aggregate queries (e.g. topic
      counts) hammer the disk.
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA cache_size=-65536")  # 64 MiB page cache per connection
    cursor.execute("PRAGMA mmap_size=268435456")  # 256 MiB memory-mapped I/O
    cursor.execute("PRAGMA temp_store=MEMORY")  # temp b-trees (DISTINCT/sort) in RAM
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
