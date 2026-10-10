# M13 固定来源与边界

## 1. 证据分层

- S：固定GitHub文件/树的静态事实，不能证明Mac已部署。
- R：既有现场/审查回执，按原时间与口径复用，不能写成本轮实测。
- D：当前候选动态执行证据；本包没有，全部NOT_RUN。

本包于2026-10-10通过GitHub connector核下列固定目录/正文。材料commit为 `9cac0fffe12fda6ec06e106206e0c647b427913f`；代码commit为 `f7cb731c384ee6890a87d16c19a5b5a621779477`。Git blob SHA不是文件SHA-256；候选仍须补逐文件SHA-256。

## 2. 编号与材料

- [总计划固定原文](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)：原M13公告、M18经理；blob `3164c9e1013eab9f84825610c7243d1ace4ab8b7`。
- [迁移固定原文](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)：继续01—18/P0—P5；旧reviewer阻塞属于当时状态，不覆盖后续已存392/5b4f回执。
- [原审查入口](https://github.com/lexi2016/v4/blob/9cac0fffe12fda6ec06e106206e0c647b427913f/handoff/v4-code-optimization-review-20261010/START_HERE.md)
- [实际策略源码图](https://github.com/lexi2016/v4/blob/9cac0fffe12fda6ec06e106206e0c647b427913f/handoff/v4-code-optimization-review-20261010/STRATEGY_SOURCE_MAP.md)
- [统一source索引](https://github.com/lexi2016/v4/blob/9cac0fffe12fda6ec06e106206e0c647b427913f/handoff/v4-code-optimization-review-20261010/SOURCE_INDEX.json)
- [策略source/SHA索引](https://github.com/lexi2016/v4/blob/9cac0fffe12fda6ec06e106206e0c647b427913f/handoff/v4-code-optimization-review-20261010/STRATEGY_SOURCES_READ.json)

原Chat另交REVIEW_FINDINGS.md、RECOMMENDED_PLAN.md、BASELINE_MERGE_MATRIX.csv、MINIMAL_MISSING_INPUTS.md，旧交接说原审查会话持有。它们不在本次核到的9cac0ff目录列表中；新Chat不得假装已获附件或引用其中未见内容。必要时只请嘻嘻补对应最小片段；当前固定源码足够开始M13路径/差异核对，不要求用户重整全包。

## 3. 已核M13入口与测试：白名单候选，不是必改清单

目录：[V5/src/v5_shadow](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow)、[V5/tests](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/tests)。

| 固定路径 | Git blob SHA | 边界 |
|---|---|---|
| `V5/src/v5_shadow/announcement_analysis_api.py` | `3fbfc9e2fab1d66c2a2a80f43414e95b256ab970` | 已读文件全文；M13候选范围，须逐文件证明必要差异 |
| `V5/src/v5_shadow/announcement_bridge.py` | `244260d7a10ca189a6132fda75ee641745bb8d72` | 已读文件全文；M13候选范围，须逐文件证明必要差异 |
| `V5/src/v5_shadow/announcement_offline_reader.py` | `5fa361e8ad09d76d9195d0697bbc30b55335f747` | 已读文件全文；M13候选范围，须逐文件证明必要差异 |
| `V5/src/v5_shadow/daily_announcement_revision.py` | `e8e5608ccc120e659062493d4940170ab07a6ba0` | 已读文件全文；M13候选范围，须逐文件证明必要差异 |
| `V5/tests/test_announcement_analysis_api.py` | `b792ce2d7073332cd3c871016330765e015bceaa` | M13针对性测试候选；先读源码再确认白名单 |
| `V5/tests/test_announcement_bridge.py` | `7ee2dbb5aca1643cd4cc53b1723211fa3d65717d` | M13针对性测试候选；先读源码再确认白名单 |
| `V5/tests/test_daily_revision_chain.py` | `9b242d18edf0581f5a84ca647d4649288b4fe009` | M13针对性测试候选；先读源码再确认白名单 |
| `V5/tests/test_manager_announcement_binding.py` | `bc627ab323e4f389502522f65751c8684e8e8168` | M18消费合同只读参考；新增M13消费fixture，不直接修改此文件 |
| `V5/tests/test_manager_offline_announcement.py` | `88416703049596b0a6674a82e9070b371cbd82c3` | M18消费合同只读参考；新增M13消费fixture，不直接修改此文件 |

接口静态事实：

- announcement_bridge.py：run_announcement_bridge(request)，绑定不可变输入并调用原catalog/analysis owner；默认source_origin_verified/workspace_consumption_verified/natural_verified均false。这些声明不能通过改布尔值当作补接生产。
- announcement_offline_reader.py：read_owner(binding, cutoff, default_analysis=False)、install_transport；只读transport，明确不capture/import/adopt。消费合同引用manager_plan固定源码，依赖≠允许修改M18。
- announcement_analysis_api.py：response_record/publish_analysis；ROUTE为 /api/v4/manager/research/announcements/analysis。默认/显式日期读回均验真实原产品；publish_analysis属于发布动作，M13 Chat不执行共享发布。
- daily_announcement_revision.py：run_revision(request, ledger_run_id)，真实review输入齐后调用固定revision owner的create/prepare/register/verify/import/readback；reader/reviewer不同，复核缺失就阻断。不要对现有392重复执行。
- 固定目录没有announcement_daily.py，规划名称不等于已有实现。新文件必须标NEW并明确最小职责。

## 4. 原owner复用，冻结donor默认只读

基线根 `V5/vendor/announcement_offline_baseline/`；具体字节与SHA-256见策略source索引。

| 相对路径 | 已有职责 | Git blob SHA |
|---|---|---|
| v4/manager_research/hkex_provider.py | 原HKEX受限transport | 3d5c134a592f8a4e54ad9097325fdbbbf59df3a7 |
| v4/manager_research/announcement_source.py | HKEX/东财发行人目录、正文身份与缓存 | 0e44ea0a91b6da65bc3fadf630dee9769b316574 |
| v4/manager_research/announcement_catalog.py | 指定日分页目录、完整性与COMPLETE_EMPTY | aa12f2f47edb63819d91519c6c4747882512dd6f |
| v4/manager_research/materials.py | 原始字节/引用/取得时间、内容寻址与派生缓存 | 555d285fa5b5cd7714c68a5c582797577c3ffaea |
| v4/manager_research/announcement_analysis.py | 原语义产品装配、严格绑定、owner import/read | 66710be1bcacd528e5677bc6ebff201ab60c82c8 |
| v4/manager_research/store.py | 原事务、原子保存与读取 | c9af9a6ae87858ebee111766d4db0fd0639943b5 |
| ops/run_manager_daily_announcement.py | capture/Reader之后的验证/导入/readback bridge | 2af4fbfa5947fdab4b93cee6239174dc03d6dd39 |
| ops/run_v5_offline_analysis.py | 原离线analysis owner；本包只核目录身份，Chat再读全文 | ed21002880104c3bcaf1593371e874bb6471d95d |

另核revision owner路径：`V5/vendor/announcement_revision_baseline/ops/run_v5_decision_revision.py`，blob `d85623e19301188ef2569bbb16595d22d91b5eb5`；该capsule的run_v5_offline_analysis.py blob为 `53e517161dcbf97bc1007a75fb270755a4726282`，与offline baseline不同，不能混拼。

`V5/contracts/announcement_readback_source_manifest.json` blob为 `3a73eb295563cd8fef0d5146d5b377a64ce3c95a`，固定announcement_readback_baseline而非任意新owner；对应胶囊/manifest关系必须逐一核对。依赖闭包不齐不能声称可安装。

## 5. 明确排除直接修改的边界

- M18：manager_plan.py、manager_plan_io.py、manager_plan_gate.py、manager vendor保存/汇总/终态；共享经理测试。
- 平台共享：module_api.py、api_gateway.py、web.py、contracts.py、daily_owner_adapters.py、daily_dispatch/run_ledger/module_artifacts等。
- 共享前端：apps/web、V5 frontend或其构建manifest；旧前端候选由嘻嘻接收，不在M13重做。
- V4现役目录/数据/服务、8910、BUY门、任何交易/订单、凭据/系统安全权限。
- M14超跌、M15美股算法与数据源，不因review矩阵存在就纳入M13。

跨模块请求而非直接补丁示例：M13实际产品字段→M18消费validator；analysis/selection exact route→共享gateway owner；错误/未知/资格语义→共享前端。写接收方、具体函数、schema差异、fixture、预期、兼容风险，由嘻嘻统一安排落地。

## 6. 旧B01与已有局部修复

旧B01“公告→经理→页面”只作R证据，跨模块写入范围已被18个独立Chat分工取代。它不是原M01；已有392/5b4f/产品SHA继续复用，不能因改编号重做。

[另一路局部修复 d659ff0](https://github.com/lexi2016/v4/blob/d659ff0dbcc00aa1944908cfc8b44443642ea171/handoff/selection-output-reuse-repair-20261010-r1/README.md)来自旧B01引用，本包未再次读取该候选。Chat先核实际文件/版本/等效实现，再只取与M13有关的最终SHA绑定或完整readback最小差异；不把超跌Decimal修复纳入M13，不把其合成/历史结果提升成本机当前通过。

当前数据、binding、source run、活动前像以Mac原件为准。身份未提供处标UNKNOWN/SOURCE_NOT_PROVIDED；不要从别的经理run、旧目录或文档时间猜source。

