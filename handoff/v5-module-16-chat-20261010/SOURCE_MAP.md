# M16来源和目标

原总计划24c6d60d524f43fcf4209ec8b078ec02cb34417e / V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md：M16/P4。
迁移d1bf034640ca2e5957423de2745a98e159b69af2 / V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md：M16（旧盘点17）。
代码固定f7cb731c384ee6890a87d16c19a5b5a621779477，完整递归树未有V5 manager_jobs.py或manager_plan_baseline/service.py。不要把旧文档的概括当源码存在证明。

## Donor → V5

- canonical/v4/manager_research/service.py::ManagerResearchJobService → 拟新增V5/vendor/manager_jobs_baseline/v4/manager_research/service.py及完整原依赖；候选V5/src/v5_shadow/manager_jobs.py只封装公开资料任务职责。
- canonical/v4/manager_research/store.py → M16私有baseline store；V5/vendor/manager_plan_baseline/v4/manager_research/store.py已有同blob c9af9a6ae87858ebee111766d4db0fd0639943b5，仅可只读对照，不能本Chat修改共享冻结闭包。
- 原ManagerResearchStore jobs/products/receipts、commit_result → M16独占runtime根。构造ensure_directory有写副作用，读server不能随GET临时初始化写store。
- canonical/apps/api/v35_api/manager_research_router.py → 仅M16路由接口请求；同文件M13/M18路由禁止带入模块补丁。
- canonical/apps/web/src/views/ManagerSelectionView.vue → 共享前端明确操作/取消轮询/取消job修正请求；本Chat不写。

## 已读固定文件

- [handoff/v4-running-source-20261005/canonical/v4/manager_research/service.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/v4/manager_research/service.py)
  - Git blob SHA：8c7cc0357aa9c203fe088edb1fd88900290c9aec
- [handoff/v4-running-source-20261005/canonical/v4/manager_research/store.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/v4/manager_research/store.py)
  - Git blob SHA：c9af9a6ae87858ebee111766d4db0fd0639943b5
- [handoff/v4-running-source-20261005/canonical/apps/api/v35_api/manager_research_router.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/apps/api/v35_api/manager_research_router.py)
  - Git blob SHA：1e89a2b2cdc9c6192eed188ac53d8b4027aa77be
- [handoff/v4-running-source-20261005/canonical/tests/test_manager_research_service.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_research_service.py)
  - Git blob SHA：197a973183307fc62d4fcd62869a0d77e8b42453
- [handoff/v4-running-source-20261005/canonical/tests/test_manager_research_router_contract.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_research_router_contract.py)
  - Git blob SHA：f7632fa8db60ec09b6b8c2388f9c4c781669c8e2
- [handoff/v4-running-source-20261005/canonical/tests/test_manager_research_catalyst_service.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_research_catalyst_service.py)
  - Git blob SHA：48a9250a14b18532bd9b266bb794cd72ceb0749e
- [handoff/v4-running-source-20261005/canonical/tests/test_manager_research_decision_recovery_contract.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_research_decision_recovery_contract.py)
  - Git blob SHA：252a3bd0553214f4d3c0004ae64ab9fee1191295
- [handoff/v4-running-source-20261005/canonical/tests/test_manager_lifecycle_hardening.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_lifecycle_hardening.py)
  - Git blob SHA：f435ac2ee102ef96c7c61b45dbf24e153cbc80a7
- [handoff/v4-running-source-20261005/canonical/tests/test_manager_contract_hardening.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_manager_contract_hardening.py)
  - Git blob SHA：95831122d073fce36067fcf9928a42791a4743a4
- [handoff/v4-running-source-20261005/canonical/tests/optimization/test_manager_transactions.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/optimization/test_manager_transactions.py)
  - Git blob SHA：e915b05e9af6a02157858f5b8571997365d44504
- [handoff/v4-running-source-20261005/canonical/apps/web/src/views/ManagerSelectionView.vue](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/apps/web/src/views/ManagerSelectionView.vue)
  - Git blob SHA：75b848172dd2a3fbc00b44dfb720759867209e42

上述blob为文件身份，非活动Mac匹配。原service含大量其他模块方法不能全量暴露；实际provider/队列/version需Mac确认。本包不提供虚构补丁SHA，Chat交付时必须对新patch和before/after逐项算SHA256。
