"""Business requests for the model tools; each action accepts only its own fields."""
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field


class Request(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid')


class VideoQuery(Request):
    action: Literal['info']
    bvid: Annotated[str | None, Field(description='完整 BV 号，与 aid 二选一', examples=['BV1xx411c7mD'])] = None
    aid: Annotated[int | None, Field(description='av 号，正整数；与 bvid 二选一')] = None


class VideoComments(Request):
    action: Literal['comments']
    bvid: Annotated[str | None, Field(description='完整 BV 号，与 aid 二选一', examples=['BV1xx411c7mD'])] = None
    aid: Annotated[int | None, Field(description='av 号，正整数；与 bvid 二选一')] = None
    page: Annotated[int, Field(description='页码从 1 起；续页用 next_page', ge=1)] = 1


class AccountComments(Request):
    action: Literal['comments']
    bvid: Annotated[str | None, Field(description='完整 BV 号，与 aid 二选一', examples=['BV1xx411c7mD'])] = None
    aid: Annotated[int | None, Field(description='av 号，正整数；与 bvid 二选一')] = None
    page: Annotated[int, Field(description='页码从 1 起；续页用 next_page', ge=1)] = 1


class VideoSubtitles(Request):
    action: Literal['subtitles']
    bvid: Annotated[str | None, Field(description='完整 BV 号，与 aid 二选一', examples=['BV1xx411c7mD'])] = None
    aid: Annotated[int | None, Field(description='av 号，正整数；与 bvid 二选一')] = None
    cid: Annotated[int | None, Field(description='分 P 的 cid，取自 bilibili_video 的 info 结果；省略为第一 P', ge=1)] = None
    language: Annotated[str | None, Field(description='字幕轨道的 lan 值，例如 ai-zh；省略只列出轨道')] = None
    start_ms: Annotated[int, Field(description='字幕区间起点，毫秒，含该时刻', ge=0)] = 0
    end_ms: Annotated[int | None, Field(description='字幕区间终点，毫秒，不含该时刻；省略至字幕末尾', ge=1)] = None


class DynamicFeed(Request):
    action: Literal['dynamics']
    mid: Annotated[int, Field(description='UP 主的 B 站 UID，正整数', ge=1)]
    offset: Annotated[str, Field(description='上次动态页返回的 offset，原样传递；空文本读取第一页')] = ''


class LiveStatus(Request):
    action: Literal['status']
    uid: Annotated[int | None, Field(ge=1, description='本群订阅主播 UID；省略读取全部订阅房间的当前状态')] = None


class LiveSubscriptions(Request):
    action: Literal['subscriptions']
    uid: Annotated[int | None, Field(ge=1, description='本群订阅主播 UID；省略读取全部直播订阅设置与最近样本')] = None


class FollowSubscriptions(Request):
    action: Literal['follows']


class LiveAdd(Request):
    action: Literal['live_add']
    uid: Annotated[int, Field(ge=1, description='UP 主的 B 站 UID，取自 search_bilibili 的 kind=user 结果')]
    name: Annotated[str, Field(min_length=1, description='开播提醒里用的名字，一般取搜索结果的 name')]
    at_all: Annotated[bool | None, Field(description='开播时是否 @全体成员；省略时新订阅为否，已有订阅保持不变')] = None


class LiveRemove(Request):
    action: Literal['live_remove']
    uid: Annotated[int, Field(ge=1, description='要在本群取消开播提醒的 UP 主 UID')]


class FollowAdd(Request):
    action: Literal['follow_add']
    uid: Annotated[int, Field(ge=1, description='UP 主的 B 站 UID，取自 search_bilibili 的 kind=user 结果')]
    name: Annotated[str, Field(description='备注名，面板和查询里显示')] = ''
    dynamic: Annotated[bool | None, Field(description='推送新动态；省略时新订阅为是，已有订阅保持不变')] = None
    video: Annotated[bool | None, Field(description='推送新视频；省略时新订阅为是，已有订阅保持不变')] = None
    comment: Annotated[bool | None, Field(description='推送 UP 主本人的评论；省略时新订阅为否，已有订阅保持不变')] = None


class FollowRemove(Request):
    action: Literal['follow_remove']
    uid: Annotated[int, Field(ge=1, description='要在本群取消推送的 UP 主 UID')]


VideoRequest = Annotated[VideoQuery | VideoComments, Field(discriminator='action')]
AccountReadRequest = Annotated[AccountComments | VideoSubtitles | DynamicFeed, Field(discriminator='action')]
MonitorRequest = Annotated[LiveStatus | LiveSubscriptions | FollowSubscriptions, Field(discriminator='action')]
SubscriptionRequest = Annotated[LiveAdd | LiveRemove | FollowAdd | FollowRemove, Field(discriminator='action')]
