<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/mjpr-3435/DisManager/master/assets/branding/dismanager-logo-dark-bg.svg">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/mjpr-3435/DisManager/master/assets/branding/dismanager-logo-light-bg.svg">
    <img alt="DisManager" src="https://raw.githubusercontent.com/mjpr-3435/DisManager/master/assets/branding/dismanager-logo-dark-bg.svg" width="380">
  </picture>
</p>

# DisManager

[![PyPI](https://img.shields.io/pypi/v/dismanager.svg)](https://pypi.org/project/dismanager/)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-blue)](https://www.python.org/downloads/)
[![License](https://img.shields.io/github/license/mjpr-3435/DisManager.svg)](https://github.com/mjpr-3435/DisManager/blob/main/LICENSE)
[![Español](https://img.shields.io/badge/README-Español-brightgreen)](../README.md)
[![English](https://img.shields.io/badge/README-English-blue)](README.en.md)
[![Guide](https://img.shields.io/badge/Guide-English-blue)](GUIDE.en.md)
[![Guía](https://img.shields.io/badge/Guía-Español-brightgreen)](GUIDE.md)

**DisManager** is a Python application to manage multiple processes and stream their consoles in real time through a Discord bot. It is an evolution of **McDis-RCON** (originally handwritten with contributions from Mauricio and Elí Maciel); much of its adaptation into this new version was done with **Gemini 4 Hydrogen**, combined with handwritten parts and a review of the core logic adapted by the model.

## Features

- **English and Spanish support:** interface and messages configurable in `config.yml`.
- **Interactive Discord panel:** overview of host CPU, RAM, storage, and each process's status.
- **Process control:** start, stop, restart, or force-kill (`start`, `stop`, `restart`, `kill`, and `-all` variants) from the panel channel, console threads, or the local console.
- **Console relay and filtering:** streams `stdout`/`stderr` output to `Console <process>` threads with per-process `blacklist` filtering and downloadable log files (`logs`).
- **Discord process configuration (`Config`):** create, edit, and delete processes directly from the panel (persisted in `.dismanager/processes.json`, up to 15 processes).
- **Backup system (`Backups`):** create and restore rotating per-process backups with live progress updates.
- **File explorer (`Files`):** browse inside the working directory (`DisManager/...`), preview text, images, and `.zip`/`.tar` archive trees, upload files, edit small text files, rename, delete, and compress/extract `.zip` archives.
- **Plugins and Addons:** extend each process (`.plugins/`) or the whole bot (`.addons/`) with lifecycle hooks (`on_process_start`, `on_process_stop`, `on_process_crash`, `on_plugins_load`, `on_plugins_unload`, `on_addons_load`, `on_addons_unload`) and hot-reload (`plreload`, `adreload`).
- **Logging and error reporting:** DisManager session logs in `.dismanager/logs/` and automatic notifications in the `Error Reports` thread (downloadable via `<prefix>log`).
- **Non-intrusive:** runs any program or server using `subprocess.Popen` without modifying its files.

## Installation

Requirements: **Python 3.13 or higher**.

```sh
pip install dismanager
```

## Getting Started

In the folder where you want to store your process directories, initialize the configuration:

```sh
dismanager init
```

This creates `config.yml`, where you should configure:
- `Bot Token`: your Discord bot token.
- `Bot Prefix`: prefix for text commands (for example `!!`).
- `Panel ID`: ID of the Discord text channel where DisManager will publish the panel.
- `Language`: `en` or `es`.
- `Backups`: maximum number of rotating backups per process.

Then start DisManager with:

```sh
dismanager run
```

Once connected, use the **Config** button on the Discord panel to register your processes.

For step-by-step instructions (including installation from scratch, commands, file explorer, backups, and addons/plugins), see the [User Guide](GUIDE.en.md).
