"""
Rotas administrativas.
Reprocessamento de resumos e manutenção do banco.
"""
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import SummaryQueue, SummaryFailure, AISummary, Post

router = APIRouter(prefix="/admin", tags=["admin"])


class ReprocessRequest(BaseModel):
    content_hash: str


@router.post("/reprocess-summary")
def reprocess_summary(
    request: ReprocessRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Reinsere um resumo na fila de processamento.

    - Busca post pelo content_hash
    - Remove de summary_failures se existir
    - Remove resumo existente de ai_summaries
    - Cria entrada na summary_queue
    """
    content_hash = request.content_hash

    # Buscar post com este hash
    post = db.query(Post).filter(Post.content_hash == content_hash).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No post found with this content_hash"
        )

    # Verificar se já está na fila
    existing_queue = db.query(SummaryQueue).filter(
        SummaryQueue.content_hash == content_hash
    ).first()
    if existing_queue:
        # Reset da entrada existente
        existing_queue.attempts = 0
        existing_queue.last_error = None
        existing_queue.error_type = None
        existing_queue.locked_at = None
        existing_queue.cooldown_until = None
        existing_queue.priority = 10  # Alta prioridade
        db.commit()
        return {"ok": True, "queued": True, "action": "reset_existing"}

    # Remover de failures se existir
    db.query(SummaryFailure).filter(
        SummaryFailure.content_hash == content_hash
    ).delete()

    # Remover resumo existente (forçar reprocessamento)
    db.query(AISummary).filter(
        AISummary.content_hash == content_hash
    ).delete()

    # Criar entrada na fila
    queue_entry = SummaryQueue(
        post_id=post.id,
        content_hash=content_hash,
        priority=10,  # Alta prioridade
    )
    db.add(queue_entry)
    db.commit()

    return {"ok": True, "queued": True, "action": "created_new"}


@router.post("/vacuum")
def vacuum_database(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Executa VACUUM no banco SQLite.

    - Libera espaço de páginas não utilizadas
    - Retorna bytes liberados
    """
    db_path = settings.database_path

    # Obter tamanho antes
    size_before = os.path.getsize(db_path) if os.path.exists(db_path) else 0

    # Executar VACUUM (precisa estar fora de transação)
    # SQLAlchemy 2.x requer commit antes
    db.commit()

    # VACUUM não pode ser executado dentro de transação
    connection = db.get_bind().raw_connection()
    try:
        connection.execute("VACUUM")
    finally:
        connection.close()

    # Obter tamanho depois
    size_after = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    freed_bytes = size_before - size_after

    return {
        "ok": True,
        "size_before_mb": round(size_before / (1024 * 1024), 2),
        "size_after_mb": round(size_after / (1024 * 1024), 2),
        "freed_bytes": max(0, freed_bytes),
        "freed_mb": round(max(0, freed_bytes) / (1024 * 1024), 2),
    }


@router.get("/config")
def get_public_config():
    """
    Retorna configurações públicas para o frontend.
    Não requer autenticação.
    """
    return {
        "toast_timeout_seconds": settings.toast_timeout_seconds,
    }


@router.get("/status")
def get_status(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Retorna status detalhado do sistema.

    Inclui contadores, tamanho do banco, estado do circuit breaker, etc.
    """
    from app.models import Feed, Post, AppSettings

    # Contadores
    feeds_count = db.query(Feed).count()
    posts_count = db.query(Post).count()
    unread_count = db.query(Post).filter(Post.is_read == False).count()
    queue_size = db.query(SummaryQueue).count()
    summaries_count = db.query(AISummary).count()
    failures_count = db.query(SummaryFailure).count()

    # Tamanho do banco
    db_path = settings.database_path
    db_size_mb = round(os.path.getsize(db_path) / (1024 * 1024), 2) if os.path.exists(db_path) else 0

    # Circuit breaker
    circuit_state = "unknown"
    health_warning = None

    for row in db.query(AppSettings).filter(
        AppSettings.key.in_(['cerebras_state', 'health_warning'])
    ).all():
        if row.key == 'cerebras_state':
            circuit_state = row.value
        elif row.key == 'health_warning':
            health_warning = row.value

    return {
        "feeds_count": feeds_count,
        "posts_count": posts_count,
        "unread_count": unread_count,
        "queue_size": queue_size,
        "summaries_count": summaries_count,
        "failures_count": failures_count,
        "circuit_breaker": circuit_state,
        "health_warning": health_warning,
        "db_size_mb": db_size_mb,
    }
