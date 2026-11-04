"""Followed uploaders through the public plugin harness: real gateway parsing on fake SDK pages, real cards."""

import asyncio
import copy
import json
from pathlib import Path
import re
import time

import pytest

from len_bot.plugin import Image, Mention, Text
from len_bot.plugin_testing import PluginTest

PACKAGE = Path(__file__).parents[1]
SCENE = "onebot:group:80001"
UID = 672342685
PAGE = json.loads((Path(__file__).parent / "data" / "dynamics.json").read_text())


def dynamics_page(source, now: int, ages: dict[str, int]) -> dict:
    """The recorded page with pictures served locally and publish times moved to ``now - age``."""
    text = json.dumps(copy.deepcopy(PAGE), ensure_ascii=False)
    count = iter(range(10_000))
    text = re.sub(r'(?:https?:)?//i\d\.hdslb\.com/[^"\s]+', lambda _: f"{source.url}/img/{next(count)}.png", text)
    page = json.loads(text)
    page["items"] = [item for item in page["items"] if item["id_str"] in ages]
    for item in page["items"]:
        item["modules"]["module_author"]["pub_ts"] = now - ages[item["id_str"]]
    return page


def config(**follow) -> dict:
    return {"follows": [{"uid": UID, "name": "乃琳", "scenes": [SCENE], **follow}], "sessdata": "synthetic",
            "comment_request_seconds": 0.5}


async def until(condition, timeout: float = 20) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_new_dynamics_are_sent_once_as_cards(source, sdk):
    now = int(time.time())
    sdk.users[UID] = {"name": "乃琳Queen", "face": f"{source.url}/img/face.png"}
    sdk.dynamics[UID] = dynamics_page(source, now, {
        "1184775739475492867": 60, "1184672110523449360": 120, "1184302893660897313": 180})
    async with PluginTest(PACKAGE, config=config()) as bot:
        await until(lambda: len(bot.deliveries) == 3)
        headlines = [delivery.parts[0].text for delivery in bot.deliveries]
        assert headlines == ["乃琳Queen 投稿了视频", "乃琳Queen 转发了动态", "乃琳Queen 发布了动态"]
        for delivery in bot.deliveries:
            text, card, url = delivery.parts
            assert isinstance(card, Image) and card.data[:8] == b"\x89PNG\r\n\x1a\n"
            assert url.text.startswith("https://")
        assert "乃琳Queen" in bot.deliveries[2].parts[1].description

        plugin = bot.host.plugins["bilibili"]
        await plugin.instance.poll_follow(plugin.instance.follows[0])
        assert len(bot.deliveries) == 3
        state = plugin.instance.push_state[SCENE][str(UID)]
        assert state["last_dynamic_id"] == "1184775739475492867"


@pytest.mark.asyncio
async def test_old_dynamics_are_not_replayed_on_first_poll(source, sdk):
    now = int(time.time())
    sdk.dynamics[UID] = dynamics_page(source, now, {"1184775739475492867": 3600, "1184672110523449360": 7200})
    async with PluginTest(PACKAGE, config=config()) as bot:
        await until(lambda: ("dynamics", UID) in sdk.calls)
        plugin = bot.host.plugins["bilibili"]
        await until(lambda: "last_success_at" in plugin.instance.push_status.get(str(UID), {}))
        assert bot.deliveries == []


@pytest.mark.asyncio
async def test_switched_off_kinds_are_skipped(source, sdk):
    now = int(time.time())
    sdk.dynamics[UID] = dynamics_page(source, now, {"1184775739475492867": 60, "1184302893660897313": 120})
    async with PluginTest(PACKAGE, config=config(dynamic=False)) as bot:
        await until(lambda: len(bot.deliveries) == 1)
        await asyncio.sleep(0.2)
        assert [delivery.parts[0].text for delivery in bot.deliveries] == ["乃琳Queen 投稿了视频"]


@pytest.mark.asyncio
async def test_own_comment_on_own_dynamic_becomes_card(source, sdk):
    now = int(time.time())
    sdk.users[UID] = {"name": "乃琳Queen", "face": ""}
    sdk.dynamics[UID] = dynamics_page(source, now, {"1184775739475492867": 600})
    async with PluginTest(PACKAGE, config=config(dynamic=False, video=False, comment=True)) as bot:
        bilibili = bot.host.plugins["bilibili"].instance
        # Drive the comment work by hand with a moved clock; the plugin's own loop would race for the same item.
        for task in [task for task in bot.host.tasks if task.get_name() == "bilibili:评论抓取"]:
            task.cancel()
        await until(lambda: bilibili.comment_journal is not None
                    and sum(bilibili.comment_journal.status(now).lifecycle_counts.values()))
        # The first scan of a new resource only records what already exists.
        for _ in range(10):
            await bilibili.comment_step(now + 1)
        assert bot.deliveries == []
        sdk.comments[389437928] = [
            {"rpid": 9001, "rpid_str": "9001", "member": {"mid": str(UID), "uname": "乃琳Queen"},
             "content": {"message": "今晚见～"}, "ctime": now + 200, "root": 0, "parent": 0, "rcount": 0,
             "replies": []},
            {"rpid": 9002, "rpid_str": "9002", "member": {"mid": "1", "uname": "路人"},
             "content": {"message": "来了"}, "ctime": now + 201, "root": 0, "parent": 0, "rcount": 0,
             "replies": []}]
        for _ in range(20):
            await bilibili.comment_step(now + 400)
            if bot.deliveries:
                break
        assert [delivery.parts[0].text for delivery in bot.deliveries] == ["乃琳Queen 发表了评论"]
        description = bot.deliveries[0].parts[1].description
        assert "今晚见" in description and "所在：乃琳Queen的动态" in description


@pytest.mark.asyncio
async def test_failed_at_all_is_sent_again_without_it(source, sdk):
    async with PluginTest(PACKAGE, config=config(dynamic=False, video=False)) as bot:
        bilibili = bot.host.plugins["bilibili"].instance
        original = bot.host.send_parts
        attempts = []

        async def send_parts(plugin, scene, parts, reply_to):
            attempts.append(parts)
            if any(isinstance(part, Mention) for part in parts):
                from len_bot.plugin import Sent
                return Sent("failed", "群里不允许 @全体")
            return await original(plugin, scene, parts, reply_to)

        bot.host.send_parts = send_parts
        sent = await bilibili.deliver(SCENE, [Text("嘉然 开播了")], at_all=True)
        assert sent.status == "simulated"
        assert [len(parts) for parts in attempts] == [2, 1]
        assert [delivery.text for delivery in bot.deliveries] == ["嘉然 开播了"]


@pytest.mark.asyncio
async def test_follows_require_login_cookie():
    with pytest.raises(RuntimeError, match="SESSDATA"):
        async with PluginTest(PACKAGE, config={"follows": config()["follows"]}):
            pass


@pytest.mark.asyncio
async def test_paused_scene_keeps_its_comment_resources(tmp_path):
    """Retirement follows the configured follows, as upstream does; a scene switched off only pauses work."""
    from types import SimpleNamespace
    from bilibili_plugin.comment_capture import CommentRetryPolicy
    from bilibili_plugin.comment_journal import CommentJournal
    from bilibili_plugin.gateway import BilibiliCommentResource
    from bilibili_plugin.push import PushFeature, follows

    def resource(uid: int) -> BilibiliCommentResource:
        return BilibiliCommentResource(key=f'video:{uid}', owner_uid=str(uid), owner_name='UP', resource_kind='video',
                                       oid=uid, type_value=1, title='视频', url=f'https://b23.tv/{uid}', published_at=1)

    async def owner_name(uid):
        return 'UP'

    async def discover(uid, name):
        return [resource(int(uid))]

    push = PushFeature.__new__(PushFeature)
    push.follows = follows([{'uid': 1, 'scenes': ['onebot:group:1'], 'comment': True},
                            {'uid': 2, 'scenes': ['onebot:group:2'], 'comment': True}])
    push.ctx = SimpleNamespace(scenes=('onebot:group:1', 'onebot:group:2'), report_error=lambda *args: None)
    push._reported = {}
    push.retry_policy = CommentRetryPolicy(random_value=lambda: 0.5)
    push.gateway = SimpleNamespace(get_comment_resource_owner_name=owner_name)
    push.monitor = SimpleNamespace(discover_comment_resources=discover)
    push.comment_journal = CommentJournal(tmp_path / 'comments.sqlite3')
    try:
        assert await push.refresh_catalog(1000) and await push.refresh_catalog(1000)
        push.ctx.scenes = ('onebot:group:1',)
        await push.refresh_catalog(1100)
        retired = push.comment_journal._connection.execute(
            "SELECT owner_uid FROM resource_lifecycle WHERE retired_at > 0").fetchall()
        assert retired == []
    finally:
        push.comment_journal.close()


@pytest.mark.asyncio
async def test_stale_profile_draws_at_once_and_refreshes_beside_it():
    from types import SimpleNamespace
    from bilibili_plugin.gateway import BilibiliAuthorCardProfile
    from bilibili_plugin.push import PushFeature

    release = asyncio.Event()
    saved = []

    async def fetch(uid):
        await release.wait()
        return BilibiliAuthorCardProfile(uid=uid, name='新名字', avatar_url='', fetched_at=int(time.time()))

    async def set_kv(key, value):
        saved.append(value)

    push = PushFeature.__new__(PushFeature)
    push.profiles = {'1': BilibiliAuthorCardProfile(uid='1', name='旧名字', avatar_url='a.png', fetched_at=1)}
    push._profile_refreshes = {}
    push._reported = {}
    push.gateway = SimpleNamespace(get_user_card_profile=fetch)
    push.ctx = SimpleNamespace(set_kv=set_kv, report_error=lambda *args: None)
    assert (await push.author_profile('1')).name == '旧名字'
    release.set()
    await until(lambda: not push._profile_refreshes)
    assert push.profiles['1'].name == '新名字' and push.profiles['1'].avatar_url == 'a.png' and saved


@pytest.mark.parametrize('kind', ['dynamic', 'video', 'repost', 'live', 'comment'])
def test_every_kind_renders_without_any_picture(kind):
    from io import BytesIO
    from PIL import Image as Picture
    from bilibili_plugin.card_kit import Run, load_fonts
    from bilibili_plugin.push_card import Note, Post, render_post
    fonts = load_fonts(Path(__file__).parents[1] / 'assets' / 'NotoSansSC.ttf')
    post = Post(kind=kind, author='名字特别长的UP主' * 8, avatar=None, published=1793768640, runs=[Run('正文 🎉')],
                title='标题' * 40, meta='虚拟主播 · 虚拟日常', badge='00:33', stats={'like': 1, 'comment': 0},
                quoted=Post(kind='dynamic', author='原作者', avatar=None, published=0, runs=[Run('原文')]),
                note=Note('所属视频', '视频标题'), url='bilibili.com/video/BV1xx')
    card = render_post(post, fonts)
    assert Picture.open(BytesIO(card)).size[0] == 1200
