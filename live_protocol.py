"""Typed public room samples; status 2 is replay, not a new live session."""

from datetime import datetime
from typing import Annotated
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator

Positive = Annotated[int, Field(gt=0)]
Scene = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_-]*:(group|private):[^:\s/\\]+$')]


class Subscription(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', frozen=True)
    uid: Positive
    room_id: Positive
    name: str = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
    at_all: bool = False

    @field_validator('scenes')
    @classmethod
    def unique_scenes(cls, scenes: list[str]) -> list[str]:
        if len(scenes) != len(set(scenes)):
            raise ValueError('同一房间的scenes不能重复')
        return scenes


def subscriptions(raw: list[dict]) -> list[Subscription]:
    items = TypeAdapter(list[Subscription]).validate_python(raw)
    if len({item.room_id for item in items}) != len(items):
        raise ValueError('rooms不能重复配置同一个房号；合并该房间的scenes')
    if len({item.uid for item in items}) != len(items):
        raise ValueError('rooms不能重复配置同一UID，避免同一房间长短号重复监测')
    return items


class Room(BaseModel):
    model_config = ConfigDict(strict=True, extra='ignore', frozen=True)
    uid: Positive
    room_id: Positive
    short_id: int = Field(ge=0)
    live_status: int = Field(ge=0, le=2)
    title: str
    live_time: str
    user_cover: str
    keyframe: str
    area_name: str = ''
    parent_area_name: str = ''


class Envelope(BaseModel):
    model_config = ConfigDict(strict=True, extra='ignore')
    code: int
    message: str
    data: object = None


class Sample(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    room: Room
    sampled_at: float
    started_at: datetime | None
    url: str


def parse_room(body: bytes, subscription: Subscription, *, now: float, zone: ZoneInfo) -> Sample:
    try:
        reply = Envelope.model_validate_json(body)
        if reply.code != 0:
            raise ValueError(f'B站房间接口 code={reply.code}: {reply.message}')
        room = Room.model_validate(reply.data)
        if room.uid != subscription.uid or subscription.room_id not in {room.room_id, room.short_id}:
            raise ValueError(f'直播房间身份与订阅不符：请求uid={subscription.uid}, room_id={subscription.room_id}; '
                             f'返回uid={room.uid}, room_id={room.room_id}, short_id={room.short_id}')
        started = (datetime.strptime(room.live_time, '%Y-%m-%d %H:%M:%S').replace(tzinfo=zone)
                   if room.live_status == 1 else None)
        return Sample(room=room, sampled_at=now, started_at=started, url=f'https://live.bilibili.com/{room.room_id}')
    except (ValidationError, ValueError) as error:
        raise ValueError(f'{error}; original={body[:600]!r}') from error
