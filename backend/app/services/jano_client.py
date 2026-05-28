"""
Jano Secret Manager client service.
Integrates with the secrets_resolver library to retrieve API keys securely.
"""

import logging

from secrets_resolver import get_secret

logger = logging.getLogger(__name__)


def get_jano_secret(path: str) -> str:
    """
    Resolve a secret value by its Jano path (e.g. 'risos.cerebras_api_key').
    Values are decrypted via sops on demand and cached in memory by secrets_resolver.
    """
    if not path or not isinstance(path, str):
        raise ValueError("Invalid secret path format")

    logger.error(f"[DEBUG jano] Tentando resolver segredo Jano para o caminho: '{path}'")
    try:
        # get_secret is provided by secrets_resolver
        val = get_secret(path)
        if val is None:
            logger.error(f"[DEBUG jano] Retorno do secrets_resolver para '{path}' foi None!")
        else:
            preview = repr(val[:5] + "..." if len(val) > 5 else val)
            logger.error(f"[DEBUG jano] secrets_resolver resolveu '{path}' com SUCESSO (tamanho={len(val)}, preview={preview})")
        return val
    except Exception as e:
        logger.error(f"[DEBUG jano] EXCEÇÃO ao resolver segredo '{path}': {type(e).__name__}: {e}", exc_info=True)
        raise
