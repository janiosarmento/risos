"""
Rotas de feeds.
CRUD + refresh + OPML import/export.
"""
import xml.etree.ElementTree as ET
from datetime import datetime
from io import BytesIO
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models import Feed, Post, Category
from app.schemas import FeedCreate, FeedUpdate, FeedResponse
from app.services.feed_ingestion import ingest_feed

router = APIRouter(prefix="/feeds", tags=["feeds"])


def get_hostname(url: str) -> str:
    """Extrai hostname da URL para usar como título placeholder."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


@router.get("", response_model=List[FeedResponse])
def list_feeds(
    category_id: Optional[int] = Query(None, description="Filtrar por categoria"),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Lista todos os feeds, opcionalmente filtrados por categoria."""
    # Subquery para contar posts não lidos por feed
    unread_count_subq = (
        db.query(Post.feed_id, func.count(Post.id).label("unread_count"))
        .filter(Post.is_read == False)
        .group_by(Post.feed_id)
        .subquery()
    )

    query = (
        db.query(Feed, func.coalesce(unread_count_subq.c.unread_count, 0).label("unread_count"))
        .outerjoin(unread_count_subq, Feed.id == unread_count_subq.c.feed_id)
    )

    if category_id is not None:
        query = query.filter(Feed.category_id == category_id)

    feeds = query.order_by(func.lower(Feed.title)).all()

    result = []
    for feed, unread_count in feeds:
        feed_dict = {
            "id": feed.id,
            "category_id": feed.category_id,
            "title": feed.title,
            "url": feed.url,
            "site_url": feed.site_url,
            "last_fetched_at": feed.last_fetched_at,
            "error_count": feed.error_count or 0,
            "last_error": feed.last_error,
            "disabled_at": feed.disabled_at,
            "created_at": feed.created_at,
            "unread_count": unread_count,
        }
        result.append(FeedResponse(**feed_dict))

    return result


@router.post("", response_model=FeedResponse, status_code=status.HTTP_201_CREATED)
async def create_feed(
    feed: FeedCreate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Cria um novo feed.
    Se título não fornecido, usa hostname da URL como placeholder.
    Dispara busca inicial dos posts automaticamente.
    """
    # Verificar se URL já existe
    existing = db.query(Feed).filter(Feed.url == feed.url).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Feed with this URL already exists"
        )

    # Verificar se category_id existe (se fornecido)
    if feed.category_id:
        category = db.query(Category).filter(Category.id == feed.category_id).first()
        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Category not found"
            )

    # Usar hostname como título se não fornecido
    title = feed.title if feed.title else get_hostname(feed.url)

    db_feed = Feed(
        url=feed.url,
        title=title,
        category_id=feed.category_id,
    )
    db.add(db_feed)
    db.commit()
    db.refresh(db_feed)

    # Disparar busca inicial dos posts
    try:
        await ingest_feed(db, db_feed)
        db.refresh(db_feed)
    except Exception as e:
        # Log error but don't fail the feed creation
        import logging
        logging.getLogger(__name__).error(f"Initial feed ingestion failed for {db_feed.url}: {e}")

    # Contar posts não lidos após ingestão
    unread_count = db.query(func.count(Post.id)).filter(
        Post.feed_id == db_feed.id,
        Post.is_read == False
    ).scalar() or 0

    return FeedResponse(
        id=db_feed.id,
        category_id=db_feed.category_id,
        title=db_feed.title,
        url=db_feed.url,
        site_url=db_feed.site_url,
        last_fetched_at=db_feed.last_fetched_at,
        error_count=db_feed.error_count or 0,
        last_error=db_feed.last_error,
        disabled_at=db_feed.disabled_at,
        created_at=db_feed.created_at,
        unread_count=unread_count,
    )


@router.post("/import-opml")
async def import_opml(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Importa feeds de um arquivo OPML.

    - Cria categorias se não existirem
    - Ignora feeds duplicados (por URL)
    - Retorna contagem de importados e erros
    """
    # Verificar tipo de arquivo
    if not file.filename.endswith(('.opml', '.xml')):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be .opml or .xml"
        )

    # Ler conteúdo
    content = await file.read()
    if len(content) > 1024 * 1024:  # 1MB limit
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File too large (max 1MB)"
        )

    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid XML: {e}"
        )

    imported = 0
    skipped = 0
    errors = []

    # Buscar body/outline
    body = root.find('.//body')
    if body is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OPML: no body element"
        )

    def process_outline(outline, category_id=None):
        nonlocal imported, skipped, errors

        xml_url = outline.get('xmlUrl')
        title = outline.get('title') or outline.get('text')

        if xml_url:
            # É um feed
            existing = db.query(Feed).filter(Feed.url == xml_url).first()
            if existing:
                skipped += 1
                return

            try:
                feed = Feed(
                    url=xml_url,
                    title=title or get_hostname(xml_url),
                    site_url=outline.get('htmlUrl'),
                    category_id=category_id,
                )
                db.add(feed)
                db.flush()
                imported += 1
            except Exception as e:
                errors.append(f"Error adding {xml_url}: {e}")
        else:
            # É uma categoria (folder)
            cat_name = title
            if cat_name:
                # Buscar ou criar categoria
                category = db.query(Category).filter(Category.name == cat_name).first()
                if not category:
                    category = Category(name=cat_name)
                    db.add(category)
                    db.flush()

                cat_id = category.id
            else:
                cat_id = category_id

            # Processar filhos
            for child in outline:
                process_outline(child, cat_id)

    # Processar outlines do body
    for outline in body:
        process_outline(outline)

    db.commit()

    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors,
    }


@router.get("/export-opml")
def export_opml(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Exporta todos os feeds no formato OPML.

    - Agrupa feeds por categoria
    - Feeds sem categoria ficam no nível raiz
    """
    # Criar estrutura OPML
    opml = ET.Element('opml', version='1.0')

    head = ET.SubElement(opml, 'head')
    title = ET.SubElement(head, 'title')
    title.text = 'RSS Reader Export'
    date_created = ET.SubElement(head, 'dateCreated')
    date_created.text = datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S GMT')

    body = ET.SubElement(opml, 'body')

    # Buscar categorias com feeds
    categories = db.query(Category).order_by(func.lower(Category.name)).all()

    for category in categories:
        feeds = db.query(Feed).filter(Feed.category_id == category.id).order_by(func.lower(Feed.title)).all()
        if not feeds:
            continue

        cat_outline = ET.SubElement(body, 'outline', text=category.name, title=category.name)

        for feed in feeds:
            attrs = {
                'type': 'rss',
                'text': feed.title,
                'title': feed.title,
                'xmlUrl': feed.url,
            }
            if feed.site_url:
                attrs['htmlUrl'] = feed.site_url
            ET.SubElement(cat_outline, 'outline', **attrs)

    # Feeds sem categoria
    uncategorized = db.query(Feed).filter(Feed.category_id.is_(None)).order_by(func.lower(Feed.title)).all()
    for feed in uncategorized:
        attrs = {
            'type': 'rss',
            'text': feed.title,
            'title': feed.title,
            'xmlUrl': feed.url,
        }
        if feed.site_url:
            attrs['htmlUrl'] = feed.site_url
        ET.SubElement(body, 'outline', **attrs)

    # Gerar XML
    xml_str = ET.tostring(opml, encoding='unicode', xml_declaration=True)

    return Response(
        content=xml_str,
        media_type='application/xml',
        headers={
            'Content-Disposition': 'attachment; filename="feeds.opml"'
        }
    )


@router.get("/{feed_id}", response_model=FeedResponse)
def get_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Busca um feed por ID."""
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feed not found"
        )

    unread_count = db.query(func.count(Post.id)).filter(
        Post.feed_id == feed_id,
        Post.is_read == False
    ).scalar()

    return FeedResponse(
        id=feed.id,
        category_id=feed.category_id,
        title=feed.title,
        url=feed.url,
        site_url=feed.site_url,
        last_fetched_at=feed.last_fetched_at,
        error_count=feed.error_count or 0,
        last_error=feed.last_error,
        disabled_at=feed.disabled_at,
        created_at=feed.created_at,
        unread_count=unread_count,
    )


@router.put("/{feed_id}", response_model=FeedResponse)
def update_feed(
    feed_id: int,
    feed_update: FeedUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """Atualiza um feed."""
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feed not found"
        )

    # Verificar URL duplicada (se alterada)
    if feed_update.url and feed_update.url != feed.url:
        existing = db.query(Feed).filter(Feed.url == feed_update.url).first()
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Feed with this URL already exists"
            )

    # Verificar category_id (se fornecido)
    if feed_update.category_id is not None:
        if feed_update.category_id != 0:  # 0 significa remover categoria
            category = db.query(Category).filter(Category.id == feed_update.category_id).first()
            if not category:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Category not found"
                )

    # Atualizar campos
    if feed_update.title is not None:
        feed.title = feed_update.title
    if feed_update.url is not None:
        feed.url = feed_update.url
    if feed_update.category_id is not None:
        feed.category_id = feed_update.category_id if feed_update.category_id != 0 else None

    db.commit()
    db.refresh(feed)

    unread_count = db.query(func.count(Post.id)).filter(
        Post.feed_id == feed_id,
        Post.is_read == False
    ).scalar()

    return FeedResponse(
        id=feed.id,
        category_id=feed.category_id,
        title=feed.title,
        url=feed.url,
        site_url=feed.site_url,
        last_fetched_at=feed.last_fetched_at,
        error_count=feed.error_count or 0,
        last_error=feed.last_error,
        disabled_at=feed.disabled_at,
        created_at=feed.created_at,
        unread_count=unread_count,
    )


@router.delete("/{feed_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Deleta um feed.
    Posts do feed são removidos em cascata.
    """
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feed not found"
        )

    db.delete(feed)
    db.commit()

    return None


@router.post("/{feed_id}/refresh")
async def refresh_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Busca e ingere novos posts de um feed.

    Retorna estatísticas da ingestão:
    - new_posts: Número de posts novos inseridos
    - skipped_duplicates: Posts ignorados por duplicidade
    - errors: Lista de erros (se houver)
    """
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feed not found"
        )

    if feed.disabled_at:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feed is disabled"
        )

    result = await ingest_feed(db, feed)

    return {
        "feed_id": feed_id,
        "new_posts": result.new_posts,
        "skipped_duplicates": result.skipped_duplicates,
        "errors": result.errors,
        "feed_title_updated": result.feed_title_updated,
        "site_url_updated": result.site_url_updated,
    }


@router.post("/{feed_id}/enable")
def enable_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user)
):
    """
    Reativa um feed desativado.
    Reseta error_count, disabled_at e next_retry_at.
    """
    feed = db.query(Feed).filter(Feed.id == feed_id).first()
    if not feed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Feed not found"
        )

    feed.error_count = 0
    feed.disabled_at = None
    feed.disable_reason = None
    feed.next_retry_at = None
    feed.last_error = None

    db.commit()

    return {"ok": True, "feed_id": feed_id}
