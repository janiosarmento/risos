"""Tests for the keep-unread sidebar view: the list filter and its count."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Feed, Post
from app.routes.posts import list_posts


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


NOW = datetime(2026, 1, 1)


def _post(**kwargs) -> Post:
    return Post(sort_date=NOW, **kwargs)


def _list(db, **kwargs):
    defaults = dict(
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
        search=None,
        limit=20,
        offset=0,
    )
    defaults.update(kwargs)
    return list_posts(**defaults, db=db, user={})


def test_keep_unread_only_lists_protected_posts(db):
    db.add(Feed(id=1, title="Feed", url="https://example.com/feed"))
    db.add(_post(id=1, feed_id=1, title="Protected", keep_unread=True))
    db.add(_post(id=2, feed_id=1, title="Plain unread"))
    db.add(_post(id=3, feed_id=1, title="Read", is_read=True))
    db.commit()

    result = _list(db, keep_unread_only=True, unread_only=True)

    assert [p.id for p in result.posts] == [1]
    assert result.keep_unread_count == 1


def test_keep_unread_count_is_global(db):
    db.add(Feed(id=1, title="Feed A", url="https://example.com/a"))
    db.add(Feed(id=2, title="Feed B", url="https://example.com/b"))
    db.add(_post(id=1, feed_id=1, title="A", keep_unread=True))
    db.add(_post(id=2, feed_id=2, title="B", keep_unread=True))
    db.commit()

    result = _list(db, feed_id=1)

    assert result.keep_unread_count == 2
