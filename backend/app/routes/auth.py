"""
Authentication routes.
Single-user with password configured via .env
Uses httpOnly session cookie instead of JWT.
"""

import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from starlette.responses import JSONResponse
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import UserSession
from app.schemas import LoginRequest, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_MAX_AGE = 60 * 60 * 24 * 90  # 90 days


@router.post("/login")
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with password, create session, set httpOnly cookie.
    Uses constant-time comparison to prevent timing attacks.
    """
    password_valid = secrets.compare_digest(
        request.password.encode("utf-8"), settings.app_password.encode("utf-8")
    )

    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    # Create session
    session_id = str(uuid.uuid4())
    session = UserSession(
        id=session_id,
        expires_at=datetime.utcnow() + timedelta(hours=settings.session_ttl_hours),
    )
    db.add(session)
    db.commit()

    response = JSONResponse({"success": True})
    response.set_cookie(
        key="risos_session",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=False,  # Allow HTTP for local dev — reverse proxy handles HTTPS
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    return response


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    """
    Delete session from DB and clear cookie.
    Works regardless of session validity (no auth required).
    """
    session_id = request.cookies.get("risos_session")
    if session_id:
        db.query(UserSession).filter(UserSession.id == session_id).delete()
        db.commit()

    response = JSONResponse({"message": "Successfully logged out"})
    response.delete_cookie(key="risos_session", path="/")
    return response


@router.get("/me", response_model=UserInfo)
def get_me(user: dict = Depends(get_current_user)):
    """Return authentication status."""
    return UserInfo(authenticated=user["authenticated"])
