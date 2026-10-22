"""add posts_fts full-text index for related-post search

A contentless FTS5 index over each post's title and its AI summary fields,
ranked with BM25 by the Smart Assistant's related-post search. Triggers keep
it in sync with `posts` and `ai_summaries`, so no write path in the app needs
to know the index exists.

Revision ID: c3f9a1b7d5e2
Revises: b8d2e4f6a1c3
Create Date: 2026-10-22

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "c3f9a1b7d5e2"
down_revision = "b8d2e4f6a1c3"
branch_labels = None
depends_on = None

# Rows to (re)index, as a SELECT over posts joined to their summary.
_ROWS = """
    SELECT p.id, coalesce(p.title, ''), coalesce(s.translated_title, ''),
           coalesce(s.one_line_summary, ''), coalesce(s.summary_pt, '')
    FROM posts p
    LEFT JOIN ai_summaries s ON s.content_hash = p.content_hash
"""
_INSERT = (
    "INSERT INTO posts_fts(rowid, title, translated_title, one_line, summary)" + _ROWS
)


def _refresh_hash(ref: str) -> str:
    """Reindex every post sharing the summary's content hash *ref*."""
    return f"""
        DELETE FROM posts_fts
        WHERE rowid IN (SELECT id FROM posts WHERE content_hash = {ref});
        {_INSERT} WHERE p.content_hash = {ref};
    """


TRIGGERS = {
    "posts_fts_after_insert": f"""
        AFTER INSERT ON posts BEGIN
            {_INSERT} WHERE p.id = NEW.id;
        END""",
    "posts_fts_after_delete": """
        AFTER DELETE ON posts BEGIN
            DELETE FROM posts_fts WHERE rowid = OLD.id;
        END""",
    "posts_fts_after_update": f"""
        AFTER UPDATE OF title, content_hash ON posts BEGIN
            DELETE FROM posts_fts WHERE rowid = OLD.id;
            {_INSERT} WHERE p.id = NEW.id;
        END""",
    "ai_summaries_fts_after_insert": f"""
        AFTER INSERT ON ai_summaries BEGIN
            {_refresh_hash("NEW.content_hash")}
        END""",
    "ai_summaries_fts_after_update": f"""
        AFTER UPDATE OF content_hash, translated_title, one_line_summary,
            summary_pt ON ai_summaries BEGIN
            {_refresh_hash("OLD.content_hash")}
            {_refresh_hash("NEW.content_hash")}
        END""",
    "ai_summaries_fts_after_delete": f"""
        AFTER DELETE ON ai_summaries BEGIN
            {_refresh_hash("OLD.content_hash")}
        END""",
}

STATEMENTS = [
    """
    CREATE VIRTUAL TABLE posts_fts USING fts5(
        title, translated_title, one_line, summary,
        content = '',
        contentless_delete = 1,
        tokenize = 'unicode61 remove_diacritics 2'
    )
    """,
    *(f"CREATE TRIGGER {name} {body}" for name, body in TRIGGERS.items()),
    _INSERT,
]


def upgrade():
    for statement in STATEMENTS:
        op.execute(statement)


def downgrade():
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute("DROP TABLE IF EXISTS posts_fts")
