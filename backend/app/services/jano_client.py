"""
Jano Secret Manager client service.
Integrates with the secrets_resolver library to retrieve API keys securely.
"""

import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Dynamically resolve and import secrets_resolver from ~/projects/jano
try:
    from secrets_resolver import get_secret
except ImportError:
    # Try adding standard user development path or production server path for Jano
    jano_src = Path.home() / "projects" / "jano" / "src"
    if not jano_src.exists():
        jano_src = Path("/opt/jano/src")

    if jano_src.exists():
        sys.path.insert(0, str(jano_src))
        try:
            from secrets_resolver import get_secret
            logger.info(f"Successfully loaded secrets_resolver from {jano_src}")
        except ImportError as e:
            logger.error(f"Failed to import secrets_resolver from {jano_src}: {e}")
            raise
    else:
        logger.error(
            "secrets_resolver not installed and local Jano repo "
            "not found in ~/projects/jano or /opt/jano"
        )
        raise


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
