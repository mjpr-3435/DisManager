from __future__ import annotations

import sys
from importlib.metadata import version

from .client import DisManagerClient
from .config import ConfigError, load_config
from .i18n import load_translator


def run() -> None:
    print(f"Initializing DisManager v{version('dismanager')}...")
    try:
        config = load_config()
    except ConfigError as exc:
        print(f'Configuration error: {exc}', file=sys.stderr)
        sys.exit(1)

    translate = load_translator(config.language)
    print(translate('Your configuration has been loaded successfully.'))

    client = DisManagerClient(config, translate)
    try:
        client.run(config.bot_token)
    except Exception as exc:
        print(translate('Error while running discord client: {}').format(exc), file=sys.stderr)
        sys.exit(1)
