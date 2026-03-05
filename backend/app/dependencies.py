"""
Dependencies for FastAPI injection.
Includes JWT authentication.
"""

from datetime import datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import TokenBlacklist

# Bearer authentication scheme
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
) -> dict:
    """
    Validate JWT token and return user info.
    Checks:
    - Valid token
    - Token not expired
    - Token not in blacklist
    """
    token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        jti: str = payload.get("jti")
        exp: int = payload.get("exp")

        if jti is None:
            raise credentials_exception

        # Check if token is in blacklist
        blacklisted = (
            db.query(TokenBlacklist).filter(TokenBlacklist.jti == jti).first()
        )

        if blacklisted:
            raise credentials_exception

        # Check expiration (jose already does this, but double-check)
        if exp and datetime.utcnow().timestamp() > exp:
            raise credentials_exception

        return {"jti": jti, "authenticated": True}

    except JWTError:
        raise credentials_exception
