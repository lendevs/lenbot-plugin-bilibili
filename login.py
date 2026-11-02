"""QR login: the owner scans a code sent to the chat, and the session goes into the plugin's own settings."""

import asyncio
from dataclasses import replace
from io import BytesIO
import time
from typing import Annotated, Literal

import httpx
from pydantic import Field
import qrcode

from len_bot.plugin import Image, Invocation, PluginContext, Text, command, tool
from .client import API, NAV, USER_AGENT, read_body
from .protocol import Envelope, Identity, QrCode, QrPoll, parse

PASSPORT = 'https://passport.bilibili.com'
GENERATE = '/x/passport-login/web/qrcode/generate'
POLL = '/x/passport-login/web/qrcode/poll'
QR_SECONDS = 180
POLL_SECONDS = 2.0
WAITING, SCANNED, EXPIRED = 86101, 86090, 86038


class LoginFeature:
    def _init_login(self, ctx: PluginContext) -> None:
        self.login_client = httpx.AsyncClient(timeout=ctx.config['request_timeout_seconds'], trust_env=False,
                                              follow_redirects=False,
                                              headers={'User-Agent': USER_AGENT, 'Referer': 'https://www.bilibili.com/'})
        self.login_session: dict | None = None
        self.login_task: asyncio.Task | None = None
        self.login_lock = asyncio.Lock()

    async def _stop_login(self) -> None:
        if self.login_task is not None:
            self.login_task.cancel()
        await self.login_client.aclose()

    @command('B站登录', '主人扫码登录插件使用的 B 站账号，二维码发到本群，3 分钟内有效')
    async def login_command(self, ctx: Invocation, args: str) -> None:
        result = await self.begin_login(ctx)
        if not result['sent']:
            await ctx.reply(result['message'])

    @tool('bilibili_login', '主人扫码登录插件使用的 B 站账号，只有主人发起的请求能执行。action：login 把登录二维码发到本群，'
          '主人用 B 站手机客户端扫码确认后自动保存登录状态并在本群告知结果；status 查询当前登录的账号和扫码进度。'
          '关注推送、账号读取都用这个账号。',
          summary='由主人扫码登录 B 站账号', needs_source=True)
    async def login_tool(self, ctx: Invocation,
                         action: Annotated[Literal['login', 'status'],
                                           Field(description='login 发送登录二维码；status 查询登录状态')]) -> dict:
        if action == 'login':
            return await self.begin_login(ctx)
        ctx.require_owner()
        return await self.login_status()

    async def begin_login(self, ctx: Invocation) -> dict:
        ctx.require_owner()
        async with self.login_lock:
            return await self._begin_login(ctx)

    async def _begin_login(self, ctx: Invocation) -> dict:
        if self.login_task is not None and not self.login_task.done():
            return {'sent': False, 'state': self.login_session['state'],
                    'message': '上一张登录二维码还在等待扫码，过期后再重新发送'}
        code = await self.passport(GENERATE, {}, QrCode)
        picture = await asyncio.to_thread(qr_png, code.url)
        sent = await ctx.reply_parts([Text('B 站扫码登录，3 分钟内有效'), Image(picture, 'B站扫码登录二维码')])
        if sent.status == 'failed':
            raise RuntimeError(f'登录二维码发送失败：{sent.report}')
        self.login_session = {'scene': ctx.scene, 'state': 'waiting', 'sent_at': ctx.now()}
        self.login_task = self.ctx.start_task('B站扫码登录', self.await_scan(ctx.scene, code.qrcode_key, self.login_session))
        return {'sent': True, 'state': 'waiting',
                'message': '二维码已发到本群；主人扫码确认后插件保存登录状态，并在本群发出结果'}

    async def await_scan(self, scene: str, key: str, session: dict) -> None:
        deadline = time.monotonic() + QR_SECONDS
        try:
            while time.monotonic() < deadline:
                await asyncio.sleep(POLL_SECONDS)
                poll, cookies = await self.poll_scan(key)
                if poll.code in (WAITING, SCANNED):
                    session['state'] = 'scanned' if poll.code == SCANNED else 'waiting'
                    continue
                if poll.code == EXPIRED:
                    break
                if poll.code != 0:
                    raise ValueError(f'B站扫码登录 code={poll.code}: {poll.message}')
                identity = await self.save_login(cookies)
                session['state'] = 'done'
                await self.ctx.send(scene, f'B 站账号已登录：{identity.uname}（UID {identity.mid}）')
                return
            session['state'] = 'expired'
            await self.ctx.send(scene, 'B 站登录二维码已过期')
        except asyncio.CancelledError:
            raise
        except Exception as error:
            session['state'] = 'failed'
            session['error'] = f'{type(error).__name__}: {error}'
            self.ctx.report_error('B站扫码登录', error)
            await self.ctx.send(scene, f'B 站扫码登录失败：{error}')

    async def poll_scan(self, key: str) -> tuple[QrPoll, dict[str, str]]:
        async with self.login_client.stream('GET', PASSPORT + POLL, params={'qrcode_key': key},
                                            headers={'Cookie': ''}) as response:
            raw = await read_body(response, 1_000_000)
            if response.status_code != 200:
                raise RuntimeError(f'B站扫码登录 HTTP {response.status_code}')
            cookies = {name: response.cookies[name] for name in ('SESSDATA', 'DedeUserID') if name in response.cookies}
        envelope = Envelope.model_validate_json(raw)
        if envelope.code != 0:
            raise ValueError(f'B站扫码登录 code={envelope.code}: {envelope.message}')
        poll = parse(envelope.data, QrPoll, b'')
        if poll.code == 0 and len(cookies) < 2:
            # Some responses carry the cookies only in the cross-domain URL; the values stay URL-encoded there.
            pairs = dict(part.split('=', 1) for part in poll.url.partition('?')[2].split('&') if '=' in part)
            cookies = {name: pairs[name] for name in ('SESSDATA', 'DedeUserID') if pairs.get(name)}
        return poll, cookies

    async def save_login(self, cookies: dict[str, str]) -> Identity:
        sessdata = cookies.get('SESSDATA', '')
        if not sessdata or any(char in sessdata for char in '\r\n; '):
            raise ValueError('扫码成功但没有取得有效的 SESSDATA')
        identity = await self.whoami(sessdata)
        if not identity.isLogin or identity.mid is None:
            raise PermissionError('扫码成功但 B 站没有确认登录状态')
        await self.ctx.update_config({'sessdata': sessdata, 'account_uid': identity.mid, 'account_read_enabled': True})
        self.content_client.sessdata = sessdata
        credential = {**self.push_config.credential_data, 'sessdata': sessdata, 'dedeuserid': str(identity.mid)}
        self.push_config = replace(self.push_config, credential_data=credential)
        self.gateway.set_credential_data(credential)
        return identity

    async def login_status(self) -> dict:
        config = self.ctx.config
        session = None if self.login_session is None else {
            key: value for key, value in self.login_session.items() if key in ('state', 'sent_at', 'error')}
        if not config['sessdata']:
            return {'logged_in': False, 'qr_login': session, 'note': '没有保存的登录状态'}
        identity = await self.whoami(config['sessdata'])
        return {'logged_in': identity.isLogin, 'uid': identity.mid, 'name': identity.uname,
                'configured_uid': config['account_uid'], 'account_read_enabled': config['account_read_enabled'],
                'qr_login': session,
                'note': '已登录' if identity.isLogin else '保存的登录状态已失效，需要重新扫码登录'}

    async def whoami(self, sessdata: str) -> Identity:
        async with self.login_client.stream('GET', API + NAV, headers={'Cookie': f'SESSDATA={sessdata}'}) as response:
            raw = await read_body(response, 1_000_000)
            if response.status_code != 200:
                raise RuntimeError(f'B站登录状态 HTTP {response.status_code}')
        envelope = Envelope.model_validate_json(raw)
        if envelope.code == -101:
            return Identity(isLogin=False)
        if envelope.code != 0:
            raise ValueError(f'B站登录状态 code={envelope.code}: {envelope.message}')
        return parse(envelope.data, Identity, b'')

    async def passport[T](self, path: str, params: dict, model: type[T]) -> T:
        async with self.login_client.stream('GET', PASSPORT + path, params=params, headers={'Cookie': ''}) as response:
            raw = await read_body(response, 1_000_000)
            if response.status_code != 200:
                raise RuntimeError(f'B站扫码登录 HTTP {response.status_code}: {raw[:300]!r}')
        envelope = Envelope.model_validate_json(raw)
        if envelope.code != 0:
            raise ValueError(f'B站扫码登录 code={envelope.code}: {envelope.message}')
        return parse(envelope.data, model, raw)


def qr_png(text: str) -> bytes:
    code = qrcode.QRCode(box_size=8, border=3)
    code.add_data(text)
    code.make(fit=True)
    buffer = BytesIO()
    code.make_image().save(buffer, format='PNG')
    return buffer.getvalue()
