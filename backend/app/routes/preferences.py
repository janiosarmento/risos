"""
User preferences routes.
Stores locale, theme, AI settings, and data settings in app_settings table.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.config import settings as env_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models import AppSettings

router = APIRouter(prefix="/preferences", tags=["preferences"])

# Keys used in app_settings
PREF_LOCALE = "pref_locale"
PREF_THEME = "pref_theme"
PREF_SUMMARY_LANGUAGE = "pref_summary_language"
PREF_CEREBRAS_MODEL = "pref_cerebras_model"
# Data settings
PREF_FEED_UPDATE_INTERVAL = "pref_feed_update_interval"
PREF_MAX_POSTS_PER_FEED = "pref_max_posts_per_feed"
PREF_MAX_POST_AGE_DAYS = "pref_max_post_age_days"
PREF_MAX_UNREAD_DAYS = "pref_max_unread_days"


class PreferencesResponse(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None
    summary_language: Optional[str] = None
    cerebras_model: Optional[str] = None
    # Data settings (returned as integers)
    feed_update_interval: Optional[int] = None
    max_posts_per_feed: Optional[int] = None
    max_post_age_days: Optional[int] = None
    max_unread_days: Optional[int] = None


class PreferencesUpdate(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None
    summary_language: Optional[str] = None
    cerebras_model: Optional[str] = None
    # Data settings
    feed_update_interval: Optional[int] = None
    max_posts_per_feed: Optional[int] = None
    max_post_age_days: Optional[int] = None
    max_unread_days: Optional[int] = None


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
        PREF_CEREBRAS_MODEL,
        PREF_FEED_UPDATE_INTERVAL,
        PREF_MAX_POSTS_PER_FEED,
        PREF_MAX_POST_AGE_DAYS,
        PREF_MAX_UNREAD_DAYS,
    ]

    prefs = {k: None for k in all_keys}

    rows = (
        db.query(AppSettings)
        .filter(AppSettings.key.in_(all_keys))
        .all()
    )

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
        summary_language=prefs[PREF_SUMMARY_LANGUAGE] or env_settings.summary_language,
        cerebras_model=prefs[PREF_CEREBRAS_MODEL] or env_settings.cerebras_model,
        # Data settings
        feed_update_interval=int_or_default(
            prefs[PREF_FEED_UPDATE_INTERVAL], env_settings.feed_update_interval_minutes
        ),
        max_posts_per_feed=int_or_default(
            prefs[PREF_MAX_POSTS_PER_FEED], env_settings.max_posts_per_feed
        ),
        max_post_age_days=int_or_default(
            prefs[PREF_MAX_POST_AGE_DAYS], env_settings.max_post_age_days
        ),
        max_unread_days=int_or_default(
            prefs[PREF_MAX_UNREAD_DAYS], env_settings.max_unread_days
        ),
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

    if prefs.cerebras_model is not None:
        _set_setting(db, PREF_CEREBRAS_MODEL, prefs.cerebras_model)

    # Data settings (store as string)
    if prefs.feed_update_interval is not None:
        _set_setting(db, PREF_FEED_UPDATE_INTERVAL, str(prefs.feed_update_interval))

    if prefs.max_posts_per_feed is not None:
        _set_setting(db, PREF_MAX_POSTS_PER_FEED, str(prefs.max_posts_per_feed))

    if prefs.max_post_age_days is not None:
        _set_setting(db, PREF_MAX_POST_AGE_DAYS, str(prefs.max_post_age_days))

    if prefs.max_unread_days is not None:
        _set_setting(db, PREF_MAX_UNREAD_DAYS, str(prefs.max_unread_days))

    db.commit()

    # Return updated preferences
    return get_preferences(db, user)


# =============================================================================
# Helper for other modules to get settings
# =============================================================================

def get_effective_summary_language(db: Session) -> str:
    """Get summary language from app_settings or env default."""
    saved = _get_setting(db, PREF_SUMMARY_LANGUAGE)
    return saved or env_settings.summary_language


def get_effective_cerebras_model(db: Session) -> str:
    """Get Cerebras model from app_settings or env default."""
    saved = _get_setting(db, PREF_CEREBRAS_MODEL)
    return saved or env_settings.cerebras_model


def get_effective_feed_update_interval(db: Session) -> int:
    """Get feed update interval from app_settings or env default."""
    saved = _get_setting(db, PREF_FEED_UPDATE_INTERVAL)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return env_settings.feed_update_interval_minutes


def get_effective_max_posts_per_feed(db: Session) -> int:
    """Get max posts per feed from app_settings or env default."""
    saved = _get_setting(db, PREF_MAX_POSTS_PER_FEED)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return env_settings.max_posts_per_feed


def get_effective_max_post_age_days(db: Session) -> int:
    """Get max post age from app_settings or env default."""
    saved = _get_setting(db, PREF_MAX_POST_AGE_DAYS)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return env_settings.max_post_age_days


def get_effective_max_unread_days(db: Session) -> int:
    """Get max unread days from app_settings or env default."""
    saved = _get_setting(db, PREF_MAX_UNREAD_DAYS)
    if saved:
        try:
            return int(saved)
        except (ValueError, TypeError):
            pass
    return env_settings.max_unread_days
