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

### F1–F4 集中返修（独立 FAIL 后）

保留初次全量代码/固定快照独立FAIL及原新60结果56/60（93.33%，含两个可识别但待分类的错误），未达到95%目标。该60现因错误已揭示而成为返修回归，返修结果不能再作为未见验证或总体准确率。稀有类别缺失、机构/日期unknown和字段错误原记录均保留。

规则版本更新为 `full-body-structure-v3-f1-f4-20261020`，仅修F1–F4：封面证券研究/策略周报等出版结构优先于正文引用，资讯署名/会议性质须有标题或记录结构；补财信/平安封面别名，不按文档ID设特例。首面长摘要而问答/发言人结构在后续准备页时，仅在未命中明确出版形式的材料中扫描已有页结构，保留发言与出处不确定性。日期优先显式报告/发表字段及封面品牌后的刊头，排除市场/基础数据和相关研究上下文；日期冲突则unknown。全正文去重分母明确为“可用准备正文（含隔离，质量状态单列）”，READY分母另存真实数量。

本轮只增量复核改变规则的实际原页及针对性测试，复用未受影响的身份、缓存、去重和静态JS PASS。源码版本变化允许必要重分类，旧输出/缓存/FAIL均保留；0OCR、0模型。最终OCR2209终态manifest仍单独等待，不因本轮返修重复读取动态进度。


### 第三轮 FAIL 后主控裁定的结构锚点限界批

历史三轮 FAIL 全部保留。本批只约束结构和排除弱证据：泛词“机构调研”需封闭栏目标题或来源归属明确的独立栏目；“机构调研是…”不成立。出版机构与本地化研究标题按完整标题匹配，免责声明“研究所保留追究…”不成立；实际封面研究院/研究所与研究团队/小组、结合证券分析师或研究封面的研究微信服务号保留。没有文档 ID 例外，也未改变全局分类优先级。

人工绑定 v2 只将6322…降为待核分类/REVIEW：第3页“原文未提供问答环节内容”仅是否定模板，不能证明实际会议。正文可读，不添加质量异常。旧25条绑定文件及其 SHA 保留，另24条记录对象不变。最终增量命令改用 v2。

同一固定1903 READY、44隔离、14失败、248待OCR快照，2209身份对账。裁定前26份变动逐条解释：22份真实封面候选恢复，剩4份中3份主类纠正及1份研究子类型变化；日期和质量零变，未出现新无关 delta。20份真实正反例回归匹配，21项必要测试通过，仅为 Writer 交接。新60早已揭示，不能用于未见泛化准确率；原FAIL及原unknown分母保留。当前待分类266＝248待OCR、14失败、3正文质量待核、1可读正文材料形式待核。

本批曾误在 canonical 新建文档2558字节，主控已核 SHA 并移至证据 incidents/ 留存恢复；此前“零 canonical 写入”表述撤回。之后命令均显式指定隔离 worktree。具体恢复回执、全量delta、输入/源码SHA、运行命令见FULL/controller-bounded-structure-20261020/HANDOFF.json。

候选看板 builds/289c9b7c476fb221809e/report.html 仍是固定快照；不代表OCR终态、独立验收或实际浏览器渲染通过。独立验收后，唯一 Writer 才能按原终态manifest/pending0门禁续最后增量。0 OCR、0模型、0删除合并、0提交推送；未改原OCR产物。
