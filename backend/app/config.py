"""
Bootstrap configuration — operational settings live in the database.
"""

from pathlib import Path

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


def load_prompts() -> dict:
    """Load prompts from prompts.yaml file."""
    prompts_path = Path(__file__).parent.parent / "prompts.yaml"
    if prompts_path.exists():
        with open(prompts_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {}


class Settings(BaseSettings):
    """Bootstrap configuration — operational settings live in the database."""

    # Database
    database_path: str = "./data/reader.db"

    # Authentication
    app_password: str
    session_ttl_hours: int = 168  # 7 days sliding window

    # Rate Limiting HTTP
    login_rate_limit: int = 5

    # Retention
    max_db_size_mb: int = 1024

    # Proxy
    proxy_timeout_seconds: int = 10
    proxy_max_size_bytes: int = 5_242_880  # 5MB

    # Logging
    log_level: str = "INFO"
    log_file: str = "./data/app.log"

    # Security
    cors_origins: str = "https://rss.sarmento.org"
    cookie_secure: bool = True  # Set to false only for local HTTP development
    jano_secret_prefix: str = "risos."  # Namespace allowed in /admin/validate-secret

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

# Global configuration instance
settings = Settings()

# HTTP client identity
USER_AGENT = "Risos/1.0 (+https://rss.sarmento.org)"
