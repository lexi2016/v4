# V4 本批发布与验收结果（2026-11-02）

## 结论

**API 日期投影修复已上线并通过验收；不代表统一调度全链已通过。**

- API：`v4-task-status-date-20261102-r9-api`。
- Main：保持 `v4-unified-release-20261102-r7-main`。
- Stage：保持 `v4-unified-release-20261102-r7-stage`。
- 发布源码：`ba6e73de294ca0d72b6ca20de886be3f449309f9`。
- r9 manifest SHA-256：`8ed8c8d8874abc573500bfa014f87f3c6efa645bd93c4991c7564d71c90d5912`。
- GitHub 同步目标：`lexi2016/v4`，工作分支 `codex/v4-unified-release-r6-20261102`。未合并默认分支，未创建 PR。

## 已完成

1. **日期合同修复。** 发布守卫、小时研究完成见证与任务状态投影均区分业务日期与目标日期。固定次日目标槽位按既有 `NEXT_TARGET_SLOTS` 和冻结交易日历求精确下一交易日；未使用任意未来日期或 `>=` 放行。日历证据未知时保留不匹配 / `CANNOT_CONFIRM`，不猜日期、不让任务状态接口崩溃。
2. **检索正文预算修复。** 正文按查询、换行和命中正文的实际拼接结果，用 pinned BGE-M3 分词器在进程内精确计数；超预算拒绝或裁掉末尾命中，计数器不可用时 fail-closed。不再以字符数、UTF-8 字节数或有 Unicode 分歧的 HF 端点代替 pinned 计数。
3. **实际清理旧代码。** 以下六个路径在现役 Main、Stage、API 三个应用树中均不存在；历史发布目录和收据未删除：
   - `ops/backfill_us_market_digest.py`
   - `ops/collect_preopen_lane.py`
   - `ops/collect_research_panel_adjustment_metadata.py`
   - `ops/run_v3_5_runtime_graph_collector.py`
   - `ops/verify_strict_us_selection_v1.py`
   - `tests/test_collect_preopen_lane.py`
4. **受控 API 单角色发布。** r9 从已核验的现役 r7 API 应用复制，只覆盖 `domains/task_status.py` 与 `tests/test_task_status_dates.py`。应用清单由 1339 项变为 1340 项。Main、Stage、手工采集的 Stage 绑定、面板和 workbench 外部资产不变。
5. **修复发布工具缺陷。** 日志写入失败不再阻断归属核验后的恢复；已确认归属但没有 PID 的失败实例可恢复；同一准备计划可回退不健康或缺失实例。外来 PID、配置和 CAS 冲突仍拒绝处理。r8 失败候选及其证据原样保留，未激活。

## 实际验收

- Writer 最终五文件测试：**105 passed，5 skipped**。五个跳过项需要显式候选/回放路径，不宣称已通过。
- 独立 Reviewer 增量测试：**85 passed，0 skipped**；另有 **11 个独立模拟恢复/归属场景**、**2 个实际候选路由检查**通过。不是把它们合并声称为 98 个 pytest 测试。
- r9 实际激活退出码为 0；实际事件为 `ACTIVATED_API_VERIFIED`。
- 实时 `/healthz`：`ok`。
- 实时执行文件身份：`MANIFEST_EXECUTION_FILES_VERIFIED`，release 与 manifest SHA 均匹配 r9。
- 实时 `/api/v4/tasks/status?date=20261102`：`RECEIPT_CHAIN_VERIFIED`。
- 原始收据：**43/43 日期有效且链有效**；状态为 22 `SUCCEEDED`、11 `NO_DUE_WORKLOADS`、10 `FAILED`。准备时已有收据的 SHA 均未改变，业务失败没有被改写为成功。
- 用 r7 实际应用字节在 bridge venv 启动真实 stdio MCP，抽测此前失败的 C09/C10/C12：声明计数与 pinned 实测分别为 **7/7、8/8、9/9**。本次不是全库重新认证，也不扩张原三篇文档的语义验收范围；r9 保留相同检索模块字节。
- 20 个非 API plist 定义受保护，包括现存 legacy symlink 的链接身份和目标字节；面板资产清单 491 项未改变。
- 研究安全：`RESEARCH_ONLY=true`；`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 明确保留的缺口

1. **自然调度仍有真实阻塞。** 21:44 只读复现发现：主调度器选择已经在 16:59 截止的 `1640` 槽位，入队又拒绝该过期节点，后续分钟重复选择它；当时 `2140` 尚无收据。Main 本批未改动，该缺陷未修复。22:00 `hourly_research` 已由 r7 Main 自然运行成功，但只证明这一支，不能认定整条链正常。
2. **面板检索 HTTP 路由尚未配置。** 实时返回 `EVIDENCE_GAP / REPORT_INDEX_NOT_CONFIGURED`。检索代码和真实 MCP 样本通过，不等于面板已经接通向量检索。未修改共享环境或安装依赖来隐瞒此缺口。
3. **UI 视觉验收未运行。** 当前宿主 Browser preview 不可附加现役 URL。API 与受保护面板资产已核对，但没有截图或视觉 PASS。
4. **未做真实故障回滚演练。** 本次真实正向切换成功；失败恢复由模拟服务场景验证，不冒充真实故障演练。bootstrap 传输超时、尚不能确认进程归属时，会停止自动恢复，不接管或杀死未知 PID；后续需使用同一准备计划重新核验并明确执行回退。
5. 微信保持用户手工导入，不作为本批阻断项；历史自动同步失败没有被重写。

## 关键本地证据

证据根：`agents调试/v4_unified_recovery_20261102_terra/task-status-closeout/`。

- `writer-repair.json`：返修前后回归与四文件 SHA。
- `reviewer-r9.json`：独立 PASS、三项缺陷关闭和边界。
- `build-r9/plan.json`、`prepared-r9/preparation.json`：本次构建及准备绑定。
- `prepared-r9/event-*.json`、`activate-r9.log`：实际激活事件和运行验收。
- `controller-acceptance-r9.json`：主控实时身份、收据保留与六路径清理核验。
- `mcp-smoke-r7.json`：三个历史失败样本的真实 MCP 抽测。
- `natural-slot-blocker.json`：过期 16:40 槽位阻塞的只读复现。
- `remote-readback-r9.json`：源码提交和关键文件的远端回读核验。

以上证据层分别成立：**本批 API 修复完成，不将其升级为 UI、向量检索面板接入或自然调度全链完成。**
