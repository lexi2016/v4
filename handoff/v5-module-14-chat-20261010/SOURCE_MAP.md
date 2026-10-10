# M14固定来源与精确迁移边界
F=f7cb731c384ee6890a87d16c19a5b5a621779477；R=40084ee76acf1c43b2d8768d538d7c91052437dd；D=d659ff0dbcc00aa1944908cfc8b44443642ea171；S=2d8e38ec61792b3e75581f96318e9c284f72b7ba。以下仅S静态读取事实。Git blob SHA不等于SHA256，候选包必须另外计算前后SHA256。

## 已核目标/参考
- [V5/src/v5_shadow/rebound_panel_repair.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/rebound_panel_repair.py)
  - Git blob: af95f98728ad0d83ff4b02f14446ee922120ff3b
  - 已读_same_code 60—97、_verify_owner100—146、_align_repair_trade_dates263—313、prepare_internal_gap_repair316—423。前像/原owner/独立authority/原行保护；不重写已修identity/date兼容。
- [V5/src/v5_shadow/rebound_raw_repair.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/rebound_raw_repair.py)
  - Git blob: 48ef3957e8287320ae454c6bcc35bfb1bbd960d6
  - 已取固定源及函数索引：decode_raw_repair 161起、_record123起。真实原decoder和raw request/capture绑定，执行者需读具体函数再改；非授权新采集入口。
- [V5/vendor/rebound_baseline/v4/manager_research/workspace_plan.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/rebound_baseline/v4/manager_research/workspace_plan.py)
  - Git blob: 10abaf491648f20b3618fbf3404c440a7ca77dc7
  - 已读主两门827—985、窗口622—669及输出字段定位。主价格float比较935—936；与manager vendor不同源。Decimal迁移目标要跟实际caller核。
- [V5/vendor/manager_plan_baseline/v4/manager_research/workspace_plan.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/manager_plan_baseline/v4/manager_research/workspace_plan.py)
  - Git blob: 25bdc2c417f28307a4bdd3a05e868ac2285b25c2
  - 已核主screen975起和1264附近：价格float，量能另有volume_proven/Decimal。M18 owner文件，仅提交集成请求，不由M14跨模块覆盖。
- [V5/src/v5_shadow/rebound_owner.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/rebound_owner.py)
  - Git blob: dcf876d677d6cc2434fc41636afc99201af12436
  - 已读research_projection322—352、_calculate355—397、_validate_artifact490—543、manager_projection546—562。明确eligible_screen=None，Python>=3.14与依赖匹配，不可换标签放行。
- [V5/src/v5_shadow/rebound_observation.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/rebound_observation.py)
  - Git blob: 2aa58b2283423aaf105a47e637258172069e51c2
  - 已读_capsule73—89、extract_calculator92—141，AST提取行号与hash/spans强绑定；变更源行必须同步准确合同，不绕过断言。
- [V5/src/v5_shadow/legacy_adapter.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/legacy_adapter.py)
  - Git blob: 592e948208d7821b8ff838a1b126d68bf355f098
  - 已读build_shadow_result和run_legacy_screen核心：OWNER_VERIFIED显式OWNER_INPUT_STABILITY_UNVERIFIED；完整分组coverage才有COMPLETED/VALID_EMPTY算术状态，仍不证明来源授权。
- [V5/src/v5_shadow/worker.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/worker.py)
  - Git blob: 70d71f33afd983a1ed6829233ec395055809b7f3
  - 已取固定源及install_python_guards/worker_main索引；原隔离入口与不可写/网络边界，执行者变更前需完整核验。
- [V5/src/v5_shadow/daily_rebound_owner.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/daily_rebound_owner.py)
  - Git blob: 32cdd698084c7e00ef5a287d0e0ef0d8db9e7de1
  - 已全文读，固定S checkout，检HEAD/PIN及ignored/untracked，导入独立rebound_daily并独立read_rebound_observation。F无同名daily文件。共享调度桥只提交统一集成。
- [V5/src/v5_shadow/rebound_daily.py @ 2d8e38ec](https://github.com/lexi2016/v4/blob/2d8e38ec61792b3e75581f96318e9c284f72b7ba/V5/src/v5_shadow/rebound_daily.py)
  - Git blob: aecadc34fd1cec0eecd4a0f9bb317528fd955ade
  - 已全文读。按request/code/dependency身份幂等numeric observation、inflight需exact reconciliation；selection_status=CANNOT_CONFIRM和scheduler_installed=False。不是已实现正式准入。
- [V5/contracts/rebound_source_manifest.json @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/rebound_source_manifest.json)
  - Git blob: d38cc667ee0d09d6ea2c2566a061c8bd91565a3d
  - 已取descriptor并核source owner SHA和闭包声明；静态验证不等于runtime通过。
- [V5/contracts/rebound_owner_capsule.json @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/rebound_owner_capsule.json)
  - Git blob: cea456a73f7ba20ff0c7ccb6a20027e4602c3242
  - 已取descriptor并核source pin；与rebound_owner.PIN整体绑定。
- [V5/contracts/rebound_observation_capsule.json @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/rebound_observation_capsule.json)
  - Git blob: 9e81b4d95fb9fc52a3953a453e09bd2548c7d85a
  - 已取descriptor并核source SHA、extracted_spans、structural_boundaries；与observation.PIN绑定。
- [V5/contracts/rebound_repair_source_manifest.json @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/rebound_repair_source_manifest.json)
  - Git blob: 836f437a516fa1528d44074d86f7c4786cbd97a5
  - 已读；原74478a0e hk_daily_supplement的_finite/_bar_date/_decode_bar不变AST提取，不新增collector。
- [V5/tests/test_rebound_date_compat.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_rebound_date_compat.py)
  - Git blob: 75a56f0fa39c5cc1cb90dd299e8c3569be92835d
  - 已全文读；整数/字符串/非法表示及private publish测试；明确SYNTHETIC，部分测试mock _verify_owner，不可替代真实身份验收。
- [V5/tests/test_rebound_owner_identity.py @ f7cb731c](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests/test_rebound_owner_identity.py)
  - Git blob: c627e6ffadd34b4de0ee3a3ff6ce27edec8b0b7d
  - 已读测试清单及身份设计；18字段、嵌套代码、helper、global、literal/native布局篡改覆盖，本轮未运行。
- [V5/src/v5_shadow/rebound_panel_repair.py @ ebe5944e](https://github.com/lexi2016/v4/blob/ebe5944ecfbec2f6a161793d7c11946dea063e57/V5/src/v5_shadow/rebound_panel_repair.py)
  - Git blob: 058206eca6e0272748d79897d1203a05d5257efb
  - 已取历史源及函数索引。旧_verify_owner从60起，不能以旧误拒绝覆盖F已修_same_code。仅作来源对照。
- [handoff/v5-rebound-admission-20261010/package/MINIMAL_ISSUE.md @ 40084ee7](https://github.com/lexi2016/v4/blob/40084ee76acf1c43b2d8768d538d7c91052437dd/handoff/v5-rebound-admission-20261010/package/MINIMAL_ISSUE.md)
  - Git blob: e7ef6c9b5a292f3ff2cd3b38652ad9ae9e70ec4c
  - 已全文读。实际与历史target分别、67 cells、trust/units/membership缺口、694 hold及撤回raw/logical digest误报。
- [handoff/v5-rebound-admission-20261010/package/SOURCE_ROUTES.md @ 40084ee7](https://github.com/lexi2016/v4/blob/40084ee76acf1c43b2d8768d538d7c91052437dd/handoff/v5-rebound-admission-20261010/package/SOURCE_ROUTES.md)
  - Git blob: ecd80274f125a7ef5618e15f86377854de5882bb
  - 已全文读。原VIPDOC增量不补内部缺口、PyTDX仅6根、历史Futu quota不证明当前授权/余量。保留owner边界。
- [handoff/selection-output-reuse-repair-20261010-r1/SOURCE_MANIFEST.json @ d659ff0d](https://github.com/lexi2016/v4/blob/d659ff0dbcc00aa1944908cfc8b44443642ea171/handoff/selection-output-reuse-repair-20261010-r1/SOURCE_MANIFEST.json)
  - Git blob: cae2a60f4813513a01f884cc45f3fa4d13c5c065
  - 已全文读。workspace_plan before SHA256 881599ba5a68badd7e18271c57666937f3e954088dfcfcb4c827dcf99419be7f，after 89d2f93201aa5284ab4d7bde5d9facc73834057d1d9cf7f9bbd6cd4ca5b95c3d；两者属V4 current-live，不是F vendor前后像。
- [handoff/selection-output-reuse-repair-20261010-r1/runtime.patch @ d659ff0d](https://github.com/lexi2016/v4/blob/d659ff0dbcc00aa1944908cfc8b44443642ea171/handoff/selection-output-reuse-repair-20261010-r1/runtime.patch)
  - Git blob: e613e571b6c127cf4a6444998c017cb7a334ccde
  - 已全文读。只借Decimal价格门及float展示最小语义；公告两处归M13，不由M14合并。

## 已核不必重复实现
- R的source/rebound_panel_repair.py经目录响应核得blob af95f98728ad0d83ff4b02f14446ee922120ff3b，与F产品文件同blob；R的test_rebound_date_compat.py与F测试也同blob75a56f0fa39c5cc1cb90dd299e8c3569be92835d。日期存储修复已经进F。
- 原identity与真实model已有Mac回执；本包不重跑。若新候选不改变其字节/依赖，引用原证据并把新变化另验，不把旧结果相加成全套。
- D给的是V4 current-live的确切前像；F两个vendor都还有旧float价格门，但规则/volume证明/文件长度不同。只做逐函数最小映射，不能apply整patch或拷贝完整后像。

## 依赖/写入责任
- M02：V5/vendor/hk_preselection_baseline/upstreams/v3_shared_data/shared_data/hk_0_2.py及原HK源/master/资格producer。M14以冻结owner和既有SOURCE_ROUTES为来源，不接管或重复采集。
- M14：自身计算/观察/准入与私有修复证据。rebound vendor与相关descriptor需单一候选协调；AST依赖必须完整列入。
- M18：manager_plan、manager vendor、经理产品/终态和普通读回。M14交产物契约与必要Decimal移植请求，禁止两Chat改同一manager workspace_plan。
- 平台集成：daily_owner_adapters/daily_rebound_owner、daily_tick、gateway、module_api、sharedUI及发布配置；M14只提出精确合同与测试，统一写入发布。
- 原总计划链接：[18模块总计划](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)；[迁移执行计划](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)。
- [既有静态三策略审查](https://github.com/lexi2016/v4/blob/d3578688995c7cf14edb3b771a36688e0558dc2f/handoff/v4-code-optimization-review-20261010/STRATEGY_SOURCE_MAP.md)保留原源地图，仅静态证据。

## 仍须Mac绑定的最小信息
当前活动/私有child字节与候选状态、原193资产保护清单、真实target/signal/member集合、来源/单位/approved authority证据、当前合法源授权和quota（只在确需按原owner补采时查）、实际解释器/锁/输出根、ordinary API/页面版本与M18消费引用。本包未读真实行情/原件，不搬到云端，不用历史路径猜当前覆盖目标。

