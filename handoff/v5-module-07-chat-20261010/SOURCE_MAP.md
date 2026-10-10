# M07 A阶段选股来源与目标映射

## donor → V5目标

路径简写：`C/` = `handoff/v4-running-source-20261005/canonical/`。以下GitHub路径均相对于`lexi2016/v4`仓库根；固定源码不是Mac活动路径。

- V4 donor定位：manifest中来源commit为`9dfa50346357b6dc4b2463a30dcbf3718fce2f03`，原路径`handoff/v4-running-source-20261005/canonical/stage_center/selection.py`及`stage_center/_selection_parts/a_live.py`。F内固定副本在`V5/vendor/stage_selection_baseline/`；不能把canonical文件直接覆盖V5 wrapper。
- 已读原普通算法：`selection.py::select_a_live_stage`→`a_live.py::_select_a_live_stage_body`；现有目标`V5/src/v5_shadow/stage_selection.py::_assemble`的A_SHARE分支。新增生产适配目标是`a_stage_daily.py`（F返回404，计划新增），共享wrapper只可请求函数级A分支差异。
- 已读原竞价声明：`selection.py::select_a_0925_auction`导入`stage_center._selection_parts.a_auction`；该body及store publication/verification固定canonical原件已附源码包，仍未列当前V5 manifest。Chat可直接提出原件冻结/收录的最小候选，由统一集成者单写manifest；Mac只负责部署前核活动版本/绑定，不需用户再找相同原件。
- 现有`SelectionStore.publish`/`publish_selection`声明依赖`store_publication`，未列当前stage manifest；实际writer、root、manifest/receipt必须从活动合同核，不能借V4根试写。
- 已读历史执行入口：`C/ops/run_stage_center_tick.py`（包括`deadline_chain_check`、`resolve_runtime_roots`、`_calendar_gate`）与`C/ops/_run_stage_center_nodes_parts/stage_dispatch.py`。只作现役绑定核对起点；不把历史runner整份搬到新调度。
- 依赖：M05→M07→M09，M01/M04只读输入；普通API/原页面精确路由U，由统一集成者实测登记。

## 已核固定窗口限制

`stage_center/contracts.py`定义共享STAGE_0925，A的window为09:20–09:25、HK另有09:15–09:20；cutoff字段09:25:05不能证明Mac现役采集/触发合同。普通阶段包括09:30–09:35、09:35–09:40、09:40–09:45、09:45–10:30、13:00–13:15、14:45–15:00。15:45–15:55仅HK。这里只陈述固定源码，实际时段均须核当前owner；不据此新造竞价、尾盘或半日合同。

## 本轮静态读取的固定文件

- [V5/src/v5_shadow/stage_selection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/stage_selection.py)
  - Git blob：`4f371cce798b512f17c36b70bcc3bce413a3ae06`；SHA-256：`7c65602ac642a92cfda17dde9f1d2eb38e7a2db92f55974f37645178c4c60a8c`；本轮只读，未运行。
- [V5/contracts/stage_selection_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/stage_selection_source_manifest.json)
  - Git blob：`ef6645352e3afa8743bad9e6bbbac78e2324a7a8`；SHA-256：`1cc54a2b9efcd1756501007469206503a49b98acaa7495860f567999ab4d0a37`；本轮只读，未运行。
- [V5/vendor/stage_selection_baseline/stage_center/selection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/stage_selection_baseline/stage_center/selection.py)
  - Git blob：`e5bb693578a32f954355f53fe9b79e1d592e8422`；SHA-256：`ccf7dddfb72fe88b5bff68ce9501e0a8ef9f41a212008a495824017943675294`；本轮只读，未运行。
- [V5/vendor/stage_selection_baseline/stage_center/_selection_parts/a_live.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/stage_selection_baseline/stage_center/_selection_parts/a_live.py)
  - Git blob：`ca1f1b6d95d9d2b76591b77d372e7415fe2c5ce7`；SHA-256：`b7faa3286df4f0312075c7a4563d3f4deed463d3f10ab2c4902967e8d5d7781d`；本轮只读，未运行。
- [V5/vendor/stage_selection_baseline/stage_center/contracts.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/stage_selection_baseline/stage_center/contracts.py)
  - Git blob：`3c08626f76e43f3534ba8edc2785e7da8fbc2292`；SHA-256：`6880f6a82c7f4fb0fde5c0661bd5a8bb12b590661a4b8552bcb3d6be969ae83d`；本轮只读，未运行。
- [V5/tests/test_stage_selection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_stage_selection.py)
  - Git blob：`8368fae537b76dec4fba0f83206f11bb94386bcd`；SHA-256：`6cb3b183451d96cd5c8f4e9bed54ddaf7ff4e3722d6a65be0d94a3b37b0507df`；本轮只读，未运行。
- [handoff/v4-running-source-20261005/canonical/ops/run_stage_center_tick.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/run_stage_center_tick.py)
  - Git blob：`95f6d00fb2b6508683fd308e2d8b188d7dc60574`；SHA-256：`53def88447abd77574d71a9edb4fb6d264480446c3568c897a297cc10b537edd`；本轮只读，未运行。
- [handoff/v4-running-source-20261005/canonical/ops/_run_stage_center_nodes_parts/stage_dispatch.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/_run_stage_center_nodes_parts/stage_dispatch.py)
  - Git blob：`44044ccdbe71c44a8c05163d209410a656f1bae8`；SHA-256：`06548184a4b09b0ae94053f2308eefb3bf5c31afc9f04abaeb805db7cebe8adb`；本轮只读，未运行。

## 固定计划

- [总计划，固定01—18/P0—P5](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)
- [迁移执行计划，固定证据规则与逐模块退出条件](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)
- [V5代码观察基线](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)：`f7cb731c384ee6890a87d16c19a5b5a621779477`，不是Mac当前字节证明。

本包只给必要定位，不提供完整可运行闭包。活动Mac源/路由/窗口/权限状态须落地前核对；缺原件不得从历史报告补造。
