查询工具只返回数据，不发消息：bilibili_video 查公开视频，search_bilibili 搜视频，bilibili_monitor 查本群订阅。

- 视频用 bvid 或 aid 二选一；评论翻页用上次结果的 next_page。
- bilibili_account_read 用配置的账号读取需要登录的内容，只接受主人发起的请求。读字幕先不填 language 列出轨道，再按轨道的 lan 取正文；空间动态翻页把 offset 原样传回。
