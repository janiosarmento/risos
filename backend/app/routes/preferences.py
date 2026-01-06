"""
User preferences routes.
Stores locale, theme, and AI settings in app_settings table.
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


class PreferencesResponse(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None
    summary_language: Optional[str] = None
    cerebras_model: Optional[str] = None


class PreferencesUpdate(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None
    summary_language: Optional[str] = None
    cerebras_model: Optional[str] = None


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
    AI settings return env defaults if not overridden.
    """
    prefs = {
        PREF_LOCALE: None,
        PREF_THEME: None,
        PREF_SUMMARY_LANGUAGE: None,
        PREF_CEREBRAS_MODEL: None,
    }

    rows = (
        db.query(AppSettings)
        .filter(AppSettings.key.in_(prefs.keys()))
        .all()
    )

    for row in rows:
        prefs[row.key] = row.value

    return PreferencesResponse(
        locale=prefs[PREF_LOCALE],
        theme=prefs[PREF_THEME],
        # Return saved value or env default for AI settings
        summary_language=prefs[PREF_SUMMARY_LANGUAGE] or env_settings.summary_language,
        cerebras_model=prefs[PREF_CEREBRAS_MODEL] or env_settings.cerebras_model,
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

    db.commit()

    # Return updated preferences
    return get_preferences(db, user)


# =============================================================================
# Helper for other modules to get AI settings
# =============================================================================

def get_effective_summary_language(db: Session) -> str:
    """Get summary language from app_settings or env default."""
    saved = _get_setting(db, PREF_SUMMARY_LANGUAGE)
    return saved or env_settings.summary_language


def get_effective_cerebras_model(db: Session) -> str:
    """Get Cerebras model from app_settings or env default."""
    saved = _get_setting(db, PREF_CEREBRAS_MODEL)
    return saved or env_settings.cerebras_model
