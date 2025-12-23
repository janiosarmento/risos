"""
Sanitização de HTML para conteúdo de posts.
Remove scripts, event handlers e URLs perigosas.
"""
import re
from typing import Optional
from urllib.parse import urlparse

import bleach

# Tags permitidas
ALLOWED_TAGS = [
    'p', 'br', 'hr',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li',
    'blockquote', 'pre', 'code',
    'a', 'img',
    'strong', 'b', 'em', 'i', 'u', 's', 'strike', 'del', 'ins',
    'table', 'thead', 'tbody', 'tr', 'th', 'td',
    'figure', 'figcaption',
    'div', 'span',
    'sub', 'sup',
]

# Atributos permitidos por tag
ALLOWED_ATTRIBUTES = {
    '*': ['class', 'id'],
    'a': ['href', 'title', 'rel', 'target'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
    'td': ['colspan', 'rowspan'],
    'th': ['colspan', 'rowspan'],
}

# Comprimento máximo para content (resumo)
MAX_CONTENT_LENGTH = 500


def _is_safe_href(url: str) -> bool:
    """
    Verifica se href é seguro.
    Apenas http:// e https:// são permitidos.
    """
    if not url:
        return False

    url_lower = url.lower().strip()

    # Bloquear protocolos perigosos
    dangerous_prefixes = [
        'javascript:',
        'data:',
        'vbscript:',
        'file:',
        'about:',
    ]

    for prefix in dangerous_prefixes:
        if url_lower.startswith(prefix):
            return False

    # Permitir URLs relativas
    if url.startswith('/') or url.startswith('#'):
        return True

    # Permitir apenas http e https
    try:
        parsed = urlparse(url)
        return parsed.scheme in ('http', 'https', '')
    except Exception:
        return False


def _is_safe_img_src(url: str) -> bool:
    """
    Verifica se src de imagem é seguro.
    Apenas https:// e data: (para imagens inline) são permitidos.
    http:// é bloqueado para evitar mixed content.
    """
    if not url:
        return False

    url_lower = url.lower().strip()

    # Bloquear http (inseguro para imagens)
    if url_lower.startswith('http://'):
        return False

    # Permitir data: apenas para imagens
    if url_lower.startswith('data:image/'):
        return True

    # Bloquear outros data:
    if url_lower.startswith('data:'):
        return False

    # Bloquear protocolos perigosos
    dangerous_prefixes = [
        'javascript:',
        'vbscript:',
        'file:',
    ]

    for prefix in dangerous_prefixes:
        if url_lower.startswith(prefix):
            return False

    # Permitir https e URLs relativas
    try:
        parsed = urlparse(url)
        return parsed.scheme in ('https', '')
    except Exception:
        return False


def _filter_attributes(tag: str, name: str, value: str) -> bool:
    """
    Filtro customizado para atributos.
    Valida URLs em href e src.
    """
    # Verificar se atributo é permitido
    allowed = ALLOWED_ATTRIBUTES.get(tag, [])
    global_allowed = ALLOWED_ATTRIBUTES.get('*', [])

    if name not in allowed and name not in global_allowed:
        return False

    # Validar href
    if name == 'href':
        return _is_safe_href(value)

    # Validar src
    if name == 'src':
        return _is_safe_img_src(value)

    return True


def _add_link_attributes(attrs, new=False):
    """
    Callback para adicionar rel e target em links.
    """
    # Adicionar/sobrescrever rel e target
    attrs[(None, 'rel')] = 'noopener noreferrer'
    attrs[(None, 'target')] = '_blank'
    return attrs


def sanitize_html(html: Optional[str], truncate: bool = True) -> Optional[str]:
    """
    Sanitiza HTML removendo conteúdo perigoso.

    Regras:
    - Remove tags não permitidas
    - Remove event handlers (onclick, onerror, etc.)
    - Remove javascript:, data: (exceto imagens), vbscript:
    - Remove http:// em src de imagens (mixed content)
    - Adiciona rel="noopener noreferrer" target="_blank" em links
    - Trunca para MAX_CONTENT_LENGTH se truncate=True

    Args:
        html: HTML para sanitizar
        truncate: Se True, trunca para MAX_CONTENT_LENGTH

    Returns:
        HTML sanitizado ou None se vazio
    """
    if not html:
        return None

    # Primeira passada: remover scripts e styles
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # Remover comentários HTML
    html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)

    # Sanitizar com bleach
    cleaner = bleach.Cleaner(
        tags=ALLOWED_TAGS,
        attributes=_filter_attributes,
        strip=True,
        strip_comments=True,
    )

    sanitized = cleaner.clean(html)

    # Adicionar rel e target em links usando linkify com callback
    # Primeiro, vamos processar os links existentes manualmente
    def fix_links(match):
        tag = match.group(0)
        # Remover rel e target existentes
        tag = re.sub(r'\s+rel="[^"]*"', '', tag)
        tag = re.sub(r'\s+target="[^"]*"', '', tag)
        # Adicionar novos
        tag = tag.replace('<a ', '<a rel="noopener noreferrer" target="_blank" ')
        return tag

    sanitized = re.sub(r'<a\s[^>]*>', fix_links, sanitized)

    # Truncar se necessário
    if truncate and len(sanitized) > MAX_CONTENT_LENGTH:
        # Tentar truncar em um ponto seguro (não no meio de uma tag)
        truncated = sanitized[:MAX_CONTENT_LENGTH]

        # Fechar tags abertas (simplificado)
        # Remover última tag incompleta
        last_lt = truncated.rfind('<')
        last_gt = truncated.rfind('>')
        if last_lt > last_gt:
            truncated = truncated[:last_lt]

        sanitized = truncated + '...'

    # Limpar whitespace excessivo
    sanitized = re.sub(r'\s+', ' ', sanitized).strip()

    return sanitized if sanitized else None


def extract_text(html: Optional[str]) -> Optional[str]:
    """
    Extrai texto puro do HTML (remove todas as tags).

    Args:
        html: HTML para extrair texto

    Returns:
        Texto puro ou None se vazio
    """
    if not html:
        return None

    # Remover todas as tags
    text = bleach.clean(html, tags=[], strip=True)

    # Limpar whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text if text else None
