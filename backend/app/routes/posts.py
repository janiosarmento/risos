"""
Rotas de posts.
Leitura, marcação como lido, extração de conteúdo e redirecionamento.
"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Post, Feed, Category, AISummary, SummaryQueue
from app.schemas import (
    PostResponse,
    PostDetail,
    PostListResponse,
    MarkReadRequest,
)
from app.services.content_extractor import extract_full_content
from app.services.cerebras import generate_summary, CerebrasError
from app.services.content_hasher import compute_content_hash
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/posts", tags=["posts"])


def get_summary_status(db: Session, post: Post) -> str:
    """
    Retorna status do resumo IA para um post.
    Antes da Fase 5, retorna sempre 'not_configured'.
    """
    # TODO: Fase 5 - verificar se IA está configurada
    # Por enquanto, retornar not_configured
    if not post.content_hash:
        return "not_configured"

    # Verificar se já existe resumo
    summary = db.query(AISummary).filter(
        AISummary.content_hash == post.content_hash
    ).first()
    if summary:
        return "ready"

    # Verificar se está na fila
    queue_entry = db.query(SummaryQueue).filter(
        SummaryQueue.post_id == post.id
    ).first()
    if queue_entry:
        if queue_entry.error_type == "permanent":
            return "failed"
        return "pending"

    return "not_configured"


@router.get("", response_model=PostListResponse)
def list_posts(
    feed_id: Optional[int] = Query(None, description="Filtrar por feed"),
    category_id: Optional[int] = Query(None, description="Filtrar por categoria"),
    unread_only: bool = Query(False, description="Apenas não lidos"),
    starred_only: bool = Query(False, description="Apenas favoritos"),
    limit: int = Query(20, ge=1, le=100, description="Limite de posts"),
    offset: int = Query(0, ge=0, description="Offset para paginação"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Lista posts com paginação.
    Ordenados por sort_date DESC (mais recentes primeiro).
    """
    query = db.query(Post)

    # Filtro de favoritos (ignora outros filtros se ativo)
    if starred_only:
        query = query.filter(Post.is_starred == True)
    else:
        # Filtros normais
        if feed_id is not None:
            query = query.filter(Post.feed_id == feed_id)
        elif category_id is not None:
            # Buscar feeds da categoria
            feed_ids = db.query(Feed.id).filter(Feed.category_id == category_id).subquery()
            query = query.filter(Post.feed_id.in_(feed_ids))

        if unread_only:
            query = query.filter(Post.is_read == False)

    # Contar total
    total = query.count()

    # Buscar posts ordenados
    posts = (
        query
        .order_by(Post.sort_date.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    # Buscar resumos para os posts (por content_hash)
    content_hashes = [p.content_hash for p in posts if p.content_hash]
    summaries_map = {}
    if content_hashes:
        summaries = db.query(AISummary).filter(
            AISummary.content_hash.in_(content_hashes)
        ).all()
        summaries_map = {s.content_hash: s for s in summaries}

    # Converter para response
    result = []
    for post in posts:
        summary = summaries_map.get(post.content_hash) if post.content_hash else None
        post_dict = {
            "id": post.id,
            "feed_id": post.feed_id,
            "guid": post.guid,
            "url": post.url,
            "title": post.title,
            "author": post.author,
            "content": post.content,
            "published_at": post.published_at,
            "fetched_at": post.fetched_at,
            "sort_date": post.sort_date,
            "is_read": post.is_read,
            "read_at": post.read_at,
            "is_starred": post.is_starred or False,
            "starred_at": post.starred_at,
            "summary_status": "ready" if summary else get_summary_status(db, post),
            "one_line_summary": summary.one_line_summary if summary else None,
            "translated_title": summary.translated_title if summary else None,
        }
        result.append(PostResponse(**post_dict))

    has_more = (offset + limit) < total

    return PostListResponse(posts=result, total=total, has_more=has_more)


@router.get("/{post_id}", response_model=PostDetail)
async def get_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Busca um post por ID com conteúdo completo.
    Inclui resumo IA se disponível.
    Extrai full_content sob demanda se não estiver em cache.
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    # Extrair full_content sob demanda se não estiver em cache
    full_content = post.full_content
    if not full_content and post.url:
        try:
            result = await extract_full_content(post.url)
            if result.success:
                full_content = result.content
                post.full_content = full_content
                db.commit()
        except Exception:
            pass  # Usar content original se falhar

    # Buscar ou gerar resumo IA on-demand
    summary_pt = None
    one_line_summary = None
    translated_title = None
    summary_status = "not_configured"

    # Usar full_content para o resumo, ou content como fallback
    content_for_summary = full_content or post.content

    # Calcular/atualizar content_hash se necessário
    if content_for_summary and not post.content_hash:
        post.content_hash = compute_content_hash(content_for_summary, title=post.title, url=post.url)
        db.commit()

    if post.content_hash:
        # Verificar se já existe resumo
        summary = db.query(AISummary).filter(
            AISummary.content_hash == post.content_hash
        ).first()

        if summary:
            summary_pt = summary.summary_pt
            one_line_summary = summary.one_line_summary
            translated_title = summary.translated_title
            summary_status = "ready"
        elif content_for_summary and len(content_for_summary.strip()) > 100:
            # Gerar resumo on-demand se há conteúdo suficiente
            try:
                logger.info(f"Generating on-demand summary for post {post.id}")
                result = await generate_summary(content_for_summary, title=post.title)

                # Salvar no banco
                new_summary = AISummary(
                    content_hash=post.content_hash,
                    summary_pt=result.summary_pt,
                    one_line_summary=result.one_line_summary,
                    translated_title=result.translated_title,
                )
                db.add(new_summary)
                db.commit()

                summary_pt = result.summary_pt
                one_line_summary = result.one_line_summary
                translated_title = result.translated_title
                summary_status = "ready"
                logger.info(f"Summary generated successfully for post {post.id}")

            except CerebrasError as e:
                logger.warning(f"Failed to generate summary for post {post.id}: {e}")
                summary_status = "pending"  # Temporário, pode tentar novamente
            except Exception as e:
                logger.error(f"Unexpected error generating summary for post {post.id}: {e}")
                summary_status = "failed"

    return PostDetail(
        id=post.id,
        feed_id=post.feed_id,
        guid=post.guid,
        url=post.url,
        title=post.title,
        author=post.author,
        content=post.content,
        full_content=full_content or post.content,
        published_at=post.published_at,
        fetched_at=post.fetched_at,
        sort_date=post.sort_date,
        is_read=post.is_read,
        read_at=post.read_at,
        is_starred=post.is_starred or False,
        starred_at=post.starred_at,
        summary_status=summary_status,
        summary_pt=summary_pt,
        one_line_summary=one_line_summary,
        translated_title=translated_title,
    )


@router.patch("/{post_id}/read")
def toggle_read(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Alterna status de leitura de um post.
    Se lido, marca como não lido. Se não lido, marca como lido.
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    if post.is_read:
        post.is_read = False
        post.read_at = None
    else:
        post.is_read = True
        post.read_at = datetime.utcnow()

    db.commit()

    return {"id": post_id, "is_read": post.is_read, "read_at": post.read_at}


@router.patch("/{post_id}/star")
def toggle_star(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Alterna status de favorito de um post.
    Se estrelado, remove estrela. Se não, adiciona.
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    if post.is_starred:
        post.is_starred = False
        post.starred_at = None
    else:
        post.is_starred = True
        post.starred_at = datetime.utcnow()

    db.commit()

    return {"id": post_id, "is_starred": bool(post.is_starred), "starred_at": post.starred_at}


@router.post("/mark-read")
def mark_read_batch(
    request: MarkReadRequest,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Marca múltiplos posts como lidos.
    - post_ids: lista de IDs de posts específicos
    - feed_id: marca todos os posts de um feed
    - category_id: marca todos os posts de feeds de uma categoria
    - all: marca todos os posts
    """
    now = datetime.utcnow()
    query = db.query(Post).filter(Post.is_read == False)

    if request.post_ids:
        # Marcar posts específicos por ID
        query = query.filter(Post.id.in_(request.post_ids))
    elif request.all:
        # Marcar todos
        pass
    elif request.feed_id:
        query = query.filter(Post.feed_id == request.feed_id)
    elif request.category_id:
        feed_ids = db.query(Feed.id).filter(Feed.category_id == request.category_id).subquery()
        query = query.filter(Post.feed_id.in_(feed_ids))
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Must specify post_ids, feed_id, category_id, or all=true"
        )

    count = query.update({"is_read": True, "read_at": now}, synchronize_session=False)
    db.commit()

    return {"marked_read": count}


@router.get("/{post_id}/full-content")
async def get_full_content(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Extrai conteúdo completo do artigo original.

    - Usa readability-lxml para extrair
    - Sanitiza HTML
    - Cache em posts.full_content
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    if not post.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post has no URL"
        )

    # Verificar cache
    if post.full_content:
        return {
            "id": post_id,
            "full_content": post.full_content,
            "cached": True,
        }

    # Extrair conteúdo
    result = await extract_full_content(post.url)

    if not result.success:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to extract content: {result.error}"
        )

    # Salvar no cache
    post.full_content = result.content
    db.commit()

    return {
        "id": post_id,
        "full_content": result.content,
        "cached": False,
    }


@router.get("/{post_id}/redirect")
def redirect_to_post(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Redireciona para URL original do post.

    - Marca post como lido
    - Retorna HTTP 302 para URL original
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    if not post.url:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post has no URL"
        )

    # Marcar como lido
    if not post.is_read:
        post.is_read = True
        post.read_at = datetime.utcnow()
        db.commit()

    return RedirectResponse(url=post.url, status_code=status.HTTP_302_FOUND)


@router.post("/{post_id}/regenerate-summary")
async def regenerate_summary(
    post_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Regenera o resumo IA de um post.

    - Extrai conteúdo completo se necessário
    - Gera novo resumo via Cerebras
    - Atualiza ou insere na tabela ai_summaries
    - Retorna o novo resumo
    """
    post = db.query(Post).filter(Post.id == post_id).first()
    if not post:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Post not found"
        )

    # Obter conteúdo para resumir
    content_for_summary = post.full_content or post.content

    # Se não tem conteúdo, tentar extrair
    if not content_for_summary and post.url:
        try:
            result = await extract_full_content(post.url)
            if result.success:
                content_for_summary = result.content
                post.full_content = content_for_summary
                db.commit()
        except Exception as e:
            logger.error(f"Failed to extract content for post {post_id}: {e}")

    if not content_for_summary or len(content_for_summary.strip()) < 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Post has insufficient content for summary"
        )

    # Calcular novo content_hash baseado no conteúdo atual
    new_content_hash = compute_content_hash(content_for_summary, title=post.title, url=post.url)

    # Atualizar content_hash do post se diferente
    if post.content_hash != new_content_hash:
        post.content_hash = new_content_hash
        db.commit()

    try:
        logger.info(f"Regenerating summary for post {post_id}")
        result = await generate_summary(content_for_summary, title=post.title)

        # Verificar se já existe resumo com esse hash
        existing_summary = db.query(AISummary).filter(
            AISummary.content_hash == new_content_hash
        ).first()

        if existing_summary:
            # Atualizar resumo existente
            existing_summary.summary_pt = result.summary_pt
            existing_summary.one_line_summary = result.one_line_summary
            existing_summary.translated_title = result.translated_title
            existing_summary.created_at = datetime.utcnow()
        else:
            # Criar novo resumo
            new_summary = AISummary(
                content_hash=new_content_hash,
                summary_pt=result.summary_pt,
                one_line_summary=result.one_line_summary,
                translated_title=result.translated_title,
            )
            db.add(new_summary)

        db.commit()
        logger.info(f"Summary regenerated successfully for post {post_id}")

        return {
            "success": True,
            "post_id": post_id,
            "summary_pt": result.summary_pt,
            "one_line_summary": result.one_line_summary,
            "translated_title": result.translated_title,
        }

    except CerebrasError as e:
        logger.error(f"Cerebras error regenerating summary for post {post_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI service error: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Unexpected error regenerating summary for post {post_id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to regenerate summary: {str(e)}"
        )
