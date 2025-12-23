"""
Dependencies para injeção no FastAPI.
Inclui autenticação JWT.
"""
from datetime import datetime

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import TokenBlacklist

# Esquema de autenticação Bearer
security = HTTPBearer()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> dict:
    """
    Valida token JWT e retorna informações do usuário.
    Verifica:
    - Token válido
    - Token não expirado
    - Token não está na blacklist
    """
    token = credentials.credentials

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"]
        )
        jti: str = payload.get("jti")
        exp: int = payload.get("exp")

        if jti is None:
            raise credentials_exception

        # Verificar se token está na blacklist
        blacklisted = db.query(TokenBlacklist).filter(
            TokenBlacklist.jti == jti
        ).first()

        if blacklisted:
            raise credentials_exception

        # Verificar expiração (jose já faz isso, mas double-check)
        if exp and datetime.utcnow().timestamp() > exp:
            raise credentials_exception

        return {"jti": jti, "authenticated": True}

    except JWTError:
        raise credentials_exception
