"""
Topic management routes.
Topics are named groups of tags for content organization.
"""

import time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import case, distinct, func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Post, PostTag, Topic, TopicTag

router = APIRouter(prefix="/topics", tags=["topics"])

# Short-lived in-process cache for the topic list. Computing post/unread
# counts scans a large post_tags table; the sidebar polls this often and
# slightly stale counts are fine (the frontend also adjusts them locally).
_TOPICS_CACHE_TTL = 60.0
_topics_cache: dict = {"data": None, "ts": 0.0}


def _invalidate_topics_cache() -> None:
    _topics_cache["data"] = None
    _topics_cache["ts"] = 0.0


class TopicCreate(BaseModel):
    name: str
    tags: List[str] = []


class TopicUpdate(BaseModel):
    name: Optional[str] = None
    position: Optional[int] = None


class TagsAdd(BaseModel):
    tags: List[str]


@router.get("")
def list_topics(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """List all topics with tags, post count, and unread count."""
    now = time.monotonic()
    if (
        _topics_cache["data"] is not None
        and now - _topics_cache["ts"] < _TOPICS_CACHE_TTL
    ):
        return _topics_cache["data"]

    topics = db.query(Topic).order_by(Topic.name).all()

    # Tags per topic, in one query.
    tags_by_topic: dict[int, list[str]] = {topic.id: [] for topic in topics}
    for topic_id, tag in (
        db.query(TopicTag.topic_id, TopicTag.tag)
        .order_by(TopicTag.topic_id, TopicTag.tag)
        .all()
    ):
        tags_by_topic.setdefault(topic_id, []).append(tag)

    # Post and unread counts for every topic in a single grouped query,
    # driven by the post_tags(tag, post_id) index. COUNT(DISTINCT ...)
    # matches the previous per-topic semantics (a post is counted once per
    # topic regardless of how many of its tags match).
    counts: dict[int, tuple[int, int]] = {}
    rows = (
        db.query(
            TopicTag.topic_id.label("topic_id"),
            func.count(distinct(PostTag.post_id)).label("post_count"),
            func.count(
                distinct(case((Post.is_read.is_(False), PostTag.post_id)))
            ).label("unread_count"),
        )
        .join(PostTag, PostTag.tag == TopicTag.tag)
        .join(Post, Post.id == PostTag.post_id)
        .group_by(TopicTag.topic_id)
        .all()
    )
    for row in rows:
        counts[row.topic_id] = (row.post_count or 0, row.unread_count or 0)

    result = []
    for topic in topics:
        post_count, unread_count = counts.get(topic.id, (0, 0))
        result.append(
            {
                "id": topic.id,
                "name": topic.name,
                "position": topic.position,
                "tags": tags_by_topic.get(topic.id, []),
                "post_count": post_count,
                "unread_count": unread_count,
            }
        )

    _topics_cache["data"] = result
    _topics_cache["ts"] = now
    return result


@router.post("")
def create_topic(
    body: TopicCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Create a new topic with optional tags."""
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Topic name cannot be empty")

    existing = db.query(Topic).filter(Topic.name == name).first()
    if existing:
        raise HTTPException(
            status_code=409, detail="Topic with this name already exists"
        )

    # Get max position
    max_pos = db.query(func.max(Topic.position)).scalar() or 0

    topic = Topic(name=name, position=max_pos + 1)
    db.add(topic)
    db.flush()

    for tag in body.tags:
        tag = tag.strip().lower()
        if tag:
            db.add(TopicTag(topic_id=topic.id, tag=tag))

    db.commit()
    db.refresh(topic)
    _invalidate_topics_cache()

    return {
        "id": topic.id,
        "name": topic.name,
        "position": topic.position,
        "tags": [tt.tag for tt in topic.tags],
    }


@router.put("/{topic_id}")
def update_topic(
    topic_id: int,
    body: TopicUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Update topic name or position."""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    if body.name is not None:
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Topic name cannot be empty")
        existing = (
            db.query(Topic).filter(Topic.name == name, Topic.id != topic_id).first()
        )
        if existing:
            raise HTTPException(
                status_code=409, detail="Topic with this name already exists"
            )
        topic.name = name

    if body.position is not None:
        topic.position = body.position

    db.commit()
    _invalidate_topics_cache()

    return {
        "id": topic.id,
        "name": topic.name,
        "position": topic.position,
        "tags": [tt.tag for tt in topic.tags],
    }


@router.delete("/{topic_id}")
def delete_topic(
    topic_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Delete a topic and its tag associations."""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    db.delete(topic)
    db.commit()
    _invalidate_topics_cache()

    return {"success": True}


@router.post("/{topic_id}/tags")
def add_tags_to_topic(
    topic_id: int,
    body: TagsAdd,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Add tags to a topic."""
    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Validate all tags exist in the database
    normalized = [t.strip().lower() for t in body.tags if t.strip()]
    if normalized:
        valid_tags = {
            row.tag
            for row in db.query(PostTag.tag)
            .filter(PostTag.tag.in_(normalized))
            .distinct()
            .all()
        }
        invalid = [t for t in normalized if t not in valid_tags]
        if invalid:
            raise HTTPException(
                status_code=400,
                detail=f"Tags not found: {', '.join(invalid)}",
            )

    existing_tags = {tt.tag for tt in topic.tags}
    added = []

    for tag in normalized:
        if tag not in existing_tags:
            db.add(TopicTag(topic_id=topic_id, tag=tag))
            added.append(tag)
            existing_tags.add(tag)

    db.commit()
    _invalidate_topics_cache()

    return {"success": True, "added": added}


@router.delete("/{topic_id}/tags/{tag}")
def remove_tag_from_topic(
    topic_id: int,
    tag: str,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Remove a tag from a topic."""
    tag = tag.strip().lower()
    row = (
        db.query(TopicTag)
        .filter(TopicTag.topic_id == topic_id, TopicTag.tag == tag)
        .first()
    )
    if row:
        db.delete(row)
        db.commit()
        _invalidate_topics_cache()

    return {"success": True}


@router.post("/{topic_id}/suggest-tags")
async def suggest_tags_for_topic(
    topic_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Use AI to suggest which unassigned tags fit a specific topic."""
    from app.services.ai._api import call_llm_json

    topic = db.query(Topic).filter(Topic.id == topic_id).first()
    if not topic:
        raise HTTPException(status_code=404, detail="Topic not found")

    # Tags already in ANY topic
    assigned_tags = {row.tag for row in db.query(TopicTag.tag).all()}

    # Get unassigned tags with counts
    query = (
        db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
        .group_by(PostTag.tag)
        .order_by(func.count(PostTag.post_id).desc())
    )
    if assigned_tags:
        query = query.filter(~PostTag.tag.in_(assigned_tags))

    rows = query.limit(200).all()

    if not rows:
        return {"tags": [], "topic_name": topic.name}

    tags_list = "\n".join(f"- {row.tag} ({row.count} posts)" for row in rows)
    current_tags = ", ".join(tt.tag for tt in topic.tags) or "(none yet)"

    system_prompt = (
        "You help organize article tags into topic groups for a personal RSS reader. "
        "Tags are always in English (lowercase, hyphenated). "
        "Topic names may be in any language (e.g. Portuguese)."
    )

    user_prompt = f"""The user has a topic called "{topic.name}" with these tags already assigned: {current_tags}

Here are unassigned tags (with post counts):

{tags_list}

Which of these tags belong in the topic "{topic.name}"? Select ONLY tags that genuinely fit this topic. Be selective — it's better to miss a tag than to include one that doesn't belong.

Respond ONLY in JSON:
{{
  "tags": ["tag1", "tag2", "tag3"]
}}"""

    result = await call_llm_json(system_prompt, user_prompt, engine="ondemand")

    # Validate: only return tags that actually exist in the unassigned pool
    available = {row.tag for row in rows}
    suggested = [
        t for t in result.get("tags", []) if isinstance(t, str) and t in available
    ]

    return {"tags": suggested, "topic_name": topic.name}


@router.post("/suggest")
async def suggest_topics(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Use AI to suggest topic groupings from popular tags."""
    from app.services.ai._api import call_llm_json

    # Exclude tags already assigned to any topic
    assigned_tags = {row.tag for row in db.query(TopicTag.tag).all()}

    # Get top 150 unassigned tags with counts
    query = (
        db.query(PostTag.tag, func.count(PostTag.post_id).label("count"))
        .group_by(PostTag.tag)
        .order_by(func.count(PostTag.post_id).desc())
    )
    if assigned_tags:
        query = query.filter(~PostTag.tag.in_(assigned_tags))

    rows = query.limit(150).all()

    if not rows:
        return {"suggestions": [], "orphan_tags": [], "total_tags_analyzed": 0}

    tags_with_counts = "\n".join(f"- {row.tag} ({row.count} posts)" for row in rows)

    system_prompt = (
        "You organize article tags into topic groups for a personal RSS reader. "
        "Create coherent, useful groupings that help the user navigate their reading."
    )

    user_prompt = f"""Here are the most frequent tags in this RSS reader, with post counts:

{tags_with_counts}

Group these tags into 5-12 coherent topics. Rules:
- Each topic gets a short, clear name (2-4 words)
- Tags should genuinely belong together
- A tag can appear in multiple topics if it fits
- Include ALL tags in at least one topic if possible
- List any tags you can't classify as "orphan_tags"

Respond ONLY in JSON:
{{
  "topics": [
    {{"name": "Topic Name", "tags": ["tag1", "tag2", "tag3"]}},
    ...
  ],
  "orphan_tags": ["tag1", "tag2"]
}}"""

    result = await call_llm_json(system_prompt, user_prompt, engine="ondemand")

    suggestions = []
    for item in result.get("topics", []):
        if isinstance(item, dict) and "name" in item and "tags" in item:
            suggestions.append(
                {
                    "name": item["name"],
                    "tags": [t for t in item["tags"] if isinstance(t, str)],
                }
            )

    return {
        "suggestions": suggestions,
        "orphan_tags": result.get("orphan_tags", []),
        "total_tags_analyzed": len(rows),
    }
