"""Infrastructure: the AI client's single API key."""

import logging
from typing import Optional, Tuple

from app.database import SessionLocal

logger = logging.getLogger(__name__)


class ApiKeyRotator:
    """
    Wrapper simples para a chave de API configurada via Jano.
    Não há rotação — existe uma única chave. A interface é mantida
    para compatibilidade com os callers existentes.
    """

    def _get_key(self) -> Optional[str]:
        """Obtém a chave de API do Jano via preferências."""
        from app.routes.preferences import get_effective_ai_api_key

        db = SessionLocal()
        try:
            return get_effective_ai_api_key(db)
        finally:
            db.close()

    # Compatibilidade com callers que usam _get_keys() (retorna lista)
    def _get_keys(self) -> list:
        key = self._get_key()
        return [key] if key else []

    def get_next_key(self) -> Tuple[Optional[str], Optional[int]]:
        """Retorna a chave configurada, ou (None, None) se não configurada."""
        key = self._get_key()
        if not key:
            logger.warning("Nenhuma chave de API configurada no Jano")
            return None, None
        return key, 0

    def has_available_key(self) -> bool:
        """Verifica se há chave disponível."""
        return bool(self._get_key())

    # Métodos de cooldown mantidos como no-op (sem rotação, sem cooldown por chave)
    def set_key_cooldown(self, key: str, seconds: int = 60):
        logger.warning(f"Rate limit atingido (sem rotação, aguardando {seconds}s)")

    def clear_cooldown(self, key: str):
        pass

    def get_status(self) -> dict:
        key = self._get_key()
        return {
            "total_keys": 1 if key else 0,
            "keys": [{"index": 1, "available": True}] if key else [],
        }


# Instância global (compatibilidade com todos os callers)
api_key_rotator = ApiKeyRotator()
