"""Bilibili collection: public video content, owner-authorized account actions and live-room scene events."""

from len_bot.next.plugin import Plugin, PluginContext

from .content import ContentFeature
from .live import LiveFeature


class Bilibili(LiveFeature, ContentFeature, Plugin):
    def __init__(self, ctx: PluginContext) -> None:
        super().__init__(ctx)
        self._init_content(ctx)
        self._init_live(ctx)

    async def stop(self) -> None:
        try:
            await self._stop_live()
        finally:
            await self._stop_content()
