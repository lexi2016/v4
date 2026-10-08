# V4 经理选股工作台自动化问题交接（2026-10-08）

## 交接目标

请修复并验收 V4 经理工作台每天自动产出三路研究结果：公告选股、港股通选股、超跌选股。公告链路必须覆盖“材料发现 → 正文可读 → 判断回执有效 → owner 导入 → 工作台读取”；港股通和超跌各自保留资格/权威面板合同。验收必须来自真实消费链路和自然运行；只改状态文案、放宽筛选门槛或把缺失写成零都不算完成。

复现页：`http://127.0.0.1:8873/manager-selection/?date=20261007&announcement_date=20261007&plan_date=20261008`。选股日期是 `date`，公告日期是 `announcement_date` / `publication_date`，计划日期是 `plan_date`；三个日期必须分开绑定。下方 2026-10-08 API 摘要只证明主控已观测的状态，不是本 Writer 重新请求或自然运行的证明。

## 当前 8 项问题与优先级

| ID / 优先级 | 现象与证据 | 代码定位 | 修复目标与验收重点 |
|---|---|---|---|
| ISSUE-01 / P0 | 三路每日自动运行和自然结果没有可确认的端到端回执。API plist 配置指向 R3；scheduler plist 配置仍指向 `hk-research-calendar-all-r1-20261007-scheduler`；实际运行进程加载的模块版本、scheduler 调用对象均 `CANNOT_CONFIRM`。计划未物化，自然时段为 `PENDING_SLOT`，检查时尚未到时段，不是故障。 | `v4/manager_research/announcement_autorun.py`、`v4/manager_research/workspace_plan_autorun.py` | 映射真实 scheduler 调用、三路 owner、run 身份、幂等和有限重试。错过窗口要显式标补跑类型；自然交易日用 scheduler、每路产物/API/重载页面读回联合验收。`PENDING_SLOT` 既不是失败也不是通过。 |
| ISSUE-02 / P1 | 同一目标日公告 analysis 和 owner import 为 `VERIFIED`，workspace 仍为 `CANNOT_CONFIRM`，报 `ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID`。根因未确认。 | `v4/manager_research/workspace_announcements.py`、`apps/api/v35_api/manager_research_router.py`、`v4/manager_research/workspace.py` | 对齐 target/publication date、产品与 source SHA、judgment/handoff/owner receipt、evidence run 和 cutoff；工作台须读到同一已导入产品。保留无效回执的具体拒绝原因。 |
| ISSUE-03 / P1 | 港股通目标日资格 `CANNOT_CONFIRM`，固定 D-1 canonical Top100 阶段池的消费者映射也未确认。目标日资格、上一完整日 membership capture、D-1 Top100 阶段池是不同合同。 | `v4/manager_research/connect_selection.py`、`v4/manager_research/connect_capture_adapter.py` | 读取精确目标日 HK_UNIVERSE_V2 资格；另行追踪 D-1 canonical Top100 的 owner、日期、run、manifest 与消费者。美股关系不能授予资格或替代 D-1 阶段池。 |
| ISSUE-04 / P1 | `market_screen` 为 `CANNOT_CONFIRM`，缺 `PLAN_HK_02_EXACT_DATE_PANEL_MISSING`、`SCREEN_PANEL_AUTHORITY_UNVERIFIED`；预期读取哪个已完成交易日面板尚未确认，不能据此断言 producer 故障。 | `v4/manager_research/workspace_plan.py`、`v4/manager_research/workspace.py` | 复用准确日期 HK 0.2 权威面板、manifest、交易日历和证券主数据。先明确盘前使用哪个已完成交易日面板、盘后使用哪个面板及其到目标选股日的映射；不要求未收盘当日完整数据。按阶段核对缺口，不能未经判断就断言 producer 故障。 |
| ISSUE-05 / P1 | 两道超跌研究门已映射为“收盘价 ≤ 前 60 个完整 HK 交易日最高价的 80%”且“当前量 ≥ 前 5 个完整 HK 交易日均量的 1.5 倍”；代码仍标 `volume_unit_status=NOT_PROVEN`。 | `v4/manager_research/workspace_plan.py` | 补齐权威来源的成交量单位、倍率和跨来源一致性证据。明确盘前/盘后已完成面板日期及其到目标选股日的映射，再核实单位与倍率；不得把未收盘当日全量作为前提，未闭环前也不得把数量门判为通过/失败或放宽门槛。 |
| ISSUE-06 / P1 | 美股 source 为 `READY`，mapping `NOT_EVALUATED`、daily run `NOT_RUN`；依赖图和各路隔离行为未确认。 | `v4/manager_research/us_market_bridge.py`、`apps/web/src/manager-selection/businessStatus.ts` | 美股关系只阻断真实依赖它的渠道。无依赖渠道应独立执行；缺少关系保持未评估，不能当零关系、港股通资格或 D-1 阶段池。 |
| ISSUE-07 / P2 | 已有测试分别覆盖 analysis 日期/读取/导入与 workspace/router 行为；已检查的用例未证明同一产品贯穿 analysis/import/workspace 的三端 parity，不能据此断言其他测试中完全不存在覆盖。 | `tests/test_manager_announcement_analysis.py:140-189,379-417`、`tests/test_manager_announcement_api_and_integrity.py:15-45,84-125`，详见 `source_map.json` | 补同日期、同产品、同 SHA 的 analysis GET → import readback → workspace GET 一致性回归，并覆盖无效回执、日期不符及 cutoff 失败。 |
| ISSUE-08 / P2 | 用户复现页将选股日/公告日 `20261007` 与计划日 `20261008` 放在同一请求中，这是要逐项核对的产品日期合同，不能把它当成故障或擅自统一成同一天。没有 20261008 三路股票、理由、目标日期和运行时间的重载 UI 读回。 | `apps/web/src/manager-selection/businessStatus.ts`、`v4/manager_research/workspace.py` | 首屏按渠道显示股票、理由、日期与运行时间；技术诊断折叠显示。自然运行后重载页面，并按 API/回执交叉核对；状态文字变化不替代行为验收。 |

## 本轮已知的日期状态

主控于 2026-10-08 提供的 live readback 摘要：

- `GET /api/v4/manager/workspace?date=20261008`：`announcement_reviewed_analysis=CANNOT_CONFIRM`，gap 为 `ANNOUNCEMENT_ANALYSIS_NOT_CONSUMED:ANNOUNCEMENT_AGENT_JUDGMENT_RECEIPT_INVALID`。
- `GET /api/v4/manager/research/announcements/analysis?date=20261008&publication_date=2026-10-07`：analysis 与 owner import receipt 均 `VERIFIED`。两端状态不一致已复现，底层原因未查明。
- 港股市场筛选：`CANNOT_CONFIRM`，缺精确日期 panel / authority。港股通正式资格：`CANNOT_CONFIRM`，缺 `HK_UNIVERSE_V2` artifact 和目标日资格验证。
- 美股：source `READY`，mapping `NOT_EVALUATED`，daily run `NOT_RUN`。
- 计划：`NOT_MATERIALIZED`。自然时段：`PENDING_SLOT`，检查时未到执行时点。
- 用户截图摘要：HKEX `NOT_RUN` / no owner，美股 `NOT_EVALUATED`，计划 `NOT_MATERIALIZED`，Stage 回执未知；截图路径、capture SHA 和 Stage 回执细节 `CANNOT_CONFIRM`。
- 前轮主控报告的 Eastmoney 手动导入/回读记录包含 33 个股票代码、54 条观察；本轮未重新核数量，也不是本轮独立复核，更不能证明全经理工作台或自然运行已可用。回执引用：`/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_DAILY_CHAIN_20261008/candidate/analysis-readback-compat/review/compat_live_independent_review.json`，主控提供 SHA-256 `308f6fbb5bdc2cd060430d4967d9af72ef42aeb7dde2eb90c3e948bbfa3a71cb`，对应远端基线 commit `0382f753929365048d231a7252d9c328d40f8522`。Writer 当前 checkout 无法读取该路径，未读取原始数据或复核回执内容。

## 代码映射与版本边界

具体入口、canonical workflow、源文件行号/SHA、未映射项、运行身份和测试库存见 [source_map.json](source_map.json)；结构化现场摘要和 8 项验收合同见 [evidence.json](evidence.json)。

已确认的关键边界：

- `workspace.py` 聚合公告、市场筛选、资格过滤和关系投影；公告 consumer 在 `workspace_announcements.py` 校验 judgment、handoff、owner receipt 和 cutoff；API GET/import 在 `manager_research_router.py` 各自读回，不能把 API 单点通过当作 workspace 消费通过。`announcement_observation.py` 将 official HKEX 与 Eastmoney 镜像资料分列，镜像不可替代官方目录。
- `connect_selection.py` 读取目标日 HK_UNIVERSE_V2 资格。`connect_capture_adapter.py` 读取上一完整交易日 Connect membership capture；它不等于固定 D-1 canonical Top100 阶段池。该阶段池具体 consumer 仍 `CANNOT_CONFIRM`。
- 超跌复用权威 HK 0.2 面板与两道门。成交量单位未证明前，不得将数量门状态提升为已确认。
- `workspace_plan_autorun.py` 的盘前计划只在合法窗口调 owner，窗口关闭后返回 `EXPIRED_NO_BACKFILL`；UI 只有 run 与 attempt 身份匹配的 `SCHEDULED_PREOPEN` 产品才标为已冻结。
- 本地列出的 canonical source candidate 大多是未跟踪文件，API router 为修改文件；这些本地文件 SHA 不是远端 commit blob，也不能证明 R3 immutable release 正在运行同一源码。R3 app 与 plist 是主控核实的配置身份，不代表本轮进程实际加载版本；模块指纹为 `CANNOT_CONFIRM`。manifest SHA 来自前一轮核验，需重新验证。
- 主控提供的远端旧 handoff 已包含相关源码。本包只交接问题与映射，不重复打包源码，也不把仓库根目录当作当前运行目录。

## 交给下一对话的执行要求

先确认远端目标分支和旧 handoff，再逐项比对旧源码、当前 canonical source 和 R3 immutable release；核实 scheduler 的真实调用对象与 receipt。沿 `ISSUE-01` 至 `ISSUE-08` 修复并补必要回归，先单日/单路验证，再观察下一次真实自然运行。保持每路状态独立，缺失不当零，港股 D-1 pool 与目标日资格不混淆，超跌两道门不放宽，研究边界不变。

- `RESEARCH_ONLY=true`
- `production_allowed=false`
- `buy_gate_updated=false`
- `orders_sent=false`

另一会话已转为只读 GitHub 交接，并报告没有执行 API 切换、当前仍为 R3 / PID 87015，下一发布窗口已释放。此状态来自跨会话报告，本包未独立核实进程身份或加载模块指纹；后续改动前仍需复核现役身份。本包不授权直接并行切换，也不修改 Vibe 8910 的源码、配置或服务。

## 本包状态

`README.md`、`evidence.json`、`source_map.json` 已整理；`manifest.json` 记录除自身外文件的 SHA-256。Writer 未运行功能测试、未重载 UI、未操作服务或 scheduler、未部署，也未 commit/push GitHub。上传交接分支与路径由主控后续处理。
