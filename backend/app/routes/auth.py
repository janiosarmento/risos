"""
Authentication routes.
Single-user with password configured via .env
"""

import secrets
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import TokenBlacklist
from app.schemas import LoginRequest, LoginResponse, UserInfo

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """
    Authenticate with password and return JWT token.
    Uses constant-time comparison to prevent timing attacks.
    """
    # Constant-time comparison
    password_valid = secrets.compare_digest(
        request.password.encode("utf-8"), settings.app_password.encode("utf-8")
    )

    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Generate JWT token
    jti = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(
        hours=settings.jwt_expiration_hours
    )

    payload = {
        "jti": jti,
        "exp": expires_at,
        "iat": datetime.utcnow(),
    }

    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

    return LoginResponse(token=token, expires_at=expires_at)


@router.post("/logout")
def logout(
    user: dict = Depends(get_current_user), db: Session = Depends(get_db)
):
    """
    Invalidate token by adding jti to blacklist.
    """
    jti = user["jti"]

    # Get token expiration
    # (token is still valid at this point, so we can trust the user's jti)
    # Calculate expires_at based on config
    expires_at = datetime.utcnow() + timedelta(
        hours=settings.jwt_expiration_hours
    )

    # Add to blacklist
    blacklist_entry = TokenBlacklist(jti=jti, expires_at=expires_at)
    db.add(blacklist_entry)
    db.commit()

    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserInfo)
def get_me(user: dict = Depends(get_current_user)):
    """
    Return user authentication status.
    """
    return UserInfo(authenticated=user["authenticated"])
