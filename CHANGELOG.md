# 1.1.0

适配 LenBot 首版 0.2.0 的插件接口 1：显式工具简介、参数说明、按需共享指南与 JSON 结果。使用新增接口的版本需要包含插件生态改造的最终 0.2.0 基线；早期同版本开发提交不支持。

账号工具删除 requester，改由 source_message_id 定位实际请求人。公开评论工具保持匿名；登录态评论使用 get_account_video_comments。账号与写操作未开启时不进入发现目录。

保留原插件名、配置和业务数据，无需数据迁移。与旧宿主共同回退时须使用原插件版本。当前为未发行开发版本；只提交源码，不创建版本标签或 Release。

## 工具精简（开发中，未发行）

旧视频信息／分P／匿名评论工具统一为 bilibili_video；旧直播状态／直播订阅／关注设置工具统一为 bilibili_monitor；账号读取统一为 bilibili_account_read，点赞和收藏统一为 bilibili_account_write，search_bilibili 保留。明确角色 tools 名单需更换为这五个名称并保留 tool_search；all 无需更改。

业务配置和数据不变；后台监测、发送回执、账号权限、真实 ID 与分页规则保持。模型工具签名变为 request.action 的类型分支，无旧工具别名。
