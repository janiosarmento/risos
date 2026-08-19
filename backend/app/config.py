"""
Bootstrap configuration — operational settings live in the database.
"""

from pathlib import Path
from typing import Optional

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

    # SSH Fallback (feed fetch) — retry via SOCKS tunnel when direct fetch fails.
    # Unset (default) disables the fallback entirely.
    ssh_fallback_host: Optional[str] = None
    ssh_fallback_user: Optional[str] = None
    ssh_fallback_port: int = 22
    ssh_fallback_key_path: Optional[str] = None

    # Logging
    log_level: str = "INFO"
    log_file: str = "./data/app.log"

    # Security
    cors_origins: str = "https://rss.sarmento.org"
    cookie_secure: bool = True  # Set to false only for local HTTP development
    # Comma-separated Jano secret names the app is allowed to resolve as an AI
    # API key (via /preferences jano_secret_name / background_jano_secret_name,
    # and /admin/validate-secret). Prevents a compromised session from making
    # the app decrypt unrelated host secrets (passwords, other apps' keys).
    jano_ai_secret_allowlist: str = "deepseek.api_key,gemini.api_key,openrouter.api_key"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def jano_ai_secret_allowlist_set(self) -> set[str]:
        return {
            name.strip()
            for name in self.jano_ai_secret_allowlist.split(",")
            if name.strip()
        }

# Global configuration instance
settings = Settings()

# HTTP client identity
USER_AGENT = "Risos/1.0 (+https://rss.sarmento.org)"
