# V4 代码定位图谱（含 V3.5 历史链路）

本页沿用原图谱路径，不新增图谱服务或第二份调度配置。当前索引更新于 **2026-10-30**，业务取证样本覆盖 **2026-10-29** 已有结果和 **2026-10-30 10:29/10:30** 默认运行；覆盖桌面阶段加载、A 股阶段输入/补选和研究面板日更三条主链，不声称是全仓完整调用图。

## 先分清源码、运行包与历史合同

- 工作区源码根为 `/Users/lexi/Desktop/学习/v4_app`。本次读取的工作区基线是 `claude/v4-typecheck-budget-20261029@7ed00ca916a55a55a0bea95944c004cb6570b6f1`；这是定位快照，不是固定分支要求，也不是整包已部署证明。
- 下表API/Main/Stage绑定更新于 **2026-10-30 10:09 +08:00**；HK一项保留00:38历史观测。新任务必须重新读取目标 label 的配置、实际 PID/cwd 和 manifest；不要复用本文 PID，也不要把 idle 定时任务没有 PID 判成故障。
- `R` 表示 `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases`。表中 app 根均为 `R/<release>/app`。

| 角色 | launchd label | 观测到的 release | 本次确认范围 |
| --- | --- | --- | --- |
| API / 8873 | `com.lexi.v4.api` | `a-daily-name-zoom-20261030-r1-api` | loaded身份核回；阶段源码/七阶段合同与已验r2一致，当前09:25实点通过 |
| Main 调度 | `com.lexi.v4.scheduler` | `a-daily-name-zoom-20261030-r1-main` | loaded显式pin、14文件及10:00真实成功见证核回；本轮未改 |
| Stage 调度 | `com.lexi.stage-center.scheduler` | `a-stage-owner-compatibility-20261030-r2-stage` | 10:08切换；10:29默认运行产出4×522→10补选，原严格节点失败仍保留 |
| HK deadline | `com.lexi.stage-center.hk-deadline` | `v4-retirement-20261028-stage-deadline` | 00:38历史观测；本轮未改、未重新认证 |

当前 API manifest 的直接父本是 `a-daily-dashboard-c6-20261030-r1-api`。不同增量分别沿各自source字段溯源，桌面导航增量的 `p7_desktop_navigation.source_root` 指向 `/Users/lexi/.codex/worktrees/v4-formal-fixes-20261029/v4_app`。这些是分层来源字段，不等于任一目录与整包完全同源；实际修改前仍须按目标文件核 SHA 和当前 owner。

工作区的 API 文件在 [`apps/api/v35_api/app.py`](../apps/api/v35_api/app.py)，当前运行包的对应入口名是 `apps/api/v4_api/app.py`。**工作区没有同名 `v4_api/app.py`，也没有本次运行包中的 `stage_center/snapshot_recovery.py`；不要因此新建占位实现，或把运行包整体覆盖回工作区。** 先回到对应集成来源核对目标文件；包名、目录名中的 `v35` 本身不证明正在运行旧服务。

### 本批修复源码与验收位置

本批业务实现不写回冷主工作区。Claude可编辑源码位于 `.task_worktrees/claude-v4-stage-loading-20261030`，原交付源码提交为 `f5bc8cee8c876fe42adef6d93f167b1e4360d251`。阶段首屏提交 `e0a6cac25f0eb406fa6848b32e5a9591dcaf709c` 的父提交 `ee4a0ff6` 已整合 P29 补选展示与两项去重；后续 `f5bc8cee` 增加已审 owner 读取修复与精简验收结果。定位增量时优先读此工作树对应文件，而不是在冷副本新造实现。

- `apps/web/src/app_shell/useAppShell.ts::loadStageTimeline`：复用已取得的同日同阶段当前 payload，详情请求由每次 9 个减为 8 个；后台其余 7 个完整详情仍存在。
- `domains/_preselection_parts/date_catalog.py::__verified_stage_artifact_catalog_body`：复用首次验证结果，删除同请求内第二轮重复 `read_verified`。三个交替真实 GET 对照中位数由 2754.64ms 降为 2261.82ms，九个目录投影相同；不是日间 p95，目录仍约 2.38MB。
- `apps/web/src/App.vue`：地图原生折叠、展开才挂载；血缘详情与原始报价表默认折叠，补选 Top10、原失败及真实时钟保持可见。14 个定向前端测试及构建通过，typecheck 保留同 26 条基线诊断。
- API 候选为 `v4-stage-performance-supplementary-20261030-r2-api`，manifest SHA `3d61dac217dec804042ae9b03eb446be5d2e6f075ec46528708a2bfb8ba7e637`。它经过原完整集成 helper，1289 个非 delta 条目和 455 个研究面板资产保留；09:15已实际激活正式8873。后续NameZoom版保留相关源码与结果，当前版本身份另行核回。
- 真实隔离 Chrome 已验收 13:15 原 A10，以及 09:25、09:35、15:00 各补选10条；报价56行可展开，地图仅展开后读取现有接口、收起即卸载。测试服务为 18874，不冒充正式入口或自然时段验收。
- 既有五份补选只读消费已通过；没有重跑评分或采集。Stage owner 兼容问题的复现见下文，修复与激活状态单独记载，不因 API 候选通过而一并升格。

当前Stage集成工作树为 `/Users/lexi/.codex/worktrees/v4-formal-fixes-20261029/v4_app`，分支 `codex/v4-stage-formal-auto-20261030`，已精确导入CC九份末态并保留SOP。当前API/Main另含日更看板任务增量，禁止用该工作树整包覆盖现役。Stage封存/配置/实装/自然状态见同分支 `docs/handoffs/20261030-stage-formal-auto/RESULT.json`；正式29日五段各10已完成接口及电脑点击验收，默认自动补选已在真实10:29运行产出四个到期早段，不能据此认证原自然选股/PIT或未到的15:00。

P32源码提交`a59af2db7e45318ce322bd34be08539334cc2414`仅修App的补选空卡说明及对应测试，8/8与构建、独审通过；该源码是候选，当前NameZoom API仍使用旧空卡。唯一原生管理员入口读取Desktop脚本EPERM，切换前已停止，未动Main/Stage。不能用P31补选表的代表点击代替P32卡片与锚点的正式验收。

## 按症状定位

以下仓库链接只用于定位同名源码。除明确记录的函数/文件对照外，不表示链接指向的整个文件与现役包相同。

| 症状 / 入口 | 首看节点 | 下一层与证据边界 |
| --- | --- | --- |
| 阶段首屏等待、反复加载 | [`useAppShell.ts`](../apps/web/src/app_shell/useAppShell.ts) 的 `onMounted`、`loadStage`、`loadStageTimeline` | 日期目录、当前阶段请求与后台时间线分开看；不要把后台请求全算成首显等待 |
| 阶段 HTTP 读取或分页 | [`pool_stage.ts`](../apps/web/src/api/pool_stage.ts) 的 `loadPoolSnapshot`、`loadStageSnapshot`、`requestJson` | 预选池展示页大小为 200，阶段详情页大小为 50；展示分页不代表原引擎的完整输入被截断 |
| 日期目录慢或日期缺失 | [`preselection.py`](../domains/preselection.py) 的 `date_catalog`；实际实现在 [`date_catalog.py`](../domains/_preselection_parts/date_catalog.py) | facade 用 `_v4_scope` 转交实现；继续看 `_date_catalog_body`、`__verified_stage_artifact_catalog_body` 和 `__verified_independent_pool_dates_body`，不要只改 facade |
| A 股候选来源缺失 / 隔离 | [`preselection_pool_sources.py`](../infrastructure/preselection_pool_sources.py) 的 `read_all_with_quarantine` | 核日期、市场、来源 SHA 和完整汇总。有效池应可继续，坏子池只隔离；保留原始 source/receipt |
| 竞价或实时输入字段不一致 | [`selection_builder_registry.py`](../stage_center/_live_collectors_parts/selection_builder_registry.py)；读取 **Stage 包**对应副本 | 区分 native / 非 native 分支；检查权威候选叠加后到原引擎输入的投影，不在 API 包里猜生产者行为 |
| 阶段有行情却无正式 A 结果 | [`consumer.py`](../stage_center/consumer.py)；Stage 包的 `infrastructure/manager_input_attestation.py` | 依次核研究 publication、completion witness、密封 owner 和代码/config inventory；行情 READY 不等于选股输入见证通过 |
| 研究小时任务收口失败 | [`executor_registry.py`](../infrastructure/scheduling/executor_registry.py) 入口；Main 包的 `infrastructure/scheduling/executor_registry_research.py` 拆分实现 | `ops.collect_hourly_research_input`、`ops.run_hourly_research` 与 `ops.refresh_research_preselection` 分别核结果；内部产物成功不能替代工作项最终完成见证 |
| 阶段产物校验 | [`selection.py`](../stage_center/selection.py) 的 `SelectionStore.read_verified` | 核 immutable artifact/manifest/receipt 与 latest entry；API 读到报价观察不证明原引擎 Top10 已落盘 |
| 日线已更新、研究页面名单未同步 | [`macos_research_panel_daily.py`](../ops/macos_research_panel_daily.py)、Main 的 `_run_a_daily`；API 包的 `apps/api/v4_api/a_share_panel_history.py::read_history` | 数据 generation、日期化数值结果、页面资产是不同层；单股行情读取正常不证明固定名单已自动换日 |

### 1. 桌面阶段读取链

1. `useAppShell.onMounted` 读取 `/api/v1/runs/date-list` 与 `/api/v4/research/dates`，随后默认阶段分支启动 `loadPool`、`loadStage`。
2. `loadStage` 经 `loadStageSnapshot` 请求 `/api/v4/workbench/stage`，通过响应身份校验后更新当前卡片；之后 `loadStageTimeline` 在后台读取时间线。
3. API 包中 `apps/api/v4_api/app.py::run_date_list` 调用 `_catalog`，后者转到 `domains.preselection.date_catalog`。阶段详情由同文件的 `stage_workbench` 读取和投影，正式产物校验最终落到 `SelectionStore`。
4. 请求数、服务器读取次数、响应字节、浏览器渲染耗时应分别量测。本文没有真实日间 p95、完整桌面浏览器瀑布或渲染性能认证。

00:39 的换版增量对照确认：新旧 API 包的 `loadStageTimeline`、`loadStage`、`onMounted`、`loadPool` 函数文本未变，`date_catalog.py` 和 `pool_stage.ts` 文件字节未变。既有受控机制探针可按此范围复用；旧包 HTTP 耗时不能改标为新包实测。

### 2. A 股阶段生产、研究见证与补选链

1. Stage 按自身配置解析 `preselection_source_root`、候选输入和 `a_auction_root` 等来源，A/HK 独立处理。09:25 native manifest、完整候选输入、行情、研究上下文是不同检查点。
2. Stage 的研究读取器按小时 publication 与 completion witness 核对密封 `research_owner_binding`。03:57 的真实只读对照已确认：现役 Stage 仍钉 `a-chain-natural-repair-20261029-r3-main`，因此拒绝 23:00 已成功的 `a-daily-sop-closure-20261029-r1-main` 完成回执；同一原 reader 使用经 inventory 核验的当前 Main pin 则通过。阻断在完成回执的 `release_id` 匹配，不是缺行情，也不能只按 materializer 代码 SHA 区分同字节 owner。修复必须同时保留显式旧 owner provenance；不得动态发现 `latest` 或绕过原见证。该对照不解释此前 15:00 code/config drift。
3. 原引擎完成评分、排序与 Top10 后，由 `SelectionStore` 保存可追溯结果；API 再读取正式选择产物。某股没有进入 Top10 与某阶段根本没有正式产物必须分开诊断。
4. 快照补选沿 [`STAGE_SELECTION_SOP.md`](operations/STAGE_SELECTION_SOP.md) 复用现有 Stage tick。运行包中的 `stage_center/snapshot_recovery.py` 与 `consumer.py` 是补选接入定位点。快照观察只是输入；只有原引擎已消费并产出结果，才能称补选完成。迟到结果必须保留真实时间、标明“事后快照补选”并保持 `WATCH_ONLY`，不得覆盖原自然失败或回填成历史 PIT 成功。
5. 本批 owner 修复仅修改 `infrastructure/manager_input_attestation.py::read_stage_hourly_attestation`：最多 current + 两个历史显式 pin，同代码 SHA 只作筛选，完整原成功 dispatch 见证才能选定 owner；除精确见证缺失外的来源/时钟等错误立即传播。隔离 Stage reader/config 两项 delta 已通过26项定向测试及一次独立审查。三份真实只读样本：13:00旧成功保留、23:00新成功通过、09:00原代码身份错误保留。以上是CC隔离阶段的原验收。10:08已实装Stage R2，current=NameZoom、history=C6/SOP，真实新Main10:00见证通过；更老R3已退新窗口但原文件及D29产物保留，10:29默认调度已产4份各10补选，Stage/API读取及桌面代表实点通过，原严格输入版本错误/partial仍保留。
6. 以后 Main 换版的既有依赖顺序应是 Main封存 → Stage显式 pin更新 → Stage封存 → 核实际launcher绑定；必须用一份换版后真实 publication检验完整 completion witness。这里只记录发布依赖与定位规则，不宣称已新增程序化发布阻断器。不能再次仅切Main、遗留Stage旧pin，也不能把隔离候选直接当正式发布计划。

### 3. 研究面板日更链

当前统一规则入口是 [单股修复与研究面板 SOP](../../因子工厂/research/a_share_local_panel_completion_20261024/SOP_SINGLE_STOCK_REPAIR.md)，API 对应 `/api/v4/research/single-stock-repair-sop`；`/api/v4/operations/sop` 的阶段文档白名单不是这份日更 SOP。

- 原 A 日更任务按 SOP 调整为 16:10，仍复用原 producer 获取官方按日期 g4day ZIP；未就绪有界等待，不能发空数据或全表 TCP 回退。16:10 是调度计划，不是已完成或时限保证。
- Main 既有 `research_panel_daily_a` 注册走 `_run_a_daily` / `ops.macos_research_panel_daily`。复权缓存消费同一批原始事实，只处理变化、新增、缺失或失效部分。
- 当前历史读取根由 `V4_A_SHARE_HISTORY_DATA_ROOT` 绑定到 `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/数据`，不是学习根的旧 `数据/` pointer。定位先读其 `data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt`，再核 generation 与 producer receipt，不重哈希 8.7GB 面板来定位页面问题。
- 2026-10-29 23:39 的 metadata 观察显示数据 generation 已到 D29；00:39 新 API manifest 的固定名单仍为数据日 D28、观察日 D29、283 只。SOP 明确日期化结果到固定页面的自动链尚未接好，**不能把数据更新等同于页面同步完成**。
- 已有数据层到“每日数值结果及索引，再由原页面按日期读取”的边目前是待接入边，不是本文宣称已经运行的调用。接入不得新增 producer、面板或闹钟，不应每天改 HTML/JS 再打包；保留“先数值筛选，用户确认后再新增图审/生成图”的冻结决定。
- 数值依赖定位：因子工厂原 `five_group_completion_r1/run.py::derive` 使用**同目标日过滤前描述符**和已接受的原公式结果，`assemble.py::run` 产出 `ALL5808_GROUP_MEMBERSHIP.json`，再交 `numeric_filters_v1_r1/run.py::compute` 与 R5 `d3_terminal.py::check`。`old` 不是昨日名单；原 `run.py` 固定 D28 并校验输入 prefix，`assemble.py` 固定保留原157及D28账本，不能直接挂为每日任务或把日期标签改成D29。
- 日期化接入仍缺同日原公式/描述符、base membership、随 generation 滚动的交易所日历/PRIOR10及原始 reference_prev_close 合同。现 QFQ `pre_close` 不能替代原始参考昨收，`user_v1_*` 也未经等价认证成为原云公式。保留 UNKNOWN、D28历史及来源/PIT未认证，不据行情日已更新就发布新日数值名单。

> 上述研究面板日更段保留04:39的定位结论。随后另一任务已安装NameZoom API/Main；本轮保留其名称、图表和日更增量，仅核其Main完成见证，未重新认证该任务的日更语义或15:40自然执行。当前状态以原 `因子工厂/research/a_share_local_panel_completion_20261024/SOP_SINGLE_STOCK_REPAIR.md` 及实际回执为准，不能把旧“未实现”当作新版本结论。

## 图谱维护与证据

- 修改模块或换版时只增量更新受影响的入口、owner、来源和证据边；保留旧版本日期，不把猜测边画成已运行边。
- 下列为本地原始定位证据，不应随源码批量上传：
  - [四角色绑定快照](../../agents调试/v4_stage_loading_sop_audit_20261029/code_map_runtime_binding_observed.json)
  - [桌面导航换版的目标函数/文件对照](../../agents调试/v4_stage_loading_sop_audit_20261029/desktop_navigation_release_delta.json)
  - [阶段请求与启动顺序受控回执](../../agents调试/v4_stage_loading_sop_audit_20261029/stage_loading_controlled_receipt.json)
  - [日期目录读取次数受控回执](../../agents调试/v4_stage_loading_sop_audit_20261029/date_catalog_duplicate_read_receipt.json)
  - [数据指针与页面绑定 metadata](../../agents调试/v4_stage_loading_sop_audit_20261029/current_data_and_panel_binding.json)
  - [研究小时任务历史身份追溯](../../agents调试/v4_stage_loading_sop_audit_20261029/owner_binding_historical_identity_trace_20261029T161629876850Z.json)
- [`v35-runtime-selection-research-graph.md`](v35-runtime-selection-research-graph.md) 与 `contracts/v35_runtime_graph_topology.json` 是既有静态拓扑合同；构建入口为 `infrastructure/runtime_graph/v35_topology.py::build_v35_topology`。本批未重建 JSON 合同、未增加运行节点、未改 collector 或 scheduler；247 节点等旧统计不代表上述 V4 链已全部线上验收。
- 所有研究仍保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。本文只是索引，不是部署、生产或交易授权。

---

## 以下为 V3.5 历史图谱，不作为现役 V4 调度表

The following historical graph describes the earlier V3.5 entry points and
contracts. It preserves ownership and evidence flow; a `READY` receipt is never
substituted for an artifact, pointer, API response, or page observation.

## Runtime ownership

```text
legacy V3 / shared producer
        │ exact-date artifact + manifest + receipt
        ▼
V3.5 adapter or consumer
        │ validated JSON receipt / immutable pool artifact
        ▼
state/data current or dated pointer
        │ API consumer
        ▼
8873 backend API
        │ date + stage query
        ▼
V3.5 web UI
```

The Stage Center remains the only raw stage-selection producer. The research
panel lane remains the A/H panel producer. Review Core remains the owner of
ReviewBundle, public-fupan and Stage7 evidence. The V3.5 scheduler only
orchestrates those existing owners and records their typed result; it does not
recompute or impersonate them.

## Scheduled entry points

The authoritative legacy-derived times are registered in
`contracts/runtime_workloads.json` and dispatched by
`infrastructure/scheduling/executor_registry.py`:

| Time | V3.5 workload | Existing entry point | Evidence boundary |
| --- | --- | --- | --- |
| 09:01 / 20:01 | `wechat_preselection_sync` | `ops.wechat_preselection_sync` (consumer-side exact-pair sync) | canonical producer is the legacy `wechat-account-new-article-poll`/`wechat_pipeline_runner sync -> wechat_publish_v35_preselection.py` chain after an exact URL; missing or partial input is retryable `CANNOT_CONFIRM`/`URL_REQUIRED`, never a scheduler-produced pair |
| 17:00 | `research_panel_daily_a` | Existing formal `com.lexi.research-panel.daily` label, `ops.macos_research_panel_daily.py --lane A` | exact formal authority-chain arguments; dated A receipt is the producer evidence; the unified scheduler must supersede the old 60-second label before deployment |
| 17:20 | `research_panel_daily_hk` | Existing formal `com.lexi.research-panel.daily` label, `ops.macos_research_panel_daily.py --lane HK` | exact formal authority-chain arguments; dated HK receipt is the producer evidence; the unified scheduler must supersede the old 60-second label before deployment |
| 17:30 | `research_panel_runtime_evidence` | `ops.publish_research_panel_runtime_receipt` | dated A/H producer receipts, selector/backtest pointers and dated close-review receipt |
| 21:15 | `review_core_pool_pipeline` | `ops.run_review_core_natural_pool_pipeline` | explicit calendar, previous HK date, next A date, package roots and Review Core provenance |

The scheduler's `ALL_SLOTS`, `compute_dates` and
`resolve_due_slot` are in `ops/run_scheduled_slot.py` and
`ops/run_v35_macos_scheduler.py`. The 09:01 workload keeps the business date;
20:01 and 21:15 use the next eligible target date. A bounded 300-second heartbeat can recover a
missed exact slot; ledger claims and dated receipts make the retry idempotent.
The fixed slot order is chronological through the research-panel chain:
`17:00 -> 17:10 -> 17:20 -> 17:30`. A retryable 15:00 failure cannot consume
an exact 17:00/17:20 producer wake; the 17:30 publisher remains dependency-
ordered catch-up after both producer lanes.

The 17:00/17:20 producer lanes reuse the already-proven formal research-panel
entry and its full authority argument set. They are not a second collector. A
future formal install must atomically replace or disable
`com.lexi.research-panel.daily` before enabling these two unified-scheduler
workloads; the candidate batch intentionally performs no install or service
action.

The 20:25 Review Core acquisition owner is intentionally not taken over by
these workloads. It remains a separate owner in the V3 graph until its own
Mac runtime is proven.

## Research panel lineage

```text
com.lexi.research-panel.daily (existing formal owner; superseded at deploy)
  └─ ops/macos_research_panel_daily.py --lane A @ 17:00
  └─ ops/macos_research_panel_daily.py --lane HK @ 17:20
  └─ state/research_panel_daily/receipts/{A,HK}-{date}.json
       ├─ selector pointer: state/workspace/数据/data_layer_interface_current/
       │                    CURRENT_SELECTOR_READY_PANEL.txt
       ├─ backtest pointer: state/workspace/数据/backtest_panel_interface_current/
       │                    CURRENT_BACKTEST_BASE_PANEL.txt
       └─ close review + receipt: state/data/close_reviews/{date}.json
                                  state/data/receipts/close_reviews/{date}.json
              │
              ▼
ops/publish_research_panel_runtime_receipt.py
  └─ state/data/runtime_graph/evidence/research_panel_status/{date}/
       ashare_research_panel.json
       hkconnect_research_panel.json
              │
              ▼
ops/collect_runtime_graph.py → infrastructure/runtime_graph/service.py
              │
              ▼
runtime graph API and 8873 observability panels
```

The publisher is a lineage publisher only. If the A authority is still
`REBUILD_REQUIRED`, it reports `PARTIAL`/`CANNOT_CONFIRM` and does not promote
that lane. The HK lane is evaluated independently.

## WeChat exact-pair lineage

```text
canonical V3 WeChat producer (exact URL verified)
  ├─ wechat-account-new-article-poll (profile hint / typed receipt only)
  └─ wechat_pipeline_runner sync -> wechat_publish_v35_preselection.py
        │
        ▼
verified V3 WeChat run
  ├─ wechat_manifest.json
  └─ wechat_rows.csv
        │ exact effective date + SHA/schema/date/safety validation
        ▼
ops/wechat_preselection_sync.py
        │
        ├─ state/data/preselection_pools/{date}/wechat_public_account_v3_preselect.json
        └─ state/data/preselection_pools/{date}/receipts/...
              │
              ▼
preselection API → 8873 D-1 / research view
```

The future scheduler input binding is the single source root
`state/data/preselection_inputs/{effective_date}` (or an explicit
`V35_WECHAT_INPUT_ROOT` under that root); it is kept separate from the output
store `state/data/preselection_pools/{effective_date}`. The historical
`state/data/preselection_pools/20260821/wechat_{manifest,rows}` pair is
evidence-only/one-time canary input and is not a natural-production fallback.
The sync does not enumerate another date, infer a filename suffix, or create a
run when the pair is missing. A `CANNOT_CONFIRM`/`URL_REQUIRED` sync is emitted
as a typed retryable failure, not a successful scheduler lane; the bounded
heartbeat may retry it after the exact pair is published. The scheduler never
claims the profile poll or the legacy exact-pair producer as its own.

## Review Core natural pool lineage

```text
20:25 Review Core acquisition owner (separate)
        │
        ▼
ops/run_review_core_natural_pool_pipeline.py @ 21:15
        │ review_core.pool_pipeline (non-shell, explicit roots)
        ├─ HK close review
        ├─ public fupan pool
        └─ Stage7 pool
              │ run_id + artifact/manifest/receipt SHA
              ▼
Review Core shared store / current pointer
              │
              ▼
preselection API + 8873 review/pool panels
```

The adapter returns `PARTIAL` or `CANNOT_CONFIRM` when any required workload
or provenance is incomplete. Existing public fupan evidence can therefore be
shown without fabricating Stage7 or video evidence.

## LaunchAgent contract

`ops/install_v35_macos_launchagents.py` renders two deterministic payloads:

* `com.lexi.v35.scheduler`: exact calendar intervals plus
  `StartInterval=300` for bounded catch-up. It is the business dispatcher.
* `com.lexi.v35.runtime-graph`: a separate observability-only one-shot
  collector with the same 300-second heartbeat. It carries
  `V35_OBSERVABILITY_ONLY=true` and cannot be treated as a producer receipt.

Both payloads carry the three safety flags as false. This candidate only
renders release-owned artifacts under the permitted Mac roots; it does not
perform a formal LaunchAgent cutover.
