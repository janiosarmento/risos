"""
Alembic environment configuration.
Imports the application's models so autogenerate can see them.
"""
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import Base and the application's models
from app.database import Base
from app.config import settings
import app.models  # noqa: F401 - needed to register models on the metadata

# Alembic Config object
config = context.config

# Set the DB URL from the application's own config
config.set_main_option("sqlalchemy.url", f"sqlite:///{settings.database_path}")

# Setup logging. disable_existing_loggers=False is required here: the
# default (True) silently disables every logger already created by the
# time this runs — including app.main's, since run_migrations() calls
# this from inside the FastAPI lifespan, after main.py's own
# logging.basicConfig() already created it. Left at the default, every
# logger.info() call anywhere in the app goes silent for the rest of
# that worker process's life the moment migrations finish — confirmed
# in prod: "Running database migrations..." appears hundreds of times
# in the log, "Migrations completed successfully" (the very next log
# call in run_migrations()) never once. Found 2026-09-13 while
# investigating a separate "AI curation looks broken" report — this
# bug didn't cause that one, but its info-log silencing is exactly why
# that investigation had no diagnostic breadcrumbs to go on.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Model metadata for autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """
    Run migrations in 'offline' mode.
    Gera SQL sem conectar ao banco.
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite requer batch mode para ALTER TABLE
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """
    Run migrations in 'online' mode.
    Conecta ao banco e executa migrations.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite requer batch mode para ALTER TABLE
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
