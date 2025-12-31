"""
Feed routes.
CRUD + refresh + OPML import/export.
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from typing import List, Optional
from urllib.parse import urlparse, urljoin
import re
import httpx

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Feed, Post, Category
from app.schemas import FeedCreate, FeedUpdate, FeedResponse, MAX_CATEGORY_NAME_LENGTH
from app.services.feed_ingestion import ingest_feed

router = APIRouter(prefix="/feeds", tags=["feeds"])


def get_hostname(url: str) -> str:
    """Extract hostname from URL to use as placeholder title."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


@router.get("", response_model=List[FeedResponse])
def list_feeds(
    category_id: Optional[int] = Query(None, description="Filter by category"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all feeds, optionally filtered by category."""
    # Subquery to count unread posts per feed
    unread_count_subq = (
        db.query(Post.feed_id, func.count(Post.id).label("unread_count"))
        .filter(Post.is_read == False)
        .group_by(Post.feed_id)
        .subquery()
    )

    query = db.query(
        Feed,
        func.coalesce(unread_count_subq.c.unread_count, 0).label(
            "unread_count"
        ),
    ).outerjoin(unread_count_subq, Feed.id == unread_count_subq.c.feed_id)

    if category_id is not None:
        query = query.filter(Feed.category_id == category_id)

    feeds = query.order_by(func.lower(Feed.title)).all()

    result = []
    for feed, unread_count in feeds:
        feed_dict = {
            "id": feed.id,
            "category_id": feed.category_id,
            "title": feed.title,
            "url": feed.url,
            "site_url": feed.site_url,
            "last_fetched_at": feed.last_fetched_at,
            "error_count": feed.error_count or 0,
            "last_error": feed.last_error,
            "disabled_at": feed.disabled_at,
            "created_at": feed.created_at,
            "unread_count": unread_count,
        }
        result.append(FeedResponse(**feed_dict))

    return result


@router.post("/discover")
async def discover_feed(
    url: str = Query(..., description="Site URL to discover feed from"),
    user: dict = Depends(get_current_user),
):
    """
    Discover RSS/Atom feed from a website URL.

    Tries:
    1. Check if URL is already a feed
    2. Look for <link rel="alternate"> tags in HTML
    3. Try common feed paths (/feed, /rss, etc.)

    Returns the feed URL if found, or error if not.
    """
    # Normalize URL
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url

    headers = {
        'User-Agent': 'Mozilla/5.0 (compatible; RSSReader/1.0)'
    }

    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        # First, check if the URL itself is a feed
        try:
            resp = await client.get(url, headers=headers)
            content_type = resp.headers.get('content-type', '').lower()

            if any(t in content_type for t in ['xml', 'rss', 'atom']):
                return {"feed_url": str(resp.url), "method": "direct"}

            # Check if content looks like a feed
            text = resp.text[:1000]
            if '<rss' in text or '<feed' in text or '<rdf:RDF' in text:
                return {"feed_url": str(resp.url), "method": "direct"}

        except httpx.RequestError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Could not fetch URL"
            )

        # Parse HTML and look for feed links
        html = resp.text
        feed_pattern = re.compile(
            r'<link[^>]+rel=["\']alternate["\'][^>]+>',
            re.IGNORECASE
        )

        for match in feed_pattern.findall(html):
            if 'application/rss+xml' in match or 'application/atom+xml' in match:
                href_match = re.search(r'href=["\']([^"\']+)["\']', match)
                if href_match:
                    feed_url = urljoin(str(resp.url), href_match.group(1))
                    return {"feed_url": feed_url, "method": "link_tag"}

        # Try common feed paths
        common_paths = [
            '/feed', '/feeds', '/rss', '/rss.xml', '/feed.xml',
            '/atom.xml', '/index.xml', '/feed/rss', '/blog/feed',
            '/.rss', '/rss/index.xml'
        ]

        base_url = f"{urlparse(str(resp.url)).scheme}://{urlparse(str(resp.url)).netloc}"

        for path in common_paths:
            try:
                test_url = base_url + path
                test_resp = await client.get(test_url, headers=headers)
                if test_resp.status_code == 200:
                    ct = test_resp.headers.get('content-type', '').lower()
                    text = test_resp.text[:1000]
                    if any(t in ct for t in ['xml', 'rss', 'atom']) or \
                       '<rss' in text or '<feed' in text or '<rdf:RDF' in text:
                        return {"feed_url": str(test_resp.url), "method": "common_path"}
            except httpx.RequestError:
                continue

        # No feed found
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No RSS/Atom feed found for this site"
        )


@router.post(
    "", response_model=FeedResponse, status_code=status.HTTP_201_CREATED
)
async def create_feed(
    feed: FeedCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Create a new feed.
    If title not provided, uses hostname from URL as placeholder.
    Triggers initial post fetch automatically.
    """
    # Check if URL already exists
    existing = db.query(Feed).filter(Feed.url == feed.url).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feed with this URL already exists",
        )

    # Check if category_id exists (if provided)
    if feed.category_id:
        category = (
            db.query(Category).filter(Category.id == feed.category_id).first()
        )
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found",
            )

    # Use hostname as title if not provided
    title = feed.title if feed.title else get_hostname(feed.url)

    db_feed = Feed(
        url=feed.url,
        title=title,
        category_id=feed.category_id,
    )
    db.add(db_feed)
    db.commit()
    db.refresh(db_feed)

    # Trigger initial post fetch
    try:
        await ingest_feed(db, db_feed)
        db.refresh(db_feed)
    except Exception as e:
        # Log error but don't fail the feed creation
        import logging

        logging.getLogger(__name__).error(
            f"Initial feed ingestion failed for {db_feed.url}: {e}"
        )

    # Count unread posts after ingestion
    unread_count = (
        db.query(func.count(Post.id))
        .filter(Post.feed_id == db_feed.id, Post.is_read == False)
        .scalar()
        or 0
    )

    return FeedResponse(
        id=db_feed.id,
        category_id=db_feed.category_id,
        title=db_feed.title,
        url=db_feed.url,
        site_url=db_feed.site_url,
        last_fetched_at=db_feed.last_fetched_at,
        error_count=db_feed.error_count or 0,
        last_error=db_feed.last_error,
        disabled_at=db_feed.disabled_at,
        created_at=db_feed.created_at,
        unread_count=unread_count,
    )


@router.post("/import-opml")
async def import_opml(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Import feeds from an OPML file.

    - Creates categories if they don't exist
    - Ignores duplicate feeds (by URL)
    - Returns count of imported and errors
    """
    # Check file type
    if not file.filename.endswith((".opml", ".xml")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be .opml or .xml",
        )

    # Read content
    content = await file.read()
    if len(content) > 1024 * 1024:  # 1MB limit
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large (max 1MB)",
        )

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid XML: {e}"
        )

    imported = 0
    skipped = 0
    errors = []

    # Find body/outline
    body = root.find(".//body")
    if body is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OPML: no body element",
        )

    def process_outline(outline, category_id=None):
        nonlocal imported, skipped, errors

        xml_url = outline.get("xmlUrl")
        title = outline.get("title") or outline.get("text")

        if xml_url:
            # It's a feed
            existing = db.query(Feed).filter(Feed.url == xml_url).first()
            if existing:
                skipped += 1
                return

            try:
                feed = Feed(
                    url=xml_url,
                    title=title or get_hostname(xml_url),
                    site_url=outline.get("htmlUrl"),
                    category_id=category_id,
                )
                db.add(feed)
                db.flush()
                imported += 1
            except Exception as e:
                errors.append(f"Error adding {xml_url}: {e}")
        else:
            # It's a category (folder)
            cat_name = title
            if cat_name:
                # Truncate category name if too long
                cat_name = cat_name[:MAX_CATEGORY_NAME_LENGTH].strip()

                # Find or create category
                category = (
                    db.query(Category)
                    .filter(Category.name == cat_name)
                    .first()
                )
                if not category:
                    category = Category(name=cat_name)
                    db.add(category)
                    db.flush()

                cat_id = category.id
            else:
                cat_id = category_id

            # Process children
            for child in outline:
                process_outline(child, cat_id)

    # Process body outlines
    for outline in body:
        process_outline(outline)

    db.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


@router.get("/export-opml")
def export_opml(
    db: Session = Depends(get_db), user: dict = Depends(get_current_user)
):
    """
    Export all feeds in OPML format.

    - Groups feeds by category
    - Uncategorized feeds go at root level
    """
    # Create OPML structure
    opml = ET.Element("opml", version="1.0")

    head = ET.SubElement(opml, "head")
    title = ET.SubElement(head, "title")
    title.text = "RSS Reader Export"
    date_created = ET.SubElement(head, "dateCreated")
    date_created.text = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")

    body = ET.SubElement(opml, "body")

    # Fetch categories with feeds
    categories = db.query(Category).order_by(func.lower(Category.name)).all()

    for category in categories:
        feeds = (
            db.query(Feed)
            .filter(Feed.category_id == category.id)
            .order_by(func.lower(Feed.title))
            .all()
        )
        if not feeds:
            continue

        cat_outline = ET.SubElement(
            body, "outline", text=category.name, title=category.name
        )

        for feed in feeds:
            attrs = {
                "type": "rss",
                "text": feed.title,
                "title": feed.title,
                "xmlUrl": feed.url,
            }
            if feed.site_url:
                attrs["htmlUrl"] = feed.site_url
            ET.SubElement(cat_outline, "outline", **attrs)

    # Uncategorized feeds
    uncategorized = (
        db.query(Feed)
        .filter(Feed.category_id.is_(None))
        .order_by(func.lower(Feed.title))
        .all()
    )
    for feed in uncategorized:
        attrs = {
            "type": "rss",
            "text": feed.title,
            "title": feed.title,
            "xmlUrl": feed.url,
        }
        if feed.site_url:
            attrs["htmlUrl"] = feed.site_url
        ET.SubElement(body, "outline", **attrs)

    # Generate XML
    xml_str = ET.tostring(opml, encoding="unicode", xml_declaration=True)

    return Response(
        content=xml_str,
        media_type="application/xml",
        headers={"Content-Disposition": 'attachment; filename="feeds.opml"'},
    )


@router.get("/{feed_id}", response_model=FeedResponse)
def get_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Fetch a feed by ID."""
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found"
        )

    unread_count = (
        db.query(func.count(Post.id))
        .filter(Post.feed_id == feed_id, Post.is_read == False)
        .scalar()
    )

    return FeedResponse(
        id=feed.id,
        category_id=feed.category_id,
        title=feed.title,
        url=feed.url,
        site_url=feed.site_url,
        last_fetched_at=feed.last_fetched_at,
        error_count=feed.error_count or 0,
        last_error=feed.last_error,
        disabled_at=feed.disabled_at,
        created_at=feed.created_at,
        unread_count=unread_count,
    )


@router.put("/{feed_id}", response_model=FeedResponse)
def update_feed(
    feed_id: int,
    feed_update: FeedUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Update a feed."""
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found"
        )

    # Check for duplicate URL (if changed)
    if feed_update.url and feed_update.url != feed.url:
        existing = db.query(Feed).filter(Feed.url == feed_update.url).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Feed with this URL already exists",
            )

    # Check category_id (if provided)
    if feed_update.category_id is not None:
        if feed_update.category_id != 0:  # 0 means remove category
            category = (
                db.query(Category)
                .filter(Category.id == feed_update.category_id)
                .first()
            )
            if not category:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Category not found",
                )

    # Update fields
    if feed_update.title is not None:
        feed.title = feed_update.title
    if feed_update.url is not None:
        feed.url = feed_update.url
    if feed_update.category_id is not None:
        feed.category_id = (
            feed_update.category_id if feed_update.category_id != 0 else None
        )

    db.commit()
    db.refresh(feed)

    unread_count = (
        db.query(func.count(Post.id))
        .filter(Post.feed_id == feed_id, Post.is_read == False)
        .scalar()
    )

    return FeedResponse(
        id=feed.id,
        category_id=feed.category_id,
        title=feed.title,
        url=feed.url,
        site_url=feed.site_url,
        last_fetched_at=feed.last_fetched_at,
        error_count=feed.error_count or 0,
        last_error=feed.last_error,
        disabled_at=feed.disabled_at,
        created_at=feed.created_at,
        unread_count=unread_count,
    )


@router.delete("/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Delete a feed.
    Feed posts are removed in cascade.
    """
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found"
        )

    db.delete(feed)
    db.commit()

    return None


@router.post("/{feed_id}/refresh")
async def refresh_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Fetch and ingest new posts from a feed.

    Returns ingestion statistics:
    - new_posts: Number of new posts inserted
    - skipped_duplicates: Posts skipped due to duplicates
    - errors: List of errors (if any)
    """
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found"
        )

    if feed.disabled_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Feed is disabled"
        )

    result = await ingest_feed(db, feed)

    return {
        "feed_id": feed_id,
        "new_posts": result.new_posts,
        "skipped_duplicates": result.skipped_duplicates,
        "errors": result.errors,
        "feed_title_updated": result.feed_title_updated,
        "site_url_updated": result.site_url_updated,
    }


@router.post("/{feed_id}/enable")
def enable_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Re-enable a disabled feed.
    Resets error_count, disabled_at and next_retry_at.
    """
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Feed not found"
        )

    feed.error_count = 0
    feed.disabled_at = None
    feed.disable_reason = None
    feed.next_retry_at = None
    feed.last_error = None

    db.commit()

    return {"ok": True, "feed_id": feed_id}
