"""
Post routes.
Read, mark as read, content extraction and redirect.
"""

import hashlib
import io
import logging
import re
import unicodedata
import zipfile
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import Session, joinedload, subqueryload
from starlette.responses import Response

from app.database import get_db
from app.dependencies import get_current_user
from app.models import (
    AISummary,
    Category,
    Feed,
    Post,
    PostTag,
    SummaryQueue,
    TopicTag,
)
from app.routes.preferences import get_effective_blocked_terms
from app.schemas import (
    MarkReadRequest,
    PostDetail,
    PostListResponse,
    PostResponse,
)
from app.services.ai import (
    CerebrasError,
    generate_summary,
)
from app.services.ai._parsing import split_into_paragraphs
from app.services.content_extractor import extract_full_content
from app.services.content_hasher import compute_content_hash
from app.services.tags import save_post_tags

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posts", tags=["posts"])


def _word_boundary(escaped: str, side: str) -> str:
    """Return appropriate boundary anchor for start/end of an escaped pattern.

    \b only works between \\w and \\W chars.  If the pattern edge is a
    non-word char (like '[' or '$'), we only need a boundary on the
    word-char side to prevent partial word matches.  The non-word char
    itself already breaks any word, so no boundary needed on that side.
    """
    if side == "start":
        ch = re.sub(r"\\(.)", r"\1", escaped[:1])  # un-escape first char
        if re.match(r"\w", ch):
            return r"\b"
        return r"(?<!\w)"
    else:
        ch = re.sub(r"\\(.)", r"\1", escaped[-1:])  # un-escape last char
        if re.match(r"\w", ch):
            return r"\b"
        return ""  # non-word char at end — no boundary needed


def title_matches_term(title_lower: str, term: str) -> bool:
    """
    Check if a title matches a blocked term.

    Without *: whole-word match ("ford" won't match "affordable").
    With *: substring match per segment, joined by .*?
    Handles terms with non-word chars like [review].
    """
    if "*" not in term:
        escaped = re.escape(term)
        lb = _word_boundary(escaped, "start")
        rb = _word_boundary(escaped, "end")
        pattern = lb + escaped + rb
        return bool(re.search(pattern, title_lower))
    parts = [re.escape(seg) for seg in term.split("*") if seg]
    if not parts:
        return False
    # Add word boundaries to first/last segments
    pattern = ".*?".join(parts)
    if not term.startswith("*"):
        pattern = _word_boundary(parts[0], "start") + pattern
    if not term.endswith("*"):
        pattern = pattern + _word_boundary(parts[-1], "end")
    return bool(re.search(pattern, title_lower))


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
        db.query(AISummary).filter(AISummary.content_hash == post.content_hash).first()
    )
    if summary:
        return "ready"

    # Check if in queue
    queue_entry = db.query(SummaryQueue).filter(SummaryQueue.post_id == post.id).first()
    if queue_entry:
        if queue_entry.error_type == "permanent":
            return "failed"
        return "pending"

    return "not_configured"


@router.get("", response_model=PostListResponse)
def list_posts(
    feed_id: Optional[int] = Query(None, description="Filter by feed"),
    category_id: Optional[int] = Query(None, description="Filter by category"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    topic_id: Optional[int] = Query(
        None, description="Filter by topic (OR across topic tags)"
    ),
    unread_only: bool = Query(False, description="Only unread"),
    starred_only: bool = Query(False, description="Only starred"),
    suggested_only: bool = Query(False, description="Only AI-suggested"),
    search: Optional[str] = Query(None, description="Search titles and summaries"),
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
    query = db.query(Post).options(subqueryload(Post.tags))

    # Track which feeds to return unread counts for
    relevant_feed_ids = set()

    # Apply topic or tag filter (mutually exclusive; topic_id takes precedence)
    if topic_id is not None:
        topic_tags = [
            row.tag
            for row in db.query(TopicTag.tag)
            .filter(TopicTag.topic_id == topic_id)
            .all()
        ]
        if topic_tags:
            query = query.join(PostTag).filter(PostTag.tag.in_(topic_tags)).distinct()
        else:
            # Empty topic — no posts match
            query = query.filter(Post.id == -1)
    elif tag:
        query = query.join(PostTag).filter(PostTag.tag == tag.strip().lower())

    # Apply feed/category filter first
    if feed_id is not None:
        query = query.filter(Post.feed_id == feed_id)
        relevant_feed_ids.add(feed_id)
    elif category_id is not None:
        # Get feeds from the category
        category_feeds = db.query(Feed.id).filter(Feed.category_id == category_id).all()
        feed_ids_list = [f.id for f in category_feeds]
        relevant_feed_ids.update(feed_ids_list)
        feed_ids = db.query(Feed.id).filter(Feed.category_id == category_id).subquery()
        query = query.filter(Post.feed_id.in_(feed_ids))

    # Apply filters (can be combined)
    if starred_only:
        query = query.filter(Post.is_starred.is_(True))
    if suggested_only:
        query = query.filter(Post.is_suggested.is_(True))
    if unread_only:
        query = query.filter(Post.is_read.is_(False))

    # Apply search filter (title + AI summary fields)
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        query = query.outerjoin(
            AISummary, Post.content_hash == AISummary.content_hash
        ).filter(
            or_(
                func.lower(Post.title).like(term),
                func.lower(Post.content).like(term),
                func.lower(AISummary.translated_title).like(term),
                func.lower(AISummary.one_line_summary).like(term),
                func.lower(AISummary.summary_pt).like(term),
            )
        )

    # Count total
    total = query.count()

    # Fetch sorted posts
    posts = query.order_by(Post.sort_date.desc()).offset(offset).limit(limit).all()

    # Fetch summaries for posts (by content_hash)
    content_hashes = [p.content_hash for p in posts if p.content_hash]
    summaries_map = {}
    if content_hashes:
        summaries = (
            db.query(AISummary).filter(AISummary.content_hash.in_(content_hashes)).all()
        )
        summaries_map = {s.content_hash: s for s in summaries}

    # Get updated unread counts for relevant feeds
    feed_unread_counts = {}
    if relevant_feed_ids:
        unread_counts = (
            db.query(Post.feed_id, func.count(Post.id))
            .filter(Post.feed_id.in_(relevant_feed_ids), Post.is_read.is_(False))
            .group_by(Post.feed_id)
            .all()
        )
        feed_unread_counts = {fid: count for fid, count in unread_counts}
        # Include feeds with 0 unread
        for fid in relevant_feed_ids:
            if fid not in feed_unread_counts:
                feed_unread_counts[fid] = 0

    # Get starred count for current context
    starred_query = db.query(func.count(func.distinct(Post.id))).filter(
        Post.is_starred.is_(True)
    )
    if topic_id is not None and topic_tags:
        starred_query = starred_query.join(PostTag).filter(PostTag.tag.in_(topic_tags))
    elif tag:
        starred_query = starred_query.join(PostTag).filter(
            PostTag.tag == tag.strip().lower()
        )
    if feed_id is not None:
        starred_query = starred_query.filter(Post.feed_id == feed_id)
    elif category_id is not None:
        starred_query = starred_query.filter(Post.feed_id.in_(feed_ids_list))
    if search and search.strip():
        term = f"%{search.strip().lower()}%"
        starred_query = starred_query.outerjoin(
            AISummary, Post.content_hash == AISummary.content_hash
        ).filter(
            or_(
                func.lower(Post.title).like(term),
                func.lower(Post.content).like(term),
                func.lower(AISummary.translated_title).like(term),
                func.lower(AISummary.one_line_summary).like(term),
                func.lower(AISummary.summary_pt).like(term),
            )
        )
    starred_count = starred_query.scalar()

    # Get suggested unread count (global - not filtered by feed/category)
    suggested_count = (
        db.query(func.count(Post.id))
        .filter(Post.is_suggested.is_(True), Post.is_read.is_(False))
        .scalar()
    )

    # Load blocked terms for is_blocked computation
    blocked_terms = get_effective_blocked_terms(db)

    # Convert to response
    result = []
    for post in posts:
        summary = summaries_map.get(post.content_hash) if post.content_hash else None
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
            "is_liked": bool(post.is_liked),
            "liked_at": post.liked_at,
            "is_suggested": bool(post.is_suggested),
            "suggestion_score": post.suggestion_score,
            "summary_status": ("ready" if summary else get_summary_status(db, post)),
            "one_line_summary": summary.one_line_summary if summary else None,
            "translated_title": summary.translated_title if summary else None,
            "skip_summary": bool(post.skip_summary),
            "keep_unread": bool(post.keep_unread),
            "is_blocked": any(
                title_matches_term((post.title or "").lower(), term)
                for term in blocked_terms
            ),
            "tags": [pt.tag for pt in post.tags],
        }
        result.append(PostResponse(**post_dict))

    has_more = (offset + limit) < total

    return PostListResponse(
        posts=result,
        total=total,
        has_more=has_more,
        feed_unread_counts=feed_unread_counts if feed_unread_counts else None,
        starred_count=starred_count,
        suggested_count=suggested_count,
    )


def _slugify(text: str) -> str:
    """Convert text to a safe filename slug."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[-\s]+", "-", text)
    return text[:80]


def _post_to_markdown(post: Post, summary: Optional[AISummary]) -> str:
    """Convert a post to a markdown string."""
    lines = [f"# {post.title or 'Untitled'}", ""]

    translated = summary.translated_title if summary else None
    if translated and translated != post.title:
        lines.append(f"**Translated title:** {translated}")

    feed_title = post.feed.title if post.feed else "Unknown"
    lines.append(f"**Feed:** {feed_title}")

    date = post.published_at or post.fetched_at
    if date:
        lines.append(f"**Date:** {date.strftime('%Y-%m-%d %H:%M')}")

    if post.url:
        lines.append(f"**URL:** {post.url}")

    lines.append("")

    one_line = summary.one_line_summary if summary else None
    full_summary = summary.summary_pt if summary else None
    if one_line:
        lines.extend(["## Summary", "", one_line, ""])
    if full_summary:
        lines.extend(["## Full Summary", "", full_summary, ""])
    elif post.content:
        lines.extend(["## Content", "", post.content, ""])

    tags = [pt.tag for pt in post.tags]
    if tags:
        lines.extend(["## Tags", "", ", ".join(tags), ""])

    return "\n".join(lines)


@router.get("/export-starred")
def export_starred(
    feed_id: Optional[int] = Query(None, description="Filter by feed"),
    category_id: Optional[int] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Export starred posts as a ZIP of markdown files."""
    query = (
        db.query(Post)
        .filter(Post.is_starred.is_(True))
        .options(joinedload(Post.feed), subqueryload(Post.tags))
    )

    zip_label = "all"

    if feed_id is not None:
        query = query.filter(Post.feed_id == feed_id)
        feed = db.query(Feed).filter(Feed.id == feed_id).first()
        if feed:
            zip_label = _slugify(feed.title)
    elif category_id is not None:
        feed_ids = db.query(Feed.id).filter(Feed.category_id == category_id).subquery()
        query = query.filter(Post.feed_id.in_(feed_ids))
        category = db.query(Category).filter(Category.id == category_id).first()
        if category:
            zip_label = _slugify(category.name)

    posts = query.order_by(Post.starred_at.desc()).all()

    if not posts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No starred posts found",
        )

    # Fetch summaries for all posts
    content_hashes = [p.content_hash for p in posts if p.content_hash]
    summaries_map = {}
    if content_hashes:
        summaries = (
            db.query(AISummary).filter(AISummary.content_hash.in_(content_hashes)).all()
        )
        summaries_map = {s.content_hash: s for s in summaries}

    # Determine if we need subfolders
    use_subfolders = feed_id is None

    # Build ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for post in posts:
            summary = (
                summaries_map.get(post.content_hash) if post.content_hash else None
            )
            md_content = _post_to_markdown(post, summary)

            # Build filename
            slug = _slugify(post.title or "untitled")
            short_hash = hashlib.md5(str(post.id).encode()).hexdigest()[:6]
            filename = f"{slug}-{short_hash}.md"

            if use_subfolders:
                folder = _slugify(post.feed.title) if post.feed else "unknown"
                filepath = f"{folder}/{filename}"
            else:
                filepath = filename

            zf.writestr(filepath, md_content)

    zip_bytes = buf.getvalue()
    today = datetime.utcnow().strftime("%Y%m%d")
    zip_filename = f"starred-{zip_label}-{today}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )



@router.get("/export-mimir")
def export_mimir(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Export starred post URLs as plain text for Mímir, one per line, oldest first."""
    posts = (
        db.query(Post)
        .filter(Post.is_starred.is_(True), Post.url.isnot(None))
        .order_by(Post.starred_at.asc())
        .all()
    )

    if not posts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No starred posts found",
        )

    lines = [post.url for post in posts]
    content = "\n".join(lines) + "\n"

    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": 'attachment; filename="mimir.txt"'},
    )


@router.post("/unstar-all")
def unstar_all(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Unstar all starred posts at once."""
    count = (
        db.query(Post)
        .filter(Post.is_starred.is_(True))
        .update(
            {"is_starred": False, "starred_at": None},
            synchronize_session="fetch",
        )
    )
    db.commit()
    return {"success": True, "count": count}


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
        except Exception as e:
            logger.debug("Content extraction skipped for post %d: %s", post_id, e)

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
            summary_pt = split_into_paragraphs(summary.summary_pt)
            one_line_summary = summary.one_line_summary
            translated_title = summary.translated_title
            summary_status = "ready"
        elif not post.skip_summary:
            # No summary yet. Check if already in background queue.
            # Never auto-enqueue on open — only explicit user action triggers generation.
            existing_queue = (
                db.query(SummaryQueue).filter(SummaryQueue.post_id == post.id).first()
            )
            summary_status = "queued" if existing_queue else "pending"

    # Compute matched and ignored tags
    post_tags = [pt.tag for pt in post.tags]
    matched_tags = []
    ignored_tags = []
    if post_tags:
        from app.models import IgnoredTag
        from app.services.user_profile import get_user_profile

        profile = get_user_profile(db)
        if profile and profile.get("tags"):
            profile_tags = {t.lower() for t in profile["tags"]}
            matched_tags = [t for t in post_tags if t.lower() in profile_tags]

        ignored_set = {row.tag for row in db.query(IgnoredTag.tag).all()}
        ignored_tags = [t for t in post_tags if t.lower() in ignored_set]

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
        is_liked=bool(post.is_liked),
        liked_at=post.liked_at,
        is_suggested=bool(post.is_suggested),
        suggestion_score=post.suggestion_score,
        summary_status=summary_status,
        summary_pt=summary_pt,
        one_line_summary=one_line_summary,
        translated_title=translated_title,
        tags=post_tags,
        matched_tags=matched_tags,
        ignored_tags=ignored_tags,
        skip_summary=bool(post.skip_summary),
        keep_unread=bool(post.keep_unread),
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

    # Protected posts cannot be marked as read
    if post.keep_unread and not post.is_read:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Post is protected by keep_unread",
        )

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
    Auto-likes the post when starring (but unstarring does NOT remove like).
    """
    from app.services.user_profile import invalidate_user_profile

    post = get_post_or_404(db, post_id)
    auto_liked = False

    if post.is_starred:
        post.is_starred = False
        post.starred_at = None
    else:
        post.is_starred = True
        post.starred_at = datetime.utcnow()
        # Auto-like when starring (for recommendations)
        if not post.is_liked:
            post.is_liked = 1
            post.liked_at = datetime.utcnow().isoformat()
            auto_liked = True

    db.commit()

    # Invalidate profile if auto-like happened
    if auto_liked:
        invalidate_user_profile(db)

    return {
        "id": post_id,
        "is_starred": bool(post.is_starred),
        "starred_at": post.starred_at,
        "is_liked": bool(post.is_liked),
    }


@router.patch("/{post_id}/like")
def toggle_like(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Toggle liked status of a post.
    Used to train the recommendation system.
    """
    from app.services.user_profile import invalidate_user_profile

    post = get_post_or_404(db, post_id)

    if post.is_liked:
        post.is_liked = 0
        post.liked_at = None
    else:
        post.is_liked = 1
        post.liked_at = datetime.utcnow().isoformat()

    db.commit()

    # Mark user profile as stale for regeneration
    invalidate_user_profile(db)

    return {
        "id": post_id,
        "is_liked": bool(post.is_liked),
        "liked_at": post.liked_at,
    }


@router.patch("/{post_id}/keep-unread")
def toggle_keep_unread(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Toggle keep_unread protection. Enabling forces post to unread."""
    post = get_post_or_404(db, post_id)

    if post.keep_unread:
        post.keep_unread = False
    else:
        post.keep_unread = True
        # Invariant: keep_unread=True + is_read=True is invalid
        if post.is_read:
            post.is_read = False
            post.read_at = None

    db.commit()

    return {
        "id": post_id,
        "keep_unread": post.keep_unread,
        "is_read": post.is_read,
        "read_at": post.read_at,
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
    query = db.query(Post).filter(
        Post.is_read.is_(False),
        Post.keep_unread.is_(False),
    )

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
            db.query(Feed.id).filter(Feed.category_id == request.category_id).subquery()
        )
        query = query.filter(Post.feed_id.in_(feed_ids))
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify post_ids, feed_id, category_id, or all=true",
        )

    count = query.update({"is_read": True, "read_at": now}, synchronize_session=False)
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

    # Mark as read (skip if protected)
    if not post.is_read and not post.keep_unread:
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
    logger.info("[REGEN] Request received for post %d", post_id)

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
        result = await generate_summary(content_for_summary, title=post.title, engine="ondemand")

        # Check if summary already exists with this hash
        existing_summary = (
            db.query(AISummary)
            .filter(AISummary.content_hash == new_content_hash)
            .first()
        )

        # Append model attribution to summary
        summary_text = result.get_summary_with_signature()

        if existing_summary:
            # Update existing summary
            existing_summary.summary_pt = summary_text
            existing_summary.one_line_summary = result.one_line_summary
            existing_summary.translated_title = result.translated_title
            existing_summary.created_at = datetime.utcnow()
        else:
            # Create new summary
            new_summary = AISummary(
                content_hash=new_content_hash,
                summary_pt=summary_text,
                one_line_summary=result.one_line_summary,
                translated_title=result.translated_title,
            )
            db.add(new_summary)

        # Save/update tags for recommendations
        if result.tags:
            save_post_tags(db, post_id, result.tags)

        db.commit()
        logger.info(f"Summary regenerated successfully for post {post_id}")

        return {
            "success": True,
            "post_id": post_id,
            "summary_pt": split_into_paragraphs(summary_text),
            "one_line_summary": result.one_line_summary,
            "translated_title": result.translated_title,
            "tags": result.tags or [],
        }

    except CerebrasError as e:
        logger.error("[REGEN] CerebrasError: %s", e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error: {str(e)}",
        )
    except Exception as e:
        logger.exception("[REGEN] Exception: %s: %s", type(e).__name__, e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate summary: {str(e)}",
        )


@router.post("/{post_id}/skip-summary")
def toggle_skip_summary(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Toggle the skip_summary flag on a post."""
    post = get_post_or_404(db, post_id)
    post.skip_summary = not post.skip_summary
    db.commit()

    # Remove from summary queue if skipping
    if post.skip_summary:
        db.query(SummaryQueue).filter(SummaryQueue.post_id == post_id).delete()
        db.commit()

    return {"post_id": post_id, "skip_summary": post.skip_summary}


class BatchUnstarRequest(BaseModel):
    post_ids: List[int]


class CurateRequest(BaseModel):
    topic_id: Optional[int] = None
    feed_id: Optional[int] = None
    category_id: Optional[int] = None
    tag: Optional[str] = None


class ExportSelectionRequest(BaseModel):
    post_ids: List[int]


@router.post("/curate")
async def curate_starred(
    body: CurateRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Analyze starred posts with AI to identify essential vs redundant."""
    from app.routes.preferences import get_effective_summary_language
    from app.services.ai._api import call_llm_json

    language = get_effective_summary_language(db)

    query = (
        db.query(Post)
        .filter(Post.is_starred.is_(True))
        .options(subqueryload(Post.tags), joinedload(Post.feed))
    )

    context_name = "All Starred"

    # Apply topic or tag filter (mutually exclusive, topic takes precedence)
    if body.topic_id is not None:
        topic_tags = [
            row.tag
            for row in db.query(TopicTag.tag)
            .filter(TopicTag.topic_id == body.topic_id)
            .all()
        ]
        if topic_tags:
            query = query.join(PostTag).filter(PostTag.tag.in_(topic_tags)).distinct()
            from app.models import Topic as TopicModel

            topic = db.query(TopicModel).filter(TopicModel.id == body.topic_id).first()
            if topic:
                context_name = topic.name
    elif body.tag:
        query = query.join(PostTag).filter(PostTag.tag == body.tag.strip().lower())
        context_name = f"tag: {body.tag}"

    # Apply feed/category filter
    if body.feed_id is not None:
        query = query.filter(Post.feed_id == body.feed_id)
        feed = db.query(Feed).filter(Feed.id == body.feed_id).first()
        if feed:
            context_name = feed.title or context_name
    elif body.category_id is not None:
        cat_feed_ids = [
            f.id
            for f in db.query(Feed.id)
            .filter(Feed.category_id == body.category_id)
            .all()
        ]
        if cat_feed_ids:
            query = query.filter(Post.feed_id.in_(cat_feed_ids))

    CURATION_MAX_POSTS = (
        100  # Hard limit — beyond this, prompt exceeds model context window
    )

    posts = query.order_by(Post.starred_at.desc()).all()

    if not posts:
        return {
            "topic": context_name,
            "total_posts": 0,
            "analysis": {
                "essential": [],
                "redundant": [],
                "keep_if_interested": [],
            },
            "summary": "No starred posts found.",
        }

    if len(posts) > CURATION_MAX_POSTS:
        raise HTTPException(
            status_code=400,
            detail=f"Too many posts for curation ({len(posts)}). Maximum is {CURATION_MAX_POSTS}. Filter by feed or topic to narrow down.",
        )

    # Fetch summaries
    content_hashes = [p.content_hash for p in posts if p.content_hash]
    summaries_map = {}
    if content_hashes:
        summaries = (
            db.query(AISummary).filter(AISummary.content_hash.in_(content_hashes)).all()
        )
        summaries_map = {s.content_hash: s for s in summaries}

    # Build post list for LLM
    posts_text = []
    for p in posts:
        summary = summaries_map.get(p.content_hash) if p.content_hash else None
        one_line = (
            summary.one_line_summary
            if summary
            else (p.content[:100] if p.content else "No summary")
        )
        tags = ", ".join(t.tag for t in p.tags)
        posts_text.append(
            f"- ID: {p.id} | Title: {p.title} | Summary: {one_line} | Tags: {tags}"
        )

    posts_with_summaries = "\n".join(posts_text)

    system_prompt = (
        "You are a knowledge management assistant helping curate a personal library of saved articles. "
        "Your job is to identify which articles are essential references, which are redundant, "
        "and which are situational. Be specific about WHY each article is essential or redundant. "
        f"IMPORTANT: All 'reason' fields MUST be written in {language}."
    )

    user_prompt = f"""The user has {len(posts)} starred articles in the topic "{context_name}".
They want to reduce their starred articles to only the most valuable ones.

Here are the articles (with AI-generated summaries):

{posts_with_summaries}

Analyze these articles and classify each one:
- "essential": Must-keep reference — unique information, comprehensive coverage, or foundational
- "redundant": Information is mostly covered by other articles in this set. Specify which ones.
- "keep_if_interested": Niche or situational — valuable only for specific use cases

For each article, explain your reasoning in one sentence.

Respond in JSON:
{{
  "essential": [
    {{"post_id": 123, "reason": "..."}},
    ...
  ],
  "redundant": [
    {{"post_id": 456, "reason": "...", "covered_by": [123, 789]}},
    ...
  ],
  "keep_if_interested": [
    {{"post_id": 321, "reason": "..."}},
    ...
  ],
}}"""

    result = await call_llm_json(system_prompt, user_prompt, max_tokens=8192, engine="ondemand")

    # Enrich result with post titles
    post_map = {p.id: p for p in posts}
    for category in ["essential", "redundant", "keep_if_interested"]:
        for item in result.get(category, []):
            pid = item.get("post_id")
            if pid and pid in post_map:
                item["title"] = post_map[pid].title

    return {
        "topic": context_name,
        "total_posts": len(posts),
        "analysis": {
            "essential": result.get("essential", []),
            "redundant": result.get("redundant", []),
            "keep_if_interested": result.get("keep_if_interested", []),
        },
    }


@router.post("/batch-unstar")
def batch_unstar(
    body: BatchUnstarRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Unstar multiple posts at once."""
    if not body.post_ids:
        return {"success": True, "count": 0}

    count = (
        db.query(Post)
        .filter(Post.id.in_(body.post_ids), Post.is_starred.is_(True))
        .update(
            {"is_starred": False, "starred_at": None},
            synchronize_session="fetch",
        )
    )
    db.commit()

    return {"success": True, "count": count}


@router.post("/export-selection")
def export_selection(
    body: ExportSelectionRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Export selected posts as a ZIP of markdown files."""
    if not body.post_ids:
        raise HTTPException(status_code=400, detail="No posts selected")

    posts = (
        db.query(Post)
        .filter(Post.id.in_(body.post_ids))
        .options(joinedload(Post.feed), subqueryload(Post.tags))
        .order_by(Post.sort_date.desc())
        .all()
    )

    if not posts:
        raise HTTPException(status_code=404, detail="No posts found")

    # Fetch summaries
    content_hashes = [p.content_hash for p in posts if p.content_hash]
    summaries_map = {}
    if content_hashes:
        summaries = (
            db.query(AISummary).filter(AISummary.content_hash.in_(content_hashes)).all()
        )
        summaries_map = {s.content_hash: s for s in summaries}

    # Build ZIP
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for post in posts:
            summary = (
                summaries_map.get(post.content_hash) if post.content_hash else None
            )
            md_content = _post_to_markdown(post, summary)

            slug = _slugify(post.title or "untitled")
            short_hash = hashlib.md5(str(post.id).encode()).hexdigest()[:6]
            filename = f"{slug}-{short_hash}.md"

            folder = _slugify(post.feed.title) if post.feed else "unknown"
            filepath = f"{folder}/{filename}"

            zf.writestr(filepath, md_content)

    zip_bytes = buf.getvalue()
    today = datetime.utcnow().strftime("%Y%m%d")
    zip_filename = f"selection-{today}.zip"

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


class RelatedSummaryRequest(BaseModel):
    post_ids: List[int]


@router.get("/{post_id}/related")
async def get_related_posts(
    post_id: int,
    include_read: bool = True,
    include_unread: bool = True,
    min_common_tags: int = 0,
    use_tag_fallback: bool = False,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Fetch related posts using a hybrid textual keyword search
    with tag-similarity fallback.

    Set use_tag_fallback=True to enable the tag-based fallback
    (Part B) when keyword search yields no results.
    """
    import math
    import re

    from sqlalchemy import case, func, or_

    from app.models import Feed, Post, PostTag
    from app.routes.preferences import get_effective_related_posts_limit

    # 1. Validar se o post existe
    post = get_post_or_404(db, post_id)

    # 2. Obter as tags do post atual (usadas para o fallback)
    tags_query = db.query(PostTag.tag).filter(PostTag.post_id == post_id)
    active_tags = [t[0] for t in tags_query.all()]

    # 3. Determinar limite das preferências
    limit = get_effective_related_posts_limit(db)

    # --- PARTE A: BUSCA TEXTUAL POR PALAVRAS-CHAVE ---
    posts_list = []

    # 4. Extrair keywords do título (fonte principal de busca)
    source_texts = [post.title or ""]
    source_texts = [post.title or ""]

    # Tokenizar todas as fontes (set elimina duplicatas entre fontes)
    all_words = set()
    for text in source_texts:
        if text:
            clean = re.sub(r"[^\w\s-]", "", text.lower())
            for w in clean.split():
                if len(w) >= 3:
                    all_words.add(w)

    # Stop words expandidas — removendo termos genéricos que poluem a busca
    stop_words = {
        "de", "do", "da", "em", "para", "com", "por", "um", "uma", "os", "as",
        "se", "ou", "o", "a", "que", "ao", "aos", "no", "na", "nos", "nas",
        "and", "the", "a", "an", "of", "to", "in", "for", "with", "on", "at",
        "by", "from", "about", "as", "is", "are", "was", "were", "it", "this",
        "that", "these", "those", "how", "why", "what", "where", "when", "who",
        "which", "released", "version", "new", "update", "novo", "nova",
        "atualizacao", "versao", "lancado", "lancada", "using", "usando",
        "post", "article", "artigo", "feed", "blog", "site", "web",
        "have", "has", "had", "having", "way", "ways", "their", "them", "they",
        "its", "get", "gets", "got", "make", "makes", "made", "like", "just",
        "also", "can", "will", "may", "said", "one", "time", "people", "many",
        "much", "even", "still", "well", "first", "last", "next", "every",
        "some", "any", "all", "been", "being", "done", "does", "did", "doing",
        "over", "under", "into", "through", "during", "before", "after",
        "between", "each", "few", "more", "most", "other", "such", "only",
        "own", "same", "too", "very", "than", "then", "now", "here", "there",
        "could", "would", "should", "might", "must", "shall", "about",
        "above", "across", "after", "again", "against", "below", "because",
        "been", "being", "both", "down", "further", "furthermore",
        "herein", "hereby", "hereafter", "however", "indeed", "instead",
        "meanwhile", "moreover", "neither", "never", "nonetheless",
        "nor", "otherwise", "perhaps", "rather", "since", "somehow",
        "somewhat", "thereafter", "thereby", "therefore", "therein",
        "thereupon", "together", "toward", "towards", "throughout",
        "unless", "unto", "upon", "whence", "whereas", "whereby",
        "wherein", "whereupon", "wherever", "whether", "whichever",
        "while", "whilst", "within", "without",
    }

    keywords = sorted(w for w in all_words if w not in stop_words)

    # Se sobrou muito pouco (menos de 2 keywords), fallback para o título puro
    if len(keywords) < 2 and post.title:
        title_clean = re.sub(r"[^\w\s-]", "", post.title.lower())
        title_words = [w for w in title_clean.split() if len(w) >= 3]
        keywords = sorted(w for w in title_words if w not in stop_words)
        if not keywords and title_words:
            keywords = title_words

    if keywords:
        # --- Batch IDF: frequência de cada keyword no título dos posts ---
        # Uma única query calcula quantos posts contêm cada keyword.
        # Palavras muito comuns (ex: "thing", "someone") ganham IDF baixo.
        total_posts = db.query(func.count(Post.id)).scalar() or 1
        freq_cases = [
            func.sum(
                case(
                    (func.lower(Post.title).like(f"%{kw}%"), 1),
                    else_=0,
                )
            )
            for kw in keywords
        ]
        freq_row = db.query(*freq_cases).first()
        kw_idf = {
            kw: math.log(max(total_posts, 1) / (1 + (freq or 0)))
            for kw, freq in zip(keywords, freq_row)
        }

        # --- Montar as condições SQL ---
        score_conditions = []
        keyword_or_groups = []  # um grupo OR por keyword

        for kw in keywords:
            term = f"%{kw}%"
            idf = kw_idf[kw]

            # Condições OR para esta keyword (qualquer campo que case)
            kw_matches = [
                func.lower(Post.title).like(term),
                func.lower(Post.content).like(term),
                func.lower(AISummary.translated_title).like(term),
                func.lower(AISummary.one_line_summary).like(term),
                func.lower(AISummary.summary_pt).like(term),
            ]
            keyword_or_groups.append(kw_matches)

            # Relevância alta para match no Título (peso 5.0 * IDF)
            title_match = or_(
                func.lower(Post.title).like(term),
                func.lower(AISummary.translated_title).like(term),
            )
            # Relevância moderada para match no Conteúdo/Resumos (peso 1.5 * IDF)
            content_match = or_(
                func.lower(Post.content).like(term),
                func.lower(AISummary.one_line_summary).like(term),
                func.lower(AISummary.summary_pt).like(term),
            )

            score_conditions.append(case((title_match, 5.0 * idf), else_=0.0))
            score_conditions.append(case((content_match, 1.5 * idf), else_=0.0))

        text_score = sum(score_conditions)

        # --- Executar a busca ---
        # Exigir que o post casado tenha PELO MENOS 2 keywords distintas
        # (caso contrário, uma única palavra genérica não basta)
        kw_any_match = [or_(*group) for group in keyword_or_groups]
        match_count = sum(case((m, 1), else_=0) for m in kw_any_match)

        text_query = (
            db.query(
                Post.id,
                Post.title,
                Post.feed_id,
                Post.is_suggested,
                Feed.title.label("feed_title"),
                AISummary.summary_pt,
            )
            .outerjoin(
                AISummary, Post.content_hash == AISummary.content_hash
            )
            .join(Feed, Post.feed_id == Feed.id)
            .filter(Post.id != post_id)
        )

        # Filtro de keywords: cada post precisa casar com ≥2 keywords
        text_query = text_query.filter(match_count >= 2)

        if not include_read:
            text_query = text_query.filter(Post.is_read.is_(False))
        if not include_unread:
            text_query = text_query.filter(Post.is_read.is_(True))

        text_query = (
            text_query.order_by(text_score.desc(), Post.sort_date.desc())
            .limit(limit)
        )
        text_results = text_query.all()

        if text_results:
            # Encontramos posts por texto! Calcular tags em comum para a UI
            post_ids_found = [r.id for r in text_results]
            tag_counts_map = {}
            if active_tags:
                tag_counts = (
                    db.query(PostTag.post_id, func.count(PostTag.tag))
                    .filter(PostTag.tag.in_(active_tags))
                    .filter(PostTag.post_id.in_(post_ids_found))
                    .group_by(PostTag.post_id)
                    .all()
                )
                tag_counts_map = {p_id: count for p_id, count in tag_counts}

            # Re-ranqueamento TF-IDF em Python: calcular TF real no texto completo
            # (título + summary_pt) de cada candidato, ponderado pelo IDF já calculado.
            scored = []
            for r in text_results:
                common_count = tag_counts_map.get(r.id, 0)
                if common_count < min_common_tags:
                    continue

                # Texto completo do candidato para TF
                candidate_text = (r.title or "")
                if r.summary_pt:
                    candidate_text += " " + re.sub(r"<[^>]+>", "", r.summary_pt)
                candidate_words = re.sub(r"[^\w\s-]", "", candidate_text.lower()).split()
                candidate_len = max(len(candidate_words), 1)

                # TF real: quantas vezes cada keyword aparece no texto do candidato
                tfidf_score = 0.0
                for kw in keywords:
                    idf = kw_idf.get(kw, 1.0)
                    tf = candidate_words.count(kw) / candidate_len
                    tfidf_score += tf * idf

                # Peso combinado: TF-IDF + (1 + 0.15 * tags_comuns) para priorizar
                # posts do mesmo tópico (mesmas tags)
                combined_score = tfidf_score * (1 + 0.15 * common_count)
                scored.append((combined_score, r, common_count))

            # Ordenar por score combinado descendente
            scored.sort(key=lambda x: -x[0])

            posts_list = [
                {
                    "id": r.id,
                    "title": r.title,
                    "feed_title": r.feed_title,
                    "feed_id": r.feed_id,
                    "is_suggested": bool(r.is_suggested),
                    "common_tags_count": common_count,
                }
                for _, r, common_count in scored
            ]

    # --- PARTE B: FALLBACK PARA BUSCA POR TAGS (TF-IDF) ---
    # Se a busca textual não encontrou nada e o post tem tags, caímos para o TF-IDF
    if not posts_list and active_tags and use_tag_fallback:
        # Carregar sort_date e categoria do post fonte para boosts
        source_sort_date = post.sort_date
        source_feed_category_id = post.feed.category_id if post.feed else None

        tag_freqs = (
            db.query(PostTag.tag, func.count(PostTag.post_id))
            .filter(PostTag.tag.in_(active_tags))
            .group_by(PostTag.tag)
            .all()
        )

        tag_weights = {}
        for tag, freq in tag_freqs:
            tag_weights[tag] = 1.0 / math.log(freq + 1) if freq > 0 else 0.1

        if not tag_weights:
            relevance_score = func.count(PostTag.tag)
        else:
            w_cases = [(PostTag.tag == t, w) for t, w in tag_weights.items()]
            relevance_score = func.sum(case(*w_cases, else_=0.0))

        related_query = (
            db.query(
                Post.id,
                Post.title,
                Post.feed_id,
                Post.is_suggested,
                Feed.title.label("feed_title"),
                Feed.category_id,
                Post.sort_date,
                func.count(PostTag.tag).label("common_tags_count"),
                relevance_score.label("relevance_score"),
            )
            .join(PostTag, Post.id == PostTag.post_id)
            .join(Feed, Post.feed_id == Feed.id)
            .filter(PostTag.tag.in_(active_tags))
            .filter(Post.id != post_id)
        )

        if not include_read:
            related_query = related_query.filter(Post.is_read.is_(False))
        if not include_unread:
            related_query = related_query.filter(Post.is_read.is_(True))

        related_query = (
            related_query.group_by(Post.id)
            .order_by(relevance_score.desc(), Post.sort_date.desc())
            .limit(limit)
        )
        tag_results = related_query.all()

        # Re-ranqueamento: combinar relevância de tags + proximidade temporal
        # + mesma categoria (assuntos quentes aparecem próximos no tempo)
        scored = []
        for r in tag_results:
            score = r.relevance_score

            # Boost temporal: posts mais próximos da data do post fonte ganham peso
            if source_sort_date and r.sort_date:
                days_diff = abs((source_sort_date - r.sort_date).days)
                if days_diff <= 1:
                    temp_boost = 2.0
                elif days_diff <= 3:
                    temp_boost = 1.5
                elif days_diff <= 7:
                    temp_boost = 1.2
                elif days_diff <= 14:
                    temp_boost = 1.0
                else:
                    temp_boost = 0.5
            else:
                temp_boost = 1.0

            # Boost de categoria: mesmo assunto → mesmo feed/categoria
            cat_boost = 1.0
            if source_feed_category_id and r.category_id:
                if r.category_id == source_feed_category_id:
                    cat_boost = 1.3  # +30% para mesma categoria

            combined = score * temp_boost * cat_boost
            scored.append((combined, r))

        # Ordenar por score combinado
        scored.sort(key=lambda x: -x[0])

        posts_list = [
            {
                "id": r.id,
                "title": r.title,
                "feed_title": r.feed_title,
                "feed_id": r.feed_id,
                "is_suggested": bool(r.is_suggested),
                "common_tags_count": r.common_tags_count,
            }
            for _, r in scored
        ]

    return {"posts": posts_list}


@router.post("/related-summary")
async def generate_related_summary(
    body: RelatedSummaryRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Generate a consolidation of summaries (summary of summaries)
    for the selected related posts.
    """
    if not body.post_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum post selecionado para consolidar",
        )

    import re

    from app.models import AISummary, Post
    from app.services.ai import call_llm_text

    # 1. Carrega os posts
    posts = db.query(Post).filter(Post.id.in_(body.post_ids)).all()
    if not posts:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Posts não encontrados",
        )

    # 2. Carrega os resumos correspondentes
    content_hashes = [p.content_hash for p in posts if p.content_hash]
    summaries_map = {}
    if content_hashes:
        summaries = (
            db.query(AISummary)
            .filter(AISummary.content_hash.in_(content_hashes))
            .all()
        )
        summaries_map = {
            s.content_hash: s.summary_pt
            for s in summaries
            if s.summary_pt
        }

    # 3. Constrói o texto consolidado
    prompt_content = []
    for p in posts:
        summary_text = summaries_map.get(p.content_hash)
        if not summary_text:
            # Fallback se não tiver resumo
            summary_text = p.content or ""

        if summary_text.strip():
            clean_summary = re.sub(r"<[^>]+>", "", summary_text)
            prompt_content.append(
                f"Título: {p.title}\nResumo:\n{clean_summary}\n---"
            )

    if not prompt_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nenhum dos posts selecionados possui resumo ou conteúdo válido",
        )

    combined_summaries = "\n\n".join(prompt_content)

    # 4. Invoca o LLM
    system_prompt = (
        "Você é o assistente inteligente de consolidação do Risos "
        "(Sparkle Assistant).\n"
        "Sua tarefa é analisar os resumos e títulos de múltiplos posts e "
        "produzir uma síntese global unificada ('sumário dos sumários').\n"
        "Crie um resumo de alto nível, bem estruturado em tópicos lógicos, "
        "destacando os pontos convergentes, divergências significativas e "
        "uma conclusão consolidada.\n"
        "Sua resposta deve ser escrita obrigatoriamente em "
        "Português Brasileiro, formatada em Markdown elegante.\n"
        "Seja direto e objetivo, sem introduções desnecessárias ou saudações. "
        "Vá direto ao conteúdo consolidado."
    )

    user_prompt = (
        "Aqui estão as matérias selecionadas e seus respectivos resumos:\n\n"
        f"{combined_summaries}\n\n"
        "Por favor, consolide tudo isso em um único sumário estruturado, "
        "elegante e fácil de ler."
    )

    try:
        super_summary = await call_llm_text(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_tokens=4096,
            temperature=0.3,
            engine="ondemand",
        )
        return {"summary": super_summary}
    except Exception as e:
        logger.error(f"Erro ao gerar sumário consolidado: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erro ao processar consolidação no LLM: {str(e)}",
        )



