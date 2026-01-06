"""
User preferences routes.
Stores locale and theme in app_settings table.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.database import get_db
from app.dependencies import get_current_user
from app.models import AppSettings

router = APIRouter(prefix="/preferences", tags=["preferences"])

# Keys used in app_settings
PREF_LOCALE = "pref_locale"
PREF_THEME = "pref_theme"


class PreferencesResponse(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None


class PreferencesUpdate(BaseModel):
    locale: Optional[str] = None
    theme: Optional[str] = None


@router.get("", response_model=PreferencesResponse)
def get_preferences(
    db: Session = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    """
    Get user preferences (locale and theme).
    Returns empty values if not set.
    """
    locale = None
    theme = None

    settings = (
        db.query(AppSettings)
        .filter(AppSettings.key.in_([PREF_LOCALE, PREF_THEME]))
        .all()
    )

    for setting in settings:
        if setting.key == PREF_LOCALE:
            locale = setting.value
        elif setting.key == PREF_THEME:
            theme = setting.value

    return PreferencesResponse(locale=locale, theme=theme)


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
        existing = (
            db.query(AppSettings)
            .filter(AppSettings.key == PREF_LOCALE)
            .first()
        )
        if existing:
            existing.value = prefs.locale
        else:
            db.add(AppSettings(key=PREF_LOCALE, value=prefs.locale))

    if prefs.theme is not None:
        existing = (
            db.query(AppSettings)
            .filter(AppSettings.key == PREF_THEME)
            .first()
        )
        if existing:
            existing.value = prefs.theme
        else:
            db.add(AppSettings(key=PREF_THEME, value=prefs.theme))

    db.commit()

    # Return updated preferences
    return get_preferences(db, user)
