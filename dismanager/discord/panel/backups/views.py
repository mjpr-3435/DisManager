from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import discord

from ....core.bootstrap.i18n import _
from ....core.format import format_bytes
from ...utils import confirmation_request

if TYPE_CHECKING:
    from ....core.managed_process import BackupEntry, ManagedProcess
    from ...client import DisManagerClient


class BackupsView(discord.ui.View):
    """Interactive backup manager view for configured processes."""

    def __init__(self, bot: DisManagerClient, process: ManagedProcess | None = None) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        processes = bot.processes
        self.process: ManagedProcess | None = process if process is not None else (processes[0] if processes else None)
        self.entries: list[BackupEntry] = []
        self._build_items()

    def build_embed(self) -> discord.Embed:
        """Render the backups summary embed for the selected process."""
        if self.process is None:
            return discord.Embed(
                title=f'📦 {_("Backups")}',
                description=f'*{_("No processes configured.")}*',
                color=0x2B2D31,
            )

        if not self.entries:
            description = f'*{_("No backups found.")}*'
        else:
            lines: list[str] = []
            for entry in self.entries:
                size_label = format_bytes(entry.size_bytes)
                lines.append(
                    f'📦 **{entry.name}**\n'
                    f'> `{_("Disk Usage")}:` {size_label}\n'
                    f'> `{_("Date")}:` {entry.created_at}'
                )
            description = '\n\n'.join(lines)

        embed = discord.Embed(
            title=f'📦 {_("Backups")} — {self.process.name}',
            description=description,
            color=0x2B2D31,
        )
        embed.set_footer(text=_('Max backups: {}').format(self.bot.config.backups))
        return embed

    async def refresh(self, interaction: discord.Interaction[Any], *, message_id: int | None = None) -> None:
        """Reload backup entries and update the Discord message."""
        self._build_items()
        embed = self.build_embed()
        target_id = message_id or (interaction.message.id if interaction.message is not None else None)
        if target_id is None:
            return
        with contextlib.suppress(discord.HTTPException):
            await interaction.followup.edit_message(
                message_id=target_id,
                embed=embed,
                view=self,
            )

    def _build_items(self) -> None:
        self.clear_items()
        processes = self.bot.processes
        if self.process is not None:
            self.process = self.bot.find_process(self.process.name)
        if self.process is None and processes:
            self.process = processes[0]

        if not processes or self.process is None:
            self.entries = []
            return

        self.entries = self.process.list_backups()
        self.add_item(_ProcessSelect(processes, self.process))
        self.add_item(_BackupSelect(self.entries))
        self.add_item(_UpdateButton(row=2))


# =========================================
#            Internal Helpers
# =========================================


class _ProcessSelect(discord.ui.Select[BackupsView]):
    def __init__(self, processes: Sequence[ManagedProcess], current: ManagedProcess) -> None:
        options = [
            discord.SelectOption(
                label=proc.name[:100],
                value=proc.name,
                default=proc.name == current.name,
            )
            for proc in processes[:25]
        ]
        super().__init__(placeholder=_('Select a process'), options=options, row=0)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await interaction.response.defer()
        self.view.process = self.view.bot.find_process(self.values[0])
        await self.view.refresh(interaction)


class _BackupSelect(discord.ui.Select[BackupsView]):
    def __init__(self, entries: list[BackupEntry]) -> None:
        options = [
            discord.SelectOption(
                label=_('➕ [Make Backup]'),
                value='__make__',
                description=_('Create a new rotating backup'),
            )
        ]
        for entry in entries[:24]:
            desc = f'{format_bytes(entry.size_bytes)} • {entry.created_at}'
            options.append(
                discord.SelectOption(
                    label=f'📦 {entry.name}'[:100],
                    value=entry.name,
                    description=desc[:100],
                )
            )
        super().__init__(placeholder=_('Select a backup'), options=options, row=1)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        view = self.view
        process = view.process
        if process is None:
            await interaction.response.defer()
            await view.refresh(interaction)
            return

        if process.is_running():
            await interaction.response.send_message(
                _('✖ Process `{}` is running. Stop it before managing backups.').format(process.name),
                ephemeral=True,
            )
            return

        selected = self.values[0]
        source_message_id = interaction.message.id if interaction.message is not None else None

        if selected == '__make__':
            prompt = _('Create a new backup for `{}`?').format(process.name)
            await confirmation_request(
                prompt,
                interaction=interaction,
                on_confirmation=lambda confirm_i: _run_backup_job(
                    confirm_interaction=confirm_i,
                    parent_interaction=interaction,
                    parent_message_id=source_message_id,
                    view=view,
                    worker=process.make_backup,
                    progress_template=_('🔄 `[{}]:` [{}/{}] files have been processed...'),
                    done_message=_('✔ Backup for `{}` created successfully.').format(process.name),
                ),
            )
            return

        entry = next((item for item in view.entries if item.name == selected), None)
        if entry is None:
            await interaction.response.send_message(_('✖ Backup not found.'), ephemeral=True)
            return

        prompt = _(
            'Restore `{}` into `{}`? Current files in `{}` will be replaced.'
        ).format(entry.name, process.name, process.name)
        await confirmation_request(
            prompt,
            interaction=interaction,
            on_confirmation=lambda confirm_i: _run_backup_job(
                confirm_interaction=confirm_i,
                parent_interaction=interaction,
                parent_message_id=source_message_id,
                view=view,
                worker=lambda progress: process.restore_backup(entry, progress),
                progress_template=_('🔄 `[{}]:` [{}/{}] files have been unpacked...'),
                done_message=_('✔ Backup `{}` restored successfully.').format(entry.name),
            ),
        )


async def _run_backup_job(
    *,
    confirm_interaction: discord.Interaction[Any],
    parent_interaction: discord.Interaction[Any],
    parent_message_id: int | None,
    view: BackupsView,
    worker: Callable[[Callable[[int, int], None]], Any],
    progress_template: str,
    done_message: str,
) -> None:
    assert view.process is not None
    process_name = view.process.name
    latest = (0, 0)

    await confirm_interaction.response.edit_message(
        content=progress_template.format(process_name, 0, '?'),
        embed=None,
        view=None,
    )

    def on_progress(done: int, total: int) -> None:
        nonlocal latest
        latest = (done, total)

    task = asyncio.create_task(asyncio.to_thread(worker, on_progress))
    last_snapshot: tuple[int, int] | None = None

    while not task.done():
        await asyncio.sleep(0.8)
        if task.done():
            break
        snapshot = latest
        if snapshot != last_snapshot and snapshot[1] > 0:
            last_snapshot = snapshot
            with contextlib.suppress(discord.HTTPException):
                await confirm_interaction.edit_original_response(
                    content=progress_template.format(process_name, snapshot[0], snapshot[1]),
                )

    try:
        await task
    except Exception as exc:
        with contextlib.suppress(discord.HTTPException):
            await confirm_interaction.edit_original_response(content=f'✖ {exc}')
        return

    with contextlib.suppress(discord.HTTPException):
        await confirm_interaction.edit_original_response(content=done_message)

    await view.refresh(parent_interaction, message_id=parent_message_id)

    with contextlib.suppress(discord.Forbidden, discord.HTTPException):
        await confirm_interaction.user.send(done_message)


class _UpdateButton(discord.ui.Button[BackupsView]):
    def __init__(self, *, row: int) -> None:
        super().__init__(label=_('Update'), style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await interaction.response.defer()
        await self.view.refresh(interaction)
