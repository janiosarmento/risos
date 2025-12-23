"""
Hash de conteúdo para deduplicação.
Normaliza conteúdo antes de calcular hash.
"""
import hashlib
import re
from typing import Optional

from app.services.html_sanitizer import extract_text

# Padrões de boilerplate a remover
BOILERPLATE_PATTERNS = [
    # Timestamps e datas
    r'\b\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}\b',
    r'\b\d{1,2}:\d{2}(:\d{2})?\s*(AM|PM|am|pm)?\b',
    # "Leia mais", "Continue lendo", etc.
    r'\b(leia|read|continue|ver|see)\s+(mais|more|reading|lendo)\b',
    r'\b(clique|click)\s+(aqui|here)\b',
    # Compartilhamento
    r'\b(share|compartilh[ae]|tweet|retweet)\b',
    # Avisos de cookies/newsletter
    r'\b(newsletter|subscribe|inscreva-se|cadastre-se)\b',
]

# Tamanho máximo para hash (bytes)
MAX_HASH_SIZE = 200 * 1024  # 200KB


def normalize_for_hash(text: str) -> str:
    """
    Normaliza texto para hash consistente.

    - Remove boilerplate
    - Normaliza whitespace
    - Lowercase
    """
    if not text:
        return ""

    # Lowercase
    text = text.lower()

    # Remover boilerplate
    for pattern in BOILERPLATE_PATTERNS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # Normalizar whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    return text


def compute_content_hash(content: Optional[str]) -> Optional[str]:
    """
    Calcula hash SHA-256 do conteúdo.

    Args:
        content: Conteúdo HTML ou texto

    Returns:
        Hash SHA-256 em hexadecimal ou None se vazio
    """
    if not content:
        return None

    # Extrair texto puro do HTML
    text = extract_text(content)
    if not text:
        return None

    # Normalizar
    normalized = normalize_for_hash(text)
    if not normalized:
        return None

    # Truncar se muito grande
    if len(normalized) > MAX_HASH_SIZE:
        # Usar início + fim para capturar variações
        half = MAX_HASH_SIZE // 2
        normalized = normalized[:half] + normalized[-half:]

    # Calcular hash
    hash_bytes = hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    return hash_bytes
