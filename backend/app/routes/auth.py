"""
Rotas de autenticação.
Single-user com senha configurada via .env
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
    Autentica com senha e retorna token JWT.
    Usa comparação em tempo constante para evitar timing attacks.
    """
    # Comparação em tempo constante
    password_valid = secrets.compare_digest(
        request.password.encode("utf-8"),
        settings.app_password.encode("utf-8")
    )

    if not password_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Gerar token JWT
    jti = str(uuid.uuid4())
    expires_at = datetime.utcnow() + timedelta(hours=settings.jwt_expiration_hours)

    payload = {
        "jti": jti,
        "exp": expires_at,
        "iat": datetime.utcnow(),
    }

    token = jwt.encode(payload, settings.jwt_secret, algorithm="HS256")

    return LoginResponse(token=token, expires_at=expires_at)


@router.post("/logout")
def logout(
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Invalida token adicionando jti à blacklist.
    """
    jti = user["jti"]

    # Decodificar token para pegar expiração
    # (o token ainda é válido neste ponto, então podemos confiar no jti do user)
    # Calcular expires_at baseado na configuração
    expires_at = datetime.utcnow() + timedelta(hours=settings.jwt_expiration_hours)

    # Adicionar à blacklist
    blacklist_entry = TokenBlacklist(jti=jti, expires_at=expires_at)
    db.add(blacklist_entry)
    db.commit()

    return {"message": "Successfully logged out"}


@router.get("/me", response_model=UserInfo)
def get_me(user: dict = Depends(get_current_user)):
    """
    Retorna status de autenticação do usuário.
    """
    return UserInfo(authenticated=user["authenticated"])
