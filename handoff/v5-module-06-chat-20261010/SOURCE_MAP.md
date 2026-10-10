# M06 · SOURCE_MAP

代码基线f7cb731c384ee6890a87d16c19a5b5a621779477；2746项tree未截断。以下为Git blob SHA，候选另交SHA256前后像。

- [V5/src/v5_shadow/hk_preselection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/hk_preselection.py)
  - blob b6bcce7e4fadddf7b3faf06a5cdf07d05c322f70
- [V5/src/v5_shadow/a_preselection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/a_preselection.py)
  - blob 05dd0b28f14bd794890f514e130d8090a1b0438b
- [V5/contracts/hk_preselection_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/hk_preselection_source_manifest.json)
  - blob 189d5258d2d20529641ae8f51d01c9d976851a3c
- [V5/tests/test_hk_preselection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_hk_preselection.py)
  - blob a43a1103be6051c4fe943067441d41ee0b5e8b2e
- [V5/vendor/hk_preselection_baseline/upstreams/v3_shared_data/shared_data/hk_0_2.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/hk_preselection_baseline/upstreams/v3_shared_data/shared_data/hk_0_2.py)
  - blob b2b366c2cbfd89ba9fed437620057fdb01f1e561
- [V5/vendor/hk_preselection_baseline/domains/preselection_materializer.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/hk_preselection_baseline/domains/preselection_materializer.py)
  - blob d0f2cda536ae243746c59ded5f4012ee01607e71
- [handoff/v4-running-source-20261005/canonical/upstreams/v3_shared_data/scripts/materialize_hk_0_2.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/upstreams/v3_shared_data/scripts/materialize_hk_0_2.py)
  - blob 5792171e414fc22b5e0788380b65c8da50b2c779
- [handoff/v4-running-source-20261005/canonical/upstreams/v3_shared_data/shared_data/hk_0_2.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/upstreams/v3_shared_data/shared_data/hk_0_2.py)
  - blob b2b366c2cbfd89ba9fed437620057fdb01f1e561
- [handoff/v4-running-source-20261005/canonical/ops/materialize_scheduled_preselection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/materialize_scheduled_preselection.py)
  - blob fef8a947cf18eec02ca2e83d97d8a7d1e3dac085

## 原生产者和reader不混同
- 原materialize_hk_0_2.py：先read_verified_hk_0_2_pool尝试精确已存在结果；明确给asset_root时调用materialize_frozen_hk_0_2。restore-source-root是一次性精确迁移，不是线上fallback；不能拿另一日旧池替代。
- 原shared_data.hk_0_2.materialize_frozen_hk_0_2 → load_frozen_hk_0_2_assets → 原预测/Top100排序 → publish_hk_0_2_rows → read_verified_hk_0_2_pool。源码同时保存panel/model assets、model manifest和models.joblib真实校验，不是只读manifest里的SHA字段。
- V5 hk_preselection.run_hk_preselection/_assemble调用build_shared_hk_0_2_pool，后者是原pool reader的严格投影。它不读source panel/模型权重、不调用SDK、不生产新日Top100，model_weights_reverified固定false。
- _verify_pool核receipt/verification READY、temporal_cutoff_safe、100行、master成员、score_prob_active有限且[0,1]、三日期及captured/finished<=cutoff。
- 原hk master按eligibility_source_date读；HK信号日按hk_securities前一session，独立报告Connect状态。输入支持的data_kind仅SYNTHETIC/RECORDED_INPUT_REPLAY，不能把自然producer塞进reader旧合同后改标签。
- 现34件hk_preselection descriptor canonical SHA=11c3af79592e15a5b9aa400fee57f14c415ef06ea3e2a8a25ba6a43f074d73cb，逐件owner来源见manifest；新生产闭包需要按原依赖补齐并交注册请求，现有reader capsule不证明新generator闭包可运行。

## 写入边界
仅hk_preselection.py本模块逻辑/test_hk_preselection.py，拟新增V5/src/v5_shadow/hk_preselection_daily.py及V5/tests/test_hk_preselection_daily.py（f7cb未有），本模块文档。
a_preselection.py为共享guard/loader依赖，禁止M06修改；已修kind/paths不重做。M02源/主表/资格、M08阶段、UI/API/gateway/调度/contract注册及manifest pin、module_artifacts/run_ledger、原vendor均只读，改动交统一集成者。

