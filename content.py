"""Video content: public video data and explicitly owner-authorized fixed account APIs."""
import math
import re
from typing import Annotated, Literal
from pydantic import Field

from len_bot.plugin import PluginContext, Invocation, tool
from .requests import VideoRequest, AccountReadRequest
from .account import Account
from .client import Client
from .protocol import Comments, Feed, Player, SearchPage, Subtitle, UserSearchPage, Video


class ContentFeature:
    def _init_content(self, ctx: PluginContext):
        c=ctx.config
        if not math.isfinite(c['request_timeout_seconds']) or c['request_timeout_seconds']<=0:
            raise ValueError('request_timeout_seconds必须为有限正数')
        if c['max_subtitle_bytes']<=0 or c['account_uid']<0:
            raise ValueError('max_subtitle_bytes必须正数；account_uid不能负数')
        for key in ('sessdata','buvid3'):
            if any(char in c[key] for char in '\r\n;'):
                raise ValueError(f'{key}不能含换行或Cookie分隔符')
        if c['account_read_enabled'] and (not c['account_uid'] or not c['sessdata']):
            raise ValueError('开启账号能力必须填account_uid和sessdata')
        self.content_client=Client(c['request_timeout_seconds'],c['buvid3'],c['sessdata'])
        self.account=Account(ctx,self.content_client)

    async def _stop_content(self):await self.content_client.close()

    @tool('bilibili_video', '按 BV 号或 av 号查询 B 站公开视频，只返回数据，不用登录。request.action：'
          'info 标题、简介、UP 主、统计和分 P 列表（含 cid）；comments 按热度排列的评论，每页 20 条。', summary='查询 B 站视频信息或评论')
    async def query_video(self, ctx: Invocation,
                          request: Annotated[VideoRequest, Field(description='公开视频元数据或评论请求')]) -> dict:
        values = request.model_dump(exclude={'action'})
        if request.action == 'info':
            return await self.video(ctx, **values)
        return await self.comments(ctx, **values)

    @tool('bilibili_account_read', '用插件配置的 B 站账号读取需要登录的内容，只有主人发起的请求能执行。request.action：'
          'comments 登录后的视频评论；subtitles 视频字幕，先省略 language 列出字幕轨道，再按轨道的 lan 取正文；'
          'dynamics 某个 UP 主的空间动态，翻页把上次的 offset 原样传回。',
          summary='由主人读取 B 站账号内容', needs_source=True)
    async def read_account(self, ctx: Invocation,
                           request: Annotated[AccountReadRequest, Field(description='账号读取请求')]) -> dict:
        values = request.model_dump(exclude={'action'})
        if request.action == 'comments':
            return await self.account_comments(ctx, **values)
        if request.action == 'subtitles':
            return await self.subtitles(ctx, **values)
        return await self.feed(ctx, **values)

    async def video(
        self,
        ctx: Invocation,
        bvid: str | None = None,
        aid: int | None = None,
    ) -> dict:
        result=await self.content_client.query('/x/web-interface/view',Video,identifier(bvid,aid))
        return result.output('公开视频元数据（标题、简介、分P等文字信息）。')

    @tool('search_bilibili', '按关键词搜索 B 站，返回一整页结果，只返回数据。kind：video 搜视频；user 搜 UP 主，'
          '结果里有 UID、粉丝数和直播间号，订阅前用它确认是哪位 UP 主。page 是页码，从 1 开始。',
          summary='按关键词搜索 B 站视频或 UP 主')
    async def search(
        self,
        ctx: Invocation,
        keyword: Annotated[
            str,
            Field(description='搜索关键词，不能全为空白', min_length=1),
        ],
        kind: Annotated[
            Literal['video', 'user'],
            Field(description='video 搜视频，user 搜 UP 主'),
        ] = 'video',
        page: Annotated[
            int,
            Field(description='页码，从 1 开始；续页用上次结果的 next_page', ge=1),
        ] = 1,
        order: Annotated[
            Literal['totalrank', 'click', 'pubdate', 'dm', 'stow', 'scores'],
            Field(description='只用于视频：totalrank 综合、click 播放最多、pubdate 最新发布、dm 弹幕最多、stow 收藏最多、scores 评论最多'),
        ] = 'totalrank',
    ) -> dict:
        if not keyword.strip():raise ValueError('关键词不能为空')
        if kind == 'user':
            result=await self.content_client.query('/x/web-interface/wbi/search/type',UserSearchPage,
                                           {'search_type':'bili_user','keyword':keyword,'page':page},wbi=True,device=True)
            users=[{'uid':user.mid,'name':strip_tags(user.uname),'fans':user.fans,'videos':user.videos,
                    'sign':user.usign,'live_room_id':user.room_id or None,'live_now':user.is_live==1}
                   for user in result.data.result]
            return {'users':users,'source':result.url,'fetched_at':result.fetched_at,
                    'note':'按源站相关度排列的 UP 主；live_room_id 为空表示没有开通直播间。',
                    'next_page':result.data.page+1 if result.data.page<result.data.numPages else None}
        result=await self.content_client.query('/x/web-interface/wbi/search/type',SearchPage,
                                       {'search_type':'video','keyword':keyword,'page':page,'order':order},wbi=True,device=True)
        return {**result.output('源搜索整页；标题里可能带源站的高亮标签。'),
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
        return {**result.output('评论区内容，代表评论者的观点；replies=null表示这次接口没有返回列表。'),
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
        if language is None:return {'tracks':[t.model_dump() for t in tracks],'source':player.url,'note':'这里只取得轨道；正文需明确language。'}
        selected_tracks=[t for t in tracks if t.lan==language]
        if len(selected_tracks)!=1:raise ValueError(f'language未唯一匹配源字幕轨道：{[t.lan for t in tracks]}')
        raw=await self.content_client.subtitle(selected_tracks[0].subtitle_url,self.ctx.config['max_subtitle_bytes'])
        try:document=Subtitle.model_validate_json(raw)
        except ValueError as error:raise ValueError(f'{error}; original={raw[:600]!r}') from error
        cues=[{'from_ms':round(c.start*1000),'to_ms':round(c.end*1000),'content':c.content} for c in document.body
              if c.end*1000>start_ms and (end_ms is None or c.start*1000<end_ms)]
        return {'bvid':video.data.bvid,'aid':video.data.aid,'cid':selected.cid,'track':selected_tracks[0].model_dump(),
                       'start_ms':start_ms,'end_ms':end_ms,'cues':cues,'downloaded_bytes':len(raw),'note':'字幕文本，来自视频的字幕轨。'}

    async def feed(
        self,
        ctx: Invocation,
        mid: int,
        offset: str = '',
    ) -> dict:
        self.account.require(ctx);await self.account.verify()
        result=await self.content_client.query('/x/polymer/web-dynamic/v1/feed/space',Feed,{'host_mid':mid,'offset':offset},account=True)
        return result.output('源页中的动态/转发描述、图文摘要和视频简介；未读取图片像素、视频或完整专栏。')


def identifier(bvid:str|None,aid:int|None)->dict:
    if (bvid is None)==(aid is None):raise ValueError('必须且只能提供bvid或aid之一')
    if bvid is not None:
        if re.fullmatch(r'BV[A-Za-z0-9]{10}',bvid) is None:raise ValueError('bvid必须是完整BV号')
        return {'bvid':bvid}
    if aid<=0:raise ValueError('aid必须为正整数')
    return {'aid':aid}


def strip_tags(text: str) -> str:
    return re.sub(r'<[^>]+>', '', text)
