"""
Serviço de ingestão de feeds.
Integra parser, normalização, sanitização e deduplicação.
"""
import logging
from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.models import Feed, Post, SummaryQueue
from app.services.feed_parser import (
    fetch_and_parse,
    ParsedFeed,
    ParsedEntry,
    FeedFetchError,
    FeedParseError,
)
from app.services.url_normalizer import normalize_url
from app.services.html_sanitizer import sanitize_html
from app.services.content_hasher import compute_content_hash

logger = logging.getLogger(__name__)


class FeedIngestionResult:
    """Resultado da ingestão de um feed."""

    def __init__(self):
        self.new_posts = 0
        self.skipped_duplicates = 0
        self.errors = []
        self.feed_title_updated = False
        self.site_url_updated = False


def _check_duplicate_by_guid(
    db: Session,
    feed: Feed,
    guid: str,
    normalized_url: Optional[str]
) -> Tuple[bool, bool]:
    """
    Verifica duplicidade por GUID.

    Returns:
        Tuple de (é_duplicado, houve_colisão)
    """
    if not guid or feed.guid_unreliable:
        return False, False

    existing = db.query(Post).filter(
        Post.feed_id == feed.id,
        Post.guid == guid
    ).first()

    if not existing:
        return False, False

    # Verificar colisão (mesmo GUID, URL diferente)
    collision = (
        normalized_url and
        existing.normalized_url and
        existing.normalized_url != normalized_url
    )

    return True, collision


def _check_duplicate_by_url(
    db: Session,
    feed: Feed,
    normalized_url: Optional[str]
) -> bool:
    """Verifica duplicidade por URL normalizada."""
    if not normalized_url or feed.allow_duplicate_urls:
        return False

    existing = db.query(Post).filter(
        Post.feed_id == feed.id,
        Post.normalized_url == normalized_url
    ).first()

    return existing is not None


def _check_duplicate_by_hash(
    db: Session,
    feed: Feed,
    content_hash: Optional[str],
    has_guid: bool,
    has_url: bool
) -> bool:
    """
    Verifica duplicidade por content_hash.
    Só usado como fallback quando GUID e URL são None.
    """
    if not content_hash:
        return False

    # Só usar hash como fallback se não tem GUID nem URL
    if has_guid or has_url:
        return False

    existing = db.query(Post).filter(
        Post.feed_id == feed.id,
        Post.content_hash == content_hash
    ).first()

    return existing is not None


def _process_entry(
    db: Session,
    feed: Feed,
    entry: ParsedEntry,
    now: datetime
) -> Tuple[Optional[Post], Optional[str]]:
    """
    Processa uma entrada do feed.

    Returns:
        Tuple de (Post criado ou None, erro ou None)
    """
    # Normalizar URL
    normalized_url = normalize_url(entry.url)

    # Sanitizar conteúdo
    content = sanitize_html(entry.content, truncate=True)

    # Calcular hash
    content_hash = compute_content_hash(entry.content)

    # Verificar duplicidade por GUID
    is_dup, collision = _check_duplicate_by_guid(
        db, feed, entry.guid, normalized_url
    )

    if collision:
        feed.guid_collision_count = (feed.guid_collision_count or 0) + 1
        if feed.guid_collision_count >= 3:
            feed.guid_unreliable = True
            logger.warning(
                f"Feed {feed.id} marcado como guid_unreliable "
                f"(colisões: {feed.guid_collision_count})"
            )

    if is_dup:
        return None, None

    # Verificar duplicidade por URL
    if _check_duplicate_by_url(db, feed, normalized_url):
        return None, None

    # Verificar duplicidade por hash (fallback)
    if _check_duplicate_by_hash(
        db, feed, content_hash,
        has_guid=bool(entry.guid),
        has_url=bool(normalized_url)
    ):
        return None, None

    # Criar post
    sort_date = entry.published_at or now

    post = Post(
        feed_id=feed.id,
        guid=entry.guid,
        url=entry.url,
        normalized_url=normalized_url,
        title=entry.title,
        author=entry.author,
        content=content,
        content_hash=content_hash,
        published_at=entry.published_at,
        fetched_at=now,
        sort_date=sort_date,
        is_read=False,
    )

    return post, None


async def ingest_feed(db: Session, feed: Feed) -> FeedIngestionResult:
    """
    Ingere um feed: busca, parseia, e insere novos posts.

    Args:
        db: Sessão do banco
        feed: Feed a ser ingerido

    Returns:
        FeedIngestionResult com estatísticas
    """
    result = FeedIngestionResult()
    now = datetime.utcnow()

    try:
        # Buscar e parsear
        parsed_feed, final_url = await fetch_and_parse(feed.url)

    except (FeedFetchError, FeedParseError) as e:
        result.errors.append(str(e))
        feed.error_count = (feed.error_count or 0) + 1
        feed.last_error = str(e)
        feed.last_error_at = now
        db.commit()
        return result

    # Atualizar metadados do feed
    if parsed_feed.title and not feed.title.startswith(feed.url):
        # Só atualizar se era placeholder (hostname)
        if '.' in feed.title and '/' not in feed.title:
            feed.title = parsed_feed.title
            result.feed_title_updated = True

    if parsed_feed.site_url and not feed.site_url:
        feed.site_url = parsed_feed.site_url
        result.site_url_updated = True

    # Processar entries
    for entry in parsed_feed.entries:
        try:
            post, error = _process_entry(db, feed, entry, now)

            if error:
                result.errors.append(error)
                continue

            if post:
                db.add(post)
                db.flush()  # Gerar ID do post

                # Adicionar à fila de resumos (se tiver content_hash)
                if post.content_hash:
                    queue_entry = SummaryQueue(
                        post_id=post.id,
                        content_hash=post.content_hash,
                        priority=0,  # Background priority
                    )
                    db.add(queue_entry)

                result.new_posts += 1
            else:
                result.skipped_duplicates += 1

        except Exception as e:
            logger.error(f"Erro ao processar entry: {e}")
            result.errors.append(str(e))

    # Atualizar feed
    feed.last_fetched_at = now
    feed.error_count = 0  # Reset em sucesso
    feed.last_error = None

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        result.errors.append(f"Erro ao salvar: {e}")
        logger.error(f"Erro ao salvar posts do feed {feed.id}: {e}")

    logger.info(
        f"Feed {feed.id} ingerido: "
        f"{result.new_posts} novos, "
        f"{result.skipped_duplicates} duplicados"
    )

    return result
