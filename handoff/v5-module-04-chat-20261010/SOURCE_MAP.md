# M04固定来源与映射

本轮读取固定树及下列文件；Git blob SHA是源码身份，不是运行成功或已部署证明。目录树递归返回truncated=false，M04总计划候选research_ingest_daily.py在固定树不存在。

## 计划身份

- [原总计划，M04/P4](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)
- [迁移执行，M04及编号换算](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)
- 代码固定提交：`f7cb731c384ee6890a87d16c19a5b5a621779477`；开发分支名称仅定位，不替代固定前像。

## Donor → V5

- 原 `ops/collect_hourly_research_input.py::build_hourly_research_input` 与 `domains/research.py::build_research_archive` → 已有 `V5/vendor/archive_builder_baseline/`、`archive_builder_v1.py`，原owner完整source/结果重放，不能按文章倒推source。
- 原 `ops/run_hourly_research.py::run_hourly_research_file` 与原archive/hourly store → M04拟新增 `research_ingest_daily.py` 的小时编排参考；先核完整依赖和实际writer，不能直接执行在V4根。
- 原 `ops/run_zsxq_hourly_delta.py` → 已有 `V5/producers/archive-acquisition-v2/source/ops/run_zsxq_hourly_delta.py` 候选。manifest原producer SHA256为 `7b984776bcdb26aec838419f8ce6cbf3cee77d9cdf3785cb46e64481ae5d3d38`，候选SHA256为 `1fe2caadfd6b2f67848b05393a02114583d0b05f6790a9b22872971dc6d7a288`；本包没有应用此补丁。
- 原archive reader/store闭包 → 已有 `V5/vendor/archive_reader_baseline/`、`archive_reader.read_private`。reader manifest的source_commit是8342862f05ca9f6516f51b3164b6110651e5af77/api变体，不能假定全部等于canonical现役字节。
- 新同批材料 → 已有 `archive_article_v2.run_import`；只接显式完整证据，旧v1保留原验证。
- M15 `current_us_research.py` 与M18 `manager_plan.py` 是已有消费者，仅接口请求；本Chat不写消费者。
- 早报/公众号/其他lane：原总计划范围仍保留，逐lane当前活动writer/完整闭包/实际API映射尚待Mac确认。不能由知识社区一lane推出全部归档完成。

## 本轮已读固定文件

- [V5/src/v5_shadow/archive_article_v2.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/archive_article_v2.py)
  - Git blob SHA：`f382350c66aeb434a53dad6cb8a378cf4b7ff817`
- [V5/src/v5_shadow/archive_builder_v1.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/archive_builder_v1.py)
  - Git blob SHA：`4550b530159785c7a28ba1c7321ef07f27e7846d`
- [V5/src/v5_shadow/archive_reader.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/src/v5_shadow/archive_reader.py)
  - Git blob SHA：`32d637d21d6a496d5d1c9c87db1ff015217e5dd5`
- [V5/producers/archive-acquisition-v2/README.md](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/producers/archive-acquisition-v2/README.md)
  - Git blob SHA：`d2953f1169e41ee15b4e598bce4e983d103eefc1`
- [V5/producers/archive-acquisition-v2/manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/producers/archive-acquisition-v2/manifest.json)
  - Git blob SHA：`ad5d27f127db77a2dcadaab0b3b4795f30aa3c21`
- [V5/contracts/archive_builder_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/archive_builder_source_manifest.json)
  - Git blob SHA：`3d3f9441d3416cf393c6f719c081054ec78916bb`
- [V5/contracts/archive_reader_source_manifest.json](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/V5/contracts/archive_reader_source_manifest.json)
  - Git blob SHA：`0c837f5b5e1b2e8c2ce2115ed1b70a957c428b44`
- [handoff/v4-running-source-20261005/canonical/ops/run_hourly_research.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/run_hourly_research.py)
  - Git blob SHA：`647f6c29f465e1b2158a34f54b4b729c650c1b2d`
- [handoff/v4-running-source-20261005/canonical/ops/collect_hourly_research_input.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/ops/collect_hourly_research_input.py)
  - Git blob SHA：`b33b26db87f87cf3dea325901164a473a5a8b491`
- [handoff/v4-running-source-20261005/canonical/domains/research.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/domains/research.py)
  - Git blob SHA：`e039fb39e602a907ab72408f43de259420d254ed`
- [handoff/v4-running-source-20261005/canonical/tests/test_hourly_research_runner.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_hourly_research_runner.py)
  - Git blob SHA：`f5ac4e469a10587b7cf0a66ec613834e4cae5e34`
- [handoff/v4-running-source-20261005/canonical/tests/test_research_archive.py](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v4-running-source-20261005/canonical/tests/test_research_archive.py)
  - Git blob SHA：`1651131cf93446aea7dbd0e029d3a23e9f0882cd`

## 已有回执的时间顺序

- [r1后续独立Mac52/52及36/36报告](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v5-article-identity-20261010/MAC_REPAIR_R1_ACCEPTANCE_20261010.md)：固定交付9fb6fa7ab1be54de9d03463e11926ad76e1cae27；集成基线889abcc3eb6a0c447348746c81fb34c9b7b213b4。保存5b64314 fixture修正，测试blob ccec69d3c9819de1a131d44430bceaaa6b77951c及manifest blob ad5d27f127db77a2dcadaab0b3b4795f30aa3c21。报告说明真实同批source仍未核、未部署。
- [更早59/59及真实输入/认证缺口报告](https://github.com/lexi2016/v4/blob/f7cb731c384ee6890a87d16c19a5b5a621779477/handoff/v5-article-identity-20261010/MAC_ENGINEERING_FOLLOWUP_20261010.md)：保留为历史，不将其中旧身份OPEN当最新工程结论，也不把52/36工程通过当认证或真实来源恢复。

如后续分支出现新修复，先比较上述固定文件和Mac真实前像；不能凭文件名或旧统计覆盖。Chat自己的补丁必须另交当前before/after SHA256，不能复用本表Git blob充当补丁SHA256。
