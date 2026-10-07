"""Business requests for the model tools; each action accepts only its own fields."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class Request(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')


class VideoQuery(Request):
    action: Literal['info']
    bvid: Annotated[str | None, Field(description='完整 BV 号，与 aid 二选一', examples=['BV1xx411c7mD'])] = None
    aid: Annotated[int | None, Field(description='正整数 av 号；视频查询时与 bvid 二选一')] = None


class VideoComments(Request):
    action: Literal['comments']
    bvid: Annotated[str | None, Field(description='完整 BV 号，与 aid 二选一', examples=['BV1xx411c7mD'])] = None
    aid: Annotated[int | None, Field(description='正整数 av 号；视频查询时与 bvid 二选一')] = None
    page: Annotated[int, Field(description='页码从 1 起；续页用 next_page', ge=1)] = 1


class AccountComments(Request):
    action: Literal['comments']
    bvid: Annotated[str | None, Field(description='完整 BV 号，与 aid 二选一', examples=['BV1xx411c7mD'])] = None
    aid: Annotated[int | None, Field(description='正整数 av 号；视频查询时与 bvid 二选一')] = None
    page: Annotated[int, Field(description='页码从 1 起；续页用 next_page', ge=1)] = 1


class VideoSubtitles(Request):
    action: Literal['subtitles']
    bvid: Annotated[str | None, Field(description='完整 BV 号，与 aid 二选一', examples=['BV1xx411c7mD'])] = None
    aid: Annotated[int | None, Field(description='正整数 av 号；视频查询时与 bvid 二选一')] = None
    cid: Annotated[int | None, Field(description='bilibili_video 的 info 结果中的真实分 P cid；省略选择第一 P', ge=1)] = None
    language: Annotated[str | None, Field(description='实际字幕轨道的 lan 值；省略只列出轨道')] = None
    start_ms: Annotated[int, Field(description='字幕区间起点，毫秒，含该时刻', ge=0)] = 0
    end_ms: Annotated[int | None, Field(description='字幕区间终点，毫秒，不含该时刻；省略至字幕末尾', ge=1)] = None


class DynamicFeed(Request):
    action: Literal['dynamics']
    mid: Annotated[int, Field(description='真实 UP 主 B 站 UID，正整数', ge=1)]
    offset: Annotated[str, Field(description='上次动态页返回的 offset，原样传递；空文本读取第一页')] = ''


class LikeState(Request):
    action: Literal['like_state']
    aid: Annotated[int, Field(description='正整数 av 号；视频查询时与 bvid 二选一')]


class FavoriteState(Request):
    action: Literal['favorite_state']
    aid: Annotated[int, Field(description='正整数 av 号；视频查询时与 bvid 二选一')]


class SetLike(Request):
    action: Literal['like']
    aid: Annotated[int, Field(description='正整数 av 号；视频查询时与 bvid 二选一')]
    desired_state: Annotated[bool, Field(description='true 设置，false 取消；不 toggle')]


class SetFavorite(Request):
    action: Literal['favorite']
    aid: Annotated[int, Field(description='正整数 av 号；视频查询时与 bvid 二选一')]
    collection_id: Annotated[int, Field(description='配置明确允许且属于该账号的完整收藏夹 ID', ge=1)]
    desired_state: Annotated[bool, Field(description='true 设置，false 取消；不 toggle')]


class LiveStatus(Request):
    action: Literal['status']
    uid: Annotated[int | None, Field(ge=1, description='本群订阅主播 UID；省略读取全部订阅房间的当前状态')] = None


class LiveSubscriptions(Request):
    action: Literal['subscriptions']
    uid: Annotated[int | None, Field(ge=1, description='本群订阅主播 UID；省略读取全部直播订阅设置与最近样本')] = None


class FollowSubscriptions(Request):
    action: Literal['follows']


VideoRequest = Annotated[VideoQuery | VideoComments, Field(discriminator='action')]
AccountReadRequest = Annotated[AccountComments | VideoSubtitles | DynamicFeed | LikeState | FavoriteState, Field(discriminator='action')]
AccountWriteRequest = Annotated[SetLike | SetFavorite, Field(discriminator='action')]
MonitorRequest = Annotated[LiveStatus | LiveSubscriptions | FollowSubscriptions, Field(discriminator='action')]
