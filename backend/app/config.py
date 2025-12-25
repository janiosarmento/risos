"""
Configuração da aplicação usando pydantic-settings.
Carrega variáveis de ambiente do arquivo .env
"""
import os
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
    """Configurações da aplicação carregadas do .env"""

    # Banco de dados
    database_path: str = "./data/reader.db"

    # Autenticação
    app_password: str
    jwt_secret: str
    jwt_expiration_hours: int = 24

    # Cerebras IA
    cerebras_api_key: str = ""  # Can be comma-separated for multiple keys
    cerebras_model: str = "llama-3.3-70b"

    @property
    def cerebras_api_keys(self) -> list:
        """Returns list of API keys (supports comma-separated values)."""
        if not self.cerebras_api_key:
            return []
        return [k.strip() for k in self.cerebras_api_key.split(",") if k.strip()]
    cerebras_max_rpm: int = 20
    cerebras_timeout: int = 30
    summary_language: str = "Brazilian Portuguese"

    # Circuit Breaker
    failure_threshold: int = 5
    recovery_timeout_seconds: int = 300
    half_open_max_requests: int = 3

    # Rate Limiting HTTP
    login_rate_limit: int = 5
    api_rate_limit: int = 100
    feeds_refresh_rate_limit: int = 10

    # Retenção
    max_posts_per_feed: int = 500
    max_post_age_days: int = 365
    max_unread_days: int = 90
    max_db_size_mb: int = 1024

    # Jobs
    feed_update_interval_minutes: int = 30
    summary_lock_timeout_seconds: int = 300
    cleanup_hour: int = 3

    # Proxy
    proxy_timeout_seconds: int = 10
    proxy_max_size_bytes: int = 5_242_880  # 5MB

    # Logging
    log_level: str = "INFO"
    log_file: str = "./data/app.log"

    # Segurança
    cors_origins: str = "https://rss.sarmento.org"

    # UI
    toast_timeout_seconds: int = 2
    idle_refresh_seconds: int = 180  # 3 minutes

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    def __init__(self, **kwargs):
        """Valida JWT_SECRET no __init__"""
        super().__init__(**kwargs)

        # Validar JWT_SECRET >= 32 caracteres
        if len(self.jwt_secret) < 32:
            raise ValueError(
                f"JWT_SECRET must be at least 32 characters long. "
                f"Current length: {len(self.jwt_secret)}"
            )


# Instância global de configuração
settings = Settings()

# Carregar prompts do arquivo YAML
prompts = load_prompts()
