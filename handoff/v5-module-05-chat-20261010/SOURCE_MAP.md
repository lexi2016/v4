# M05 · SOURCE_MAP

固定基线f7cb731c384ee6890a87d16c19a5b5a621779477；完整tree2746项未截断。以下是Git blob SHA，patch另需SHA256。

- [V5/src/v5_shadow/a_preselection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/a_preselection.py)
  - blob 05dd0b28f14bd794890f514e130d8090a1b0438b
- [V5/contracts/a_preselection_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/a_preselection_source_manifest.json)
  - blob 5dffd28c3a176d0d727927878071302ae4093672
- [V5/docs/A_PRESELECTION.md](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/docs/A_PRESELECTION.md)
  - blob 153129b64b9c63929554af6f7c2afa2d4f7b400e
- [V5/tests/test_a_preselection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_a_preselection.py)
  - blob b2f9fcc9fed8085a2c5ce2da39e2bbd26415d038
- [V5/tests/test_a_preselection_platform_utc.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_a_preselection_platform_utc.py)
  - blob 284e983c8563ad3194b8292a16605232bda9904c
- [V5/vendor/a_preselection_baseline/domains/preselection_materializer.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/a_preselection_baseline/domains/preselection_materializer.py)
  - blob d0f2cda536ae243746c59ded5f4012ee01607e71
- [V5/vendor/a_preselection_baseline/domains/_preselection_materializer_parts/hourly_pool.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/a_preselection_baseline/domains/_preselection_materializer_parts/hourly_pool.py)
  - blob 18994639f5c600c1c394307982dd7b6466f71523
- [handoff/v4-running-source-20261005/canonical/ops/materialize_scheduled_preselection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/materialize_scheduled_preselection.py)
  - blob fef8a947cf18eec02ca2e83d97d8a7d1e3dac085
- [handoff/v4-running-source-20261005/canonical/infrastructure/preselection_pool_store.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/infrastructure/preselection_pool_store.py)
  - blob 0e9df7a85177fe031241d8b8743d6a1996d985c7
- [handoff/v4-running-source-20261005/canonical/infrastructure/preselection_pool_transactions.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/infrastructure/preselection_pool_transactions.py)
  - blob 6b8ade94068811f6e46fe2d1233938eb9f4c0da5
- [handoff/v4-running-source-20261005/canonical/domains/preselection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/preselection.py)
  - blob 4fce41432f8fd016cb64882e30d08a03ed920b0d
- [handoff/v4-running-source-20261005/canonical/domains/_preselection_parts/optional_pool_merge.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/_preselection_parts/optional_pool_merge.py)
  - blob e2646b986bcb40fceb03d326cdfcf064085096a6

## 原七来源与六lane/六A产物精确对应
- V192 → kind=v192 → 原build_shared_v192_premarket_pool → a_d1_premarket_pool
- FUPAN → kind=fupan → build_fupan_watchlist_pool → a_d1_fupan_watchlist_pool
- Stage7 → kind=stage7 → build_stage7_review_pool → a_d1_stage7_fenshi_review_pool
- 公众号 → kind=wechat → build_wechat_pool → wechat_public_account_v3_preselect
- 白毛 → kind=baimao → build_baimao_pool/原source → a_share_baimao_research_map
- hourly research与research preview两种来源 → 同一个kind=research → build_hourly_research_pool优先，仅FileNotFoundError时且preview+selector完整SHA绑定才build_research_preview_pool → 单一a_share_research_recommendation_pool
“七来源”不是七并列A产物。原scheduled materializer在CROSS_MARKET时另插HK池，不能把该第七产物算A七池。原聚合/去重在原consumer进行，不能新增跨池排名算法。

## 已读与待扩闭包
a_preselection.py、其40条descriptor、原materializer、hourly_pool、本模块文档已connector读取；scheduled materializer由已核快照读到build/publish。store/transactions/原consumer路径已tree定位，正式保存候选前应读取并核完整writer闭包，不能用reader-only capsule证明可写。
固定descriptor canonical SHA=d0fddbcaa1d5eb22f50edd5d651976b8bc2643122bc951b31733448dea8e23e4；原40件byte sizes/SHA见descriptor，vendor只读。原源码真实来源包含多个固定source_commit，按逐件manifest，不能统一改成一个捏造owner SHA。
a_preselection当前保留V192_CANDIDATE_READY_EMPTY与原validator冲突为LEGACY_EMPTY_STATUS_CONTRACT_MISMATCH，不自动改成VALID_EMPTY。

## 独占范围和共享底座
M05自有a_preselection业务分支、test_a_preselection.py、拟新增V5/src/v5_shadow/a_preselection_daily.py与V5/tests/test_a_preselection_daily.py（f7cb均未有）、本模块文档。
特别注意：a_preselection._guard/_relative/_request/_FrozenLoader/SAFETY等被HK与其他模块复用，属于共享底座，即使文件归M05也不得任意改；跨模块影响修改只交统一集成请求。M06不得同时写此文件。
UI/API/gateway/调度/contract注册及manifest pin、module_artifacts/run_ledger、所有vendor/canonical只读。正式writer闭包注册与发布平台接线通过INTEGRATION_REQUEST统一集成。


## 当前adapter原字节补充
f7cb的a_preselection.py为29,140 bytes，SHA256=e666660830b2f088c51ba00b9fafdefcf966efb798c25a5c21b18ba1c74aa74b，Git blob=05dd0b28f14bd794890f514e130d8090a1b0438b。已重算Git blob并与connector/tree一致。历史89ea56f报告final adapter为ab023e…，不是这个字节版本，本包不转移其29项通过结论。
