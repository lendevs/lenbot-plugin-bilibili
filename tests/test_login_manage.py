"""Search with visitor cookies, QR login and subscriptions changed from chat, against a local source."""

import importlib
import json
from pathlib import Path

import pytest

from len_bot.plugin import Image
from len_bot.plugin_testing import PluginTest

PACKAGE = Path(__file__).parents[1]
OWNER = 'onebot:70001'
SCENE = 'onebot:group:80001'
OTHER = 'onebot:group:80002'
NAV = {'isLogin': False, 'wbi_img': {'img_url': 'https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png',
                                     'sub_url': 'https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png'}}


def point(monkeypatch, source, bot):
    plugin = bot.host.plugins['bilibili'].instance
    package = type(plugin).__module__
    client = importlib.import_module(type(plugin.content_client).__module__)
    monkeypatch.setattr(client, 'API', source.url)
    monkeypatch.setattr(client, 'HOME', source.url + '/')
    login = importlib.import_module(package + '.login')
    monkeypatch.setattr(login, 'API', source.url)
    monkeypatch.setattr(login, 'PASSPORT', source.url)
    monkeypatch.setattr(login, 'POLL_SECONDS', 0.01)
    manage = importlib.import_module(package + '.manage')
    monkeypatch.setattr(manage, 'ROOM_OF_UID', source.url + '/room')


def ask(bot, text='帮我处理一下 B 站', sender=OWNER, scene=SCENE):
    return bot.add_message(text, sender=sender, scene=scene).platform_message_id


@pytest.mark.asyncio
async def test_user_search_fetches_visitor_cookies_once(source, monkeypatch):
    source.text('/', '<html></html>', 'text/html')
    source.headers['/'] = [('Set-Cookie', 'buvid3=visitor-3; Path=/'), ('Set-Cookie', 'b_nut=100; Path=/')]
    source.json('/x/frontend/finger/spi', {'code': 0, 'message': '0', 'data': {'b_3': 'x', 'b_4': 'visitor-4'}})
    source.json('/x/web-interface/nav', {'code': -101, 'message': '账号未登录', 'data': NAV})
    source.json('/x/web-interface/wbi/search/type', {'code': 0, 'message': '0', 'data': {
        'page': 1, 'pagesize': 20, 'numResults': 1, 'numPages': 1, 'result': [{
            'mid': 672328094, 'uname': '<em class="keyword">嘉然</em>今天吃什么', 'usign': '签名', 'fans': 100,
            'videos': 5, 'upic': '//face', 'room_id': 22637261, 'is_live': 1}]}})
    async with PluginTest(PACKAGE) as bot:
        point(monkeypatch, source, bot)
        result = json.loads(await bot.tool('search_bilibili', {'keyword': '嘉然', 'kind': 'user'}))
        assert result['users'] == [{'uid': 672328094, 'name': '嘉然今天吃什么', 'fans': 100, 'videos': 5, 'sign': '签名',
                                    'live_room_id': 22637261, 'live_now': True}]
        await bot.tool('search_bilibili', {'keyword': '嘉然', 'kind': 'user'})
        searches = [cookie for (path, _), cookie in zip(source.requests, source.cookies) if path.endswith('search/type')]
        assert searches == ['buvid3=visitor-3; b_nut=100; buvid4=visitor-4'] * 2
        assert [path for path, _ in source.requests].count('/') == 1
        assert search_params(source)['search_type'] == ['bili_user']


@pytest.mark.asyncio
async def test_search_voucher_is_reported_and_cookies_renewed(source, monkeypatch):
    source.text('/', '<html></html>', 'text/html')
    source.headers['/'] = [('Set-Cookie', 'buvid3=visitor-3; Path=/')]
    source.json('/x/frontend/finger/spi', {'code': 0, 'message': '0', 'data': {'b_3': 'x', 'b_4': 'visitor-4'}})
    source.json('/x/web-interface/nav', {'code': -101, 'message': '账号未登录', 'data': NAV})
    source.json('/x/web-interface/wbi/search/type', {'code': 0, 'message': '0', 'data': {'v_voucher': 'voucher_1'}})
    async with PluginTest(PACKAGE) as bot:
        point(monkeypatch, source, bot)
        with pytest.raises(RuntimeError, match='人机验证'):
            await bot.tool('search_bilibili', {'keyword': '嘉然'})
        with pytest.raises(RuntimeError, match='人机验证'):
            await bot.tool('search_bilibili', {'keyword': '嘉然'})
        assert [path for path, _ in source.requests].count('/') == 2


def search_params(source):
    return next(query for path, query in reversed(source.requests) if path.endswith('search/type'))


@pytest.mark.asyncio
async def test_qr_login_sends_code_and_saves_the_session(source, monkeypatch):
    source.json('/x/passport-login/web/qrcode/generate', {'code': 0, 'message': '0', 'data': {
        'url': 'https://account.bilibili.com/h5/account-h5/auth/scan-web?qrcode_key=k1', 'qrcode_key': 'k1'}})
    source.json('/x/passport-login/web/qrcode/poll', {'code': 0, 'message': '0', 'data': {
        'code': 0, 'message': '', 'url': 'https://passport.biligame.com/crossDomain?DedeUserID=12345'}})
    source.headers['/x/passport-login/web/qrcode/poll'] = [
        ('Set-Cookie', 'SESSDATA=synthetic%2Csession; Path=/'), ('Set-Cookie', 'DedeUserID=12345; Path=/')]
    source.json('/x/web-interface/nav', {'code': 0, 'message': '0', 'data': {**NAV, 'isLogin': True, 'mid': 12345,
                                                                             'uname': '主人账号'}})
    async with PluginTest(PACKAGE, owners=[OWNER]) as bot:
        point(monkeypatch, source, bot)
        with pytest.raises(PermissionError, match='主人'):
            await bot.tool('bilibili_login', {'source_message_id': ask(bot, sender='onebot:70002'), 'action': 'login'})
        result = json.loads(await bot.tool('bilibili_login', {'source_message_id': ask(bot), 'action': 'login'}))
        assert result['sent'] is True
        await bot.wait_tasks('B站扫码登录')
        assert any(isinstance(part, Image) for part in bot.deliveries[0].parts)
        assert bot.deliveries[-1].text == 'B 站账号已登录：主人账号（UID 12345）'
        assert bot.saved_config['sessdata'] == 'synthetic%2Csession'
        assert bot.saved_config['account_uid'] == 12345 and bot.saved_config['account_read_enabled'] is True
        plugin = bot.host.plugins['bilibili'].instance
        assert plugin.content_client.sessdata == 'synthetic%2Csession'
        assert plugin.gateway.get_credential_data()['sessdata'] == 'synthetic%2Csession'
        assert 'bilibili_account_read' in {item['name'] for item in bot.preview_tools() if not item['reasons']}
        status = json.loads(await bot.tool('bilibili_login', {'source_message_id': ask(bot), 'action': 'status'}))
        assert status['logged_in'] is True and status['qr_login']['state'] == 'done'


@pytest.mark.asyncio
async def test_expired_code_is_announced_without_saving(source, monkeypatch):
    source.json('/x/passport-login/web/qrcode/generate', {'code': 0, 'message': '0', 'data': {
        'url': 'https://example.invalid/k2', 'qrcode_key': 'k2'}})
    source.json('/x/passport-login/web/qrcode/poll', {'code': 0, 'message': '0', 'data': {
        'code': 86038, 'message': '二维码已失效'}})
    async with PluginTest(PACKAGE, owners=[OWNER]) as bot:
        point(monkeypatch, source, bot)
        assert await bot.message('/B站登录', sender=OWNER)
        await bot.wait_tasks('B站扫码登录')
        assert bot.deliveries[-1].text == 'B 站登录二维码已过期'
        assert bot.saved_config is None


@pytest.mark.asyncio
async def test_live_subscription_added_and_removed_from_chat(source, monkeypatch):
    source.json('/room', {'code': 0, 'message': 'ok', 'data': {'roomStatus': 1, 'roomid': 22637261}})
    config = {'rooms': [{'uid': 1, 'room_id': 10, 'name': '已有', 'scenes': [OTHER]}]}
    async with PluginTest(PACKAGE, config=config, scenes=[SCENE, OTHER], owners=[OWNER]) as bot:
        point(monkeypatch, source, bot)
        add = {'action': 'live_add', 'uid': 672328094, 'name': '嘉然'}
        with pytest.raises(PermissionError, match='主人'):
            await bot.tool('bilibili_subscription', {'source_message_id': ask(bot, sender='onebot:70002'), 'request': add})
        result = json.loads(await bot.tool('bilibili_subscription', {'source_message_id': ask(bot), 'request': add}))
        assert result['changed'] is True
        assert source.requests[-1] == ('/room', {'mid': ['672328094']})
        plugin = bot.host.plugins['bilibili'].instance
        assert [(item.uid, item.room_id, item.scenes) for item in plugin.rooms] == [
            (1, 10, [OTHER]), (672328094, 22637261, [SCENE])]
        assert bot.saved_config['rooms'][1] == {'uid': 672328094, 'room_id': 22637261, 'name': '嘉然',
                                                'scenes': [SCENE], 'at_all': False}
        again = json.loads(await bot.tool('bilibili_subscription', {'source_message_id': ask(bot), 'request': add}))
        assert again['changed'] is False
        shared = {'action': 'live_add', 'uid': 1, 'name': '已有', 'at_all': True}
        await bot.tool('bilibili_subscription', {'source_message_id': ask(bot), 'request': shared})
        assert bot.saved_config['rooms'][0] == {'uid': 1, 'room_id': 10, 'name': '已有', 'scenes': [OTHER, SCENE],
                                                'at_all': True}
        for uid in (672328094, 1):
            await bot.tool('bilibili_subscription', {'source_message_id': ask(bot),
                                                     'request': {'action': 'live_remove', 'uid': uid}})
        assert bot.saved_config['rooms'] == [{'uid': 1, 'room_id': 10, 'name': '已有', 'scenes': [OTHER], 'at_all': True}]
        assert [item.uid for item in plugin.rooms] == [1]
        monitor = json.loads(await bot.tool('bilibili_monitor', {'request': {'action': 'subscriptions'}}))
        assert monitor['rooms'] == []


@pytest.mark.asyncio
async def test_uid_without_live_room_is_refused(source, monkeypatch):
    source.json('/room', {'code': 0, 'message': 'ok', 'data': {'roomStatus': 0, 'roomid': 0}})
    async with PluginTest(PACKAGE, owners=[OWNER]) as bot:
        point(monkeypatch, source, bot)
        with pytest.raises(ValueError, match='没有开通直播间'):
            await bot.tool('bilibili_subscription', {'source_message_id': ask(bot),
                                                     'request': {'action': 'live_add', 'uid': 5, 'name': '某人'}})
        assert bot.saved_config is None


@pytest.mark.asyncio
async def test_follow_needs_login_and_starts_polling(source, monkeypatch):
    async with PluginTest(PACKAGE, owners=[OWNER]) as bot:
        point(monkeypatch, source, bot)
        with pytest.raises(PermissionError, match='先登录'):
            await bot.tool('bilibili_subscription', {'source_message_id': ask(bot),
                                                     'request': {'action': 'follow_add', 'uid': 9}})
    config = {'sessdata': 'synthetic-session', 'account_uid': 12345}
    async with PluginTest(PACKAGE, config=config, owners=[OWNER]) as bot:
        plugin = bot.host.plugins['bilibili'].instance
        started = []
        monkeypatch.setattr(plugin, '_content_loop', lambda: started.append('content') or _idle())
        monkeypatch.setattr(plugin, '_catalog_loop', lambda: started.append('catalog') or _idle())
        monkeypatch.setattr(plugin, '_comment_loop', lambda: started.append('comment') or _idle())
        request = {'action': 'follow_add', 'uid': 9, 'name': '某 UP', 'comment': True}
        result = json.loads(await bot.tool('bilibili_subscription', {'source_message_id': ask(bot), 'request': request}))
        assert result['follow'] == {'uid': 9, 'name': '某 UP', 'scenes': [SCENE], 'dynamic': True, 'video': True,
                                    'comment': True}
        assert started == ['content', 'catalog', 'comment']
        await bot.tool('bilibili_subscription', {'source_message_id': ask(bot),
                                                 'request': {'action': 'follow_add', 'uid': 10, 'video': False}})
        assert started == ['content', 'catalog', 'comment']
        follows = json.loads(await bot.tool('bilibili_monitor', {'request': {'action': 'follows'}}))
        assert [item['uid'] for item in follows['follows']] == [9, 10]
        await bot.tool('bilibili_subscription', {'source_message_id': ask(bot),
                                                 'request': {'action': 'follow_remove', 'uid': 9}})
        assert [item['uid'] for item in bot.saved_config['follows']] == [10]
        assert [item.uid for item in plugin.follows] == [10]


async def _idle():
    return None
