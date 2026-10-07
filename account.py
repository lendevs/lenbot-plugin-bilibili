"""Fixed owner-authorized reads and state-setting actions; no proposal ledger."""
import asyncio
from datetime import datetime
import json
from zoneinfo import ZoneInfo
from pydantic import TypeAdapter

from .client import NAV
from .protocol import Counts, Flag, Folders, Identity


class Account:
    def __init__(self, ctx, client, allowed: set[int]):
        self.ctx, self.client, self.allowed = ctx, client, allowed
        self.lock = asyncio.Lock()
        self.quota_file = ctx.data_dir / 'write-counts.json'
        self.zone = ZoneInfo(ctx.config['quota_timezone'])

    def require(self, invocation, *, kind: str | None = None):
        invocation.require_owner()
        config = self.ctx.config
        if kind is None and not config['account_read_enabled']:
            raise PermissionError('账号读取未在根配置开启')
        if kind is not None and config[f'daily_{kind}_limit'] == 0:
            raise PermissionError(f'{kind}写入未在根配置开启')
        if not config['account_uid'] or not config['sessdata']:
            raise ValueError('账号能力需要明确account_uid和SESSDATA')
        if kind is not None and not config['bili_jct']:
            raise ValueError('写入需要明确bili_jct')
        if kind == 'like' and not config['buvid3']:
            raise ValueError('点赞需要明确buvid3，不自动生成设备Cookie')

    async def verify(self):
        result = await self.client.query(NAV, Identity, account=True)
        if not result.data.isLogin or result.data.mid != self.ctx.config['account_uid']:
            raise PermissionError(f'登录身份与account_uid不一致：isLogin={result.data.isLogin}, mid={result.data.mid}')
        return result

    async def like_state(self, aid: int):
        result = await self.client.query('/x/web-interface/archive/has/like', Flag, {'aid':aid}, account=True)
        return {'aid':aid,'raw_state':result.data, 'liked':True if result.data == 1 else None,
                'source':result.url,'fetched_at':result.fetched_at,
                'note':'0只能说明未查到近期点赞，不能可靠证明没有点赞。'}

    async def folders(self, aid: int):
        result = await self.client.query('/x/v3/fav/folder/created/list-all', Folders,
                                         {'up_mid':self.ctx.config['account_uid'],'type':2,'rid':aid}, account=True)
        folders = result.data.folders
        if result.data.count != (0 if folders is None else len(folders)):
            raise ValueError('收藏夹列表count与实际项目数不一致；未确认完整状态')
        if folders is not None and any(folder.mid != self.ctx.config['account_uid'] for folder in folders):
            raise PermissionError('收藏夹列表包含其他账号；停止动作')
        return result

    def count_attempt(self, kind: str):
        # One file contains only real account/date counters, not action IDs or pending work.
        counts = (TypeAdapter(dict[str,dict[str,Counts]]).validate_json(self.quota_file.read_bytes(),strict=True)
                  if self.quota_file.exists() else {})
        days = counts.setdefault(str(self.ctx.config['account_uid']), {})
        date = datetime.fromtimestamp(self.ctx.now(), self.zone).date().isoformat()
        current = days.setdefault(date, Counts())
        used = getattr(current, kind)
        if used >= self.ctx.config[f'daily_{kind}_limit']:
            raise PermissionError(f'账号今天的{kind}写尝试已达配置上限；日期={date}，时区={self.zone.key}')
        setattr(current,kind,used+1)
        temporary = self.quota_file.with_suffix('.json.tmp')
        temporary.write_text(json.dumps({uid:{day:value.model_dump() for day,value in entries.items()}
                                         for uid,entries in counts.items()},ensure_ascii=False),encoding='utf-8')
        temporary.replace(self.quota_file)

    async def write(self, invocation, kind: str, aid: int, desired: bool, collection_id: int | None = None):
        self.require(invocation,kind=kind)
        if kind == 'favorite' and collection_id not in self.allowed:
            raise PermissionError('目标收藏夹未在allowed_collection_ids中明确允许')
        async with self.lock:
            await self.verify()
            if kind == 'like':
                observed = await self.like_state(aid)
                state = observed['liked']
                path='/x/web-interface/archive/like';form={'aid':aid,'like':1 if desired else 2}
            else:
                folders = await self.folders(aid)
                matches = [] if folders.data.folders is None else [item for item in folders.data.folders if item.id == collection_id]
                if len(matches) != 1:
                    raise ValueError('未在配置账号的完整收藏夹列表中找到目标收藏夹')
                state = bool(matches[0].fav_state)
                observed = {'folder':matches[0].model_dump(),'source':folders.url,'fetched_at':folders.fetched_at}
                path='/x/v3/fav/resource/deal';form={'rid':aid,'type':2,'add_media_ids':str(collection_id) if desired else '',
                                                   'del_media_ids':'' if desired else str(collection_id)}
            if state is not None and state == desired:
                return {'status':'already_observed','write_sent':False,'desired_state':desired,'observed':observed}
            self.require(invocation,kind=kind)
            self.count_attempt(kind)
            try:
                receipt = await self.client.write(path,form)
            except asyncio.CancelledError:
                self.ctx.report_error(f'{kind}写入',RuntimeError(f'av{aid}等待回执时取消，结果未知；先查询平台状态，未自动重发'))
                raise
            except Exception as error:
                raise RuntimeError(f'{kind} av{aid} 写入结果未知；先查询平台状态，未自动重发。{type(error).__name__}: {error}') from error
            return {**receipt,'write_sent':True,'aid':aid,'collection_id':collection_id,'desired_state':desired,'observed_before':observed}
