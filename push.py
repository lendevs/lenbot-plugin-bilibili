"""Followed uploaders: dynamics and videos polled per UID, their own comments captured through the journal.

Every new item goes to the subscribed scenes as one card. Polling cursors, the comment journal and delivery
retries follow the AstrBot A-SOUL plugin; only the targets changed from message origins to LenBot scenes.
"""

import asyncio
from dataclasses import asdict, replace
from io import BytesIO
import json
import random
import time
from pathlib import Path
from typing import Annotated

import httpx
from PIL import Image as Picture, ImageOps
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from len_bot.next.plugin import Image, Invocation, Mention, PluginContext, Sent, Text, tool
from .card_kit import Fonts, Run
from .comment_capture import CommentCaptureCoordinator, CommentCaptureError, CommentRetryPolicy, CommentWorkScheduler
from .comment_journal import CommentJournal
from .gateway import (COMMENT_RESOURCE_REFRESH_INTERVAL_SECONDS, BilibiliAuthorCardProfile, BilibiliGateway,
                      BilibiliMonitorService, BilibiliNotification, build_bilibili_push_config)
from .push_card import KIND, ACTION, Note, Post, render_post

Positive = Annotated[int, Field(gt=0)]
Scene = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_-]*:(group|private):[^:\s/\\]+$')]

FONT = Path(__file__).parent / 'assets' / 'font.ttf'
# Symbols and kaomoji the bundled font lacks; only fonts present on this machine are used.
FALLBACK_FONTS = ('/Library/Fonts/Arial Unicode.ttf', '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
                  '/System/Library/Fonts/Apple Symbols.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
                  '/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf',
                  '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
CONTENT_POLL_TIMEOUT_SECONDS = 90
CATALOG_TIMEOUT_SECONDS = 30
PROFILE_TTL_SECONDS = 6 * 3600
PROFILE_TIMEOUT_SECONDS = 20
VIDEO_STATS_TIMEOUT_SECONDS = 12
CARD_TTL_SECONDS = 600
REPORT_INTERVAL_SECONDS = 600
MAX_IMAGE_BYTES = 12_000_000
MAX_IMAGE_SIDE = 1600
IDLE_SECONDS = 30


class Follow(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    uid: Positive
    name: str = ''
    scenes: list[Scene] = Field(min_length=1)
    dynamic: bool = True
    video: bool = True
    comment: bool = False

    @field_validator('scenes')
    @classmethod
    def unique_scenes(cls, scenes: list[str]) -> list[str]:
        if len(scenes) != len(set(scenes)):
            raise ValueError('同一UP主的scenes不能重复')
        return scenes


def follows(raw: list[dict]) -> list[Follow]:
    items = TypeAdapter(list[Follow]).validate_python(raw)
    if len({item.uid for item in items}) != len(items):
        raise ValueError('follows不能重复配置同一UID；合并该UP主的scenes')
    return items


class DeliveryFailed(RuntimeError):
    """The host reported a failed send; the item stays pending and is retried."""


def classify(error: Exception) -> CommentCaptureError:
    """Retry category for one failure (risk control, credential, deleted, network, api or internal)."""
    def number(value):
        try:
            return int(value) if value is not None else None
        except (TypeError, ValueError):
            return None
    if isinstance(error, DeliveryFailed):
        return CommentCaptureError('delivery', '', str(error)[:160] or '发送失败')
    code, status = number(getattr(error, 'code', None)), number(getattr(error, 'status', None))
    if status == 412 or code in {-352, -412}:
        return CommentCaptureError('risk_control', str(status if status == 412 else code), '请求被 B 站风控拒绝')
    if status in {401, 403} or code in {-101, -102}:
        return CommentCaptureError('credential', str(status if status in {401, 403} else code), 'B 站登录状态无效')
    message = ' '.join(str(getattr(error, 'msg', '') or getattr(error, 'message', '') or error or '').split())[:160]
    code_text = str(code if code is not None else status or '')
    if CommentJournal.is_deleted_comment_error('api', message, code=code_text):
        return CommentCaptureError('gone', code_text, message or '评论已删除或不存在')
    name = type(error).__name__
    if status is not None or name in {'NetworkException', 'TimeoutError', 'ClientError'} or isinstance(error, httpx.HTTPError):
        return CommentCaptureError('network', str(status or ''), 'B 站网络请求失败')
    if code is not None or name in {'ResponseCodeException', 'ApiException'}:
        return CommentCaptureError('api', str(code or ''), message or 'B 站接口返回错误')
    return CommentCaptureError('internal', name, message or name)


class PushFeature:
    def _init_push(self, ctx: PluginContext) -> None:
        config = ctx.config
        self.follows = follows(config['follows'])
        if self.follows and not config['sessdata']:
            raise ValueError('关注推送需要填写 SESSDATA：空间动态和评论接口未登录时会被风控拒绝')
        self.push_config = build_bilibili_push_config({
            'enabled': True, 'poll_interval_seconds': config['push_poll_seconds'], 'request_client': 'httpx',
            'push_live': False, 'sessdata': config['sessdata'], 'bili_jct': config['bili_jct'],
            'buvid3': config['buvid3'], 'dedeuserid': str(config['account_uid'] or ''),
            'comment_request_interval_seconds': config['comment_request_seconds']})
        self.gateway = BilibiliGateway(request_client='httpx', credential_data=self.push_config.credential_data,
                                       comment_request_interval_seconds=self.push_config.comment_request_interval_seconds)
        self.monitor = BilibiliMonitorService(self.gateway)
        self.comment_journal: CommentJournal | None = None
        self.retry_policy = CommentRetryPolicy(random_value=random.random)
        self.comment_scheduler = CommentWorkScheduler()
        self.fonts = Fonts(FONT, FONT, fallbacks=tuple(Path(path) for path in FALLBACK_FONTS if Path(path).is_file()),
                           fake_bold=True)
        self.media_client = httpx.AsyncClient(timeout=config['request_timeout_seconds'], follow_redirects=True,
                                              trust_env=False, headers={
                                                  'User-Agent': 'Mozilla/5.0 LenBot-Bilibili/2.0',
                                                  'Referer': 'https://www.bilibili.com/'})
        self.push_state: dict = {}
        self.profiles: dict[str, BilibiliAuthorCardProfile] = {}
        self.push_status: dict[str, dict] = {}
        self._emoji: dict[str, Picture.Image] = {}
        self._cards: dict[str, tuple[float, bytes]] = {}
        self._reported: dict[str, float] = {}
        self._state_lock = asyncio.Lock()

    async def _start_push(self) -> None:
        self.push_state = await self.ctx.get_kv('push_state', {})
        self.profiles = {uid: BilibiliAuthorCardProfile(**value)
                         for uid, value in (await self.ctx.get_kv('profiles', {})).items()}
        if any(item.dynamic or item.video for item in self.follows):
            self.ctx.start_task('动态轮询', self._content_loop())
        if any(item.comment for item in self.follows):
            self.comment_journal = CommentJournal(self.ctx.data_dir / 'comments.sqlite3')
            self.comment_capture = CommentCaptureCoordinator(gateway=self.gateway, journal=self.comment_journal,
                                                             classify_error=classify, retry_policy=self.retry_policy)
            self.ctx.start_task('评论资源发现', self._catalog_loop())
            self.ctx.start_task('评论抓取', self._comment_loop())

    async def _stop_push(self) -> None:
        try:
            await self.media_client.aclose()
        finally:
            if self.comment_journal is not None:
                self.comment_journal.close()

    # ---------- targets and reporting ----------

    def follow_targets(self, item: Follow) -> tuple[str, ...]:
        return tuple(scene for scene in item.scenes if scene in self.ctx.scenes)

    def comment_uids(self) -> list[str]:
        return [str(item.uid) for item in self.follows if item.comment and self.follow_targets(item)]

    def comment_scenes(self) -> list[str]:
        return sorted({scene for item in self.follows if item.comment for scene in self.follow_targets(item)})

    def report(self, where: str, error: Exception) -> None:
        # Loops retry on their own; the panel gets one record per place every ten minutes.
        now = time.monotonic()
        if now - self._reported.get(where, -REPORT_INTERVAL_SECONDS) >= REPORT_INTERVAL_SECONDS:
            self._reported[where] = now
            self.ctx.report_error(where, error)

    # ---------- dynamics and videos ----------

    async def _content_loop(self) -> None:
        due: dict[int, float] = {}
        while True:
            items = [item for item in self.follows if (item.dynamic or item.video) and self.follow_targets(item)]
            now = time.monotonic()
            ready = [item for item in items if due.get(item.uid, 0) <= now]
            if not ready:
                wait = min((due[item.uid] - now for item in items), default=IDLE_SECONDS)
                await asyncio.sleep(min(max(wait, 1), IDLE_SECONDS))
                continue
            item = min(ready, key=lambda follow: due.get(follow.uid, 0))
            status = self.push_status.setdefault(str(item.uid), {})
            status['last_attempt_at'] = self.ctx.now()
            try:
                await asyncio.wait_for(self.poll_follow(item), CONTENT_POLL_TIMEOUT_SECONDS)
                status['last_success_at'] = self.ctx.now()
                status.pop('last_error', None)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                kind = classify(error)
                status['last_error'] = {'at': self.ctx.now(), 'category': kind.category, 'message': kind.message}
                self.report(f'UP主 {item.uid} 动态轮询', error)
            due[item.uid] = time.monotonic() + self.push_config.poll_interval_seconds
            await asyncio.sleep(self.push_config.task_gap_seconds)

    async def poll_follow(self, item: Follow) -> None:
        scenes = self.follow_targets(item)
        if not scenes:
            return
        uid = str(item.uid)
        config = replace(self.push_config, push_dynamic=item.dynamic, push_video=item.video, push_live=False)
        seed = next((self.push_state[scene][uid] for scene in scenes if self.push_state.get(scene, {}).get(uid)), None)
        snapshot = await self.monitor.fetch_uid_snapshot(config=config, uid=uid, previous_state=seed)
        fallback = next((post.author for post in snapshot.dynamics if post.author.name or post.author.avatar_url),
                        BilibiliAuthorCardProfile(uid=uid, name=snapshot.author_name))
        snapshot = replace(snapshot, author_profile=await self.author_profile(uid, fallback))
        for scene in scenes:
            plan = self.monitor.plan_uid_deliveries(config=config, snapshot=snapshot,
                                                    previous_state=self.push_state.get(scene, {}).get(uid, {}))
            for delivery in plan.deliveries:
                try:
                    await self.send_notification(scene, delivery.notification)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    # The cursor stays before this item, so the next poll sends it again.
                    self.report(f'UP主 {uid} 推送到 {scene}', error)
                    break
                await self.commit_state(scene, uid, delivery.uid_state)
            else:
                await self.commit_state(scene, uid, plan.final_state)

    async def commit_state(self, scene: str, uid: str, state: dict) -> None:
        keys = ('author_name', 'last_dynamic_id', 'last_dynamic_created_at', 'recent_dynamic_ids')
        async with self._state_lock:
            current = self.push_state.setdefault(scene, {}).setdefault(uid, {})
            updated = {**current, **{key: state[key] for key in keys if key in state}}
            if updated != current:
                self.push_state[scene][uid] = json.loads(json.dumps(updated))
                await self.ctx.set_kv('push_state', self.push_state)

    # ---------- comments ----------

    async def _catalog_loop(self) -> None:
        while True:
            try:
                worked = bool(self.comment_uids()) and await self.refresh_catalog(int(time.time()))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.report('评论资源发现', error)
                worked = False
            await asyncio.sleep(0 if worked else IDLE_SECONDS)

    async def refresh_catalog(self, now: int) -> bool:
        uids = self.comment_uids()
        self.comment_journal.retire_unconfigured_owners(uids, now)
        for uid in uids:
            if not self.comment_journal.catalog_refresh_due(uid, now, COMMENT_RESOURCE_REFRESH_INTERVAL_SECONDS):
                continue
            self.comment_journal.begin_catalog_refresh(uid, now)

            async def discover(uid=uid):
                name = await self.gateway.get_comment_resource_owner_name(uid)
                return name, await self.monitor.discover_comment_resources(uid, name)
            try:
                name, resources = await asyncio.wait_for(discover(), CATALOG_TIMEOUT_SECONDS)
            except asyncio.CancelledError:
                raise
            except Exception as error:
                kind = classify(error)
                delay = self.retry_policy.delay_seconds(self.comment_journal.catalog_retry_count(uid))
                self.comment_journal.fail_catalog_refresh(uid, kind.category, kind.message, next_attempt_at=now + delay)
                self.report(f'UP主 {uid} 评论资源发现', error)
                return True
            self.comment_journal.sync_resource_catalog(uid, name, resources, now)
            return True
        return False

    async def _comment_loop(self) -> None:
        while True:
            try:
                worked = bool(self.comment_uids()) and await self.comment_step(int(time.time()))
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.report('评论抓取', error)
                worked = False
            await asyncio.sleep(0 if worked else 1)

    async def comment_step(self, now: int) -> bool:
        """One unit of work: deliver one captured comment, or scan one page."""
        journal = self.comment_journal
        scenes = self.comment_scenes()
        journal.cancel_ineligible_deliveries(scenes)
        if await self.comment_capture.deliver_one(self.send_comment, now):
            return True
        journal.activate_reply_gaps(now)
        uids = self.comment_uids()
        task = self.comment_scheduler.next_task(journal, now, uids)
        if task is None:
            return False
        await self.comment_capture.run_scan_task(task, target_uids=uids, target_origins=scenes, now=now)
        return True

    async def send_comment(self, scene: str, notification: BilibiliNotification) -> None:
        item = next((follow for follow in self.follows if str(follow.uid) == notification.uid), None)
        if item is None or not item.comment or scene not in self.follow_targets(item):
            return  # The author's comments are no longer sent to this scene.
        await self.send_notification(scene, notification)

    # ---------- cards ----------

    async def author_profile(self, uid: str, fallback: BilibiliAuthorCardProfile | None = None
                             ) -> BilibiliAuthorCardProfile:
        cached = self.profiles.get(uid)
        if cached is not None and time.time() - cached.fetched_at < PROFILE_TTL_SECONDS:
            return cached
        try:
            profile = await asyncio.wait_for(self.gateway.get_user_card_profile(uid), PROFILE_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.report(f'UP主 {uid} 资料', error)
            return cached or fallback or BilibiliAuthorCardProfile(uid=uid)
        previous = cached or fallback
        if previous is not None:
            profile = replace(profile, name=previous.name if profile.name in {'', uid} and previous.name else profile.name,
                              avatar_url=profile.avatar_url or previous.avatar_url)
        self.profiles[uid] = profile
        await self.ctx.set_kv('profiles', {key: asdict(value) for key, value in self.profiles.items()})
        return profile

    async def send_notification(self, scene: str, notification: BilibiliNotification, *,
                                at_all: bool = False) -> Sent:
        author = notification.author_profile.name or notification.author_name or notification.uid
        action = notification.comment_action_text or ACTION[card_kind(notification)]
        headline = f'{author} {action}'
        try:
            card = await self.notification_card(notification)
            parts = [Text(headline), Image(card, describe(notification, headline)), Text(notification.url)]
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.report(f'{KIND[card_kind(notification)]}卡片渲染', error)
            parts = [Text('\n'.join(part for part in (headline, notification.text[:500], notification.url) if part))]
        return await self.deliver(scene, parts, at_all=at_all)

    async def deliver(self, scene: str, parts: list, *, at_all: bool = False) -> Sent:
        sent = await self.ctx.send_parts(scene, [Mention('all'), *parts] if at_all else parts)
        if sent.status == 'failed' and at_all:
            # The group may forbid @全体 or have used up today's count; send the card without it.
            sent = await self.ctx.send_parts(scene, parts)
        if sent.status == 'failed':
            raise DeliveryFailed(sent.report)
        return sent

    async def notification_card(self, notification: BilibiliNotification) -> bytes:
        key = f'{notification.kind}:{notification.content_id}'
        cached = self._cards.get(key)
        if cached is not None and time.monotonic() - cached[0] < CARD_TTL_SECONDS:
            return cached[1]
        if notification.kind == 'video' and notification.video_bvid:
            try:
                stats = await asyncio.wait_for(self.gateway.get_video_engagement_stats(notification.video_bvid),
                                               VIDEO_STATS_TIMEOUT_SECONDS)
                notification = replace(notification, stats=stats)
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # The dynamic's own counts are close enough for the card.
        if notification.kind == 'comment':
            fallback = BilibiliAuthorCardProfile(uid=notification.uid, name=notification.author_name)
            notification = replace(notification, author_profile=await self.author_profile(notification.uid, fallback))
        post = await self.build_post(notification)
        card = await asyncio.to_thread(render_post, post, self.fonts)
        self._cards = {k: v for k, v in self._cards.items() if time.monotonic() - v[0] < CARD_TTL_SECONDS}
        self._cards[key] = (time.monotonic(), card)
        return card

    async def build_post(self, notification: BilibiliNotification) -> Post:
        forwarded = notification.forwarded
        kind = card_kind(notification)
        images = [] if forwarded is not None else notification.image_urls[:9]
        if kind == 'video':
            images = []
        urls = [notification.author_profile.avatar_url, notification.cover_url, *images,
                *(node.image_url for node in notification.rich_nodes if node.kind == 'emoji')]
        if forwarded is not None:
            urls += [*forwarded.image_urls[:9], *(node.image_url for node in forwarded.rich_nodes if node.kind == 'emoji')]
        pictures = await self.fetch_images(urls)
        stats = {}
        if kind != 'comment':
            s = notification.stats
            stats = {'like': s.like_count, 'comment': s.comment_count, 'forward': s.forward_count}
        note = None
        if kind == 'comment':
            note = Note(f'{notification.comment_resource_owner_name}的{notification.comment_resource_kind}',
                        notification.comment_resource_title)
        elif notification.additional_card.kind == 'reserve':
            card = notification.additional_card
            note = Note(card.subtitle or '预约', card.title)
        quoted = None
        if forwarded is not None:
            quoted = Post(kind='dynamic', author=forwarded.author_name, avatar=None, published=0,
                          runs=runs(forwarded.rich_nodes, forwarded.text, pictures), title=forwarded.title,
                          images=[pictures[url] for url in forwarded.image_urls[:9] if pictures.get(url)],
                          timezone=self.push_timezone)
        text = '' if notification.text == '发布了新动态' and not notification.rich_nodes else notification.text
        nodes = notification.rich_nodes
        if kind == 'video' and notification.title and text.startswith(notification.title):
            # A video dynamic usually repeats the title, which the card already shows under the cover.
            text, nodes = text[len(notification.title):].strip(), []
        return Post(kind=kind, author=notification.author_profile.name or notification.author_name or notification.uid,
                    avatar=pictures.get(notification.author_profile.avatar_url), published=notification.published_at,
                    runs=runs([node for node in nodes if note is None or node.kind != 'attachment'], text, pictures),
                    images=[pictures[url] for url in images if pictures.get(url)],
                    title=notification.title if kind == 'video' else '', cover=pictures.get(notification.cover_url),
                    stats=stats, quoted=quoted, note=note, action=notification.comment_action_text,
                    url=notification.url.removeprefix('https://'), timezone=self.push_timezone)

    @property
    def push_timezone(self) -> str:
        return self.ctx.config['live_source_timezone']

    async def fetch_images(self, urls) -> dict[str, Picture.Image]:
        wanted = list(dict.fromkeys(url for url in urls if url))
        limit = asyncio.Semaphore(6)

        async def one(url: str):
            if url in self._emoji:
                return url, self._emoji[url]
            async with limit:
                try:
                    return url, await self.fetch_image(url)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    return url, None  # A missing picture leaves a gray placeholder.
        found = dict(await asyncio.gather(*(one(url) for url in wanted)))
        return {url: image for url, image in found.items() if image is not None}

    async def fetch_image(self, url: str) -> Picture.Image:
        async with self.media_client.stream('GET', url) as response:
            response.raise_for_status()
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > MAX_IMAGE_BYTES:
                    raise ValueError(f'图片超过 {MAX_IMAGE_BYTES} 字节：{url}')
        image = await asyncio.to_thread(decode, bytes(body))
        if image.width <= 160 and image.height <= 160:
            # Small pictures are emoji and stickers; they repeat across posts.
            if len(self._emoji) > 512:
                self._emoji.clear()
            self._emoji[url] = image
        return image

    async def follow_status(self, ctx: Invocation) -> dict:
        items = [{'uid': item.uid, 'name': item.name, 'dynamic': item.dynamic, 'video': item.video,
                  'comment': item.comment, **self.push_status.get(str(item.uid), {})}
                 for item in self.follows if ctx.scene in item.scenes]
        journal = None if self.comment_journal is None else {'pending_deliveries': self.comment_journal.pending_delivery_count()}
        return {'scene': ctx.scene, 'follows': items, 'interval_seconds': self.push_config.poll_interval_seconds,
                           'comment_journal': journal,
                           'settings': '由运营者在插件面板修改 plugins.bilibili.follows，保存后重载插件生效。'}


def card_kind(notification: BilibiliNotification) -> str:
    if notification.kind in {'video', 'comment', 'live'}:
        return notification.kind
    return 'repost' if notification.forwarded is not None else 'dynamic'


def runs(nodes, text: str, pictures: dict) -> list[Run]:
    if not nodes:
        return [Run(text)] if text else []
    return [Run(image=pictures[node.image_url]) if node.kind == 'emoji' and pictures.get(node.image_url)
            else Run(node.text) for node in nodes]


def describe(notification: BilibiliNotification, headline: str) -> str:
    lines = [f'B站{KIND[card_kind(notification)]}卡片：{headline}']
    if notification.kind == 'comment':
        lines.append(f'所在：{notification.comment_resource_owner_name}的{notification.comment_resource_kind}'
                     f'《{notification.comment_resource_title}》')
    if notification.kind == 'video' and notification.title:
        lines.append(f'标题：{notification.title}')
    if notification.text and notification.text != '发布了新动态':
        lines.append(notification.text[:400])
    if notification.forwarded is not None:
        lines.append(f'转发自 @{notification.forwarded.author_name}：{notification.forwarded.text[:200]}')
    lines.append(notification.url)
    return '\n'.join(lines)


def decode(data: bytes) -> Picture.Image:
    image = Picture.open(BytesIO(data))
    image.seek(0)  # Animated stickers use their first frame.
    image = ImageOps.exif_transpose(image).convert('RGBA')
    image.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    return image
