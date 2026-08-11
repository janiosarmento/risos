"""
Scheduler for background jobs.
Uses database lock to ensure only one active instance.
"""

import asyncio
import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import or_, text

from app.config import settings
from app.database import SessionLocal
from app.models import SchedulerLock
from app.services.ai._constants import (
    AI_MAX_RPM,
    CLEANUP_HOUR,
    SUMMARY_LOCK_TIMEOUT_SECONDS,
)

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
            existing = db.query(SchedulerLock).filter(SchedulerLock.id == 1).first()

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
                    logger.info(f"Another instance is leader: {existing.locked_by}")
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
                logger.info("Lock acquired. This instance is the leader.")

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

        # Job: update_user_profile (every 6 hours, if stale)
        self._tasks.append(asyncio.create_task(self._job_update_user_profile()))

        # Job: process_suggestions (every hour)
        self._tasks.append(asyncio.create_task(self._job_process_suggestions()))

    async def _job_update_feeds(self):
        """Job to update feeds periodically."""
        from app.models import Feed
        from app.services.feed_ingestion import ingest_feed

        while self._running and self.is_leader:
            interval = 30 * 60  # default 30 minutes
            try:
                logger.info("Job update_feeds: starting...")

                db = SessionLocal()
                try:
                    from app.routes.preferences import (
                        get_effective_feed_update_interval,
                    )

                    interval = get_effective_feed_update_interval(db) * 60
                    now = datetime.utcnow()

                    # Find eligible feeds
                    feeds = (
                        db.query(Feed)
                        .filter(
                            (Feed.next_retry_at.is_(None))
                            | (Feed.next_retry_at <= now),
                        )
                        .order_by(
                            Feed.error_count.asc()
                        )  # Prioritize feeds without errors
                        .limit(20)
                        .all()
                    )

                    logger.info(f"Job update_feeds: {len(feeds)} feeds to update")

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
                            logger.error(f"Error updating feed {feed.id}: {e}")

                        # Small delay between feeds
                        await asyncio.sleep(1)

                finally:
                    db.close()

                logger.info("Job update_feeds: completed")

                # Backfill missing summaries after feed update
                await self._backfill_missing_summaries()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in job update_feeds: {e}")

            # Wait for next cycle
            await asyncio.sleep(interval)

    async def _backfill_missing_summaries(self, limit: int = 50):
        """
        Find posts that have content_hash but no AI summary and add them
        to the summary queue. This catches orphaned posts that were never
        queued or whose queue entries were lost.
        """
        from app.models import AISummary, Post, SummaryQueue

        db = SessionLocal()
        try:
            # Find orphaned posts:
            # - Has content_hash
            # - Not in summary_queue
            # - No entry in ai_summaries
            # - Not read (don't waste tokens on read posts), unless favorited
            orphaned_posts = (
                db.query(Post)
                .filter(
                    Post.content_hash.isnot(None),
                    or_(Post.is_read.is_(False), Post.is_starred.is_(True)),
                    ~Post.content_hash.in_(db.query(SummaryQueue.content_hash)),
                    ~Post.content_hash.in_(db.query(AISummary.content_hash)),
                )
                .order_by(Post.published_at.desc())  # Newer posts first
                .limit(limit)
                .all()
            )

            if not orphaned_posts:
                return

            logger.info(f"Backfill: found {len(orphaned_posts)} orphaned posts")

            added = 0
            for post in orphaned_posts:
                # Double-check not already in queue (race condition)
                exists = (
                    db.query(SummaryQueue)
                    .filter(SummaryQueue.content_hash == post.content_hash)
                    .first()
                )
                if exists:
                    continue

                queue_entry = SummaryQueue(
                    post_id=post.id,
                    content_hash=post.content_hash,
                    priority=-1,  # Low priority (below normal 0)
                )
                db.add(queue_entry)
                added += 1

            if added > 0:
                db.commit()
                logger.info(f"Backfill: added {added} posts to summary queue")

        except Exception as e:
            logger.error(f"Error in backfill_missing_summaries: {e}")
            db.rollback()
        finally:
            db.close()

    async def _job_cleanup_retention(self):
        """Job to clean up old posts."""
        from app.models import CleanupLog, Post

        while self._running and self.is_leader:
            try:
                now = datetime.utcnow()

                # Check if it's time to run (03:00)
                target_hour = CLEANUP_HOUR
                if now.hour != target_hour:
                    # Calculate time until next execution
                    next_run = now.replace(
                        hour=target_hour, minute=0, second=0, microsecond=0
                    )
                    if now.hour >= target_hour:
                        next_run += timedelta(days=1)
                    wait_seconds = (next_run - now).total_seconds()
                    await asyncio.sleep(min(wait_seconds, 3600))  # Max 1h wait
                    continue

                logger.info("Job cleanup_retention: starting...")

                db = SessionLocal()
                start_time = datetime.utcnow()

                try:
                    from app.routes.preferences import (
                        get_effective_max_post_age_days,
                        get_effective_max_unread_days,
                    )

                    posts_removed = 0
                    full_content_cleared = 0
                    unread_removed = 0

                    # 1. Remove posts read more than MAX_POST_AGE_DAYS ago
                    # (except favorites which are never removed)
                    cutoff_read = now - timedelta(
                        days=get_effective_max_post_age_days(db)
                    )
                    result = (
                        db.query(Post)
                        .filter(
                            Post.is_read.is_(True),
                            Post.read_at < cutoff_read,
                            (Post.is_starred.is_(False)) | (Post.is_starred.is_(None)),
                            Post.keep_unread.is_(False),
                        )
                        .delete(synchronize_session=False)
                    )
                    posts_removed += result

                    # 2. Remove unread posts older than MAX_UNREAD_DAYS
                    # (except favorites and keep_unread which are never removed)
                    cutoff_unread = now - timedelta(
                        days=get_effective_max_unread_days(db)
                    )
                    result = (
                        db.query(Post)
                        .filter(
                            Post.is_read.is_(False),
                            Post.fetched_at < cutoff_unread,
                            (Post.is_starred.is_(False)) | (Post.is_starred.is_(None)),
                            Post.keep_unread.is_(False),
                        )
                        .delete(synchronize_session=False)
                    )
                    unread_removed += result

                    # 3. Clear full_content from posts read more than 30 days ago
                    # (except favorites and keep_unread which keep content)
                    cutoff_full = now - timedelta(days=30)
                    result = (
                        db.query(Post)
                        .filter(
                            Post.is_read.is_(True),
                            Post.read_at < cutoff_full,
                            Post.full_content.isnot(None),
                            (Post.is_starred.is_(False)) | (Post.is_starred.is_(None)),
                            Post.keep_unread.is_(False),
                        )
                        .update({"full_content": None}, synchronize_session=False)
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

                except Exception:
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
        import os

        from app.models import AppSettings

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
                    free_mb = (statvfs.f_frsize * statvfs.f_bavail) / (1024 * 1024)
                    if free_mb < 100:
                        warnings.append(f"Low disk space: {free_mb:.0f}MB")

                    # 3. Check database size
                    db_path = settings.database_path
                    if os.path.exists(db_path):
                        db_size_mb = os.path.getsize(db_path) / (1024 * 1024)
                        if db_size_mb > settings.max_db_size_mb:
                            warnings.append(f"Database too large: {db_size_mb:.0f}MB")

                    # Update app_settings
                    if warnings:
                        warning_text = "; ".join(warnings)
                        logger.warning(f"Health check warnings: {warning_text}")
                        existing = (
                            db.query(AppSettings)
                            .filter(AppSettings.key == "health_warning")
                            .first()
                        )
                        if existing:
                            existing.value = warning_text
                        else:
                            db.add(
                                AppSettings(key="health_warning", value=warning_text)
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

    def _claim_queue_item(self, db):
        """Claim the highest-priority eligible item from the summary queue.

        Returns (candidate, now) on success, or (None, None) when the
        queue is empty or another worker beat us to the lock.
        """
        from app.models import Feed, Post, SummaryQueue

        now = datetime.utcnow()
        lock_timeout = now - timedelta(seconds=SUMMARY_LOCK_TIMEOUT_SECONDS)

        candidate = (
            db.query(SummaryQueue)
            .join(Post, SummaryQueue.post_id == Post.id)
            .join(Feed, Post.feed_id == Feed.id)
            .filter(
                (SummaryQueue.locked_at.is_(None))
                | (SummaryQueue.locked_at < lock_timeout),
                (SummaryQueue.cooldown_until.is_(None))
                | (SummaryQueue.cooldown_until < now),
            )
            .order_by(
                SummaryQueue.priority.desc(),
                Post.published_at.desc(),  # Newer posts ALWAYS first
                Feed.weight.desc(),  # Tie-breaker only (same publish time)
            )
            .first()
        )
        if not candidate:
            return None, now

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
            db.rollback()
            return None, now

        db.commit()
        return candidate, now

    def _validate_and_prepare_post(self, db, candidate):
        """Check that the post behind *candidate* is still valid and has content.

        Returns (post, content, title_only) when ready to generate, or
        (None, None, None) when the item should be skipped (the caller
        continues the main loop).
        """
        from app.models import AISummary, Post, SummaryQueue

        # Already summarized?
        existing = (
            db.query(AISummary)
            .filter(AISummary.content_hash == candidate.content_hash)
            .first()
        )
        if existing:
            db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
            db.commit()
            return None, None, None

        post = db.query(Post).filter(Post.id == candidate.post_id).first()
        if not post or post.skip_summary:
            db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
            db.commit()
            return None, None, None

        if post.is_read and not post.is_starred:
            db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
            db.commit()
            return None, None, None

        content = post.full_content or post.content
        title_only = False

        if not content:
            if post.title:
                content = post.title
                title_only = True
            else:
                post.skip_summary = True
                db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
                db.commit()
                return None, None, None

        return post, content, title_only

    def _handle_summary_error(self, db, post, candidate, error):
        """Update queue state after a failed generation attempt."""
        from app.models import SummaryQueue
        from app.services.ai import (
            GarbageContentError,
            TemporaryError,
        )

        now = datetime.utcnow()

        if isinstance(error, GarbageContentError):
            post.skip_summary = True
            db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
            db.commit()
            logger.info("Post %s: %s, marked skip_summary", post.id, error)
            return

        candidate.attempts = (candidate.attempts or 0) + 1
        candidate.last_error = str(error)
        candidate.locked_at = None

        if isinstance(error, TemporaryError):
            err_msg = str(error)
            # "All API keys are in cooldown" is not the item's fault — retry
            if "API keys" in err_msg and "cooldown" in err_msg:
                candidate.locked_at = None
                candidate.last_error = err_msg
                candidate.attempts = (candidate.attempts or 1) - 1  # don't count
                db.commit()
                return

            candidate.error_type = "temporary"
            if candidate.attempts >= 5:
                candidate.cooldown_until = now + timedelta(hours=24)
                candidate.attempts = 0
                logger.warning("Post %s: 5 errors, 24h cooldown", post.id)
        else:
            candidate.error_type = "permanent"
            if candidate.attempts >= 5:
                db.query(SummaryQueue).filter(SummaryQueue.id == candidate.id).delete()
                logger.error(
                    "Post %s: removed from queue after 5 attempts (not marked skip)",
                    post.id,
                )

        db.commit()
        logger.warning(
            "%s error post %s: %s", type(error).__name__, post.id, error
        )

    async def _job_process_summaries(self):
        """Job to process AI summary queue."""
        from app.models import AISummary, SummaryQueue
        from app.services.ai import (
            GarbageContentError,
            PermanentError,
            TemporaryError,
            api_key_rotator,
            circuit_breaker,
            generate_summary,
        )
        from app.services.content_extractor import ensure_full_content
        from app.services.tags import save_post_tags

        interval = max(5, 60 // AI_MAX_RPM + 1)

        while self._running and self.is_leader:
            try:
                if not circuit_breaker.can_call()[0]:
                    await asyncio.sleep(interval)
                    continue

                if not api_key_rotator.has_available_key():
                    await asyncio.sleep(30)
                    continue

                db = SessionLocal()
                try:
                    candidate, now = self._claim_queue_item(db)
                    if not candidate:
                        await asyncio.sleep(interval)
                        continue

                    post, content, title_only = self._validate_and_prepare_post(db, candidate)
                    if not post:
                        continue

                    # Fetch full_content if not already cached
                    if not post.full_content and post.url:
                        await ensure_full_content(db, post)
                        content = post.full_content or content
                        await asyncio.sleep(2)

                    try:
                        logger.info("Generating summary for post %s...", post.id)
                        summary_result = await generate_summary(
                            content, title=post.title, title_only=title_only,
                            engine="background",
                        )
                        summary_text = summary_result.get_summary_with_signature()

                        db.add(AISummary(
                            content_hash=candidate.content_hash,
                            summary_pt=summary_text,
                            one_line_summary=summary_result.one_line_summary,
                            translated_title=summary_result.translated_title,
                        ))
                        if summary_result.tags:
                            save_post_tags(db, post.id, summary_result.tags)
                        db.query(SummaryQueue).filter(
                            SummaryQueue.id == candidate.id
                        ).delete()
                        db.commit()
                        logger.info("Summary generated for post %s", post.id)

                        from app.services.ai._constants import SUMMARY_QUEUE_SLEEP_SECONDS
                        await asyncio.sleep(SUMMARY_QUEUE_SLEEP_SECONDS)

                    except (GarbageContentError, TemporaryError, PermanentError) as e:
                        self._handle_summary_error(db, post, candidate, e)

                except Exception as e:
                    db.rollback()
                    logger.error("Error in job process_summaries: %s", e)
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in job process_summaries: %s", e)

            await asyncio.sleep(interval)

    async def _job_update_user_profile(self):
        """Job to update user interest profile for recommendations."""
        from app.services.user_profile import (
            MIN_LIKED_POSTS,
            generate_user_profile,
            get_liked_posts_count,
            is_profile_stale,
        )

        # Check every 6 hours
        interval = 6 * 60 * 60  # 6 hours in seconds

        while self._running and self.is_leader:
            try:
                db = SessionLocal()
                try:
                    # Check if profile needs update
                    if is_profile_stale(db):
                        liked_count = get_liked_posts_count(db)
                        if liked_count >= MIN_LIKED_POSTS:
                            logger.info(
                                f"Job update_user_profile: regenerating profile "
                                f"({liked_count} liked posts)"
                            )
                            generate_user_profile(db)
                        else:
                            logger.debug(
                                f"Job update_user_profile: not enough likes "
                                f"({liked_count}/{MIN_LIKED_POSTS})"
                            )
                    else:
                        logger.debug("Job update_user_profile: profile is fresh")
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in job update_user_profile: {e}")

            await asyncio.sleep(interval)

    async def _job_process_suggestions(self):
        """Job to process suggestion candidates using AI comparison."""
        from app.services.suggestions import process_suggestion_candidates
        from app.services.user_profile import get_user_profile

        # Check every hour
        interval = 60 * 60  # 1 hour in seconds

        while self._running and self.is_leader:
            try:
                db = SessionLocal()
                try:
                    # Only process if we have a user profile
                    profile = get_user_profile(db)
                    if profile and profile.get("profile"):
                        logger.info("Job process_suggestions: starting...")
                        suggested_count = process_suggestion_candidates(db)
                        logger.info(
                            f"Job process_suggestions: completed "
                            f"({suggested_count} new suggestions)"
                        )
                    else:
                        logger.debug(
                            "Job process_suggestions: no user profile yet, skipping"
                        )
                finally:
                    db.close()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in job process_suggestions: {e}")

            await asyncio.sleep(interval)


# Global instance
scheduler = Scheduler()
