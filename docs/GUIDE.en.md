# DisManager Guide

This guide explains from scratch how to install, configure, and use **DisManager**, without assuming prior Python experience.

---

## 0. Installing from Scratch (if you have never used Python)

If you have never installed a Python package before, follow these steps in order:

### Step 1: Install Python 3.13 or higher
- **Windows:** download Python from [python.org/downloads](https://www.python.org/downloads/). In the installer, check **"Add python.exe to PATH"** before clicking *Install*.
- **Linux (Ubuntu/Debian):** make sure Python 3.13+ and the `venv` module are installed (for example `python3 --version`).

To verify the installation, open a terminal (PowerShell/CMD on Windows or Terminal on Linux) and run:

```sh
python --version
```
*(On Linux it may be `python3 --version`).* It must show `3.13` or higher.

### Step 2: Create a folder for DisManager
Create an empty folder where you want to store your configuration and process directories, then enter it from the terminal:

```sh
mkdir DisManager
cd DisManager
```

### Step 3: Create and activate a virtual environment (`venv`)
A virtual environment isolates DisManager's dependencies from the rest of your system to avoid conflicts:

- **On Windows (PowerShell):**
  ```powershell
  python -m venv .venv
  .\.venv\Scripts\Activate.ps1
  ```
- **On Linux / macOS:**
  ```sh
  python3 -m venv .venv
  source .venv/bin/activate
  ```

When active, you will see `(.venv)` at the beginning of your terminal prompt. *(Whenever you open a new terminal to run DisManager, remember to activate `.venv` again).*

### Step 4: Install DisManager

> **Note:** This project is still in testing and is not yet published on PyPI. Soon you will be able to install it directly with:

```sh
pip install dismanager
```

---

## 1. Creating the Discord Bot

To use DisManager, you need a Discord bot token. If you do not have one yet, follow the official `discord.py` tutorial: [Creating a Bot Account](https://discordpy.readthedocs.io/en/stable/discord.html).

Important points:
1. Enable the required **Privileged Gateway Intents** (especially **Message Content Intent**, needed to read text commands in the panel and console threads).
2. Invite the bot to your server. Granting Administrator permissions (or permissions to manage messages, channels, and threads in the panel channel) is recommended to avoid issues creating the panel and `Console <process>` threads.

---

## 2. Initialization and Local Console Commands

### Initialize (`dismanager init`)
Inside the folder where you will run DisManager (with `.venv` active):

```sh
dismanager init
```

This generates `config.yml` with the basic settings:
- `Bot Token`: secret token of your Discord bot.
- `Bot Prefix`: prefix for Discord commands (for example `!!`).
- `Panel ID`: ID of the Discord text channel where DisManager will publish the panel.
- `Language`: interface language (`en` or `es`).
- `Backups`: maximum number of rotating backups kept per process.

Example `config.yml`:

```yaml
Bot Token: "YOUR_TOKEN_HERE"
Bot Prefix: "!!"
Panel ID: 123456789012345678
Language: en
Backups: 3
```

### Run (`dismanager run`)
Once `config.yml` is edited, start DisManager:

```sh
dismanager run
```

Example startup output:

```text
Initializing DisManager v0.1.0...
Your configuration has been loaded successfully.
Logged in as MyBot#1234!

Commands: start, stop, restart, kill, plreload, adreload, status, exit
>>
```

### Local Console Commands
While DisManager is running, you can type commands at the `>> ` prompt:
- `start <process>` / `start-all`
- `stop <process>` / `stop-all`
- `restart <process>` / `restart-all`
- `kill <process>` / `kill-all`
- `plreload <process>` / `plreload-all`
- `adreload`
- `status`: shows each process's state (`Online`/`Offline`) and RAM usage.
- `exit`: shuts down all processes (waits up to 60 seconds after sending `stop_command`, then force-kills unresponsive ones) and exits DisManager.

Pressing `Ctrl + C` also triggers a graceful shutdown of running processes before exiting.

---

## 3. Folder Structure

Inside the working directory (referred to as `DisManager` in the interface):

- `DisManager/config.yml`: general bot configuration.
- `DisManager/.dismanager/processes.json`: registered process definitions (name, start command, stop command, and blacklist).
- `DisManager/.dismanager/logs/`: DisManager session logs (up to 20 recent sessions, 25 MB max per file) and per-process logs under `.dismanager/logs/processes/<process>/`.
- `DisManager/.addons/`: global DisManager addons.
- `DisManager/.backups/<process>/`: rotating backups for each process.
- `DisManager/<process>/`: working directory for `<process>`.
- `DisManager/<process>/.plugins/`: plugins specific to that process.

---

## 4. Configuring Processes

Once the bot is online, the first step is to register at least one process by clicking **Config** on the Discord panel (up to 15 processes). All changes are saved to `.dismanager/processes.json` and applied immediately.

When creating or editing a process, four fields are configured:

- **`Name` (required):** process name. Determines how it appears on the panel, its thread name (`Console <Name>`), its working folder (`DisManager/<Name>/`), and its logs/backups folders. DisManager creates `DisManager/<Name>/` automatically if it does not exist.
- **`Start command` (required):** exact command used to launch the process (for example `python3 bot.py`, `node index.js`, or `./start.sh`).
  - Internally, DisManager splits the command into arguments (respecting quotes) and launches it directly with `DisManager/<Name>/` as its working directory (`cwd`), without an intermediate shell, wiring its console so you can send commands and read all output.
  - **Recommendation (`.sh` / `.bat`):** if your command uses shell syntax (`&&`, `|`, environment variables) or is very long, place it in a script inside `DisManager/<Name>/` and run the script:
    - On **Linux:** use `./start.sh` (with `chmod +x start.sh`) or `bash start.sh`. Using `exec` on the last line of the `.sh` (e.g. `exec python3 main.py`) is recommended so the main process receives `kill` signals directly and leaves no orphan processes.
    - On **Windows:** use `start.bat` (or `cmd /c start.bat`).
- **`Stop command` (optional):** command sent to the process when requesting a graceful stop (`stop`, `restart`, or when shutting down DisManager).
  - If set (e.g. `stop` or `exit` if your program accepts console commands), `stop` writes that text to the process console so it can save and exit cleanly; during DisManager shutdown (`exit` / `Restart`), it waits up to 60 seconds before force-killing.
  - If left **empty**, there is no graceful stop command: running `stop` immediately performs a `kill` (forceful termination of the process tree).
- **`Blacklist` (optional):** list of filter strings, **one per line**, to prevent spam in Discord.
  - Exact behavior: for every line printed by the process, DisManager checks whether the line **contains** any of those strings as a substring (**case-sensitive**). For example, if you add `[DEBUG]` or `Heartbeat`, any line containing that text anywhere will be skipped in Discord.
  - Important: `blacklist` **only hides the line in the Discord thread**; the line is still recorded in the disk session log (`.dismanager/logs/processes/<Name>/`) and in the file returned by `logs`.
  - If left **empty**, all non-blank process output is sent to the Discord thread.

**Example process configuration:**
- **Name:** `my-bot` (uses `DisManager/my-bot/`)
- **Start command:** `python3 main.py`
- **Stop command:** `exit` *(or empty if the program does not accept console shutdown commands)*
- **Blacklist:**
  ```text
  [DEBUG]
  Heartbeat OK
  ```

---

## 5. Discord Panel

In the channel configured under `Panel ID`, DisManager maintains a single main message showing:
- Host metrics (CPU, RAM, storage, and DisManager RAM).
- List of configured processes with their state (`Running`/`Closed`), RAM usage, and a mention to their `Console <process>` thread.

### Console Threads (`Console <process>`)
Each process has its own thread under the panel channel. Everything the process prints to its console is saved to its history and streamed to this thread (skipping only in Discord any lines that contain one of its `blacklist` entries). Any regular message you type in the thread is sent directly to the process, as if typed into its console.

The thread also recognizes these direct commands (without prefix):
- `start`: starts the process.
- `stop`: sends the configured stop command (or force-kills if none is configured).
- `kill`: forcefully terminates the process and its subprocesses.
- `restart`: stops the process and starts it again.
- `plreload`: reloads plugins in that process's `.plugins/` folder.
- `logs`: uploads a `.log` file with recent in-memory history (up to 8 MB).

The relay packs multiple lines per Discord message to respect API limits. If a process produces output faster than Discord allows and the queue reaches 1000 lines, DisManager keeps new lines, drops the oldest ones, and posts a notice with the omitted count once the queue stabilizes.

### Panel Channel Text Commands
In the panel channel, use the configured prefix (for example `!!`):
- `!!start <process>` / `!!start-all`
- `!!stop <process>` / `!!stop-all`
- `!!kill <process>` / `!!kill-all`
- `!!restart <process>` / `!!restart-all`
- `!!plreload <process>` / `!!plreload-all`
- `!!adreload`: reloads all global addons in `.addons/`.

---

## 6. Panel Buttons

Five buttons appear below the main panel embed:

### Config
Opens the manager to create, edit, or delete processes from Discord (see **4. Configuring Processes** for field details). Deleting a process asks for double confirmation when the option to also delete `DisManager/<Name>/` is checked.

### Backups
Manages rotating backups for the selected process (the process must be stopped to create or restore a backup):
- **`[Make Backup]`:** copies process files to `.backups/<process>/<process> 1` and rotates older backups up to the `Backups` limit in `config.yml`, showing live progress.
- **Select a backup:** restores that backup by replacing the current contents of the process folder (after confirmation).

### Files
Interactive file explorer confined to `DisManager`:
- In folders: navigate via dropdown or index (`Open by index`), jump to a path (`📌` using `DisManager/...`), calculate folder size, create folders, upload up to 10 files, compress the folder to `.zip`, rename, delete by index, or delete the folder.
- In files: shows inline previews (images up to 8 MB, UTF-8 text snippets, or `.zip`/`.tar` content trees), `<` / `>` buttons to step through sibling files, direct download (respecting the server's upload limit), rename, modal text editing (UTF-8 files up to 4000 characters), `.zip` extraction, and deletion.

### Guide
Displays the interactive DisManager user guide directly inside Discord.

### Restart
Requests confirmation to cleanly restart DisManager (stopping active processes before relaunching).

---

## 7. Addons and Plugins System

DisManager can be extended with Python modules:
- **Addons (`.addons/`):** stay active while DisManager is connected. Reloaded with `!!adreload` or `adreload`.
- **Plugins (`<process>/.plugins/`):** stay active while their owning process is running. Reloaded with `plreload`.

Modules can be single `.py` files or packages with `__init__.py` inside `.addons/` or `.plugins/`.

### Lifecycle Hooks
Hooks are optional (typically `async def`; `unload` can be synchronous or `async`). You can optionally inherit from `BaseAddon` or `BasePlugin` from `dismanager.classes` for full type hints:

| Hook | In `BaseAddon` | In `BasePlugin` | When it runs |
| --- | --- | --- | --- |
| `unload` | `unload(self)` | `unload(self)` | Before unloading or reloading |
| `on_addons_load` | `on_addons_load(self)` | — | After addons are loaded or reloaded |
| `on_addons_unload` | `on_addons_unload(self)` | — | Before addons are unloaded |
| `on_plugins_load` | `on_plugins_load(self, process)` | `on_plugins_load(self)` | After a process finishes loading/reloading plugins |
| `on_plugins_unload` | `on_plugins_unload(self, process)` | `on_plugins_unload(self)` | Before a process unloads its plugins |
| `on_process_start` | `on_process_start(self, process)` | `on_process_start(self)` | When the process starts |
| `on_process_stop` | `on_process_stop(self, process)` | `on_process_stop(self)` | When `stop` or `kill` is requested |
| `on_process_crash` | `on_process_crash(self, process)` | `on_process_crash(self)` | When the process exits unexpectedly with a non-zero code |
| `on_process_log` | `on_process_log(self, process, log)` | `on_process_log(self, log)` | For each console line that passes `blacklist` |

### Addon Example (`DisManager/.addons/monitor.py`)
The main class must be named `addon` and receives `client: DisManagerClient`:

```python
from dismanager.classes import BaseAddon, DisManagerClient, ManagedProcess


class addon(BaseAddon):
    def __init__(self, client: DisManagerClient) -> None:
        self.client = client

    async def on_process_start(self, process: ManagedProcess) -> None:
        print(f'Process started: {process.name}')

    async def on_process_crash(self, process: ManagedProcess) -> None:
        recent = process.last_logs(limit=20)
        print(f'{process.name} crashed. Recent lines:\n' + '\n'.join(recent))
```

### Plugin Example (`DisManager/<process>/.plugins/alerts.py`)
The main class must be named `plugin` and receives `process: ManagedProcess`:

```python
from dismanager.classes import BasePlugin, ManagedProcess


class plugin(BasePlugin):
    def __init__(self, process: ManagedProcess) -> None:
        self.process = process

    async def on_process_log(self, log: str) -> None:
        if 'ERROR' in log:
            await self.process.send_to_console(f'Error detected in {self.process.name}: `{log}`')
```

---

## 8. Errors and Logs

If an internal error occurs (in the panel, an addon, or a plugin), DisManager:
1. Writes the full traceback to the current session log under `DisManager/.dismanager/logs/`.
2. Posts a notice in the **`Error Reports`** thread under the panel channel (rate-limited to avoid spam).

Inside `Error Reports`, you can run `<prefix>log` (for example `!!log`) to make DisManager upload the current session `.log` file (up to the last 8 MB in memory).
