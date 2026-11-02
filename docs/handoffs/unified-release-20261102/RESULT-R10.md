# V4 r10 调度追补修复与发布结果（2026-11-03 凌晨）

## 结论

**Main 调度器的“过期槽位饥饿”已修复并完成三角色受控切换；自然全链验收尚未进行。**

- Main：`v4-unified-scheduler-20261102-r10-main`（PID 73620）。
- Stage：`v4-unified-scheduler-20261102-r10-stage`（按 tick 启动，当前空闲）。
- API：`v4-unified-scheduler-20261102-r10-api`（PID 73672）。
- 修复源码：`34bbc0cd83839ac6a6a52378077182e9e5b3d4c8`，工作分支 `codex/v4-unified-release-r6-20261102`。
- 候选：Main `d1b0e55e…`、Stage `d8213430…`、API `8de9e394…`（应用差异分别只有调度解析器、Stage 配置、API 手工采集配置一处）。
- 发布计划：`publication-plan-r10d/publication-plan.json`，SHA-256 `21d9cd43777c97f220e194c3e5456d7fd7afe697d1c6e54536f2e7ae20568d9b`。
- 激活：`activation-r10/preparation.json`，SHA-256 `36bf467879ccaee935f665aaedbb65a0260f82138c79e35602b734de8ea6935a`。

## 根因与修复

旧解析器在追补扫描中不考虑原始截止时间，会持续返回已过期的 `1640`；入队端按 `moment > cutoff` 拒绝该槽位，下一分钟又再次选中，形成饥饿。修复工件由**现役 r7 Main 真实字节**派生（`e6e18cef…` → `ff1130e6…`），仅 3 处、9 行：本地 `_past_cutoff` 判定与两个追补扫描中的跳过；当前小时、exact、固定槽和整点回退分支以及全部截止时间定义未动。现役应用回归在修补前后均为 24 failed / 109 passed，失败集合逐项一致，修补未新增失败。

同一批次还修复了发布链在“上线后再发布”时的三处陈旧归属假设与两项保护缺口：

1. Stage 的 `research_transition_owner_binding` 按冻结证据（f10-daily / `3f9a184c…` / 20261102）原样保留，不再被改写为当前 Main。
2. `transition_owner_proof` 与省略主证据扫描都以冻结绑定为归属来源，当前 Main 的收据不被混入。
3. 发布目录中的后续归属发布必须由真实派发收据内嵌的发布字典精确匹配，且归属不得是冻结旧主；旧主发布缺失收据时拒绝。
4. 计划与激活对全部 18 个非目标 LaunchAgent（17 文件 + 1 现存 symlink，目标哈希 `7d4bfc92…`）做只读身份/字节保护，切换前后复核。
5. 打包器支持以显式三角色快照叠加在现役谱系上，并为已应用的调度修复、测试覆盖、路由注册提供幂等处理。

## 实际验收

- 独立复核：五项要求测试 **97 passed、0 skipped**；两项闸门缺陷关闭；候选三路径差异、冻结证据 42 收据/14 发布、额外发布 2200/2300 的归属校验、plist 保护与计划绑定均通过。
- 激活返回 0，事件为三次 `TARGET_VERIFIED` + `ACTIVATED_OPERATIONAL_VERIFIED`。
- 实时 `/healthz` 为 `ok`；`/readyz` 三个交易安全标志均为 `false`；API 执行文件身份为 `MANIFEST_EXECUTION_FILES_VERIFIED`，且 release/manifest 与 r10 一致。
- Stage 绑定：`research_owner_binding → r10-main`，冻结过渡仍为 `f10-daily/20261102`，3 个历史绑定未变；API 手工采集配置的 `stage_owner_root → r10-stage`。
- 切换后自然调度日志为 `00:12/0013/0014/0015` 等当前分钟槽位，`active_children=0`，不再出现 `1640`。
- `20261102` 任务状态：**45 条收据，链有效，45/45 日期有效**；原始业务状态保留为 23 `SUCCEEDED`、11 `NO_DUE_WORKLOADS`、11 `FAILED`。
- `20261103`：尚无收据（`NO_SAME_DATE_RECEIPT`），当日自然调度未到点。

## 明确保留

1. **21:40 追补未在 20261102 执行**：复核闸门在 23:59 截止前无法完成，切换发生在 00:12，`2140` 当日无收据。不得补写或宣称昨日完成。
2. 旧 Main 在 23:59 截止前对 `1500` 做了迟到重试，至 00:02 以 `fupan_close_materials` 失败结束；该失败按原始状态保留（第 11 条 FAILED）。
3. **自然全链验收 `NATURAL_VERIFIED=NOT_RUN`**：需在次日 04:15 起的真实自然槽位观察修复后的追补与整点链；本报告只证明机制与切换后即时日志行为。
4. 面板检索 HTTP 路由仍未配置（实时返回 `REPORT_INDEX_NOT_CONFIGURED`）；本批未修改共享环境或安装依赖。
5. UI 视觉验收未运行（当前宿主无法附加现役 URL 的浏览器预览）。
6. 失败恢复与回退由模拟场景和此前 r9 工具验证覆盖；本次是真实正向切换，未做真实故障回滚演练。回退使用同一计划与 preparation SHA。

## 关键证据

- `scheduler-r10-writer/`：补丁工件、前后差异、复现脚本、活体应用回归日志、writer 交接。
- `publication-plan-r10d/`、`activation-r10/`：计划、准备回执、原/新 plist、激活事件。
- `task-status-closeout/reviewer-r10b.json`：最终独立 PASS 与两项关闭证据。
- `task-status-closeout/natural-slot-blocker.json`：旧解析器饥饿的只读复现。
- `task-status-closeout/mcp-smoke-r7.json`、`controller-acceptance-r9.json`：本批之前已验收的检索与 API 日期修复证据。

**证据分层：本批源码修复、候选构建、独立复核、三角色部署与即时行为成立；自然全链、UI 与面板检索接入仍未完成。**