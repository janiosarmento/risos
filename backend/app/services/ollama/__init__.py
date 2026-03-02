"""Local Ollama LLM client for background batch processing."""

from app.services.ollama._api import generate_summary_local

__all__ = ["generate_summary_local"]
