# M03 · 固定源码与职责地图

本轮通过GitHub connector读取两份原计划、f7cb完整tree（2746项，truncated=false）及下列源码。S=静态事实，R=既有报告，U=尚未核；不存在Mac部署推断。

固定代码commit：f7cb731c384ee6890a87d16c19a5b5a621779477。以下SHA是Git blob SHA，不是SHA256；Chat交patch时必须另算before/after SHA256。

- [V5/src/v5_shadow/cloud_us_collector.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/cloud_us_collector.py)
  - blob：7647e20aaa7b4cc4f56aa638596c3aea2f3c8b12
- [V5/contracts/cloud_us_collector_sources.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/cloud_us_collector_sources.json)
  - blob：9f0c558326b6cffd2519d1e190b988fecd73a334
- [V5/src/v5_shadow/cloud_transport.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/cloud_transport.py)
  - blob：81964a78093b1afff5a3ac935b6600776961f473
- [V5/tests/test_cloud_us_collector.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_cloud_us_collector.py)
  - blob：8d166f3b0b9d1674ed38ffd3d7a4bec3c6566c2d
- [V5/src/v5_shadow/current_us_research.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/current_us_research.py)
  - blob：1e4483e91551dc08ae5954a8cce2d18842195a19
- [V5/src/v5_shadow/us_mapping_daily.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/us_mapping_daily.py)
  - blob：366190eaeeaf65ed51e5bda5da6c17cd5b5d5f1e
- [handoff/v4-running-source-20261005/canonical/ops/run_us_market_slot.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/run_us_market_slot.py)
  - blob：033663ade7b8436925e12b54d49b4f4f00a4d716
- [handoff/v4-running-source-20261005/canonical/ops/_us_market_digest_parts/session_windows.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_us_market_digest_parts/session_windows.py)
  - blob：5d7c88a81c39dd0076f8375fcb58f663e7c3ffd1
- [handoff/v4-running-source-20261005/canonical/infrastructure/scheduling/_executor_registry_parts/us_digest.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/infrastructure/scheduling/_executor_registry_parts/us_digest.py)
  - blob：4a63572d32ce3e12be34f26aa08d41f85eda4125
- [V5/vendor/us_mapping_baseline/infrastructure/_research_peripheral_store_parts/publish_read.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/infrastructure/_research_peripheral_store_parts/publish_read.py)
  - blob：63a7be703ff1f4e19b8379ab84d3b46b5a194b84
- [V5/vendor/us_mapping_baseline/infrastructure/_research_peripheral_store_parts/session_validation.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/infrastructure/_research_peripheral_store_parts/session_validation.py)
  - blob：48685dc90d51e3aa496348e11a08ac8a89d8af26
- [handoff/v4-running-source-20261005/canonical/apps/api/v35_api/research_lane_router.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/apps/api/v35_api/research_lane_router.py)
  - blob：528782c7018482df6b439db4c8fd4f1f33e7a7cc

## 必须复用与依赖关系
- 原slot：run_us_market_slot → FixedExecutorRegistry._us_market_digest → us_market_digest。只允许0415/0515/2100/2200四个上海slot；是否到期仍按纽约DST与原日历，不能四槽全当生产。
- collector：cloud_us_collector.descriptor/verify/load_owner/main。descriptor PIN=34f45318dd89132a496ac0edf98147455b41d9ea926198d83ce1bd8810c20d8b；48件闭包source_commit=164c010c7eaa1659db9bfed0ff5f123c7a39eefc；每件git_path/bytes/SHA256在descriptor，装配必须按此，不随机复制文件。
- 配套组装工具V5/tools/cloud_preview/assemble_us_collector.py在固定tree存在；本包仅树定位，Chat先读具体实现再使用。test_cloud_us_collector.py静态可见其setUpClass调用此工具。
- ResearchPeripheralStore.publish/read_exact负责原payload/receipt/manifest一致性；vendor中reader闭包供只读复用，原reader锁必须隔离。保留原旧receipt精确兼容，不能任意忽略字段。
- current_us_research.run_current_research明确校验三条精确路径，使用真实当前时钟，随后调用M15/M18；是消费者参考，不是M03可改目标。
- provider transport需现有网络能力和已有配置；本包不申请新凭据/权限，不保证未来provider可用。

## 独占写入白名单
现有：V5/src/v5_shadow/cloud_us_collector.py及V5/tests/test_cloud_us_collector.py，仅确认确需改时最小修改。
拟新增（f7cb树未有）：V5/src/v5_shadow/us_source_daily.py、V5/tests/test_us_source_daily.py；M03私有文档目录可新增。若共享函数有缺陷，向统一集成者请求，不把白名单自动扩大。

## 共享只读/变更请求
cloud_transport.py、composition.py、contracts.py、各contracts注册及pin、module_artifacts.py、run_ledger.py、daily_*共享调度、api_gateway.py、module_api.py、UI、所有M15/M18业务文件与原vendor。需要时交INTEGRATION_REQUEST：target path + before SHA + requested interface + exact acceptance + owner；统一集成。

