"""Bilibili collection: public video content, owner-authorized account reads, live-room scene events and
cards for followed uploaders' dynamics, videos and comments."""

from typing import Annotated
from pydantic import Field
from len_bot.plugin import Invocation, Plugin, PluginContext, tool
from .requests import MonitorRequest

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

    @tool('bilibili_monitor', '查询本群的 B 站订阅，只返回数据。request.action：status 现在去读订阅直播间的开播状态；'
          'subscriptions 本群的直播订阅设置和最近一次记录；follows 本群关注的 UP 主和推送开关。',
          summary='查询 B 站订阅配置或当前直播状态')
    async def query_monitor(self, ctx: Invocation,
                      request: Annotated[MonitorRequest, Field(description='直播状态或订阅配置查询')]) -> dict:
        if request.action == 'status':
            return await self.status(ctx, request.uid)
        if request.action == 'subscriptions':
            return await self.subscriptions(ctx, request.uid)
        return await self.follow_status(ctx)

    def unavailable_tools(self, scene: str) -> dict[str, str]:
        config = self.ctx.config
        unavailable = {}
        if not config['buvid3']:
            unavailable['search_bilibili'] = '视频搜索需要配置 buvid3'
        if not config['account_read_enabled']:
            unavailable['bilibili_account_read'] = '账号读取未开启'
        return unavailable
