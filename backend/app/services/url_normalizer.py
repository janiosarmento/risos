"""
Normalização de URLs para deduplicação.
Aplica regras consistentes para comparar URLs.
"""
import logging
import re
from typing import Optional
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

logger = logging.getLogger(__name__)

# Parâmetros de tracking a remover
TRACKING_PARAMS = {
    # UTM
    'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content',
    'utm_id', 'utm_source_platform', 'utm_creative_format',
    # Facebook
    'fbclid', 'fb_action_ids', 'fb_action_types', 'fb_source', 'fb_ref',
    # Google
    'gclid', 'gclsrc', 'dclid',
    # Twitter
    'twclid',
    # Microsoft/Bing
    'msclkid',
    # Mailchimp
    'mc_cid', 'mc_eid',
    # HubSpot
    'hsa_acc', 'hsa_cam', 'hsa_grp', 'hsa_ad', 'hsa_src', 'hsa_tgt',
    'hsa_kw', 'hsa_mt', 'hsa_net', 'hsa_ver',
    # Outros comuns
    '_ga', '_gl', 'ref', 'source', 'via',
}

# Portas padrão por scheme
DEFAULT_PORTS = {
    'http': 80,
    'https': 443,
}


def normalize_url(url: Optional[str]) -> Optional[str]:
    """
    Normaliza URL para comparação consistente.

    Regras aplicadas:
    - Hostname para lowercase
    - Remove fragmento (#...)
    - Remove porta padrão (80 para http, 443 para https)
    - Remove parâmetros de tracking (utm_*, fbclid, gclid, etc.)
    - Remove trailing slash (exceto para root "/")
    - Rejeita URLs com userinfo (usuário:senha@)

    Args:
        url: URL para normalizar

    Returns:
        URL normalizada ou None se inválida

    Examples:
        >>> normalize_url("https://Site.com:443/Article?utm_source=rss&id=123#comments")
        "https://site.com/Article?id=123"

        >>> normalize_url("http://user:pass@example.com/page")
        None  # URLs com userinfo são rejeitadas
    """
    if not url:
        return None

    try:
        parsed = urlparse(url)
    except Exception as e:
        logger.warning(f"URL inválida: {url} - {e}")
        return None

    # Rejeitar URLs com userinfo (segurança)
    if parsed.username or parsed.password:
        logger.warning(f"URL com userinfo rejeitada: {url}")
        return None

    # Verificar scheme válido
    if parsed.scheme not in ('http', 'https'):
        logger.warning(f"URL com scheme inválido: {url}")
        return None

    # Hostname para lowercase
    hostname = parsed.hostname
    if not hostname:
        return None
    hostname = hostname.lower()

    # Remover porta padrão
    port = parsed.port
    default_port = DEFAULT_PORTS.get(parsed.scheme)
    if port == default_port:
        port = None

    # Reconstruir netloc
    if port:
        netloc = f"{hostname}:{port}"
    else:
        netloc = hostname

    # Processar path
    path = parsed.path

    # Remover trailing slash (exceto para root)
    if path and path != '/' and path.endswith('/'):
        path = path.rstrip('/')

    # Se path vazio, usar /
    if not path:
        path = '/'

    # Processar query string - remover parâmetros de tracking
    query_params = parse_qs(parsed.query, keep_blank_values=True)

    # Filtrar parâmetros de tracking
    filtered_params = {
        k: v for k, v in query_params.items()
        if k.lower() not in TRACKING_PARAMS
    }

    # Reconstruir query string ordenada (para consistência)
    if filtered_params:
        # Flatten: parse_qs retorna listas, precisamos de valores únicos
        flat_params = []
        for k, v in sorted(filtered_params.items()):
            for val in v:
                flat_params.append((k, val))
        query = urlencode(flat_params)
    else:
        query = ''

    # Reconstruir URL sem fragmento
    normalized = urlunparse((
        parsed.scheme,
        netloc,
        path,
        '',  # params (raramente usado)
        query,
        '',  # fragment removido
    ))

    return normalized


def extract_domain(url: str) -> Optional[str]:
    """
    Extrai domínio de uma URL.

    Args:
        url: URL para extrair domínio

    Returns:
        Domínio em lowercase ou None se inválido
    """
    try:
        parsed = urlparse(url)
        if parsed.hostname:
            return parsed.hostname.lower()
    except Exception:
        pass
    return None
