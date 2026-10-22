"""Tests for the assistant's keyword search for related posts."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AISummary, Feed, Post, PostTag
from app.routes.posts import _keywords_from_title, _text_search_related

NOW = datetime(2026, 1, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(Feed(id=1, title="Feed", url="https://example.com/feed"))
    session.commit()
    yield session
    session.close()


def _add(db, post_id, title, content=None, summary=None, tags=()):
    content_hash = f"hash-{post_id}" if summary else None
    db.add(
        Post(
            id=post_id,
            feed_id=1,
            title=title,
            content=content,
            content_hash=content_hash,
            sort_date=NOW,
        )
    )
    if summary:
        db.add(
            AISummary(
                content_hash=content_hash,
                summary_pt=summary,
                one_line_summary="",
            )
        )
    for tag in tags:
        db.add(PostTag(post_id=post_id, tag=tag))
    db.commit()


def _search(db, keywords, min_common_tags=0, limit=30, active_tags=()):
    results = _text_search_related(
        db,
        post_id=1,
        keywords=keywords,
        active_tags=list(active_tags),
        limit=limit,
        include_read=True,
        include_unread=True,
        min_common_tags=min_common_tags,
    )
    return [r["id"] for r in results]


def test_substring_hits_are_not_related(db):
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "Arc Browser adds split view")
    # "arc" only occurs inside "research", "search" and "March".
    _add(db, 3, "Browser research from March", summary="A search engine study.")

    assert _search(db, ["arc", "browser"]) == [2]


def test_feed_excerpt_does_not_count_as_a_match(db):
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "New browser released", content="Built by the Arc team.")

    assert _search(db, ["arc", "browser"]) == []


def test_ai_summary_counts_as_a_match(db):
    _add(db, 1, "Arc Browser ships tab sync")
    _add(db, 2, "New browser released", summary="<p>Built by the Arc team.</p>")

    assert _search(db, ["arc", "browser"]) == [2]


def test_limit_applies_after_whole_word_filter(db):
    _add(db, 1, "Arc Browser ships tab sync")
    # Substring-only candidates rank first in SQL (two title hits each).
    for post_id in range(2, 6):
        _add(db, post_id, f"Browser research {post_id}")
    _add(db, 10, "Arc Browser update", summary="Arc browser news.")

    assert _search(db, ["arc", "browser"], limit=1) == [10]


def test_keywords_drop_possessive_suffix():
    assert _keywords_from_title("China’s Linux and Apple's desktop") == [
        "apple",
        "china",
        "desktop",
        "linux",
    ]


def test_possessive_matches_its_base_word(db):
    _add(db, 1, "Apple ships desktop")
    # SQL LIKE '%apple%' finds "Apple's"; the whole-word check must too.
    _add(db, 2, "Apple's new desktop")

    assert _search(db, ["apple", "desktop"]) == [2]
