"""
Authentication routes.
Single-user with password configured via .env
Uses httpOnly session cookie instead of JWT.
"""

import json
import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import AppSettings, UserSession
from app.password import (
    MIN_PASSWORD_LENGTH,
    PASSWORD_HASH_KEY,
    hash_password,
    verify_hash,
)
from app.rate_limiter import limiter
from app.schemas import ChangePasswordRequest, LoginRequest, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])

COOKIE_MAX_AGE = 60 * 60 * 24 * 90  # 90 days

def verify_password(db: Session, password: str) -> bool:
    """Check against the stored hash if one was set, else the env password."""
    row = db.query(AppSettings).filter(AppSettings.key == PASSWORD_HASH_KEY).first()
    if row:
        return verify_hash(password, row.value)
    return secrets.compare_digest(
        password.encode("utf-8"), settings.app_password.encode("utf-8")
    )


@router.post("/login")
@limiter.limit(f"{settings.login_rate_limit}/minute")
def login(request: Request, credentials: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with password, create session, set httpOnly cookie.
    Uses constant-time comparison to prevent timing attacks.
    Rate limited per IP to prevent brute force.
    """
    if not verify_password(db, credentials.password):
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

    response = Response(content=json.dumps({"success": True}), media_type="application/json")
    response.set_cookie(
        key="risos_session",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,  # True in production; set COOKIE_SECURE=false for local HTTP dev
        max_age=COOKIE_MAX_AGE,
        path="/",
    )
    return response


@router.post("/change-password")
@limiter.limit(f"{settings.login_rate_limit}/minute")
def change_password(
    request: Request,
    payload: ChangePasswordRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Change the app password. Requires the current one, and signs out every
    other session so a leaked cookie does not survive the change.
    """
    if not verify_password(db, payload.current_password):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Current password is incorrect",
        )
    if len(payload.new_password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"New password must be at least {MIN_PASSWORD_LENGTH} characters",
        )

    new_hash = hash_password(payload.new_password)
    row = db.query(AppSettings).filter(AppSettings.key == PASSWORD_HASH_KEY).first()
    if row:
        row.value = new_hash
    else:
        db.add(AppSettings(key=PASSWORD_HASH_KEY, value=new_hash))

    current_session_id = request.cookies.get("risos_session")
    db.query(UserSession).filter(UserSession.id != current_session_id).delete()
    db.commit()
    return {"success": True}


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

    response = Response(content=json.dumps({"message": "Successfully logged out"}), media_type="application/json")
    response.delete_cookie(key="risos_session", path="/")
    return response


@router.get("/me", response_model=UserInfo)
def get_me(user: dict = Depends(get_current_user)):
    """Return authentication status."""
    return UserInfo(authenticated=user["authenticated"])
