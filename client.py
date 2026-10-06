"""One HTTP request per endpoint; public and account cookie jars never mix."""
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import md5
import re
import time
from urllib.parse import quote, urlencode, urlsplit

import httpx
from pydantic import BaseModel

from .protocol import Envelope, Nav, parse

API = 'https://api.bilibili.com'
NAV = '/x/web-interface/nav'
MIXIN = (46,47,18,2,53,8,23,32,15,50,10,31,58,3,45,35,27,43,5,49,33,9,42,19,29,28,14,39,12,38,41,13,
         37,48,7,16,24,55,40,61,26,17,0,1,60,51,30,4,22,25,54,21,56,59,6,63,57,62,11,36,20,34,44,52)
USER_AGENT = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36'


@dataclass(frozen=True)
class Result[T]:
    data: T
    url: str
    fetched_at: str

    def output(self, note: str) -> dict:
        return {'data': self.data.model_dump(mode='json', by_alias=True) if isinstance(self.data, BaseModel) else self.data,
                'source': self.url, 'fetched_at': self.fetched_at, 'note': note}


def sign(params: dict, img_url: str, sub_url: str, timestamp: int) -> dict:
    keys = [urlsplit(url).path.rsplit('/',1)[-1].split('.')[0] for url in (img_url, sub_url)]
    if any(re.fullmatch(r'[0-9a-fA-F]{32}', key) is None for key in keys):
        raise ValueError(f'WBI口令URL格式错误：{img_url!r}, {sub_url!r}')
    combined = ''.join(keys)
    mixin = ''.join(combined[index] for index in MIXIN)[:32]
    values = {key: ''.join(char for char in str(value) if char not in "!'()*") for key,value in {**params,'wts':timestamp}.items()}
    encoded = urlencode(sorted(values.items()), quote_via=quote)
    return {**values, 'w_rid': md5((encoded + mixin).encode()).hexdigest()}


class Client:
    def __init__(self, timeout: float, buvid3: str, sessdata: str, bili_jct: str) -> None:
        headers = {'User-Agent': USER_AGENT, 'Referer': 'https://www.bilibili.com/'}
        self.public = httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False, headers=headers)
        self.account = httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False, headers=headers)
        self.media = httpx.AsyncClient(timeout=timeout, trust_env=False, follow_redirects=False, headers=headers)
        self.buvid3, self.sessdata, self.bili_jct = buvid3, sessdata, bili_jct
        self.keys: tuple[float, Nav] | None = None
        self.key_lock = asyncio.Lock()

    async def close(self):
        await self.public.aclose()
        await self.account.aclose()
        await self.media.aclose()

    async def _wire(self, path: str, params: dict | None = None, *, account: bool = False, form: dict | None = None):
        client = self.account if account else self.public
        cookies = {}
        if self.buvid3: cookies['buvid3'] = self.buvid3
        if account:
            cookies['SESSDATA'] = self.sessdata
            if form is not None: cookies['bili_jct'] = self.bili_jct
        # Explicit Cookie prevents a Set-Cookie response from changing configured credentials on later calls.
        headers = {'Cookie': '; '.join(f'{key}={value}' for key,value in cookies.items())}
        async with client.stream('POST' if form is not None else 'GET', API + path, params=params, data=form, headers=headers) as response:
            raw = await read_body(response, 4_000_000)
            if response.status_code != 200:
                raise RuntimeError(f'{response.url} HTTP {response.status_code}: {raw[:600]!r}')
        try:
            envelope = Envelope.model_validate_json(raw)
        except ValueError as error:
            raise ValueError(f'{error}; original={raw[:600]!r}') from error
        return envelope, raw, str(response.url)

    async def wbi_params(self, params: dict) -> dict:
        async with self.key_lock:
            if self.keys is None or time.monotonic() >= self.keys[0]:
                envelope, raw, _ = await self._wire(NAV)
                if envelope.code not in (0, -101):
                    raise ValueError(f'WBI nav code={envelope.code}: {envelope.message}; original={raw[:600]!r}')
                nav = parse(envelope.data, Nav, raw)
                self.keys = (time.monotonic() + 3600, nav)
            nav = self.keys[1]
        return sign(params, nav.wbi_img.img_url, nav.wbi_img.sub_url, int(time.time()))

    async def query[T](self, path: str, model: type[T], params: dict | None = None, *, account: bool = False, wbi: bool = False) -> Result[T]:
        if wbi: params = await self.wbi_params(params or {})
        envelope, raw, url = await self._wire(path, params, account=account)
        if envelope.code != 0:
            raise ValueError(f'B站 code={envelope.code}: {envelope.message}; original={raw[:600]!r}')
        return Result(parse(envelope.data, model, raw), url, datetime.now(timezone.utc).isoformat())

    async def write(self, path: str, form: dict) -> dict:
        envelope, _, url = await self._wire(path, account=True, form={**form,'csrf':self.bili_jct})
        return {'status': 'acknowledged' if envelope.code == 0 else 'platform_error',
                'code': envelope.code, 'message': envelope.message, 'source': url,
                'note': '平台业务回执；非零码报告错误，不推断最终状态已改变或未改变。不是随后再次观察的状态。'}

    async def subtitle(self, url: str, limit: int) -> bytes:
        if url.startswith('//'):url = 'https:' + url
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username is not None or parsed.password is not None:
            raise ValueError(f'字幕URL必须是不带账号口令的HTTPS地址：{url!r}')
        # Separate no-cookie request: neither configured cookies nor CDN Set-Cookie values are sent.
        async with self.media.stream('GET', url, headers={'Cookie': ''}) as response:
            raw = await read_body(response, limit)
            if response.status_code != 200:
                raise RuntimeError(f'字幕 HTTP {response.status_code}: {raw[:600]!r}')
        return raw


async def read_body(response: httpx.Response, limit: int) -> bytes:
    data = bytearray()
    async for chunk in response.aiter_bytes():
        if len(data) + len(chunk) > limit:
            raise ValueError(f'{response.url} 响应超过 {limit} 字节；original={bytes(data[:100])!r}')
        data.extend(chunk)
    return bytes(data)
