"""Video tools: request signing and argument rules that do not need the real site."""

from pathlib import Path

import pytest

from len_bot.next.plugin_testing import PluginTest

PACKAGE = Path(__file__).parents[1]


def test_wbi_signature_matches_documented_example():
    # Example from SocialSisterYi/bilibili-API-collect docs/misc/sign/wbi.md.
    import importlib.util, sys
    spec = importlib.util.spec_from_file_location("bilibili_pkg", PACKAGE / "__init__.py",
                                                  submodule_search_locations=[str(PACKAGE)])
    package = importlib.util.module_from_spec(spec)
    sys.modules["bilibili_pkg"] = package
    spec.loader.exec_module(package)
    from bilibili_pkg.client import sign
    signed = sign({"foo": "114", "bar": "514", "zab": 1919810},
                  "https://i0.hdslb.com/bfs/wbi/7cd084941338484aae1ad9425b84077c.png",
                  "https://i0.hdslb.com/bfs/wbi/4932caff0ff746eab6f01bf08b70ac45.png", 1702204169)
    assert signed["w_rid"] == "8f6f2b5b3d485fe1886cec6a0be8c5d4"


@pytest.mark.asyncio
async def test_video_tools_require_exactly_one_identifier():
    async with PluginTest(PACKAGE) as bot:
        for arguments in ({}, {"bvid": "BV1xx411c7mD", "aid": 1}):
            with pytest.raises(ValueError, match="bvid或aid"):
                await bot.tool("get_video_info", arguments)
        with pytest.raises(ValueError, match="完整BV号"):
            await bot.tool("get_video_pages", {"bvid": "BV1"})


@pytest.mark.asyncio
async def test_account_writes_need_account_settings():
    with pytest.raises(RuntimeError, match="account_uid和sessdata"):
        async with PluginTest(PACKAGE, config={"daily_like_limit": 1}):
            pass
