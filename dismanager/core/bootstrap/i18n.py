from __future__ import annotations

import gettext
import logging
from pathlib import Path

_LOCALES_DIR = Path(__file__).resolve().parent.parent.parent / 'locales'
_logger = logging.getLogger(__name__)
_translations: gettext.NullTranslations = gettext.NullTranslations()


def init_i18n(language: str) -> None:
    """Load gettext translations for ``language`` into the active module translator."""
    global _translations
    if language == 'en':
        _translations = gettext.NullTranslations()
        return

    try:
        _translations = gettext.translation('app', localedir=str(_LOCALES_DIR), languages=[language])
    except (OSError, ValueError) as exc:
        _logger.warning("Could not load translations for '%s': %s", language, exc)
        _translations = gettext.NullTranslations()


def _(text: str) -> str:
    """Translate ``text`` using the active DisManager language."""
    return _translations.gettext(text)
