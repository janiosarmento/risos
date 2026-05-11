"""Constants for the Cerebras client."""

from datetime import timedelta

# API endpoints
DEFAULT_API_BASE_URL = "https://api.cerebras.ai/v1"

# Model cache
MODELS_CACHE_TTL = timedelta(minutes=30)
MODELS_FETCH_TIMEOUT = 10

# Tag translation settings
TAG_TRANSLATION_MODEL = "llama3.1-8b"
TAG_TRANSLATION_TEMPERATURE = 0.1
TAG_TRANSLATION_MAX_TOKENS = 200
TAG_TRANSLATION_TIMEOUT = 15

# Summary generation
SUMMARY_TEMPERATURE = 0.3
SUMMARY_MAX_TOKENS = 2048

# Content limits
MAX_CONTENT_LENGTH = 12000
MIN_CONTENT_LENGTH = 50
SHORT_CONTENT_LENGTH = 200
MAX_ONE_LINE_LENGTH = 150
MAX_TAGS = 15

# Rate limiting
RATE_LIMIT_COOLDOWN_SECONDS = 300
DEFAULT_KEY_COOLDOWN_SECONDS = 60

# Throttle between automatic summary generations to avoid hitting rate limits.
# Manual requests (generate/regenerate) bypass this delay.
SUMMARY_QUEUE_SLEEP_SECONDS = 15
