# lenbot-plugin-bilibili

LenBot 插件接口 1 的哔哩哔哩合集，插件名 `bilibili`。包含两部分：

- **视频内容**：公开视频、分P、WBI 搜索、评论；主人明确请求的字幕、空间动态、点赞收藏状态和设定状态。账号能力默认关闭。
- **直播监测**：每 30 秒观察订阅的直播间，真实开播／下播变化进入场景事件，由大脑决定如何回应。不读取账号，没有插件内模型或固定群播报。

## 安装

在 LenBot 面板「能力 → 插件」填写本仓库的 Git 地址，或导入发布页的 ZIP，应用后配置参数并选择启用的群。也可以把仓库目录直接放进实例的 `plugins/`。

根配置的局部示例（不要覆盖完整根配置）：

```json
{
  "owners": ["onebot:70001"],
  "plugins": {
    "bilibili": {
      "rooms": [
        {"uid": 100001, "room_id": 12345, "name": "填写真实主播名称", "scenes": ["onebot:group:10001"]}
      ],
      "account_read_enabled": false
    }
  },
  "scenes": {"onebot:group:10001": {"plugins": ["bilibili"]}}
}
```

各工具还需要角色 `tools` 放行相应名称与 `tool_search`。

### 从旧的两个独立插件迁移

旧插件 `bilibili_content` 与 `bilibili_live` 合并为 `bilibili`，工具名不变：

- `plugins.bilibili_content` 的全部字段原样移到 `plugins.bilibili`。
- `plugins.bilibili_live.rooms` 移到 `plugins.bilibili.rooms`；`api_url` 改名 `live_api_url`，`source_timezone` 改名 `live_source_timezone`；`request_timeout_seconds` 两部分共用一个。
- 场景 `plugins` 列表里的 `bilibili_content`、`bilibili_live` 换成 `bilibili`。
- 旧数据目录里只有 `bilibili_content/write-counts.json` 需要移到新插件数据目录 `bilibili/`；直播监测不保存数据。

## 直播监测

`rooms` 每项填写真实 UID、长／短房号、名称和要提醒的群。默认接口是 `https://api.live.bilibili.com/room/v1/Room/get_info`。

- 每个房间的群列表与宿主实际启用本插件的群取交集。交集为空就不请求该房间；多个群订阅同一房间，每周期只请求一次。相同 UID 或房号不能分成多条记录，合并 `scenes` 即可。源响应的 UID 和长／短房号必须与配置一致。
- 固定 30 秒周期，启动后立即采样；新进程每个房间第一个成功样本只建立基线，不补报停机期间的直播。
- 状态 1 才是正在直播，状态 2 是轮播。持续状态 1 但来源开播时间改变，视为新场次；从 1 变成 0／2 发下播事件。事件包含实际采样时间、标题、房号、UID 和链接，时间换算成本群时区。
- 某个房间采样失败只结束它本次采样并保留原始错误，其他房间继续；下一周期重新观察。相同场次不重复发事件。不保证宿主硬崩溃时严格只投递一次。
- 安静时段由宿主场景事件规则处理。事件是当时的观察，不保证大脑稍后回应时仍在直播。

低频工具：

- `get_live_status(uid=None)`：重新读取本群订阅对象，请求失败就报原始错误；不拿旧样本当当前状态，也不影响监测基线。
- `get_live_subscriptions(uid=None)`：本群真实订阅、最近一次成功采样和最近一次失败。`last_sample` 只是上次成功样本，当前状态用上一个工具重读。

本插件不自动增删订阅，运营者在面板修改 `rooms` 和场景启用名单。

## 视频内容

公共请求不带 SESSDATA。账号工具只接受根配置 `owners` 里的真实请求人，每次账号调用前查询 nav 核对真实 B 站 UID。凭据只由运营者在面板填写；不读取浏览器或环境变量，不自动登录、刷新 Cookie 或生成 buvid。

- 公共视频／分P 不需要账号；搜索需要真实 `buvid3`。
- 登录态读取需要开启 `account_read_enabled` 并填写 `account_uid`、`sessdata`。
- 点赞／收藏还需要相应 `daily_*_limit` 大于 0 和 `bili_jct`；点赞需要 `buvid3`，收藏需要完整收藏夹 ID 允许列表。写入也要求开启读取，以便结果未知时独立核对。
- 没有批量发布、投币、任意带 Cookie 的 URL 或浏览器登录工具。

工具：

- `get_video_info` / `get_video_pages`：完整 BV 号或正整数 aid 二选一，公开视频元数据与分P，不代表看过视频。
- `search_bilibili`：WBI 签名的搜索端点，`page` 为来源页码，整页返回并给出 `next_page`。WBI 口令成功后缓存 1 小时，失败不重试。
- `get_video_comments`：默认匿名；明确传入主人 `requester` 才用登录态，匿名失败不自动切换。
- `get_video_subtitles`：主人登录态读取指定分P；先不传 `language` 列出真实轨道，再指定语言读取时间范围。字幕走独立的无 Cookie 请求，不播放或下载视频。
- `get_dynamic_feed`：主人登录态的空间动态，保留来源描述、图文摘要、视频简介和响应里已有的转发；`offset` 原样传递。
- `get_bilibili_like_state` / `get_bilibili_favorite_state`：主人独立核对平台状态。点赞接口返回 0 只表示没查到近期点赞。
- `set_bilibili_like` / `set_bilibili_favorite`：明确 `desired_state`；先核对身份与当前状态，已符合就不发请求，否则只请求一次。非零业务码如实返回 `platform_error`；等待回执时超时、取消或响应异常算结果未知，先查状态，不自动重发。

同一账号的写入在插件内串行执行。插件数据目录的 `write-counts.json` 只保存账号、日期和两种动作的写尝试次数，在发请求前写入；结果未知或取消也计一次。日额度按唯一的 `quota_timezone` 计算，跨群调用不会重置。计数文件损坏直接报错。不要让多个进程共用同一插件数据目录。

## 开发

在与 LenBot 同级的目录里，用宿主的开发环境运行测试：

```sh
uv run --project ../LenBot --no-sync pytest -q
```

测试用本地 HTTP 服务模拟直播间接口，不访问真实 B 站。真实账号、源站当前协议和 QQ 内的使用效果未在测试中验证。

许可证：GNU AGPL v3 或更新版本，见 [LICENSE](LICENSE)；协议来源见 [SOURCE.md](SOURCE.md)。
