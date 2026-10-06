# 来源

本仓库由 `lenbot-personal` 中的 `bilibili_content` 与 `bilibili_live` 两个插件合并而成（2026-10-05），协议实现未改动。

## 视频内容（content.py、client.py、account.py、protocol.py）

- 本地 `SocialSisterYi/bilibili-API-collect` 快照 `cfc5fdd`（2026-08-12同步，2026-09-28核对）：video/info.md、video/action.md、search/search_request.md、comment/list.md、dynamic/space.md、fav/info.md、login/login_info.md、misc/sign/wbi.md、misc/errcode.md。文档许可CC-BY-NC 4.0；这里只按协议事实独立实现，不复制文档示例代码或素材。
- WBI混排表和MD5仅用于平台要求的请求签名，不是内容去重或审计指纹。编码按百分号大写/空格%20；nav -101仍携带wbi_img是协议已明确的匿名行为，不是失败兜底。
- [固定SDK提交的接口定义](https://raw.githubusercontent.com/Nemo2011/bilibili-api/0147ab61aa5a9f821c9b441cb1ddfdc761a3d999/bilibili_api/data/api/video.json)：核对player `x/player/wbi/v2`需要登录、WBI，以及收藏 `x/v3/fav/resource/deal`。本机SDK文档快照同提交，未引入SDK依赖、网络重试或自动设备参数生成。主线raw URL本次404，未声称核对主线当前版本。
- 旧LenBot插件只用于功能盘点，不保留旧Capability/Gate、action_reviewer、register_action、reserve_attempt、trace或请求归属证明。
- 新插件代码采用GNU AGPL v3或更新版本，见LICENSE。接口当前在线表现未调用真实B站验证。

## 直播监测（live.py、live_protocol.py）

- `SocialSisterYi/bilibili-API-collect` 的 `docs/live/info.md`（直播间基本信息）、`docs/misc/errcode.md`。本机参考快照提交 `cfc5fdd`，同步于2026-08-12，2026-09-28读取核对。文档本身为CC-BY-NC 4.0，本插件不复制其示例代码或素材。
- 端点：`GET https://api.live.bilibili.com/room/v1/Room/get_info?room_id=...`。实际身份使用 `uid`、`room_id`、`short_id`，状态0/1/2分别未播/直播/轮播。仅状态1解释来源 `live_time`，非直播的 `0000-00-00 00:00:00` 原样保留，不伪造起点。
- 依据已核对协议独立实现新接口，不复制旧插件的动作审查、别名目录、claim状态、渲染回退或模型播报流程。
- 源站当前在线协议和真实账号/平台未在本轮调用；本机合成观察不是实际开播验收。
- 新插件代码采用 GNU AGPL v3 或更新版本，见LICENSE。
