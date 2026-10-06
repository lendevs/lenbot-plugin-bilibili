"""Live-room monitoring through the public local plugin harness and a local room endpoint."""

import asyncio
import json
from pathlib import Path

import pytest

from len_bot.next.plugin_testing import PluginTest

PACKAGE = Path(__file__).parents[1]
SCENE = "onebot:group:80001"


def room(status: int, live_time: str = "0000-00-00 00:00:00") -> dict:
    return {"code": 0, "message": "0", "data": {
        "uid": 672328094, "room_id": 22637261, "short_id": 0, "live_status": status, "title": "测试直播",
        "live_time": live_time, "user_cover": "", "keyframe": ""}}


def config(source) -> dict:
    return {"rooms": [{"uid": 672328094, "room_id": 22637261, "name": "嘉然", "scenes": [SCENE]}],
            "live_api_url": source.url + "/room"}


async def first_poll(bot) -> None:
    while bot.state()["plugins"][0]["backgrounds"][0]["last_finished"] is None:
        await asyncio.sleep(0.01)


@pytest.mark.asyncio
async def test_status_tool_reads_room_again(source):
    source.json("/room", room(0))
    async with PluginTest(PACKAGE, config=config(source)) as bot:
        assert json.loads(await bot.tool("get_live_status", {}))["items"][0]["status"] == "未开播"
        source.json("/room", room(1, "2026-10-05 20:00:00"))
        item = json.loads(await bot.tool("get_live_status", {}))["items"][0]
        assert (item["status"], item["started_at"]) == ("直播中", "2026-10-05T20:00:00+08:00")
        assert source.requests[-1] == ("/room", {"room_id": ["22637261"]})


@pytest.mark.asyncio
async def test_session_start_and_end_become_scene_events(source):
    source.json("/room", room(0))
    async with PluginTest(PACKAGE, config=config(source)) as bot:
        await first_poll(bot)
        assert bot.events() == []
        plugin = bot.host.plugins["bilibili"]
        source.json("/room", room(1, "2026-10-05 20:00:00"))
        await plugin.instance.poll(plugin.context)
        source.json("/room", room(1, "2026-10-05 20:00:00"))
        await plugin.instance.poll(plugin.context)
        source.json("/room", room(2))
        await plugin.instance.poll(plugin.context)
        texts = [event["content"] for event in sorted(bot.events(), key=lambda event: event["id"])]
        assert len(texts) == 2
        assert "新直播场次" in texts[0] and "嘉然" in texts[0]
        assert "已结束" in texts[1] and "轮播中" in texts[1]


@pytest.mark.asyncio
async def test_rooms_reject_duplicate_room_ids(source):
    rooms = config(source)["rooms"] * 2
    with pytest.raises(RuntimeError, match="同一个房号"):
        async with PluginTest(PACKAGE, config={"rooms": rooms}):
            pass
