# M17固定来源与目标

原总计划24c6d60d524f43fcf4209ec8b078ec02cb34417e / V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md：M17/P4。
迁移d1bf034640ca2e5957423de2745a98e159b69af2 / V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md：M17（旧盘点16）。
代码固定f7cb731c384ee6890a87d16c19a5b5a621779477，完整树无close_discovery_daily.py。以下源码已读，非活动Mac匹配/运行证明。

## Donor → V5

- canonical/ops/materialize_manager_close_discovery.py::prepare_universe/materialize/recapture_close_minutes → 拟新增V5/vendor/close_discovery_baseline完整owner闭包；候选V5/src/v5_shadow/close_discovery_daily.py只封装当前活动模式。
- canonical/domains/manager_close_discovery.py、manager_close_rebound.py → 原1530观察规则/历史witness，在M17私有baseline只读固定；文件含rebound名称但PHASE=SNAPSHOT_1530_NOT_FINAL_CLOSE，不能当M14 daily超跌完成。
- canonical/domains/manager_catalyst_tracking.py::read_catalyst_events/read_prior_evidence → 原PIT与prior校验、持续跟踪；只通过完整validator的prior可建立lineage。
- canonical/domains/manager_research_evidence.py → 原universe/snapshot attestation，source实际available不等同quote时间。
- canonical/apps/api/v35_api/manager_workbench_router.py → 只读合同对照；V5挂载共享集成请求，不能让M17改M18或其他router。
- canonical/infrastructure/scheduling/manager_close_executor.py → 当前mode与真实窗口合同对照，调度绑定由单一集成者改。
- 已有V5/vendor/manager_plan_baseline/v4/manager_research/workspace_discovery.py及V5/src/v5_shadow/manager_panel_observation.py → 已存在其他投影参考，不是M17生产，禁止跨写。

原1530产物workbench_research/{date}/1530.json及1530.receipt.json；late产物close_recapture.json/receipt/candidates与inputs/close_recapture_pytdx.json分列。V5必须映射到本模块私有root，不默认实际现役路径。完整owner依赖、当前模式和真实首次/后续receipt待Mac核，不因历史文件已找到而宣称全部迁移。

## 已读文件与Git blob

- [handoff/v4-running-source-20261005/canonical/tests/test_manager_close_executor_rework.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_close_executor_rework.py)
  - Git blob SHA：38fa6bbf4200fbbb53599fdb01132b3472970ad5
- [handoff/v4-running-source-20261005/canonical/ops/materialize_manager_close_discovery.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/materialize_manager_close_discovery.py)
  - Git blob SHA：85529d94684e4afd0a6efdebb6d8c4549d1e46f7
- [handoff/v4-running-source-20261005/canonical/domains/manager_close_rebound.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/manager_close_rebound.py)
  - Git blob SHA：1c39affd1bfcf181654c4e9d00e2c501c1d5bfc5
- [handoff/v4-running-source-20261005/canonical/domains/manager_close_discovery.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/manager_close_discovery.py)
  - Git blob SHA：4aae1db0cba7495a3b1997ecfda10146317e977c
- [handoff/v4-running-source-20261005/canonical/domains/manager_catalyst_tracking.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/manager_catalyst_tracking.py)
  - Git blob SHA：cbc1688cc08c48bcfe7dc395d1f00a42442b95ab
- [handoff/v4-running-source-20261005/canonical/tests/test_stage_jobs_manager_close_recapture.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_stage_jobs_manager_close_recapture.py)
  - Git blob SHA：965e45fc21b3f796b249787736567fbf6e200c48
- [handoff/v4-running-source-20261005/canonical/tests/test_manager_materializer_rework.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_materializer_rework.py)
  - Git blob SHA：228b107393c1eb284aaf9717499ab4111755efc9
- [handoff/v4-running-source-20261005/canonical/tests/test_manager_r2_rework.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_r2_rework.py)
  - Git blob SHA：8d88482f13fa0e46b8af07f6e44562b191fa1cf4
- [handoff/v4-running-source-20261005/canonical/tests/test_manager_workbench_research_router.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_workbench_research_router.py)
  - Git blob SHA：c6bcfe8831a03b90abc80f963163cfc9dc0511d3
- [handoff/v4-running-source-20261005/canonical/apps/api/v35_api/manager_workbench_router.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/apps/api/v35_api/manager_workbench_router.py)
  - Git blob SHA：793a8687601d34a042565f14b14b607bf0c46c10
- [handoff/v4-running-source-20261005/canonical/infrastructure/scheduling/manager_close_executor.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/infrastructure/scheduling/manager_close_executor.py)
  - Git blob SHA：943f324e235da0fb146501ad49eae5eaed7b824f
- [handoff/v4-running-source-20261005/canonical/domains/manager_research_evidence.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/manager_research_evidence.py)
  - Git blob SHA：9255d425083e3c3627d4940d7556eed79e3bc00f
- [V5/vendor/manager_plan_baseline/v4/manager_research/workspace_discovery.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/manager_plan_baseline/v4/manager_research/workspace_discovery.py)
  - Git blob SHA：d27203bc60a41534f312907d8f6cd6d5e3628b1f
- [V5/src/v5_shadow/manager_panel_observation.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/manager_panel_observation.py)
  - Git blob SHA：2724a231efdcc91f4db7d9d464edf480a6a89803

Git blob不等于patch SHA256。Chat新候选另交patch及每文件before/after SHA256，遇实际前像不符先明确差异，不整包覆盖。持续跟踪和尾盘接口不从Stage、M14或M16借成功标签。
