# Identity repair r1：Mac RED/GREEN 与集成回执

本记录接续 [889abcc 阻塞回执](MAC_REPAIR_R1_ACCEPTANCE_BLOCKER_20261010.md)，不覆盖冻结问题包及先前失败记录。固定交付为 `9fb6fa7ab1be54de9d03463e11926ad76e1cae27`；本轮开发分支基线 `889abcc3eb6a0c447348746c81fb34c9b7b213b4`。旧59/59属于5b64314阶段，不拿来证明新候选。

## 已取得的独立结果

| 批次 | 实际结果 | 结论 |
|---|---|---|
| 冻结cdd显式三项（Writer及独立Reviewer分别执行） | control通过；article_id、dedupe_key变异均在 `Identity mutation unexpectedly accepted` 失败；退出1 | 原缺口RED确认 |
| 原样9fb身份批（Writer） | 51项，50通过；直接AVGO合成fixture跨中文逗号子句失败，退出1 | 不是全通过；与既有fixture问题一致 |
| 精确保留5b64314 fixture修正后的身份批（Writer） | 52/52，退出0 | 工程GREEN |
| 最终身份批（独立Reviewer） | **52/52，退出0** | 独立工程GREEN |
| 相关五组（Writer默认sandbox） | 35/36；唯一socket bind EPERM，退出1 | 保留环境失败 |
| 该loopback单项（Writer正常授权） | 1/1，退出0 | 分次结果，不伪称一次36项 |
| 相关五组完整批（独立Reviewer正常授权） | **36/36，退出0** | 独立相关回归通过 |

独立检查覆盖完整source/原owner与builder重放、source和archive同时伪造拒绝、规范JSON的1/true类型差异、source可用时间与导入时间排序、安全IO/symlink sentinel/no-overwrite、v1分派及原store→reader→材料/主体→manager同run保存/读回。合成source的自洽性与原算法重放成立，不等于真实来源已证。

相关回归的正常工具授权仅用于同一个已确认的临时 `127.0.0.1` 端口监听；未改系统安全设置，未绕过审核拒绝。没有后台测试仍在运行。

独立Reviewer首次误用模块发现收集到继承测试，随后Ctrl-C退出130；该次仅作中断记录，不计RED/GREEN。后续RED严格显式列三项。先前Python3.9导入失败、Mac离线、默认sandbox EPERM记录均保留，不改写成通过。

## 来源门与工程源

候选18项初始文件的长度、SHA256及Git blob已核。此前两个真实根对15项新依赖分别13/15和14/15，继续保持拒绝且原根未改。

按用户明确授权重建 `identity-r1/original-source`：
- 原版本 `cdd430e4dcd8d3e8c5949baff21a4831b4689444`，canonical tree `3080eb75fbdf014f46f922847079774c68742cb9`。
- 完整 **1216/1216** blob独立重算匹配；Reviewer还按Git tree序列化重算根tree一致。
- 单独结构补件来自真实 `/Users/lexi/Desktop/学习/v4_app/domains/_research_hourly_parts/_namespace.py`，527字节，SHA256 `45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1`，复制后字节相等。未取vendor/stub冒充真实路径。
- 候选依赖 **15/15** 独立重算匹配。

这是一份“固定完整canonical重建＋有真实来源的namespace结构补件”的隔离工程源，不是现役源，也不声称是未经补件的原始cdd树。

## 修正、冲突与精确字节

相对9fb产品候选，唯一新增调整为：精确保留5b64314的同句AVGO正例和跨句不冒认负例，并同步manifest两处当前测试SHA。原owner、生产关系算法及9fb产品修复字节未被改写。冻结 `SOURCE_SHA256.json`、`static_review_changes`、交付时静态计数51保持历史含义；本轮新增负例后实际52记录于此。

当前测试SHA256：
`74ca5b7696ae1e6d5ec8343004eb7194ee5a5fa4236b2ae112afa69741968de0`；
Git blob `ccec69d3c9819de1a131d44430bceaaa6b77951c`。

当前producer manifest SHA256：
`3e0c745c614a0a13127ba053991f4171734f897ce90ccffdbbcb0ebb0dfbc876`；
Git blob `ad5d27f127db77a2dcadaab0b3b4795f30aa3c21`。

其余16项保持固定9fb交付字节。完整18项前置blob/当前blob、SHA256及长度见 [集成源码清单](MAC_REPAIR_R1_SOURCE_SHA256_20261010.json)。

同步前按开发分支889abcc逐项核18路径：只有测试/manifest与5b64314重叠，已精确保留两项修正；其余原路径或缺失状态符合固定基线，无未处理冲突。使用原分支树只写明确路径，保留既有回执和冻结包，不整树覆盖。

## 精确复现命令

Python：`/Users/lexi/.local/bin/python3.13`，3.13.12；MacOS26.6.2。公共环境：

```sh
export TMPDIR=/private/var/folders/mw/045dzcpj70x3m5nnfwj6lmnm0000gn/T
export PYTHONPATH=V5/src:V5/tests
```

旧基线 cwd：`/Users/lexi/Documents/Codex/2026-10-10/task-2/identity-r1/baseline`：

```sh
V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/Users/lexi/Documents/Codex/2026-10-02/task/V4_SOURCE_SYNC_20261005/payload/handoff/v4-running-source-20261005/canonical PYTHONPATH=V5/src:V5/tests:handoff/v5-article-identity-20261010 /Users/lexi/.local/bin/python3.13 -B -m unittest test_identity_gap_candidate.IdentityGapCandidate.test_control_valid_capture_is_accepted test_identity_gap_candidate.IdentityGapCandidate.test_article_id_mutation_must_be_rejected test_identity_gap_candidate.IdentityGapCandidate.test_dedupe_key_mutation_must_be_rejected -v
```

候选 cwd：`/Users/lexi/Documents/Codex/2026-10-10/task-2/identity-r1/candidate`：

```sh
export V5_ARCHIVE_PRODUCER_SOURCE_ROOT=/Users/lexi/Documents/Codex/2026-10-10/task-2/identity-r1/original-source
/Users/lexi/.local/bin/python3.13 -B -m unittest test_archive_article_v2 test_archive_builder_identity -v
/Users/lexi/.local/bin/python3.13 -B -m unittest test_archive_acquisition_producer test_current_us_research test_manager_archive_reader test_us_mapping_scope test_manager_plan -v
```

第二个候选命令的完整独立复跑通过正常执行工具 `sandbox_permissions=require_escalated` 完成，仅解除既有测试loopback监听限制，不修改安全配置。各批结果分开记录，数量不相加。

## 剩余范围与本机证据

身份合同的合成RED→GREEN已验证；**真实同批builder source来源仍CANNOT_CONFIRM，natural_verified=false**。未借本轮修复真实认证、采集、来源或时间；实际产物接入仍须同批source/capture/receipt及适用session/native identity。工程成功不关闭M04/M15全模块或自然验收。

未部署、未改V4/61796或四键三股、未用Chrome、未访问秘密。源码集成不等于现役服务已升级。

本机根：`/Users/lexi/Documents/Codex/2026-10-10/task-2/identity-r1`。
Writer完整命令/18SHA：`MAC_IDENTITY_REPAIR_WRITER_REPORT.md/json`；
来源：`original-source-provenance.json`、`cdd-source-tree.json`；
Writer日志：`baseline-red-python313.log`、`candidate-original-51.log`、`candidate-fixed-52.log`、`candidate-related-5.log`、`related-loopback-rerun.log`；
独立来源及RED回执：`review/independent-source-and-red-review.md`；
最终独立回执与52/36日志位于 `review/`。
