# 公众号链接固定执行方案

## 0. 默认输入/回传方案 v3（2026-09-21）

保留原有脚本，不新建采集、OCR、研究或Drive客户端。默认路径：

```text
本地复用 → 采集/OCR仅补缺 → freeze(input_digest/package receipt)
→ Drive文章目录：01_资料包 → 02_Chat回传 → 03_本地复核
→ 给用户一个Drive START_HERE链接与短prompt → Chat研究
→ Codex回收原字节/本地归档/结构校验 → 云盘镜像
→ V4 Stage A引用登记 → exact文章日API与UI归档展示验证
```

Codex负责采集、冻结、回收、校验、云盘镜像和V4 Stage A归档展示核验，Chat负责研究，用户负责提交Chat研究。Drive是默认优先交接与回收镜像通道；直接文件仅为Drive当前工具不支持或有界诊断失败时的受控回退，不默认要求用户再次上传资料。
本节是文档、技能和提示词实施，不代表已安装Drive连接器或已有自动传输系统。Chat没有Drive写工具时，Chat/用户把原文件字节回传给Codex，由Codex负责上传；没有真实metadata/bytes receipt不得声称已写入Drive。
相同资料不重复抓取/OCR；完成回传不自动再次运行method。报告改写沿用同输入的CSV原字节，只更新报告与摘要。

### 0.1 冻结身份
唯一打包/导入入口仍是scripts/wechat_chat_handoff.py。
完整input_digest覆盖BODY、OCR_FULL、图片清单和所有原图的有序摘要，原文HTML摘要也保留；manifest.json不摘要自身。
新冻结包另写`review_contract_version=wechat-event-dispositions-v1`，同时纳入manifest.json及input_descriptor/input_digest；不得由Chat回传摘要自行选择或降级版本。summary.json的`event_dispositions`需按coverage.csv的EVENT来源编号各给一个PROMOTE/HOLD/REJECT/CANNOT_CONFIRM。旧`chat-materials-ocr-v2`包若无该版本字段仍按旧合同导入，并在IMPORT_RECEIPT明确`NOT_RUN_LEGACY_PACKAGE`。
ZIP SHA在包外PACKAGE_RECEIPT.json，Drive文件/目录ID在上传后的外部交接记录中；Drive文章目录本身不替代package_id、input_digest或可信ZIP SHA。
package_id应在每个内容版本使用新值；跨目录没有全局ID注册器，验证必须核对(package_id,input_digest,可信ZIP SHA)，不可只认ID。
导入旧报告对照旧冻结ZIP，不对照当前run OCR。发布时间缺失/日期非法、原图不完整、不可解码或OCR切片失败不能PACKAGE_READY。
已有旧OCR无配置指纹可保守复用并标未知，不为新增元数据重跑89图。错误/超时只补缺；空文本终态需原图核查，默认不无穷重试。

### 0.2 运行命令
```bash
python3 scripts/wechat_chat_handoff.py package --run-dir "$RUN" --out-dir "$HANDOFF" --package-id "$PACKAGE_ID" --reading-mode OCR_RISK_REVIEW
python3 scripts/wechat_chat_handoff.py import --source-run "$RUN" --package-id "$PACKAGE_ID" --package-zip "$ZIP" --package-sha256 "$TRUSTED_SHA256" --report "$RETURN/report.md" --coverage "$RETURN/coverage.csv" --mentions "$RETURN/mentions.csv" --unmapped "$RETURN/unmapped.csv" --summary "$RETURN/summary.json" --out-dir "$ARCHIVE"
```
可信ZIP SHA取自本地冻结回执，不从待验ZIP现算一个值再称可信；空缺时只留存未绑定结果。
回收前先读summary.json与report.md绑定头，按`package_id/input_digest/return_id/URL/article_date`定位对应冻结包；不得按最近Chat会话或同目录最新文件配对。90与58等来源数量差异先查文章/包身份，再核数量差异。必须取回五个原始文件；缺项如实登记。不同return_id或不同字节保存成新版本，不能覆盖此前文件；同批`artifact_sha256`必须一致。
若仅有报告，省略结构参数，REPORT_ONLY_ARCHIVED并列明缺失；不伪造空附件。
输入旧v1包可作历史原字节留存，不能无声升级为v2。

### 0.3 阅读与报告
默认OCR_RISK_REVIEW完整读正文/OCR，关键事实核原图并对NO_EVENT抽查；用户要求全图时用FULL_ORIGINAL_REVIEW。九章报告的事件地图保留简短`event_chain_id`、来源编号与事件摘要索引，详细论证只在事件卡出现一次。
每个coverage `EVENT`在summary.json按`source_index`恰好有一个`PROMOTE/HOLD/REJECT/CANNOT_CONFIRM`；不得漏项、重复、写未知编号或给`NO_EVENT/UNREADABLE`处置。多个来源合并为一条事件链时仍逐来源列项。该检查只证明字段闭合，不证明事件分类或研究结论语义正确。
九章顺序不变，但事件地图按事件链合并，逐图账本进CSV，全文公司池不冒充精选排序。
公司优先级表需分列已有公司级证据和待核公司级证据；矛盾数字保留原值、单位、期间、主体与算术结果，不能勾稽就标未确认，不猜改总量。`PROMOTE`仅表示研究优先级。
研究区分框架/LOI、firm PO、交付、验收、收入、利润、回款；A/BJ与HK独立，港股通资格另核。
权威字段模板见templates/chat_research_prompt.md及baimao-method/references/wechat-report-chain.md。

### 0.4 Drive优先交接、回收与失败回退
每篇文章先核实真实Drive root、文章目录及`01_资料包`、`02_Chat回传`、`03_本地复核`的metadata和parents；每个`package_id/input_digest`在`01_资料包`内保持独立不可变版本，`02_Chat回传`按`return_id`区分，`03_本地复核`只保存复核意见。当前已知root候选`1-PbGAtNO3Vu_b-YHjHlOfrKvrKiodNNG`仅作为metadata查询提示，不写死为本篇目录或全局身份；名称/日期不能代替真实ID。
给用户一个可核验的Drive `START_HERE`链接和短prompt，指向本篇已核实目录/资料包。Chat若有真实Drive写工具可按合同写入；没有Drive写工具时，Chat/用户回传原文件给Codex，由Codex在本地留存后上传到`02_Chat回传`并记录实际provider ID/revision。不得以文件引用、文本readback或附件存在冒称Drive写入。
先查元数据；接口暴露fields时请求版本、checksum与canDownload，缺值记缺值。`raw_bytes_obtained`、`observed_sha256`、`expected_sha256`、`hash_match`独立记录；计算出SHA不等于比对通过，provider MD5不能直接比较SHA256。
原ZIP上传达到60秒超时，先查目标目录是否已有本次结果；无结果再使用相互独立的小ZIP（本例每个约2–3.5MB曾成功），不使用分卷ZIP，不重做OCR。每个分包记录成员清单`members_sha256`，并绑定原`input_digest`与原包SHA；分包hash不能替代原包身份。403先记录发生层/脱敏error reason，不猜权限或大小问题。
拿到文件引用、文本readback或Chat回传附件都不等于原字节落盘或Drive原字节往返验证。Drive失败才转受控直接文件交接，保持本地包和可信回执，不重抓、不重OCR、不重建下载原件；不默认要求用户重新上传。
相同已核文件ID/版本/来源且此前取过原字节才可跳过；版本变下载后SHA相同则跳过重复导入。
不轮询、不代发Chat、不改权限、不建立第二Drive客户端。

### 0.5 状态和最小验收
receipt独立保留bytes_archived/input_binding_valid/structure_valid/chat_claimed_complete/independent_review_scope。
metadata、bytes、hash、Chat读取、结构和语义是互不替代的状态；`UPLOADED_METADATA_VERIFIED`只证明provider元数据，`RAW_BYTES_OBTAINED`只证明保留精确字节，`CHAT_READ_UNVERIFIED`只证明回传尚未完成独立读取，结构归档也不证明语义研究。
回传生命周期事实分开记录：`RAW_BYTES_OBTAINED`（已保留精确回传字节）、`HASH_COMPUTED`（本地已计算SHA-256）、`TRUSTED_HASH_MATCH`（期望哈希已绑定可信provider文件身份或revision且与观测字节匹配）。旧消费者的`DOWNLOADED_HASH_VERIFIED`仅兼容映射自`TRUSTED_HASH_MATCH`及其可信身份/期望哈希绑定；本地单独计算SHA不得升级为该旧状态。
REPORT_AND_STRUCTURED_ARCHIVED仅表示五文件绑定/结构/原字节通过，不证明研究、完整视觉或证券映射成立。
使用新合同的可信冻结ZIP导入时，IMPORT_RECEIPT.binding记录account、biz、published_at及冻结manifest member SHA，来源标为包内manifest.json；未通过可信ZIP SHA校验时这些身份元数据标unknown/不提供。旧v2包仍原样归档，`event_dispositions_contract_status=NOT_RUN_LEGACY_PACKAGE`，不因新版prompt而升级检查。
未持可信ZIP SHA即使语法完整仍REPORT_WITH_STRUCTURED_UNBOUND；不让Chat填写RESEARCH_VERIFIED。
以同一文章试验：抓取0、真实OCR0 → 可读性检查 → 一次研究 → 原字节返回 → 重复导入跳过。
Drive小文件原字节往返、原ZIP/独立小ZIP传输、Chat读取、结构检查和语义复核分别验收；回传附件不能当作Drive往返验证，失败不得掩盖为整个闭环通过。归档与云盘镜像通过后，V4 Stage A引用登记、exact文章日API和UI展示也分别验收。未实测token只报未测量。

### 0.6 V4 Stage A研究归档展示（用户已授权的默认末步）

这是归档展示的研究只读末步，不是`LEGACY_FULL_RESEARCH`，不构建候选、不评分、不发布正式池、不更新BUY gate。只有本地原字节归档、Drive镜像及其receipt已分别通过后，才登记引用；首次将既有归档根迁移到统一路径时先备份并按现有批准处理，日常新文章不需要restart。

当前V4运行路径为：

```text
archive_root=/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/articles
data_root=/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data
```

回传导入receipt的binding是可信冻结身份字段的归档入口，包含`account`、`biz`、`published_at`和`frozen_manifest_sha256_observed`。V4可从binding使用这些字段；不要求仅为补字段把manifest单独抽出。
若显式传`--manifest`，该路径必须是归档内原始冻结manifest，且其`input_descriptor`引用的所有BODY/OCR/图片文件均须在相同归档路径下存在。只复制manifest会造成源引用缺失。源引用不完整时保留`FROZEN_INPUT_NOT_REGISTERED`；它与receipt身份metadata是否齐全是两项独立状态。

在V4根目录执行现有登记器；`receipt`和可选`manifest`必须是相对`archive_root`的路径，SHA必须来自已选择的可信本地receipt/冻结manifest，不从新版OCR或待验文件补算旧身份：

```bash
cd /Users/lexi/Desktop/学习/v4_app
python -m ops.index_wechat_research \
  --archive-root "/Users/lexi/Desktop/学习/v3_system/选股池/微信公众号/articles" \
  --data-root "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data" \
  --receipt "<ARTICLE_RELATIVE_RECEIPT>" \
  --receipt-sha256 "<TRUSTED_RECEIPT_SHA256>" \
  [--manifest "<ARTICLE_RELATIVE_FROZEN_MANIFEST>" \
   --manifest-sha256 "<TRUSTED_MANIFEST_SHA256>"]
```

`status=INDEXED`或同输入幂等结果只证明V4已登记Stage A受控引用；index不是股票池。登记成功后，使用同一`article_date`核验：

1. API：`/api/v3/research/wechat/materials?date=<ARTICLE_DATE>&date_basis=article&limit=20`只返回目标文章日的Stage A归档，并核对记录身份、报告原字节和可信SHA。
2. UI：重新加载当前V4研究页面，进入“公众号研究归档”，选择同一`article_date`和文章，打开报告；页面显示的文章身份、日期和报告内容必须与本地原件一致。

`V4_STAGE_A_REFERENCE_INDEXED`、`V4_STAGE_A_API_VERIFIED`、`V4_STAGE_A_UI_VERIFIED`分别记录；归档、Drive镜像、登记、API和UI任何一步失败都分别报告，不冒称默认闭环完成。旧9.17引用保持不可变；同文章新版不能替代冻结包的旧身份。

### 0.7 历史链隔离
以下旧章节仅为历史操作资料。需要用户明确选择LEGACY_FULL_RESEARCH，且任何发布/API/UI需要独立授权。
“完整白毛报告”不是legacy选择。旧依赖缺失不补造；默认不加载旧selector/池构建/页面测试，不重启任何服务。
所有路径保持RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE；production_allowed=false、buy_gate_updated=false、orders_sent=false。

### 0.8 默认前篇全文提及表现附录

每次默认Drive/Chat交接都准备前篇公众号提及上市代码的单日表现附录。附录是独立包外文件，不进入当前冻结 ZIP、`input_digest` 或五个Chat回传原件；同时绑定前篇可信 `IMPORT_RECEIPT.json`、package_id/input_digest/ZIP SHA/`mentions.csv` SHA，以及本篇 `PACKAGE_RECEIPT.json`、package_id/input_digest、观察日、运行指针发现回执、市场日历和逐日行情receipt。不得修改已冻结包。

前篇按可信 receipt 中真实时区化 `published_at` 和文章日选择，禁止用mtime、目录排序或文件名猜身份。默认严格选择昨天的文章；若昨天没有文章，可引用最近更早文章，但必须展示真实文章日并标为“较早参考”，不得称为昨天。同一日期有多篇时各自保留身份并分别出表，不按mtime静默选一篇。没有可信文章或 `mentions.csv` 时逐行保留 `CANNOT_CONFIRM`。

表现表覆盖前篇 `mentions.csv` 中全部有效上市代码，按 `(market, code)` 去重并分A、BJ、HK；不能只展示PROMOTE、推荐、涨幅靠前或白毛精选。收盘值按同一 exact-date 源中的 `(close / pre_close - 1) × 100%`；盘中值必须另带价格字段、时区化精确 `as_of` 和来源，不能和收盘混算。它是逐上市代码的单日描述性价格变动，不是策略/组合收益、候选排序、正式池或BUY信号。

每次生成前，先从当前已加载的 scheduler runtime 配置记录 selector pointer、panel receipt root、HK asset root 和 pointer 实际目标，保存 append-only 的 `runtime_pointer_discovery.json`，至少含 `observed_at`、读取来源、退出码、环境变量绑定和 pointer target。后续严格按“当前已加载 runtime配置 → 当前配置的 pointer → exact observation_date 行 → 同日期 receipt/manifest”读取并校验SHA。目录名含 `v35` 不构成过期证据；从其他目录查不到某一文件，也不能得出行情全局缺失结论。若 runtime 证据、pointer、exact 行或 receipt 任一层缺失/不匹配，就保留具体市场或代码的 `CANNOT_CONFIRM`，并记录实际检查路径；不换第二来源。

A/BJ默认读runtime selector pointer指向的selector-ready parquet，并要求 `a-<OBSERVATION_DATE>.json` receipt精确绑定同一目标、同一SHA和日期；逐代码核对 `trade_date/ts_code/market_type/close/pre_close/pct_chg`。receipt整体为 `PARTIAL` 时，只使用可唯一匹配且字段可复算的代码，并同时披露receipt覆盖分母和sync authority；无行、重复行或涨幅不闭合的代码逐只标 `CANNOT_CONFIRM`。HK按runtime配置的asset root读取 `hk-<OBSERVATION_DATE>.json` → manifest → panel parquet，核对实际SHA、receipt/manifest SHA和日历确定的前一HK交易日面板。只有当前面板 `parent_panel_sha256` 与前一交易日receipt面板SHA相同，并且当前面板前收与父面板前一交易日收盘一致时，才报原始收盘价格变动。若提供方没有公司行动/复权因子证据，明确写原始未复权价格变动、不含分红、复权未知且非官方涨幅；不把HK前收说成未经核验的provider pre_close。

主控用以下现有脚本命令生成JSON、Markdown及机器可查receipt；命令为只读数据探测和派生文件输出，不会抓行情、写共享状态或修改冻结包：

```bash
"<V35_RUNTIME_PYTHON_WITH_PYARROW>" scripts/wechat_yesterday_performance.py appendix \
  --prior-article-dir "<PRIOR_ARTICLE_ARCHIVE>" \
  --current-package-receipt "<CURRENT_PACKAGE_RECEIPT>" \
  --obs-date "<OBSERVATION_DATE_YYYYMMDD>" \
  --runtime-config-evidence "<RUNTIME_POINTER_DISCOVERY_JSON>" \
  --calendar-json "<MARKET_CALENDAR_JSON>" \
  --out-dir "<LOCAL_APPENDIX_EVIDENCE_DIR>"
```

运行时路径由当前已加载配置 evidence 提供，不硬编码旧snapshot目录。把独立附录的真实Drive链接、SHA及前篇/本篇身份放入本篇 `START_HERE` 交接，不要修改已冻结package。Chat核实身份绑定后，将附录放在第一章结论后作为非编号小节，保持九章结构；缺失或不可信时也在该位置附市场覆盖分母和逐行 `CANNOT_CONFIRM`，不自行查其他源、不做涨跌挑选。

## 1. 旧版完整流程目标（显式 LEGACY_FULL_RESEARCH）

输入一个公开微信文章链接，输出可恢复、可审计、日期安全的全文提及股票池和白毛研究报告，
并在当前 8873 V3.5 公众号观察预选页完成真实可见性验收；页面日期与来源日期必须分开记录。

固定边界：`RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE`。

## 2. 权威路径

| 项目 | 路径 |
| --- | --- |
| 本地工作根 | `C:\Users\huang\Desktop\学习\v3_system\选股池\微信公众号` |
| 原始处理管线 | `C:\Users\huang\Desktop\学习\个股\股票池\风言风语\scripts\fengyan_wechat_pipeline.py` |
| V3 构建器 | `C:\Users\huang\Desktop\学习\个股\scripts\main_scripts\build_wechat_v3_preselect.py` |
| legacy 归档根 | `C:\Users\huang\Desktop\学习\个股\股票池\风言风语\articles` |
| V3 归档 | `articles\YYYYMMDD_标题` |
| 单次运行 | `runs\YYYYMMDD_<agent>_<article-id>` |
| V3 latest pointer | `latest_wechat_v3_preselect_manifest.json` |
| 文章 latest pointer | `latest_article_manifest.json` |
| 当前运行入口 | `http://127.0.0.1:8873/?date=<EFFECTIVE_DATE>&date_anchor=<AS_OF_DATE>` |
| 当前 API | `http://127.0.0.1:8873/api/v3/preselection-pools?date=<EFFECTIVE_DATE>&limit=300` |
| 8873 运行 release | `/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/20260904T142505Z-v35-manager-workbench-reason-v3` |
| 8873 运行 state data | `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data`（只读核验，不改写） |
| 20260901 公众号输入对 | `<state data>/preselection_inputs/20260901/wechat_manifest.json` + `wechat_rows.csv`（来源 signal=20260831） |

`fengyan_wechat_pipeline.py` 是抓取、基础抽取、V3 构建和归档的现有入口，但它的成功不等于
全文覆盖或白毛复核完成。`codex_checkpoint_ocr_to_v3.py` 与
`codex_persistent_easyocr_to_v3.py` 是 OCR 备用路线，不是完整工作流控制器。

## 3. 单次任务合同

开始前在会话中冻结：

```text
GOAL: 完成指定 URL 的全文转录、全提及池、V3 发布、白毛复核和页面验收
WRITER: 当前主控唯一 Luna Max Writer（gpt-5.6-luna / reasoning_effort=max）；REVIEWER: 独立 Luna Max Reviewer；rootcoord: readonly
ALLOWED_PATHS: 本次 run、对应 articles 归档、两个 latest manifest
FORBIDDEN_PATHS: 正式池、BUY gate、交易、计划任务、未授权服务启停
PASS_SIGNAL: validate_wechat_run.py PASS + API 目标池行数正确 + 页面可见
STOP_RULE: PASS 后停止；未获授权不重启 8873 或修改运行 state
```

## 4. 状态机

```text
URL_RECEIVED
  -> RESUME_CHECKED
  -> IDENTITY_VERIFIED
  -> SOURCES_CAPTURED
  -> OCR_COMPLETE
  -> COVERAGE_1_TO_1
  -> ALL_MENTIONS_POOL_COMPLETE
  -> V3_ARCHIVED_AND_PUBLISHED
  -> BAIMAO_REVIEW_COMPLETE
  -> API_VALIDATED
  -> UI_VERIFIED
  -> HANDOFF_COMPLETE
```

任何阶段失败都保留 checkpoint；下一会话从最早未完成阶段恢复，不能从头重复。

## 5. 执行步骤

### 5.1 恢复检查

1. 在 `runs/`、`articles/`、`latest_article_manifest.json` 中按完整 URL、文章 ID、内容哈希搜索。
2. 若已有同源 run，读取 `run_summary.json`、OCR summary、coverage summary 和 V3 manifest。
3. 只补缺失阶段。已有成功 OCR、股票映射或覆盖账本不得重跑。
4. 同日期多篇文章分别保留 run，以 URL/哈希去重，不用日期覆盖文章身份。

### 5.2 抓取和身份验真

先运行基础抓取，可先跳过 OCR：

```powershell
python -X utf8 `
  'C:\Users\huang\Desktop\学习\个股\股票池\风言风语\scripts\fengyan_wechat_pipeline.py' `
  --target-date <ARTICLE_DATE_YYYYMMDD> `
  --url '<WECHAT_URL>' `
  --run-dir '<RUN_DIR>' `
  --v3-system-root 'C:\Users\huang\Desktop\学习\v3_system\选股池\微信公众号' `
  --archive-root 'C:\Users\huang\Desktop\学习\个股\股票池\风言风语\articles' `
  --skip-ocr
```

Mac 本地入口 `scripts/wechat_article_fetch.py` 默认继续使用 urllib；图片下载默认最多 3 个并发，
每图写入 `wechat_article_image_checkpoint.json`，并在复用前核对原 URL、SHA-256 和图片签名。
需要补抓失败的 HTML 时可显式使用 `--fetch-mode auto`，它只在 urllib 失败或命中验证页后尝试可选的
Crawl4AI 浏览器传输；`--fetch-mode http` 保持纯 HTTP，`--fetch-mode crawl4ai` 强制后备路线。
可用 `--image-workers 1` 降为串行、`--image-retries 0` 关闭重试。两条传输路线都回到同一身份、正文和
图片提取门禁，验证页仍然拒绝，浏览器路线不读取登录 cookie 或用户 profile。

检查：标题、公众号、真实时间、`biz`、图片数、原始 HTML、URL 和内容哈希。微信验证页不得当正文。

### 5.3 OCR：canary、持久化、增量恢复

1. 对短图、中图、最长图各选一张做 3 图 canary。
2. EasyOCR 只有 canary 在合理时间内稳定通过才可继续；默认并发 3。
3. EasyOCR 超时或模型重复加载拖慢时立即停止该路线，改用单次初始化的
   `Windows.Media.Ocr` `zh-Hans-CN` 引擎。
4. 长边超过 10000 像素的图片切片，保留 `img_NN_part_MM` 和原始图片映射。
5. 每图写 checkpoint；恢复时只处理 `OCR_TIMEOUT/OCR_ERROR/OCR_MISSING`。
6. 输出 `wechat_article_ocr_text.txt`、`wechat_article_ocr_summary.json` 和逐图结果 JSON/MD。

严禁：同时启动几十个独立 OCR 模型、因一个超时重跑全部图片、把关键词搜索当全文阅读。

### 5.4 一对一来源覆盖

生成 `source_coverage_ledger_<N>.csv|md` 和 `source_coverage_summary.json`。

每个正文块/图片必须包含：顺序、转录、`EVENT/NO_EVENT`、主体、产品层、数字单位、日期、
来源等级、上下文、反证、置信度。通过条件：

```text
captured_sources == reviewed_sources
event_count + no_event_count == captured_sources
missing_ids == []
duplicate_ids == []
```

关键数字、缩写、归属、前后矛盾必须回看原图。

### 5.5 全文提及证券池

1. 从全文和每张图提取所有 A/BJ/HK 公司，不只提白毛候选。
2. 证券简称映射要防普通词误命中、母子公司误映射、A/H 上市线混淆。
3. 输出：
   - `wechat_stock_pool_raw.csv`
   - `pool_mapping_summary.json`
   - `pool_exclusion_ledger.csv`
   - `unmapped_security_mentions.csv`
4. 无法确认时写 `CANNOT_CONFIRM_COMPANY_MAPPING`，不猜代码。
5. 若同一发行人 A/H 均需记录，必须说明原文上市线与研究派生上市线。

### 5.6 日期安全的 V3 构建和归档

1. 文章真实日期写 `article_publish_date/signal_date`。
2. 当前 run contract 要求 selector 使用与 `signal_date` 完全相等的文章日合格面板；禁止用更早日期、`latest` 或运行时当前面板补位。缺 exact 面板时，正文/OCR/覆盖/全文提及池/白毛研究仍可源研究归档，但 selector qualification、V3 build、发布和 API/UI 必须 `CANNOT_CONFIRM`。
3. 盘后文章的 `effective_trade_date` 是下一个有效交易日，必须由交易日历确认。
4. 当前构建器的 `--target-date` 使用文章日；不要误传页面日。
5. V3 只对 A/BJ 行计算观察排序；港股提及仍保留在全文池与研究报告。
6. 同步 run、legacy 归档、V3 归档和两个 latest pointer。
7. latest pointer 只能指向本次精确文章，禁止为让页面有数据而回退旧池。

### 5.7 白毛高价值复核

先生成事件卡，再分配研究深度：

1. 搜全 `PRICE/QUEUE/ALLOCATION/LEAD_TIME/OUTAGE/YIELD/QUALIFICATION/CAPACITY/POLICY/FALSIFIER`。
2. 优先研究至少同时具备两个经营信号的事件。
3. 先定位最小卡点层，再映射公司。
4. 对每个候选检查：变化、因果、稀缺、公司捕获、财务桥、一手证据、反证。
5. 标记 `SOURCE_NAMED`、`RESEARCHER_DERIVED` 或 `CANNOT_CONFIRM_COMPANY_MAPPING`。
6. 分别输出 A 股和港股通排序、立场、升级条件、失效条件。
7. 做遗漏审计：每个强事件必须 `PROMOTE/HOLD/REJECT/CANNOT_CONFIRM` 四选一。
8. 最终交付必须生成机器可校验的 `run_summary.json.event_topic_index`；它要逐一覆盖 coverage ledger 的全部 `EVENT` 来源（`source_index/event/subject`），并据此审查 `PRICE/ORDER/CAPACITY` 等主题，不得只保留精选摘要。证券实体候选还必须有 `security_entity_candidates_summary.json`、`security_entity_candidates.csv` 和 `security_entity_coverage_ledger.csv` 闭环；扫描失败或 `UNRESOLVED` 时不得以空池/validator PASS 代替。

报告默认保存到 `baimao_reader_out/master_controller_review.md`。

#### 源研究交接顺序（selector 缺失时）

当文章日 exact selector 面板尚不可用时，仍按同一个 Writer 阶段完成源研究交接，
不把人工阶段拆成多份重复收尾：

1. Writer 先冻结正文、全部 OCR 来源、逐名证券候选清单和逐名未映射清单，连同
   `security_entity_candidates_summary.json`、`security_entity_candidates.csv`、
   `security_entity_coverage_ledger.csv` 交给独立 Reviewer 查漏。Reviewer 的检查对象
   是当前冻结输入和清单；已有 `OCR_OK` 工件不因这次交接重跑。
2. Writer 可以并行查重点事件的一手证据，但不提前把未通过实体门的内容写成最终长报告或
   归档结论。实体门通过后，由同一个 Writer 一次生成 `run_summary.json`、白毛报告和归档
   所需的摘要工件；源模式只允许研究归档，selector/V3/latest/API/UI 继续保持
   `CANNOT_CONFIRM`。
3. Reviewer 在末尾只复核本批新增的摘要、日期字段、来源清单和状态差分；已冻结的完整
   OCR/来源账本沿用其既有哈希证据，不因增量复核重新阅读全文 OCR。

这是执行顺序约定。清单的机器闭环可以证明文件、计数、身份和映射账本一致，不能自动证明
自然语言候选已经穷尽；遗漏仍须由 Reviewer 对正文、OCR 和原图进行有界查漏并保留
`CANNOT_CONFIRM`。

源模式命令固定为：

```powershell
python -X utf8 .\scripts\wechat_pipeline_runner.py `
  --run-dir '<RUN_DIR>' --stage summary --source-only --resume
```

只有 source-only 前置 intake、OCR、来源覆盖、实体扫描和映射工件均通过当前检查时才生成
摘要；相同输入会输出 `SKIP_RESUME`。研究输入、报告或映射发生变化时，必须重新生成摘要，
不得只按文件存在跳过。

### 5.8 四路验收

**本地工件：**

```powershell
python -X utf8 .\validate_wechat_run.py --run-dir '<RUN_DIR>' --require-latest
```

**API（当前 8873 入口）：**

```powershell
$r = Invoke-RestMethod `
  -Uri 'http://127.0.0.1:8873/api/v3/preselection-pools?date=<EFFECTIVE_DATE>&limit=300'
$w = $r.pools | Where-Object pool_id -eq 'wechat_public_account_v3_preselect'
$w | Select-Object status,pool_size,returned_rows,target_date,date_match_status
```

必须核对目标 pool，不要误把统一页面总行数当公众号行数。

**页面：** 打开对应 `date=<EFFECTIVE_DATE>&view=preselection`，确认公众号区块、文章日期、
行数和至少 2 个预期代码/名称可见，并确认没有“日期不匹配/空池”提示。
页面的 `date` 必须是 `effective_trade_date`；`date_anchor` 只记录来源截面，不能替代 `date`。

**部署状态：** 源码测试通过但运行进程未加载时，记录 `DEPLOYED=false`；没有用户授权不得重启。

### 5.9 可选跨模型网页审核（仅用户明确要求）

本阶段不是普通微信链接的默认步骤，也不改变 5.4 状态机或其完成含义。
skill 即使因 `allow_implicit_invocation: true` 被发现或加载，也不等于外部激活；
当前请求没有明确跨模型审核/比较意图时立即记为 `ROUTE_NOT_APPLICABLE`，回到
`feed→method`，不认领标签、不预检标签页、不索取发送确认、不外发。
只有用户明确要求 ChatGPT、Gemini、跨模型网页审核或比较时，才在本地
`BAIMAO_REVIEW_COMPLETE` 之后读取并使用
`baimao-cross-model-audit`。本地文章身份、完整 OCR、来源一对一账本、
`EVENT/NO_EVENT`、全文提及池和白毛报告必须先完成；网页模型只是
challenger/auditor，不能写回 canonical 报告、映射、disposition、观察池、
正式池、BUY gate 或交易状态。

使用 `browser:control-in-app-browser`，复用已有用户标签并只做可见状态读取。
发送前必须精确核对 URL、页面标题、提供方、请求模型和可见模型/模式；
ChatGPT 必须是 Chat 而非 Codex，Gemini 按用户指定模型核对，并在要求时
核对 Deep Research。任一项无法核对，记录 `MODEL_MODE_UNVERIFIED` 并在
发送前停止。

`mode_verified=true` 只表示本地逐项比较通过：`requested_model` 必须等于
`visible_model`，`requested_mode` 必须等于 `visible_mode`；ChatGPT 的
`surface` 必须为 Chat（不得为 Codex）；Gemini 请求 Deep Research 时
`deep_research_visible` 必须为 true，且请求/可见 Deep Research 不得漂移。
任一模型、模式、surface 或 Deep Research 字段缺失/不匹配，都必须
`MODEL_MODE_UNVERIFIED`、清除确认并回到 `AWAITING_SEND_CONFIRMATION`，禁止发送。

每个 provider 还要在确认时和发送前分别记录 target snapshot：site/provider、
tab/conversation identifier、visible URL/title、requested/visible model/mode、
surface、`deep_research_requested`、`deep_research_visible`。target SHA 的计算先
排除 `canonical_sha256` helper 字段，再用 UTF-8 的 canonical JSON（键排序、
紧凑 separators，等价于 `sort_keys=True`、`separators=(",", ":")`、
`allow_nan=False`，NaN 直接拒绝）做 SHA-256；URL/title 保持
可见原值，不 trim 或 normalize，hash 只写入 local receipt 的
`confirmed_target_snapshot_sha256` / `actual_target_snapshot_sha256`，snapshot
本身不写自引用 hash。

发送前进入 `AWAITING_SEND_CONFIRMATION`，进行一次 action-time confirmation：
列出每个目标站点/标签、将发送的完整 OCR 文字、冻结 manifest/账本/报告及
最小图片集合。不得上传秘密、cookie、profile、日志、配置或未列明资料。
默认只发送完整文字稿与冻结工件；原图仅为解决 OCR、归属、边界、单位或数字
歧义的最小集合。

审核模式只能二选一：

- `FAIR_BLIND`：各提供方收到相同冻结输入和相同 core rubric，互相不可见
  对方输出；全部结果捕获后再比较。
- `ROLE_SPLIT`：ChatGPT=`SECOND_RESEARCHER`，负责反证与遗漏审计；Gemini
  Deep Research=`PRIMARY_SOURCE_VERIFIER`，核对 URL、实体、发布日期、检索
  时间和 `source_type`；文章日后的材料标记 `POST_DATE_FOLLOWUP`。

网页结果永不多数投票，最终按本地 `source_ref`、计数和边界裁决。每个提供方
每轮最多提交一次，并只做一次不超过 60 秒的有界观察；仍生成则记录
`PENDING_WEB_RESULT`、调用 `markHandoff`，下一轮从 receipt 恢复，禁止重复发送。
提示词必须要求一个 machine-readable JSON 块和简短 memo、闭合 `source_ref`、
计数回显、缺输入时 `INPUT_UNAVAILABLE/CANNOT_CONFIRM`、不猜实体/代码/数字、
不改 disposition，并保留 `SOURCE_ONLY/RESEARCH_ONLY/WATCH_ONLY/NO_BUY_GATE`
及三个安全旗为 false。详细模板和 receipt 字段见
`/Users/lexi/.codex/skills/baimao-cross-model-audit/references/prompt-contract.md`。

本阶段使用独立状态，不把网页生成完成、HTTP 200、标题或停止按钮消失当作内容
验收：

```text
LOCAL_READY → INPUT_FROZEN → TAB_PREFLIGHT_VERIFIED
  → AWAITING_SEND_CONFIRMATION → SUBMITTED_ONCE
  → RESULT_PENDING / RESULT_CAPTURED → RECONCILED
```

receipt 至少保留 `audit_id`、`round_id`、`provider_attempt_id`、provider、
conversation URL/title、请求/可见模型模式及验证；并保留
`confirmation_required`、`confirmation_status`、`confirmation_at`、
`confirmed_targets`、`confirmed_payload_manifest_sha256`、
`confirmed_text_files`、`confirmed_attachments`、`confirmed_minimal_images`、
`actual_payload_manifest_sha256`、`payload_matches_confirmation`。每个确认的
文本/附件/最小图片必须带路径或名称与 SHA。发送/观察/恢复字段还包括
`send_attempt_count`、`sent_once`、`submitted_at`、`observed_at`、
`observation_count_in_turn`、`observation_wait_seconds`、`handoff_marked`、
`handoff_at`、`resume_from_receipt`、`resend_blocked`、`status`；发送 gate 必须
同时满足 `confirmation_required=true`、`confirmation_status=CONFIRMED`、
`payload_matches_confirmation=true`、
`actual_payload_manifest_sha256=confirmed_payload_manifest_sha256`、
`target_matches_confirmation=true`、
`actual_target_snapshot_sha256=confirmed_target_snapshot_sha256` 和
`mode_verified=true`，且 `confirmation_at` 存在；变化必须重新确认。
另保留 prompt 版本、输入 manifest/content/evidence hashes、原始响应路径/SHA、
JSON parse 状态、source/event/no-event/disposition/pool echoes、缺失/重复/非法
refs、变更代码/映射/数字/disposition、errors 和
`production_allowed=false / buy_gate_updated=false / orders_sent=false`。
target snapshot 还必须分别记录 `confirmed_target_snapshot` 与
`actual_target_snapshot` 及其 canonical SHA：每个 snapshot 含 site/provider、
tab/conversation identifier、visible URL/title、requested/visible model、
requested/visible mode、surface、`deep_research_requested` 和
`deep_research_visible`。只有 `actual_target_snapshot_sha256` 等于
`confirmed_target_snapshot_sha256`、`target_matches_confirmation=true` 且
`mode_verified=true` 才可提交；任一站点、提供方、URL/title、模型、模式、surface
或 Deep Research 字段漂移都清除确认并回到 `AWAITING_SEND_CONFIRMATION`。
网页 provider 的 `BEGIN_MACHINE_JSON` 只承载研究响应、输入回显和边界证据；
confirmation、target、payload、send/observe/handoff/resend 字段全部由本地
receipt 记录，不能要求 provider 自报本地生命周期。
该阶段的结果与 `ARTIFACT_VALIDATED`、`LATEST_POINTER_VALIDATED`、
`API_VALIDATED`、`UI_VERIFIED`、`NATURAL_VERIFIED` 分开报告，不能替代它们。

## 6. 交付格式

最终答复按以下顺序：

1. 是否完成，以及文章标题/日期。
2. 来源覆盖、OCR、全文证券池 A/H 数量。
3. V3 matched/unmatched、API 行数、页面是否可见。
4. 白毛最高价值卡点和研究排序，不把它们伪装成全文池。
5. `CANNOT_CONFIRM` 和真实部署缺口。
6. run、股票池、覆盖账本、白毛报告、run summary 的可点击绝对路径。
7. `production_allowed=false / buy_gate_updated=false / orders_sent=false`。

## 7. 快速失败与恢复

| 失败 | 动作 |
| --- | --- |
| 微信验证页 | 保留失败摘要；用公开页面/已授权可见浏览器获取正文，不伪造 |
| OCR 全部超时 | 停止 EasyOCR 路线；换持久化 Windows OCR，不继续堆并发 |
| 少量超时 | 只重试失败图片；成功项不动 |
| 股票过少 | 回查全文覆盖、OCR 歧义和普通词误命中；不拿白毛 shortlist 冒充全文池 |
| selector 无文章日面板 | 保留源研究与全文提及池；selector qualification、V3 build、发布、API/UI 保持 `CANNOT_CONFIRM`，不得使用旧日期、`latest` 或当前面板补位 |
| 页面空池 | 检查 exact latest pointer、文章日/生效日合同、API 目标 pool；禁止 fallback 旧池 |
| 页面有股但日期旧 | 区分 manifest 正确、源码已修、运行进程未加载；未经授权不重启 |
