"""Tests for the post list's topic/tag filters, summary status and story cache."""

import threading
import time
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.services.stories as stories
from app.database import Base
from app.models import Feed, Post, PostTag, SummaryQueue, Topic, TopicTag
from app.routes.posts import list_posts
from app.services.blocked_terms import title_is_blocked, title_matches_term


@pytest.fixture
def db():
    # StaticPool: the story-map refresh thread must see the same in-memory DB
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture(autouse=True)
def empty_story_cache(monkeypatch):
    monkeypatch.setattr(stories, "_cache", {"data": {}, "members": {}, "ts": 1e18})


NOW = datetime(2026, 1, 1)


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


def _seed_topic(db):
    db.add(Feed(id=1, title="Feed", url="https://example.com/feed"))
    db.add(Topic(id=1, name="Linux"))
    db.add_all([TopicTag(topic_id=1, tag="linux"), TopicTag(topic_id=1, tag="kernel")])
    db.add_all(
        [
            Post(id=1, feed_id=1, title="Both tags", sort_date=NOW, is_starred=True),
            Post(id=2, feed_id=1, title="One tag", sort_date=NOW),
            Post(id=3, feed_id=1, title="Off topic", sort_date=NOW),
        ]
    )
    db.add_all(
        [
            PostTag(post_id=1, tag="linux"),
            PostTag(post_id=1, tag="kernel"),
            PostTag(post_id=2, tag="kernel"),
            PostTag(post_id=3, tag="cooking"),
        ]
    )
    db.commit()


def test_topic_lists_each_matching_post_once(db):
    _seed_topic(db)

    result = _list(db, topic_id=1)

    assert sorted(p.id for p in result.posts) == [1, 2]
    assert result.total == 2
    assert result.starred_count == 1
    assert sorted(next(p for p in result.posts if p.id == 1).tags) == [
        "kernel",
        "linux",
    ]


def test_tag_filter_matches_normalized_tag(db):
    _seed_topic(db)

    result = _list(db, tag=" Kernel ")

    assert sorted(p.id for p in result.posts) == [1, 2]
    assert result.starred_count == 1


def test_summary_status_comes_from_the_queue(db):
    db.add(Feed(id=1, title="Feed", url="https://example.com/feed"))
    db.add_all(
        [
            Post(id=1, feed_id=1, title="Queued", content_hash="a", sort_date=NOW),
            Post(id=2, feed_id=1, title="Failed", content_hash="b", sort_date=NOW),
            Post(id=3, feed_id=1, title="Unqueued", content_hash="c", sort_date=NOW),
            Post(id=4, feed_id=1, title="No hash", sort_date=NOW),
        ]
    )
    db.add_all(
        [
            SummaryQueue(post_id=1, content_hash="a"),
            SummaryQueue(post_id=2, content_hash="b", error_type="permanent"),
        ]
    )
    db.commit()

    statuses = {p.id: p.summary_status for p in _list(db).posts}

    assert statuses == {
        1: "pending",
        2: "failed",
        3: "not_configured",
        4: "not_configured",
    }


def test_blocked_terms_match_as_one_pattern_like_term_by_term():
    terms = ["ford", "[review]", "apple tv*series", "*coin", "crypto*"]
    titles = [
        "New Ford Mustang",
        "An affordable laptop",
        "Phone [review]",
        "Apple TV+ renews the series",
        "Bitcoin rallies",
        "Crypto crash",
        "Nothing to see",
        None,
    ]
    for title in titles:
        expected = any(title_matches_term((title or "").lower(), t) for t in terms)
        assert title_is_blocked(title, terms) == expected, title


def test_expired_story_map_is_served_stale_and_rebuilt_in_background(db, monkeypatch):
    stale = {7: (7, 2)}
    monkeypatch.setattr(stories, "_cache", {"data": stale, "members": {}, "ts": 0.0})
    started = threading.Event()
    release = threading.Event()

    def slow_find_stories(session, now=None):
        started.set()
        release.wait(5)
        return [[1, 2]]

    monkeypatch.setattr(stories, "find_stories", slow_find_stories)

    assert stories.get_story_map(db) is stale
    assert started.wait(5)
    # A second expired read while the rebuild runs neither blocks nor
    # starts another one
    assert stories.get_story_map(db) is stale

    release.set()
    deadline = time.monotonic() + 5
    while stories._cache["data"] is stale and time.monotonic() < deadline:
        time.sleep(0.01)
    assert stories._cache["data"] == {1: (1, 2), 2: (1, 2)}
    assert stories.get_story_map(db) == {1: (1, 2), 2: (1, 2)}


def test_story_map_is_built_inline_when_there_is_none(db, monkeypatch):
    monkeypatch.setattr(stories, "_cache", {"data": None, "members": {}, "ts": 0.0})
    monkeypatch.setattr(stories, "find_stories", lambda session, now=None: [[3, 4]])

    assert stories.get_story_map(db) == {3: (3, 2), 4: (3, 2)}
