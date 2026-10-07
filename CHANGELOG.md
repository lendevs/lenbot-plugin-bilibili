# 1.1.0

需要 LenBot 0.2.0 起的插件接口 1（从 `len_bot.plugin` 导入）。插件名、配置和业务数据不变，无需数据迁移。

- 工具精简：旧的视频信息／分P／匿名评论工具合并为 `bilibili_video`，旧的直播状态／直播订阅／关注设置工具合并为 `bilibili_monitor`，账号读取合并为 `bilibili_account_read`，点赞和收藏合并为 `bilibili_account_write`，`search_bilibili` 保留。角色 `tools` 写的是明确名称列表时，要换成这五个名称并保留 `tool_search`；写 `all` 的不用改。
- 账号工具去掉 `requester` 参数，改由 `source_message_id` 找到实际请求人。公开评论保持匿名，登录态评论用 `get_account_video_comments`。账号读取和写操作没开启时，对应工具不出现在工具发现里。
- 模型工具参数改为按 `request.action` 区分的分支，不保留旧工具名。后台监测、发送回执、账号权限、真实 ID 和分页规则不变。
- 工具带显式简介和参数说明，相关用法写在按需加载的共享指南里，结果返回 JSON。
