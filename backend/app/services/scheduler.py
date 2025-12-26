"""
Scheduler for background jobs.
Uses database lock to ensure only one active instance.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import SessionLocal
from app.models import SchedulerLock

logger = logging.getLogger(__name__)

# Configuration
HEARTBEAT_INTERVAL = 30  # seconds
LOCK_TIMEOUT = 60  # seconds - lock expires if heartbeat stops


class Scheduler:
    """Background jobs manager with distributed lock."""

    def __init__(self):
        self.instance_id = str(uuid.uuid4())
        self.is_leader = False
        self._running = False
        self._tasks = []

    async def start(self):
        """Start the scheduler."""
        self._running = True
        logger.info(f"Scheduler starting (instance_id: {self.instance_id})")

        # Try to acquire lock
        await self._try_acquire_lock()

        # Start heartbeat
        asyncio.create_task(self._heartbeat_loop())

        # If leader, start jobs
        if self.is_leader:
            await self._start_jobs()

    async def stop(self):
        """Stop the scheduler and release lock."""
        self._running = False
        logger.info("Scheduler stopping...")

        # Cancel tasks
        for task in self._tasks:
            task.cancel()

        # Release lock
        if self.is_leader:
            await self._release_lock()

    async def _try_acquire_lock(self) -> bool:
        """
        Try to acquire leader lock.
        Uses INSERT OR REPLACE with expired heartbeat check.
        """
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            timeout = now - timedelta(seconds=LOCK_TIMEOUT)

            # Check existing lock
            existing = (
                db.query(SchedulerLock).filter(SchedulerLock.id == 1).first()
            )

            if existing:
                # Check if expired
                if existing.heartbeat_at < timeout:
                    logger.info(
                        f"Lock expired (last heartbeat: {existing.heartbeat_at}). "
                        f"Acquiring..."
                    )
                    existing.locked_by = self.instance_id
                    existing.locked_at = now
                    existing.heartbeat_at = now
                    db.commit()
                    self.is_leader = True
                elif existing.locked_by == self.instance_id:
                    # Already the leader
                    self.is_leader = True
                else:
                    # Another process is leader
                    logger.info(
                        f"Another instance is leader: {existing.locked_by}"
                    )
                    self.is_leader = False
            else:
                # Create lock
                lock = SchedulerLock(
                    id=1,
                    locked_by=self.instance_id,
                    locked_at=now,
                    heartbeat_at=now,
                )
                db.add(lock)
                db.commit()
                self.is_leader = True

            if self.is_leader:
                logger.info(f"Lock acquired. This instance is the leader.")

            return self.is_leader

        except Exception as e:
            logger.error(f"Error acquiring lock: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    async def _release_lock(self):
        """Release leader lock."""
        db = SessionLocal()
        try:
            db.query(SchedulerLock).filter(
                SchedulerLock.id == 1,
                SchedulerLock.locked_by == self.instance_id,
            ).delete()
            db.commit()
            logger.info("Lock released")
        except Exception as e:
            logger.error(f"Error releasing lock: {e}")
            db.rollback()
        finally:
            db.close()

    async def _heartbeat_loop(self):
        """Heartbeat loop to keep lock active."""
        while self._running:
            try:
                await asyncio.sleep(HEARTBEAT_INTERVAL)

                if not self._running:
                    break

                if self.is_leader:
                    await self._update_heartbeat()
                else:
                    # Try to acquire lock if not leader
                    await self._try_acquire_lock()
                    if self.is_leader:
                        await self._start_jobs()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Heartbeat error: {e}")

    async def _update_heartbeat(self):
        """Update lock heartbeat."""
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            result = (
                db.query(SchedulerLock)
                .filter(
                    SchedulerLock.id == 1,
                    SchedulerLock.locked_by == self.instance_id,
                )
                .update({"heartbeat_at": now})
            )

            if result == 0:
                # Lost the lock
                logger.warning("Lock lost! Another instance took over.")
                self.is_leader = False
                # Cancel jobs
                for task in self._tasks:
                    task.cancel()
                self._tasks = []
            else:
                db.commit()

        except Exception as e:
            logger.error(f"Error updating heartbeat: {e}")
            db.rollback()
        finally:
            db.close()

    async def _start_jobs(self):
        """Start all background jobs."""
        logger.info("Starting jobs...")

        # Job: update_feeds (every 30 minutes)
        self._tasks.append(asyncio.create_task(self._job_update_feeds()))

        # Job: cleanup_retention (daily at 03:00)
        self._tasks.append(asyncio.create_task(self._job_cleanup_retention()))

        # Job: health_check (every 5 minutes)
        self._tasks.append(asyncio.create_task(self._job_health_check()))

        # Job: process_summaries (every 1 minute)
        self._tasks.append(asyncio.create_task(self._job_process_summaries()))

    async def _job_update_feeds(self):
        """Job to update feeds periodically."""
        from app.services.feed_ingestion import ingest_feed
        from app.models import Feed

        interval = settings.feed_update_interval_minutes * 60

        while self._running and self.is_leader:
            try:
                logger.info("Job update_feeds: starting...")

                db = SessionLocal()
                try:
                    now = datetime.utcnow()

                    # Find eligible feeds
                    feeds = (
                        db.query(Feed)
                        .filter(
                            Feed.disabled_at.is_(None),
                            (Feed.next_retry_at.is_(None))
                            | (Feed.next_retry_at <= now),
                        )
                        .order_by(
                            Feed.error_count.asc()
                        )  # Prioritize feeds without errors
                        .limit(20)
                        .all()
                    )

                    logger.info(
                        f"Job update_feeds: {len(feeds)} feeds to update"
                    )

                    for feed in feeds:
                        if not self._running or not self.is_leader:
                            break

                        try:
                            result = await ingest_feed(db, feed)
                            logger.info(
                                f"Feed {feed.id} updated: "
                                f"{result.new_posts} new, "
                                f"{result.skipped_duplicates} duplicates"
                            )
                        except Exception as e:
                            logger.error(
                                f"Error updating feed {feed.id}: {e}"
                            )

                        # Small delay between feeds
                        await asyncio.sleep(1)

                finally:
                    db.close()

                logger.info("Job update_feeds: completed")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in job update_feeds: {e}")

            # Wait for next cycle
            await asyncio.sleep(interval)

    async def _job_cleanup_retention(self):
        """Job to clean up old posts."""
        from app.models import Post, CleanupLog

        while self._running and self.is_leader:
            try:
                now = datetime.utcnow()

                # Check if it's time to run (03:00)
                target_hour = settings.cleanup_hour
                if now.hour != target_hour:
                    # Calculate time until next execution
                    next_run = now.replace(
                        hour=target_hour, minute=0, second=0, microsecond=0
                    )
                    if now.hour >= target_hour:
                        next_run += timedelta(days=1)
                    wait_seconds = (next_run - now).total_seconds()
                    await asyncio.sleep(
                        min(wait_seconds, 3600)
                    )  # Max 1h wait
                    continue

                logger.info("Job cleanup_retention: starting...")

                db = SessionLocal()
                start_time = datetime.utcnow()

                try:
                    posts_removed = 0
                    full_content_cleared = 0
                    unread_removed = 0

                    # 1. Remove posts read more than MAX_POST_AGE_DAYS ago
                    # (except favorites which are never removed)
                    cutoff_read = now - timedelta(
                        days=settings.max_post_age_days
                    )
                    result = (
                        db.query(Post)
                        .filter(
                            Post.is_read == True,
                            Post.read_at < cutoff_read,
                            (Post.is_starred == False)
                            | (Post.is_starred.is_(None)),
                        )
                        .delete(synchronize_session=False)
                    )
                    posts_removed += result

                    # 2. Remove unread posts older than MAX_UNREAD_DAYS
                    # (except favorites which are never removed)
                    cutoff_unread = now - timedelta(
                        days=settings.max_unread_days
                    )
                    result = (
                        db.query(Post)
                        .filter(
                            Post.is_read == False,
                            Post.fetched_at < cutoff_unread,
                            (Post.is_starred == False)
                            | (Post.is_starred.is_(None)),
                        )
                        .delete(synchronize_session=False)
                    )
                    unread_removed += result

                    # 3. Clear full_content from posts read more than 30 days ago
                    # (except favorites which keep content)
                    cutoff_full = now - timedelta(days=30)
                    result = (
                        db.query(Post)
                        .filter(
                            Post.is_read == True,
                            Post.read_at < cutoff_full,
                            Post.full_content.isnot(None),
                            (Post.is_starred == False)
                            | (Post.is_starred.is_(None)),
                        )
                        .update(
                            {"full_content": None}, synchronize_session=False
                        )
                    )
                    full_content_cleared += result

                    db.commit()

                    # Log in cleanup_logs
                    duration = (datetime.utcnow() - start_time).total_seconds()
                    log = CleanupLog(
                        posts_removed=posts_removed,
                        full_content_cleared=full_content_cleared,
                        unread_removed=unread_removed,
                        duration_seconds=duration,
                    )
                    db.add(log)
                    db.commit()

                    logger.info(
                        f"Job cleanup_retention: completed in {duration:.1f}s - "
                        f"posts removed: {posts_removed}, "
                        f"unread removed: {unread_removed}, "
                        f"full_content cleared: {full_content_cleared}"
                    )

                except Exception as e:
                    db.rollback()
                    raise
                finally:
                    db.close()

                # Wait for next day
                await asyncio.sleep(3600)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in job cleanup_retention: {e}")
                await asyncio.sleep(3600)

    async def _job_health_check(self):
        """Job to check system health."""
        from app.models import AppSettings
        import os

        interval = 300  # 5 minutes

        while self._running and self.is_leader:
            try:
                logger.debug("Job health_check: checking...")

                db = SessionLocal()
                warnings = []

                try:
                    # 1. Check SELECT 1
                    db.execute(text("SELECT 1"))

                    # 2. Check disk space
                    statvfs = os.statvfs(".")
                    free_mb = (statvfs.f_frsize * statvfs.f_bavail) / (
                        1024 * 1024
                    )
                    if free_mb < 100:
                        warnings.append(
                            f"Low disk space: {free_mb:.0f}MB"
                        )

                    # 3. Check database size
                    db_path = settings.database_path
                    if os.path.exists(db_path):
                        db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
                        if db_size_mb > settings.max_db_size_mb:
                            warnings.append(
                                f"Database too large: {db_size_mb:.0f}MB"
                            )

                    # Update app_settings
                    if warnings:
                        warning_text = "; ".join(warnings)
                        logger.warning(
                            f"Health check warnings: {warning_text}"
                        )
                        existing = (
                            db.query(AppSettings)
                            .filter(AppSettings.key == "health_warning")
                            .first()
                        )
                        if existing:
                            existing.value = warning_text
                        else:
                            db.add(
                                AppSettings(
                                    key="health_warning", value=warning_text
                                )
                            )
                    else:
                        db.query(AppSettings).filter(
                            AppSettings.key == "health_warning"
                        ).delete()

                    db.commit()

                except Exception as e:
                    db.rollback()
                    logger.error(f"Health check failed: {e}")
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in job health_check: {e}")

            await asyncio.sleep(interval)

    async def _job_process_summaries(self):
        """Job to process AI summary queue."""
        from app.models import SummaryQueue, AISummary, SummaryFailure, Post
        from app.services.cerebras import (
            generate_summary,
            circuit_breaker,
            TemporaryError,
            PermanentError,
        )
        from app.services.content_extractor import extract_full_content

        # Interval based on rate limit (with safety margin)
        interval = max(5, 60 // settings.cerebras_max_rpm + 1)

        while self._running and self.is_leader:
            try:
                # Check if API can be called
                can_call, reason = circuit_breaker.can_call()
                if not can_call:
                    logger.debug(f"Job process_summaries: {reason}")
                    await asyncio.sleep(interval)
                    continue

                db = SessionLocal()
                try:
                    now = datetime.utcnow()
                    lock_timeout = now - timedelta(
                        seconds=settings.summary_lock_timeout_seconds
                    )

                    # Find next eligible item
                    candidate = (
                        db.query(SummaryQueue)
                        .filter(
                            (SummaryQueue.locked_at.is_(None))
                            | (SummaryQueue.locked_at < lock_timeout),
                            (SummaryQueue.cooldown_until.is_(None))
                            | (SummaryQueue.cooldown_until < now),
                        )
                        .order_by(
                            SummaryQueue.priority.desc(),
                            SummaryQueue.created_at.asc(),
                        )
                        .first()
                    )

                    if not candidate:
                        logger.debug("Job process_summaries: queue empty")
                        await asyncio.sleep(interval)
                        continue

                    # Try to acquire lock atomically
                    result = (
                        db.query(SummaryQueue)
                        .filter(
                            SummaryQueue.id == candidate.id,
                            (SummaryQueue.locked_at.is_(None))
                            | (SummaryQueue.locked_at < lock_timeout),
                        )
                        .update({"locked_at": now})
                    )

                    if result == 0:
                        # Another worker got it
                        db.rollback()
                        continue

                    db.commit()

                    # Check if summary already exists for this hash
                    existing_summary = (
                        db.query(AISummary)
                        .filter(
                            AISummary.content_hash == candidate.content_hash
                        )
                        .first()
                    )

                    if existing_summary:
                        # Summary already exists, remove from queue
                        db.query(SummaryQueue).filter(
                            SummaryQueue.id == candidate.id
                        ).delete()
                        db.commit()
                        logger.debug(
                            f"Summary already exists for hash {candidate.content_hash[:16]}..."
                        )
                        continue

                    # Get post for content
                    post = (
                        db.query(Post)
                        .filter(Post.id == candidate.post_id)
                        .first()
                    )
                    if not post:
                        # Post was deleted, remove from queue
                        db.query(SummaryQueue).filter(
                            SummaryQueue.id == candidate.id
                        ).delete()
                        db.commit()
                        continue

                    # Skip already read posts (not worth spending API on them)
                    if post.is_read:
                        db.query(SummaryQueue).filter(
                            SummaryQueue.id == candidate.id
                        ).delete()
                        db.commit()
                        logger.debug(f"Post {post.id} already read, skipping summary")
                        continue

                    # Fetch full_content if not available
                    content = post.full_content
                    if not content and post.url:
                        try:
                            logger.info(
                                f"Fetching full content for post {post.id}..."
                            )
                            result = await extract_full_content(post.url)
                            if result.success and result.content:
                                content = result.content
                                post.full_content = content
                                db.commit()
                                logger.info(
                                    f"Full content saved for post {post.id}"
                                )
                            # Delay to avoid rate limit (429)
                            await asyncio.sleep(2)
                        except Exception as e:
                            logger.warning(
                                f"Failed to extract content from post {post.id}: {e}"
                            )

                    # Fallback to RSS content
                    if not content:
                        content = post.content

                    if not content:
                        # No content, remove from queue
                        db.query(SummaryQueue).filter(
                            SummaryQueue.id == candidate.id
                        ).delete()
                        db.commit()
                        continue

                    # Call API
                    try:
                        logger.info(f"Generating summary for post {post.id}...")
                        summary_result = await generate_summary(
                            content, title=post.title
                        )

                        # Save summary
                        ai_summary = AISummary(
                            content_hash=candidate.content_hash,
                            summary_pt=summary_result.summary_pt,
                            one_line_summary=summary_result.one_line_summary,
                            translated_title=summary_result.translated_title,
                        )
                        db.add(ai_summary)

                        # Remove from queue
                        db.query(SummaryQueue).filter(
                            SummaryQueue.id == candidate.id
                        ).delete()
                        db.commit()

                        logger.info(
                            f"Summary generated successfully for post {post.id}"
                        )

                    except TemporaryError as e:
                        # Temporary error - increment attempts
                        candidate.attempts = (candidate.attempts or 0) + 1
                        candidate.last_error = str(e)
                        candidate.error_type = "temporary"

                        if candidate.attempts >= 5:
                            # 24h cooldown
                            candidate.cooldown_until = now + timedelta(
                                hours=24
                            )
                            candidate.attempts = 0
                            logger.warning(
                                f"Post {post.id}: 5 errors, 24h cooldown"
                            )

                        candidate.locked_at = None
                        db.commit()
                        logger.warning(f"Temporary error post {post.id}: {e}")

                    except PermanentError as e:
                        # Permanent error
                        candidate.attempts = (candidate.attempts or 0) + 1
                        candidate.last_error = str(e)
                        candidate.error_type = "permanent"

                        if candidate.attempts >= 5:
                            # Move to failures
                            failure = SummaryFailure(
                                content_hash=candidate.content_hash,
                                last_error=str(e),
                            )
                            db.add(failure)
                            db.query(SummaryQueue).filter(
                                SummaryQueue.id == candidate.id
                            ).delete()
                            logger.error(
                                f"Post {post.id}: permanent failure after 5 attempts"
                            )
                        else:
                            candidate.locked_at = None

                        db.commit()
                        logger.error(f"Permanent error post {post.id}: {e}")

                except Exception as e:
                    db.rollback()
                    logger.error(f"Error in job process_summaries: {e}")
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in job process_summaries: {e}")

            await asyncio.sleep(interval)


# Global instance
scheduler = Scheduler()
