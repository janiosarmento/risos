"""Make the backend package importable, and share fixtures across tests."""

import importlib.util
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importing a route module pulls in the sanitizer, and therefore bleach, which
# a developer machine may not have (requirements.txt pins an editable dep that
# only exists on the deploy host, so a clean local install fails). Nothing in
# the test suite sanitizes HTML, so a stub keeps collection working without
# pretending to provide the real behaviour.
try:  # pragma: no cover - depends on the local environment
    import bleach  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover
    stub = types.ModuleType("bleach")

    def _unavailable(*args, **kwargs):
        raise RuntimeError("bleach is stubbed out in tests; install it to use it")

    stub.clean = _unavailable
    stub.linkify = _unavailable
    css_sanitizer = types.ModuleType("bleach.css_sanitizer")
    css_sanitizer.CSSSanitizer = _unavailable
    stub.css_sanitizer = css_sanitizer
    sys.modules["bleach"] = stub
    sys.modules["bleach.css_sanitizer"] = css_sanitizer


FTS_MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic/versions/c3f9a1b7d5e2_add_posts_fts_index.py"
)


@pytest.fixture
def fts_engine():
    """In-memory database with the full schema plus the posts_fts index.

    The index and its triggers live only in their Alembic migration, so the
    migration's own statements are run here instead of a copy of them.
    """
    from sqlalchemy import create_engine, text

    from app.database import Base

    spec = importlib.util.spec_from_file_location("fts_migration", FTS_MIGRATION)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for statement in migration.STATEMENTS:
            conn.execute(text(statement))
    return engine
