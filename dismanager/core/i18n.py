from __future__ import annotations

import gettext
import logging
from collections.abc import Callable
from pathlib import Path

Translator = Callable[[str], str]

_LOCALES_DIR = Path(__file__).resolve().parent.parent / 'locales'
_logger = logging.getLogger(__name__)


def load_translator(language: str) -> Translator:
    """Return a gettext translation function for the configured language."""
    translations: gettext.NullTranslations
    if language == 'en':
        translations = gettext.NullTranslations()
    else:
        try:
            translations = gettext.translation('app', localedir=str(_LOCALES_DIR), languages=[language])
        except (OSError, ValueError) as exc:
            _logger.warning("Could not load translations for '%s': %s", language, exc)
            translations = gettext.NullTranslations()

    return translations.gettext
