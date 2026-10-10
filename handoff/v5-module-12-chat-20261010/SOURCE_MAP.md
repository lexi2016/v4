# M12来源与目标映射

总计划：24c6d60d524f43fcf4209ec8b078ec02cb34417e / V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md，M12/P4。
迁移：d1bf034640ca2e5957423de2745a98e159b69af2 / V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md，M12。
代码：f7cb731c384ee6890a87d16c19a5b5a621779477。固定完整树未有video_fupan_daily.py，以下是原owner源码而非已部署V5服务。

## 映射

- canonical/upstreams/review_core/producer.py::acquire_video → 拟新增M12私有V5/vendor/video_fupan_baseline/review_core闭包；候选video_fupan_daily调用活动原producer。需先核全闭包core/config及工具绑定，不仅拷producer.py。
- canonical/upstreams/review_core/consumer.py::load_v35_video_layer → 本模块只读adapter。它只投影已产证据，不调用discover/capture/ASR/OCR/gap。
- canonical/ops/run_v35_close_review_node.py及_parts → 原node及状态/bridge合同参考。真实根走Review Core，临时fixture走旧producer的分支必须保留区分；不是要求再实现8套独立服务。
- canonical/ops/check_bilibili_fupan.py、capture_bilibili_fupan.py → 原发现/捕获donor与测试对照；是否是活动producer由Mac确认，不能与Review Core并行采集。
- 原收盘时间线、/api/v3/review视频字段、M05/M09下游 → 共享集成请求，本Chat不修改。

原receipt路径runtime_graph/evidence/node_action_status/{date}/{node}.json只作原合同参考；V5不得指回活动V4根。旧_is_reusable只检文件存在；Review Core的media/ASR缓存另核SHA，二者不可混称。

## 本轮已读文件身份

- [handoff/v4-running-source-20261005/canonical/ops/check_bilibili_fupan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/check_bilibili_fupan.py)
  - Git blob SHA：277b3497673a5b99a0797ecb0e9047f8470e1a56
- [handoff/v4-running-source-20261005/canonical/ops/capture_bilibili_fupan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/capture_bilibili_fupan.py)
  - Git blob SHA：ea30dde6167261b2720299b9b2decac951b09d16
- [handoff/v4-running-source-20261005/canonical/ops/run_v35_close_review_node.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/run_v35_close_review_node.py)
  - Git blob SHA：6635895c84d53b81378889d99b27015aa0e38324
- [handoff/v4-running-source-20261005/canonical/ops/_run_v35_close_review_node_parts/fupan_publish.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_run_v35_close_review_node_parts/fupan_publish.py)
  - Git blob SHA：07a2568701904da25a81c7b6b316b52e51ae45ff
- [handoff/v4-running-source-20261005/canonical/tests/test_bilibili_capture.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_bilibili_capture.py)
  - Git blob SHA：9e9ee3731dcd4e722813c19cfa82a347cc9b444b
- [handoff/v4-running-source-20261005/canonical/tests/test_bilibili_fupan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_bilibili_fupan.py)
  - Git blob SHA：330e94a5e3fdc7aa7bf75875f4dab423c90e6926
- [handoff/v4-running-source-20261005/canonical/ops/_run_v35_close_review_node_parts/receipt_io.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_run_v35_close_review_node_parts/receipt_io.py)
  - Git blob SHA：8ac742cd1427e908f4f094c66e23412a81dc3a46
- [handoff/v4-running-source-20261005/canonical/ops/_run_v35_close_review_node_parts/node_cli.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_run_v35_close_review_node_parts/node_cli.py)
  - Git blob SHA：8b035c439fc83814695c1a8cd19ae291ebef241c
- [handoff/v4-running-source-20261005/canonical/ops/_run_v35_close_review_node_parts/source_binding.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_run_v35_close_review_node_parts/source_binding.py)
  - Git blob SHA：d9181be2cecf450cd3ddcad2bbff253708cd4b8b
- [handoff/v4-running-source-20261005/canonical/tests/test_bilibili_stockdict.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_bilibili_stockdict.py)
  - Git blob SHA：e174e64b57fbf3a3846c6658da3892bf2c982300
- [handoff/v4-running-source-20261005/canonical/tests/test_video_gap_audit.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_video_gap_audit.py)
  - Git blob SHA：191725c32b1263a196c85d9100cfa04544a2d5f7
- [handoff/v4-running-source-20261005/canonical/tests/test_video_ocr_alignment.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_video_ocr_alignment.py)
  - Git blob SHA：13c4e39b0ea033b9b8bffef1345e878472efecd2
- [handoff/v4-running-source-20261005/canonical/upstreams/review_core/consumer.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/upstreams/review_core/consumer.py)
  - Git blob SHA：e8a984d968b646820f790f15d5db5756bd79381a
- [handoff/v4-running-source-20261005/canonical/upstreams/review_core/producer.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/upstreams/review_core/producer.py)
  - Git blob SHA：18cabb94c5ceb176341b159de388f8ab6f283118

每项Git blob只能证明固定文件。原tool/网络绑定、完整生产测试、活动时段和完整writer清单仍须Mac补。源码里的默认URL/账号/数据根不是新授权或现役已验证证据。新补丁必须另交SHA256及全部前后文件SHA。
