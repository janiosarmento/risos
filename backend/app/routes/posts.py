"""
Post routes.
Read, mark as read, content extraction and redirect.
"""

import logging
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Post, Feed, Category, AISummary, SummaryQueue
from app.schemas import (
    PostResponse,
    PostDetail,
    PostListResponse,
    MarkReadRequest,
)
from app.services.content_extractor import extract_full_content
from app.services.cerebras import generate_summary, CerebrasError
from app.services.content_hasher import compute_content_hash

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posts", tags=["posts"])


def get_post_or_404(db: Session, post_id: int) -> Post:
    """Fetch post by ID or raise 404."""
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Post not found"
        )
    return post


def is_safe_redirect_url(url: str) -> bool:
    """
    Validate URL is safe for redirect (prevents open redirect attacks).
    Only allows http/https schemes and blocks localhost/private IPs.
    """
    try:
        parsed = urlparse(url)

        # Must be http or https
        if parsed.scheme not in ("http", "https"):
            return False

        # Must have a hostname
        hostname = parsed.hostname or ""
        if not hostname:
            return False

        # Block localhost and private IPs
        if hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1"):
            return False

        # Block common private IP ranges
        if hostname.startswith(("10.", "192.168.", "172.16.", "172.17.", "172.18.")):
            return False

        return True

    except Exception:
        return False


def get_summary_status(db: Session, post: Post) -> str:
    """
    Return AI summary status for a post.
    """
    if not post.content_hash:
        return "not_configured"

    # Check if summary already exists
    summary = (
        db.query(AISummary)
        .filter(AISummary.content_hash == post.content_hash)
        .first()
    )
    if summary:
        return "ready"

    # Check if in queue
    queue_entry = (
        db.query(SummaryQueue).filter(SummaryQueue.post_id == post.id).first()
    )
    if queue_entry:
        if queue_entry.error_type == "permanent":
            return "failed"
        return "pending"

    return "not_configured"


@router.get("", response_model=PostListResponse)
def list_posts(
    feed_id: Optional[int] = Query(None, description="Filter by feed"),
    category_id: Optional[int] = Query(None, description="Filter by category"),
    unread_only: bool = Query(False, description="Only unread"),
    starred_only: bool = Query(False, description="Only starred"),
    limit: int = Query(20, ge=1, le=100, description="Post limit"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    List posts with pagination.
    Ordered by sort_date DESC (newest first).
    Also returns updated unread counts for relevant feeds.
    """
    query = db.query(Post)

    # Track which feeds to return unread counts for
    relevant_feed_ids = set()

    # Apply feed/category filter first
    if feed_id is not None:
        query = query.filter(Post.feed_id == feed_id)
        relevant_feed_ids.add(feed_id)
    elif category_id is not None:
        # Get feeds from the category
        category_feeds = (
            db.query(Feed.id)
            .filter(Feed.category_id == category_id)
            .all()
        )
        feed_ids_list = [f.id for f in category_feeds]
        relevant_feed_ids.update(feed_ids_list)
        feed_ids = (
            db.query(Feed.id)
            .filter(Feed.category_id == category_id)
            .subquery()
        )
        query = query.filter(Post.feed_id.in_(feed_ids))

    # Apply starred or unread filter (mutually exclusive)
    if starred_only:
        query = query.filter(Post.is_starred == True)
    elif unread_only:
        query = query.filter(Post.is_read == False)

    # Count total
    total = query.count()

    # Fetch sorted posts
    posts = (
        query.order_by(Post.sort_date.desc()).offset(offset).limit(limit).all()
    )

    # Fetch summaries for posts (by content_hash)
    content_hashes = [p.content_hash for p in posts if p.content_hash]
    summaries_map = {}
    if content_hashes:
        summaries = (
            db.query(AISummary)
            .filter(AISummary.content_hash.in_(content_hashes))
            .all()
        )
        summaries_map = {s.content_hash: s for s in summaries}

    # Get updated unread counts for relevant feeds
    feed_unread_counts = {}
    if relevant_feed_ids:
        unread_counts = (
            db.query(Post.feed_id, func.count(Post.id))
            .filter(Post.feed_id.in_(relevant_feed_ids), Post.is_read == False)
            .group_by(Post.feed_id)
            .all()
        )
        feed_unread_counts = {fid: count for fid, count in unread_counts}
        # Include feeds with 0 unread
        for fid in relevant_feed_ids:
            if fid not in feed_unread_counts:
                feed_unread_counts[fid] = 0

    # Get starred count for current context
    starred_query = db.query(func.count(Post.id)).filter(Post.is_starred == True)
    if feed_id is not None:
        starred_query = starred_query.filter(Post.feed_id == feed_id)
    elif category_id is not None:
        starred_query = starred_query.filter(Post.feed_id.in_(feed_ids_list))
    starred_count = starred_query.scalar()

    # Convert to response
    result = []
    for post in posts:
        summary = (
            summaries_map.get(post.content_hash) if post.content_hash else None
        )
        post_dict = {
            "id": post.id,
            "feed_id": post.feed_id,
            "guid": post.guid,
            "url": post.url,
            "title": post.title,
            "author": post.author,
            "content": post.content,
            "published_at": post.published_at,
            "fetched_at": post.fetched_at,
            "sort_date": post.sort_date,
            "is_read": post.is_read,
            "read_at": post.read_at,
            "is_starred": post.is_starred or False,
            "starred_at": post.starred_at,
            "summary_status": "ready"
            if summary
            else get_summary_status(db, post),
            "one_line_summary": summary.one_line_summary if summary else None,
            "translated_title": summary.translated_title if summary else None,
        }
        result.append(PostResponse(**post_dict))

    has_more = (offset + limit) < total

    return PostListResponse(
        posts=result,
        total=total,
        has_more=has_more,
        feed_unread_counts=feed_unread_counts if feed_unread_counts else None,
        starred_count=starred_count,
    )


@router.get("/{post_id}", response_model=PostDetail)
async def get_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Fetch a post by ID with full content.
    Includes AI summary if available.
    Extracts full_content on-demand if not cached.
    """
    post = get_post_or_404(db, post_id)

    # Extract full_content on-demand if not cached
    full_content = post.full_content
    if not full_content and post.url:
        try:
            result = await extract_full_content(post.url)
            if result.success:
                full_content = result.content
                post.full_content = full_content
                db.commit()
        except Exception:
            pass  # Use original content if extraction fails

    # Fetch or generate AI summary on-demand
    summary_pt = None
    one_line_summary = None
    translated_title = None
    summary_status = "not_configured"

    # Use full_content for summary, or content as fallback
    content_for_summary = full_content or post.content

    # Calculate/update content_hash if needed
    if content_for_summary and not post.content_hash:
        post.content_hash = compute_content_hash(
            content_for_summary, title=post.title, url=post.url
        )
        db.commit()

    if post.content_hash:
        # Check if summary already exists
        summary = (
            db.query(AISummary)
            .filter(AISummary.content_hash == post.content_hash)
            .first()
        )

        if summary:
            summary_pt = summary.summary_pt
            one_line_summary = summary.one_line_summary
            translated_title = summary.translated_title
            summary_status = "ready"
        elif content_for_summary and len(content_for_summary.strip()) > 100:
            # Generate on-demand summary if there's enough content
            try:
                logger.info(f"Generating on-demand summary for post {post.id}")
                result = await generate_summary(
                    content_for_summary, title=post.title
                )

                # Save to database
                new_summary = AISummary(
                    content_hash=post.content_hash,
                    summary_pt=result.summary_pt,
                    one_line_summary=result.one_line_summary,
                    translated_title=result.translated_title,
                )
                db.add(new_summary)
                db.commit()

                summary_pt = result.summary_pt
                one_line_summary = result.one_line_summary
                translated_title = result.translated_title
                summary_status = "ready"
                logger.info(
                    f"Summary generated successfully for post {post.id}"
                )

            except CerebrasError as e:
                logger.warning(
                    f"Failed to generate summary for post {post.id}: {e}"
                )
                summary_status = "pending"  # Temporary, can retry later
            except Exception as e:
                logger.error(
                    f"Unexpected error generating summary for post {post.id}: {e}"
                )
                summary_status = "failed"

    return PostDetail(
        id=post.id,
        feed_id=post.feed_id,
        guid=post.guid,
        url=post.url,
        title=post.title,
        author=post.author,
        content=post.content,
        full_content=full_content or post.content,
        published_at=post.published_at,
        fetched_at=post.fetched_at,
        sort_date=post.sort_date,
        is_read=post.is_read,
        read_at=post.read_at,
        is_starred=post.is_starred or False,
        starred_at=post.starred_at,
        summary_status=summary_status,
        summary_pt=summary_pt,
        one_line_summary=one_line_summary,
        translated_title=translated_title,
    )


@router.patch("/{post_id}/read")
def toggle_read(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Toggle read status of a post.
    If read, marks as unread. If unread, marks as read.
    """
    post = get_post_or_404(db, post_id)

    if post.is_read:
        post.is_read = False
        post.read_at = None
    else:
        post.is_read = True
        post.read_at = datetime.utcnow()

    db.commit()

    return {"id": post_id, "is_read": post.is_read, "read_at": post.read_at}


@router.patch("/{post_id}/star")
def toggle_star(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Toggle starred status of a post.
    If starred, removes star. If not, adds star.
    """
    post = get_post_or_404(db, post_id)

    if post.is_starred:
        post.is_starred = False
        post.starred_at = None
    else:
        post.is_starred = True
        post.starred_at = datetime.utcnow()

    db.commit()

    return {
        "id": post_id,
        "is_starred": bool(post.is_starred),
        "starred_at": post.starred_at,
    }


@router.post("/mark-read")
def mark_read_batch(
    request: MarkReadRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Mark multiple posts as read.
    - post_ids: list of specific post IDs
    - feed_id: marks all posts from a feed
    - category_id: marks all posts from feeds in a category
    - all: marks all posts
    """
    now = datetime.utcnow()
    query = db.query(Post).filter(Post.is_read == False)

    if request.post_ids:
        # Mark specific posts by ID
        query = query.filter(Post.id.in_(request.post_ids))
    elif request.all:
        # Mark all
        pass
    elif request.feed_id:
        query = query.filter(Post.feed_id == request.feed_id)
    elif request.category_id:
        feed_ids = (
            db.query(Feed.id)
            .filter(Feed.category_id == request.category_id)
            .subquery()
        )
        query = query.filter(Post.feed_id.in_(feed_ids))
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify post_ids, feed_id, category_id, or all=true",
        )

    count = query.update(
        {"is_read": True, "read_at": now}, synchronize_session=False
    )
    db.commit()

    return {"marked_read": count}


@router.get("/{post_id}/full-content")
async def get_full_content(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Extract full content from the original article.

    - Uses readability-lxml for extraction
    - Sanitizes HTML
    - Caches in posts.full_content
    """
    post = get_post_or_404(db, post_id)

    if not post.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Post has no URL"
        )

    # Check cache
    if post.full_content:
        return {
            "id": post_id,
            "full_content": post.full_content,
            "cached": True,
        }

    # Extract content
    result = await extract_full_content(post.url)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to extract content: {result.error}",
        )

    # Save to cache
    post.full_content = result.content
    db.commit()

    return {
        "id": post_id,
        "full_content": result.content,
        "cached": False,
    }


@router.get("/{post_id}/redirect")
def redirect_to_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Redirect to the original post URL.

    - Validates URL scheme (http/https only)
    - Marks post as read
    - Returns HTTP 302 to original URL
    """
    post = get_post_or_404(db, post_id)

    if not post.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Post has no URL"
        )

    # Validate URL to prevent open redirect attacks
    if not is_safe_redirect_url(post.url):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or unsafe URL",
        )

    # Mark as read
    if not post.is_read:
        post.is_read = True
        post.read_at = datetime.utcnow()
        db.commit()

    return RedirectResponse(url=post.url, status_code=status.HTTP_302_FOUND)


@router.post("/{post_id}/regenerate-summary")
async def regenerate_summary(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Regenerate the AI summary for a post.

    - Extracts full content if needed
    - Generates new summary via Cerebras
    - Updates or inserts into ai_summaries table
    - Returns the new summary
    """
    post = get_post_or_404(db, post_id)

    # Get content for summary
    content_for_summary = post.full_content or post.content

    # If no content, try to extract
    if not content_for_summary and post.url:
        try:
            result = await extract_full_content(post.url)
            if result.success:
                content_for_summary = result.content
                post.full_content = content_for_summary
                db.commit()
        except Exception as e:
            logger.error(f"Failed to extract content for post {post_id}: {e}")

    if not content_for_summary or len(content_for_summary.strip()) < 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post has insufficient content for summary",
        )

    # Calculate new content_hash based on current content
    new_content_hash = compute_content_hash(
        content_for_summary, title=post.title, url=post.url
    )

    # Update post content_hash if different
    if post.content_hash != new_content_hash:
        post.content_hash = new_content_hash
        db.commit()

    try:
        logger.info(f"Regenerating summary for post {post_id}")
        result = await generate_summary(content_for_summary, title=post.title)

        # Check if summary already exists with this hash
        existing_summary = (
            db.query(AISummary)
            .filter(AISummary.content_hash == new_content_hash)
            .first()
        )

        if existing_summary:
            # Update existing summary
            existing_summary.summary_pt = result.summary_pt
            existing_summary.one_line_summary = result.one_line_summary
            existing_summary.translated_title = result.translated_title
            existing_summary.created_at = datetime.utcnow()
        else:
            # Create new summary
            new_summary = AISummary(
                content_hash=new_content_hash,
                summary_pt=result.summary_pt,
                one_line_summary=result.one_line_summary,
                translated_title=result.translated_title,
            )
            db.add(new_summary)

        db.commit()
        logger.info(f"Summary regenerated successfully for post {post_id}")

        return {
            "success": True,
            "post_id": post_id,
            "summary_pt": result.summary_pt,
            "one_line_summary": result.one_line_summary,
            "translated_title": result.translated_title,
        }

    except CerebrasError as e:
        logger.error(
            f"Cerebras error regenerating summary for post {post_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error: {str(e)}",
        )
    except Exception as e:
        logger.error(
            f"Unexpected error regenerating summary for post {post_id}: {e}"
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate summary: {str(e)}",
        )
