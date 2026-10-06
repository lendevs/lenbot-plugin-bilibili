"""Live rooms: observe real sessions; a new session sends a live card, and both changes become scene events."""

import asyncio
from datetime import datetime
import json
import math
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from len_bot.next.plugin import Image, Invocation, PluginContext, Text, background, tool
from .live_protocol import Sample, Subscription, parse_room, subscriptions
from .push_card import Post, render_post

STATUS = {0: '未开播', 1: '直播中', 2: '轮播中'}
MAX_RESPONSE_BYTES = 1_000_000


class LiveFeature:
    def _init_live(self, ctx: PluginContext) -> None:
        self.rooms = subscriptions(ctx.config['rooms'])
        self.live_zone = ZoneInfo(ctx.config['live_source_timezone'])
        url = urlsplit(ctx.config['live_api_url'])
        if url.scheme not in {'http', 'https'} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('live_api_url必须是不带账号/查询/片段的完整HTTP(S)接口地址')
        timeout = ctx.config['request_timeout_seconds']
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('request_timeout_seconds必须为有限正数')
        self.live_client = httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False,
                                             headers={'User-Agent': 'LenBot-Bilibili-Live/2.0'})
        self.samples: dict[int, Sample] = {}
        self.errors: dict[int, dict] = {}

    async def _stop_live(self) -> None:
        await self.live_client.aclose()

    def targets(self, item: Subscription) -> tuple[str, ...]:
        return tuple(scene for scene in item.scenes if scene in self.ctx.scenes)

    def for_scene(self, scene: str, uid: int | None) -> list[Subscription]:
        items = [item for item in self.rooms if scene in item.scenes and scene in self.ctx.scenes
                 and (uid is None or uid == item.uid)]
        if uid is not None and not items:
            raise ValueError(f'当前场景未订阅B站UID {uid}')
        return items

    async def sample(self, item: Subscription) -> Sample:
        async with self.live_client.stream('GET', self.ctx.config['live_api_url'], params={'room_id': item.room_id}) as response:
            body = bytearray()
            async for chunk in response.aiter_bytes():
                if len(body) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ValueError(f'直播房间 {item.room_id} 响应超过 {MAX_RESPONSE_BYTES} 字节；original={bytes(body[:100])!r}')
                body.extend(chunk)
            if response.status_code != 200:
                raise RuntimeError(f'直播房间 {item.room_id} HTTP {response.status_code}: {bytes(body[:600])!r}')
        return parse_room(bytes(body), item, now=self.ctx.now(), zone=self.live_zone)

    @background(every='30s')
    async def poll(self, ctx: PluginContext) -> None:
        # The periodic loop awaits each sample; explicit status reads do not move this baseline.
        for item in self.rooms:
            targets = self.targets(item)
            if not targets:
                continue
            try:
                current = await self.sample(item)
                previous = self.samples.get(item.room_id)
                self.samples[item.room_id] = current
                self.errors.pop(item.room_id, None)
                if previous is None:
                    continue
                new_session = current.room.live_status == 1 and (
                    previous.room.live_status != 1 or previous.started_at != current.started_at)
                ended = previous.room.live_status == 1 and current.room.live_status != 1
                if not new_session and not ended:
                    continue
                card = None
                if new_session:
                    try:
                        card = await self.live_card(item, current)
                    except Exception as error:
                        ctx.report_error(f'房间 {item.room_id} 开播卡片', error)
                for scene in targets:
                    zone = ZoneInfo(ctx.timezone(scene))
                    sampled = datetime.fromtimestamp(current.sampled_at, zone).isoformat()
                    if new_session:
                        change = f'与上次采样相比已出现新直播场次，来源开播时间 {current.started_at.astimezone(zone).isoformat()}'
                        delivered = await self.send_live_card(scene, item, current, card)
                    else:
                        change = f'上次直播场次已结束，当前状态：{STATUS[current.room.live_status]}'
                        delivered = ''
                    await ctx.emit_event(scene, f'{item.name}（B站UID {current.room.uid}，房间 {current.room.room_id}）：{change}。\n'
                                         f'标题：{current.room.title}\n{current.url}\n采样时间：{sampled}。{delivered}'
                                         '这是当时的房间采样，不代表稍后仍在直播；是否回应由当前对话决定。')
            except Exception as error:
                self.errors[item.room_id] = {'at': ctx.now(), 'error': f'{type(error).__name__}: {error}'}
                ctx.report_error(f'房间 {item.room_id} 采样', error)

    async def live_card(self, item: Subscription, sample: Sample) -> bytes:
        room = sample.room
        profile = await self.author_profile(str(item.uid))
        cover = room.user_cover or room.keyframe
        pictures = await self.fetch_images([profile.avatar_url, cover])
        post = Post(kind='live', author=item.name, avatar=pictures.get(profile.avatar_url),
                    published=sample.started_at.timestamp(), title=room.title, cover=pictures.get(cover),
                    meta=' · '.join(part for part in (room.parent_area_name, room.area_name) if part),
                    url=sample.url.removeprefix('https://'), timezone=self.live_zone.key)
        return await asyncio.to_thread(render_post, post, self.fonts)

    async def send_live_card(self, scene: str, item: Subscription, sample: Sample, card: bytes | None) -> str:
        """Send the live card (text when it could not be drawn); returns the fact line for the scene event."""
        headline = f'{item.name} 开播了'
        parts = ([Text(headline), Image(card, f'B站开播卡片：{headline}\n标题：{sample.room.title}\n{sample.url}'),
                  Text(sample.url)] if card is not None else [Text(f'{headline}\n{sample.room.title}\n{sample.url}')])
        try:
            sent = await self.deliver(scene, parts, at_all=item.at_all)
        except Exception as error:
            self.ctx.report_error(f'房间 {item.room_id} 开播通知发送到 {scene}', error)
            return '插件发送开播通知失败。'
        return f'插件已向本群发出开播通知（发送状态 {sent.status}）。'

    @tool('get_live_status', '重新读取本群已订阅房间的实际直播状态；uid为空读取全部，2是轮播；查询不触发开播通知')
    async def status(self, ctx: Invocation, uid: int | None = None) -> str:
        items = []
        for subscription in self.for_scene(ctx.scene, uid):
            sample = await self.sample(subscription)
            items.append({'name': subscription.name, 'requested_room_id': subscription.room_id,
                          'status': STATUS[sample.room.live_status], **sample.model_dump(mode='json')})
        return json.dumps({'items': items, 'note': '仅本群配置订阅对象；每项sampled_at是该次实际读取时间。'}, ensure_ascii=False)

    @tool('get_live_subscriptions', '读取本群真实开播订阅和监测最近样本/错误；不修改设置，不把时间提醒当订阅，不声称旧样本是当前状态')
    async def subscriptions(self, ctx: Invocation, uid: int | None = None) -> str:
        items = []
        for item in self.for_scene(ctx.scene, uid):
            previous = self.samples.get(item.room_id)
            items.append({'name': item.name, 'uid': item.uid, 'room_id': item.room_id,
                          'last_sample': previous.model_dump(mode='json') if previous is not None else None,
                          'last_poll_error': self.errors.get(item.room_id)})
        return json.dumps({'scene': ctx.scene, 'rooms': items, 'interval_seconds': 30,
                           'notification': '变化发场景事件，由大脑决定回应；新进程首样本不补报',
                           'settings': '由运营者在插件面板修改根配置 plugins.bilibili.rooms 和场景启用名单，保存后重载插件生效。'}, ensure_ascii=False)
