# 日期下拉与 Top20 对照交付

日期控件已改为保存日期下拉，83项合法日期按顺序显示。实际切换20→19→20，并从固定run切日，确认旧phase/run清除；最后恢复今天15:03默认版本。已接受的“研究候选410只（不等于正式入选）”说明一并上线，候选表完整410行。

按港股通收盘榜冻结698份当日报价，实际严格入选0/20、盘前BENEFIT0/20；盘中232只宽条件观察重合7/20。事后修复的5只研究BENEFIT也为0/20，不能回填成盘前命中。高鑫零售第17、+6.880734%；昨日nested字段读取缺陷确实影响具名弱同行展示，修复后仍停留DATED_WEAK_PEER，今早WMT负方向，盘中仅宽行业观察。逐股缺口见RESEARCH_REPORT.md；不认定上涨因果，不按收盘涨幅补选或调门槛。

本批在r8上保留其他模块，单次激活r1并发布原冻结05d40结果，源时间/10:24处理时间不变，属于PROCESSING_RECOVERY。日研究698=5受益+303观察+379未映射+11未评估；正式入选0，strict仍暂停。其他阶段、默认15:03与旧历史保留。随后现役切为并行manual-backfill-button-20261020-r2；独立验收确认其manifest以r1为父，本目标11项源码/static与manager资产闭包全部同字节。当前PID44298，manifest4454d885713ceac187d0bccfee3e314a5bba4b60f12ff52bb5250510b74da49e；刷新后的DOM确认目标继续存在。原r1部署回执作为历史保留，不冒充当前运行身份。

独立研究、前端与交付元数据、候选/发布保护、实际API/UI均PASS，分别见INDEPENDENT_*。4项针对测试通过，10个构建产物可复现；完整typecheck保留原r8既有FAIL，诊断与基线完全相同。UI操作由主控完成，Reviewer独立核验截图/DOM/合同。当前IAB零宽不能再截图，已留实际r1交互截图及同字节current-r2加载DOM，没有虚称新截图。

本轮未采集历史行情、未重跑pipeline/严格选股、未改模型门槛、未发单。自然运行未验收，scheduler仍PENDING_PARENT_DRIFT_NOT_DEPLOYED；本结论不覆盖并行manual功能或策略有效性。

源码根/工作分支与真实r8 overlay分开记录在FRONTEND_DELTA：不将旧任务分支缺少的r8公告接口倒灌，不声称完整Git HEAD等于现役release。必要源码、两测试、可重现overlay patch及精简证据同步lexi2016/v4对应工作分支；raw行情、大snapshot/API响应、release/dist、plist、依赖和截图只留local_only。
