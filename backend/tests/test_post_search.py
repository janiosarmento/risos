"""Tests for the post list's search box, backed by the posts_fts index."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import AISummary, Feed, Post
from app.routes.posts import list_posts

NOW = datetime(2026, 1, 1)


@pytest.fixture
def db(fts_engine):
    session = sessionmaker(bind=fts_engine)()
    session.add(Feed(id=1, title="Feed", url="https://example.com/feed"))
    session.commit()
    yield session
    session.close()


def _add(db, post_id, title, summary=None, **kwargs):
    # Higher ids are newer, so the default newest-first order is by id desc.
    db.add(
        Post(
            id=post_id,
            feed_id=1,
            title=title,
            content_hash=f"hash-{post_id}",
            sort_date=NOW + timedelta(hours=post_id),
            **kwargs,
        )
    )
    if summary:
        db.add(
            AISummary(
                content_hash=f"hash-{post_id}",
                summary_pt=summary,
                one_line_summary="",
            )
        )
    db.commit()


def _search(db, search, **kwargs):
    params = dict(
        feed_id=None,
        category_id=None,
        tag=None,
        topic_id=None,
        unread_only=False,
        starred_only=False,
        suggested_only=False,
        no_summary_only=False,
        keep_unread_only=False,
        blocked_only=False,
        search=search,
        limit=20,
        offset=0,
    )
    params.update(kwargs)
    return list_posts(**params, db=db, user={})


def _ids(result):
    return [p.id for p in result.posts]


def test_all_words_must_match_in_any_order(db):
    _add(db, 1, "Apple Health adds sleep score")
    _add(db, 2, "Health insurance costs rise")
    _add(db, 3, "New health features for Apple Watch")

    result = _search(db, "health apple")

    assert _ids(result) == [3, 1]
    assert result.total == 2


def test_long_words_match_as_prefix(db):
    _add(db, 1, "Kubernetes 1.40 released")
    _add(db, 2, "Cube puzzle world record")

    assert _ids(_search(db, "kube")) == [1]


def test_short_words_match_exactly(db):
    _add(db, 1, "AI tools for writers")
    _add(db, 2, "Aid workers return home")

    assert _ids(_search(db, "ai")) == [1]


def test_accents_are_ignored(db):
    _add(db, 1, "Café opens downtown")
    _add(db, 2, "Cafe prices climb")

    assert _ids(_search(db, "café")) == [2, 1]
    assert _ids(_search(db, "cafe")) == [2, 1]


def test_ai_summary_is_searched(db):
    _add(db, 1, "New release", summary="Built by the Arc browser team.")
    _add(db, 2, "Another release")

    assert _ids(_search(db, "arc browser")) == [1]


def test_symbol_searches_fall_back_to_substring(db):
    _add(db, 1, "What's new in C++26")
    _add(db, 2, "Series C funding for a startup")

    assert _ids(_search(db, "c++")) == [1]


def test_starred_count_follows_search(db):
    _add(db, 1, "Arc browser news", is_starred=True)
    _add(db, 2, "Firefox news", is_starred=True)

    assert _search(db, "arc").starred_count == 1
