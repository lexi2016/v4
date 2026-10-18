# 周五归档与日常选股链路交付

工程链路已修复，并完成真实保存结果、API 和经理研究工作台的独立核对。**完整选股验收仍为 NOT_PASS / PARTIAL，目标尚未全部完成**。0 入选、0 条件观察、19 只港股待评估，不能解释为完整评估后的零候选。

本次消费周五 **US20261016** 的原有 48 条真实行情归档，目标港股日为 **20261020**。原始归档的 `CONTROLLED_LATE_POST_CLOSE`、捕获时间与 SHA 保持；没有补采或改写旧快照。

| 实际交付面 | 状态与证据 |
| --- | --- |
| 手动历史重跑 | `fbf5e99c50324c549a5c83792d875b3b`，已保存并经 API/UI 独立核对 |
| 新调度器自动消费同一归档 | `466dae7ee920499b9b92dc86fd791692`，`SCHEDULED / NEXT_DAY / PARTIAL`；自动追赶历史归档 |
| 真实结果 | 48 来源均已读取、48 来源未完成资格评估；60 候选研究记录、36 关系记录、19 只港股；0 入选、0 观察、19 待评估 |
| 目录 | 1003 关系 / 667 股票完整消费，保留为目录观察，与候选合并及计数分开 |
| API / 经理台 | 同一最新 run_id、目标日、来源日、计数和不确定原因；研究输入截止与结果生成时间分开 |
| 独立验收 | `SCHEDULER_ACTUAL_RUN_INDEPENDENT_ACCEPTANCE.json`：运行链路及显示有界 PASS；业务 NOT_PASS；本批实现无 P0/P1/P2 |
| 最终 canonical 合并 | `CANONICAL_BASELINE_PRESERVATION_INDEPENDENT_REVIEW.json`：27 Python、2 UI、聚焦 Vue 类型检查 PASS，原有 12 个远端测试保留 |
| 自然时段 | `NATURAL_VERIFIED=false`；上述两次均不能替代自然收盘时段验收 |

本批修复了固定历史材料与日常运行模式的合同不一致、目录影响候选合并、无来源生效日期仍可通过的行业分支、凭月份推定港股通有效区间，以及界面读取错误截止字段/缺失可读原因的问题。日常因子路径要求真正的日期配对审核材料，旧 20261013 材料没有重贴日期。API 和 scheduler 分别按各自既有版本做增量集成；scheduler 的失效 relation_root 已改到同一已存在来源。既有并行 digest 保留。

运行身份分别为：API `us-daily-selection-chain-20261018-r2`，scheduler `us-daily-selection-scheduler-20261018-r1`。实际 PID、源码根、配置及 manifest SHA 见 `ROOT_FINAL_RUNTIME_IDS.json` 与独立运行回执。Canonical、API、scheduler 保留各自来源记录，不能把同名文件当成字节相同。原有行业纯函数/缓存接口与 UI 漏斗的 canonical 恢复通过独立测试；本批没有启动该采集器、发布行业数据或宣称这部分已有新的自然采集结果。

尚缺的真实证据为：

1. 覆盖目标日的港股通有效区间和资格证明。旧 Futu 观测不能改称 HKEX 官方有效成分。
2. 目标日、日常模式适用且 SHA 配对的因子候选/独立审核材料。
3. 覆盖目标日并有可确认 `source_asof`/生效语义的行业分类；抓取时间不能替代来源日期。
4. 关系审核、可得时间与 PIT/有效期间。24 个美股来源符号仍有关系缺口，不是 24 只港股或 24 条关系。

这些缺口保留 `CANNOT_CONFIRM`；运行合同 `VERIFIED` 只证明记录身份可校验。公开来源核验没有得到完整、有日期的行业底板，TCOM 与 09961 的发行人关系证明也不能替代港股通资格。没有制造非零结果或放松门禁。另一个扩展行情范围夹具的 47/49 READY 旧失败保留在既有回执中，未归入本批通过项，也未重跑或扩大为 producer 修复；本批实际固定 48 条归档读取通过。

GitHub 使用既有 `lexi2016/v4` 的独立分支 `codex/us-daily-selection-chain-20261018`，基线 `3b942a957b39c6e60690ba4c77e863038d304743`。`ROOT_GITHUB_SYNC_PLAN.json` 逐项记录必要源码/测试的远端基线及最终 SHA。仅同步必要源码、测试、既有 scheduler 的源码差分和精简结果；不上传原始行情、完整关系/行业数据、运行配置、plist、发布目录、dist、日志或截图。提交后的远端 commit 与文件读回证明写入本地 `ROOT_GITHUB_SYNC.json`，该回执不会把自己的上传作为证明。

既有 `issue45` 自然监控已更新到这些身份与结果，原定计划保留。首个待验来源 US20261019 / 目标 HK20261020；只在有新的失败、恢复、完成或需用户动作时通知。Issue45 和完整业务验收继续保持未闭环。

`RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
