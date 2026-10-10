# 源码复用图与逐路追踪点

## 运行链与源码身份

当前实际读取链来自 E deployed release（源码完整快照在 `source/current-live-release/app/`）：

`manager_research_router.read_manager_workspace` (207) → `ManagerResearchJobService.get_workspace` → `workspace.get_workspace` (482) → `workspace._compute_workspace` (666) → 原 owner reads / `workspace_daily_channels.build_daily_channels` (79) → 既有 API/date 验证 → `catalystObservationPanel.render` (471)。以 `SOURCE_MANIFEST.json` 中当前 release 模块 SHA 为准。

历史阳性公告链来自 `manager-daily-chain-20261008-r2-api` release（完整必要快照在 `source/historical-r2-release/app/`）：`run_manager_daily_announcement._register_handoff/_import` → `workspace_announcements.validate_registered_handoff` → `announcement_analysis.build_product/import_product` → router `import_announcement_analysis` → `ManagerResearchJobService.import_announcement_analysis` → exact date product/readback/owner receipt。该旧 runner 的历史 `register-handoff` 是 `CURRENT_INTERACTIVE_REPAIR_TASK_NOT_NATURAL_HEARTBEAT`，不是自然周期执行。

这些是为修复问题挑选的 manager research 源文件，不是完整 release；完整的真实 owner 数据、数据目录、运行态状态和服务配置没有随包提供。

## ANNOUNCEMENT：旧真实产品日期不匹配

当前期望 `(target_trade_date=20261009, publication_date=2026-10-08)`；旧 VERIFIED 产品为 `(20261008, 2026-10-07)`。`workspace_daily_channels.build_daily_channels` 把 `plan_date` 与 announcement publication binding 归一化后，以两字段精确筛 `announcement_reviewed_analysis.products`。零 exact 产品时给 `ANNOUNCEMENT_EXACT_DATE_PRODUCT_NOT_CONSUMED`。`workspace_announcements.read_analysis_consumption(service,target,publication,...)` 使用 `announcement_analysis.product_path` 精确读取，比较 product/readback 的 target、publication、product SHA、source manifest/catalog SHA、agent judgment receipt 和 owner import receipt，然后再检查 cutoff 与 selection counters。禁止把旧两日期中的任何一个字段改绑。

- 当前实际 gap：0 verified rows，no consumed evidence run/product，根因仍 `CANNOT_CONFIRM`。
- 需要从真实当前 owner readback/receipt 查 `announcement_reviewed_analysis.products`、`research_references`、`product_checks`、`other_product_checks`、`target_trade_date`、`publication_date`、`sha256`、`source_manifest_sha256`、`catalog_run_id`、`evidence_run_id`、`agent_judgment_receipt.sha256`、`owner_import_receipt.sha256`、`selection_status` 和 `not_assessed_stock_count`。当前 16 MB 响应与 saved owner readback 均不入包。
- 可复用历史实现：日期 catalog/handoff 校验、exact pair product build、不可覆写不同产品的幂等 import、owner readback/receipt 校验。真实历史 catalog、reviewer output 与 article decisions 未打包；历史正向数据不能从 ZIP 单独复跑。

## HK_CONNECT：目标日 V2 authority/membership 未确认

当前 workspace 的 consumer 是 `workspace._compute_workspace` → `connect_selection.read_scope(context)`；它调用 `domains.manager_research_evidence.read_universe_evidence(root, date, require_v2=True, authority_owner_root=..., authority_owner_sha256=...)`。当前 receipt gaps：`HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:HK_UNIVERSE_V2_ARTIFACT_MISSING` 与 `TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED`。

精确检查 `V4_MANAGER_UNIVERSE_ROOT`、`V4_MANAGER_UNIVERSE_OWNER_ROOT`、`V4_MANAGER_UNIVERSE_OWNER_SHA256` 的 runtime binding，返回 artifact V2 schema，`source_date==target_trade_date`、`market=HK_CONNECT`、`source.sha256`、`acquired_at/available_at<=research_cutoff`、canonical sorted unique membership codes、`authority_reader_binding.source_code_ref/source_code_sha256`，以及 `connect_selection._scope_error` 的 membership result。fallback previous-session capture 只是 source evidence，不能升级为目标日 authority。真实 producer/root cause 仍 `CANNOT_CONFIRM`。

## OVERSOLD：历史 panel 覆盖和量单位证据不足

当前路径是 `workspace._compute_workspace` → `workspace_plan.read_rebound_screen(authority_root,context)` → `_read_hk02_panel_witness`、`_screen_panel_volume_evidence`、`rebound_native_evidence` 和目标日 security master witness。它复用原 HK panel 和日期 security master，不建新 market producer。review receipt 显示 `pending_count=693`、`total_gap_count=695`，包括 `REBOUND_HISTORY_VOLUME_UNIT_NOT_PROVEN` 及 history/volume incomplete gaps。

下一步只核已绑定 screen authority root 下的原 owner：`panel_path`、panel/manifest SHA、manifest `panel_max_date`、`native_observation.owner_source_sha256`、`read_started_at/read_completed_at/manifest_prepared_at`、`requested_through_date`、所需 `prior60` 60 日 + `previous5` 5 日 session 集、每证券有效 high/volume bars、native volume 字段/byte offset/storage type、unit/scale 与 provider attestation/source SHA、security-master capture 时间。不能把裸 unit 字符串当作 attestation。旧的 3.24 MB真实 analysis 产品与市场 panel 不在包里；owner/input provenance 不足继续 `CANNOT_CONFIRM`。

## 正式 Stage：当前 consumer 只证实缺少结果

`workspace._compute_workspace` 通过 `service.observation_reader.read(date)` / `_reader_value(...,'STAGE')` 调原 Stage reader；`_stage_attempt` 只接受 exact-date LIVE execution-ledger receipt。当前 evidence 是 artifact `CANNOT_CONFIRM`、lane `UNVERIFIED`。向原 owner 查目标日期、market/pool contract、固定池输入 manifest/SHA 与 membership、receipt `target_date`/`scheduled_date`/`workload_results`、Stage run/artifact SHA、consumer date 与 readback status。固定池合同：A 为完整同日 `a_all_pool_rows`；HK 为精确上一 HK 交易日 canonical D-1 Top100。当前没有足够 receipt 将空 workspace 列表解释为正式 Stage 合法零选股。

## 历史证据与未核声明

- 真实历史公告 owner receipt：`VERIFIED`，target 20261008/publication 2026-10-07，run `3f9d37a643060b57992167f3df05d987`，product SHA `8b1e906db2cdcb8784d9658085aa4f1aa0711a8711b83a38c9ee8d7567151157`。其 analysis 摘要 613 article decisions，37 个 `SELECTED_EVENT`/`SELECTED_PERFORMANCE` 决定，覆盖 33 个 unique HK source codes；79 `NOT_ASSESSED`。只证明公告分析 lane 有历史阳性决策。
- 真实历史 catalog、reviewer receipt/output 和 article decision 文件不放入 ZIP。`NOT_REPRODUCIBLE_FROM_PACKAGE`；不能声称本包/合成 fixture 重现真实 33 个证券结果。
- 用户提及的 2026-09-30 三路独立成功在本包和 E live acceptance 中未核，`CANNOT_CONFIRM`；不与 10/8 公告阳性或 10/9 current failure 混淆。
- E 有独立 GET body (16,410,445 bytes, SHA `5f56cc...f53952`, 未持久化) 与本地 saved owner readback (16,410,447 bytes, SHA `6c0fe...40bdbc`) 两个不同 evidence；二者均不入包。

## 定向测试

包内 `tests/upstream_reference/test_manager_announcement_analysis.py` 与 `test_manager_announcement_daily_flow.py` 是项目原测试文件的完整 byte copies；它们本身用 synthetic fixtures，不包含真实决策。`tests/test_synthetic_package_contract.py` 及 `fixtures/synthetic_lane_contracts.json` 只检查脱敏 contract 字段如何连线，不能替代实际代码测试或真实 owner 输出。准确命令和复现限制见 `README/CHAT_HANDOFF.md` 与 `SOURCE_MANIFEST.json`。
