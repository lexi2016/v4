# M10 HK收盘复盘来源与目标映射

## donor → V5目标

路径简写：`C/` = `handoff/v4-running-source-20261005/canonical/`。以下GitHub路径均相对于`lexi2016/v4`仓库根；固定源码不是Mac活动路径。

- 原算法donor：`9dfa50346357b6dc4b2463a30dcbf3718fce2f03`的`canonical/domains/close_review.py`；F固定副本`V5/vendor/hk_close_baseline/domains/close_review.py::build_native_close_review`已读。现有目标`hk_close_review.py::_assemble`是回放wrapper；新增`hk_close_daily.py`为生产适配（F查询404）。
- 原新日collector已读：`C/ops/collect_hkconnect_close_snapshot.py::collect_close_snapshot`，先验证已有同日snapshot可复用，否则当前日且FINAL_CLOSE_CUTOFF=16:10，依原Connect板块集合取得行情后要求coverage。源码的quantity阈值不能取代M02权威成员/取得时间证据。
- 原producer已读：`C/ops/build_close_review.py::build_close_review`→`CloseSnapshotStore.read_snapshot`→`PreselectionPoolStore.read_pool(trade_date,'hkconnect_d1_top100')`→原模型/七阶段reader→`build_native_close_review`→`ReviewStore.publish_native(expected_sha256=...)`。缺或非法预选原实现标模型来源缺口，不回退旧NativeDataStore/其他日期。
- 原publisher/store部分已列`hk_close_source_manifest`，ops producer/collector不在该manifest内。固定canonical collector/build/store/预选reader与阶段selection原件已附，可直接审查静态依赖并提出收录候选；由统一集成者冻结新来源，不为凑运行复制任意canonical整目录。
- 旧结果reader已读：`review_bridge.py`使用独立`review_readback_baseline`与source manifest，验证payload/receipt/manifest并只读投影；这三个输入必须保持原字节与source identity，不能把它改成执行器或把source_origin_verified提升。
- HK复盘原七阶段是STAGE_0925、STAGE_0930_0935、STAGE_0935_0940、STAGE_0940_0945、STAGE_0945_1030、STAGE_1300_1315、STAGE_1445_1500；Stage8不在此集。缺阶段使用None，空列表仅是声明空，需额外源证才算真空。
- 冻结catalog：workload_id=`hk_connect_close_review`，slot=`1610`，run_policy=`HK_SECURITIES_TRADE_DAY`，session_requirement=`POST_CLOSE`，命令原`ops.build_close_review`；日历与Connect资格不是一个门。
- 关键差异：`hk_close_review.py`的半日12:10是既有回放算术边界；公共`daily_close_plan`明确半日合同未绑定，禁止据前者推导自然采集/调度。保持该限制并报所需原合同。
- 原review API、HK收盘时间线第一项由计划确认，精确现役URL/挂载与A/H envelope交集待Mac核；API/前端由统一集成者单写。旧剩余10项提示页不包含本次新增业务。

## 本轮静态读取的固定文件

- [V5/src/v5_shadow/hk_close_review.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/hk_close_review.py)
  - Git blob：`d6c66f50b0f77b33cb064313ac89090445e9c723`；SHA-256：`70e3b925d6e6bd247ddbbde644cee629a9470d79f7d73c6d9efa347d5aba2668`；本轮只读，未运行。
- [V5/contracts/hk_close_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/hk_close_source_manifest.json)
  - Git blob：`31ace626714fb396845ca52a501c142484ab0939`；SHA-256：`47a42e9206afd971921ebd4817b2a68a5944665fa0303a4b1db1b447888e4ec9`；本轮只读，未运行。
- [V5/vendor/hk_close_baseline/domains/close_review.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/hk_close_baseline/domains/close_review.py)
  - Git blob：`f5714c41e22e50b5e48d2137548a0fe134a24bfa`；SHA-256：`24dd8ee1394844d464b06b2b46053d3551f9a088acede1031b5f18bf8ee997ab`；本轮只读，未运行。
- [V5/tests/test_hk_close_review.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_hk_close_review.py)
  - Git blob：`66e885e1f1109df1b166247816cc8f7ce13fdc0a`；SHA-256：`86b71de4df19e69284bb9d2b9fca3f3c24fb65c7aad4612d9f07e0747f18822a`；本轮只读，未运行。
- [V5/src/v5_shadow/review_bridge.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/review_bridge.py)
  - Git blob：`e8195b5a4fa312c0af4fa6fff1daeee75808dfd2`；SHA-256：`3a73b18beaf876056b5f010a764217be1810ef21c751db1876b5bf95400ff40d`；本轮只读，未运行。
- [V5/src/v5_shadow/daily_close_plan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/daily_close_plan.py)
  - Git blob：`b816802e512a8f22d736716168c515f5ade61ca0`；SHA-256：`f51af9be40a32de88ea55672fffb7b7c74570c9d1ae6053b488b51a4d89bf3f6`；本轮只读，未运行。
- [V5/vendor/daily_schedule_baseline/contracts/runtime_workloads.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/daily_schedule_baseline/contracts/runtime_workloads.json)
  - Git blob：`abdcae3adfcd56b4c33b2752e14c8fffb844f351`；SHA-256：`7389cae30de08cf68c31e5b0bb6f5b17fead403366946496b7a4de148229d0ef`；本轮只读，未运行。
- [handoff/v4-running-source-20261005/canonical/ops/collect_hkconnect_close_snapshot.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/collect_hkconnect_close_snapshot.py)
  - Git blob：`1b329ef71a29ff61330ba2960362aa8e5a89a4b1`；SHA-256：`901905f77532fe61674d2f423b6fab1babc86b3b6f5e3aeb5a34abce91630c76`；本轮只读，未运行。
- [handoff/v4-running-source-20261005/canonical/ops/build_close_review.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/build_close_review.py)
  - Git blob：`6aa059859d27506e9cc4f39e76d7b81dc33855fe`；SHA-256：`6be84fa7462490d17e174d5e4bf77b476afc0ba7a67d60edddd036655683cf26`；本轮只读，未运行。

## 固定计划

- [总计划，固定01—18/P0—P5](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)
- [迁移执行计划，固定证据规则与逐模块退出条件](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)
- [V5代码观察基线](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)：`f7cb731c384ee6890a87d16c19a5b5a621779477`，不是Mac当前字节证明。

本包只给必要定位，不提供完整可运行闭包。活动Mac源/路由/窗口/权限状态须落地前核对；缺原件不得从历史报告补造。
