# M09 A收盘复盘来源与目标映射

## donor → V5目标

路径简写：`C/` = `handoff/v4-running-source-20261005/canonical/`。以下GitHub路径均相对于`lexi2016/v4`仓库根；固定源码不是Mac活动路径。

- 原模型donor：manifest记来源`9dfa50346357b6dc4b2463a30dcbf3718fce2f03`、`canonical/domains/a_share_close_model.py`；F中的`V5/vendor/a_close_baseline/domains/a_share_close_model.py::build_close_model`为已读原件。目标`V5/src/v5_shadow/a_close_review.py::_assemble`只封装原模型，不是原生产者完整替代。
- 原生产路径已读：`C/ops/build_a_share_close_review.py::build_review_from_panel`，读取`panel_pointer`→`build_close_model`→`build_close_review_chain`→`build_a_share_review`→`AShareReviewStore.import_review/replace_review`。这里的调用链由已读caller确认；其未列入a_close manifest的review/chain/store/owned_path固定canonical原件现已附；Chat可以直接据此设计冻结收录候选，不声称已搬迁或部署。
- 原节点与槽参考已读：`C/ops/run_v35_close_review_slot.py`、`C/ops/run_v35_close_review_node.py::run_node`。部分节点属于M12；仅消费其正式产物，不把整份视频节点runner纳入M09写入域。
- 新生产适配`V5/src/v5_shadow/a_close_daily.py`：F查询404，为计划新增点。输出只在A模块私有根，原AShareReviewStore的真实publish/reader目录与活动绑定待Mac核；复用前必须验证完整source closure。
- 冻结`V5/vendor/daily_schedule_baseline/contracts/runtime_workloads.json`中workload_id=`a_share_close_review`，slots=`1605,1710`，run_policy=`A_SHARE_TRADE_DAY`、session_requirement=`POST_CLOSE`、target/signal日期角色BUSINESS_DATE；命令指向原`ops.build_a_share_close_review`。
- `daily_close_plan.py::plan_close_day`同时计划A/H，不能由本Chat编辑；logical_run_key只是同日逻辑键，job_key含slot，run_id=None。半日状态为SCHEDULE_BINDING_UNVERIFIED，不执行也不验证输入。
- 模型capsule只列模型、trading_calendar.py和market_calendar_2026.json；后两者只读冻结。原A市场日历独立于HK/Connect，不因共用+08时区而合并。
- 原review router `/review` 与ReviewView来自迁移计划，完整URL/挂载路径及A/H聚合字段待Mac验证，不猜端口或将HK成品覆盖A字段。

## 本轮静态读取的固定文件

- [V5/src/v5_shadow/a_close_review.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/a_close_review.py)
  - Git blob：`8696f56b59475e73a4432a2b7f0874251ab89bed`；SHA-256：`b288b916f43a41cfc7bd95511ad6decfd537a4cccf64ba5875f13dc04fad1933`；本轮只读，未运行。
- [V5/contracts/a_close_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/a_close_source_manifest.json)
  - Git blob：`71eac2236bd97c202cf887ce341911e603d4d241`；SHA-256：`1b433f3b88f97e21b6ff33d084b9fcdccde5b90a43a220eefbf7a6b8c5a55f27`；本轮只读，未运行。
- [V5/vendor/a_close_baseline/domains/a_share_close_model.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/a_close_baseline/domains/a_share_close_model.py)
  - Git blob：`96e914f73117d162f1ad7c1e4538ce07c23c1afb`；SHA-256：`140d3aabb0f24a55d05d0c624e4563694af050fe2ac02910292fc026d7de7e4a`；本轮只读，未运行。
- [V5/tests/test_a_close_review.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_a_close_review.py)
  - Git blob：`7d02a794ad918fb1cb19f1198281d8b7ee83ad3d`；SHA-256：`fe331baa493299720380d6e8332947aa635b0e52d3b24a2b291bfdd20ca8c1f8`；本轮只读，未运行。
- [V5/src/v5_shadow/daily_close_plan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/daily_close_plan.py)
  - Git blob：`b816802e512a8f22d736716168c515f5ade61ca0`；SHA-256：`f51af9be40a32de88ea55672fffb7b7c74570c9d1ae6053b488b51a4d89bf3f6`；本轮只读，未运行。
- [V5/vendor/daily_schedule_baseline/contracts/runtime_workloads.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/daily_schedule_baseline/contracts/runtime_workloads.json)
  - Git blob：`abdcae3adfcd56b4c33b2752e14c8fffb844f351`；SHA-256：`7389cae30de08cf68c31e5b0bb6f5b17fead403366946496b7a4de148229d0ef`；本轮只读，未运行。
- [V5/tests/test_daily_close_plan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_daily_close_plan.py)
  - Git blob：`4ad9d199b9dcf0020755ae53c2aecbb83b62baff`；SHA-256：`23f0ff9eb5938d96eb46611064d1b74861f14194507c6a7b859562ef67cc9f6e`；本轮只读，未运行。
- [handoff/v4-running-source-20261005/canonical/ops/build_a_share_close_review.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/build_a_share_close_review.py)
  - Git blob：`d8295efa1d082917522d93f3d9396ee154a0926f`；SHA-256：`f3a465e3a79a32241971ce38d95c79767a211e41e40918989fbff8968b703f53`；本轮只读，未运行。
- [handoff/v4-running-source-20261005/canonical/ops/run_v35_close_review_slot.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/run_v35_close_review_slot.py)
  - Git blob：`4535a1a6883cd9ea5aa1d60e1565f5b87f3fa585`；SHA-256：`08f46d928dc70fabf2c1ca49d96b5fa64dc67f113909ed3ce66b81bfcad67ae5`；本轮只读，未运行。
- [handoff/v4-running-source-20261005/canonical/ops/run_v35_close_review_node.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/run_v35_close_review_node.py)
  - Git blob：`6635895c84d53b81378889d99b27015aa0e38324`；SHA-256：`e48e27969d79a1e09f31bdd4be35fb3ade0822ee5e80e43888ceb1abe3bda856`；本轮只读，未运行。

## 固定计划

- [总计划，固定01—18/P0—P5](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)
- [迁移执行计划，固定证据规则与逐模块退出条件](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)
- [V5代码观察基线](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)：`f7cb731c384ee6890a87d16c19a5b5a621779477`，不是Mac当前字节证明。

本包只给必要定位，不提供完整可运行闭包。活动Mac源/路由/窗口/权限状态须落地前核对；缺原件不得从历史报告补造。
