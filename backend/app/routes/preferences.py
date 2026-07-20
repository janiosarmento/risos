"""
User preferences routes.
Stores locale, theme, AI settings, and data settings in app_settings table.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.config import load_prompts
from app.database import get_db
from app.dependencies import get_current_user
from app.models import AppSettings
from app.services.ai._constants import DEFAULT_API_BASE_URL

router = APIRouter(prefix="/preferences", tags=["preferences"])

# Keys used in app_settings
PREF_LOCALE = "pref_locale"
PREF_THEME = "pref_theme"
PREF_SUMMARY_LANGUAGE = "pref_summary_language"
PREF_AI_MODEL = "pref_ai_model"
# Data settings
PREF_FEED_UPDATE_INTERVAL = "pref_feed_update_interval"
PREF_MAX_POST_AGE_DAYS = "pref_max_post_age_days"
PREF_MAX_UNREAD_DAYS = "pref_max_unread_days"
# Interface settings
PREF_TOAST_TIMEOUT = "pref_toast_timeout"
PREF_IDLE_REFRESH = "pref_idle_refresh"
PREF_READING_MODE = "pref_reading_mode"
PREF_SPLIT_RATIO = "pref_split_ratio"
# Suggestions settings
PREF_SUGGESTION_MIN_TAGS = "pref_suggestion_min_tags"
PREF_PROFILE_MIN_TAG_FREQ = "pref_profile_min_tag_freq"
PREF_SUGGESTION_MIN_SUMMARY_LENGTH = "pref_suggestion_min_summary_length"
# AI keys and prompts
PREF_JANO_SECRET_NAME = "pref_jano_secret_name"
PREF_TAGS_PER_POST = "pref_tags_per_post"
PREF_SYSTEM_PROMPT = "pref_system_prompt"
PREF_USER_PROMPT = "pref_user_prompt"
# Blocked terms
PREF_BLOCKED_TERMS = "pref_blocked_terms"
# API base URL
PREF_API_BASE_URL = "pref_api_base_url"
PREF_AI_TIMEOUT = "pref_ai_timeout"
PREF_RELATED_POSTS_LIMIT = "pref_related_posts_limit"
PREF_AI_MAX_TOKENS = "pref_ai_max_tokens"

# Background AI settings (fall back to on-demand if not set)
PREF_BACKGROUND_JANO_SECRET_NAME = "pref_background_jano_secret_name"
PREF_BACKGROUND_API_BASE_URL = "pref_background_api_base_url"
PREF_BACKGROUND_AI_MODEL = "pref_background_ai_model"


class PreferencesResponse(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None
    summary_language: Optional[str] = None
    ai_model: Optional[str] = None
    # Data settings (returned as integers)
    feed_update_interval: Optional[int] = None
    max_post_age_days: Optional[int] = None
    max_unread_days: Optional[int] = None
    # Interface settings
    toast_timeout_seconds: Optional[int] = None
    idle_refresh_seconds: Optional[int] = None
    reading_mode: Optional[str] = None  # 'fullscreen' or 'split'
    split_ratio: Optional[int] = None  # percentage for posts panel (20-80)
    # Suggestions settings
    suggestion_min_tags: Optional[int] = None  # minimum tag overlap for suggestions
    profile_min_tag_freq: Optional[int] = (
        None  # min liked posts for a tag to enter profile
    )
    suggestion_min_summary_length: Optional[int] = (
        None  # min translated summary length (chars) to be eligible for suggestions
    )
    # AI keys and prompts
    jano_secret_name: Optional[str] = None
    tags_per_post: Optional[int] = None  # number of tags per AI summary (3-15)
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    # Blocked terms (newline-separated)
    blocked_terms: Optional[str] = None
    # API base URL
    api_base_url: Optional[str] = None
    ai_timeout: int = 30
    related_posts_limit: int = 30
    ai_max_tokens: int = 8192
    # Background AI settings (fall back to on-demand if not set)
    background_jano_secret_name: Optional[str] = None
    background_api_base_url: Optional[str] = None
    background_ai_model: Optional[str] = None


class PreferencesUpdate(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None
    summary_language: Optional[str] = None
    ai_model: Optional[str] = None
    # Data settings
    feed_update_interval: Optional[int] = None
    max_post_age_days: Optional[int] = None
    max_unread_days: Optional[int] = None
    # Interface settings
    toast_timeout_seconds: Optional[int] = None
    idle_refresh_seconds: Optional[int] = None
    reading_mode: Optional[str] = None
    split_ratio: Optional[int] = None
    # Suggestions settings
    suggestion_min_tags: Optional[int] = None
    profile_min_tag_freq: Optional[int] = None
    suggestion_min_summary_length: Optional[int] = None
    # AI keys and prompts
    jano_secret_name: Optional[str] = None
    tags_per_post: Optional[int] = None
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    blocked_terms: Optional[str] = None
    api_base_url: Optional[str] = None
    ai_timeout: Optional[int] = None
    related_posts_limit: Optional[int] = None
    ai_max_tokens: Optional[int] = None
    # Background AI settings
    background_jano_secret_name: Optional[str] = None
    background_api_base_url: Optional[str] = None
    background_ai_model: Optional[str] = None


def _get_setting(db: Session, key: str) -> Optional[str]:
    """Get a single setting value from app_settings."""
    row = db.query(AppSettings).filter(AppSettings.key == key).first()
    return row.value if row else None


def _set_setting(db: Session, key: str, value: str):
    """Set a single setting value in app_settings."""
    existing = db.query(AppSettings).filter(AppSettings.key == key).first()
    if existing:
        existing.value = value
    else:
        db.add(AppSettings(key=key, value=value))


@router.get("", response_model=PreferencesResponse)
def get_preferences(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get user preferences.
    Settings return env defaults if not overridden.
    """
    # Gather every key referenced in PREF_SPEC plus the special/non-spec keys.
    all_keys = [sp.key for sp in PREF_SPEC.values()] + [
        PREF_LOCALE,
        PREF_THEME,
        PREF_SUGGESTION_MIN_TAGS,
        PREF_JANO_SECRET_NAME,
        PREF_SYSTEM_PROMPT,
        PREF_USER_PROMPT,
        PREF_BLOCKED_TERMS,
        PREF_API_BASE_URL,
        PREF_BACKGROUND_JANO_SECRET_NAME,
        PREF_BACKGROUND_API_BASE_URL,
        PREF_BACKGROUND_AI_MODEL,
    ]
    prefs = {k: None for k in all_keys}
    for row in db.query(AppSettings).filter(AppSettings.key.in_(all_keys)).all():
        prefs[row.key] = row.value

    prompts = load_prompts()
    def r(name): return _resolve_spec(prefs, name)
    def i(name, default): return _resolve_spec(prefs, name) if name in PREF_SPEC else default

    return PreferencesResponse(
        locale=prefs[PREF_LOCALE],
        theme=prefs[PREF_THEME],
        summary_language=r("summary_language"),
        ai_model=r("ai_model"),
        feed_update_interval=r("feed_update_interval"),
        max_post_age_days=r("max_post_age_days"),
        max_unread_days=r("max_unread_days"),
        toast_timeout_seconds=r("toast_timeout_seconds"),
        idle_refresh_seconds=r("idle_refresh_seconds"),
        reading_mode=r("reading_mode"),
        split_ratio=r("split_ratio"),
        suggestion_min_tags=get_effective_suggestion_min_tags(db),
        profile_min_tag_freq=r("profile_min_tag_freq"),
        suggestion_min_summary_length=r("suggestion_min_summary_length"),
        jano_secret_name=prefs[PREF_JANO_SECRET_NAME],
        tags_per_post=r("tags_per_post"),
        system_prompt=prefs[PREF_SYSTEM_PROMPT] or prompts.get("system_prompt", ""),
        user_prompt=prefs[PREF_USER_PROMPT] or prompts.get("user_prompt", ""),
        blocked_terms=prefs[PREF_BLOCKED_TERMS] or "",
        api_base_url=prefs[PREF_API_BASE_URL] or DEFAULT_API_BASE_URL,
        ai_timeout=r("ai_timeout"),
        related_posts_limit=r("related_posts_limit"),
        ai_max_tokens=r("ai_max_tokens"),
        background_jano_secret_name=prefs[PREF_BACKGROUND_JANO_SECRET_NAME],
        background_api_base_url=prefs[PREF_BACKGROUND_API_BASE_URL] or prefs[PREF_API_BASE_URL] or DEFAULT_API_BASE_URL,
        background_ai_model=prefs[PREF_BACKGROUND_AI_MODEL] or prefs[PREF_AI_MODEL] or "llama-3.3-70b",
    )


# Mapping from PreferencesUpdate field → app_settings key, grouped by
# transform.  (K4 — the simple cases use a loop; special cases stay explicit.)
_UPDATE_FIELDS_AS_IS: list[tuple[str, str]] = [
    ("locale", PREF_LOCALE),
    ("theme", PREF_THEME),
    ("summary_language", PREF_SUMMARY_LANGUAGE),
    ("ai_model", PREF_AI_MODEL),
    ("reading_mode", PREF_READING_MODE),
    ("system_prompt", PREF_SYSTEM_PROMPT),
    ("user_prompt", PREF_USER_PROMPT),
    ("background_ai_model", PREF_BACKGROUND_AI_MODEL),
]
_UPDATE_FIELDS_STRINT: list[tuple[str, str]] = [
    ("feed_update_interval", PREF_FEED_UPDATE_INTERVAL),
    ("max_post_age_days", PREF_MAX_POST_AGE_DAYS),
    ("max_unread_days", PREF_MAX_UNREAD_DAYS),
    ("toast_timeout_seconds", PREF_TOAST_TIMEOUT),
    ("idle_refresh_seconds", PREF_IDLE_REFRESH),
    ("ai_timeout", PREF_AI_TIMEOUT),
]


@router.put("", response_model=PreferencesResponse)
def update_preferences(
    prefs: PreferencesUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """Update user preferences.  Only fields that are provided (not None)."""

    # ---- simple fields (no transform) ----
    for field, key in _UPDATE_FIELDS_AS_IS:
        val = getattr(prefs, field, None)
        if val is not None:
            _set_setting(db, key, val)

    # ---- simple int fields (store as string) ----
    for field, key in _UPDATE_FIELDS_STRINT:
        val = getattr(prefs, field, None)
        if val is not None:
            _set_setting(db, key, str(val))

    # ---- special cases (clamping, trimming, side effects) ----

    if prefs.split_ratio is not None:
        _set_setting(db, PREF_SPLIT_RATIO, str(max(20, min(80, prefs.split_ratio))))

    if prefs.suggestion_min_tags is not None:
        max_tags = get_effective_tags_per_post(db)
        clamped = max(1, min(max_tags, prefs.suggestion_min_tags))
        _set_setting(db, PREF_SUGGESTION_MIN_TAGS, str(clamped))
        from app.services.suggestions import clear_all_suggestions
        clear_all_suggestions(db)

    if prefs.profile_min_tag_freq is not None:
        clamped = max(1, min(20, prefs.profile_min_tag_freq))
        _set_setting(db, PREF_PROFILE_MIN_TAG_FREQ, str(clamped))
        from app.services.suggestions import clear_all_suggestions
        from app.services.user_profile import invalidate_user_profile
        clear_all_suggestions(db)
        invalidate_user_profile(db)

    if prefs.suggestion_min_summary_length is not None:
        clamped = max(0, min(2000, prefs.suggestion_min_summary_length))
        _set_setting(db, PREF_SUGGESTION_MIN_SUMMARY_LENGTH, str(clamped))
        from app.services.suggestions import clear_all_suggestions
        clear_all_suggestions(db)

    if prefs.jano_secret_name is not None:
        _set_setting(db, PREF_JANO_SECRET_NAME, prefs.jano_secret_name.strip())

    if prefs.tags_per_post is not None:
        _set_setting(db, PREF_TAGS_PER_POST, str(max(3, min(15, prefs.tags_per_post))))

    if prefs.api_base_url is not None:
        _set_setting(db, PREF_API_BASE_URL, prefs.api_base_url.strip().rstrip("/"))

    if prefs.related_posts_limit is not None:
        _set_setting(db, PREF_RELATED_POSTS_LIMIT, str(max(5, min(100, prefs.related_posts_limit))))

    if prefs.ai_max_tokens is not None:
        _set_setting(db, PREF_AI_MAX_TOKENS, str(max(256, min(32768, prefs.ai_max_tokens))))

    if prefs.blocked_terms is not None:
        lines = [ln.strip().lower() for ln in prefs.blocked_terms.splitlines() if ln.strip()]
        _set_setting(db, PREF_BLOCKED_TERMS, "\n".join(sorted(set(lines))))
        _unsuggest_blocked_posts(db, lines)

    if prefs.background_jano_secret_name is not None:
        _set_setting(db, PREF_BACKGROUND_JANO_SECRET_NAME, prefs.background_jano_secret_name.strip())

    if prefs.background_api_base_url is not None:
        _set_setting(db, PREF_BACKGROUND_API_BASE_URL, prefs.background_api_base_url.strip().rstrip("/"))

    db.commit()
    return get_preferences(db, user)


def _unsuggest_blocked_posts(db: Session, blocked_terms: list):
    """Remove suggestion status from posts matching blocked terms."""
    if not blocked_terms:
        return
    from app.models import Post
    from app.routes.posts import title_matches_term

    suggested = db.query(Post).filter(Post.is_suggested == 1, Post.is_read == 0).all()
    count = 0
    for post in suggested:
        title_lower = (post.title or "").lower()
        if any(title_matches_term(title_lower, term) for term in blocked_terms):
            post.is_suggested = 0
            post.suggestion_score = None
            post.suggested_at = None
            count += 1
    if count:
        import logging

        logging.getLogger(__name__).info(
            f"Removed {count} suggestions matching blocked terms"
        )


# =============================================================================
# Preference spec table — single source of truth for key / type / default.
# Used by get_preferences(), update_preferences(), and every get_effective_*().
# =============================================================================

from dataclasses import dataclass
from typing import Any, Callable


def _cast_int(val: Any) -> int | None:
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


@dataclass
class PrefSpec:
    key: str
    default: Any
    cast: Callable[[Any], Any | None] = lambda v: v
    clamp: Callable[["PrefSpec", Any], Any] | None = None


PREF_SPEC: dict[str, PrefSpec] = {
    "summary_language": PrefSpec(
        PREF_SUMMARY_LANGUAGE, "Brazilian Portuguese"
    ),
    "ai_model": PrefSpec(
        PREF_AI_MODEL, "llama-3.3-70b"
    ),
    "feed_update_interval": PrefSpec(
        PREF_FEED_UPDATE_INTERVAL, 30, cast=_cast_int,
    ),
    "max_post_age_days": PrefSpec(
        PREF_MAX_POST_AGE_DAYS, 365, cast=_cast_int,
    ),
    "max_unread_days": PrefSpec(
        PREF_MAX_UNREAD_DAYS, 90, cast=_cast_int,
    ),
    "toast_timeout_seconds": PrefSpec(
        PREF_TOAST_TIMEOUT, 2, cast=_cast_int,
    ),
    "idle_refresh_seconds": PrefSpec(
        PREF_IDLE_REFRESH, 180, cast=_cast_int,
    ),
    "reading_mode": PrefSpec(
        PREF_READING_MODE, "fullscreen",
    ),
    "split_ratio": PrefSpec(
        PREF_SPLIT_RATIO, 40, cast=_cast_int,
        clamp=lambda sp, v: max(20, min(80, v)),
    ),
    "profile_min_tag_freq": PrefSpec(
        PREF_PROFILE_MIN_TAG_FREQ, 2, cast=_cast_int,
        clamp=lambda sp, v: max(1, min(20, v)),
    ),
    "suggestion_min_summary_length": PrefSpec(
        PREF_SUGGESTION_MIN_SUMMARY_LENGTH, 100, cast=_cast_int,
        clamp=lambda sp, v: max(0, min(2000, v)),
    ),
    "tags_per_post": PrefSpec(
        PREF_TAGS_PER_POST, 7, cast=_cast_int,
        clamp=lambda sp, v: max(3, min(15, v)),
    ),
    "ai_timeout": PrefSpec(
        PREF_AI_TIMEOUT, 30, cast=_cast_int,
        clamp=lambda sp, v: max(5, v),
    ),
    "ai_max_tokens": PrefSpec(
        PREF_AI_MAX_TOKENS, 8192, cast=_cast_int,
        clamp=lambda sp, v: max(256, min(32768, v)),
    ),
    "related_posts_limit": PrefSpec(
        PREF_RELATED_POSTS_LIMIT, 30, cast=_cast_int,
        clamp=lambda sp, v: max(5, min(100, v)),
    ),
}


def _get_effective(db: Session, name: str) -> Any:
    """Resolve one preference from db or fall back to its spec default."""
    spec = PREF_SPEC[name]
    saved = _get_setting(db, spec.key)
    val = spec.cast(saved) if saved is not None else None
    if val is not None:
        if spec.clamp is not None:
            return spec.clamp(spec, val)
        return val
    return spec.default


def _resolve_spec(prefs: dict, name: str) -> Any:
    """Like _get_effective but from a pre-fetched key→value dict (avoids N+1 queries)."""
    spec = PREF_SPEC.get(name)
    if spec is None:
        return None
    raw = prefs.get(spec.key)
    if raw is not None:
        val = spec.cast(raw)
        if val is not None:
            if spec.clamp is not None:
                return spec.clamp(spec, val)
            return val
    return spec.default


# =============================================================================
# Helper for other modules to get settings
# =============================================================================



def get_effective_ai_api_key(db: Session) -> Optional[str]:
    """Retorna a chave de API única configurada via Jano, ou None."""
    secret_name = _get_setting(db, PREF_JANO_SECRET_NAME)
    if not secret_name:
        return None
    from app.services.jano_client import get_jano_secret
    try:
        val = get_jano_secret(secret_name)
        return val.strip() if val and val.strip() else None
    except Exception:
        logging.getLogger(__name__).exception(
            "Jano secret lookup failed for %s", secret_name
        )
        return None


def get_effective_system_prompt(db: Session) -> str:
    """Get system prompt from app_settings or prompts.yaml default."""
    saved = _get_setting(db, PREF_SYSTEM_PROMPT)
    if saved:
        return saved
    prompts = load_prompts()
    prompt = prompts.get("system_prompt", "")
    if prompt:
        _set_setting(db, PREF_SYSTEM_PROMPT, prompt)
        db.commit()
    return prompt


def get_effective_user_prompt(db: Session) -> str:
    """Get user prompt template from app_settings or prompts.yaml default."""
    saved = _get_setting(db, PREF_USER_PROMPT)
    if saved:
        return saved
    prompts = load_prompts()
    prompt = prompts.get("user_prompt", "")
    if prompt:
        _set_setting(db, PREF_USER_PROMPT, prompt)
        db.commit()
    return prompt


def get_effective_summary_language(db: Session) -> str:
    return _get_effective(db, "summary_language")


def get_effective_ai_model(db: Session) -> str:
    return _get_effective(db, "ai_model")


def get_effective_feed_update_interval(db: Session) -> int:
    return _get_effective(db, "feed_update_interval")


def get_effective_max_post_age_days(db: Session) -> int:
    return _get_effective(db, "max_post_age_days")


def get_effective_max_unread_days(db: Session) -> int:
    return _get_effective(db, "max_unread_days")


def get_effective_toast_timeout(db: Session) -> int:
    return _get_effective(db, "toast_timeout_seconds")


def get_effective_idle_refresh(db: Session) -> int:
    return _get_effective(db, "idle_refresh_seconds")


def get_effective_tags_per_post(db: Session) -> int:
    """Get number of tags per post from app_settings or default (7)."""
    return _get_effective(db, "tags_per_post")


def get_effective_suggestion_min_tags(db: Session) -> int:
    """Get minimum tag overlap for suggestions from app_settings or default (3)."""
    saved = _get_setting(db, PREF_SUGGESTION_MIN_TAGS)
    if saved:
        try:
            max_tags = get_effective_tags_per_post(db)
            return max(1, min(max_tags, int(saved)))
        except (ValueError, TypeError):
            pass
    return 3  # Default: 3 tags minimum


def get_effective_profile_min_tag_freq(db: Session) -> int:
    """Get minimum tag frequency for profile inclusion (default: 2)."""
    return _get_effective(db, "profile_min_tag_freq")


def get_effective_suggestion_min_summary_length(db: Session) -> int:
    """Min translated summary length (chars) for a post to be eligible for suggestions (default: 100)."""
    return _get_effective(db, "suggestion_min_summary_length")


def get_effective_ai_timeout(db: Session) -> int:
    """Get AI request timeout from app_settings or default 30s."""
    return _get_effective(db, "ai_timeout")


def get_effective_ai_max_tokens(db: Session) -> int:
    """Get AI request max tokens from app_settings or default 8192."""
    return _get_effective(db, "ai_max_tokens")


def get_effective_api_base_url(db: Session) -> str:
    """Get API base URL from app_settings or default."""
    row = db.query(AppSettings).filter(AppSettings.key == PREF_API_BASE_URL).first()
    return (row.value if row and row.value else DEFAULT_API_BASE_URL).rstrip("/")


def get_effective_background_ai_api_key(db: Session) -> Optional[str]:
    """Background API key — falls back to on-demand key if not set."""
    secret_name = _get_setting(db, PREF_BACKGROUND_JANO_SECRET_NAME)
    if secret_name:
        from app.services.jano_client import get_jano_secret

        try:
            val = get_jano_secret(secret_name)
            if val and val.strip():
                return val.strip()
        except Exception as e:
            logging.getLogger(__name__).debug("jano_secret lookup failed for %s: %s", secret_name, e)
    return get_effective_ai_api_key(db)


def get_effective_background_api_base_url(db: Session) -> str:
    """Background API base URL — falls back to on-demand URL if not set."""
    row = db.query(AppSettings).filter(AppSettings.key == PREF_BACKGROUND_API_BASE_URL).first()
    if row and row.value:
        return row.value.rstrip("/")
    return get_effective_api_base_url(db)


def get_effective_background_ai_model(db: Session) -> str:
    """Background AI model — falls back to on-demand model if not set."""
    saved = _get_setting(db, PREF_BACKGROUND_AI_MODEL)
    return saved or get_effective_ai_model(db)


def get_effective_blocked_terms(db: Session) -> list:
    """Get blocked terms list from app_settings. Returns list of lowercase strings."""
    saved = _get_setting(db, PREF_BLOCKED_TERMS)
    if not saved:
        return []
    return [line.strip() for line in saved.splitlines() if line.strip()]


def get_effective_related_posts_limit(db: Session) -> int:
    return _get_effective(db, "related_posts_limit")
