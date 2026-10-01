# BI04 与日历：核实结论，不含运行补丁

## BI04 静态不一致已确认

本包 source 的 `v4/manager_research/workspace.py` SHA256 `35c9292d3b422c9d5a744590cc472de5bfa2da8a62d12c6382ca0d1a9b3a6168`：
- validate_attempt 第96–100行接受 SCHEDULED_MORNING，并约束原 workspace plan owner。
- _read_plan 第512行接受它。
- refresh_workspace_plan 第563–596行接受该执行类别，保留 morning 窗口/完整 reader/保留正式 preopen 计划分支；第645–648行以 execution_kind 原值写产品。

同包 `workspace_history.py` SHA256 `d2ad875f639e7018e06498fbafb8c379808576425dedf6cfbed590155309bdca`：
- _read_candidate 第58–60行仅允许 MANUAL_REFRESH / SCHEDULED_PREOPEN。
- select_plan 第92–99行先读 latest；真实 morning 保存产品会被这个历史 reader 的类型白名单拒绝。

SOURCE_INDEX 中这两文件各自 canonical_matches_configured=true。可确认 writer/current-reader/history-reader **静态合同不一致**；这不是 PID 已加载字节或自然触发失败的证明。进程载入、自然写入/读回：CANNOT_CONFIRM。

建议下一最小修复只在 `_read_candidate` 的执行类型白名单增加既有 SCHEDULED_MORNING；不得删除 owner/hash/date/context/cutoff 校验，不增加调度。用真实临时 Store 保存 morning 产品再经 select_plan/read_history 读回，另测错误 owner、后截止/损坏产物仍拒绝。**本批没有应用此建议，也未重跑历史测试。**自然 writer `v4/manager_research/workspace_plan_autorun.py` 不在本包 SOURCE_INDEX；若要核其触发入口，只需它的最终字节/绑定，不要全项目 ZIP。

## 非交易日 409 不在本批改动

本包 workspace_announcements 的官方 refresh 第266行、return 第296行、mirror refresh 第471行及 return 第526行、GET/read 第553/576行均调用 plan_context；project 第664–666行还约束消费者/产品 target date。workspace_plan.plan_context 自第18行开始核 hk_securities calendar。并非只改 POST 入口就能将公告采集改为自然日。

announcement_autorun.py 本次 SOURCE_INDEX 未包含；它的自动交易日政策不能从引用推断或顺手修改。材料日期/计划交易日/consumer cutoff 是否拆分属于后续业务合同裁定，本轮没有改全局日历、日期或历史数据。以上定位不阻挡 BI01/BI02。
