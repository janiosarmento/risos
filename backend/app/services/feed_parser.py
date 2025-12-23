"""
Parser de feeds RSS/Atom.
Usa feedparser + httpx para fetch e parse.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List, Tuple
from urllib.parse import urlparse

import feedparser
import httpx

logger = logging.getLogger(__name__)

# Configurações
USER_AGENT = "RSSReader/1.0"
TIMEOUT_SECONDS = 10
MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10MB
MAX_REDIRECTS = 3


@dataclass
class ParsedEntry:
    """Entrada parseada de um feed."""
    guid: Optional[str]
    url: Optional[str]
    title: Optional[str]
    author: Optional[str]
    content: Optional[str]
    published_at: Optional[datetime]


@dataclass
class ParsedFeed:
    """Feed parseado."""
    title: Optional[str]
    site_url: Optional[str]
    entries: List[ParsedEntry]


class FeedParseError(Exception):
    """Erro ao parsear feed."""
    pass


class FeedFetchError(Exception):
    """Erro ao buscar feed."""
    pass


def _parse_date(entry: dict) -> Optional[datetime]:
    """Extrai data de publicação de uma entrada."""
    # feedparser converte para struct_time em published_parsed ou updated_parsed
    for field in ['published_parsed', 'updated_parsed', 'created_parsed']:
        parsed = entry.get(field)
        if parsed:
            try:
                return datetime(*parsed[:6])
            except (TypeError, ValueError):
                continue
    return None


def _extract_content(entry: dict) -> Optional[str]:
    """Extrai conteúdo de uma entrada (content ou summary)."""
    # Tentar content primeiro (geralmente mais completo)
    if 'content' in entry and entry['content']:
        contents = entry['content']
        if isinstance(contents, list) and contents:
            # Preferir text/html
            for c in contents:
                if c.get('type') == 'text/html':
                    return c.get('value', '')
            # Fallback para primeiro content
            return contents[0].get('value', '')

    # Fallback para summary
    if 'summary' in entry:
        return entry['summary']

    # Fallback para description
    if 'description' in entry:
        return entry['description']

    return None


def _is_same_domain(url1: str, url2: str) -> bool:
    """Verifica se duas URLs são do mesmo domínio."""
    try:
        parsed1 = urlparse(url1)
        parsed2 = urlparse(url2)
        return parsed1.netloc.lower() == parsed2.netloc.lower()
    except Exception:
        return False


def _is_http_to_https(original: str, redirect: str) -> bool:
    """Verifica se é um redirect de http para https."""
    try:
        parsed_orig = urlparse(original)
        parsed_redir = urlparse(redirect)
        return (
            parsed_orig.scheme == 'http' and
            parsed_redir.scheme == 'https' and
            parsed_orig.netloc.lower() == parsed_redir.netloc.lower()
        )
    except Exception:
        return False


async def fetch_feed_content(url: str) -> Tuple[bytes, Optional[str]]:
    """
    Busca conteúdo do feed via HTTP.

    Returns:
        Tuple de (conteúdo em bytes, URL final após redirects)

    Raises:
        FeedFetchError: Se não conseguir buscar o feed
    """
    final_url = url
    redirects_followed = 0

    async with httpx.AsyncClient(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=False,  # Controle manual de redirects
    ) as client:
        current_url = url

        while redirects_followed <= MAX_REDIRECTS:
            try:
                response = await client.get(
                    current_url,
                    headers={"User-Agent": USER_AGENT},
                )

                # Verificar redirect
                if response.status_code in (301, 302, 303, 307, 308):
                    redirect_url = response.headers.get('location')
                    if not redirect_url:
                        raise FeedFetchError("Redirect sem header Location")

                    # Validar redirect
                    is_safe = (
                        _is_http_to_https(current_url, redirect_url) or
                        _is_same_domain(current_url, redirect_url)
                    )

                    if not is_safe:
                        logger.warning(
                            f"Redirect para domínio diferente: {current_url} -> {redirect_url}"
                        )

                    if response.status_code == 301:
                        logger.info(
                            f"Redirect permanente (301): {current_url} -> {redirect_url}. "
                            "Considere atualizar a URL do feed manualmente."
                        )

                    current_url = redirect_url
                    final_url = redirect_url
                    redirects_followed += 1
                    continue

                # Verificar status
                if response.status_code >= 400:
                    raise FeedFetchError(
                        f"HTTP {response.status_code}: {response.reason_phrase}"
                    )

                # Verificar tamanho via streaming
                content_length = response.headers.get('content-length')
                if content_length and int(content_length) > MAX_SIZE_BYTES:
                    raise FeedFetchError(
                        f"Feed muito grande: {int(content_length)} bytes (max: {MAX_SIZE_BYTES})"
                    )

                # Ler conteúdo com limite
                content = b""
                async for chunk in response.aiter_bytes():
                    content += chunk
                    if len(content) > MAX_SIZE_BYTES:
                        raise FeedFetchError(
                            f"Feed muito grande: > {MAX_SIZE_BYTES} bytes"
                        )

                return content, final_url if final_url != url else None

            except httpx.TimeoutException:
                raise FeedFetchError(f"Timeout após {TIMEOUT_SECONDS}s")
            except httpx.RequestError as e:
                raise FeedFetchError(f"Erro de conexão: {e}")

        raise FeedFetchError(f"Muitos redirects (> {MAX_REDIRECTS})")


def parse_feed_content(content: bytes) -> ParsedFeed:
    """
    Parseia conteúdo de feed RSS/Atom.

    Args:
        content: Bytes do feed XML

    Returns:
        ParsedFeed com entries

    Raises:
        FeedParseError: Se não conseguir parsear
    """
    try:
        feed = feedparser.parse(content)
    except Exception as e:
        raise FeedParseError(f"Erro ao parsear XML: {e}")

    # Verificar se teve erro de parse
    if feed.bozo and not feed.entries:
        bozo_exception = getattr(feed, 'bozo_exception', None)
        raise FeedParseError(f"Feed XML inválido: {bozo_exception}")

    # Extrair metadados do feed
    feed_title = feed.feed.get('title')
    site_url = feed.feed.get('link')

    # Parsear entries
    entries = []
    for entry in feed.entries:
        parsed_entry = ParsedEntry(
            guid=entry.get('id') or entry.get('guid'),
            url=entry.get('link'),
            title=entry.get('title'),
            author=entry.get('author'),
            content=_extract_content(entry),
            published_at=_parse_date(entry),
        )
        entries.append(parsed_entry)

    return ParsedFeed(
        title=feed_title,
        site_url=site_url,
        entries=entries,
    )


async def fetch_and_parse(url: str) -> Tuple[ParsedFeed, Optional[str]]:
    """
    Busca e parseia um feed.

    Args:
        url: URL do feed

    Returns:
        Tuple de (ParsedFeed, URL final se houve redirect)

    Raises:
        FeedFetchError: Se não conseguir buscar
        FeedParseError: Se não conseguir parsear
    """
    content, final_url = await fetch_feed_content(url)
    parsed = parse_feed_content(content)
    return parsed, final_url
