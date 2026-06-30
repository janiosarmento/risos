"""Constants for the AI client."""

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
SUMMARY_MAX_TOKENS = 8192

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

# Circuit breaker
CB_FAILURE_THRESHOLD = 5
CB_RECOVERY_TIMEOUT_SECONDS = 300
CB_HALF_OPEN_MAX_REQUESTS = 3

# Scheduler jobs
SUMMARY_LOCK_TIMEOUT_SECONDS = 300
CLEANUP_HOUR = 3

# API rate limiting
AI_MAX_RPM = 20

# Language gate: post-summary cleanup of mixed-language output.
# Detection is per-sentence and cheap; the LLM cleanup pass only fires when a
# sentence is confidently in the wrong language, so clean summaries cost nothing
# beyond the detection itself.
LANGUAGE_GATE_ENABLED = True
# Sentences shorter than this are skipped: langdetect is unreliable on short
# spans (e.g. "chip" alone is misclassified), which would cause false positives.
LANGUAGE_GATE_MIN_SENTENCE_CHARS = 25
# A sentence is flagged as foreign only when its top language differs from the
# target AND scores at least this probability. Genuine target-language text
# rarely produces a confident foreign label, so false positives are rare.
LANGUAGE_GATE_CONFIDENCE = 0.90
LANGUAGE_GATE_CLEANUP_TEMPERATURE = 0.1
LANGUAGE_GATE_CLEANUP_MAX_TOKENS = 4096
# Reject the cleaned result if it is shorter than this fraction of the original
# (guards against a model that drops content instead of just translating).
LANGUAGE_GATE_MIN_LENGTH_RATIO = 0.5
