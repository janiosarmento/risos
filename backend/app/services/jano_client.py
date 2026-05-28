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

    logger.debug(f"Resolving Jano secret for path: {path}")
    try:
        # get_secret is provided by secrets_resolver
        return get_secret(path)
    except Exception as e:
        logger.error(f"Failed to resolve Jano secret '{path}': {e}")
        raise
