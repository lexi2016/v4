# Offline PDF ledger and classification sample

This one-purpose tool consumes a fixed existing OCR progress snapshot and the original 2,209-document manifest. It writes derivative review artifacts only: full identity CSV/JSON, candidate statistics, a reproducible 60-document evidence sample, ten real material-relation examples, and a standalone HTML report. It never extracts PDFs, performs OCR, calls models, downloads data, starts a service, deletes/merges material, or changes the original OCR run.

The progress file must first be read once into a snapshot with its exact SHA and capture time. Only terminal rows in that snapshot can supply existing immutable receipt/page-input references. Later live OCR additions do not enter this delivery. Pending rows stay visible in the 2,209 denominator. Every input receipt, page-input and page-text SHA is checked; identity/coverage/hash drift fails closed.

## Reproduce

Use the existing Python runtime and a derivative evidence directory containing:

- `input/batch-manifest.json`, exact original manifest SHA.
- `input/ocr-progress-snapshot.json` and `snapshot-receipt.json`, single-read frozen progress.
- `input/industry-taxonomy.json`, extracted labels/version/source SHA from the existing canonical `CANONICAL_GLOBAL_INDUSTRY_PROXY_MAP`; no new industry authority.
- `input/selection60.json`, frozen sample IDs bound to manifest/progress SHAs.
- `input/writer-sample-review.json` and `writer-relations-review.json`, scoped manual readback decisions with page/excerpt hashes; independent semantic acceptance is separate.

```sh
python -m ops.build_pdf_classification_sample \
  --input-root /absolute/derivative-evidence/input \
  --prepared-root /absolute/existing/prepared/full-cohort-sol-20261019-r1 \
  --output-root /absolute/derivative-evidence/delivery \
  --selection /absolute/derivative-evidence/input/selection60.json \
  --sample-review /absolute/derivative-evidence/input/writer-sample-review.json \
  --relation-review /absolute/derivative-evidence/input/writer-relations-review.json
```

To initially freeze the existing dictionary, supply `--taxonomy-source` pointing to canonical `infrastructure/research_peripheral_store.py`. AST literal reading extracts only the existing 24 theme labels and mapping version; it does not import or execute that source. These are text-topic candidates, not issuer industry assignments, listed-security mappings, or market eligibility.

## Evidence and classification boundaries

All 2,209 rule classifications remain candidates. Filename text is a hint; body publication/record/news structure controls material classification. A broker report citing minutes or a white paper remains broker research. A `风口研报` news compilation does not become a broker original because it quotes several analysts. Institution abbreviations have Latin token boundaries: `UBS` must not match `Subsidlary`. Date candidates exclude related-research sections and export/transcript timestamps; reviewed publication/header dates retain literal body evidence, otherwise unknown. Collection-directory dates are separately labelled and never substituted for report dates.

The Writer sample distinguishes main research subjects from mentioned companies and retains literal name evidence. It supplies no guessed ticker/exchange mappings. Some old audio-derived guides contain incoherent text and cannot authenticate their branded filename: classify the derivative material, keep source/content uncertainty visible, and route it to REVIEW. Six main categories do not imply that the current snapshot contains at least five verified documents in every category; shortfalls stay explicit. The sample deliberately covers boundary/quality cases and is not a random estimate of population frequencies or overall accuracy. Rule/Writer disagreements and per-class source/content uncertainty (including non-READY inputs) are reported, and independent semantic accuracy is not self-scored.

Routes are SAVE, REUSE_CANDIDATE, REVIEW, LIGHT_EXTRACTION_CANDIDATE, or DEEP_RESEARCH_CANDIDATE. They are candidates only. No explicit research question means no automatic deep-research/high-value assignment. No reviewed valid existing-result binding means no executed analysis reuse. No summaries, three research packages, investment analysis, or buy signals are generated in this phase.

## Document relations

Exact text identity uses NFC plus whitespace collapse per page, with page sequence preserved. Digits, signs, dates, units, case and numeric/word boundaries are retained: `1 2` differs from `12`, `-5%` differs from `+5%`. The original PDF SHA remains separate. Exact normalized text matches retain every source record; fuzzy title/topic overlap proposes candidates only. Numeric-token differences explicitly cover only the stated prepared-page window, not a complete factual audit. OCR/watermark differences do not automatically establish a new forecast or a revised report. Same theme is a retrieval group, never sufficient grounds to merge.

`report.html` is self-contained for viewing/filtering all 60 samples and ten relation examples, with no external scripts/styles or server. Linked CSV/JSON provide the full ledger. All snippets are HTML escaped and checked against the bound page text. CSV formula-like fields receive a display-only apostrophe; JSON identities and deduplication inputs are unchanged.

## Acceptance

Run only `tests/test_pdf_classification_sample.py` for this tool. Writer test results are handoff evidence. Independent review must reconcile all 2,209 IDs; assess the 60 material labels (target at least95%, with per-class uncertainty disclosed); review ten relation pairs with zero false merges; and confirm zero security-code mismatches. Passing local mechanical checks does not establish full-cohort semantic acceptance or authorize model analysis. The original OCR executor continues independently.

## 2026-10-20 全量增量候选阶段

本阶段沿用原静态HTML，添加完整2209身份的分页、搜索、主类/分流/OCR/语言筛选及严格同正文组的可选显示折叠。历史60样例和10对关系证据保持独立原样例时点；其独立PASS仅支持原材料形式/关系及静态脚本范围。浏览器file协议实际渲染仍为CANNOT_CONFIRM，不启动服务绕过安全拒绝。新全量候选不冒充语义验收。

正文规则版本 `full-body-structure-v2-20261020`：优先识别摘要导出模板和新闻栏目，会议引用/白皮书引用不能覆盖有明确机构和研究结构的封面；UBS按词界识别，机构只取封面品牌候选，二手导读标题不当成原机构。全量公司仅提取正文封面明确字面对象候选；未完成实体提及抽取保留unknown，所有证券代码仍未知；主题标签不作为发行人行业。发布日期仅取封面独立或显式日期字段；采集目录/导出/转录时间分开保留。

增量分类缓存绑定文档ID、PDF SHA、分页正文SHA、page-input SHA、receipt SHA、质量状态、规则版本、源码SHA、字典SHA及原manifest记录SHA。完全相同绑定复用分类；新完成/正文变化/规则修复产生新记录，保留历史缓存。每次仍核输入SHA和逐页SHA，校验不等于重复OCR。所有输出写入新FULL证据根的不可变build目录；同一build重复调用只校验并复用。正文严格归一化仅做NFC及空白折叠，保留页界、数字、单位、词界及符号；完整同正文组确证，标题日期归并仅召回不同正文的版本/转载候选，保留双方，不删除、不合并。未声称穷尽模糊重复召回。

新验证集在调优前从未用于开发的文档冻结60份（排除旧60及关系材料）；使用旧规则分层及语言/长度/质量等覆盖抽样，不是总体准确率估计。Writer不提供真值，独立Reviewer核类别、机构和日期等正文证据，未知和未READY比例另报。旧12差异逐项归因及回归只作为开发证据。

最终增量命令使用同一工具 `--full --evidence-root FULL_ROOT --prepared-root PREPARED_ROOT --sample-root SAMPLE_ROOT --require-final`。`--require-final`只消费原OCR owner的2209终态 `prepared-text-manifest.json`，校验FROZEN_COMPLETE、原manifestSHA、完整唯一ID集合、READY/QUARANTINED/FAILED分区、计数及pending0，再核所有receipt/page-input/逐页SHA。缺最终manifest即报WAITING_OCR，无OCR尝试。初步固定快照使用不带refresh/final的命令；有新授权快照才可加`--refresh-snapshot`，单次原子读取，不轮询。资源失败/隔离身份保留在完整台账并路由REVIEW，不能冒充正文READY或拖住其他文件。

本阶段所有执行均离线研究候选：0 OCR、0模型请求、0下载、0订单、0删除、0合并。部署/替换旧看板/提交推送由主控在独立验收后处理。原OCR和所有旧报告、原件、队列、HALT及服务保持由其原owner管理。
