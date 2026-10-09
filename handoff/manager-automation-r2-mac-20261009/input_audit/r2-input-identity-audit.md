# R2 输入与自动执行身份核对

审计时间：2026-10-09 09:15 CST（+0800）。只读检查；未操作服务、任务、API 写入或 UI，也未输出原始行情行。

## US 四槽原任务

- LaunchAgent `com.lexi.v4.us-market-digest` 配置存在，已出现在 `launchctl list`；当前 PID 为 `-`，表示检查时没有正在运行的 job 进程。`RunAtLoad=false`，本地四槽为 04:15、05:15、21:00、22:00。
- argv 使用原 executor：`python -B -m ops.run_us_market_slot`；Python、app、data、ledger roots 与 runner SHA 均见 JSON。runner 物理 SHA 为 `16f7895072a66b8a7e6ed0c792f74069101426cfa1194df3bd89e63d95f4d948`，与指定原版一致。
- 10/8 与 10/9 的 04:15 dispatch 均为 `LIVE / SUCCEEDED / dry_run=false`。它们分别关联 US session 10/7、10/8 的 `POST_CLOSE` 原时采集；source receipt 与 payload 的 SHA 均匹配，状态为 READY。报告只保留 ID、状态、日期、摘要和 SHA，不含行情行。
- 当前 API launchd 进程 `com.lexi.v35.api-only` 正在运行（PID 34989）。API `V35_DATA_ROOT` 与任务 `--data-root` 都是 `.../state/data`；源码将 reader 绑定到 `ResearchPeripheralUsMarketReader(store.root)`。R1 daily mapping hook 在当前 API release 源码中；本次未核某次 plan 的实际调用，不把 hook 说成缺失。

## 公告 06:30 heartbeat

- 限定检查了 `~/.codex/automations` 下 6 个 `automation.toml`。没有找到公告 06:30 的启用任务定义。近似项 `20-30` 与 `v4` 都是 `PAUSED`，时间分别是 16:20/21:50 和 10:00/17:00；未发现目标任务时区。
- 10/8 有一组绑定 target 10/8、publication 10/7 的 Reader/Reviewer 输出，evidence run ID `3f9d37a643060b57992167f3df05d987`。owner receipt 记录 parent task ID `01a11654-a832-70c1-b6ba-036c79e146e8`。Reader 声明 613 条来源绑定记录；不同身份的 Reviewer 声明 PASS，review 时间 08:09 CST，决定数 613。handoff manifest、analysis product 与 owner import receipt 都存在且状态 VERIFIED；owner `available_at` 为 08:55:47 CST。
- capture receipt 状态为 `PARTIAL_BODY_MATERIAL_CAPTURE_WITH_TERMINAL_GAPS`。handoff 是 `OUTPUT_BOUND`，外部审查为 `DECLARED`，不构成平台身份认证；owner import 成功不能单独证明由 06:30 自然调度触发。
- 截至 10/9 09:15 CST，配置的 research state root 中没有 target 10/9、publication 10/8 的公告 evidence run 或 owner product。自然 06:30 执行无法确认。

本机 runbook 定义了 Reader/Reviewer JSON 输入输出约束、不同身份检查、原始字节 hash 绑定、capture resume、幂等注册及 owner import/readback；本地 CLI 消费外部输出，不负责发起 Reader/Reviewer 调用。原 recurring task 的配置 ID、启用状态、时区和外部 Reader/Reviewer 重试归属仍需原自动化 owner 只读回读。

## boundary_status

`US_ORIGINAL_TASK_AND_10_08_10_09_SOURCE_RECEIPTS_CONFIRMED; ANNOUNCEMENT_10_08_OUTPUTS_BOUND_AND_IMPORTED_BUT_RECURRING_0630_CONFIG_AND_10_09_RUN_CANNOT_CONFIRM`

## recommended_next_step

由原自动化 owner 只读回读与 parent task ID `01a11654-a832-70c1-b6ba-036c79e146e8` 对应的 recurring heartbeat 定义（task ID、enabled、timezone、06:30），并取回 10/9 的 capture/Reader/Reviewer/handoff/import receipts。不要新建替代任务；保留 10/8 partial capture 与 `DECLARED` 身份边界。

## evidence_paths

机器可读报告的 `evidence_paths` 列出配置、源码、receipt 与原 runbook。原始行情 payload 仅通过路径和 SHA 证明存在，没有读取或复制行情行。


## automation-3 历史指针补充（2026-10-09）

parent chat `01a11654-a832-70c1-b6ba-036c79e146e8` 的最新完成记录曾读取历史路径 `/Users/lexi/.codex/automations/automation-3/automation.toml` 并查看同 ID；当时 commentary 称找到原 06:30 定义。这是历史指针，不代表当前配置存在。

本次对该精确路径核对为 `exists=false`。同 ID 的当前 view 只返回 “Rendered automation card in the app”，未提供定义或状态，因此卡片渲染不作为配置存在、启用状态或时区证据。当前状态仍为 `CANNOT_CONFIRM`。原六份 automation.toml 检查结果保留不变。
