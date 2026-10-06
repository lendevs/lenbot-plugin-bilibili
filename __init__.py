"""Bilibili collection: public video content, owner-authorized account actions, live-room scene events and
cards for followed uploaders' dynamics, videos and comments."""

from len_bot.next.plugin import Plugin, PluginContext

from .content import ContentFeature
from .live import LiveFeature
from .push import PushFeature


class Bilibili(PushFeature, LiveFeature, ContentFeature, Plugin):
    def __init__(self, ctx: PluginContext) -> None:
        super().__init__(ctx)
        self._init_content(ctx)
        self._init_live(ctx)
        self._init_push(ctx)

    async def start(self) -> None:
        await self._start_push()

    async def stop(self) -> None:
        try:
            await self._stop_push()
        finally:
            try:
                await self._stop_live()
            finally:
                await self._stop_content()
