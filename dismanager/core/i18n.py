from __future__ import annotations

import gettext
from collections.abc import Callable
from pathlib import Path

Translator = Callable[[str], str]

LOCALES_DIR = Path(__file__).resolve().parent.parent / 'locales'


def load_translator(language: str) -> Translator:
    """Return a gettext translation function for the configured language."""
    translations: gettext.NullTranslations
    if language == 'en':
        translations = gettext.NullTranslations()
    else:
        try:
            translations = gettext.translation('app', localedir=str(LOCALES_DIR), languages=[language])
        except FileNotFoundError:
            translations = gettext.NullTranslations()

    return translations.gettext
