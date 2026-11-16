from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

import discord

from ....core.backups import BackupEntry, list_backups, process_backups_dir
from ....core.paths import BACKUPS_DIR
from ...utils import confirmation_request
from .embed import format_bytes, to_dismanager_path

if TYPE_CHECKING:
    from ....core.processes import ManagedProcess
    from ...client import DisManagerClient
    from .views import FilesView


class BackupsView(discord.ui.View):
    """Interactive backup manager view for a process's `.backups/<process>` directory."""

    def __init__(
        self,
        bot: DisManagerClient,
        process: ManagedProcess,
        *,
        files_view: FilesView,
    ) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.process = process
        self.files_view = files_view
        self.entries: list[BackupEntry] = []
        self._build_items()

    def build_embed(self) -> discord.Embed:
        """Render the backups summary embed for the current process."""
        backups_dir = process_backups_dir(self.process.name)
        title_path = to_dismanager_path(backups_dir, self.files_view.root)

        if not self.entries:
            description = f'*{self.bot._("No backups found.")}*'
        else:
            lines: list[str] = []
            for entry in self.entries:
                size_label = format_bytes(entry.size_bytes)
                date_label = entry.created_at or self.bot._('Unknown')
                lines.append(
                    f'📦 **{entry.name}**\n'
                    f'> `{self.bot._("Disk Usage")}:` {size_label}\n'
                    f'> `{self.bot._("Date")}:` {date_label}'
                )
            description = '\n\n'.join(lines)

        embed = discord.Embed(
            title=f'📁 {title_path}',
            description=description,
            color=0x2B2D31,
        )
        embed.set_footer(text=self.bot._('Max backups: {}').format(self.bot._config.backups))
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
                attachments=[],
            )

    def _build_items(self) -> None:
        self.clear_items()
        self.entries = list_backups(self.process.name)
        self.add_item(_BackupSelect(self.bot, self.entries))
        self.add_item(_BackButton(self.bot, row=1))
        self.add_item(_UpdateButton(self.bot, row=1))
        self.add_item(_FilesButton(self.bot, row=1))


class _BackupSelect(discord.ui.Select[BackupsView]):
    def __init__(self, bot: DisManagerClient, entries: list[BackupEntry]) -> None:
        options = [
            discord.SelectOption(
                label=bot._('➕ [Make Backup]'),
                value='__make__',
                description=bot._('Create a new rotating backup'),
            )
        ]
        for entry in entries[:24]:
            desc = f'{format_bytes(entry.size_bytes)} • {entry.created_at or bot._("Unknown")}'
            options.append(
                discord.SelectOption(
                    label=f'📦 {entry.name}'[:100],
                    value=entry.name,
                    description=desc[:100],
                )
            )
        super().__init__(placeholder=bot._('Select a backup'), options=options, row=0)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        view = self.view
        bot = view.bot
        process = view.process

        if process.is_running():
            await interaction.response.send_message(
                bot._('✖ Process `{}` is running. Stop it before managing backups.').format(process.name),
                ephemeral=True,
            )
            return

        selected = self.values[0]
        source_message_id = interaction.message.id if interaction.message is not None else None

        if selected == '__make__':
            prompt = bot._('Create a new backup for `{}`?').format(process.name)
            await confirmation_request(
                prompt,
                interaction=interaction,
                on_confirmation=lambda confirm_i: _run_backup_job(
                    confirm_interaction=confirm_i,
                    parent_interaction=interaction,
                    parent_message_id=source_message_id,
                    view=view,
                    worker=process.make_backup,
                    progress_template=bot._('🔄 `[{}]:` [{}/{}] files have been processed...'),
                    done_message=bot._('✔ Backup for `{}` created successfully.').format(process.name),
                ),
            )
            return

        entry = next((item for item in view.entries if item.name == selected), None)
        if entry is None:
            await interaction.response.send_message(bot._('✖ Backup not found.'), ephemeral=True)
            return

        prompt = bot._(
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
                worker=lambda progress: process.restore_backup(entry.path, progress),
                progress_template=bot._('🔄 `[{}]:` [{}/{}] files have been unpacked...'),
                done_message=bot._('✔ Backup `{}` restored successfully.').format(entry.name),
            ),
        )


async def _run_backup_job(
    *,
    confirm_interaction: discord.Interaction[Any],
    parent_interaction: discord.Interaction[Any],
    parent_message_id: int | None,
    view: BackupsView,
    worker: Callable[[list[int]], Any],
    progress_template: str,
    done_message: str,
) -> None:
    progress = [0, 0]
    task = asyncio.create_task(asyncio.to_thread(worker, progress))
    last_snapshot: tuple[int, int] | None = None

    while not task.done():
        snapshot = (progress[0], progress[1])
        if snapshot != last_snapshot and snapshot[1] > 0:
            last_snapshot = snapshot
            with contextlib.suppress(discord.HTTPException):
                await confirm_interaction.edit_original_response(
                    content=progress_template.format(view.process.name, snapshot[0], snapshot[1]),
                )
        await asyncio.sleep(1.0)

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


class _BackButton(discord.ui.Button[BackupsView]):
    def __init__(self, bot: DisManagerClient, *, row: int) -> None:
        super().__init__(label=bot._('Back'), style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await self.view.files_view.navigate(interaction, BACKUPS_DIR.resolve())


class _UpdateButton(discord.ui.Button[BackupsView]):
    def __init__(self, bot: DisManagerClient, *, row: int) -> None:
        super().__init__(label=bot._('Update'), style=discord.ButtonStyle.secondary, row=row)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await interaction.response.defer()
        await self.view.refresh(interaction)


class _FilesButton(discord.ui.Button[BackupsView]):
    def __init__(self, bot: DisManagerClient, *, row: int) -> None:
        super().__init__(label=bot._('Files'), style=discord.ButtonStyle.primary, row=row)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        target: Path = process_backups_dir(self.view.process.name)
        await self.view.files_view.navigate(interaction, target, open_backups_ui=False)
