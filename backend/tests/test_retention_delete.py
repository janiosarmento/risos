"""Retention's bulk post delete also removes the posts' tags and queue entries."""

from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Feed, Post, PostTag, SummaryQueue
from app.services.scheduler import delete_posts


def test_delete_posts_removes_dependent_rows():
    session = sessionmaker(bind=create_engine("sqlite://"))()
    Base.metadata.create_all(session.get_bind())
    session.add(Feed(id=1, title="Feed", url="https://example.com/feed"))
    for post_id, is_read in ((1, True), (2, False)):
        session.add(
            Post(
                id=post_id,
                feed_id=1,
                title="Post",
                sort_date=datetime(2026, 1, 1),
                is_read=is_read,
            )
        )
        session.add(PostTag(post_id=post_id, tag="linux"))
        session.add(SummaryQueue(post_id=post_id, content_hash=f"h{post_id}"))
    session.commit()

    assert delete_posts(session, Post.is_read.is_(True)) == 1
    session.commit()

    assert [p.id for p in session.query(Post)] == [2]
    assert [t.post_id for t in session.query(PostTag)] == [2]
    assert [q.post_id for q in session.query(SummaryQueue)] == [2]
