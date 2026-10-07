bilibili_video：info 返回视频元数据及分P/cid，comments 匿名读评论；search_bilibili 搜索。BV/aid 二选一，页码用 next_page 续页。元数据、评论和字幕不表示已观看画面。
bilibili_monitor：status 新读取直播状态，subscriptions/follows 查本群配置与旧样本；旧样本和日程不证明当前直播，不修改设置或发送。
bilibili_account_read/write 需要主人真实请求的 source_message_id。读取可选 comments/subtitles/dynamics/like_state/favorite_state；字幕先不填 language 列轨道，再按真实 lan 取正文，动态 offset 原样续页。写入用 like/favorite 和明确 desired_state，各自受配置额度限制。未知结果先查状态，不重发；点赞状态0不能证明未点赞。凭据不传给模型。
