# M02 · SOURCE_MAP

代码基线f7cb731c384ee6890a87d16c19a5b5a621779477；完整tree2746项未截断，以下为Git blob SHA，不是SHA256。

- [handoff/v4-running-source-20261005/canonical/ops/macos_research_panel_daily.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/macos_research_panel_daily.py)
  - blob b9717c8a28a13b727658aee98cb12bc0ff5500cd
- [handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/hk_market_capture.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/hk_market_capture.py)
  - blob 41abd49f836ab0e118b1eec3c68001e9915c415b
- [handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/hk_capture_gate.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_macos_research_panel_daily_parts/hk_capture_gate.py)
  - blob 57fa7f9dcd5ee6485c70c757add8c40f11344ca4
- [handoff/v4-running-source-20261005/canonical/ops/collect_hkconnect_close_snapshot.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/collect_hkconnect_close_snapshot.py)
  - blob 1b329ef71a29ff61330ba2960362aa8e5a89a4b1
- [V5/src/v5_shadow/capture_master.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/capture_master.py)
  - blob b43d7e0ebeae50f31378be9e5d4e158b9cb92964
- [V5/src/v5_shadow/provider_evidence.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/provider_evidence.py)
  - blob 5d72d3b2d54c0449576e46e7eba7be4fbc7884d6
- [V5/src/v5_shadow/snapshot_recording.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/snapshot_recording.py)
  - blob 9865203da95d7c3f280ee70ba1cedb9a2a655d51
- [V5/src/v5_shadow/membership_reader.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/membership_reader.py)
  - blob bb6c9421a50d034e99476f41dfe690c8f5625e92
- [V5/src/v5_shadow/native_identity_reader.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/native_identity_reader.py)
  - blob be5efc73262dfd89c3c38ed2aff60f970fe6790e
- [V5/src/v5_shadow/hk_membership_recovery.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/hk_membership_recovery.py)
  - blob 9ac4edb45b73b950ca4fd52b62350970d9e5cb23
- [V5/contracts/security_master_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/security_master_source_manifest.json)
  - blob 60edf94fa5dd25a9504becac3e0b8be90deee2bb
- [V5/contracts/hk_membership_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/hk_membership_source_manifest.json)
  - blob 4d80d4d7ac3a22d8320657cd738514c4206f35c3
- [V5/contracts/hk_preselection_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/hk_preselection_source_manifest.json)
  - blob 189d5258d2d20529641ae8f51d01c9d976851a3c

## 原owner与现有适配
- macos_research_panel_daily.collect_hk_futu_rows/run_hk_0_2_authority为原行情/面板authority入口；hk_market_capture保留SDK原始响应、plate集合、capture manifest，hk_capture_gate核run/SHA、主表/资格和panel authority。原run_hk_0_2_authority要求READY且through_date匹配，不能删后置校验。
- collect_hkconnect_close_snapshot.collect_close_snapshot输出close snapshot，不等于证券主表或目标日资格。
- capture_master.prepare_futu_master/publish_futu_master/read_futu_master：已静态读。只作operator-bound Futu reference replay，无acquisition、membership publication或调度。MasterBinding含root/trade_date/cutoff/codes/membership_source_sha256/producer_code_sha256/raw_records_sha256/snapshot_receipt_sha256；prepared值为进程内能力，JSON不是授权。
- snapshot_recording.SnapshotRecorder只包已有get_market_snapshot兼容调用，不添调用/重试；provider_evidence保留SDK原值与业务规范化分离，stock_owner不是股东关系。两者为共享工具。
- hk_membership_recovery.run_recovery：保留SDK回执的私有恢复，明确不调用OpenD；固定owner验证后输出七文件，available_at为真实恢复取得时间，不回填PIT。
- membership_reader.read_private：精确七文件。六引用来自artifact_ref/manifest_ref/receipt_ref/current_ref/capture_ref/publication_ref，第七为capture同目录sdk.capture.json；核原owner、目标日、SDK SHA与精确集合。
- native_identity_reader.read_private：复用hk_preselection固定reader，绝不从名称推issuer identity；依赖manager_plan._snapshot为只读消费者边界，不能为本模块改经理。
- security_master/hk_membership/hk_preselection三个source_manifest分别约束闭包，不互相替代。security_master、membership descriptor本包树定位；hk_preselection descriptor和入口已读取，Chat应用前核全manifest及每件原字节。

## 唯一写入白名单
现有M02文件：capture_master.py、membership_reader.py、native_identity_reader.py、hk_membership_recovery.py及其定向测试，只在实际缺口命中时最小改。
拟新增（f7cb未有）：V5/src/v5_shadow/hk_source_daily.py、V5/tests/test_hk_source_daily.py、本模块文档。所有数据为模块私有输出。
共享snapshot_recording.py/provider_evidence.py/a_preselection.py/hk_preselection.py/composition.py/contracts.py、manifest/注册/pin、UI/gateway/API/调度/manager_plan均只提变更请求；M06/M14业务不得修改。原vendor/canonical只读复用，不直接改原V4。

