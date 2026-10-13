"""Posts whose title matches a blocked term must never reach the LLM."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import AppSettings, Feed, Post, SummaryQueue
from app.services.blocked_terms import title_is_blocked
from app.services.scheduler import Scheduler


def test_title_is_blocked():
    assert title_is_blocked("New Ford Mustang revealed", ["ford"])
    assert not title_is_blocked("An affordable laptop", ["ford"])
    assert title_is_blocked("Crypto crash deepens", ["crypto*"])
    assert not title_is_blocked(None, ["ford"])
    assert not title_is_blocked("Anything", [])


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    session.add(AppSettings(key="pref_blocked_terms", value="ford"))
    session.add(Feed(id=1, title="Example", url="https://example.com/feed"))
    session.commit()
    yield session
    session.close()


def _queued(db, title, priority=0, starred=False):
    post = Post(
        feed_id=1,
        title=title,
        content="Body text.",
        content_hash=f"hash-{title}-{priority}-{starred}",
        is_starred=starred,
    )
    db.add(post)
    db.flush()
    entry = SummaryQueue(
        post_id=post.id, content_hash=post.content_hash, priority=priority
    )
    db.add(entry)
    db.commit()
    return post, entry


def test_worker_drops_blocked_background_entry(db):
    post, entry = _queued(db, "New Ford Mustang revealed")

    result = Scheduler()._validate_and_prepare_post(db, entry)

    assert result == (None, None, None)
    assert db.query(SummaryQueue).count() == 0
    # Not flagged, so removing the term lets backfill summarize it later
    assert not post.skip_summary


def test_worker_keeps_unblocked_entry(db):
    post, entry = _queued(db, "A new laptop")

    returned_post, content, _ = Scheduler()._validate_and_prepare_post(db, entry)

    assert returned_post is post
    assert content == "Body text."


@pytest.mark.parametrize("priority,starred", [(10, False), (0, True)])
def test_worker_honors_explicit_requeue_and_starred(db, priority, starred):
    post, entry = _queued(
        db, "New Ford Mustang revealed", priority=priority, starred=starred
    )

    returned_post, _, _ = Scheduler()._validate_and_prepare_post(db, entry)

    assert returned_post is post
