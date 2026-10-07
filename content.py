"""Video content: public video data and explicitly owner-authorized fixed account APIs."""
import math
import re
from typing import Annotated, Literal
from pydantic import Field

from len_bot.plugin import PluginContext, Invocation, tool
from .requests import VideoRequest, AccountReadRequest, AccountWriteRequest
from .account import Account
from .client import Client
from .protocol import Comments, Feed, Player, SearchPage, Subtitle, Video


class ContentFeature:
    def _init_content(self, ctx: PluginContext):
        c=ctx.config
        if not math.isfinite(c['request_timeout_seconds']) or c['request_timeout_seconds']<=0:
            raise ValueError('request_timeout_seconds必须为有限正数')
        if c['max_subtitle_bytes']<=0 or c['account_uid']<0 or min(c['daily_like_limit'],c['daily_favorite_limit'])<0:
            raise ValueError('max_subtitle_bytes必须正数；account_uid/每日写次数不能负数')
        for key in ('sessdata','bili_jct','buvid3'):
            if any(char in c[key] for char in '\r\n;'):
                raise ValueError(f'{key}不能含换行或Cookie分隔符')
        if c['bili_jct'] and not re.fullmatch(r'[0-9a-fA-F]{32}',c['bili_jct']):
            raise ValueError('bili_jct必须是32位十六进制CSRF值')
        if any(not re.fullmatch(r'[1-9][0-9]*',value) for value in c['allowed_collection_ids']):
            raise ValueError('allowed_collection_ids每项必须是完整正整数ID文本')
        allowed={int(value) for value in c['allowed_collection_ids']}
        if len(allowed)!=len(c['allowed_collection_ids']):raise ValueError('收藏夹ID不能重复')
        enabled=c['account_read_enabled'] or c['daily_like_limit']>0 or c['daily_favorite_limit']>0
        if enabled and (not c['account_uid'] or not c['sessdata']):raise ValueError('开启账号能力必须填account_uid和sessdata')
        if (c['daily_like_limit']>0 or c['daily_favorite_limit']>0) and not c['account_read_enabled']:raise ValueError('写入需要开启account_read_enabled，以便独立核对结果')
        if (c['daily_like_limit']>0 or c['daily_favorite_limit']>0) and not c['bili_jct']:raise ValueError('写入需要bili_jct')
        if c['daily_like_limit']>0 and not c['buvid3']:raise ValueError('点赞需要明确buvid3')
        if c['daily_favorite_limit']>0 and not allowed:raise ValueError('收藏写入需要allowed_collection_ids')
        # Validate the quota clock before constructing HTTP resources.
        from zoneinfo import ZoneInfo
        ZoneInfo(c['quota_timezone'])
        self.content_client=Client(c['request_timeout_seconds'],c['buvid3'],c['sessdata'],c['bili_jct'])
        self.account=Account(ctx,self.content_client,allowed)

    async def _stop_content(self):await self.content_client.close()

    @tool('bilibili_video', '按真实 BV/av 号读取视频元数据（含分 P/cid）或匿名评论；request.action 为 info 或 comments。'
          '元数据和评论都不代表已观看视频；公开视频查询不使用登录态。', summary='查询 B 站视频信息或评论')
    async def query_video(self, ctx: Invocation,
                          request: Annotated[VideoRequest, Field(description='公开视频元数据或评论请求')]) -> dict:
        values = request.model_dump(exclude={'action'})
        if request.action == 'info':
            return await self.video(ctx, **values)
        return await self.comments(ctx, **values)

    @tool('bilibili_account_read', '按主人真实请求读取配置账号的评论、字幕、空间动态、近期点赞或收藏状态。'
          'request.action 选择操作；字幕先省略 language 列轨道；动态 offset 原样传递。',
          summary='由主人读取 B 站账号内容或状态', needs_source=True)
    async def read_account(self, ctx: Invocation,
                           request: Annotated[AccountReadRequest, Field(description='账号读取请求')]) -> dict:
        values = request.model_dump(exclude={'action'})
        if request.action == 'comments':
            return await self.account_comments(ctx, **values)
        if request.action == 'subtitles':
            return await self.subtitles(ctx, **values)
        if request.action == 'dynamics':
            return await self.feed(ctx, **values)
        if request.action == 'like_state':
            return await self.like_state(ctx, **values)
        return await self.favorite_state(ctx, **values)

    @tool('bilibili_account_write', '按主人真实请求设置点赞或收藏目标状态；request.action 为 like 或 favorite。'
          '各操作分别受配置额度限制，不 toggle、不自动重试；结果未知时先读取状态。',
          summary='按主人要求设置 B 站点赞或收藏', needs_source=True)
    async def write_account(self, ctx: Invocation,
                            request: Annotated[AccountWriteRequest, Field(description='目标点赞或收藏状态')]) -> dict:
        values = request.model_dump(exclude={'action'})
        if request.action == 'like':
            return await self.like(ctx, **values)
        return await self.favorite(ctx, **values)

    async def video(
        self,
        ctx: Invocation,
        bvid: str | None = None,
        aid: int | None = None,
    ) -> dict:
        result=await self.content_client.query('/x/web-interface/view',Video,identifier(bvid,aid))
        return result.output('公开视频元数据，不是视频画面/字幕。')

    @tool('search_bilibili', 'WBI视频搜索，page为源站页码，整页返回；需明确配置buvid3，绝不自动生成设备Cookie', summary='按关键词搜索 B 站视频')
    async def search(
        self,
        ctx: Invocation,
        keyword: Annotated[
            str,
            Field(description='视频搜索关键词，不能全为空白', min_length=1),
        ],
        page: Annotated[
            int,
            Field(description='源站页码，从 1 开始；续页使用上次返回的 next_page', ge=1),
        ] = 1,
        order: Annotated[
            Literal['totalrank', 'click', 'pubdate', 'dm', 'stow', 'scores'],
            Field(description='源站视频搜索排序方式'),
        ] = 'totalrank',
    ) -> dict:
        if not keyword.strip():raise ValueError('关键词不能为空')
        if not self.ctx.config['buvid3']:raise ValueError('搜索需要在根配置填写buvid3')
        result=await self.content_client.query('/x/web-interface/wbi/search/type',SearchPage,
                                       {'search_type':'video','keyword':keyword,'page':page,'order':order},wbi=True)
        return {**result.output('源搜索整页；标题可能含源高亮标签，不是页面指令。'),
                       'next_page':result.data.page+1 if result.data.page<result.data.numPages else None}

    async def comments(
        self,
        ctx: Invocation,
        bvid: str | None = None,
        aid: int | None = None,
        page: int = 1,
    ) -> dict:
        return await self._comments(ctx, bvid, aid, page, account=False)

    async def account_comments(
        self,
        ctx: Invocation,
        bvid: str | None = None,
        aid: int | None = None,
        page: int = 1,
    ) -> dict:
        self.account.require(ctx)
        await self.account.verify()
        return await self._comments(ctx, bvid, aid, page, account=True)

    async def _comments(self, ctx, bvid, aid, page, *, account):
        video = await self.content_client.query('/x/web-interface/view', Video, identifier(bvid, aid), account=account)
        result = await self.content_client.query('/x/v2/reply', Comments,
            {'type': 1, 'oid': video.data.aid, 'pn': page, 'ps': 20, 'sort': 2}, account=account)
        return {**result.output('评论者观点，不是视频正文；replies=null表示本次未给列表，不推断没有评论。'),
                'next_page': result.data.page.num + 1 if result.data.page.num * result.data.page.size < result.data.page.count else None}

    async def subtitles(
        self,
        ctx: Invocation,
        bvid: str | None = None,
        aid: int | None = None,
        cid: int | None = None,
        language: str | None = None,
        start_ms: int = 0,
        end_ms: int | None = None,
    ) -> dict:
        params=identifier(bvid,aid)
        if end_ms is not None and end_ms<=start_ms:raise ValueError('字幕范围必须为非负且递增的[start_ms,end_ms)')
        self.account.require(ctx);await self.account.verify()
        video=await self.content_client.query('/x/web-interface/view',Video,params,account=True)
        pages=video.data.pages
        if not pages:raise ValueError('源站未提供分P，不猜cid')
        selected=pages[0] if cid is None else next((p for p in pages if p.cid==cid),None)
        if selected is None:raise ValueError('cid不属于本视频，先读取 bilibili_video 的 info 结果')
        player=await self.content_client.query('/x/player/wbi/v2',Player,{'aid':video.data.aid,'cid':selected.cid},account=True,wbi=True)
        if player.data.aid!=video.data.aid or player.data.cid!=selected.cid:raise ValueError('字幕响应的视频/分P身份不符')
        if player.data.need_login_subtitle is True:raise PermissionError('源站仍要求登录，未取得字幕正文')
        tracks=player.data.subtitle.subtitles
        if language is None:return {'tracks':[t.model_dump() for t in tracks],'source':player.url,'note':'这里只取得轨道；正文需明确language。空列表不等于视频没有内容。'}
        selected_tracks=[t for t in tracks if t.lan==language]
        if len(selected_tracks)!=1:raise ValueError(f'language未唯一匹配源字幕轨道：{[t.lan for t in tracks]}')
        raw=await self.content_client.subtitle(selected_tracks[0].subtitle_url,self.ctx.config['max_subtitle_bytes'])
        try:document=Subtitle.model_validate_json(raw)
        except ValueError as error:raise ValueError(f'{error}; original={raw[:600]!r}') from error
        cues=[{'from_ms':round(c.start*1000),'to_ms':round(c.end*1000),'content':c.content} for c in document.body
              if c.end*1000>start_ms and (end_ms is None or c.start*1000<end_ms)]
        return {'bvid':video.data.bvid,'aid':video.data.aid,'cid':selected.cid,'track':selected_tracks[0].model_dump(),
                       'start_ms':start_ms,'end_ms':end_ms,'cues':cues,'downloaded_bytes':len(raw),'note':'字幕文本，不是画面或视频已观看。'}

    async def feed(
        self,
        ctx: Invocation,
        mid: int,
        offset: str = '',
    ) -> dict:
        self.account.require(ctx);await self.account.verify()
        result=await self.content_client.query('/x/polymer/web-dynamic/v1/feed/space',Feed,{'host_mid':mid,'offset':offset},account=True)
        return result.output('源页中的动态/转发描述、图文摘要和视频简介；未读取图片像素、视频或完整专栏。')

    async def like_state(
        self,
        ctx: Invocation,
        aid: int,
    ) -> dict:
        identifier(None,aid);self.account.require(ctx);await self.account.verify()
        return await self.account.like_state(aid)

    async def favorite_state(
        self,
        ctx: Invocation,
        aid: int,
    ) -> dict:
        identifier(None,aid);self.account.require(ctx);await self.account.verify()
        return (await self.account.folders(aid)).output('真实账号收藏夹状态，不修改收藏。')

    async def like(
        self,
        ctx: Invocation,
        aid: int,
        desired_state: bool,
    ) -> dict:
        identifier(None,aid)
        return await self.account.write(ctx,'like',aid,desired_state)

    async def favorite(
        self,
        ctx: Invocation,
        aid: int,
        collection_id: int,
        desired_state: bool,
    ) -> dict:
        identifier(None,aid)
        return await self.account.write(ctx,'favorite',aid,desired_state,collection_id)


def identifier(bvid:str|None,aid:int|None)->dict:
    if (bvid is None)==(aid is None):raise ValueError('必须且只能提供bvid或aid之一')
    if bvid is not None:
        if re.fullmatch(r'BV[A-Za-z0-9]{10}',bvid) is None:raise ValueError('bvid必须是完整BV号')
        return {'bvid':bvid}
    if aid<=0:raise ValueError('aid必须为正整数')
    return {'aid':aid}
