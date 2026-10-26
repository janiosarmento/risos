"""The summary worker only runs when the background engine can authenticate."""

import pytest

import app.routes.preferences as preferences
from app.services.ai import has_background_api_key
from app.services.ai._constants import DEFAULT_API_BASE_URL


@pytest.fixture
def background(monkeypatch):
    def configure(key, base_url):
        monkeypatch.setattr(
            preferences, "get_effective_background_ai_api_key", lambda db: key
        )
        monkeypatch.setattr(
            preferences, "get_effective_background_api_base_url", lambda db: base_url
        )

    return configure


def test_key_on_default_endpoint(background):
    background("secret", DEFAULT_API_BASE_URL)
    assert has_background_api_key()


def test_no_key_on_default_endpoint(background):
    background(None, DEFAULT_API_BASE_URL)
    assert not has_background_api_key()


def test_keyless_local_endpoint_counts_as_configured(background):
    background(None, "http://localhost:1234/v1")
    assert has_background_api_key()
