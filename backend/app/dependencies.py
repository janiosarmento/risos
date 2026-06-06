"""
Dependencies for FastAPI injection.
Authenticates via httpOnly session cookie.
"""

from datetime import datetime, timedelta

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import UserSession


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """
    Validates session cookie and returns user info.
    Slides the expiry window on each request.
    """
    session_id = request.cookies.get("risos_session")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
    )

    if not session_id:
        raise credentials_exception

    session = (
        db.query(UserSession)
        .filter(UserSession.id == session_id)
        .first()
    )

    if not session:
        raise credentials_exception

    # Check expiry
    if session.expires_at < datetime.utcnow():
        db.delete(session)
        db.commit()
        raise credentials_exception

    # Sliding window: extend expiry
    session.expires_at = datetime.utcnow() + timedelta(hours=settings.session_ttl_hours)
    db.commit()

    return {"authenticated": True}
