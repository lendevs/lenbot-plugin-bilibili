"""Subscriptions changed from chat: the owner adds or removes UP 主 for the current scene, and the change is saved
to the plugin's own settings and applied at once."""

import asyncio
from typing import Annotated

from pydantic import Field

from len_bot.plugin import Invocation, PluginContext, tool
from .client import read_body
from .live_protocol import subscriptions
from .protocol import Envelope, LiveRoom, parse
from .push import follows
from .requests import FollowAdd, LiveAdd, SubscriptionRequest

ROOM_OF_UID = 'https://api.live.bilibili.com/room/v1/Room/getRoomInfoOld'


class ManageFeature:
    def _init_manage(self, ctx: PluginContext) -> None:
        self.subscription_lock = asyncio.Lock()

    @tool('bilibili_subscription', '主人在本群订阅或取消 B 站 UP 主，写入插件配置并立即生效，只有主人发起的请求能执行。'
          'request.action：live_add 开播提醒；live_remove 取消开播提醒；follow_add 推送新动态、新视频和 UP 主本人的评论，'
          '需要插件已登录 B 站账号；follow_remove 取消推送。不确定 UID 时先用 search_bilibili 的 kind=user 搜索，'
          '把候选的名字、UID 和粉丝数告诉主人，确认后再订阅。现有订阅用 bilibili_monitor 查询。',
          summary='由主人在本群订阅或取消 B 站 UP 主', needs_source=True)
    async def manage_subscription(self, ctx: Invocation,
                                  request: Annotated[SubscriptionRequest, Field(description='订阅变更')]) -> dict:
        ctx.require_owner()
        async with self.subscription_lock:
            if request.action == 'live_add':
                return await self.add_room(ctx, request)
            if request.action == 'live_remove':
                return await self.remove_room(ctx, request.uid)
            if request.action == 'follow_add':
                return await self.add_follow(ctx, request)
            return await self.remove_follow(ctx, request.uid)

    async def add_room(self, ctx: Invocation, request: LiveAdd) -> dict:
        rooms = [dict(item) for item in self.ctx.config['rooms']]
        item = next((room for room in rooms if room['uid'] == request.uid), None)
        if item is None:
            item = {'uid': request.uid, 'room_id': await self.room_of(request.uid), 'name': request.name,
                    'scenes': [ctx.scene], 'at_all': bool(request.at_all)}
            rooms.append(item)
        else:
            if ctx.scene in item['scenes'] and request.at_all in (None, item['at_all']):
                return {'changed': False, 'room': item, 'note': '本群已经订阅了这个直播间'}
            item['scenes'] = [*item['scenes'], ctx.scene] if ctx.scene not in item['scenes'] else item['scenes']
            if request.at_all is not None:
                item['at_all'] = request.at_all
        subscriptions(rooms)
        saved = await ctx.update_config({'rooms': rooms})
        self.rooms = subscriptions(saved['rooms'])
        return {'changed': True, 'room': item,
                'note': '已保存；30 秒内开始观察这个直播间，第一次读取的状态作为基线，之后开播时在本群提醒'}

    async def remove_room(self, ctx: Invocation, uid: int) -> dict:
        rooms, removed = without_scene(self.ctx.config['rooms'], uid, ctx.scene)
        if removed is None:
            return {'changed': False, 'note': f'本群没有订阅 UID {uid} 的直播间'}
        saved = await ctx.update_config({'rooms': rooms})
        self.rooms = subscriptions(saved['rooms'])
        if all(room.uid != uid for room in self.rooms):
            self.samples.pop(removed['room_id'], None)
            self.errors.pop(removed['room_id'], None)
        return {'changed': True, 'removed': {'uid': uid, 'name': removed['name']}, 'note': '本群不再收到这个直播间的提醒'}

    async def add_follow(self, ctx: Invocation, request: FollowAdd) -> dict:
        if not self.ctx.config['sessdata']:
            raise PermissionError('关注推送需要先登录 B 站账号：调用 bilibili_login 或发送 /B站登录')
        items = [dict(item) for item in self.ctx.config['follows']]
        flags = {key: getattr(request, key) for key in ('dynamic', 'video', 'comment') if getattr(request, key) is not None}
        item = next((follow for follow in items if follow['uid'] == request.uid), None)
        if item is None:
            item = {'uid': request.uid, 'name': request.name, 'scenes': [ctx.scene],
                    'dynamic': True, 'video': True, 'comment': False, **flags}
            items.append(item)
        else:
            if ctx.scene in item['scenes'] and all(item[key] == value for key, value in flags.items()):
                return {'changed': False, 'follow': item, 'note': '本群已经关注了这个 UP 主'}
            if ctx.scene not in item['scenes']:
                item['scenes'] = [*item['scenes'], ctx.scene]
            item.update(flags)
            if request.name:
                item['name'] = request.name
        if not (item['dynamic'] or item['video'] or item['comment']):
            raise ValueError('动态、视频、评论至少推送一种')
        follows(items)
        saved = await ctx.update_config({'follows': items})
        self.follows = follows(saved['follows'])
        self._ensure_push_tasks()
        return {'changed': True, 'follow': item,
                'note': f'已保存；约 {self.push_config.poll_interval_seconds} 秒读一次，第一次读取作为基线，之后的新内容推送到本群'}

    async def remove_follow(self, ctx: Invocation, uid: int) -> dict:
        items, removed = without_scene(self.ctx.config['follows'], uid, ctx.scene)
        if removed is None:
            return {'changed': False, 'note': f'本群没有关注 UID {uid}'}
        saved = await ctx.update_config({'follows': items})
        self.follows = follows(saved['follows'])
        return {'changed': True, 'removed': {'uid': uid, 'name': removed['name']}, 'note': '本群不再收到这个 UP 主的推送'}

    async def room_of(self, uid: int) -> int:
        async with self.live_client.stream('GET', ROOM_OF_UID, params={'mid': uid}) as response:
            raw = await read_body(response, 1_000_000)
            if response.status_code != 200:
                raise RuntimeError(f'查询 UID {uid} 的直播间 HTTP {response.status_code}')
        envelope = Envelope.model_validate_json(raw)
        if envelope.code != 0:
            raise ValueError(f'查询 UID {uid} 的直播间 code={envelope.code}: {envelope.message}')
        room = parse(envelope.data, LiveRoom, raw)
        if not room.roomStatus or not room.roomid:
            raise ValueError(f'UID {uid} 没有开通直播间')
        return room.roomid


def without_scene(items, uid: int, scene: str) -> tuple[list[dict], dict | None]:
    """The list with ``scene`` removed from this UID's entry; an entry left without scenes is dropped."""
    result, removed = [], None
    for item in items:
        item = dict(item)
        if item['uid'] == uid and scene in item['scenes']:
            removed = item
            item['scenes'] = [value for value in item['scenes'] if value != scene]
            if not item['scenes']:
                continue
        result.append(item)
    return result, removed
