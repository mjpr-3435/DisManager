from __future__ import annotations

import os
import subprocess
import sys
from importlib.metadata import version

from .core.bootstrap.config import ConfigError, load_config
from .core.bootstrap.i18n import Translator, load_translator
from .core.bootstrap.logs import LogSession
from .core.bootstrap.paths import ensure_workspace_dirs
from .discord.client import DisManagerClient


def run() -> None:
    print(f"Initializing DisManager v{version('dismanager')}...")
    ensure_workspace_dirs()
    log_session             = LogSession()
    should_restart          = False
    translate: Translator   = load_translator('en')

    try:
        config = load_config()
        translate = load_translator(config.language)
        print(translate('Your configuration has been loaded successfully.'))

        client = DisManagerClient(config, translate, log_session)
        client.run(config.bot_token)
        should_restart = client.restart_requested()
    except ConfigError as exc:
        print(f'Configuration error: {exc}', file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(translate('Error while running discord client: {}').format(exc), file=sys.stderr)
        sys.exit(1)
    finally:
        log_session.close()

    if should_restart:
        _relaunch()


def _relaunch() -> None:
    cmd = [sys.executable, '-m', 'dismanager.cli', *sys.argv[1:]]
    if os.name == 'nt':
        sys.exit(subprocess.call(cmd))
    elif os.name == 'posix':
        os.execv(sys.executable, cmd)
