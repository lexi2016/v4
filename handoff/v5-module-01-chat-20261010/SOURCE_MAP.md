# M01 · SOURCE_MAP

固定commit：f7cb731c384ee6890a87d16c19a5b5a621779477。GitHub完整tree已核2746项，未截断。下面SHA是Git blob SHA；补丁另需SHA256。

- [handoff/v4-running-source-20261005/canonical/ops/a_share_daily_sync.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/a_share_daily_sync.py)
  - blob 37cef8f6ab20e0a4061c1a5f5f4581ac19203876
- [handoff/v4-running-source-20261005/canonical/ops/macos_research_panel_daily.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/macos_research_panel_daily.py)
  - blob b9717c8a28a13b727658aee98cb12bc0ff5500cd
- [handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/a_market_capture.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/a_market_capture.py)
  - blob b9ca6a9eee63890fb3e08c78f624f76cbea6d9e7
- [handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/a_formula_execution.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/a_formula_execution.py)
  - blob dc8b3d50f7b41cc2470cbe519612ea1753b1101d
- [handoff/v4-running-source-20261005/canonical/ops/a_formula_input_manifest.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/a_formula_input_manifest.py)
  - blob 3addc924e0f637655a21b6406d5ff4142c2368f3
- [handoff/v4-running-source-20261005/canonical/ops/a_formula_increment.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/a_formula_increment.py)
  - blob 8b6162ddcd9e6539d0bae5390915ee228b151e32
- [V5/src/v5_shadow/input_snapshot.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/input_snapshot.py)
  - blob 3c56fe99b9d79e51cae24378db3b0afa458e4696
- [V5/src/v5_shadow/snapshot_recording.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/snapshot_recording.py)
  - blob 9865203da95d7c3f280ee70ba1cedb9a2a655d51
- [V5/src/v5_shadow/provider_evidence.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/provider_evidence.py)
  - blob 5d72d3b2d54c0449576e46e7eba7be4fbc7884d6

## 复用链与读取深度
- a_share_daily_sync.py::run_sync及其本地历史/字段/目标集/预算门禁已静态定位；不要复制其下载循环新建producer。
- macos_research_panel_daily.py::run_windows_a_sync_authority、run_windows_a_formula_authority、run_v4_a_formula_offline、run_scheduled_lanes为原入口；该文件由已有已核源码快照读取并与固定tree blob对照。
- a_market_capture.py提供原pytdx采集与VIPDOC接续；a_formula_execution.py含run_v4_a_live_generation流程、已有generation复用、sync receipt→input manifest→offline formula→read_formula_generation。已读取parts，不把入口壳当全部闭包。
- a_formula_input_manifest.py与a_formula_increment.py已树定位，未在本包深入函数实现；Chat实施前读取并沿imports核完整闭包。parts的_namespace不能凭空补写，按原manifest/正式闭包找齐。
- input_snapshot.snapshot_digest/verify_snapshot只校验快照，不采集。snapshot_recording.SnapshotRecorder记录已有Futu快照调用，不额外发调用；provider_evidence是HK SDK规范化。它们不是A采集器，不强套HK主表合同到A源。
- 原A universe、日线/VIPDOC、xdxr、公式参数/种子/合同CSV、source pointer和原依赖必须分别固定；实际Windows authority脚本绑定/可用性U，不能假定有第二台可控机器或绕过既有Mac路径。

## 写入边界
拟新增（固定tree未有）：V5/src/v5_shadow/a_source_daily.py、V5/tests/test_a_source_daily.py、本模块文档/私有测试fixture。仅薄封装原owner，不重写同步/公式。
共享input_snapshot.py、snapshot_recording.py、provider_evidence.py、contracts.py、composition.py、module_artifacts.py、API/gateway/调度/registry/所有UI只读；必要修改交统一集成者。所有canonical/原V4/vendor为只读donor。M05池、M09复盘、M02 HK不在本Chat写入范围。

