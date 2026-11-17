from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


class ConfigError(Exception):
    """Raised when the DisManager configuration file cannot be read or is invalid."""


@dataclass(frozen=True, slots=True)
class DisManagerConfig:
    """Validated runtime configuration for DisManager."""

    bot_token   : str
    bot_prefix  : str
    panel_id    : int
    language    : str
    backups     : int


def load_config() -> DisManagerConfig:
    """Load and validate a YAML configuration file from disk."""
    config_path = Path('config.yml')
    yaml = YAML(typ='safe')

    try:
        content = config_path.read_text(encoding='utf-8')
    except OSError as exc:
        raise ConfigError(f"The file '{config_path}' could not be opened: {exc}") from exc

    try:
        raw: object = yaml.load(content)
    except YAMLError as exc:
        raise ConfigError(f"The file '{config_path}' contains invalid YAML: {exc}") from exc

    return _validate_config(raw)


# =========================================
#            Internal Helpers
# =========================================


def _validate_config(raw: object) -> DisManagerConfig:
    if not isinstance(raw, Mapping):
        raise ConfigError('Configuration root must be a YAML mapping.')

    return DisManagerConfig(
        bot_token=_require_non_empty_str(raw, 'Bot Token'),
        bot_prefix=_parse_bot_prefix(raw),
        panel_id=_parse_panel_id(raw),
        language=_parse_language(raw),
        backups=_parse_backups(raw),
    )


def _is_strict_int(value: object) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool)


def _require_non_empty_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"The '{key}' variable must be a non-empty string.")
    return value.strip()


def _parse_bot_prefix(data: Mapping[str, Any]) -> str:
    default_prefix = '!!'
    value = data.get('Bot Prefix')
    if value is None:
        return default_prefix
    if not isinstance(value, str) or not value.strip():
        raise ConfigError("The 'Bot Prefix' variable must be a non-empty string or null.")
    return value


def _parse_panel_id(data: Mapping[str, Any]) -> int:
    value = data.get('Panel ID')
    if not _is_strict_int(value) or value <= 0:
        raise ConfigError("The 'Panel ID' variable must be a positive integer.")
    return value


def _parse_language(data: Mapping[str, Any]) -> str:
    allowed_languages: tuple[str, ...] = ('en', 'es')
    value = data.get('Language')
    if not isinstance(value, str) or value not in allowed_languages:
        allowed = ', '.join(allowed_languages)
        raise ConfigError(f"The 'Language' variable must be one of the following: {allowed}.")
    return value


def _parse_backups(data: Mapping[str, Any]) -> int:
    min_backups = 1
    max_backups = 5
    value = data.get('Backups')
    if not _is_strict_int(value):
        raise ConfigError(
            f"The 'Backups' variable must be an integer between {min_backups} and {max_backups}."
        )
    if not (min_backups <= value <= max_backups):
        raise ConfigError(
            f"The 'Backups' variable must be between {min_backups} and {max_backups}, not {value}."
        )
    return value
