"""
Routes for the AI suggestion system.
Includes status endpoint and admin controls.
"""

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user
from app.services.suggestions import get_suggestion_stats, process_suggestion_candidates
from app.services.user_profile import (
    generate_user_profile,
    invalidate_user_profile,
    get_liked_posts_count,
    MIN_LIKED_POSTS,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


class SuggestionStatusResponse(BaseModel):
    """Response for suggestion system status."""

    liked_count: int
    min_liked_required: int
    profile_ready: bool
    profile_stale: bool
    profile_tags_count: int
    suggested_unread: int
    suggested_total: int
    last_profile_update: str | None


class AdminActionResponse(BaseModel):
    """Response for admin actions."""

    success: bool
    message: str


@router.get("/status", response_model=SuggestionStatusResponse)
def get_status(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get the current status of the suggestion system.
    Shows whether the user has enough likes for suggestions,
    if the profile is ready, and how many suggestions exist.
    """
    stats = get_suggestion_stats(db)

    return SuggestionStatusResponse(
        liked_count=stats["liked_count"],
        min_liked_required=MIN_LIKED_POSTS,
        profile_ready=stats["profile_ready"],
        profile_stale=stats["profile_stale"],
        profile_tags_count=stats["profile_tags_count"],
        suggested_unread=stats["suggested_unread"],
        suggested_total=stats["suggested_total"],
        last_profile_update=stats["last_profile_update"],
    )


@router.post("/admin/regenerate-profile", response_model=AdminActionResponse)
async def regenerate_profile(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Force regeneration of user interest profile.
    Requires at least MIN_LIKED_POSTS liked posts.
    """
    liked_count = get_liked_posts_count(db)

    if liked_count < MIN_LIKED_POSTS:
        return AdminActionResponse(
            success=False,
            message=f"Not enough liked posts ({liked_count}/{MIN_LIKED_POSTS})",
        )

    # Mark as stale to trigger regeneration
    invalidate_user_profile(db)

    # Generate immediately instead of waiting for scheduled job
    try:
        result = await generate_user_profile(db)
        if result:
            return AdminActionResponse(
                success=True,
                message=f"Profile regenerated with {len(result.get('tags', []))} tags",
            )
        else:
            return AdminActionResponse(
                success=False,
                message="Profile generation failed",
            )
    except Exception as e:
        logger.error(f"Error regenerating profile: {e}")
        return AdminActionResponse(
            success=False,
            message=f"Error: {str(e)}",
        )


@router.post("/admin/process-suggestions", response_model=AdminActionResponse)
async def process_suggestions(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Force processing of suggestion candidates.
    Finds posts with tag overlap and evaluates them with AI.
    """
    try:
        suggested_count = await process_suggestion_candidates(db)
        return AdminActionResponse(
            success=True,
            message=f"Processed suggestions: {suggested_count} new suggestions found",
        )
    except Exception as e:
        logger.error(f"Error processing suggestions: {e}")
        return AdminActionResponse(
            success=False,
            message=f"Error: {str(e)}",
        )
