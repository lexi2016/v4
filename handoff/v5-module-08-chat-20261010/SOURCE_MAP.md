# M08 HK阶段选股来源与目标映射

## donor → V5目标

路径简写：`C/` = `handoff/v4-running-source-20261005/canonical/`。以下GitHub路径均相对于`lexi2016/v4`仓库根；固定源码不是Mac活动路径。

- 原donor来源`9dfa50346357b6dc4b2463a30dcbf3718fce2f03`，canonical `stage_center/selection.py`与`_selection_parts/hk_four_lanes.py`；F固定副本在`V5/vendor/stage_selection_baseline/`。manifest给逐文件原路径、字节与SHA，不等于Mac现役证明。
- 已读普通路径：`selection.py::merge_hk_four_lane_candidates`、`select_hk_four_lane`→`hk_four_lanes.py`；现有目标`stage_selection.py::_assemble`的HK_CONNECT分支。原`hk_four_lane_score`仍保留；其具体formula body按manifest原件复用，不由本任务重写。
- 竞价入口声明`select_hk_0925_second_filter`→`hk_auction_filter`，`select_hk_0925_d1_reference`→`hk_auction_reference`；这两body以及SelectionStore publication/verification固定canonical原件已附，尚未列V5 stage manifest。Chat可继续静态编码与闭包方案，冻结收录由统一集成者单写；活动接口与窗口部署前核。
- 新生产适配目标`V5/src/v5_shadow/hk_stage_daily.py`：F查询404，只是总计划指定新增点，不宣称现有服务。现有普通wrapper不允许直接用Stage8 ID。
- 执行参考：已读`C/ops/run_stage_center_tick.py`、`C/ops/_run_stage_center_nodes_parts/stage_dispatch.py`；历史恢复授权、锁、receipt机制不可擅自移除，但活动绑定/Stage8调用与真实根仍U。
- 已读固定`stage_center/contracts.py`：共享STAGE_0925对HK的window为09:15–09:20，其stage cutoff字段09:25:05；这些旧字段不能合并解释为已证现役竞价时刻。`STAGE_1545_1555`只属于HK；原半日合同另核。
- 依赖M02→M06→M08→M10，M04时点内材料只读。M10需要的七阶段是STAGE_0925、0930_0935、0935_0940、0940_0945、0945_1030、1300_1315、1445_1500，均带STAGE_前缀；Stage8独立。
- 原HK阶段页/经理阶段航迹已由计划指出，精确活动HTTP路由、参数和按钮矩阵U，不能编造URL。

## 本轮静态读取的固定文件

- [V5/src/v5_shadow/stage_selection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/stage_selection.py)
  - Git blob：`4f371cce798b512f17c36b70bcc3bce413a3ae06`；SHA-256：`7c65602ac642a92cfda17dde9f1d2eb38e7a2db92f55974f37645178c4c60a8c`；本轮只读，未运行。
- [V5/contracts/stage_selection_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/stage_selection_source_manifest.json)
  - Git blob：`ef6645352e3afa8743bad9e6bbbac78e2324a7a8`；SHA-256：`1cc54a2b9efcd1756501007469206503a49b98acaa7495860f567999ab4d0a37`；本轮只读，未运行。
- [V5/vendor/stage_selection_baseline/stage_center/selection.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/stage_selection_baseline/stage_center/selection.py)
  - Git blob：`e5bb693578a32f954355f53fe9b79e1d592e8422`；SHA-256：`ccf7dddfb72fe88b5bff68ce9501e0a8ef9f41a212008a495824017943675294`；本轮只读，未运行。
- [V5/vendor/stage_selection_baseline/stage_center/_selection_parts/hk_four_lanes.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/stage_selection_baseline/stage_center/_selection_parts/hk_four_lanes.py)
  - Git blob：`1c462d4ac2925bb5d77f7a8199735a3567205a8b`；SHA-256：`d44cd657b15b806922dd99317cfe759849a0d59884a0e39a533f0204f530ae71`；本轮只读，未运行。
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
