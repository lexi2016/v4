# 原15号模块固定来源清单

本包不重复搬运源码。以下链接均固定commit；代码观察基线F=f7cb731c384ee6890a87d16c19a5b5a621779477。清单用于Chat直接定位，不是把所有参考文件列为M15可修改文件。权限边界以PROMPT_FOR_CHAT.md为准。

## 一 计划和既有审查

- [原总计划](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)：原15号为美股到港股映射，18个模块/P0—P5保留。
- [迁移执行计划](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)：§3 M03/M04/M15/M18、§4依赖；03+04+02→15→18。原§9工作包二是超跌，与按18个Chat的模块编号无关。
- [已有V4源码审查包](https://github.com/lexi2016/v4/blob/d3578688995c7cf14edb3b771a36688e0558dc2f/handoff/v4-code-optimization-review-20261010/START_HERE.md)：复用已核来源索引。原审查Chat另有REVIEW_FINDINGS、RECOMMENDED_PLAN、BASELINE_MERGE_MATRIX、MINIMAL_MISSING_INPUTS，但它们不在本链接交付目录中，新Chat不得假装已持有。本包已列明US owner接口、窄receipt兼容和同run的具体源码依据，足够开始；不要求重新做整库审查或等待整套旧附件。

## 二 当前M15及只读依赖定位

表中Git blob是固定仓库身份，不是SHA-256。manifest内的SHA-256和wrapper的PIN各按原算法核，不混用。

| 文件与固定链接 | Git blob | 读取依据与用途 |
|---|---|---|
| [V5/src/v5_shadow/us_mapping_daily.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/us_mapping_daily.py) | 366190eaeeaf65ed51e5bda5da6c17cd5b5d5f1e | 本轮读完整源码；M15隔离调用、39项源PIN、三文件合同、原保存读回 |
| [V5/src/v5_shadow/us_mapping_io.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/us_mapping_io.py) | 3820d694747d9edd624b2b28a3f71e767b6e862c | 本轮读完整源码；M15 Python I/O守卫；不是OS sandbox |
| [V5/src/v5_shadow/us_mapping_scope.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/us_mapping_scope.py) | cc864ef910d1f33bf3eb2ad2f168e846b2c8423d | 本轮读完整源码；四键有限范围、原来源身份与未知 |
| [V5/src/v5_shadow/daily_us_owner.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/daily_us_owner.py) | cb6252d8403d36d86f5d06b2c3cb5ad86f7cb5f4 | 本轮读完整源码；原daily ledger适配；natural_verified=false |
| [V5/contracts/us_mapping_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/us_mapping_source_manifest.json) | 0e803149fa083bf30c5a72a190d62dea626e15f2 | 本轮读完整清单；M15现有39项闭包；不是完整采集闭包 |
| [V5/vendor/us_mapping_baseline/v4/manager_research/us_market_bridge.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/v4/manager_research/us_market_bridge.py) | 6b79f476e1251d2ac55d03e832de76ebbef1c72d | 本轮读源码；精确session原三文件消费；旧receipt拒绝点 |
| [V5/vendor/us_mapping_baseline/infrastructure/research_peripheral_store.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/infrastructure/research_peripheral_store.py) | 9bc740c094697370208b4e84a07e724648a80a8a | 本轮读源码；只读原source owner；两legacy字段常量及_receipt_matches |
| [V5/vendor/us_mapping_baseline/infrastructure/_research_peripheral_store_parts/publish_read.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/infrastructure/_research_peripheral_store_parts/publish_read.py) | 63a7be703ff1f4e19b8379ab84d3b46b5a194b84 | 本轮读源码；只读source owner；原窄兼容与exact-read |
| [V5/src/v5_shadow/current_us_research.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/current_us_research.py) | 1e4483e91551dc08ae5954a8cce2d18842195a19 | 本轮读完整源码；跨模块参考；真实当前时钟、coverage_paths、dynamic读回 |
| [V5/src/v5_shadow/manager_plan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/manager_plan.py) | 5e05f82ec6d2d88f47e79d19e5caf433a0143f2c | 本轮读源码；M18参考；native_master已接，保存/attempt/current-recovery |
| [V5/contracts/manager_plan_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/manager_plan_source_manifest.json) | ed8abe0e2286fd3e830ff08d4b3adeb7f48a0ea8 | 本轮读完整清单；M18现有80项；材料原函数在此闭包 |

M15原算法与种子记录的固定入口（既有审查索引已核，按这些函数继续追依赖）：

- [V5/vendor/us_mapping_baseline/v4/manager_research/us_mapping_research.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/v4/manager_research/us_mapping_research.py)：_read_reviewed、_relation_index、_relation_available_at、build_daily_run、persist_daily_run、read_workspace_mapping。基线旧persist在280行附近只接受now。
- [V5/vendor/us_mapping_baseline/v4/manager_research/us_mapping_relation_registry.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/v4/manager_research/us_mapping_relation_registry.json) 与 [V5/vendor/us_mapping_baseline/v4/manager_research/us_mapping_reviewed_20260930.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/v4/manager_research/us_mapping_reviewed_20260930.json)：原四daily键、卡片关系类型及范围；不能靠扩张此数据清除未评估。
- [V5/vendor/us_mapping_baseline/ops/us_market_digest.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/ops/us_market_digest.py) 和 [V5/vendor/us_mapping_baseline/ops/_us_market_digest_parts/market_snapshot.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/us_mapping_baseline/ops/_us_market_digest_parts/market_snapshot.py)：M03来源语义参考。24行业代理/33配置证券、POST_CLOSE和原报价校验；M15不修改或接管采集。

原store兼容只允许缺market_snapshot_captured_at、market_snapshot_source_response_sha256两字段的精确旧形状（research_peripheral_store.py约77—80、publish_read.py约80—99）。M15 bridge约74—106在原exact-read后重读字节，再以完整receipt字典比较而拒绝这种旧形状。本模块修消费桥接时应复用原_receipt_matches；原store与原receipt不改，M18同名副本另交请求。

## 三 材料路径原函数所在的共享闭包

以下属于共享manager_plan_baseline参考源码，不能在M15候选中直接修改：

- [V5/vendor/manager_plan_baseline/v4/manager_research/issuer_us_relations.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/manager_plan_baseline/v4/manager_research/issuer_us_relations.py)：extract_issuer_business_relations、_card_errors、_standing_contract、material_us_relations。主体/action/span、20类taxonomy、native identity及真实时钟/原引用合同。
- [V5/vendor/manager_plan_baseline/v4/manager_research/research_evidence.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/manager_plan_baseline/v4/manager_research/research_evidence.py)：us_mappings（约336—403）、collect_attention_evidence（约528—595）以及us_mapping_diagnostics；原行业与显式个股join。
- [V5/vendor/manager_plan_baseline/v4/manager_research/research_attention.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/manager_plan_baseline/v4/manager_research/research_attention.py)：原attention组装和范围表达。
- [V5/vendor/manager_plan_baseline/v4/manager_research/workspace.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/vendor/manager_plan_baseline/v4/manager_research/workspace.py)：实际_compute_workspace调用链。物理在M18闭包不改变M15两路径业务职责；Chat应给最小独立调用/封装方案，保持原算法和来源字节，不复制整套经理系统。
- [V5/src/v5_shadow/native_identity_reader.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/native_identity_reader.py)、[V5/src/v5_shadow/archive_reader.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/archive_reader.py)：M02/M04消费边界定位，当前输入缺口交相应owner。

已核manager_plan.py约406—414将_workspace_security_master_root设为roots.get('native_master')。current_us_research.py已有coverage_paths，明确industry_material、individual_material、reviewed_seed，并使用原当前时钟；其run_current_research只证明显式dynamic调用合同，不采来源、不证明普通auto/页面通过。不要重复修“native root永远None”等历史缺口。

## 四 R3 owner与FOUR接线是条件donor

- [R3完整US owner](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-r3-repair-20261009/after/api_current/v4/manager_research/us_mapping_research.py)：本轮读源码；_read_exact_run约419行，persist_daily_run约958—960接受timeout_seconds与execution_context。含budget、reader并发、dispatch/publication intent、有限扫描及恢复；不能只摘签名。
- [R3 service调用](https://github.com/lexi2016/v4/blob/8c8e35d9d53431c9082dec49f4976e363c275765/handoff/manager-daily-r3-repair-20261009/after/api_current/v4/manager_research/service.py)：约417—427。共享service归对应集成owner，本Chat只提出合同请求。
- [FOUR路由准备与exact US读回](https://github.com/lexi2016/v4/blob/74478a0e62be215c8527ccc9a14b89b51042d014/handoff/manager-four-functional-gaps-20261009/package/code/r2_chat_patch_target/apps/api/v35_api/manager_research_router.py)：约247—380。用于理解上游准备和保存次序，不是M15可覆盖的目标文件。

采用R3时必须重核M15源manifest、imports、namespace全局常量、projection/plan_context、安全和store合同、JSON种子文件及自有输出范围。现有M15只允许runs/latest的I/O守卫与R3 dispatch路径可能不同；不能通过放宽成任意写来兼容。仅当实际需要才移植，已等效保持原字节。

## 五 M03采集可信边界 已在基线存在

- [可信采集加载器固定树](https://github.com/lexi2016/v4/blob/4acb6ae631bb9cb012674ddac1491dce412047e2/V5/src/v5_shadow/cloud_us_collector.py)；Git blob 7647e20aaa7b4cc4f56aa638596c3aea2f3c8b12，与F树同文件相同。
- [48文件采集manifest](https://github.com/lexi2016/v4/blob/4acb6ae631bb9cb012674ddac1491dce412047e2/V5/contracts/cloud_us_collector_sources.json)；Git blob 9f0c558326b6cffd2519d1e190b988fecd73a334，与F树相同。manifest的source_commit是164c010c7eaa1659db9bfed0ff5f123c7a39eefc；loader原descriptor字节PIN为34f45318dd89132a496ac0edf98147455b41d9ea926198d83ce1bd8810c20d8b。
- [既有18项合成审查回执](https://github.com/lexi2016/v4/blob/4acb6ae631bb9cb012674ddac1491dce412047e2/V5/docs/reviews/cloud-preview-20261010/COLLECTOR_REVIEW.md)：可信finder/loader、清单外模块/pyc/外部同名包拒绝及namespace路径审计；正向Tencent/RSS→原CLI→原store三文件是合成链。原48文件及PIN未变，本包不重测、不推断真实网络已通。
- [来源与完整验收限制](https://github.com/lexi2016/v4/blob/4acb6ae631bb9cb012674ddac1491dce412047e2/V5/docs/reviews/cloud-preview-20261010/ROUND3.md)：真实出口/材料、自然接续仍须另验。

4acb6ae这个commit本身只修改既有失败日志格式；这里引用其固定树和审查回执，不称它是新增采集实现的提交。M15不改这部分；M03若有真实源问题独立处理，不绕过出口拒绝。

## 六 M18消费和页面只读参考

- [V5/src/v5_shadow/manager_plan.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/manager_plan.py)：原经理保存与独立attempt验证、CURRENT_RECOVERY、普通read。当前refresh约454—461读取saved并比较同run，不代表并发latest交错已全部解决；按最终集成版本验证。
- [V5/src/v5_shadow/module_api.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/module_api.py) 与 [V5/src/v5_shadow/api_gateway.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/api_gateway.py)：源码目录定位已核，实际挂载与DTO由M18/集成者继续核，不猜Mac地址。
- [V5/ui/manager-workbench/source/apps/web/src/manager-selection/usMappingCoverage.ts](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/ui/manager-workbench/source/apps/web/src/manager-selection/usMappingCoverage.ts)、[V5/ui/manager-workbench/source/apps/web/src/manager-selection/dailyChannels.ts](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/ui/manager-workbench/source/apps/web/src/manager-selection/dailyChannels.ts)、[V5/ui/manager-workbench/source/apps/web/src/api/managerWorkspace.ts](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/ui/manager-workbench/source/apps/web/src/api/managerWorkspace.ts)：固定目录存在已核；共享UI不在M15可修改范围，Chat给字段/诊断合同与必要消费请求即可。

本轮仅做固定源码/目录/清单读取和文档一致性检查。没有新产品执行结果，没有读取Mac活动源码或重新核其真实业务原件，也没有进行真实采集、产品测试或部署。

