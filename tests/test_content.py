"""Video tools: request signing and argument rules that do not need the real site."""

from pathlib import Path

import pytest

from len_bot.plugin_testing import PluginTest

PACKAGE = Path(__file__).parents[1]


def test_wbi_signature_matches_documented_example():
    # Example from SocialSisterYi/bilibili-API-collect docs/misc/sign/wbi.md.
    from bilibili_plugin.client import sign
    signed = sign({"foo": "114", "bar": "514", "zab": 1919810},
                  "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                  "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png", 1702204169)
    assert signed["w_rid"] == "8f6f2b5b3d485fe1886cec6a0be8c5d4"


@pytest.mark.asyncio
async def test_video_tools_require_exactly_one_identifier():
    async with PluginTest(PACKAGE) as bot:
        for arguments in ({}, {"bvid": "BV1xx411c7mD", "aid": 1}):
            with pytest.raises(ValueError, match="bvid或aid"):
                await bot.tool("bilibili_video", {"request": {"action": "info", **arguments}})
        with pytest.raises(ValueError, match="完整BV号"):
            await bot.tool("bilibili_video", {"request": {"action": "info", "bvid": "BV1"}})


@pytest.mark.asyncio
async def test_account_reads_need_account_settings():
    with pytest.raises(RuntimeError, match="account_uid和sessdata"):
        async with PluginTest(PACKAGE, config={"account_read_enabled": True}):
            pass


@pytest.mark.asyncio
async def test_configuration_controls_discovery_and_preview_has_no_credentials():
    async with PluginTest(PACKAGE) as bot:
        preview = {item['name']: item for item in bot.preview_tools()}
        available = {item['name'] for item in preview.values() if not item['reasons']}
        assert {'bilibili_video', 'bilibili_monitor'} <= available
        assert set(preview) == {'bilibili_video', 'search_bilibili', 'bilibili_monitor',
                                'bilibili_account_read'}
        assert 'bilibili_account_read' not in available
        assert preview['bilibili_account_read']['reasons'] == ['账号读取未开启']
        for item in preview.values():
            assert item['summary'] and item['instructions']
            for field in item['parameters']['properties'].values():
                assert field['description']


@pytest.mark.asyncio
async def test_account_tool_uses_source_sender_not_a_model_supplied_owner():
    config = {'account_read_enabled': True, 'account_uid': 12345, 'sessdata': 'synthetic-session',
              'buvid3': 'synthetic-device'}
    async with PluginTest(PACKAGE, config=config, owners=['onebot:70001']) as bot:
        source = bot.add_message('请读取评论', sender='onebot:70002')
        bot.add_message('我刚好在后面发言', sender='onebot:70001')
        with pytest.raises(PermissionError, match='主人'):
            await bot.tool('bilibili_account_read', {'source_message_id': source.platform_message_id,
                'request': {'action': 'comments', 'aid': 1}})
        with pytest.raises(ValueError):
            await bot.tool('bilibili_account_read', {'requester': 'onebot:70001',
                'request': {'action': 'comments', 'aid': 1}})
        preview = {item['name']: item for item in bot.preview_tools()}
        assert not preview['bilibili_account_read']['reasons']
        import json
        assert 'synthetic-session' not in json.dumps(preview)


@pytest.mark.asyncio
async def test_public_info_includes_pages_and_comments_use_same_capability(source, monkeypatch):
    import importlib
    import json
    video = {'bvid': 'BV1xx411c7mD', 'aid': 1, 'title': '合成标题', 'desc': '合成简介', 'pic': '',
             'pubdate': 1791298800, 'duration': 30, 'owner': {'mid': 123, 'name': '合成UP主', 'face': ''},
             'stat': {}, 'pages': [{'cid': 456, 'page': 1, 'part': 'P1', 'duration': 30}]}
    source.json('/x/web-interface/view', {'code': 0, 'message': '0', 'data': video})
    source.json('/x/v2/reply', {'code': 0, 'message': '0', 'data': {
        'page': {'num': 1, 'size': 20, 'count': 21}, 'replies': [{'content': {'message': '合成评论'}}]}})
    async with PluginTest(PACKAGE) as bot:
        client = bot.host.plugins['bilibili'].instance.content_client
        monkeypatch.setattr(importlib.import_module(type(client).__module__), 'API', source.url)
        info = json.loads(await bot.tool('bilibili_video', {'request': {'action': 'info', 'aid': 1}}))
        assert info['data']['pages'][0]['cid'] == 456
        comments = json.loads(await bot.tool('bilibili_video', {'request': {'action': 'comments', 'aid': 1}}))
        assert comments['data']['replies'][0]['content']['message'] == '合成评论'
        assert comments['next_page'] == 2
        assert source.requests[-1][1]['oid'] == ['1']
        assert not bot.deliveries
        before = len(source.requests)
        for request in ({'action': 'info', 'page': 1}, {'action': 'unknown', 'aid': 1}):
            with pytest.raises(ValueError):
                await bot.tool('bilibili_video', {'request': request})
        assert len(source.requests) == before


@pytest.mark.asyncio
async def test_account_read_only_exposes_content_actions():
    config = {'account_read_enabled': True, 'account_uid': 12345, 'sessdata': 'synthetic-session'}
    async with PluginTest(PACKAGE, config=config, owners=['onebot:70001']) as bot:
        message = bot.add_message('读取字幕', sender='onebot:70001')
        for action in ('like', 'favorite', 'like_state', 'favorite_state'):
            with pytest.raises(ValueError):
                await bot.tool('bilibili_account_read', {'source_message_id': message.platform_message_id,
                                                        'request': {'action': action, 'aid': 1}})
        assert 'bilibili_account_write' not in {item['name'] for item in bot.preview_tools()}


@pytest.mark.asyncio
async def test_account_comments_verify_identity_and_use_get(source, monkeypatch):
    import importlib
    import json

    source.json('/x/web-interface/nav', {'code': 0, 'message': '0', 'data': {'isLogin': True, 'mid': 12345}})
    source.json('/x/web-interface/view', {'code': 0, 'message': '0', 'data': {
        'bvid': 'BV1xx411c7mD', 'aid': 1, 'title': '合成标题', 'desc': '', 'pic': '',
        'pubdate': 1791298800, 'duration': 30, 'owner': {'mid': 123, 'name': 'UP', 'face': ''},
        'stat': {}, 'pages': [{'cid': 456, 'page': 1, 'part': 'P1', 'duration': 30}]}})
    source.json('/x/v2/reply', {'code': 0, 'message': '0', 'data': {
        'page': {'num': 1, 'size': 20, 'count': 1}, 'replies': [{'content': {'message': '账号评论'}}]}})
    config = {'account_read_enabled': True, 'account_uid': 12345, 'sessdata': 'synthetic-session'}
    async with PluginTest(PACKAGE, config=config, owners=['onebot:70001']) as bot:
        client = bot.host.plugins['bilibili'].instance.content_client
        monkeypatch.setattr(importlib.import_module(type(client).__module__), 'API', source.url)
        requests = []
        async def capture(request):
            requests.append(request)
        client.account.event_hooks['request'].append(capture)
        message = bot.add_message('读取评论', sender='onebot:70001')
        arguments = {'source_message_id': message.platform_message_id, 'request': {'action': 'comments', 'aid': 1}}
        result = json.loads(await bot.tool('bilibili_account_read', arguments))
        assert result['data']['replies'][0]['content']['message'] == '账号评论'
        assert len(requests) == 3 and all(request.method == 'GET' for request in requests)
        assert all(request.headers['Cookie'] == 'SESSDATA=synthetic-session' for request in requests)
        source.json('/x/web-interface/nav', {'code': 0, 'message': '0', 'data': {'isLogin': True, 'mid': 999}})
        with pytest.raises(PermissionError, match='account_uid不一致'):
            await bot.tool('bilibili_account_read', arguments)
        assert len(requests) == 4
