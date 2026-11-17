from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from ....core.bootstrap.i18n import _
from .embed import GuidePage, build_guide_embed, get_guide_pages

if TYPE_CHECKING:
    from ...client import DisManagerClient

_DOCS_BASE_URL = 'https://github.com/mjpr-3435/DisManager/blob/main/docs'


class GuideView(discord.ui.View):
    """Interactive paginated Guide view with section selector and GitHub link."""

    bot: DisManagerClient
    page: int

    def __init__(self, bot: DisManagerClient, *, page: int = 0) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.page = page
        self._rebuild_items()

    def build_embed(self) -> discord.Embed:
        """Build the embed for the currently selected Guide page."""
        return build_guide_embed(self.page, bot_prefix=self.bot.config.bot_prefix)

    async def navigate(self, interaction: discord.Interaction[Any], target_page: int) -> None:
        """Switch to ``target_page`` and update the ephemeral Guide message."""
        pages = get_guide_pages(self.bot.config.bot_prefix)
        self.page = min(max(target_page, 0), len(pages) - 1)
        self._rebuild_items()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    # =========================================
    #            Internal Helpers
    # =========================================

    def _rebuild_items(self) -> None:
        self.clear_items()
        pages = get_guide_pages(self.bot.config.bot_prefix)
        last_idx = len(pages) - 1
        self.page = min(max(self.page, 0), last_idx)

        doc_name = 'GUIDE.en.md' if self.bot.config.language == 'en' else 'GUIDE.md'
        self.add_item(_SectionSelect(pages, self.page))
        self.add_item(_PageButton('<<', target_page=0, disabled=self.page <= 0))
        self.add_item(_PageButton('<', target_page=max(0, self.page - 1), disabled=self.page <= 0))
        self.add_item(_PageButton('>', target_page=min(last_idx, self.page + 1), disabled=self.page >= last_idx))
        self.add_item(_PageButton('>>', target_page=last_idx, disabled=self.page >= last_idx))
        self.add_item(
            discord.ui.Button(
                label=_('Open GUIDE.md'),
                style=discord.ButtonStyle.link,
                url=f'{_DOCS_BASE_URL}/{doc_name}',
                row=1,
            )
        )


class _SectionSelect(discord.ui.Select[GuideView]):
    def __init__(self, pages: list[GuidePage], current_page: int) -> None:
        options = [
            discord.SelectOption(
                label=page.label[:100],
                value=str(idx),
                description=page.summary[:100],
                default=idx == current_page,
            )
            for idx, page in enumerate(pages)
        ]
        super().__init__(placeholder=_('Select a section'), options=options, row=0)

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await self.view.navigate(interaction, int(self.values[0]))


class _PageButton(discord.ui.Button[GuideView]):
    def __init__(self, label: str, *, target_page: int, disabled: bool) -> None:
        super().__init__(label=label, style=discord.ButtonStyle.gray, row=1, disabled=disabled)
        self._target_page = target_page

    async def callback(self, interaction: discord.Interaction[Any]) -> None:
        assert self.view is not None
        await self.view.navigate(interaction, self._target_page)
