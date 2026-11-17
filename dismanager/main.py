from __future__ import annotations

import logging
import os
import subprocess
import sys
from importlib.metadata import version

from .core.bootstrap.config import ConfigError, load_config
from .core.bootstrap.i18n import _, init_i18n
from .core.bootstrap.logs import LogSession
from .core.bootstrap.paths import ensure_workspace_dirs
from .discord.client import DisManagerClient

_logger = logging.getLogger(__name__)


def run() -> None:
    """Initialize configuration, logging, and run the DisManager Discord client."""
    app_version = version('dismanager')
    print(f'Initializing DisManager v{app_version}...')
    ensure_workspace_dirs()
    log_session             = LogSession()
    _logger.info('Initializing DisManager v%s...', app_version)
    should_restart          = False

    try:
        config = load_config()
        init_i18n(config.language)
        _logger.info('Configuration loaded (language=%s, panel_id=%s).', config.language, config.panel_id)
        print(_('Your configuration has been loaded successfully.'))

        client = DisManagerClient(config, log_session)
        client.run(config.bot_token)
        should_restart = client.restart_requested()
    except ConfigError as exc:
        _logger.error('Configuration error: %s', exc)
        sys.exit(1)
    except Exception as exc:
        log_session.unmute_console()
        _logger.exception('Error while running discord client: %s', exc)
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
