# 实施计划：预选池 → 阶段选股 → HK close review

**状态：** future implementation proposal。当前 R7 Writer 只写方案/审计，不实施业务改动；所有下述代码测试本轮 `NOT_RUN`。

**GOAL:** 在唯一 canonical V4 source 中满足已锁定 A-stage 行为，保留 HK 日期/来源/研究安全合同，并按证据做最小局部简化。

**WRITER:** 由主控为后续每批指定唯一源码 Writer；同文件集不得并发写。Close producer 需要其 source/runtime owner 确认输入合同，owner 不是默认 Writer。

**REVIEWER:** 与 Writer 不同 agent identity 的 Luna Max 独立只读 Reviewer；审实际 diff、冻结验收、风险和目标行为并重跑变更所需的 focused tests。

**ALLOWED_PATHS (future implementation batch only):** 每个批次表列出的 V4 canonical `domains/`、`stage_center/`、`ops/`、`infrastructure/`、`apps/api/`、`apps/web/`、关联测试。未来批次开始前仍须冻结精确列表；本文不是本轮代码路径授权。

**FORBIDDEN:** V3 legacy repository；Vibe 8910；真实 market data 和 account data；本轮外部 release trees；第二 producer/面板/store；生产/交易门禁；未列入未来批次的源码/配置/服务/调度器。当前本轮也不更改 Git/branch/remote。

**PASS_SIGNAL:** 分批 tests pass + independent Reviewer `REVIEWED` / 行为批次 `BEHAVIOR_VERIFIED`；最终 release owner 对齐分别留下 API、preselection scheduler、Stage scheduler 与实际 browser bundle 证据。用户要求的自然行为只有在真实目标 slot 才能另记 `NATURAL_VERIFIED`。

**STOP_RULE:** A 有效行丢失、坏源未隔离、HK D-1 日期或 source SHA 变更、七阶段集合改变、Native/Stage Center store 混写、partial/formal/BUY/PIT 混用、缓存 freshness 无可追溯 timestamp contract、或运行 owner/target root 未确认时停止该批并报 `CANNOT_CONFIRM`。不得换样本/复用旧 receipt 掩盖失败。

## Batch 0 — 冻结代码与运行 owner（只读门槛）

**目的和输入：** R7 原始审计、runtime drift 与本设计的源 SHA。当前 R7 基线 head 是 `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`；14:09:45 UTC 最新被观察 API 目录是 `research-desk-20261012-r3/app`，源码尚未审；HK close producer 是分开的 `hk-auto-d1-20261011-r1/app`。API R4 是历史时间点比较，不能称为最新。已记录的调度快照分别显示 Stage Center/Futu R4 `NOT_RUNNING`、HK deadline 旧 R1 `NOT_RUNNING`、V3.5 scheduler R1/PID 8009；这些是采样时状态，R1/PID 8009 的目标行为和最新 workload binding 仍未知，不据此推断当前是否在运行。

**核实内容：** 精确 API plist/root/PID/manifest；pool producer 和 scheduler label；Stage scheduler root/label/active Native vs Stage Center route；browser bundle build/revision；实际 date/root/receipt 绑定。按完整 file SHA 将每个候选输入映射到 canonical source。将 `NOT_RUNNING` 快照与 R1/PID 8009 观察按时间分开记录；确认对应 task 的最终 source/build、launch binding、实际调用与读取者，不能用 PID、plist 中的路径或 API route 代替行为证据。更新 scope ledger，但不扩展 752 locating-index 覆盖为逐行审计。

**Files / signatures:** 只读 `RUNTIME_API_DRIFT_AFTER_FREEZE_R7.json`、`RUNTIME_IDENTITIES_R7.json`、对应 launch manifests/plists 和各 receipt；不改产品文件。

**Commands / expected:** 文件 SHA 清单和 PID/CWD observation 必须互相引用且带时间；API/browser bundle 与 scheduler 三种 owner 分别能定源才 `PASS`。只得 API PID、看见端口、或 API 200 不够。此门槛没有 business pytest。

**Dependencies / rollback:** 后续所有 source-writing batch 的先决条件；任何 owner/source 尚未知就停在本门槛，保留候选工作树，不挑一个 release 代替。

**Ownership:** 主控收齐身份 receipt；未来只读 Reviewer 确认 SHA 对照。主控另行给每个后续批次指定唯一 Writer 和不同 identity Reviewer。

## Batch 1 — 让有效 A 行按锁定合同进入 Native Stage

**当前问题：** `StageInputProducer._stage_candidates` 的 `eligible_ids` 白名单排除了 `a_share_baimao_research_map` 和 `wechat_public_account_v3_preselect`；而 `PreselectionPoolStore.POOL_ORDER` 与 `domains/_preselection_parts/independent_projection.py::_project_independent_pools` 将所有 `market == "A"` 行汇入完整 `a_all_pool_rows`。白名单造成 Native Stage 与权威汇总不一致，违背用户 DECISION_LOCK。`PreselectionPoolStore.read_all(trade_date)` 只忽略 `FileNotFoundError`；单池 `ValueError`/池级文件 integrity failure 会中止全部输入。A 合同冻结为：完整汇总中任一有效且可追溯 A 行可进入候选；坏池单独隔离；缺失、空或 partial 子池保留缺口但不全局阻断候选；状态不升格。

**Scope / target modules:**

- `domains/stage_input_producer.py:36-113` — `StageInputProducer.produce(self, trade_date: str, stage_id: str, *, replace: bool = False) -> dict[str, Any]`；保留合法 stage/date、阶段时间窗、market scope 及候选去重。
- `domains/stage_input_producer.py:36-113,165-210` — `produce(...)` 与 `_stage_candidates(...)`；候选来源用现有完整 `a_all_pool_rows` 语义，不按 pool ID 排除已验证的 A 行；HK 只允许 `hkconnect_d1_top100`。
- `infrastructure/preselection_pool_store.py:41-49,1018-1097`、`infrastructure/preselection_pool_readers.py:1-100` — 保留 exact-date、单一 source root 和 manifest/receipt/source-SHA 验证。`read_all` 保持现有兼容行为；增加窄的按池快照/隔离入口，在同一 root lock 下读取同一交易日的各 pool，避免逐池重开锁造成不同时间快照。
- `domains/_preselection_parts/independent_projection.py:60-135` — 复用 `a_all_pool_rows` 全量 A 汇总规则；Stage 输入不能引用分页后的 API `limit/offset` 结果，也不重复实现另一套 A 聚合定义。
- 关联 tests：`tests/test_stage_input_producer.py`、新增 `tests/test_preselection_pool_partial_read.py`、`tests/test_stage_projection_regressions.py`、`tests/test_preselection_source_root_20261008.py`。

**具体实施:** 新增只读 `PreselectionPoolStore.read_all_with_quarantine(trade_date)`（或同等窄 API）：在一个 exact root 的 `.import.lock` lease 中按 `POOL_ORDER` 逐池调用既有 `read_pool_snapshot(trade_date, pool_id, *, lock_lease=lease)`，复用物理 artifact/manifest/receipt/SHA 校验并维持各池的 pending-read guard；不得逐池解锁后拼接跨时点快照。只在 pool-local artifact 已经可定位、且 `read_pool_snapshot` 的 manifest/receipt/行身份内容校验能明确归属单池时，转换成缺口或 typed `PreselectionPoolIntegrityError(pool_id, reason)` 并隔离该池。root/source-owner 改变、锁 lease/preflight、pending-commit reconciliation、SafeRoot/路径安全错误及未分类 `OSError` 必须 fail closed；不得用宽泛 `except ValueError/OSError` 把它们误判成坏池。保持 `read_all` 原有调用合同。将通过验证的 pool 组交给现有完整投影规则，取全量 `a_all_pool_rows` 作为 A 候选，不按 `eligible_ids` 白名单过滤；仅从精确 `hkconnect_d1_top100` 取 HK 候选，不把其它来源 HK 行引入 D-1 Top100。完整性错误、missing/empty/partial status 和来源 SHA gap 继续进入 `source_summary.cannot_confirm` / source evidence；只隔离损坏池，不抹除仍有效池的行。`market_status[A]` / stage readiness 仍因实际 pool/quote/evidence 缺口为 `CANNOT_CONFIRM`，不能以有效行存在而升格。保持 StageRunner 的 A Top50/HK Top10、Native StageStore receipts、日期和风险标记。

**Tests / commands / expected:**

1. 更新并改名现有反向测试 `tests/test_stage_input_producer.py::test_native_producer_reads_independent_graph_pools_and_excludes_research_only_lanes`（`:184-209`）→ `::test_native_producer_aggregates_every_traceable_a_pool_row`：其 fixture helper `:136-150` 将 `a_share_baimao_research_map`、`wechat_public_account_v3_preselect` 行都声明为 `market=A`，须保留该契约并断言两类有效行均进入完整 request/input；不能再以 pool ID 把它们排除。HK request 仍只有 D-1 Top100；有 quote coverage 缺口时 A 状态仍 `CANNOT_CONFIRM`。
2. 新增 `tests/test_stage_input_producer.py::test_valid_traceable_a_rows_survive_missing_sibling_pool`：一个有效 A 池加 missing/empty/partial sibling，A 候选进入 stage input，gap 和 source SHA 证据仍在。
3. 新增 `tests/test_stage_input_producer.py::test_bad_a_pool_is_quarantined_without_dropping_valid_rows`：单池坏 manifest/receipt 或行身份契约导致该池被隔离，另一个有效来源的 A 行可进入候选；`cannot_confirm` 带池名与失败原因，不把坏池 rows 当成零值或有效 rows。
4. 新增 `tests/test_preselection_pool_partial_read.py::test_pool_integrity_is_quarantined_but_root_and_lock_failures_abort`：确认只隔离显式 pool integrity typed error；source-root/lock/preflight/安全错误向上传递且不 publish Stage input。
5. 新增/延伸 `tests/test_stage_input_producer.py::test_stage_runner_workbench_keeps_partial_a_as_watch_only`，端到端调用 `StageRunner.ensure` + `read_workbench` 并检查实际 workbench selection：有效 A row 出现且 row-level `recommendation_status=WATCH_ONLY`；Stage workbench `stage.status=PARTIAL_WITH_WATCH_ROWS`、`markets.A.source_status=CANNOT_CONFIRM`、partial source evidence/gaps 保留，所有 production/BUY/order flags false；即使 stage run 完成也不得把 evidence 提升成 READY。只检查 producer candidate/input 不算验收。
6. 保留 `tests/test_stage_projection_regressions.py::test_stage_projection_propagates_partial_market_reason_without_status_upgrade` 与 `tests/test_preselection_source_root_20261008.py::test_api_reads_exact_source_date_dedupes_a_pools_and_keeps_hk_separate`。

命令：

```bash
uv run --group dev pytest -q \
  tests/test_stage_input_producer.py \
  tests/test_preselection_pool_partial_read.py \
  tests/test_stage_projection_regressions.py::test_stage_projection_propagates_partial_market_reason_without_status_upgrade \
  tests/test_preselection_source_root_20261008.py::test_api_reads_exact_source_date_dedupes_a_pools_and_keeps_hk_separate
```

Expected：新旧 targeted tests 全绿；确认 `a_all_pool_rows` 所有有效 A 行进入 stage candidate（包括 BaiMao research map lane）、坏源单池隔离、root/lock 失败 fail closed、pool gaps/source evidence 保留、HK exact D-1 Top100 不变；`StageRunner` 可产生 watch row 但不能把 partial/cannot-confirm 提升为 READY。不可用 `READY_EMPTY` 冒充有 gap 的 partial。

**Dependencies / rollback:** Batch 0 PASS。测试失败时只回滚此 producer admission 分支和关联新断言，保留原 receipt 记录失败；不去掉 safety checks，不改其他 stage 算法。

**Writer / Reviewer:** 一个 future implementation Writer 只持有上表 domain/test files；独立 Reviewer 只读同 diff 并亲自复跑上述命令。Reviewer 没有 `BEHAVIOR_VERIFIED` 前本批不视为完成。

## Batch 2 — 删除 Stage Center 一次无用 builder 构造

**依据：** 行审计确认第一次 factory result 被覆盖且没有被消费；这不是采集器、公式或数据状态变更。

**Scope / targets:**

- `stage_center/_runner_parts/slot_execution.py:256-267`，函数 `_StageCenterRunner__run_one_body(_v4_scope, /, self, decision, *, historical_backfill, backfill_run_id, historical_markets)`。
- `stage_center/_live_collectors_parts/selection_builder_registry.py:423-455`，只读引用 `production_selection_builders(stage_id)` 现有 factory。
- `tests/test_hk_observation_calendar_20260925.py`，加一项 call-count。

**Change:** 在 `builders is None` 时只调用一次 factory；保留显式配置分支、市场过滤、candidate validation、RawStore 先于 SelectionStore、receipt/bundle publish 和恢复检查。该初始化精简不能改变 Stage8 的两类路由：同日自然 Futu 采集仍为 natural，历史 replay route 仍标为 historical，不通过 replay 冒充自然结果。

**Tests / commands / expected:** 新增 `tests/test_hk_observation_calendar_20260925.py::test_run_one_constructs_production_builders_once_when_unconfigured`，通过 spy 断言一次构造并检查使用的 builder；保留 `test_run_one_hk_only_filters_extra_a_builder_but_keeps_required_hk_builder` 与 `test_run_one_hk_only_still_rejects_a_missing_required_hk_builder`。一条命令：

```bash
uv run --group dev pytest -q \
  tests/test_hk_observation_calendar_20260925.py::test_run_one_constructs_production_builders_once_when_unconfigured \
  tests/test_hk_observation_calendar_20260925.py::test_run_one_hk_only_filters_extra_a_builder_but_keeps_required_hk_builder \
  tests/test_hk_observation_calendar_20260925.py::test_run_one_hk_only_still_rejects_a_missing_required_hk_builder \
  stage_center/tests/test_selection_consumer_batch3.py::test_consumer_ensure_is_read_only_and_has_no_producer_path \
  tests/test_hk_stage8_v4_recovery.py::test_same_day_route_is_natural_and_historical_route_is_not
```

Expected：builder factory once；market-filtering and required-HK failure tests pass；consumer has no producer/publish/write path；same-day route remains natural and historical route remains non-natural. 新增测试是 implementation task，不表示当前已有。

**Dependency / rollback / ownership:** Batch 0 PASS；与 Batch 1 可分开 review，但一时只允许一位 writer 写 Stage Center test/source set。Call-count 或 identity 差异失败则恢复原初始化，停止 Stage Center simplification。独立 Reviewer 看 diff 后复跑命令。

## Batch 3 — 单一 canonical HK close producer 与可靠失败状态

**当前 source identity:** 定时执行的 R1 collector/builder/domain 路径与 R4 API candidate 不同。canonical worktree 当前已有 `ops/build_close_review.py` / `domains/close_review.py` / stores，但 close report 未在 canonical 找到当前 active collector 的同一 runtime owner。将 R1 producer 迁移进 canonical 是替换 source owner 的计划，绝不建立第二条 active producer 或并行 scheduler。

**Targets and functions:**

- canonical 新建/对齐 `ops/collect_hkconnect_close_snapshot.py`：按 active R1 `ops/collect_hkconnect_close_snapshot.py:42-120,122-196` 移入同一个收集职责；先核实可从 source response 得到 authoritative capture timestamp。`CloseSnapshotStore.import_snapshot(self, payload)` / `read_snapshot(self, trade_date)` 在 `infrastructure/hkconnect_close_store.py:16-79` 校验现有 full-universe/manifest/receipt contract。
- canonical `ops/build_close_review.py:145-194` 的 `build_close_review(data_root: Path, trade_date: str, *, stage_selection_root: Path | str | None = None) -> dict[str, Any]`：保持 exact missing sentinel；不要把 R1 catch-all `FileNotFoundError/OSError/TypeError/ValueError` 改成 `{}`。继续 exact-date read `hkconnect_d1_top100`、七个 stage、expected-SHA publish。
- canonical `domains/close_review.py:43-98,100-212,237-286`：`_metric`、`_missing_metric`、`_partial_research_metric(..., *, evidence)`、`build_native_close_review(...)`。保存 pool source/manifest/receipt SHA，保留 formal-vs-partial 两条 DTO、安全旗标与七 stage evidence。
- `infrastructure/review_store.py:15-47,84-146`：`validate_close_review_reference(payload)`、`ReviewStore.publish_native(payload, *, expected_sha256=None)`。按 schema 分层校验：native `v3_5.close_review.v1` 必须 `RESEARCH_ONLY=true`，同时保留生产/BUY/order false 和 expected previous SHA supersession；既存 imported `v3_5.close_review_reference.v1` 继续要求 `reference_snapshot=true`、既有全部只读安全标志，不新增缺字段门槛、不把它升格为 native formal。`publish_native` 仍拒绝 imported schema，且只能以 expected previous SHA 替换。
- `apps/api/v35_api/_review_router_parts/http_routes.py:79-102` 的 `_create_review_router_body(...)` / GET `review(date)`：审阅目标 date exact projection 和 non-trading-day artifact precedence；这一变化等 Batch 0 确认活跃 API 源后进行。
- Active R1 workload binding `contracts/runtime_workloads.json:1257-1273` 与 `executor_registry_review.py::_hk_connect_close_review` `:781-842`：未来只由 scheduler owner 在另一个 release 批次将既有任务切到 canonical source；不是 Writer 本地自行重绑。

**实施子步:**

1. 接纳 R1 collector 之前先固定 Futu quote capture timestamp 的权威字段、时区、same-date cache 复用规则与 close cutoff。R1 artifact 当前没有 capture timestamp，审计不能推断 fresh。若 authoritative time 或复用时间窗尚未有 owner 决定，则此步停止；保持 `CANNOT_CONFIRM`，不得发明 TTL、以 mtime 代替，或把 stale payload 标 READY。
2. 将现有唯一 R1 producer 实现迁入 canonical collector；保持 Futu HK Connect plates、exact-date row filtering、600+ rows/100% coverage、content SHA、CloseSnapshotStore。调度目标只在 test + reviewer PASS 后由其 owner替换绑定；不能同一 slot 双跑。
3. builder 区分“精确目标 artifact 不存在”与“manifest/receipt/JSON/类型/校验失败”。未确认缺失时保持 typed error/CANNOT_CONFIRM；存入 model pool manifest/receipt/source SHA。Stage selection consumer 保持只读，source-date/stage IDs unchanged。
4. domain/store 只补必需 source identity、partial nested research/safety flags。`ReviewStore` 的 native/imported 两个 schema 分支分别验收，legacy imported reference 保持可读/可 supersede；不要求旧 `v3_5.close_review_reference.v1` 补写 `RESEARCH_ONLY`。不要在本批删兼容 aliases；API route non-trading-day precedence 先取得 API owner的 contract ruling。

**Tests / commands / expected:** 新增以下 focused tests，放在列明的现存 suite，不冒称已存在：

- `tests/test_close_review_producer.py::test_cached_close_snapshot_requires_verified_capture_time`：同日无可验证 capture time 的 cache 不能作为 fresh formal input。
- `tests/test_close_review_verified_inputs.py::test_missing_exact_pool_differs_from_corrupt_manifest`：仅精确 missing sentinel 变 missing metric；坏 manifest/receipt 保持异常/CANNOT_CONFIRM。
- `tests/test_hk_close_review_recovery_r6.py::test_partial_stage_union_keeps_research_only_safety_fields`：缺 stage 不生成 formal union，observed 保持 partial/no-buy/PIT unverified。
- 更新 `tests/test_close_review_producer.py::test_native_review_supersedes_blocked_reference_with_audit_receipt` 与 `tests/test_close_review_slice.py::test_review_reference_is_served_by_date_without_old_runtime_dependency`：无 `RESEARCH_ONLY` 的旧 imported v1 fixture 继续可读并可通过 expected-SHA supersession 被 native 替换。
- 新增 `tests/test_close_review_producer.py::test_native_reference_requires_research_only_without_breaking_imported_v1`：当前 native v1 缺少或置假 marker 被拒；旧 imported schema仍遵守 false safety flags/reference_snapshot并通过独立路径。
- `tests/test_review_api_contract.py`：仅在 route precedence contract 决策后新增 non-trading-day stored artifact test。

并复跑现有 exact identity suites：

```bash
uv run --group dev pytest -q \
  tests/test_close_review_producer.py \
  tests/test_close_review_verified_inputs.py \
  tests/test_review_api_contract.py \
  tests/test_hk_close_review_recovery_r6.py
```

同时确认既有 `test_native_review_ranks_full_close_universe_and_calculates_frozen_kpis`、`test_store_backed_producer_joins_close_model_and_seven_stage_inputs`、`test_native_review_supersedes_blocked_reference_with_audit_receipt`、`test_review_reference_is_served_by_date_without_old_runtime_dependency`、`test_review_endpoint_keeps_rich_exact_date_a_review_when_hk_is_unavailable` 与 `test_hk_review_projection_preserves_partial_observation_contract_fields` 都在命令的测试结果中通过。Expected：formal happy path unchanged；exact missing 与 corrupt 输入不再同形；formal union 7/7；native partial nested marker 全；native schema 要求 `RESEARCH_ONLY`，旧 imported reference v1 不因缺 marker 失效；new replacement SHA/review receipt lineage 和 store supersession 正常。

**Dependencies / rollback / owners:** Batch 0 owner/source freeze + freshness/capture-time policy 是开始 producer 行为改动的阻塞依赖。canonical source Writer 拥有 `ops/collect...`, close domain/store 和 tests；API Writer owner 若需 router 变化另立一批；scheduler owner 持有其独立 workload/plist/release 绑定。若 capture time 无据、任何语义依赖旧 R1 行为但无法分类、或 formal/read path regression，就回滚本批 canonical implementation，不碰 external release/scheduler，不准双 producer。独立 Reviewer 分别复跑 close/domain/store 和 API/scheduler owner的 targeted checks。

## Batch 4 — UI wire-boundary 及安全删除候选

**Dependencies:** Batch 0 确认 canonical UI build/bundle owner 和 active API response；Batch 1/3 contracts 已 freeze。保持单一 8873 UI，不做新 panel。

**Target modules:**

- `apps/web/src/app_shell/useAppShell.ts:297-415,419-629` (`loadPool`, `loadStage`, date change, request lifecycle) 保留日期/nav/abort/loading/error/state；pool GET 仍只显示 response，stage GET 不接收 pool rows。
- `apps/web/src/app_shell/formatters.ts:65-93` 已有 exact date/stage assertions；优先复用这些而非另建多份 validator。
- 建议窄 API module `apps/web/src/api/pool_stage.ts`，一个业务 client 负责请求构造及 runtime `trade_date`/market/pool-status/`stage_id`/pagination 校验；`api/review.ts::loadReview(date, signal?)` 和显式 `generateReview(date)` 仍只管 review。若实现计算表明 client 模块增加复杂度，应原地收拢在当前 api/types边界，不新增依赖。
- `apps/web/src/app_shell/types.ts:1-102,103-127` 与 `apps/web/src/contracts/review.ts`：仅统一 review DTO optionality/field set 后删除重复类型。canonical 8-stage navigation 保留，formal close union 7-stage 单独从 domain/API contract来。
- `apps/web/src/app_shell/useAppShell.ts:127-141,293-296,416-418` 和 `types.ts:120-123` 是 line audit 标出的有限 unused 候选；需复查全 `apps/web/src` caller。

**Tests / commands / expected:** 必须覆盖目标 response 日期缺失/错配、stage 错配、market/status 不合法、请求过期不覆盖新日期、display offset/limit 仅影响 view、review exact date 独立。新 API client tests（如新模块成立）：`apps/web/src/api/pool_stage.spec.ts::rejects_pool_date_mismatch_before_state_update`、`::rejects_stage_id_mismatch_before_state_update`、`::keeps_page_limit_out_of_stage_request_input`。已有 `apps/web/src/App.spec.ts` relevant cases: `does not turn an incomplete zero-row pool into a verified empty pool`; `keeps the V3 pool tables complete instead of merging or truncating groups`; `opens one exact-date A/H review without a cross-date request`; `rejects a preselection response whose date evidence is wrong`; `rejects a preselection response with missing date evidence`; `rejects a close review response whose trade date is wrong`; `rejects a close review response with missing trade date`; `loads every stage snapshot into the timeline and explains an empty HK stage`。

```bash
npm --prefix apps/web test -- src/api/pool_stage.spec.ts src/App.spec.ts
npm --prefix apps/web run typecheck
```

执行前若 api spec 是新增，先实现；Expected：当前已有保护与新 wire-boundary tests 通过，typecheck 无 TS/Vue 错误；pool display 不提供 stage 的 candidate rows，8 stage nav 和 7 stage close union 不混合。ReviewView、HK panel 的已有 spec 也要在 DTO 变化影响时一并纳入命令。

**Rollback:** 如果 API line response/optional fields 与 frozen receipt不合，回滚 client/types 单批；不得把 TS cast 当作 runtime validation，不改外部 R4 bundle。

## Batch 5 — 有边界的删除与指标接口收敛（非必要项，独立审批）

下列项目各自单独 PR/batch，不和行为修复同批，也不自动全做：

- preselection `domains/_preselection_parts/optional_pool_merge.py` 的 `_merge_optional_pools`、`_optional_placeholders` (111行)，已有静态 API read graph不调用且测试拒绝 read-time merge；删除前查 CLI/config/reflection/dynamic imports，并重跑注册表/source resolver tests。
- `domains/close_review.py:43-73` 中重复 metric aliases，在 API DTO/TypeScript contract/ReviewView/HK panel 所有 field consumer 确认后，先兼容读再删一个输出字段；统一单位与空值定义，保持 receipts/content SHA语义已知。否则保持兼容字段。
- UI unused派生量和 `ReviewResponse` 仅经全调用图验证、类型检查、相关组件 tests再删。

**Tests:** 逐项运行真实相关全调用者、模块专属 suite、前端 unit/type check。Expected：无 import/reflection/config consumer 悬空；序列化字段变化由同批 API/UI compatibility tests覆盖。不能仅用“没有 `rg` 命中”判断动态 consumer不存在。

**Rollback:** 任一 consumer break 或 response SHA/field semantics不兼容即只撤回当前删除批；此前 behavior batch 留存。

## Batch 6 — 三个运行 owner 分别集成与 readback

仅当各代码批的 independent review PASS 后由各 release owner接手：

1. **API owner：** exact API root/manifest/PID、date query和review projection；若还要换前端 bundle，明确静态资源 revision并以真实浏览器/reloaded page核验。
2. **Preselection scheduler owner：** 唯一 producer/schedule入口及 data-root；target-date artifact/manifest/receipt/source SHA 与 API exact-date读取相符。
3. **Stage scheduler owner：** Native runner和/或 Stage Center route明晰；绑定 pool receipt→runner receipt→Native StageStore 或 Stage Center RawStore/SelectionStore receipt，证明读取者沿正确 store，不把两个路径混接。
4. **页面/readback owner：** 同一选定日期 A/HK pools、每个 stage、HK close review；明确 zero/missing/partial/formal 和 last-read SHA。
5. **Natural slot：** 另记自然时段证据，不以离线、人工、回放或 R4 fixed approved replay替代。

集成日志分别报告 `IMPLEMENTED/TESTED/REVIEWED/INTEGRATED/DEPLOYED/API_VERIFIED/UI_VERIFIED/BEHAVIOR_VERIFIED/NATURAL_VERIFIED`。用户规则授权的私有 GitHub 同步由主控按当前仓库合同执行；本计划不触碰发布、启停服务、外部调度操作或交易。

## 当前已知缺口

- API 最新观察的 `research-desk-20261012-r3` 运行源、bindings和response 未审。
- API PID/CWD 不证明 browser bundle；UI page 未回读。
- 已观察到的 scheduler 状态按时间保留：Stage Center/Futu R4 与 HK deadline 旧 R1 是 `NOT_RUNNING` 快照；V3.5 scheduler 记录为 R1/PID 8009，但其行为及最新 workload binding 未确认。不能由 API identity 推断当前状态或 natural execution。
- R1 snapshot payload没有 capture time；authoritative Futu timestamp、zone/cutoff/cache validity规则需 owner核实。此规则未知时 Batch 3 stop。
- R4 `ApprovedResearchReadBinding` 固定 20261009/0930_0935 replay adapter的 exact pair/backing payload没读；不能当成当前 stage producer或 natural success。
- 本轮没有运行上述任何 business pytest、frontend tests、collector、runner、API 或 UI；这里的 commands/expected outcome 是未来计划，不是测试结果。
