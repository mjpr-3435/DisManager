from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import version

from .core.config import ConfigError, load_config
from .core.i18n import load_translator
from .core.logs import setup_logging
from .core.paths import ensure_workspace_dirs
from .discord.client import DisManagerClient


def run() -> None:
    print(f"Initializing DisManager v{version('dismanager')}...")
    try:
        config = load_config()
    except ConfigError as exc:
        print(f'Configuration error: {exc}', file=sys.stderr)
        sys.exit(1)

    ensure_workspace_dirs()
    setup_logging()
    translate = load_translator(config.language)
    print(translate('Your configuration has been loaded successfully.'))

    client = DisManagerClient(config, translate)
    try:
        client.run(config.bot_token)
    except Exception as exc:
        print(translate('Error while running discord client: {}').format(exc), file=sys.stderr)
        sys.exit(1)

    if client.restart_requested():
        _relaunch()


def _relaunch() -> None:
    cmd = [sys.executable, '-m', 'dismanager.cli', *sys.argv[1:]]
    if os.name == 'nt':
        sys.exit(subprocess.call(cmd))
    elif os.name == 'posix':
        os.execv(sys.executable, cmd)
