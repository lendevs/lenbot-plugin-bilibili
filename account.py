"""Owner-authorized account reads."""

from .client import NAV
from .protocol import Identity


class Account:
    def __init__(self, ctx, client):
        self.ctx, self.client = ctx, client

    def require(self, invocation):
        invocation.require_owner()
        config = self.ctx.config
        if not config['account_read_enabled']:
            raise PermissionError('账号读取未在根配置开启')
        if not config['account_uid'] or not config['sessdata']:
            raise ValueError('账号能力需要明确account_uid和SESSDATA')

    async def verify(self):
        result = await self.client.query(NAV, Identity, account=True)
        if not result.data.isLogin or result.data.mid != self.ctx.config['account_uid']:
            raise PermissionError(f'登录身份与account_uid不一致：isLogin={result.data.isLogin}, mid={result.data.mid}')
        return result
