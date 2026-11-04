# 来源

本仓库由 `lenbot-personal` 中的 `bilibili_content` 与 `bilibili_live` 两个插件合并而成（2026-10-05），协议实现未改动。2026-10-06 加入关注推送和推送卡片。

## 视频内容（content.py、client.py、account.py、protocol.py）

- 本地 `SocialSisterYi/bilibili-API-collect` 快照 `cfc5fdd`（2026-08-12同步，2026-09-28核对）：video/info.md、video/action.md、search/search_request.md、comment/list.md、dynamic/space.md、fav/info.md、login/login_info.md、misc/sign/wbi.md、misc/errcode.md。文档许可CC-BY-NC 4.0；这里只按协议事实独立实现，不复制文档示例代码或素材。
- WBI混排表和MD5用于平台要求的请求签名。编码按百分号大写、空格写%20；nav返回-101时仍携带wbi_img，这是协议明确的匿名行为。
- [固定SDK提交的接口定义](https://raw.githubusercontent.com/Nemo2011/bilibili-api/0147ab61aa5a9f821c9b441cb1ddfdc761a3d999/bilibili_api/data/api/video.json)：核对player `x/player/wbi/v2`需要登录、WBI，以及收藏 `x/v3/fav/resource/deal`。本机SDK文档快照为同一提交。
- 旧LenBot插件用于功能盘点。
- 新插件代码采用GNU AGPL v3或更新版本，见LICENSE。

## 直播监测（live.py、live_protocol.py）

- `SocialSisterYi/bilibili-API-collect` 的 `docs/live/info.md`（直播间基本信息）、`docs/misc/errcode.md`。本机参考快照提交 `cfc5fdd`，同步于2026-08-12，2026-09-28读取核对。文档本身为CC-BY-NC 4.0，本插件不复制其示例代码或素材。
- 端点：`GET https://api.live.bilibili.com/room/v1/Room/get_info?room_id=...`。实际身份使用 `uid`、`room_id`、`short_id`，状态0/1/2分别未播/直播/轮播。只在状态1时解释来源 `live_time`，非直播时的 `0000-00-00 00:00:00` 原样保留。
- 依据已核对协议独立实现新接口。
- 新插件代码采用 GNU AGPL v3 或更新版本，见LICENSE。

## 关注推送（gateway.py、comment_journal.py、comment_capture.py、push.py）

- `gateway.py`、`comment_journal.py`、`comment_capture.py` 来自仓库所有者自己的 AstrBot 插件 `astrbot_plugin_asoul` 的 `asoul_bilibili.py`、`asoul_comment_journal.py`、`asoul_comment_capture.py`，只改了模块导入；动态附加卡片的文字节点改标为 `attachment`，方便卡片单独绘制。对应测试 `test_bilibili_monitor.py`、`test_comment_journal.py`、`test_comment_capture.py` 一并移植。
- `push.py` 按 AstrBot 版 `asoul_bilibili_runtime.py` 的轮询、错误分类和投递顺序重写：投递目标从 AstrBot 消息来源换成 LenBot 场景，状态存插件 KV 和数据目录，@全体 由配置决定。
- 依赖 `bilibili-api-python==17.4.1`（GPL-3.0-or-later），只用 httpx 客户端。`tests/data/dynamics.json` 是 2026-03-31 录制的公开空间动态页中的 3 条。

## 卡片（card_kit.py、push_card.py、assets/NotoSansSC.ttf）

- `push_card.py` 按仓库所有者的 `astrbot_plugin_asoul` 的 `templates/bilibili_card.html` 用 Pillow 重写，CSS 尺寸减半作为逻辑像素。`card_kit.py` 与 `lenbot-plugin-asoul`、`lenbot-plugin-group-digest` 共用同一份，三个仓库一起修改。
- `assets/NotoSansSC.ttf` 为 Google Fonts 分发的 Noto Sans SC 可变字重字体，按 SIL Open Font License 1.1 分发，许可证见 `assets/NotoSansSC-OFL.txt`。
