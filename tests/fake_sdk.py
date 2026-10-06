"""A stand-in for the parts of bilibili-api-python the gateway calls, backed by in-memory pages."""

from io import BytesIO
import types

from PIL import Image

_buffer = BytesIO()
Image.new("RGB", (64, 64), "#e799b0").save(_buffer, format="PNG")
PICTURE = _buffer.getvalue()


class FakeSdk:
    def __init__(self) -> None:
        self.users: dict[int, dict] = {}
        self.dynamics: dict[int, dict] = {}
        self.videos: dict[int, dict] = {}
        self.comments: dict[int, list[dict]] = {}
        self.calls: list[tuple] = []
        sdk = self

        class Credential:
            def __init__(self, **values):
                self.values = values

            def has_sessdata(self):
                return bool(self.values.get("sessdata"))

        class User:
            def __init__(self, uid, credential=None):
                self.uid = uid

            async def get_user_info(self):
                sdk.calls.append(("user", self.uid))
                return sdk.users.get(self.uid, {"name": f"UP{self.uid}", "face": ""})

            async def get_relation_info(self):
                return {"following": 1, "follower": 2}

            async def get_up_stat(self):
                return {"likes": 3}

            async def get_dynamics_new(self, offset=""):
                sdk.calls.append(("dynamics", self.uid))
                return sdk.dynamics.get(self.uid, {"items": [], "has_more": False, "offset": ""})

            async def get_videos(self, pn=1, ps=30):
                return sdk.videos.get(self.uid, {"list": {"vlist": []}})

        async def get_comments_lazy(oid, type_, offset="", order=None, credential=None):
            sdk.calls.append(("comments", oid, offset))
            return {"replies": list(sdk.comments.get(oid, [])), "top_replies": [],
                    "cursor": {"is_end": True, "pagination_reply": {"next_offset": ""}}}

        class Comment:
            def __init__(self, oid, type_, rpid, credential=None):
                self.oid, self.rpid = oid, rpid

            async def get_sub_comments(self, page_index=1, page_size=20):
                return {"replies": [], "page": {"count": 0, "num": page_index, "size": page_size}}

        class Video:
            def __init__(self, bvid, credential=None):
                self.bvid = bvid

            async def get_info(self):
                return {"stat": {"like": 520, "reply": 13, "share": 14, "view": 1000}}

        module = types.ModuleType("bilibili_api")
        module.Credential = Credential
        module.select_client = lambda name: None
        module.user = types.SimpleNamespace(User=User)
        module.comment = types.SimpleNamespace(
            CommentResourceType=lambda value: value, OrderType=types.SimpleNamespace(TIME="time"),
            get_comments_lazy=get_comments_lazy, Comment=Comment)
        module.video = types.SimpleNamespace(Video=Video)
        self.module = module
