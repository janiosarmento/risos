"""Counts behind the sidebar topics and the popular-tags strip."""

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import topics_cache
from app.database import Base
from app.models import Feed, Post, PostTag, Topic, TopicTag
from app.routes.tags import get_popular_tags
from app.routes.topics import list_topics

NOW = datetime(2026, 1, 1)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add_all(
        [
            Feed(id=1, title="Feed A", url="https://a.example/rss"),
            Feed(id=2, title="Feed B", url="https://b.example/rss"),
        ]
    )
    # post 1: read, tags ai+python; post 2: unread, tags ai+rust;
    # post 3: unread + starred, tag rust, feed 2.
    session.add_all(
        [
            Post(id=1, feed_id=1, sort_date=NOW, is_read=True),
            Post(id=2, feed_id=1, sort_date=NOW, is_read=False),
            Post(id=3, feed_id=2, sort_date=NOW, is_read=False, is_starred=True),
        ]
    )
    for post_id, tag in [(1, "ai"), (1, "python"), (2, "ai"), (2, "rust"), (3, "rust")]:
        session.add(PostTag(post_id=post_id, tag=tag))
    session.add_all(
        [
            Topic(id=1, name="Tech", position=1),
            Topic(id=2, name="Empty", position=2),
        ]
    )
    session.add_all(
        [
            TopicTag(topic_id=1, tag="ai"),
            TopicTag(topic_id=1, tag="rust"),
            TopicTag(topic_id=2, tag="cooking"),
        ]
    )
    session.commit()
    topics_cache.invalidate()
    yield session
    session.close()
    topics_cache.invalidate()


def test_topic_counts_dedupe_posts_and_count_unread(db):
    topics = {t["name"]: t for t in list_topics(db=db, user={})}
    # Post 2 matches both "ai" and "rust" but is counted once.
    assert topics["Tech"]["post_count"] == 3
    assert topics["Tech"]["unread_count"] == 2
    assert topics["Empty"]["post_count"] == 0
    assert topics["Empty"]["unread_count"] == 0


def _popular(db, **kwargs):
    defaults = dict(
        limit=10,
        min_count=1,
        unread_only=False,
        starred_only=False,
        suggested_only=False,
        feed_id=None,
        category_id=None,
        topic_id=None,
    )
    defaults.update(kwargs)
    result = get_popular_tags(db=db, user={}, **defaults)
    return {t["tag"]: t["count"] for t in result["tags"]}


def test_popular_tags_unfiltered(db):
    assert _popular(db) == {"ai": 2, "rust": 2, "python": 1}


def test_popular_tags_filters(db):
    assert _popular(db, unread_only=True) == {"ai": 1, "rust": 2}
    assert _popular(db, starred_only=True) == {"rust": 1}
    assert _popular(db, feed_id=2) == {"rust": 1}
    # Topic 1 covers posts 1-3 through "ai"/"rust"; python rides along on post 1.
    assert _popular(db, topic_id=1) == {"ai": 2, "rust": 2, "python": 1}
    assert _popular(db, topic_id=1, unread_only=True) == {"ai": 1, "rust": 2}
