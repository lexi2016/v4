# US–HK 667 交付卷完整性收件记录

日期：2026-10-15（Asia/Shanghai）

## 范围与方法

只检查 `/Users/lexi/Downloads` 顶层名称匹配 `US_HK_667*` 的文件和同名目录。未发现同名解压目录；共找到下列四个 ZIP。使用 ZIP CRC 检查、读取包内 README/清单，并按 `DELIVERABLE_MANIFEST.json`、`TOTAL_CONTENTS.json` 和本卷清单校验成员 SHA256、字节数和归卷关系。只用标准库读取压缩成员，没有执行 ZIP 内脚本，没有联网或操作服务。

40 与 220 是单 ZIP 快照，没有分卷 `TOTAL_CONTENTS.json`；读取其 README 和 `DELIVERABLE_MANIFEST.json`。560 与 700 是多卷交付，读取分卷说明、总清单、本卷清单和交付清单。多卷包内记录的“原总 ZIP SHA256”是整包标识；因整包及其他卷未齐，不能据此验证原总 ZIP 哈希。

## Downloads 顶层库存与校验

| 版本/文件 | 当前文件 SHA256 | ZIP CRC | 清单成员校验 | 发现 |
|---|---|---|---|---|
| `US_HK_667_batch2_cumulative40_review_20261015.zip` | `e623b55d2443dedf6298f05680bd6f658482d8ec122d072b852a072dec873d94` | PASS，36 个 ZIP 成员 | 35/35 个交付成员的 SHA256/字节数 PASS | 单 ZIP 文件包完整 |
| `US_HK_667_batch11_cumulative220_review_20261015.zip` | `8a214c3c10931e2ab807a3f1701449105702c68186a07a3c1da717413e69fab1` | PASS，125 个 ZIP 成员 | 124/124 个交付成员的 SHA256/字节数 PASS | 单 ZIP 文件包完整 |
| `US_HK_667_batch28_cumulative560_review_20261015_part2of2.zip` | `b851a2b1bdcd88b1a8e50eef2f923bf989183fa466c677e34b561edabaca3d0a` | PASS，161 个 ZIP 成员 | 本卷 158/158 个成员 SHA256/字节数/CRC PASS | 仅第 2/2 卷；总清单列 314 个原包成员，缺第 1 卷 156 个成员。清单所列原总 ZIP SHA256：`a19ff605d189990accd8c44d89f2b1f0384e1219c47de657882263afbb68c378` |
| `US_HK_667_batch35_cumulative700_review_20261015_part3of3.zip` | `d991f732193bb0a08046c84a5bfc0e6bcfa6ffbaffd03d7c5413a6b567dc7974` | PASS，134 个 ZIP 成员 | 本卷 131/131 个成员 SHA256/字节数/CRC PASS | 用户给定 SHA256 与实算一致；仅第 3/3 卷。总清单列 395 个原包成员，缺第 1 卷 131 个和第 2 卷 133 个成员。清单所列原总 ZIP SHA256：`589dd772523dd2f189dd6d86dce239d4eaa7402341df525e39d7f25904895c0d` |

560、700 的 `DELIVERABLE_MANIFEST.json` 与 `TOTAL_CONTENTS.json` 在排除 manifest 自身后，路径、字节数、SHA256 逐项一致；各 ZIP 实际交付成员集合也与本卷清单和总清单对应卷完全一致。以上只证明现有文件及清单间的字节完整性，不证明缺失卷内容，也不构成关系事实或研究语义验收。

## 分版本缺卷与关键依赖

### Batch 2 / 累计 40

完整单 ZIP，较早快照。README 记录累计处理 40/1003 条、963 条尚未处理，并明确事件为 `NOT_RUN`、prediction 为 `UNTESTED`、PIT 为 `NOT_VALIDATED`。包文件完整不表示研究全集完成。

### Batch 11 / 累计 220

完整单 ZIP，是 Downloads 顶层目前最新的完整交付包。README 记录累计处理 220/1003 条、783 条尚未处理；其中显式判定闭环 148 条（139 条限定用途闭环、9 条历史/排除裁决），72 条未闭环。它不是 1003 条关系的完整研究，也不是交易或预测验收。

### Batch 28 / 累计 560

当前只有 `part2of2.zip`。分卷说明确认原归档为 `US_HK_667_batch28_cumulative560_review_20261015.zip`、共 2 卷；第 1 卷未在 Downloads 顶层找到。按现有命名推测缺失文件应为 `US_HK_667_batch28_cumulative560_review_20261015_part1of2.zip`，该名称是推测，未发现对应文件。当前卷的 `DELIVERABLE_MANIFEST` 有 313 个交付文件；总清单显示完整原包为 314 个成员，当前仅持有其中 158 个。

第 1 卷缺少的关键文件包括：

- 来源与证据：`02_original_url_occurrences.csv`、`03_evidence_by_url.csv`、`03_stable_evidence_id_record_occurrences.json`。
- 累计/本批结果与覆盖：`04_cumulative_results.csv`、`04_current_batch_results.csv`、`05_change_control_summary.json`、`06_stock_progress_667.csv`、`08_asset_identity_790_original_plus_revision.csv`。
- 关系研究与补充记录：`11_cumulative_processed_relation_summary.csv`、`11_current_batch_relation_summary.md`、`11_relation_research_summary_1003.csv`、`11_research_summary_records_complete.json`、`12_subsequent_research_addenda.json`、`12_subsequent_research_addenda.md`、`13_declared_navigation_reference_exceptions.json`。
- 完整输入及解释材料：`README_累计结果与边界.md`、`research_records_complete.json`、`summary.json`，以及 58 个 `research_inputs`、48 个 `summary_inputs`、27 个 `support_inputs` 文件。

因此当前不能核实 560 快照 README 中的研究口径或将它作为完整累计研究包；也不得与 700 版分卷拼接。

### Batch 35 / 累计 700

当前只有 `part3of3.zip`。分卷说明确认原归档为 `US_HK_667_batch35_cumulative700_review_20261015.zip`、共 3 卷；第 1、2 卷未在 Downloads 顶层找到。按现有命名推测缺失文件分别为 `US_HK_667_batch35_cumulative700_review_20261015_part1of3.zip` 与 `US_HK_667_batch35_cumulative700_review_20261015_part2of3.zip`，名称是推测，未发现对应文件。当前卷 131 个成员，完整原包 395 个成员。

第 1 卷缺少的关键文件包括：`03_evidence_by_url.csv`、`04_current_batch_results.csv`、`05_change_control_summary.json`、`08_asset_identity_790_original_plus_revision.csv`、`10_batch_progress_and_breakpoint.json`、`11_cumulative_processed_relation_summary.csv`、`11_research_summary_records_complete.json`、`12_subsequent_research_addenda.csv`、`README_累计结果与边界.md`、`research_records_complete.json`，以及 47 个 `research_inputs`、42 个 `summary_inputs`、20 个 `support_inputs` 文件。

第 2 卷缺少的关键文件包括：`01A_full_667_original_plus_revision.csv`、`04_cumulative_readable_report.md`、`05_field_level_revision_log.csv`、`06_stock_progress_667.csv`、`08_asset_relation_identity_projections.json`、`09_prediction_design_1003.csv`、`11_cumulative_processed_relation_summary.md`、`11_累计700条关系摘要_20261015.csv`、`support_records_complete.json`，以及 47 个 `research_inputs`、44 个 `summary_inputs`、23 个 `support_inputs` 文件。

因此不能把当前第 3 卷称为累计 700 的完整交付，更不能用其文件或成员数补齐累计 560；在其余两卷到齐前，700 研究内容和累计结果均为 `CANNOT_CONFIRM`。

## 当前可用基线与剩余依赖

最近一个已在本机完整找到并通过 CRC/成员 SHA 校验的交付包是 Batch 11 / 累计 220。Batch 2 / 累计 40 是较早完整包。560 尚缺第 1/2 卷；700 尚缺第 1/3 与第 2/3 卷。只有各版本自己的缺卷到齐并重新核验后，才能确认对应完整交付包；之后仍需独立语义验收，不能把包完整性等同于研究完成。
