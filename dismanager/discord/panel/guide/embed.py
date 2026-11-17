from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import version

import discord

from ....core.bootstrap.i18n import _

_GUIDE_COLOUR = 0x2F3136
_REPO_URL = 'https://github.com/mjpr-3435/DisManager'


@dataclass(frozen=True, slots=True)
class GuidePage:
    """Metadata and rendered sections for a single interactive Guide page."""

    label: str
    summary: str
    title: str
    description: str
    fields: tuple[tuple[str, str], ...] = ()


def get_guide_pages(bot_prefix: str) -> list[GuidePage]:
    """Return the ordered list of Guide pages localized for the active language."""
    return [
        GuidePage(
            label=_('Overview'),
            summary=_('Introduction and quick index of all sections'),
            title=_('Overview'),
            description=_(
                'DisManager lets you manage multiple processes and stream their consoles through Discord '
                'without modifying your programs.\n\n'
                'Use the **dropdown menu** below to jump to a section or the **navigation buttons** to '
                'read page by page. You can also open the full `GUIDE.md` on GitHub.'
            ),
            fields=(
                (
                    _('Sections'),
                    _(
                        '• **1. Getting Started & Local Console** — `init`, `config.yml`, `run`, `>>` commands\n'
                        '• **2. Process Configuration** — `Name`, `Start`, `Stop`, `Blacklist`\n'
                        '• **3. Panel & Console Threads** — `Console` threads, prefix commands, relay queue\n'
                        '• **4. Backups & Files** — Rotating backups, explorer, previews, upload, `.zip`\n'
                        '• **5. Addons, Plugins & Errors** — Hooks, hot-reload, `Error Reports`'
                    ),
                ),
            ),
        ),
        GuidePage(
            label=_('1. Getting Started & Local Console'),
            summary=_('Initialization, config.yml, and terminal commands'),
            title=_('1. Getting Started & Local Console'),
            description=_(
                'Run `dismanager init` in your working folder to generate `config.yml`, fill in your bot '
                'settings (`Bot Token`, `Bot Prefix`, `Panel ID`, `Language`, `Backups`), and start with '
                '`dismanager run`.'
            ),
            fields=(
                (
                    _('Folder Layout'),
                    _(
                        '• `DisManager/<process>/` — Working directory for each process\n'
                        '• `DisManager/<process>/.plugins/` — Per-process Python plugins\n'
                        '• `DisManager/.addons/` — Global bot addons\n'
                        '• `DisManager/.backups/` — Rotating process backups\n'
                        '• `DisManager/.dismanager/` — `processes.json` and logs'
                    ),
                ),
                (
                    _('Local Console Commands (>>)'),
                    _(
                        '• `start`, `stop`, `restart`, `kill`, `plreload` (`<name>` or `-all`)\n'
                        '• `adreload` — Reloads global addons\n'
                        '• `status` — Shows online state and RAM usage\n'
                        '• `exit` — Gracefully stops processes (60s timeout) and exits'
                    ),
                ),
            ),
        ),
        GuidePage(
            label=_('2. Process Configuration'),
            summary=_('How Name, Start command, Stop command, and Blacklist work'),
            title=_('2. Process Configuration'),
            description=_(
                'Use the **Config** button on the panel to register, edit, or delete up to 15 processes '
                '(saved in `.dismanager/processes.json`).'
            ),
            fields=(
                (
                    _('Fields'),
                    _(
                        '• **Name:** Display name, `Console <Name>` thread, and `DisManager/<Name>/` folder.\n'
                        '• **Start command:** Exact command launched directly inside `DisManager/<Name>/` '
                        '(without an intermediate shell). For shell syntax (`&&`, `|`, env vars), put it in a '
                        '`.sh` (use `exec ...` on Linux) or `.bat` script.\n'
                        '• **Stop command (optional):** Sent to the process console on `stop`/`restart`. If left '
                        'empty, `stop` forces a `kill`.\n'
                        '• **Blacklist (optional):** One filter per line (case-sensitive substring). Matching '
                        'lines are hidden in Discord only, while still saved to `.log` files.'
                    ),
                ),
            ),
        ),
        GuidePage(
            label=_('3. Panel & Console Threads'),
            summary=_('Using Console threads, prefix commands, and relay queue'),
            title=_('3. Panel & Console Threads'),
            description=_(
                'The main panel shows host CPU, RAM, storage, and each process status with a link to its '
                '`Console <process>` thread.'
            ),
            fields=(
                (
                    _('Inside Console <process>'),
                    _(
                        'Any normal message you type is sent directly to the process console. You can also type:\n'
                        '• `start`, `stop`, `kill`, `restart`, `plreload`\n'
                        '• `logs` — Uploads the recent `.log` buffer (up to 8 MB)'
                    ),
                ),
                (
                    _('Panel Channel Commands & Relay'),
                    _(
                        '• `{0}start`, `{0}stop`, `{0}kill`, `{0}restart`, `{0}plreload` (`<name>` or `-all`)\n'
                        '• `{0}adreload` — Reloads global addons\n'
                        '• Relay packs multiple lines per message; if the queue hits 1000 lines, oldest lines '
                        'are dropped and a notice reports how many were omitted.'
                    ).format(bot_prefix),
                ),
            ),
        ),
        GuidePage(
            label=_('4. Backups & Files'),
            summary=_('Managing rotating backups and the Files explorer'),
            title=_('4. Backups & Files'),
            description=_(
                'Use the **Backups** and **Files** buttons on the panel to manage process data safely '
                'without leaving Discord.'
            ),
            fields=(
                (
                    _('Backups'),
                    _(
                        'The process must be stopped before creating or restoring a backup.\n'
                        '• **[Make Backup]:** Copies files to `.backups/<process>/<process> 1` and rotates '
                        'older backups up to `Backups` in `config.yml`.\n'
                        '• **Restore:** Replaces current files in `DisManager/<process>/` with live progress.'
                    ),
                ),
                (
                    _('Files Explorer'),
                    _(
                        'Confined to `DisManager/...` with pagination (`99` entries/page) and path jump (`📌`).\n'
                        '• **Folders:** Open/delete by index, calculate size, create folder, upload up to 10 '
                        'files, compress to `.zip`, rename, delete.\n'
                        '• **Files:** Inline previews (images ≤ 8 MB, UTF-8 text, `.zip`/`.tar` trees), '
                        'download, rename, edit (≤ 4000 chars), unzip, delete.'
                    ),
                ),
            ),
        ),
        GuidePage(
            label=_('5. Addons, Plugins & Errors'),
            summary=_('Extending DisManager with Python hooks and Error Reports'),
            title=_('5. Addons, Plugins & Errors'),
            description=_(
                'Place `.py` files or packages (`__init__.py`) in `.addons/` (class `addon(BaseAddon)`) '
                'or `<process>/.plugins/` (class `plugin(BasePlugin)`).'
            ),
            fields=(
                (
                    _('Lifecycle Hooks'),
                    _(
                        '• `unload()` — Cleanup before unload/reload\n'
                        '• `on_addons_load` / `on_addons_unload` (addons)\n'
                        '• `on_plugins_load` / `on_plugins_unload`\n'
                        '• `on_process_start` / `on_process_stop` / `on_process_crash`\n'
                        '• `on_process_log` — Filtered console lines'
                    ),
                ),
                (
                    _('Error Reports'),
                    _(
                        'Unhandled exceptions are logged to `.dismanager/logs/` and notified in the '
                        '`Error Reports` thread. Use `{0}log` inside that thread to download the session log.'
                    ).format(bot_prefix),
                ),
            ),
        ),
    ]


def build_guide_embed(page_idx: int, *, bot_prefix: str) -> discord.Embed:
    """Build the Discord embed for a specific Guide page index."""
    pages = get_guide_pages(bot_prefix)
    clamped = min(max(page_idx, 0), len(pages) - 1)
    page = pages[clamped]

    embed = discord.Embed(
        title=f"> DisManager v{version('dismanager')} — {page.title}",
        colour=_GUIDE_COLOUR,
        url=_REPO_URL,
        description=page.description,
    )
    for name, value in page.fields:
        embed.add_field(name=name, value=value, inline=False)

    embed.set_footer(text=_('Page {}/{}').format(clamped + 1, len(pages)))
    return embed
