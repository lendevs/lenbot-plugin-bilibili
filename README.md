# lenbot-plugin-bilibili

LenBot 插件接口 1 的哔哩哔哩合集，插件名 `bilibili`。包含三部分：

- **视频内容**：公开视频、分P、WBI 搜索、评论；主人明确请求的字幕和空间动态。账号能力默认关闭。
- **直播监测**：每 30 秒观察订阅的直播间。开播时向群里发开播卡片，开播／下播变化同时进入场景事件，由大脑决定是否再回应。
- **关注推送**：关注的 UP 主发了新动态、新视频，或本人在自己的动态和视频下发表／回复评论，就以卡片推送到订阅的群。

## 安装

在 LenBot 面板「插件」填写本仓库的 Git 地址，或导入发布页的 ZIP，应用后配置参数并选择启用的群。也可以把仓库目录直接放进实例的 `plugins/`。

根配置的局部示例（不要覆盖完整根配置）：

```json
{
  "owners": ["onebot:70001"],
  "plugins": {
    "bilibili": {
      "rooms": [
        {"uid": 100001, "room_id": 12345, "name": "填写真实主播名称", "scenes": ["onebot:group:10001", "telegram:group:-1001234567890"], "at_all": false}
      ],
      "follows": [
        {"uid": 100001, "name": "备注名", "scenes": ["onebot:group:10001", "telegram:group:-1001234567890"], "dynamic": true, "video": true, "comment": false}
      ],
      "sessdata": "关注推送需要",
      "account_read_enabled": false
    }
  },
  "scenes": {
    "onebot:group:10001": {"plugins": ["bilibili"]},
    "telegram:group:-1001234567890": {"plugins": ["bilibili"]}
  }
}
```

各工具还需要角色 `tools` 放行相应名称与 `tool_search`。

### 从旧的两个独立插件迁移

旧插件 `bilibili_content` 与 `bilibili_live` 合并为 `bilibili`，工具名不变：

- `plugins.bilibili_content` 的全部字段原样移到 `plugins.bilibili`。
- `plugins.bilibili_live.rooms` 移到 `plugins.bilibili.rooms`；`api_url` 改名 `live_api_url`，`source_timezone` 改名 `live_source_timezone`；`request_timeout_seconds` 两部分共用一个。
- 场景 `plugins` 列表里的 `bilibili_content`、`bilibili_live` 换成 `bilibili`。
- 直播监测在启动后重新建立基线。

## 直播监测

`rooms` 每项填写真实 UID、长／短房号、名称和要提醒的群。默认接口是 `https://api.live.bilibili.com/room/v1/Room/get_info`。

- 每个房间的群列表与宿主实际启用本插件的群取交集。交集为空就不请求该房间；多个群订阅同一房间，每周期只请求一次。相同 UID 或房号不能分成多条记录，合并 `scenes` 即可。源响应的 UID 和长／短房号必须与配置一致。
- 固定 30 秒周期，启动后立即采样；新进程每个房间第一个成功样本作为基线，停机期间的直播跳过。
- 状态 1 才是正在直播，状态 2 是轮播。持续状态 1 但来源开播时间改变，视为新场次；从 1 变成 0／2 发下播事件。事件包含实际采样时间、标题、房号、UID 和链接，时间换算成本群时区。
- 新场次先向每个群发一张开播卡片（主播头像、封面、标题、分区），再发场景事件，事件里写明卡片的实际发送状态。卡片画不出来时改发文字。下播只有场景事件。
- `at_all` 默认关闭。打开后开播卡片前带 @全体成员：QQ 群需要机器人是管理员且当天还有次数，飞书群需要群设置允许，发送失败时去掉 @全体 再发一次；Telegram 没有全员提醒，只发卡片。
- 某个房间采样失败只结束它本次采样并保留原始错误，其他房间继续；下一周期重新观察。相同场次只发一次事件。
- 安静时段由宿主场景事件规则处理。

低频工具：

- `bilibili_monitor(request={"action": "status", "uid": ...})`：重新读取本群订阅对象的当前状态，请求失败就报原始错误。
- `bilibili_monitor(request={"action": "subscriptions", "uid": ...})`：本群真实订阅、最近一次成功采样和最近一次失败。`last_sample` 是上次成功样本，当前状态用 status 重读。

订阅由运营者在面板的 `rooms` 和场景启用名单中管理。

## 关注推送

`follows` 每项填写 UP 主 UID、要推送的群，以及动态、视频、评论三个开关（评论默认关）。有关注项时必须填写 `sessdata`：空间动态和评论接口未登录时会被风控拒绝。读取走 bilibili-api-python SDK（插件清单声明的唯一额外依赖），使用宿主已有的 httpx。

- **动态和视频**：每个 UP 主每 `push_poll_seconds`（默认 300）秒读一次空间动态，多个 UP 主之间错开 20 秒。每个群各自记录推送进度，保存在插件 KV 里，重启后接着上次进度。新关注或停机很久后第一次读取，只推最近 5 分钟内发布的内容。转发动态把原动态画在灰色块里，直播预约画成附加块。
- **评论**：只抓 UP 主本人在自己最近 3 条动态和 3 个视频下的评论和回复，别人的评论不推。评论记录、扫描进度和每个群的投递状态保存在插件数据目录的 `comments.sqlite3`。新资源第一次扫描只记录已有评论；之后的新评论发送失败会按退避时间重试，超过 24 小时的不再发。所有评论请求共用 `comment_request_seconds` 的最短间隔。
- 卡片发送失败（宿主返回 failed）时不推进进度，下次轮询重发；返回 unconfirmed 等其他状态视为已发，避免重复刷屏。同一条内容推到多个群只画一次卡片。
- 卡片字体用随插件分发的更纱黑体（Sarasa Mono SC），缺字的符号回退到系统里的 Arial Unicode、DejaVu Sans 或 Noto 字体。

`bilibili_monitor(request={"action": "follows"})`：本群的关注项、每个 UP 主最近一次轮询时间和错误、评论待投递数量。

## 视频内容

公共请求不带 SESSDATA。账号工具只接受根配置 `owners` 里的真实请求人，每次账号调用前查询 nav 核对真实 B 站 UID。凭据由运营者在面板填写和更新。

- 公共视频／分P 不需要账号；搜索需要真实 `buvid3`。
- 登录态读取需要开启 `account_read_enabled` 并填写 `account_uid`、`sessdata`。

工具：

- `bilibili_video`：request.action=info 读元数据及分P，comments 匿名读评论。
- `search_bilibili`：视频搜索，来源页码与 next_page 原样续页。
- `bilibili_monitor`：status 新读取当前直播状态，subscriptions/follows 读取本群配置与旧样本。
- `bilibili_account_read`：request.action 为 comments、subtitles、dynamics；需要真实 source_message_id 和账号读取开关。字幕先列实际轨道再取正文。

共四项能力。request 按 action 校验，只接受当前操作的字段；source_message_id 放在 request 外由宿主解析。授权按 source_message_id 对应消息的发送者判断。


## 从 1.1.x 更新

配置中删除 `bili_jct`、`daily_like_limit`、`daily_favorite_limit`、`allowed_collection_ids` 和 `quota_timezone`。角色工具名单移除 `bilibili_account_write`，保留 `bilibili_video`、`search_bilibili`、`bilibili_account_read`、`bilibili_monitor` 以及 `tool_search`。旧数据文件 `write-counts.json` 可删除。

## 开发

在与 LenBot 同级的目录里，用宿主的开发环境运行测试：

```sh
uv run --project ../LenBot --no-sync pytest -q
```

测试使用本地 HTTP 服务模拟源站，普通用例用 `tests/fake_sdk.py` 替换 SDK；`test_sdk_protocol.py` 使用清单固定的真实 SDK 验证 HTTP 协议。运行前安装 `plugin.toml` 的 dependencies：`uv pip install --python ../LenBot/.venv/bin/python bilibili-api-python==17.4.1`。

许可证：GNU AGPL v3 或更新版本，见 [LICENSE](LICENSE)；协议来源见 [SOURCE.md](SOURCE.md)。

## 工具接口

工具采用接口 1 的显式简介、Field 参数说明与 `prompts/tools.md` 共享指南，返回原生 JSON 或文本。用 `PluginTest.preview_tools()` 查看模型说明、参数与可用性；测试里模型服务默认关闭。兼容和更新事项见 [CHANGELOG](CHANGELOG.md)。

CI 调用 LenBot 的可复用工作流，跟随宿主 master 测试。catalog-entry.json 记录目录条目的安装来源。

本机生成 ZIP（LenBot 仓库与本仓库放在同一目录下）：`uv run --no-project --python 3.13 python ../LenBot/scripts/package_plugin.py . /tmp/plugin.zip`。打包取 Git 已跟踪的运行源码和资源，新增文件需先加入 Git。

## 宿主能力

清单声明 `send`、`events`。这些权限约束宿主提供的能力，插件自行执行的 Python 与网络访问不受其约束。插件运行在宿主进程中，当前功能使用工具或后台协程，`isolation = "inline"`。
