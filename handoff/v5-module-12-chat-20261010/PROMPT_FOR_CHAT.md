# 给Chat的M12任务

## 必须使用用户指定的 Superpowers 插件

用户明确指定已安装的 Superpowers（plugin://superpowers@openai-curated-remote）。本会话须实际选择并使用该插件的相关技能，不能只在正文写插件名称当作已调用。先按 using-superpowers 判断应使用的流程；修复按 systematic-debugging，必要设计/计划在本模块范围内完成，再按 test-driven-development、requesting-code-review 与 verification-before-completion交代码和可核验证据。复用既有总体计划，不再发起全仓设计或仅交第二份计划。

如果本会话无法访问该插件，说明实际入口/可见限制，不声称已启用；把这一问题回传嘻嘻。仍如实区分候选、静态检查、实际测试和Mac验收，禁止伪造执行。


请交付视频FUPAN具体最小代码候选，而不是视频重写方案。按SOURCE_MAP先核原owner和真实活动绑定，再给V4 donor→V5目标/输入/产物/API的逐节点表。video_fupan_daily等路径明确标拟新增。

## 必须保留原链

原close node列8个node ID：bilibili_fupan_nightly、FUPAN_V3_PUBLISH、FUPAN_8771_VERIFY、FUPAN_VIDEO_CHECK、FUPAN_VIDEO_DOWNLOAD_ASR、FUPAN_STOCKDICT、FUPAN_VIDEO_TABLE_OCR_ALIGN、FUPAN_VIDEO_GAP。session为内部步骤；不能因不存在同名node就漏掉。实际依赖顺序从原catalog/活动回执核，不能拿上述枚举顺序作拓扑顺序。

先核Review Core acquire_video→原consumer.load_v35_video_layer，分清只读桥接与真实生产。列全依赖和每节点run/输入SHA/输出SHA/receipt。活动producer或现场绑定未确认，只阻断真实生产、安装和启用；仍须根据固定Review Core producer/consumer交付最小静态代码候选及契约测试，并列精确缺件，不能只回缺件。禁止旧新两个producer同时抓取。

## 具体代码要求

1. 薄封装原producer/原规则，明确target date、视频BV/作者/上传/内容日期、允许的晚到身份和时间。无精确同日视频不借旧BV；NO_NEW_VIDEO、UP_LOOKUP_BLOCKED、NOT_LOCKED、ASR_REVIEW_REQUIRED与失败分列。
2. 长任务独立worker，不阻塞普通API/复盘；GET/页面刷新只查已提交节点，不触发发现、下载、ASR、OCR、发布。
3. 复用真实已成功媒体和ASR的SHA缓存。失败ASR sentinel不当可复用证据；修失败节点创建新不可变run，前媒体/转写及前成功receipt不覆盖。补并发、崩溃、重复触发及输入变化身份，不删除成功来“清理”。
4. 保留原exact股票字典、别名不确定性、OCR/表格对齐、gap矩阵和spotcheck要求。视频增强与独立市场事实分离，不把转写观点注入独立事实值；ASR工具退出0不自动视为已人工核验。
5. 旧receipt仅文件存在的复用不足由V5外围做摘要/代码/配置/输入绑定，原算法变更须独立列出，不通过更改状态标签绕过原门。
6. 所有输出仅本模块私有根，不指向V4默认root/8873或旧8771命名代表的现役服务。精确V5 loopback地址由Mac/集成绑定；禁止打开旧服务写入口。
7. 复用既有已授权本机媒体工具，不安装新软件、不新增账户/令牌；访问限制如实阻断，不更换方法绕过拒绝。

## 共享接线与交付

INTEGRATION_REQUEST.md列只读节点状态、显式操作、日期目录和原收盘时间线/复盘FUPAN映射、M05/M09消费引用、调度binding请求；本Chat不写共享前端/gateway/scheduler。按真实业务触发验收，不强行新建每日任务。

交固定commit、精确补丁SHA256和文件before/after SHA、完整donor manifest、原/新增测试与实际命令退出码、Mac真实验收步骤、回滚、未解决项。标清source事实/已有报告/新实测；旧桥接SUCCESS或fixture通过不关闭M12。
