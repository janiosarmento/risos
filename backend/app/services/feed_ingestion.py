"""
Feed ingestion service.
Integrates parser, normalization, sanitization and deduplication.
"""

import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Feed, Post, SummaryQueue
from app.services.feed_parser import (
    fetch_and_parse,
    ParsedFeed,
    ParsedEntry,
    FeedFetchError,
    FeedParseError,
)
from app.services.url_normalizer import normalize_url
from app.services.html_sanitizer import sanitize_html
from app.services.content_hasher import compute_content_hash

logger = logging.getLogger(__name__)


class FeedIngestionResult:
    """Result of feed ingestion."""

    def __init__(self):
        self.new_posts = 0
        self.skipped_duplicates = 0
        self.errors = []
        self.feed_title_updated = False
        self.site_url_updated = False


def _check_duplicate_by_guid(
    db: Session, feed: Feed, guid: str, normalized_url: Optional[str]
) -> Tuple[bool, bool]:
    """
    Check for duplicates by GUID.

    Returns:
        Tuple of (is_duplicate, had_collision)
    """
    if not guid:
        return False, False

    existing = (
        db.query(Post)
        .filter(Post.feed_id == feed.id, Post.guid == guid)
        .first()
    )

    if not existing:
        return False, False

    # If guid_unreliable, we still need to detect duplicate to avoid
    # constraint violation, but we don't do collision detection
    if feed.guid_unreliable:
        return True, False

    # Check for collision (same GUID, different URL)
    collision = (
        normalized_url
        and existing.normalized_url
        and existing.normalized_url != normalized_url
    )

    return True, collision


def _check_duplicate_by_url(
    db: Session, feed: Feed, normalized_url: Optional[str]
) -> bool:
    """Check for duplicates by normalized URL."""
    if not normalized_url or feed.allow_duplicate_urls:
        return False

    existing = (
        db.query(Post)
        .filter(Post.feed_id == feed.id, Post.normalized_url == normalized_url)
        .first()
    )

    return existing is not None


def _check_duplicate_by_hash(
    db: Session,
    feed: Feed,
    content_hash: Optional[str],
    has_guid: bool,
    has_url: bool,
) -> bool:
    """
    Check for duplicates by content_hash.
    Only used as fallback when GUID and URL are None.
    """
    if not content_hash:
        return False

    # Only use hash as fallback if no GUID or URL
    if has_guid or has_url:
        return False

    existing = (
        db.query(Post)
        .filter(Post.feed_id == feed.id, Post.content_hash == content_hash)
        .first()
    )

    return existing is not None


def _process_entry(
    db: Session, feed: Feed, entry: ParsedEntry, now: datetime
) -> Tuple[Optional[Post], Optional[str]]:
    """
    Process a feed entry.

    Returns:
        Tuple of (created Post or None, error or None)
    """
    # Normalize URL
    normalized_url = normalize_url(entry.url)

    # Sanitize content
    content = sanitize_html(entry.content, truncate=True)

    # Compute hash (includes title and URL to avoid collisions)
    content_hash = compute_content_hash(
        entry.content, title=entry.title, url=entry.url
    )

    # Check for duplicates by GUID
    is_dup, collision = _check_duplicate_by_guid(
        db, feed, entry.guid, normalized_url
    )

    if collision:
        feed.guid_collision_count = (feed.guid_collision_count or 0) + 1
        if feed.guid_collision_count >= 3:
            feed.guid_unreliable = True
            logger.warning(
                f"Feed {feed.id} marked as guid_unreliable "
                f"(collisions: {feed.guid_collision_count})"
            )

    if is_dup:
        return None, None

    # Check for duplicates by URL
    if _check_duplicate_by_url(db, feed, normalized_url):
        return None, None

    # Check for duplicates by hash (fallback)
    if _check_duplicate_by_hash(
        db,
        feed,
        content_hash,
        has_guid=bool(entry.guid),
        has_url=bool(normalized_url),
    ):
        return None, None

    # Create post
    sort_date = entry.published_at or now

    post = Post(
        feed_id=feed.id,
        guid=entry.guid,
        url=entry.url,
        normalized_url=normalized_url,
        title=entry.title,
        author=entry.author,
        content=content,
        content_hash=content_hash,
        published_at=entry.published_at,
        fetched_at=now,
        sort_date=sort_date,
        is_read=False,
    )

    return post, None


async def ingest_feed(db: Session, feed: Feed) -> FeedIngestionResult:
    """
    Ingest a feed: fetch, parse, and insert new posts.

    Args:
        db: Database session
        feed: Feed to ingest

    Returns:
        FeedIngestionResult with statistics
    """
    result = FeedIngestionResult()
    now = datetime.utcnow()

    try:
        # Fetch and parse
        parsed_feed, final_url = await fetch_and_parse(feed.url)

    except (FeedFetchError, FeedParseError) as e:
        result.errors.append(str(e))
        feed.error_count = (feed.error_count or 0) + 1
        feed.last_error = str(e)
        feed.last_error_at = now
        db.commit()
        return result

    # Update feed metadata
    if parsed_feed.title and not feed.title.startswith(feed.url):
        # Only update if it was a placeholder (hostname)
        if "." in feed.title and "/" not in feed.title:
            feed.title = parsed_feed.title
            result.feed_title_updated = True

    if parsed_feed.site_url and not feed.site_url:
        feed.site_url = parsed_feed.site_url
        result.site_url_updated = True

    # Process entries
    for entry in parsed_feed.entries:
        try:
            post, error = _process_entry(db, feed, entry, now)

            if error:
                result.errors.append(error)
                continue

            if post:
                db.add(post)
                db.flush()  # Generate post ID

                # Add to summary queue (if has content_hash)
                if post.content_hash:
                    queue_entry = SummaryQueue(
                        post_id=post.id,
                        content_hash=post.content_hash,
                        priority=0,  # Background priority
                    )
                    db.add(queue_entry)

                result.new_posts += 1
            else:
                result.skipped_duplicates += 1

        except Exception as e:
            logger.error(f"Error processing entry: {e}")
            result.errors.append(str(e))

    # Update feed
    feed.last_fetched_at = now
    feed.error_count = 0  # Reset on success
    feed.last_error = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        result.errors.append(f"Error saving: {e}")
        logger.error(f"Error saving posts for feed {feed.id}: {e}")

    logger.info(
        f"Feed {feed.id} ingested: "
        f"{result.new_posts} new, "
        f"{result.skipped_duplicates} duplicates"
    )

    return result
