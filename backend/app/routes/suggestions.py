"""
Routes for the AI suggestion system.
Includes status endpoint and admin controls.
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.routes.auth import get_current_user
from app.services.suggestions import (
    clear_all_suggestions,
    process_suggestion_candidates,
)
from app.services.user_profile import (
    MIN_LIKED_POSTS,
    generate_user_profile,
    get_liked_posts_count,
    invalidate_user_profile,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/suggestions", tags=["suggestions"])


class AdminActionResponse(BaseModel):
    """Response for admin actions."""

    success: bool
    message: str


@router.post("/admin/regenerate-profile", response_model=AdminActionResponse)
def regenerate_profile(
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
        result = generate_user_profile(db)
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
def process_suggestions(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Force processing of suggestion candidates.
    Resets existing suggestions so they are re-scored, then finds posts
    with tag overlap and scores them by overlap percentage.
    """
    try:
        # Clear existing suggestions so they get re-evaluated
        clear_all_suggestions(db)

        suggested_count = process_suggestion_candidates(db)
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
