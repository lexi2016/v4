# A股研究面板数据、接入与异常处置 SOP

本文件是人工处理和验收规则。它不代表全部程序已实现、候选已部署或自然日更已通过。用户入口、数据 owner 和 completion 事件均沿用 V4；金融研究保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。

## 1. 先确定故障在哪一层

| 层次 | 要核实的事实 | 处理方向 |
| --- | --- | --- |
| 研究数据层 | 同证券、市场、报告期、来源及其原始字段是否存在；行情目标日、复权、公司资料与历史事件各自的来源和 SHA 是否可追溯 | 数据确缺时走原 owner 的增量采集或物化；来源未认证、过期或冲突时保留 typed gap。 |
| 看板接入层 | 原数据存在时，产品清单、代次、分片、API 投影和页面字段是否实际绑定并解释同一事实 | 修复有证据的引用、字段映射、校验门或展示；不得因为页面空值重新抓取已有源。 |
| 规则或样本限制 | 公式有无确定约定、历史长度是否足够、同根高低先后能否确定、事件收益是否成熟 | 按证据保留 `UNKNOWN`、观察期或未成熟；不补零、不倒推缺失事件，也不把新股观察期列为坏数据。 |

先记录症状、证券、交易所、目标日、数据层原值和实际可见页面。源更新日、采集日、报告期、公告披露日和行情日期分别记录，不互相替代。已有同日同源、同公式、同身份的有效产物优先复用；不同代次的材料须由原 owner 重新核实身份和引用，不能绕过门禁拼接。

## 2. 全 A 范围与既有异常登记

以目标交易日的权威证券名单、原行情 owner 的目标集、selector/backtest 和现有研究索引作集合对账，逐项记录新上市、停牌、退市、旧码映射、缺目标日和资料接入缺口。名单完整性做机械全检；日期、证券身份、口径及页面语义按风险抽检。不能用 20 股测试名单当全 A 分母，也不能把索引 `READY` 当作可交易或买入资格。

现有记录优先复用：

1. 日更同步记录在原 owner 的 dated `summary.json` 和其 `progress_path`；按证券、原因和有证据的事件生效日查找。目标日无行情的目标日期是**观察日期**，不能伪造成事件生效日。历史回执、原行情和已通过记录不覆盖、不重复建账；新证据沿原 owner 的合同及版本机制追加。
2. 北交所旧码映射沿原 owner 的 `ops/a_share_bse_old_new_code_crosswalk.csv`；退市和待复核状态沿 `ops/a_share_lifecycle_notes.json`；具体日期的例外处置及新增退市事实沿 `contracts/a_share_daily_source_policy.json`。以上资产有来源和 SHA 约束；同时核 scheduler 的实际进程路径与 `V4_RESEARCH_PANEL_A_SYNC_SCRIPT` 指定的同步脚本及其资产，二者可以位于不同目录。再在同一源码 owner 提交候选及配套校验，不能直接手改运行副本或历史 progress。
3. API 的 `apps/api/v4_api/a_share_lifecycle_notes.json` 是说明侧资产，其用途与 main 的同步处置不同。两边分别核路径、SHA、用途和实际调用；不能因其中一边存在便断言另一边已更新。
4. 已有清越 `688496.SH` 的停牌起点和待复核记录。旧核验截止后的状态仍为 `CANNOT_CONFIRM`；新的公告是可追加的证据，不得复制同一事件或把旧公告推成当前持续停牌、复牌或退市结论。目标日缺行情与财报是否可读分开处理。

2026-10-30 的一次冻结核对：G2 候选索引有 5,839 个代码，包含旧目标集 5,808 及 31 个额外代码。31 个已有对应上市公告及当日有效行情来源记录；这不证明正式入口已接入，也不证明该候选索引已穷尽当日全部证券。G2 的 268 个 `UNKNOWN` 代码与原同步登记完全重合：232 个旧码、30 个退市、5 个目标日无有效行情、1 个状态待复核。232 个旧码对应的新码中，230 在该候选索引为 `READY`，2 个仍为 `UNKNOWN` 且已在退市记录中；代码数不能当作新增缺数据证券数。另有三只既存候选在该索引之外，必须纳入原名单对账，不能因不在索引中忽略。[原记录的来源补充](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/THREE_LISTING_FINDINGS.json>)中，001381 的 11 月 2 日公告载明 11 月 3 日上市，回顾性可将 10 月 30 日归为上市前；688827、920085 的发行日程支持目标日仍处发行阶段，上市首日未证实。920085 的来源索引日期与公告落款日期不一致，须分别保留。后发证据不得倒称目标日已知，原登记由原 owner 增量处理，不另建权威名单。

本机证据：[31 个代码与上市资料对账](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/ALL_A_UNIVERSE_31_RECONCILIATION.json>)、[268 条原登记交叉核对](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/ALL_A_EXCEPTION_RECONCILIATION.json>)。它们是审计回执，不能替代原登记或作为线上指针。

## 3. 按根因恢复

| 问题 | 原则与所需修复 |
| --- | --- |
| P01、P02：评分计算 | KDJ 使用合法复权序列时允许有限负值，并保留原 J 一致性检查；收盘比较和 24 日 BBI 按合同使用有限、同口径前复权值，不以必须大于零误拒合法序列。保留收盘比较方向、BBI 原公式及两位小数规则，收盘等于 BBI 的既有未决边界仍为 `UNKNOWN`。阳线按已确认的收盘与开盘规则计算，不附加未定义量能条件。修原评分 owner 并回归受影响分项。 |
| P03：历史已有但未显示 | 用现有同股、同日期及身份匹配的历史分片和 SHA 重新绑定；复用已物化事件与收益，不因换入口重算全部历史。 |
| P04、P09：股东数据 | 户数与统计截止日必须同源。仅当同一已核 F10 文件 SHA、旧行明确为该 F10 的 native 投影、数值一致且正文有期时，可隐藏重复旧行；日期仍只属于正文，不改原始数据。异源、数值不同或来源身份未证时，分别标明来源与日期。“不变”须按原文与可核前值解释，缺期不冒充新期。修既有解析和投影，保留来源差异。 |
| P05—P07、G01：公司资料 | F10 正文中有主营、名称或报告期时，核源后接到 host 和页面；异步资料更新须重画对应标题。来源无绑定不等于公司资料不存在；优先复用已存 F10，缺项才由同一 F10 owner 补齐。 |
| P08、G02：财务及现金流 | 已有公司材料中的收入、归母净利、现金流、期间、单位和披露资料逐项核对；原表已有净额不得因新字段名或类型差异被误丢。原字段含义、单位、报告期或来源不明时保留待核，不把每股现金流、增长率、净利润或来源更新日替代净额和披露日。 |
| P10、P11：历史统计解释 | 展示命中、有效分母、未成熟、缺价、非正价格以及未知位置等实际分类；保留原计算和未知值，不把未知收益或未知分位填为零。 |
| P12—P15：原因、读取和来源门 | 分别显示可计算性原因；大包沿既有分块读取；来源未通过校验不能显示为已核；区分 F10 正文更新、native 财务更新与实际采集。数据来源日不等于公告披露日。 |
| G03、G07：新股或短历史 | 以所需窗口、上市日和实际有效 K 线记录观察期；不足时保留未知，不补造数据，也不隔离正常新股。 |
| G04：结构不明确 | 同根高低先后不可知或确认转折不足时标明原因；按已批准的结构合同处理，不靠调整阈值强行生成结果。N V1 的有效 K 线合同明确要求正价并包含比例结构，不得将 KDJ、收盘比较或 BBI 的有限值规则直接套用到 N。 |
| G05：目标日无行情 | 查询原生命周期记录与有效期，保留原始行情及缺失原因；按 owner 的目标日例外或隔离路径处理。恢复必须有对应日期、来源和状态证据，不借用其他交易日。ST 标识本身不等于停牌或退市。 |
| G06：方法规则或实现未闭环 | 区分“原方法已有说明但当前实现未量化”和“定义尚未确认”；按已批准的合同保留待核，不编造 S1/S2/S3 结果，也不以总分齐全代替其他条件。 |
| G08：研报 | 复用现有检索 owner、索引和分页；未读完续页时显示 `PARTIAL`，不能把未命中解释为没有研报。 |
| G09：历史可得性 | 文件 SHA、单页显示和当前快照不认证历史 PIT、自然运行、回测收益或交易资格；独立标注未完成的认证。 |

`UNKNOWN` 应按实际原因分别记录输入无效、样本不足、合同边界或规则未闭环等状态，不能一概称为数据缺失或方法未定义。

- KDJ 的既有合同按原始输入行序列及同口径 HLC 递推，不因成交量为零增加过滤；保留零量原记录，也不能仅据此推断停牌、复牌或行情错误。若 KB J 未生成是因为与 B1 共用了成交量或昨收门，应沿原 KB owner 按既有 HLC 序列生成受证 J，再经原评分绑定和一致性门使用；B1 的原有成交量、昨收和买点条件保持不变。不足 KDJ 所需历史或 HLC 无效时仍为 `UNKNOWN`，其他图形或独立计算的 J 不直接替代 KB 绑定字段。[301468 单股来源诊断](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/301468_KB_J_DIAGNOSIS.json>)保留旧缺口及原始输入证据；源码修复与受影响项回补应另以对应候选回执确认，不以该诊断宣称已完成。
- 2026-11-02 候选增量中，[KB J 回执](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/kb_j_bulk_r1/RESULT.json>)记录 645 项就绪、零失败；[收盘比较与 BBI 回执](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/negative_score_bulk_r1/RESULT.json>)记录 650 项就绪、零失败，两集合重合 642 项、合计 653 项，保留原 B1、事件、行情和历史收益。该结果属于候选来源及评分修复回执，不代表代码独审、预览切换、页面验收、正式部署或自然运行已通过。

## 4. F10、公司材料及来源时点

- 原 F10 路径是 `ops/research_panel_f10.py`，由既有 `ops/research_panel_top200.py` 日更完成链调用。先核目标、来源代次、input/selector SHA、collector 版本和既有 checkpoint；扩大名单时，`scope_sha256` 等身份不匹配就不能强用旧 checkpoint。2026-10-30 这次实际默认 scope 取旧 snapshot 的 5,808 个代码，不含 G2 多出的 31 个；原函数拒绝 scope 外的显式请求，须通过同一 owner 及来源身份合同扩展，不能仅运行默认参数就宣称全 A。当前产品索引中的 F10 `COMPLETE` 仅对应明确列出的 3 个样例。只通过原 owner 合并有效引用并补真正缺项，失败项保留原因，不建第二 producer 或在 GET 请求中抓取。
- F10 目录存在但正文返回空时，应保留证券、市场、目录文件名和字节范围、源端点及实际异常，不能直接判定源无资料。当前 SDK 默认可能吞掉解码异常；本批 000408 的目录声明 32,301 字节，已观测端点首次返回 30,720 字节且恰在 GBK 双字节字符中间截断。使用既有 SDK parser 按目录的字节范围分块、核对各段实收长度，合并后一次严格 GBK 解码和核身份，已对该例通过；不能逐块解码后忽略或替换不完整字符。端点单次返回上限须依据实测，不当作已认证的通用协议常数；短读、解码失败或身份不符时保留 `UNKNOWN` 并沿原 owner 增量恢复。[分块原始正文回执](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/f10_content_diagnosis/000408.SZ/CHUNK_PROBE_RECEIPT.json>)与[已保存正文长度核对](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/f10_content_diagnosis/OBSERVED_LENGTH_CENSUS_20261102T054618Z.json>)记录了失败样本和候选短正文；因旧 owner 会去除 NUL，重编码长度差本身需结合原字节复核，不能将全部差异自动定性。修复后只补受影响证券，原 checkpoint 与历史分片保留，并按新旧适配器身份验签复用。
- 2026-11-02 的本批候选：25 条原失败和 10 条旧正文缺尾已定向重取；[35 条来源回读](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/f10_content_diagnosis/REPAIRED_35_SOURCE_REVIEW.json>)逐条核对了新分片、字节长度与 SHA、严格解码、证券身份及 checkpoint 绑定。10 条旧短正文均与新完整正文的前缀一致，目录声明长度未变。新候选回执记录 5,571/5,571 为 `OBSERVED`、零失败；这一来源范围不是页面、代码独审、正式部署或自然运行的验收，实际采集于目标日之后，也不认证历史 PIT。
- 北交所已观察到的样例使用文本 market 0、财务 market 2，并各自核代码/市场身份；样本通过不等于全北交所来源或所有字段均已认证。
- 原公司材料按 `company_materials` 索引、证券分片、`source_generation`、`input_sha256`、`numeric_manifest` 和来源核验读取。2026-10-29 既有 247 条材料中已有 `financials_reported.latest_operating_cashflow`、报告期、日期和单位，字段值是字符串，原来源标 `SECONDARY_REPORTED`。当前单股消费路径使用的 `operating_cash_flow`、数值类型和净额口径检查与其不同；先确认原材料、单位、报告期、来源等级和代次，再由原 owner 规范映射。原 `docs/handoffs/a_daily_dashboard_closure_20261029/readable_stock_materials/prepare_c9.py` 展示了这些分片如何使用原 owner 的 `checked/save/digest` 和白名单投影；该脚本固定 D29，并包含历史索引写入，不能直接作为现役全 A 采集器运行。不得把 D29 产物伪装为 D30 原生材料，也不得把二级资料标成官方原文。
- 已授权的公司资料补缺沿同一个 daily-product owner 扩展：先复用可核的 247 条既有材料和 19 条已有官方样本，按当前证券/市场和原报告期保存来源等级、URL、SHA、原单位、实际采集日与原始日期；剩余证券再按受证名单增量查询同一来源，续跑只补缺项和受修订影响项。旧交付的一次性 `fetch_public.py` / `normalize_materials.py` 仅作字段与查询契约参考，不另行运行成平行 producer。旧 247 条中有 198 条曾报告官方同页值与标签机械匹配、49 条未匹配；该记录不等于本地原件可用、逐表审核或官方认证。
- 二级财务源的 `RPT_F10_FINANCE_MAINFINADATA` 中，旧材料把 `NETCASH_OPERATE_PK` 标作经营活动现金流净额，报告期和来源声明披露日分别来自 `REPORT_DATE` 与 `NOTICE_DATE`。扩展时应核 `SECUCODE` 和交易所、原始值、币种、期别及所有返回分页，并保存来源响应及 SHA；日期时间精度不够时不推断收盘前可得。对照、限速、失败和重试沿原 owner 的可观测配置执行；旧脚本的历史并发数不是供应商当前额度保证。[沪深北三只已存样本 canary](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/eastmoney_canary/CANARY_RECEIPT.json>) 的同报告期净额与既有官方原件一致，但该结果只证明三项对照和接口返回，来源仍为二级且非 PIT。
- F10 的 `finance_native_raw` 是 SDK 返回结果，不能仅凭字段名认定未转换的协议值。当前安装的 pytdx 对若干金额字段有统一乘数；样本中存在量纲差异和正文/财务更新跨期。19 份发行人对应期间对照及协议边界见[现金流单位专项复核](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/NATIVE_CASHFLOW_UNIT_REVIEW.md>)；这些对照不证明协议单位或 SDK 字段自带报告期。未经协议单位、净额口径和该字段自己的报告期证据，不得全市场统一缩放或用正文日期补 native 报告期。条件不满足时标 `CANNOT_CONFIRM`，待同源口径和期间证据就绪后由原 owner 修复。
- 财报金额应保存原文数值、单位、币种、合并或母公司口径、年初累计期间、原件 SHA 和页码；原文仅写“元”时不宣称表头明确写了人民币。营业总收入、营业收入、归母净利润、净利润分别命名。官方索引日期与公告文字日期不同或披露时刻未知时，保留各自来源与差异，不把任一日期自动认证为收盘前可得。
- 本批 19 只有行情样本的官方现金流事实和 20 股 F10 来源可复用；它们是来源证据，不是全 A 认证。既有 F10 概念文件与 G2 六位代码可匹配 5,159 项，但仅含概念信息，不能当成完整公司或财务覆盖。[来源覆盖清点](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/ALL_A_F10_COMPANY_INVENTORY.json>)注明范围和身份。更多证券优先检查已有的受约束来源和投影，不能因样本有 PDF 就对全市场重复抓取同源文件。
- 批量绑定历史事件和收益时，逐股原样保留 shard 中完整的 `source_index` 引用，并按原 owner 的完整引用身份分组；即使 `path` 和 `sha256` 相同，有无可选 `bytes` 字段也属于不同的引用结构，不能合并后丢字段或放宽 owner 身份检查。遇到引用结构不一致时保留原失败回执，核对原 shard 与来源索引后使用完整引用恢复，不按单只证券硬编码，也不将传参差异误判为历史数据冲突。本批 000021 的[原失败](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/history_scope_r1/groups/0a4c782da4ee2df6/RESULT.json>)和[完整引用恢复](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/history_000021_ref_rebind/RESULT.json>)分别保留。
- 本批[全 A 历史来源盘点](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/source_sop/ALL_A_HISTORY_REUSE_INVENTORY.json>)与[候选绑定回执](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/history_scope_r1/RESULT_FINAL.json>)记录 5,571 个目标日 `READY` 项已有历史材料并完成候选绑定，其中沿用预览已有 19 项、新绑定 5,552 项；复用原 shard，未重算标签或收益。历史来源与 G2 的代次、规则、日历、价格口径和引用由原 owner 校验；该候选结果不代表实际页面、独审、正式部署、自然运行或历史 PIT 已通过。
- 研报关系检索沿原关系 owner 保留既有 Bloom 候选门，对通过来源及 OCR 逐页 SHA 校验的候选做精确文字预筛，再对命中项复核对应 PDF；共享缓存以索引和文件身份为键并有界使用，身份变化时失效。原有每窗口 32 篇、96 MiB 的 PDF 预算不放宽，按窗口续查；预算不足或来源校验失败保留待核与续查状态。新窗口可查看旧结果，但应标明索引快照、读取时刻及本次未重验，不把其当成本次已复核。当前样本中不可用 1,506 项与尚不具可验证检索条件的 23 项有重叠，不得相加或宣称覆盖完整。冷查询不得阻断评分、F10、图和切股等主数据读取；[浦发冷/热查询回执](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/RELATED_REAL_CANARY_256.json>)记录约 72 秒和 8.6 秒；[并发回执](</Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/reports/a20_review_20261102_resume/a20_repair_r5/CONCURRENCY_ASGI_CANARY.json>)覆盖评分、F10、图和切股，属于候选 ASGI 检查，不能据此宣称实际浏览器验收通过。

## 5. 执行、恢复与验收

1. 固定唯一目标、完整待处理名单、各来源身份、owner、输出目录和失败恢复点。先做受影响字段的机械覆盖盘点；同原因复用原登记和已通过校验。真实新增才按原 owner 的字段与日期登记。
2. 沿原 owner 验证、增量补齐或修复投影；先做一个代表单例，失败保留原件、错误和 checkpoint。同源 SHA 未变时不重复采集、解压或全历史重算。目标源变化、日期或身份冲突时停止该项并保留旧产品及 typed gap。
3. 修复后按完整名单机械对账来源、引用、分类和剩余项；异常状态与正常观察期分账。核原 owner 的锁、CAS、completion 和消费身份后，才能按获准范围更新相应候选，GET 只读取物化产物。材料或源无证据时仍明确 `PARTIAL` / `CANNOT_CONFIRM`。
4. 全 A 处理和机械覆盖完成后，重新抽取 20 只做来源、页面、异常及边界语义检查，覆盖沪深京、银行、短历史和已知异常。抽查不能代替全 A 逐项计数或历史 PIT 认证。
5. 交付分别写明源码、独立审查、候选物化、预览 API/UI、正式安装和自然日更的实际状态；只声明已有证据的层次。无授权不改正式服务、生产指针、交易池、BUY 门禁或订单。
