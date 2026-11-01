"""The pinned, real SDK talks HTTP to a loopback source; no SDK methods are replaced."""

import asyncio
from contextlib import asynccontextmanager
from importlib.metadata import version
import json
import time
from urllib.parse import parse_qs, urlsplit

import httpx
import jwt
import pytest

from bilibili_plugin.gateway import BilibiliGateway


@pytest.fixture(autouse=True)
def sdk():
    # Override conftest's synthetic SDK fixture for this protocol module.
    import bilibili_api
    assert version('bilibili-api-python') == '17.4.1'
    return bilibili_api


class Loopback(httpx.AsyncBaseTransport):
    def __init__(self, port):
        self.port = port
        self.transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False)

    async def handle_async_request(self, request):
        assert request.url.host in {'api.bilibili.com', 'space.bilibili.com'}
        request.url = request.url.copy_with(scheme='http', host='127.0.0.1', port=self.port)
        return await self.transport.handle_async_request(request)

    async def aclose(self):
        await self.transport.aclose()


@asynccontextmanager
async def source(likes):
    requests = []
    token = jwt.encode({'iat': int(time.time()), 'ttl': 3600}, 'synthetic-protocol-key-for-local-tests', algorithm='HS256')

    async def peer(reader, writer):
        head = (await reader.readuntil(b'\r\n\r\n')).decode()
        url = urlsplit(head.splitlines()[0].split()[1])
        requests.append((url.path, parse_qs(url.query)))
        if url.path.endswith('/dynamic'):
            body = ('<script id="__RENDER_DATA__" type="application/json">'
                    + json.dumps({'access_id': token}) + '</script>').encode()
            content_type = 'text/html'
        else:
            routes = {
                '/x/web-interface/nav': {'wbi_img': {
                    'img_url': 'https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png',
                    'sub_url': 'https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png'}},
                '/x/space/wbi/acc/info': {'name': '合成UP', 'face': '', 'pendant': {}},
                '/x/relation/stat': {'following': 12, 'follower': 34},
                '/x/space/upstat': {'archive': {'view': 987654}, **({} if likes is None else {'likes': likes})},
            }
            body = json.dumps({'code': 0, 'message': '0', 'data': routes[url.path]}).encode()
            content_type = 'application/json'
        writer.write(f'HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode() + body)
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(peer, '127.0.0.1', 0)
    async with server:
        yield server.sockets[0].getsockname()[1], requests


@pytest.mark.asyncio
@pytest.mark.parametrize('likes', [None, 73])
async def test_profile_reads_only_the_card_fields_without_csrf(sdk, likes):
    settings = sdk.request_settings
    old_auto, old_retries = settings.get_enable_auto_buvid(), settings.get_wbi_retry_times()
    old_client, _ = sdk.get_selected_client()
    sdk.select_client('httpx')
    original = sdk.get_session()
    settings.set_enable_auto_buvid(False)
    settings.set_wbi_retry_times(1)
    try:
        async with source(likes) as (port, requests), httpx.AsyncClient(transport=Loopback(port), trust_env=False) as session:
            sdk.set_session(session)
            gateway = BilibiliGateway(request_client='httpx', credential_data={
                'sessdata': 'synthetic', 'buvid3': 'synthetic-3', 'buvid4': 'synthetic-4'})
            profile = await gateway.get_user_card_profile('672328094')
            assert profile.name == '合成UP'
            assert profile.total_likes is None and profile.following is None and profile.follower is None
            assert not any(path in {'/x/space/upstat', '/x/relation/stat'} for path, _ in requests)
            assert [path for path, _ in requests].count('/x/space/wbi/acc/info') == 1
            info = next(query for path, query in requests if path == '/x/space/wbi/acc/info')
            assert info['mid'] == ['672328094'] and 'w_rid' in info and 'wts' in info
    finally:
        sdk.set_session(original)
        sdk.select_client(old_client)
        settings.set_enable_auto_buvid(old_auto)
        settings.set_wbi_retry_times(old_retries)
