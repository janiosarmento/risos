"""
Configuração do banco de dados SQLite com SQLAlchemy.
WAL mode habilitado para melhor concorrência.
"""
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy.engine import Engine

from app.config import settings


# Construir URL do banco
DATABASE_URL = f"sqlite:///{settings.database_path}"

# Engine com configurações para SQLite
engine = create_engine(
    DATABASE_URL,
    connect_args={
        "check_same_thread": False,  # Permite uso em múltiplas threads
    },
    echo=False,  # Mude para True para debug de queries
)


# Configurar WAL mode e busy_timeout via PRAGMA
@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_conn, connection_record):
    """
    Configura PRAGMAs do SQLite ao conectar:
    - WAL mode para melhor concorrência
    - busy_timeout para esperar locks
    """
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


# Base declarativa para modelos ORM
Base = declarative_base()

# Session factory
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """
    Dependency injection para FastAPI.
    Fornece uma sessão do banco e garante que seja fechada após uso.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
