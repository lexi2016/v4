# 20261014 六阶段自然采集准备与监控

## 当前状态

2026-10-13 已直接修复并部署既有 stage-center 服务。IMPLEMENTED / DEPLOYED；40 项源码回归通过，实际运行候选 39 项通过。独立 Reviewer NOT_RUN（用户明确要求主助手直接处理）。NATURAL_SLOT_UNVERIFIED：明天尚未运行，不能预先宣称成功。

唯一源码 `/Users/lexi/Desktop/学习/v4_app`。本轮不改 8873 API、前端或 8910，不改历史阶段记录、不新增采集器或服务。

## 根因及修复

1. 实际 R13 阶段运行包仍只有阶段结束时调度及 Stage8 预采集，缺六阶段截止前的预采集；canonical 已有通用预采集源码。复用并部署现有 `HK_SNAPSHOT_SCHEDULE`、`prepare_due_snapshot`、快照保存/读取及对应 collector 参数传递。
2. 旧链路先等分钟线结束，再拉实时快照，可能越过截止。现在自然阶段读取已落盘的同日、同阶段、同池快照。当前预采集优先于旧阶段重试，避免窄窗口被旧任务占用。
3. `fetch_futu_snapshot` 增加默认关闭的 `include_order_book`，仅六阶段预采集启用；复用同一 OpenD 连接和精确 D-1 代码集，获取十档盘口，保存 Bid/Ask、服务端时间、请求及接收时间，错误逐股票保留。原竞价及 Stage8 行为保持。
4. 原分钟桥只返回汇总行，完整原始响应没有归档。现在在原 raw 根下原子保存原始 K_1M JSON，包含准确日期、阶段、代码集、NONE 复权口径与真实采集时间，来源证据带路径及 SHA。缺失或无时区采集时间不能通过。
5. 快照保留完整盘口字段；自然阶段只读快照，投影一档买卖价格/数量，缺失或超时盘口显示 `HK_STAGE_ORDERBOOK_INCOMPLETE`，不重新拉截止后的盘口冒充当时证据。

## 时刻

| 阶段 | 自然预采集 | 原阶段执行 |
|---|---|---|
| 09:30–09:35 | 09:34 | 09:35:05 |
| 09:35–09:40 | 09:39 | 09:40:05 |
| 09:40–09:45 | 09:44 | 09:45:05 |
| 09:45–10:30 | 10:29 | 10:30 |
| 13:00–13:15 | 13:14 | 13:15 |
| 14:45–15:00 | 14:59 | 15:00 |

沿用冻结的分钟窗口聚合口径。分钟 K 线在窗口结束后获取并保存；盘口必须在截止前获取。两者采集时间分别保留，不混同为一个时间。收盘后的可用性探测不写入正式阶段。

## 实测与剩余验收

- 真实 OpenD 单股票盘口成功，约 0.77 秒；完整 100 只候选盘口 100/100 成功，约 1.86 秒，无盘口错误。这是盘后连通/能力测试，不是自然时点验证。
- 实际候选运行包的分钟采集：100/100，READ_OK，约 53.60 秒；原始 JSON、SHA、采集时间成功保存到隔离证据目录。14:45–15:00 冻结窗口为 14 根，未修改算法窗口。
- 20261014 精确 D-1 池 READY，100 只；SHA `1627efe05e26228fbd036c2a0507000d52ebe77589863dea57e3cf4fa3986aff`。
- `tests/test_hk_natural_capture_20261014.py`、晨间恢复、下午路由、Stage8 回归：源码 40 passed。运行候选 39 passed、1 deselected；被排除的旧 mock 测试 `test_runner_precapture_is_before_due_decision_and_exact_window` 在未修改 R13 基线同样因 mock 缺真实池状态而失败，记录基线失败，不升级为通过。新测试覆盖六个预采集时间、重试顺序、原始分钟持久化、盘口时间边界及快照保留。
- 初次测试全部用例执行后遇到系统旧 pytest 临时目录清理权限错误；使用本轮专属 basetemp 后成功完成。
- 运行包 `--check` 为 CHECK_OK，16 个原/新增定时节点均在表内。launchd 读回已绑定新包，RunAtLoad=false，未触发盘后伪阶段。
- 8873 真实重新加载成功，日期 20261013、STAGE_1545_1555、港股 10 行和原 API 身份保持。明天六阶段 API/UI 仍待自然产物验收。

## 部署身份与兼容

现役 label `com.lexi.stage-center.scheduler`，app 根：
`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-natural-capture-20261014/app`。

manifest SHA `77057c3424f022b4552ca4803183fab0f42cbead29e5dedb032fd6b1cc325248`；launchagent SHA `e44cdce9e80fc906670aa550467ac402ada3b92228ad333e4ec93eff3ff0fe9f`。

以真实 R13 包克隆，覆盖既有预采集所需文件。`node_entry.py` 只替换预采集分支和排序，保留 R13 的其他修复；runner receipt 的既有恢复合并逻辑不动。补齐 Stage8 rtdata 对新快照读取接口的池 SHA 参数，相关回归通过。

本机证据目录：`/Users/lexi/Desktop/学习/agents调试/V4_HK_NATURAL_CAPTURE_20261014`。`SCOPE.json`、`source_sha.json`、`candidate.json`、`deployment.json`、`launchctl-after.txt`、`runtime-check.json`、`book_full_canary.json`、`minute_canary.json`、`nextday_pool.json`、`ui-smoke.txt` 与测试日志分别记录范围、源码前后 SHA、运行文件差异、真实能力和验收边界。原始行情不上传 GitHub。

测试解释器：`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`。运行 `-B -m pytest -q --basetemp=<本轮目录> tests/test_hk_natural_capture_20261014.py tests/test_hk_futu_morning_recovery.py tests/test_hk_futu_afternoon_routing.py tests/test_hk_stage8_v4_recovery.py`；运行包通过隔离测试副本及 `PYTHONPATH`/`V4_TEST_STAGE_APP_ROOT` 指向实际候选。API/UI 不等于自然通过。

## 明天接续

已有 heartbeat `v4` 已更新为“10月14日六阶段自然采集与8873验收”，当天早盘起检查已到期阶段，检查新结果或新故障才通知；最迟 15:47 收束并暂停。原 `automation-3` 的 16:16 收盘复盘验收继续保留。

逐阶段检查：真实 launchd 时间 → `.hk_active_snapshots_v2/20261014/<stage>/snapshot.json` 的完整盘口/请求和接收时间/池 SHA → `.futu_minute_captures/20261014/<stage>/*.json` 原始分钟与采集时间 → immutable raw/selection 与自然回执 → 8873 同日期同阶段 API和页面。采集根均在 `/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/raw`。补跑与自然成功分开记录，真实缺口继续保留。

Git 基线 `2acd25e1d24d1d095c70ea3254dbab718c879589`；本轮私有同步分支 `codex/hk-natural-capture-20261014`，远端 commit/逐文件读回见本机 `github_sync.json`。仅同步必要源码、测试和本文；缺失于仓库根的现有预采集依赖一并补入，不上传缓存/原始行情/运行包。

RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。
