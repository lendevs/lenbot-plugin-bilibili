# 1.3.0

- 新增视频与 UP 主搜索，自动获取访客设备 Cookie。
- 主人可通过 /B站登录 或 bilibili_login 扫码登录，二维码发到当前聊天，登录成功后保存账号并立即生效。
- 新增 bilibili_subscription，在聊天中增删本群开播、动态、视频和评论订阅。
- 声明 configure 权限，增加 qrcode 依赖；需要 LenBot 0.2.1。

# 1.2.0

- 移除点赞、收藏、相关状态查询和账号写入工具，保留账号评论、字幕、动态读取与直播、关注推送。
- 配置删除 `bili_jct`、`daily_like_limit`、`daily_favorite_limit`、`allowed_collection_ids`、`quota_timezone`；更新前从已保存配置移除这些字段。旧 `write-counts.json` 可删除。
- 角色工具名单移除 `bilibili_account_write`；现有四项读取和监测工具名称不变。
- 作者资料只查询昵称、头像和挂件，移除卡片未使用的总获赞、关注数、粉丝数请求与 bili_jct 配置。
- Telegram 开播通知在插件发送入口省略 @全体，兼容现有宿主的消息段处理。
- 评论抓取：群在面板里暂停时不再把该 UP 主的评论资源退役。之前暂停再恢复会重建资源，期间的评论可能漏推；现在与上游一致，只有从 `follows` 删掉 UID 才退役。
- 作者资料缓存过期时先用旧资料出卡片，后台刷新，与上游一致；挂件地址在刷新时保留。
- 工具说明重写，去掉实现细节，写清各 action 的内容和翻页方式；卡片标志换成 LenBot 新图标。
- Telegram 模拟测试使用接口 1 现有参数，兼容宿主 master 与多平台开发分支。

# 1.1.3

`at_all` 的配置说明和 README 写明各聊天平台的效果：QQ 群需要管理员和当天次数，飞书群需要群设置允许，Telegram 没有全员提醒，宿主省略这个提及后照常发出卡片。配置示例加入一个 Telegram 群。配置、数据格式和工具名称不变。

# 1.1.2

工具说明、配置说明和 README 改为直接陈述功能与数据来源；配置、数据格式和工具名称不变。

# 1.1.1

声明 send/events 宿主能力；缺少获赞数时保持未知，不再用播放量替代；补充真实 SDK 的本机 HTTP 协议验证。配置、数据格式和工具名称不变。

# 1.1.0

需要 LenBot 0.2.0 起的插件接口 1（从 `len_bot.plugin` 导入）。插件名、配置和业务数据不变，无需数据迁移。

- 工具精简：旧的视频信息／分P／匿名评论工具合并为 `bilibili_video`，旧的直播状态／直播订阅／关注设置工具合并为 `bilibili_monitor`，账号读取合并为 `bilibili_account_read`，点赞和收藏合并为 `bilibili_account_write`，`search_bilibili` 保留。角色 `tools` 写的是明确名称列表时，要换成这五个名称并保留 `tool_search`；写 `all` 的不用改。
- 账号工具去掉 `requester` 参数，改由 `source_message_id` 找到实际请求人。公开评论保持匿名，登录态评论用 `get_account_video_comments`。账号读取和写操作没开启时，对应工具不出现在工具发现里。
- 模型工具参数改为按 `request.action` 区分的分支，不保留旧工具名。后台监测、发送回执、账号权限、真实 ID 和分页规则不变。
- 工具带显式简介和参数说明，相关用法写在按需加载的共享指南里，结果返回 JSON。
