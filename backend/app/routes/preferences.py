"""
User preferences routes.
Stores locale, theme, AI settings, and data settings in app_settings table.
"""

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
PREF_MAX_POSTS_PER_FEED = "pref_max_posts_per_feed"
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
# AI keys and prompts
PREF_AI_API_KEYS = "pref_ai_api_keys"
PREF_TAGS_PER_POST = "pref_tags_per_post"
PREF_MODEL_COOLDOWN = "pref_model_cooldown_minutes"
PREF_SYSTEM_PROMPT = "pref_system_prompt"
PREF_USER_PROMPT = "pref_user_prompt"
# Blocked terms
PREF_BLOCKED_TERMS = "pref_blocked_terms"
# API base URL
PREF_API_BASE_URL = "pref_api_base_url"
PREF_AI_TIMEOUT = "pref_ai_timeout"


class PreferencesResponse(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None
    summary_language: Optional[str] = None
    ai_model: Optional[str] = None
    # Data settings (returned as integers)
    feed_update_interval: Optional[int] = None
    max_posts_per_feed: Optional[int] = None
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
    # AI keys and prompts
    ai_api_keys: Optional[str] = None  # masked: "cbrk-****1234, cbrk-****5678"
    tags_per_post: Optional[int] = None  # number of tags per AI summary (3-15)
    model_cooldown_minutes: Optional[int] = (
        None  # grace period for failed models (5-120)
    )
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    # Blocked terms (newline-separated)
    blocked_terms: Optional[str] = None
    # API base URL
    api_base_url: Optional[str] = None
    ai_timeout: int = 30


class PreferencesUpdate(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None
    summary_language: Optional[str] = None
    ai_model: Optional[str] = None
    # Data settings
    feed_update_interval: Optional[int] = None
    max_posts_per_feed: Optional[int] = None
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
    # AI keys and prompts
    ai_api_keys: Optional[str] = None
    tags_per_post: Optional[int] = None
    model_cooldown_minutes: Optional[int] = None
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    blocked_terms: Optional[str] = None
    api_base_url: Optional[str] = None
    ai_timeout: Optional[int] = None


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
    all_keys = [
        PREF_LOCALE,
        PREF_THEME,
        PREF_SUMMARY_LANGUAGE,
        PREF_AI_MODEL,
        PREF_FEED_UPDATE_INTERVAL,
        PREF_MAX_POSTS_PER_FEED,
        PREF_MAX_POST_AGE_DAYS,
        PREF_MAX_UNREAD_DAYS,
        PREF_TOAST_TIMEOUT,
        PREF_IDLE_REFRESH,
        PREF_READING_MODE,
        PREF_SPLIT_RATIO,
        PREF_SUGGESTION_MIN_TAGS,
        PREF_PROFILE_MIN_TAG_FREQ,
        PREF_AI_API_KEYS,
        PREF_TAGS_PER_POST,
        PREF_MODEL_COOLDOWN,
        PREF_SYSTEM_PROMPT,
        PREF_USER_PROMPT,
        PREF_BLOCKED_TERMS,
        PREF_API_BASE_URL,
        PREF_AI_TIMEOUT,
    ]

    prefs = {k: None for k in all_keys}

    rows = db.query(AppSettings).filter(AppSettings.key.in_(all_keys)).all()

    for row in rows:
        prefs[row.key] = row.value

    # Helper to get int or default
    def int_or_default(val, default):
        if val is not None:
            try:
                return int(val)
            except (ValueError, TypeError):
                pass
        return default

    return PreferencesResponse(
        locale=prefs[PREF_LOCALE],
        theme=prefs[PREF_THEME],
        # AI settings
        summary_language=prefs[PREF_SUMMARY_LANGUAGE] or "Brazilian Portuguese",
        ai_model=prefs[PREF_AI_MODEL] or "llama-3.3-70b",
        # Data settings
        feed_update_interval=int_or_default(
            prefs[PREF_FEED_UPDATE_INTERVAL],
            30,
        ),
        max_posts_per_feed=int_or_default(prefs[PREF_MAX_POSTS_PER_FEED], 500),
        max_post_age_days=int_or_default(prefs[PREF_MAX_POST_AGE_DAYS], 365),
        max_unread_days=int_or_default(prefs[PREF_MAX_UNREAD_DAYS], 90),
        # Interface settings
        toast_timeout_seconds=int_or_default(prefs[PREF_TOAST_TIMEOUT], 2),
        idle_refresh_seconds=int_or_default(prefs[PREF_IDLE_REFRESH], 180),
        reading_mode=prefs[PREF_READING_MODE] or "fullscreen",
        split_ratio=int_or_default(prefs[PREF_SPLIT_RATIO], 40),
        # Suggestions
        suggestion_min_tags=int_or_default(prefs[PREF_SUGGESTION_MIN_TAGS], 3),
        profile_min_tag_freq=int_or_default(prefs[PREF_PROFILE_MIN_TAG_FREQ], 2),
        # AI keys and prompts
        ai_api_keys=_mask_keys(prefs[PREF_AI_API_KEYS] or ""),
        tags_per_post=int_or_default(prefs[PREF_TAGS_PER_POST], 7),
        model_cooldown_minutes=int_or_default(prefs[PREF_MODEL_COOLDOWN], 30),
        system_prompt=prefs[PREF_SYSTEM_PROMPT]
        or load_prompts().get("system_prompt", ""),
        user_prompt=prefs[PREF_USER_PROMPT] or load_prompts().get("user_prompt", ""),
        blocked_terms=prefs[PREF_BLOCKED_TERMS] or "",
        api_base_url=prefs[PREF_API_BASE_URL] or DEFAULT_API_BASE_URL,
        ai_timeout=int_or_default(prefs[PREF_AI_TIMEOUT], 30),
    )


@router.put("", response_model=PreferencesResponse)
def update_preferences(
    prefs: PreferencesUpdate,
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Update user preferences.
    Only updates fields that are provided (not None).
    """
    if prefs.locale is not None:
        _set_setting(db, PREF_LOCALE, prefs.locale)

    if prefs.theme is not None:
        _set_setting(db, PREF_THEME, prefs.theme)

    if prefs.summary_language is not None:
        _set_setting(db, PREF_SUMMARY_LANGUAGE, prefs.summary_language)

    if prefs.ai_model is not None:
        _set_setting(db, PREF_AI_MODEL, prefs.ai_model)

    # Data settings (store as string)
    if prefs.feed_update_interval is not None:
        _set_setting(db, PREF_FEED_UPDATE_INTERVAL, str(prefs.feed_update_interval))

    if prefs.max_posts_per_feed is not None:
        _set_setting(db, PREF_MAX_POSTS_PER_FEED, str(prefs.max_posts_per_feed))

    if prefs.max_post_age_days is not None:
        _set_setting(db, PREF_MAX_POST_AGE_DAYS, str(prefs.max_post_age_days))

    if prefs.max_unread_days is not None:
        _set_setting(db, PREF_MAX_UNREAD_DAYS, str(prefs.max_unread_days))

    # Interface settings (store as string)
    if prefs.toast_timeout_seconds is not None:
        _set_setting(db, PREF_TOAST_TIMEOUT, str(prefs.toast_timeout_seconds))

    if prefs.idle_refresh_seconds is not None:
        _set_setting(db, PREF_IDLE_REFRESH, str(prefs.idle_refresh_seconds))

    if prefs.reading_mode is not None:
        _set_setting(db, PREF_READING_MODE, prefs.reading_mode)

    if prefs.split_ratio is not None:
        # Clamp to valid range
        ratio = max(20, min(80, prefs.split_ratio))
        _set_setting(db, PREF_SPLIT_RATIO, str(ratio))

    # Suggestions settings
    if prefs.suggestion_min_tags is not None:
        # Clamp to valid range (1 to tags_per_post)
        max_tags = get_effective_tags_per_post(db)
        min_tags = max(1, min(max_tags, prefs.suggestion_min_tags))
        _set_setting(db, PREF_SUGGESTION_MIN_TAGS, str(min_tags))
        # Clear all suggestions so they get re-evaluated with the new threshold
        from app.services.suggestions import clear_all_suggestions

        clear_all_suggestions(db)

    if prefs.profile_min_tag_freq is not None:
        freq = max(1, min(20, prefs.profile_min_tag_freq))
        _set_setting(db, PREF_PROFILE_MIN_TAG_FREQ, str(freq))
        # Rebuild profile and re-evaluate suggestions
        from app.services.suggestions import clear_all_suggestions
        from app.services.user_profile import invalidate_user_profile

        clear_all_suggestions(db)
        invalidate_user_profile(db)

    # AI keys and prompts
    if prefs.ai_api_keys is not None and prefs.ai_api_keys.strip():
        # Only save if not masked (contains actual keys, not "****")
        if "****" not in prefs.ai_api_keys:
            _set_setting(db, PREF_AI_API_KEYS, prefs.ai_api_keys.strip())

    if prefs.tags_per_post is not None:
        tags_per_post = max(3, min(15, prefs.tags_per_post))
        _set_setting(db, PREF_TAGS_PER_POST, str(tags_per_post))

    if prefs.model_cooldown_minutes is not None:
        cooldown = max(5, min(120, prefs.model_cooldown_minutes))
        _set_setting(db, PREF_MODEL_COOLDOWN, str(cooldown))

    if prefs.system_prompt is not None:
        _set_setting(db, PREF_SYSTEM_PROMPT, prefs.system_prompt)

    if prefs.user_prompt is not None:
        _set_setting(db, PREF_USER_PROMPT, prefs.user_prompt)

    if prefs.api_base_url is not None:
        cleaned_url = prefs.api_base_url.strip().rstrip("/")
        _set_setting(db, PREF_API_BASE_URL, cleaned_url)

    if prefs.ai_timeout is not None:
        _set_setting(db, PREF_AI_TIMEOUT, str(prefs.ai_timeout))

    if prefs.blocked_terms is not None:
        # Clean, sort, and store
        lines = [
            line.strip().lower()
            for line in prefs.blocked_terms.splitlines()
            if line.strip()
        ]
        cleaned = "\n".join(sorted(set(lines)))
        _set_setting(db, PREF_BLOCKED_TERMS, cleaned)
        # Remove existing suggestions for newly-blocked posts
        _unsuggest_blocked_posts(db, lines)

    db.commit()

    # Return updated preferences
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
# Helper for other modules to get settings
# =============================================================================


def _mask_keys(raw: str) -> str:
    """Mask API keys for display: show first 5 and last 4 chars."""
    if not raw:
        return ""
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    masked = []
    for k in keys:
        if len(k) > 12:
            masked.append(k[:5] + "****" + k[-4:])
        else:
            masked.append("****")
    return ", ".join(masked)


def get_effective_ai_api_keys(db: Session) -> list:
    """Get API keys from app_settings."""
    saved = _get_setting(db, PREF_AI_API_KEYS)
    if not saved:
        return []
    return [k.strip() for k in saved.split(",") if k.strip()]


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
    saved = _get_setting(db, PREF_SUMMARY_LANGUAGE)
    return saved or "Brazilian Portuguese"


def get_effective_ai_model(db: Session) -> str:
    saved = _get_setting(db, PREF_AI_MODEL)
    return saved or "llama-3.3-70b"


def get_effective_feed_update_interval(db: Session) -> int:
    saved = _get_setting(db, PREF_FEED_UPDATE_INTERVAL)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return 30


def get_effective_max_posts_per_feed(db: Session) -> int:
    saved = _get_setting(db, PREF_MAX_POSTS_PER_FEED)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return 500


def get_effective_max_post_age_days(db: Session) -> int:
    saved = _get_setting(db, PREF_MAX_POST_AGE_DAYS)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return 365


def get_effective_max_unread_days(db: Session) -> int:
    saved = _get_setting(db, PREF_MAX_UNREAD_DAYS)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return 90


def get_effective_toast_timeout(db: Session) -> int:
    saved = _get_setting(db, PREF_TOAST_TIMEOUT)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return 2


def get_effective_idle_refresh(db: Session) -> int:
    saved = _get_setting(db, PREF_IDLE_REFRESH)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return 180


def get_effective_tags_per_post(db: Session) -> int:
    """Get number of tags per post from app_settings or default (7)."""
    saved = _get_setting(db, PREF_TAGS_PER_POST)
    if saved:
        try:
            return max(3, min(15, int(saved)))
        except (ValueError, TypeError):
            pass
    return 7  # Default: 7 tags per post


def get_effective_model_cooldown(db: Session) -> int:
    saved = _get_setting(db, PREF_MODEL_COOLDOWN)
    if saved:
        try:
            return max(5, min(120, int(saved)))
        except (ValueError, TypeError):
            pass
    return 30


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
    """Get minimum tag frequency for profile inclusion from app_settings or default (2)."""
    saved = _get_setting(db, PREF_PROFILE_MIN_TAG_FREQ)
    if saved:
        try:
            return max(1, min(20, int(saved)))
        except (ValueError, TypeError):
            pass
    return 2  # Default: tag must appear in at least 2 liked posts


def get_effective_ai_timeout(db: Session) -> int:
    """Get AI request timeout from app_settings or default 30s."""
    saved = _get_setting(db, PREF_AI_TIMEOUT)
    if saved:
        try:
            return max(5, int(saved))
        except (ValueError, TypeError):
            pass
    return 30


def get_effective_api_base_url(db: Session) -> str:
    """Get API base URL from app_settings or default."""
    row = db.query(AppSettings).filter(AppSettings.key == PREF_API_BASE_URL).first()
    return (row.value if row and row.value else DEFAULT_API_BASE_URL).rstrip("/")


def get_effective_blocked_terms(db: Session) -> list:
    """Get blocked terms list from app_settings. Returns list of lowercase strings."""
    saved = _get_setting(db, PREF_BLOCKED_TERMS)
    if not saved:
        return []
    return [line.strip() for line in saved.splitlines() if line.strip()]
