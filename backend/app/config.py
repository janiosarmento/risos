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
    jwt_secret: str
    jwt_expiration_hours: int = 24

    # Rate Limiting HTTP
    login_rate_limit: int = 5
    api_rate_limit: int = 100
    feeds_refresh_rate_limit: int = 10

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

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    def __init__(self, **kwargs):
        """Validate JWT_SECRET in __init__"""
        super().__init__(**kwargs)

        # Validate JWT_SECRET >= 32 characters
        if len(self.jwt_secret) < 32:
            raise ValueError(
                f"JWT_SECRET must be at least 32 characters long. "
                f"Current length: {len(self.jwt_secret)}"
            )


# Global configuration instance
settings = Settings()

# HTTP client identity
USER_AGENT = "Risos/1.0 (+https://rss.sarmento.org)"
