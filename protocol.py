"""Bilibili response contracts used by the fixed public/account endpoints."""
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, model_validator

Positive = Annotated[int, Field(gt=0)]
Count = Annotated[int, Field(ge=0)]
Flag = Annotated[int, Field(ge=0, le=1)]


class DTO(BaseModel):
    model_config = ConfigDict(strict=True, extra='ignore')


class Envelope(DTO):
    code: int
    message: str
    data: JsonValue = None


class WbiImage(DTO):
    img_url: str
    sub_url: str


class Nav(DTO):
    isLogin: bool
    mid: Positive | None = None
    wbi_img: WbiImage


class Owner(DTO):
    mid: Positive
    name: str
    face: str


class VideoPage(DTO):
    cid: Positive
    page: Positive
    part: str
    duration: Count


class Video(DTO):
    bvid: str
    aid: Positive
    title: str
    desc: str
    pic: str
    pubdate: int
    duration: Count
    owner: Owner
    stat: dict[str, JsonValue]
    pages: list[VideoPage]


class SearchVideo(DTO):
    bvid: str
    aid: Positive
    title: str
    author: str
    mid: Positive
    description: str
    arcurl: str
    pic: str
    pubdate: int
    duration: str
    play: int | str


class SearchPage(DTO):
    page: Positive
    pagesize: Positive
    numResults: Count
    numPages: Count
    result: list[SearchVideo]


class CommentPage(DTO):
    num: Positive
    size: Positive
    count: Count


class Comments(DTO):
    page: CommentPage
    replies: list[dict[str, JsonValue]] | None
    hots: list[dict[str, JsonValue]] | None = None


class SubtitleTrack(DTO):
    id: int
    lan: str
    lan_doc: str
    subtitle_url: str


class SubtitleTracks(DTO):
    subtitles: list[SubtitleTrack]


class Player(DTO):
    aid: Positive
    cid: Positive
    need_login_subtitle: bool | None = None
    subtitle: SubtitleTracks


class Cue(DTO):
    start: float = Field(alias='from', ge=0, allow_inf_nan=False)
    end: float = Field(alias='to', ge=0, allow_inf_nan=False)
    content: str

    @model_validator(mode='after')
    def ordered(self):
        if self.end < self.start:
            raise ValueError('字幕结束时间早于开始时间')
        return self


class Subtitle(DTO):
    body: list[Cue]


class Folder(DTO):
    id: Positive
    mid: Positive
    title: str
    fav_state: Flag


class Folders(DTO):
    count: Count
    folders: list[Folder] | None = Field(alias='list')


class Counts(DTO):
    model_config = ConfigDict(strict=True, extra='forbid')
    like: Count = 0
    favorite: Count = 0


def parse[T](data: JsonValue, model: type[T], raw: bytes) -> T:
    try:
        return TypeAdapter(model).validate_python(data, strict=True)
    except ValueError as error:
        raise ValueError(f'{error}; original={raw[:600]!r}') from error


class Identity(DTO):
    isLogin: bool
    mid: Positive | None = None


class Text(DTO):
    text: str


class DynamicAuthor(DTO):
    mid: Positive
    name: str
    pub_ts: int | None = None


class Opus(DTO):
    title: str | None = None
    summary: Text


class Archive(DTO):
    bvid: str
    title: str
    desc: str


class Major(DTO):
    type: str
    opus: Opus | None = None
    archive: Archive | None = None


class DynamicBody(DTO):
    desc: Text | None = None
    major: Major | None = None


class Modules(DTO):
    module_author: DynamicAuthor
    module_dynamic: DynamicBody


class DynamicItem(DTO):
    id_str: str
    type: str
    modules: Modules
    orig: 'DynamicItem | None' = None


class Feed(DTO):
    has_more: bool
    offset: str
    items: list[DynamicItem]
