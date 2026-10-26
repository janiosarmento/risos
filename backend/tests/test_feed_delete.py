"""Deleting a feed removes its posts and their summary queue entries."""

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Feed, Post, PostTag, SummaryQueue
from app.routes.feeds import delete_feed


def test_delete_feed_cascades_to_posts_tags_and_queue():
    # No PRAGMA foreign_keys here (nor in production): the ORM cascade alone
    # must clean up, which is why Post.summary_queue_entry exists.
    session = sessionmaker(bind=create_engine("sqlite://"))()
    Base.metadata.create_all(session.get_bind())
    session.add(Feed(id=1, title="Feed", url="https://example.com/feed"))
    session.add(Post(id=1, feed_id=1, title="Post", sort_date=datetime(2026, 1, 1)))
    session.add(PostTag(post_id=1, tag="linux"))
    session.add(SummaryQueue(post_id=1, content_hash="h"))
    session.commit()

    delete_feed(feed_id=1, db=session, user={})

    assert session.query(Post).count() == 0
    assert session.query(PostTag).count() == 0
    assert session.query(SummaryQueue).count() == 0
