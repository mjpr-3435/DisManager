from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from .main import run

TEMPLATES_DIR = Path(__file__).resolve().parent / 'templates'


def init() -> None:
    """Initialize the project by copying the default configuration template."""
    target = Path('config.yml')
    source = TEMPLATES_DIR / 'config.yml'
    if not target.exists():
        shutil.copy(source, target)

    print('✔ Successfully generated config.yml.')


def main() -> None:
    parser = argparse.ArgumentParser(description='DisManager CLI')
    subparsers = parser.add_subparsers(dest='command')

    init_parser = subparsers.add_parser('init', help='Initialize the project')
    init_parser.set_defaults(func=init)

    run_parser = subparsers.add_parser('run', help='Run DisManager')
    run_parser.set_defaults(func=run)

    args = parser.parse_args()
    if args.command:
        args.func()
    else:
        parser.print_help()
