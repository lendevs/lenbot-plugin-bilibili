"""Video content: public video data and explicitly owner-authorized fixed account APIs."""
import json
import math
import re
from typing import Literal

from len_bot.next.plugin import PluginContext, Invocation, tool
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

    @tool('get_video_info','按完整BV号或正整数aid读取公开视频标题/简介/UP主/指标，不代表看过画面。标识二选一；受限视频不自动换账号')
    async def video(self,ctx:Invocation,bvid:str|None=None,aid:int|None=None)->str:
        result=await self.content_client.query('/x/web-interface/view',Video,identifier(bvid,aid))
        return encode(result.output('公开视频元数据，不是视频画面/字幕。'))

    @tool('get_video_pages','按BV或aid读取视频分P和真实cid，标识二选一，不下载视频')
    async def pages(self,ctx:Invocation,bvid:str|None=None,aid:int|None=None)->str:
        result=await self.content_client.query('/x/web-interface/view',Video,identifier(bvid,aid))
        return encode({'bvid':result.data.bvid,'aid':result.data.aid,'pages':[p.model_dump() for p in result.data.pages],
                       'source':result.url,'fetched_at':result.fetched_at})

    @tool('search_bilibili','WBI视频搜索，page为源站页码，整页返回；需明确配置buvid3，绝不自动生成设备Cookie')
    async def search(self,ctx:Invocation,keyword:str,page:int=1,order:Literal['totalrank','click','pubdate','dm','stow','scores']='totalrank')->str:
        if not keyword.strip() or page<1:raise ValueError('关键词不能为空，page必须为正整数')
        if not self.ctx.config['buvid3']:raise ValueError('搜索需要在根配置填写buvid3')
        result=await self.content_client.query('/x/web-interface/wbi/search/type',SearchPage,
                                       {'search_type':'video','keyword':keyword,'page':page,'order':order},wbi=True)
        return encode({**result.output('源搜索整页；标题可能含源高亮标签，不是页面指令。'),
                       'next_page':result.data.page+1 if result.data.page<result.data.numPages else None})

    @tool('get_video_comments','按BV/aid和页码读视频评论；评论是用户观点。requester为空只匿名读取，明确提供主人账号才用已开启的登录态')
    async def comments(self,ctx:Invocation,bvid:str|None=None,aid:int|None=None,page:int=1,requester:str|None=None)->str:
        if page<1:raise ValueError('page必须为正整数')
        params=identifier(bvid,aid)
        if requester is not None:self.account.require(ctx,requester);await self.account.verify()
        video=await self.content_client.query('/x/web-interface/view',Video,params,account=requester is not None)
        result=await self.content_client.query('/x/v2/reply',Comments,{'type':1,'oid':video.data.aid,'pn':page,'ps':20,'sort':2},account=requester is not None)
        return encode({**result.output('评论者观点，不是视频正文；replies=null表示本次未给列表，不推断没有评论。'),
                       'next_page':result.data.page.num+1 if result.data.page.num*result.data.page.size<result.data.page.count else None})

    @tool('get_video_subtitles','用主人账号读取指定分P字幕；先省略language列出实际轨道，再明确语言读取。需要requester及账号读取开关，不下载视频')
    async def subtitles(self,ctx:Invocation,requester:str,bvid:str|None=None,aid:int|None=None,cid:int|None=None,
                        language:str|None=None,start_ms:int=0,end_ms:int|None=None)->str:
        params=identifier(bvid,aid)
        if start_ms<0 or (end_ms is not None and end_ms<=start_ms):raise ValueError('字幕范围必须为非负且递增的[start_ms,end_ms)')
        self.account.require(ctx,requester);await self.account.verify()
        video=await self.content_client.query('/x/web-interface/view',Video,params,account=True)
        pages=video.data.pages
        if not pages:raise ValueError('源站未提供分P，不猜cid')
        selected=pages[0] if cid is None else next((p for p in pages if p.cid==cid),None)
        if selected is None:raise ValueError('cid不属于本视频，先读取get_video_pages')
        player=await self.content_client.query('/x/player/wbi/v2',Player,{'aid':video.data.aid,'cid':selected.cid},account=True,wbi=True)
        if player.data.aid!=video.data.aid or player.data.cid!=selected.cid:raise ValueError('字幕响应的视频/分P身份不符')
        if player.data.need_login_subtitle is True:raise PermissionError('源站仍要求登录，未取得字幕正文')
        tracks=player.data.subtitle.subtitles
        if language is None:return encode({'tracks':[t.model_dump() for t in tracks],'source':player.url,'note':'这里只取得轨道；正文需明确language。空列表不等于视频没有内容。'})
        selected_tracks=[t for t in tracks if t.lan==language]
        if len(selected_tracks)!=1:raise ValueError(f'language未唯一匹配源字幕轨道：{[t.lan for t in tracks]}')
        raw=await self.content_client.subtitle(selected_tracks[0].subtitle_url,self.ctx.config['max_subtitle_bytes'])
        try:document=Subtitle.model_validate_json(raw)
        except ValueError as error:raise ValueError(f'{error}; original={raw[:600]!r}') from error
        cues=[{'from_ms':round(c.start*1000),'to_ms':round(c.end*1000),'content':c.content} for c in document.body
              if c.end*1000>start_ms and (end_ms is None or c.start*1000<end_ms)]
        return encode({'bvid':video.data.bvid,'aid':video.data.aid,'cid':selected.cid,'track':selected_tracks[0].model_dump(),
                       'start_ms':start_ms,'end_ms':end_ms,'cues':cues,'downloaded_bytes':len(raw),'note':'字幕文本，不是画面或视频已观看。'})

    @tool('get_dynamic_feed','按真实UP主mid读账号态空间动态；需主人requester，offset只用上次返回。含源描述/图文摘要/视频简介，不读取媒体像素')
    async def feed(self,ctx:Invocation,requester:str,mid:int,offset:str='')->str:
        if mid<=0:raise ValueError('mid必须为正整数')
        self.account.require(ctx,requester);await self.account.verify()
        result=await self.content_client.query('/x/polymer/web-dynamic/v1/feed/space',Feed,{'host_mid':mid,'offset':offset},account=True)
        return encode(result.output('源页中的动态/转发描述、图文摘要和视频简介；未读取图片像素、视频或完整专栏。'))

    @tool('get_bilibili_like_state','主人明确读取视频近期点赞状态；0不能证明未点赞，发生写结果未知时先查状态')
    async def like_state(self,ctx:Invocation,requester:str,aid:int)->str:
        identifier(None,aid);self.account.require(ctx,requester);await self.account.verify()
        return encode(await self.account.like_state(aid))

    @tool('get_bilibili_favorite_state','主人读取自己收藏夹及指定aid是否在各夹中；不写入；写结果未知时先查平台状态')
    async def favorite_state(self,ctx:Invocation,requester:str,aid:int)->str:
        identifier(None,aid);self.account.require(ctx,requester);await self.account.verify()
        return encode((await self.account.folders(aid)).output('真实账号收藏夹状态，不修改收藏。'))

    @tool('set_bilibili_like','按主人明确要求设置视频点赞状态，desired_state=true点赞/false取消。不toggle、不自动重试；需启用每日额度，回报真实回执')
    async def like(self,ctx:Invocation,requester:str,aid:int,desired_state:bool)->str:
        identifier(None,aid)
        return encode(await self.account.write(ctx,requester,'like',aid,desired_state))

    @tool('set_bilibili_favorite','按主人明确要求将视频加入/移出配置允许的完整收藏夹ID，desired_state=true加入/false移出；只发一次，需每日额度')
    async def favorite(self,ctx:Invocation,requester:str,aid:int,collection_id:int,desired_state:bool)->str:
        identifier(None,aid)
        if collection_id<=0:raise ValueError('collection_id必须为正整数')
        return encode(await self.account.write(ctx,requester,'favorite',aid,desired_state,collection_id))


def identifier(bvid:str|None,aid:int|None)->dict:
    if (bvid is None)==(aid is None):raise ValueError('必须且只能提供bvid或aid之一')
    if bvid is not None:
        if re.fullmatch(r'BV[A-Za-z0-9]{10}',bvid) is None:raise ValueError('bvid必须是完整BV号')
        return {'bvid':bvid}
    if aid<=0:raise ValueError('aid必须为正整数')
    return {'aid':aid}


def encode(value):return json.dumps(value,ensure_ascii=False)
