# V4→V5 迁移执行计划：先贯通三策略业务，再完成隔离交付

状态：**迁移执行计划定稿，事实更新至2026-10-10最新独立验收报告。** 本次提交仅包含本文，不修改产品、不应用修复补丁或扩大发布范围。页面整理已上线；业务接线、真实审核返回和自动运行的完成情况分别登记。

依据：固定总计划 `24c6d60d`（完整 SHA 见附录），代码观察基线 `e9c94a13a1407449a16b3fa731bd0ef46867cf34`，分支 `v5/module-isolation-20261008`。原总计划保留，不覆盖历史。本文调整执行方式和证据账，不重新定义策略、不猜进度百分比或工期。

## 1. 交付对象与当前判断

交付对象是用户原来使用的业务：可靠来源进入原算法，结果保存后能在普通 API 和原页面读到，并按原时段持续更新。18 个模块是职责边界，不是要求重写 18 套算法、启动 18 个 HTTP 服务或新建 18 个页面。

现在不能说“V4 全好”或“V5 全坏”。V4 有成功产物、调度回执和成熟算法，也有原合同、资料、PIT 和页面断点。V5 已保存大量原源码闭包、增加隔离调用与部分真实接线，但不少适配器只验了录制/合成输入，尚无来源生产→业务计算→发布→自然更新的证据。继续增加孤立 helper 不会自动补齐这条链。

以后每次工作必须绑定下文一个模块的验收记录，或首批三策略贯通的一处具体断点。先用真实输入做业务等价对照：完整代码集合、次序/分数、理由、有效空、未知、原拒绝码均逐项比较；只允许封装、身份、存储位置与展示组织的预先列明差异。原实现本身失败时，记录原失败并交唯一 owner 修复，不以新算法绕过。

## 2. 编号与证据规则

本文 **01—18、P0—P5 一律沿用 24c6d60d**。早期 `V4_V5_MODULE_AUDIT_20261009.md` 的编号不同，不能直接拼接其进度：

| 总计划编号 | 早期盘点编号 | 模块 |
|---|---|---|
| 01/02/03 | 01/02/03 | A/HK/US 来源 |
| 04 | 10 | 研究情报与归档 |
| 05/06/07/08/09/10 | 04/05/06/07/08/09 | A预选/HK预选/A阶段/HK阶段/A复盘/HK复盘 |
| 11/12/13 | 11/12/13 | 盘中研究与研究复盘/视频/公告 |
| 14/15/16/17/18 | 15/14/17/16/18 | 超跌/US映射/公开资料任务/尾盘跟踪/经理计划 |

证据分为：**S 源码事实**（本轮静态读取，可定位），**R 已有报告**（仓库文档或研发负责人转述的 Mac 结果，本轮没有重跑或读取全部原日志），**U 未知**（没有足够材料）。S 不等于部署同版本；R 不自动覆盖当前 HEAD。模块只设一条主验收记录 `M01`…`M18`，下面的各项只是该记录的字段，不能分别计完成。

每条验收记录必须含：固定代码/原 owner SHA、Mac 环境与锁、目标日/信号日/资格日/US session、真实输入来源 SHA 与取得时点、运行触发类型与起止、原产物及同 run 的独立读回、API 和页面证据、自然接续证据、单模块回滚结果。`fixture`、`RECORDED_INPUT_REPLAY`、`MANUAL_RECOVERY`、自然运行分别登记；测试数不相加。不沿用初始“0/18”作今天的状态结论；以下逐项登记已有成果及未完成。当前也没有把18项全部判为完整验收的证据。

### 最新已证成果与剩余问题

独立验收已完成原01—18编号盘点。下文逐项列出现有成果及缺口；未重核的活动源码、运行身份和原始回执引用标为待核，不把历史快照当现役系统。

- **页面已上线：** `e9c94a13a1407449a16b3fa731bd0ef46867cf34`于2026-10-10 10:02:54北京时间上线。62/62测试、typecheck、build、headless桌面/手机通过，新旧4组API哈希不变。公告selection404、10月12日analysis503仍缺，10月9日analysis200。页面成功不等于公告生产或自然执行成功。
- **经理与公告修订工程链：** 外部修复候选 `2bfb4c8c5f770122077e3baf914cf5b05b8a2450/handoff/v5-blockers-fix-20261010-r1` 的Mac经理84项、e06d126项通过。独立current_recovery、host submit/poll和修订绑定工具的工程结果已有证；真实业务仍待原reviewer返回，不认定真实导入、普通业务读回或自然链完成。
- **超跌身份与真实模型：** 新身份回归18项通过，原回归77通过/4跳过，显式启用验收38通过/1跳过；各套结果分别记录，不相加。身份检查与真实model已通过。私有child随后因panel的trade_date为int64、raw为string触发ArrowInvalid，child未发布，原193项资产不变。下一步只处理该已确定的小兼容问题。
- **归档规模：** 2058条记录，实际34份产物、69个文件。读取有证，取得时间合同仍缺；记录、产物、文件不混计。
- **US：** 四键保存、读回和页面已有证；行业材料与其余19仍未齐。外部候选附录停留在旧7a3d3bc阶段，不覆盖当前成果。四键不等于完整US两路径。

### 源码路径约定

- `C/` = `handoff/v4-running-source-20261005/canonical/`，固定历史 V4 源码，不能冒充 Mac 当前活动字节。
- `M/` = `V5/vendor/manager_plan_baseline/`，当前 V5 固定原经理闭包；逐文件来源见 `V5/contracts/manager_plan_source_manifest.json`。
- `V/` = `V5/src/v5_shadow/`；`W/` = `V5/ui/manager-workbench/`。
- 其他 vendor 按 `V5/contracts/*source_manifest.json` 或 `*capsule.json` 指向。闭包内固定文件不因“迁移”而任意改算法。
- 独立来源模块若没有确认的用户 API，直接写未核；不为填表编造端点。页面/按钮出现也不能证明背后 producer 成功。

## 3. 18 模块逐项底账与唯一验收

### 01 A行情与公式面板来源 — M01

- **V4入口/生产者（S）：** `C/ops/a_share_daily_sync.py::run_sync`；`ops/macos_research_panel_daily.py` 的 `run_windows_a_sync_authority`、`run_windows_a_formula_authority`、`run_v4_a_formula_offline`、`run_scheduled_lanes`。同步与公式计算分别核 owner，不把面板文件当采集器。
- **输入/算法：** 原 A universe、日线/VIPDOC、provider 响应、字段/单位规则及原公式；Windows authority 与 Mac 调用边界存在，当前可用绑定 U。
- **输出/持久化：** 原日线、公式/selector-ready 面板、pointer 与 runtime receipt；实际活动根、generation/SHA 待 Mac 登记，不猜共享目录。
- **API/页面：** 下游 D-1 池、阶段及 A 复盘使用；独立来源 API 精确路径 U。原 UI 入口来自旧盘点，不等于本轮点击成功。
- **调度/成功（R）：** 10/9 盘点记录 A 面板17:00配置、10/8 17:11:35成功；不是本轮自然更新证明。
- **V5复用/接入：** `input_snapshot.py`、`snapshot_recording.py`、`provider_evidence.py` 有来源读取/记录/规范化能力；没有证据表明已经接管真实 A 日生产。89/128等历史工程测试不能证明采集接通。
- **最新独立实地盘点（R，2026-10-10）：** 已有来源适配；每日生产闭环未证。
- **缺口/下一步：** Mac 给一套当前原生产入口+活动源码SHA+来源/面板/receipt索引，先消费现有有效产物；仅缺原件时由原 owner 补采。
- **唯一退出 M01：** 同一真实交易日来源→原公式面板→05/09消费身份一致，下一适用日接续；坏单位/缺行情明确拒绝，既有成功不被重试覆盖，来源 owner 可单独回滚。

### 02 HK行情、主表与资格来源 — M02

- **V4入口/生产者（S）：** `C/ops/macos_research_panel_daily.py::collect_hk_futu_rows/run_hk_0_2_authority`；`ops/collect_hkconnect_close_snapshot.py::collect_close_snapshot`；原 `load_verified_hk_security_master` 通过 HK 预选闭包复用。
- **输入/算法：** 原 HK quote/daily/panel、证券主表、目标日 Connect 资格、HK证券日历；主表参考日与目标资格日分开，原量纲和规模证据不省略。
- **输出/持久化：** 原 panel/master/membership 及 manifest/receipt，三者不是可互换产物；实际今日生产根/发布关系 U。
- **API/页面：** HK预选、阶段、复盘、经理超跌/资格消费；独立主表/资格 API 活动地址 U。
- **调度/成功（R）：** 旧盘点 HK面板17:20配置，17:20:03成功；全链/半日未验。早期20261008 native master限定查找曾缺；独立验收最新确认已有master恢复读回证据，具体来源日与该历史缺口是否对应仍须按回执核对，不将“恢复有证”推成全部来源/资格齐备。
- **V5复用/接入：** `capture_master.py`、`membership_reader.py`、`native_identity_reader.py`、`hk_membership_recovery.py`；22项主表合成验收等仅工程证据。7a3d3bc 的 optional native root 接线有 Mac11/11报告，不能据此认定当前资格已核。
- **最新独立实地盘点（R，2026-10-10）：** HK master恢复读回有证；来源完整性及目标资格仍缺。
- **缺口/下一步：** 给当前可用参考日 master、价格历史、资格各自实际回执；超跌私有修复被身份门拒绝归冻结问题3，不在这里绕过。
- **唯一退出 M02：** 三日期、取得时点、单位与权威 identity 经原 reader验证，并被06/14真实消费；价格可用而资格未知时保持不同状态，次日自动接续及独立回滚成立。

### 03 US行情来源 — M03

- **V4入口/生产者（S）：** `C/ops/run_us_market_slot.py::run_us_market_slot` 调原 workload；`ops/us_market_digest.py` 及 `_us_market_digest_parts`；`infrastructure/research_peripheral_store.py::ResearchPeripheralStore` 保存/读取。
- **输入/算法：** 原配置标的/行业代理、provider报价、phase、US session与美股日历/DST；33只是已见配置样本，不是全市场定义。
- **输出/持久化：** digest payload、manifest、receipt及session身份；`M/v4/manager_research/us_market_bridge.py::project_us_market` 是验证/投影，不是采集器。
- **API/页面：** `C/apps/api/v35_api/research_lane_router.py::us_market` 路由后缀 `/us-market`；经理 `us_market_attention`。活动完整挂载路径由 Mac确认，不推测前缀。
- **调度/成功（R）：** 旧配置04:15/05:15/21:00/22:00，22:00记录NOT_DUE；另有真实33/33恢复报告，不等于自然抓取成功。新批数量需独立验收固定run证明。
- **V5复用/接入：** US闭包和 `V/us_mapping_daily.py` 已验证并消费既有三文件；`current_us_research.py` 取真实当前时钟和原 session context，**不采集来源**。
- **最新独立实地盘点（R，2026-10-10）：** 33只报价读取有证；自然采集未证。
- **缺口/下一步：** 原 fresh-source slot→不可变三文件→V5 request 的真实绑定仍需证据，不能把 reader 成功当 producer迁移。
- **唯一退出 M03：** 原slot真实运行，三文件同session且取得不晚于消费cutoff，15两路径消费同来源；错session/缺报价保留未知，下一适用session自动更新和旧成功保留。

### 04 研究情报与归档 — M04

- **V4入口/生产者（S）：** `C/ops/run_hourly_research.py::run_hourly_research_file` 调 `domains.research.build_research_archive`；`ops/collect_hourly_research_input.py`、`ops/import_research_archive.py` 和原周边物化链。
- **输入/算法：** 原报告/新闻/公众号/正文/图片/OCR、原归档 reader与研究材料规则；来源发布时间、实际取得时间与文字span分别保留。
- **输出/持久化：** 原 archive/material/周边产物与 provenance；各输入lane活动writer、不可变成功版本和读取索引仍需 Mac逐项确认。
- **API/页面：** 原 ResearchView、DailyResearchCommandView；具体每lane API/按钮与后台对应 U，不以HTML200代替。
- **调度/成功（R）：** 旧盘点LIVE_HOURLY，缺registry/OCR等；21:40日物化21:42:06成功但API仍有gaps，非所有资料链成功。
- **V5复用/接入：** `archive_reader.py` 固定原读取闭包接经理；只读 archive 接线不包含抓取/OCR/小时更新生产。
- **最新独立实地盘点（R，2026-10-10）：** 2058条原归档记录读取有证，对应34份产物、69个文件；取得时间合同仍缺。记录数不是有效研究命题、产物数或全量来源通过数。
- **缺口/下一步：** 先核13/15所需那份真实材料的正文、原取得回执与身份；三篇知识社区帖涉五只A股、无US对手方，不作为US关系。不存在历史时间不得补造。
- **唯一退出 M04：** 至少一个真实常规触发归档和失败后续跑，完整原文/缺失图片状态不丢，11/13/15消费同SHA；再覆盖原各lane范围，不能一篇恢复就报全模块完成。

### 05 A预选池 — M05

- **V4入口/生产者（S）：** `C/ops/materialize_scheduled_preselection.py::build_scheduled_artifacts/publish_scheduled_artifacts`；原 `domains.preselection_materializer` 与 PreselectionPoolStore事务。
- **输入/算法：** 01/04及原 V192、FUPAN、Stage7、公众号、白毛、hourly research、research preview 共七A来源build；原聚合/去重/分数次序保持，坏可选lane只隔离自身。
- **输出/持久化：** 原各子池及正式池发布；不能为新reader伪造bundle/producer字段。复盘→翌日池是跨日依赖，不是同日死循环。
- **API/页面：** 原D-1预选池；完整活动pool API路径与当前发布指针 U。
- **调度/成功（R）：** 17:30/18:00，旧18:00 UPSTREAM_NOT_READY；历史找到过原池，但不足证明当天读写闭环。
- **V5复用/接入：** `run_a_preselection` 只读五lane（v192/fupan/stage7/wechat/baimao），不发布正式store；17项及旧145全套的报告只覆盖对应提交。**七池不等于五lane适配完成**。
- **最新独立实地盘点（R，2026-10-10）：** 原30行实际产物存在；真实回放遭来源拒绝。不是无池，也不是V5真实接线已通过。
- **缺口/下一步：** 核当前真实池与reader合同；先处理现有产物读取，再补hourly/preview和正式聚合消费。原verified-empty与validator不兼容单独记原缺陷。
- **唯一退出 M05：** 七来源适用状态齐备，完整合法集合进入原阶段consumer；有效空与缺源不同，某lane坏不清健康lane，真实翌日更新、API/UI及回滚同一发布身份。

### 06 HK预选池 — M06

- **V4入口/生产者（S）：** 同原 scheduled materializer中的 `build_hk_pool`、`build_shared_hk_0_2_pool`，依赖02的原模型/主表和严格reader。
- **输入/算法：** 固定HK02模型/权重来源、全输入面板、目标日/信号日/资格日、原排序；不是只搬100条JSON就证明新池生成。
- **输出/持久化：** 原Top100/manifest/receipt及正式池store，权重字段SHA不代替实际权重校验。
- **API/页面：** D-1 HK池及HK阶段消费；当前API根/活动生成器版本待Mac核对。
- **调度/成功（R）：** 原预选槽同上；真实新日Top100生成成功证据本轮 U。
- **V5复用/接入：** `run_hk_preselection` 固定原reader/build，保存全部100行与次序的读取适配；不调用SDK、不加载权重生成新池。
- **最新独立实地盘点（R，2026-10-10）：** Top100读取候选已有；真实新池生成未证。
- **缺口/下一步：** 先给已有真实合格池+三日期+权重/receipt，做原reader与V5结果对照，再绑定原generator；错日拒绝不得改成fallback。
- **唯一退出 M06：** 原新日Top100生产与独立读回真实通过，08消费同identity；资格未知不捏造、全部100行未截断，连续适用日及单模块回滚留证。

### 07 A阶段选股 — M07

- **V4入口/生产者（S）：** `C/ops/run_stage_center_tick.py`、`run_stage_center_nodes.py`及 `_run_stage_center_nodes_parts/stage_dispatch.py`；原 `stage_center.selection` 的live/auction分路。
- **输入/算法：** 05合法汇总池、原实时五价/昨收/量额、news/research分数、对应阶段窗口录制；阶段分数与BUY门不改。
- **输出/持久化：** 原stage结果、selection artifact/ledger/receipt；具体当前活动存储发布与竞价writer须Mac确认。
- **API/页面：** 原阶段选股A页和经理阶段航迹；活动普通/竞价路由与参数矩阵 U。
- **调度/成功（R）：** 旧报告若干阶段PARTIAL_WITH_ROWS、尾盘CANNOT_CONFIRM；loaded/exit3不是正常自然运行。
- **V5复用/接入：** `run_stage_selection` 调 `select_a_live_stage` 的录制适配；显式拒绝竞价，不把普通阶段wrapper称全阶段。
- **最新独立实地盘点（R，2026-10-10）：** 非竞价回放有证；竞价及自然执行链仍缺。
- **缺口/下一步：** Mac列普通/竞价/尾盘各原执行入口和窗口证据；先一真实普通窗口贯通，再填全部合同，不用当前行情补早盘。
- **唯一退出 M07：** 每个原A阶段（含竞价/尾盘）真实窗口输入→原结果→保存→阶段页一致；缺窗口记错过/恢复身份，09可追溯，自动接续与隔离回滚成立。

### 08 HK阶段选股 — M08

- **V4入口/生产者（S）：** 原stage tick/dispatch，`stage_center.selection::select_hk_four_lane`及独立竞价、Stage8入口；后二者当前精确活动函数/绑定 U。
- **输入/算法：** 06池、02实时与Connect资格、四价/涨幅/量比/流通市值/量额及候选lane，原HK日历。
- **输出/持久化：** 原stage artifacts与ledger/receipt；Stage8不冒充七阶段归因。
- **API/页面：** 原HK阶段页、经理阶段航迹；活动路由/Stage8按钮需要Mac矩阵。
- **调度/成功（R）：** 旧阶段部分有行，竞价/Stage8全链成功 U；半日窗口未核不能推导。
- **V5复用/接入：** `run_stage_selection` 只含普通four-lane录制回放，拒绝竞价和Stage8独立回放；来源SHA声明不是真实来源资格。
- **最新独立实地盘点（R，2026-10-10）：** 非竞价回放有证；竞价/自然链与HK富化仍缺。
- **缺口/下一步：** 对每窗口绑定原录制/collector和池日期，补竞价/Stage8实际owner调用，保持不同市场源独立。
- **唯一退出 M08：** 原全部HK窗口含竞价/Stage8有同日同源结果与普通页面证据；10七阶段引用正确，半日未知拒绝，自然更新及跨模块无扰动回滚。

### 09 A收盘复盘 — M09

- **V4入口/生产者（S）：** `C/ops/run_v35_close_review_slot.py`、`run_v35_close_review_node.py::run_node`；`domains/a_share_close_model.py::build_close_model`为确定性原模型，不等同12视频链。
- **输入/算法：** 01全声明当日面板、07阶段证据及12正式材料可用部分；不是阶段Top10替代全市场面板。
- **输出/持久化：** 原A模型/复盘产物和正式材料；阶段缺失保留PARTIAL，实际各文件writer/活动root待Mac补充。
- **API/页面：** 原review router `/review`、ReviewView；完整服务前缀及混合A/H发布隔离需Mac核对。
- **调度/成功（R）：** 16:05/17:10槽，旧最近17:11:41成功；15:30是输入门，不是计划触发；PARTIAL_STAGE_EVIDENCE及正式多产物缺失仍在。
- **V5复用/接入：** `run_a_close_review` 调原build，录制/合成输入，CANNOT_CONFIRM与legacy_status分列；不是每日原producer迁移完成。
- **最新独立实地盘点（R，2026-10-10）：** A核心回放有证；新日完整正式输出未证。
- **缺口/下一步：** 用原当日全panel与模型输出做等价对照，复用原publisher并分清12依赖缺失；禁止校准/改原常量来改善结果。
- **唯一退出 M09：** 两槽各自输入/产物身份可核，原模型字段等价、阶段/材料缺口真实；普通复盘API/UI、后续适用日与独立回滚成功。

### 10 HK收盘复盘 — M10

- **V4入口/生产者（S）：** `C/ops/collect_hkconnect_close_snapshot.py::collect_close_snapshot`、原close node；`domains/close_review.py::build_native_close_review`。
- **输入/算法：** 02真实全声明收盘集合、06 Top100、08七阶段；原Top20及覆盖归因，不把Stage8补成七阶段。
- **输出/持久化：** 原close review产物、manifest/receipt；已有旧成品与新日计算必须分开登记。
- **API/页面：** 原review API与HK收盘时间线首项；其余10个时间线项旧盘点为提示页，不能顺带算已交付。
- **调度/成功（R）：** 活动盘点16:10、10/8 16:12:07成功且缺七阶段；旧canonical16:08等待16:10，不据此恢复旧触发；半日未核。
- **V5复用/接入：** `run_hk_close_review` 原算法回放；`run_review_bridge` 真实旧副本Top20/100/0及缺7读回有44b514a Mac6/6报告，曾接日期目录/API，非新计算。
- **最新独立实地盘点（R，2026-10-10）：** HK旧成品预览有证；新计算和七阶段证据未齐。
- **缺口/下一步：** 先对照已验旧产品，后用原新日collector→算法→publisher→同API，缺阶段保留PARTIAL。
- **唯一退出 M10：** 一个新真实收盘日全链及下一适用日自然更新，20/100/七阶段每项可追溯；与A同URL仍可单模块回退，不覆盖09。

### 11 盘中研究与研究复盘 — M11

- **V4入口/生产者（S）：** `C/ops/run_intraday_research.py`→`domains.intraday_research::capture_intraday/read_intraday_day`；`ops/run_research_review_generation.py`→`domains.research_review_generation.assembly::assemble_runtime`。
- **输入/算法：** 04已提交研究材料、原slot配置及当时可用市场/阶段证据；不把收盘后材料假装盘中已知。
- **输出/持久化：** 原slot快照、日研究总结/产物与attempt；实际完整路径、runtime binding及writer U。
- **API/页面：** 研究复盘和DailyResearchCommandView；各slot接口/按钮当前实际映射待Mac确认。
- **调度/成功（R）：** 旧盘点日文件及六slot缺失；不能由研究物化一次成功推出全slot成功。
- **V5复用/接入：** 源码可复用；当前未发现对应独立 `research_review_daily.py` 的实现；经理attention只读投影不替代本模块。
- **最新独立实地盘点（R，2026-10-10）：** 归档运输已有，但不等于独立盘中研究/研究复盘生产。
- **缺口/下一步：** 先记录一个原slot真实输入和持久化结果，再逐槽接续原执行器；不先写通用研究生成器。
- **唯一退出 M11：** 原slot集合及日总结的时点/引用/结果读回正确；中断能续原步骤、缺slot可见；研究页面与下一适用触发留证。

### 12 视频FUPAN — M12

- **V4入口/生产者（S）：** `C/ops/check_bilibili_fupan.py`、`capture_bilibili_fupan.py::capture_locked_video`、close node的video_download/video_session/stock_dictionary/video_alignment/video_gap/fupan_publish步骤。
- **输入/算法：** 原视频、ASR/OCR、股票字典、对齐与原报告规则；媒体凭据和可用运行绑定未在本轮验证。
- **输出/持久化：** 原逐步骤缓存、转写/OCR/对齐及正式发布证据；不能把最后一步失败清空前置成功。
- **API/页面：** 收盘时间线/复盘FUPAN入口，旧多数提示项无完整页面；真实可操作API/结果页 U。
- **调度/成功（R）：** 旧20:30—21:15多槽，至21:10步骤成功、21:15上游未就绪，不是整链成功。
- **V5复用/接入：** 原源码仍在；未发现独立video_fupan_daily执行实现，A模型回放不覆盖此链。
- **最新独立实地盘点（R，2026-10-10）：** 原步骤证据不齐，不能判定视频全链完成。
- **缺口/下一步：** 由Mac给一套不含媒体正文的节点run/状态/SHA索引和现有入口；先从实际失败节点恢复，不重下/重转成功媒体。
- **唯一退出 M12：** 同视频原节点完整发布与读回、失败恢复不重做前置成功、页面可定位每步；按真实业务触发验收，不强制编成日任务。

### 13 公告研究与选股 — M13

- **V4入口/生产者（S）：** `C/ops/run_manager_announcement_cycle.py`、原服务 `refresh_announcements`；e06d闭包 `run_manager_daily_announcement.py/run_v5_offline_analysis.py/run_v5_decision_revision.py` 的准备、review、导入链。
- **输入/算法：** 原公告目录/正文、实际publication/capture/cutoff、Reader语义决定、独立Reviewer与修订父产品绑定；不重做已验392条决定来逃避修订门禁。
- **输出/持久化：** 原analysis、owner receipt、consumption validation、不可变revision及经理输入；可读analysis不代表已被计划消费。
- **API/页面：** 普通 `/api/v4/manager/research/announcements`、analysis路由与经理页；发布验收报告selection404 ROUTE_NOT_CONFIGURED、10/12 analysis503 MODULE_RESULT_NOT_AVAILABLE、10/09 analysis200，分别保留，不能统称“公告0条”。
- **调度/成功（R）：** 9426a1b Mac17/17及真实analysis已存在；历史冻结包e06d10+7测试有报告；最新2bfb4c8c的Mac经理84项、e06d126项工程链通过，真实revision仍待原reviewer补充返回。不是自然采集→语义→经理整链通过。
- **V5复用/接入：** `announcement_bridge.py/announcement_analysis_api.py/announcement_offline_reader.py/daily_announcement_revision.py` 与原闭包；`daily_owner_adapters.read_announcement_owner`、经理组装后段存在。
- **最新独立实地盘点（R，2026-10-10）：** 旧成品与新392条判定已有；修订绑定工程验证已过，真实原reviewer返回仍阻塞业务导入。
- **缺口/下一步：** 外部2bfb4c8c的reviewer绑定只读工具和host submit/poll工程链已通过Mac验证；仍待原独审真实revision acknowledgment及返回文件SHA。可调用合同已到不等于真实host通道/返回已接通，不能发明队列或模型凭据。对已有合法产品先确认cutoff消费，不重复分析。
- **唯一退出 M13：** 原目录→正文→独审导入→经理同SHA消费→普通API/页同run；已分析未消费可定位，0/null/缺源分开；真实后续日自动接续后才记完整完成。

### 14 超跌研究与选股 — M14

- **V4入口/生产者（S）：** 02原HK02面板owner；`M/v4/manager_research/workspace_plan.py::read_rebound_history/read_rebound_screen` 及固定原owner胶囊；strict/near两门保留。
- **输入/算法：** 原60/5交易日历史、收盘/前高、量/5日均量、单位/scale、完整panel/master和资格；数值满足两门不等于正式准入。
- **输出/持久化：** 原screen及strict/near/unknown、独立观察产物；私有repair child与原panel/pointer严格分开。
- **API/页面：** 经理workspace.market_screen、独立rebound_panel_observation；观察695条一类统计不能冒充候选。
- **调度/成功（R）：** 旧ebe5944e曾因身份检查误拒绝阻断；最新2bfb4c8c身份回归18PASS、原回归77PASS/4SKIP、显式启用验收38PASS/1SKIP。身份与真实model已过；私有child因trade_date的int64/string类型不一致触发ArrowInvalid，未发布，原193项资产不变。
- **V5复用/接入：** `legacy_adapter.py/worker.py/rebound_owner.py/rebound_observation.py/manager_panel_observation.py/daily_rebound_owner.py`；工程回放、观察接页不等于正式真实screen完成。
- **最新独立实地盘点（R，2026-10-10）：** 五只真实代码算术有证，身份与真实model验收已通过；private child的trade_date兼容故障仍阻断发布，正式准入仍缺。不能把五只结果推为全panel成功。
- **缺口/下一步：** 由现有本机修复流程对panel int64/raw string的trade_date兼容问题制作最小候选并独立核对；不重开外部问题包、不另起重复修复。保留严格日期/身份/量纲门禁，修复后验证child发布与独立读回、原193项资产不变；不放开694批量。
- **唯一退出 M14：** 正确原owner身份通过且篡改仍拒绝；真实原两门输出与独立读回一致，unknown不填0，18消费同run；后续适用日、UI及回滚补齐。

### 15 美股到港股映射 — M15（两条路径都在范围内）

- **V4入口/生产者（S）：** `M/v4/manager_research/us_mapping_research.py::build_daily_run/persist_daily_run/read_workspace_mapping` 是已审种子daily路径；材料路径为 `workspace._compute_workspace`→`issuer_us_relations.material_us_relations`→`research_evidence.collect_attention_evidence/us_mappings/us_mapping_diagnostics`→`research_attention.build_research_attention`。
- **输入/算法：** 03精确session与上涨行；种子路径只查原registry的daily_match_symbols。材料路径依赖04原主体/正文span、命题、真实取得时点与02 native identity，按原行业/主题及个股关系分别计算，不靠标签词汇补关系。
- **输出/持久化：** 种子daily有原store保存/独立读回；材料路径输出research_attention和us_market_attention.mapping_diagnostics，随18 workspace/plan保留。未发现可据以宣称“全市场已审关系库”的产物。
- **API/页面：** 普通经理workspace下 `us_mapping_research` 与 `us_market_attention/research_attention` 两组字段；不能用HK_CONNECT或其他lane的未评估覆盖daily已评估。
- **调度/成功（R）：** 27c7d08真实恢复33/33、2匹配报告，MANUAL_RECOVERY/natural=false/资格CANNOT_CONFIRM；7a3d3bc Mac11/11及某批四键均下跌、八上涨在范围外的有限空结果报告。独立验收最新确认四键保存/读回/页面已有证，行业材料与其余19仍未齐；具体批次run/session/SHA留在Mac证据索引，不把这些数写成固定配置或全市场结论。
- **V5复用/接入：** `run_us_mapping`、`us_mapping_scope.py`、`native_identity_reader.py`、`current_us_research.run_current_research`与经理实际接线；8a667188当前目标驱动只接原owner→原保存→dynamic读回，不证明普通auto历史问题已修。
- **最新独立实地盘点（R，2026-10-10）：** 四键保存、读回及页面有证；行业材料路径及其余19尚未齐，不是完整两路径迁移完成。
- **缺口/下一步：** 四键（LITE/COHR/AVGO/CIEN）对应三可匹配HK卡，另两宽主题卡无daily键；它们不等于完整15。材料路径必须用原可验证资料证明接通或准确说明拒绝，不新造关系/时间。两个路径的来源与覆盖各自验收。
- **唯一退出 M15：** 真实同session的种子路径及原材料两类映射均有独立结果/拒绝证据、保存/普通页面一致；范围外未知、目标资格与自然身份保留；两路径未齐不将M15判完成。

### 16 经理候选公开资料任务 — M16

- **V4入口/生产者（S）：** `C/v4/manager_research/service.py::ManagerResearchJobService.ensure/ensure_events/retry/job/cancel`，通过原provider/任务机制运行。
- **输入/算法：** 原固定候选、公开资料与事件更新规则，调用身份/可用provider绑定 U；不让页面GET暗中创建新研究任务。
- **输出/持久化：** 原job/product/receipt与事件状态，`M/v4/manager_research/store.py` 具有原读回接口；实际当前writer/队列版本 U。
- **API/页面：** 原 `/api/v4/manager/research` 下 `/ensure`、`/retry`、`/events`、`/jobs/{job_id}`与cancel，ManagerSelectionView；源码曾有NOT_MATERIALIZED+can_ensure条件自动POST，不能称所有原页面操作天然只读。
- **调度/成功（R）：** 旧任务状态HTTP500；没有本轮完整job成功/取消/重试实证，标U而非不存在。
- **V5复用/接入：** 原service随经理闭包存在，但未发现独立manager_jobs执行接管；原workspace读取不能替代公开资料job生命周期。
- **最新独立实地盘点（R，2026-10-10）：** 公告材料子路径已接部分，不等于通用公开资料jobs完成。
- **缺口/下一步：** Mac核唯一任务入口、服务绑定和实际job回执；限定一个既有候选任务验证，恢复逻辑由原job owner负责。
- **唯一退出 M16：** 一次真实任务的提交/运行/结果、失败重试、取消及事件更新各自可追踪，GET无隐式副作用；长任务不阻塞普通经理读，结果按原输入身份回滚。

### 17 尾盘量价发现与持续跟踪 — M17

- **V4入口/生产者（S）：** `C/ops/materialize_manager_close_discovery.py::prepare_universe/materialize/recapture_close_minutes`；原 `domains.manager_close_rebound` 与 `domains.manager_catalyst_tracking`。
- **输入/算法：** 原15:30窗口股票/快照/历史、资格证据及既有催化跟踪；盘后补采身份单列，不替代原15:30现场观察。
- **输出/持久化：** 原snapshot evidence、discovery/workbench payload、tracking events及receipt；首次producer与持续状态必须同一原链。
- **API/页面：** 经理close/close_recapture/跟踪区；独立当前刷新接口与调度binding U。
- **调度/成功（R）：** 旧盘点首次15:30产物/receipt缺口，未见本轮全链成功；不能用Stage或超跌结果作替代。
- **V5复用/接入：** 经理原reader与投影可显示已有close输入；未发现独立close_discovery_daily生产实现，不代表已迁移尾盘捕获。
- **最新独立实地盘点（R，2026-10-10）：** 完整owner尚未定位接入；本表列出的历史入口只是定位线索，不代表完整依赖闭包已核，更不能用超跌替代。
- **缺口/下一步：** 找原确切窗口receipt和后续跟踪读回；无窗口录制只能记错过或盘后观察，不补写现场时间。
- **唯一退出 M17：** 真正原窗口产物→后续跟踪更新→经理页理由/失效条件同identity；补采与现场分列，重复触发幂等，跨日及独立回滚成立。

### 18 经理决策账本、汇总与计划 — M18

- **V4入口/生产者（S）：** `M/v4/manager_research/workspace.py::get_workspace/_compute_workspace/refresh_workspace_plan/read_attempt/verified_plan_attempt`，workspace_history和原store；聚合消费不反向拥有上游采集/语义/筛选算法。
- **输入/算法：** 已提交04—17各自产物、原plan_context/cutoff/date绑定；可用lane独立保留，缺失不伪造成0。原筛选/排名与BUY门保持。
- **输出/持久化：** 原保存plan、同attempt/run、journal与独立读回；动态观察与历史截止前合格计划是不同合同。
- **API/页面：** `/api/v4/manager/research/workspace` GET及`/workspace/refresh`，原经理UI兼容网关；W只作展示接线，发布由唯一发布负责人执行。
- **调度/成功（R）：** 3d9541ac43单元通过，原链1PASS/1FAIL；保存成功但跨日auto历史拒绝是冻结问题1。最新发布回执确认e9c94a13于2026-10-10 10:02:54北京时间上线：62/62、type/build、headless desktop/mobile均通过，新旧4组API哈希不变；这是展示与读取等价证据，不补齐跨日/自然运行。55377ed的旧type失败作为历史保留。
- **V5复用/接入：** `manager_plan.run_manager_plan/publish_workspace_read`、`daily_manager_assembly.assemble_manager_request`、`daily_owner_adapters.run_manager_daily`；原workspace真实保存接线已存在；不是单个helper代替整链。
- **最新独立实地盘点（R，2026-10-10）：** 部分保存/独立读回/UI已有；跨日恢复工程验证已过，真实业务一致性及自然运行仍待验。
- **缺口/下一步：** 外部2bfb4c8c的current_recovery/auto读回与host submit/poll已获Mac工程链验证；仍须原reviewer真实返回及真实来源绑定，完成三策略实际产物保存和普通业务读回；每日前半链尚未证明闭合。15定向dynamic结果不能拿来取消这个缺口。
- **唯一退出 M18：** 13/14/15及其他实际已提交lane经原经理保存，普通API/页独立读回同run/SHA；当日/跨日/历史拒绝正确、缺lane不隐藏健康结果、读与执行分开、自然更新与单模块回退可核。

## 4. 执行顺序：保留 P0—P5，改变推进单位

依赖关系：01→05→07→09；02→06→08→10；03+04+02→15；02→14；04→13；13/14/15→18。04也供11/16；12给后续05/09提供材料；17有独立窗口。复盘产物进入下一交易日预选，不将跨日边强行变成同日顺序。

| 阶段（原编号） | 现在先做什么 | 进入条件与退出证据 |
|---|---|---|
| P0 执行/发布底座 | 复用已有run_ledger/daily_dispatch/module_artifacts，服务三策略保存及普通读回；不继续扩建通用平台 | 已绑定原owner与独立私有根；真实同输入复用、失败保留、未知副作用不盲重试、API同generation读回及回滚证据。代码存在不等于已安装调度 |
| P1 经理三链 | 首批必须13公告、14超跌、15US三策略业务结果可见，并经18保存及普通读回；随后补自然接续 | 三策略真实结果或原算法验证的有效空，同run保存/独立读回/API/页面一致；缺输入只算阻断，不能计业务完成。自然接续是后续完整验收门，不用四键调度替代其余链 |
| P2 来源/预选 | P1需要的02/03来源绑定提前执行；其余01/05/06随后按依赖完成 | 优先消费原成功产品，补的是owner接线；M01/02/03/05/06各自退出记录，不替换V4活动源 |
| P3 阶段/收盘 | 预选与实时输入可用后，07/08每窗口、09/10每槽贯通 | 原算法等价、新日计算与普通页、无窗口录制明确错过；半日须原活动合同 |
| P4 研究/辅助 | 04供P1所需的材料入口提前核；11/12/16/17按其真实触发逐项完成 | 原生产闭环及步骤恢复，而不是统一套daily wrapper；独立任务不抢占/拖慢普通API |
| P5 整体验收 | 汇总唯一M01—M18记录与当前固定提交回归；再做跨模块升级/回滚、自然连续接续 | 原总计划要求的两个连续适用交易日自然证据；非每日模块按实际触发。没有全部证据不得宣布全系统完成 |

P1不是等待完整P2/P4后才启动，但也不能跳过其必要输入。先完成业务等价，再把已验路径的输入快照、私有写根、进程/版本和发布指针逐步隔离；每一步都回放同一证据。已有隔离代码保留，不为追求架构整齐重新复制或重写原业务。

## 5. 首批交付：三策略业务结果可见，并完成普通读回

首批围绕 **13公告＋14超跌＋15US→18原经理计划** 交付，所需02/03/04来源按依赖接入。不能再将四键US的自然调度作为全部优先工作，延后公告和超跌真实结果。已有US保存、页面及已验计算直接复用，只修变化处。

1. **公告取得真实独审返回。** 复用已有392条决定及原semantic字节，使用已通过工程验证的绑定工具请求原reviewer真实补充；取得新文件SHA后经原owner导入、消费和独立读回。缺返回时保持阻断，不伪造PASS或反复重做语义。
2. **超跌修小兼容问题并发布私有child。** 现有本机流程最小处理panel int64/raw string的trade_date差异；核准语义一致才转换，不吞异常或填日期。复用已过身份/真实model证据，验证child与独立读回及原193项资产不变，原正式准入限制继续有效。
3. **US保留已验结果，同时标清两路径。** 四键daily结果与材料行业/个股路径分别展示；范围外未评估不能写0。当前材料缺口继续按原门禁定位，不扩种子凑结果，也不因四键通过宣告完整M15。
4. **原经理统一保存和普通读回。** 用三策略各自产物的实际目标日、来源日、cutoff和SHA生成原计划，独立核同run attempt；普通API及页面读到相同结果。工程测试通过的current_recovery须经真实产品验证；显式历史继续保留PIT门禁，不以dynamic选择替代普通读取。
5. **用户可见核对。** 公告、超跌、US各自的股票/理由/来源/日期/资格限制可见；成功、部分、有效空、未知分别展示。公告404/503须定位为路由未配置或产品未就绪，不能被折叠展示或统一0计数掩盖。

**首批退出条件必须同时满足：** 三策略都有实际原业务结果，或由原算法在已验证输入范围内得出的有效空；原经理保存和普通API/页面同run/SHA读回；坏lane不隐藏健康lane、缺输入不伪装零结果、跨日恢复身份清楚。仅有状态卡、源码/fixture通过或US四键结果，不满足首批退出。

研究结果可见不等于正式选股资格成立；资格未知、原拒绝原因与未自然验证继续保留。首批业务退出也不等于M13—M18完整迁移：US材料路径、后续适用日自然接续、单模块回滚和全范围验收仍须按各M记录完成。

首批之后再按P0/P1补真实调度与恢复绑定，并推进P2—P4其余模块；完整P5仍要求原计划规定的自然连续接续。已经取得且identity一致的计算、页面和接口证据直接引用，不为新计划重复测试。

## 6. 模块边界与三项外部修复候选的接入门槛

- 数据owner独占真实采集与发布；来源快照传引用和必要只读副本，不建立第二活动数据底板。
- 算法owner保留原规则与输出；兼容网关只转换路由/合同并读取已提交产品，不能采集或选股。
- 18只消费；13/14/15各自独立状态。US不替换HK_CONNECT，超跌不替换尾盘/Stage。
- 调度只处理依赖、时钟/slot、claim/receipt、恢复；未提供回执的进行中任务保持结果未知，不根据超时自动重跑有副作用任务。
- 职责保持单一写入和独立验收，不让多个实现者同时修改同一问题。

| 职责 | 责任边界 |
|---|---|
| 研发 | 保留原算法，编写最小接线与兼容候选，固定源码/合同/回滚说明；不代替独审出具结论 |
| 独立验收 | 在锁定Mac环境核真实来源、工程与业务结果、API/页面、资产不变及恢复证据；工程通过与真实业务通过分开 |
| 原独立审核者 | 对精确revision绑定给出真实返回，保留原决定与semantic，不由集成代码伪造身份或PASS |
| 唯一发布 | 验收后核活动身份、执行单模块切换与回滚，保留V4及其他模块版本 |
| 本机兼容修复 | 当前trade_date小故障由既有本机流程制作最小候选并独立核对；研发不另起同一问题的平行实现 |


| 修复事项 | 最新状态与责任边界 | 收回业务主线的必要证据 |
|---|---|---|
| 1 跨日经理保存与auto历史读取 | 冻结3d9541ac；2bfb4c8c经理84项Mac工程验证通过，current_recovery/auto真实业务验证待三策略产物 | 当天/跨日/历史不合格/来源变化与重复读取都保留正确身份；普通页与恢复保存同run语义明确；不改旧计划、不倒填时钟、不只改测试日期 |
| 2 reviewer修订绑定 | 冻结e06d；2bfb4c8c对应126项Mac工程验证通过；仍待原reviewer真实绑定返回及新SHA | 新审查文件SHA、原91门禁及create→prepare→register→verify→import→readback通过；不得集成器伪造PASS，不改392决定来过门 |
| 3 超跌marshal身份检查 | 冻结ebe5944e；18属性比较及真实model已通过；当前阻断转为private child的trade_date类型兼容故障，由既有本机流程最小修复 | 保留已过loader/篡改验证；解决int64/string类型差异后真实child发布反读，原193项资产及panel/pointer不变；不松正式量纲/历史准入 |

固定包 `handoff/v5-blockers-20261010/`（46081f5）原样保留。另一个独立接入项是每日source/Reader/Reviewer运行通道：2bfb4c8c已提供submit_review_task/poll_review_task/validate_review_return/preflight_revision合同，需要注入既有host对象；没有新建实际worker、认证客户端或后台轮询。channel未绑定仍须BLOCKED_REVIEW_CHANNEL_NOT_BOUND；结构校验不证明作者身份或语义PASS，等待不消耗业务attempt，未知副作用不自动重提。研发协调既有真实通道与原独审返回，不发明服务或凭据。

## 7. 回滚与不做事项

每次未来接线前记录当前模块active generation、route→generation、代码/输入/配置摘要；新产物写私有不可变目录，先直接读候选，再由唯一发布者切该模块引用。失败时用现有activation/CAS机制切回经验证旧generation，保留失败attempt；API显式旧日/旧版本，不能用“回滚”把昨日成功冒充今日。

原store若有自己的latest指针，单独登记其语义。公共run ledger保留成功并不证明原owner latest永不指向不完整结果；必须在真实演练中验证。新worker/端口切换要核运行源码与root身份，不能仅更改目录指针假定旧进程已换数据。V4所有源根/服务与8910保留，不能把迁移完成理解为删除许可。

本轮及后续不做：重写已验算法/分数、扩全市场关系库来凑数量、倒填发布时间或取得时间、用当前行情补历史窗口、null填0、以人工恢复冒称自然、将不同提交测试相加、为HTTP空重复采成功源、批量重读已审公告、同时修冻结三问题、先扩通用调度再找业务、新增18个空页面/服务、改BUY或发订单。

## 8. 执行中继续补齐的待核证据

1. **当前活动V4清单。** 18项各一个活动入口/源码SHA/真实根/下游路由；重点01/02采集绑定、05七池完整聚合、07/08竞价/Stage8、11/12节点、16任务队列、17首次窗口。本文历史snapshot不能替代此项。
2. **成功与失败的原始索引。** 已引用Mac数字均按报告记R；需固定日志/receipt引用和SHA。旧02635f1全套298与当前局部结果分别登记，不能对当前HEAD宣布全套298通过。
3. **当前US两路径证据。** 已收到独立验收逐模块摘要：四键保存读回/页面有证，行业材料/其余19未齐；本轮已核原函数。仍需在本机证据索引内引用对应run/session/取得时点，不能把未持有的完整回执细节从摘要补造。
4. **页面发布证据索引。** 已收到e9c94a13的测试/type/build/视觉及10:02:54上线回执摘要；继续登记其实际日志/部署generation/4组API哈希索引即可，不重复安排已通过的视觉验收。公告404/503没有因此解决。
5. **修复后的真实业务验收。** 经理84/e06d126为已过工程链；仍需原reviewer真实返回、三策略原产物保存与普通读回。超跌身份/model已过，需本机trade_date兼容修复、child发布读回及193项资产不变证明。跳过项保留原原因，不计通过。
6. **半日与自然调度。** 现役slot、输入门、cutoff、实际触发分别登记；没有half-day合同不猜时刻，没有下一适用日证据不提前签自然通过。
7. **范围边缘。** 8910与模型训练完整业务范围仍未知；保留原范围核对项，不删除、不私自添编号。总计划引用的 `V5/source_inputs/V5_MODULE_MIGRATION_MAP.md` 在现有源码清单不存在；须研发负责人给原索引或说明失效，不从记忆补造。

本文以已有结果为接续起点；证据不足的模块保持待核，不把计划目标写成当前事实。首批按文末列明的三个工作包推进，不另扩通用平台或重复已验业务。

## 附录：本轮静态来源索引

固定总计划完整提交：`24c6d60d524f43fcf4209ec8b078ec02cb34417e`。以下只是已读取源码/文档的SHA定位，不是运行回执；源码可沿当前基线e9c94a13及各capsule来源追溯。Python仅做AST解析定位，没有导入或执行产品。

| 仓库文件 | SHA256 |
|---|---|
| `V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md` | `daa69decc1ff83797fb20571f0bd54c5435d07109906f4a6c132918dd401d9b8` |
| `V5/docs/V4_V5_MODULE_AUDIT_20261009.md` | `4dfc285789e690806c2ff3cc7dac3dd4f5ba6506eab15d208e4a7b2816b04181` |
| `V5/docs/US_ORIGINAL_OWNER_RECONNECTION_20261010.md` | `ab762c9e19ce5d551ee4cb16bbc8e183c5693e142e6d9e58eea5460455f274c4` |
| `handoff/v5-blockers-20261010/START_HERE.md` | `f9a38f80229dabdd8aff6838242f157ea3fa341ad663e3fb391c30a4d00d41b0` |
| `handoff/v5-blockers-20261010/REPRO_AND_ACCEPTANCE.md` | `23f92f37b1927e1576576486350580c5444d08e97884fb57bc2de89a79eaa350` |
| `V5/contracts/manager_plan_source_manifest.json` | `92c445765cdfe4a76531bc4929622ef3878b58702b4a2aa3f56dc0da8b2c3767` |
| `V5/contracts/us_mapping_source_manifest.json` | `a304682e3a48114058ddbc7fcb4c3cd2a272b354d90cce25dadcfbe2a264b3d6` |
| `V5/vendor/manager_plan_baseline/v4/manager_research/workspace.py` | `8d66916ba9fddf73e81aa8e5f3411e1c3cd3421e40dcab03fb35f3f25f537b25` |
| `V5/vendor/manager_plan_baseline/v4/manager_research/us_mapping_research.py` | `297dc6f5950d3614437378c22e3157b6866823fbf25fd39cb47f112ffea40da7` |
| `V5/vendor/manager_plan_baseline/v4/manager_research/issuer_us_relations.py` | `75fdca7a3c8bc1e8f385a023d47df640f002096921d6a0f3af8ea6cc466ee00f` |
| `V5/vendor/manager_plan_baseline/v4/manager_research/research_evidence.py` | `d2539b676d5779d9369fd8aba187c0565fcc38dbb0e89596d1248668fda4a7d5` |
| `V5/vendor/manager_plan_baseline/v4/manager_research/research_attention.py` | `ccf9246193e082f6fd09e83fae0df00533c8dc0ef27ebb5f5335dfc35d76be96` |
| `V5/vendor/manager_plan_baseline/v4/manager_research/workspace_plan.py` | `c734f3e986af81b39bf11c09d93caf7a205526c8b4df940a4beeb011f74e0ebb` |
| `V5/vendor/manager_plan_baseline/v4/manager_research/workspace_daily_channels.py` | `de4e91150d3198dda40e170660de8a83c717811d478411941015b7cf1364c15f` |
| `V5/src/v5_shadow/daily_tick.py` | `d206b5497ddc37f0b66427cdc78b4b0c6984e5df7f1242a85aa7e05118137623` |
| `V5/src/v5_shadow/daily_owner_adapters.py` | `4bb109ef0a83be48a631bc295fbf2819a88f54b425eac0c21976ebb6b6dac762` |
| `V5/src/v5_shadow/daily_manager_assembly.py` | `45314cb7e179956d7f4b01d81a134bcfc3d5eb7938c34e508d72a03c59e9f29c` |
| `V5/src/v5_shadow/current_us_research.py` | `966f728556da096afd6d5be6a38869f8e7c40d7f85dd7f619c5044858ce8118d` |
| `V5/src/v5_shadow/manager_plan.py` | `ce1dec06f4d42b8b902b0f560fa8ff694c465564d06340eff0e1dd4e27a842f7` |
| `V5/src/v5_shadow/module_artifacts.py` | `07c1ab119367abbdb73363ca4f4d0af2d05e3bbef5e02be911a77a6a31f02e17` |
| `handoff/v4-running-source-20261005/canonical/ops/a_share_daily_sync.py` | `42d2ef712abca59e2d230e8a37253a08a922001d7fd88b3baa1e0e0fb7ce4b7c` |
| `handoff/v4-running-source-20261005/canonical/ops/macos_research_panel_daily.py` | `bb4db8d0cafaf43c7080439a60b986bf0ed02d4e4cb3295bde3f7ad8a266377f` |
| `handoff/v4-running-source-20261005/canonical/ops/run_us_market_slot.py` | `e2e9cf1e22844f6375948db2877f9ae73bfd5fdd6bd980bd6bf648dbf6ac43e6` |
| `handoff/v4-running-source-20261005/canonical/ops/us_market_digest.py` | `5e814bc2ddffeec45a2ed7a593d3fa20128826c7c4951e0f10a95f3bdc0f552c` |
| `handoff/v4-running-source-20261005/canonical/ops/materialize_scheduled_preselection.py` | `8e90cabbac847946151f8c6bba2696c94b556ff3d56543f0058d74e406d3dab5` |
| `handoff/v4-running-source-20261005/canonical/ops/run_hourly_research.py` | `eaf56ebec0d821fe5b8548ceeafe8070bd67245d3159f94d1431a7d87795f98a` |
| `handoff/v4-running-source-20261005/canonical/ops/run_intraday_research.py` | `26d56dd55cdfd37126d03f2e3ed81394a328b63a2f0c6bc07ccfccdb603c65b3` |
| `handoff/v4-running-source-20261005/canonical/ops/run_research_review_generation.py` | `b783bfc1c9d3c593c49a7f775c9e861767cc1f82373530536ec4df0f87e04622` |
| `handoff/v4-running-source-20261005/canonical/ops/capture_bilibili_fupan.py` | `d5a40e2dd6ddf2582cfb9547ba43c86b07cab60847b68a67d0b560b66a30e17a` |
| `handoff/v4-running-source-20261005/canonical/ops/run_v35_close_review_node.py` | `e48e27969d79a1e09f31bdd4be35fb3ade0822ee5e80e43888ceb1abe3bda856` |
| `handoff/v4-running-source-20261005/canonical/ops/collect_hkconnect_close_snapshot.py` | `901905f77532fe61674d2f423b6fab1babc86b3b6f5e3aeb5a34abce91630c76` |
| `handoff/v4-running-source-20261005/canonical/ops/materialize_manager_close_discovery.py` | `84b584713fdb1513379dd2513735d5f3a2e23cdfff9f07756526f7592de339e1` |
| `handoff/v4-running-source-20261005/canonical/v4/manager_research/service.py` | `1d1ffc81991c32aeb66b3b4704db8421a9131896bc76597f3596d4510bfbccdd` |
| `handoff/v4-running-source-20261005/canonical/apps/api/v35_api/manager_research_router.py` | `fa2f578635ed7cbbdbab0ca301a52e17101667eaa611fd8a3e1c58c545a833b1` |
| `handoff/v4-running-source-20261005/canonical/apps/api/v35_api/research_lane_router.py` | `a3a0ef464fe75cc673b1648d36f23d76b5d4b712bba39037010da050a0b6d378` |
| `handoff/v4-running-source-20261005/canonical/apps/api/v35_api/_review_router_parts/http_routes.py` | `5d0f487f7396dcefdeb4e3fdb72926327714276ce0e5f0aff26788ec91eedde6` |

外部候选补充定位（不修改原冻结包或当前产品）：

- `2bfb4c8c:handoff/v5-blockers-fix-20261010-r1/README.md`，SHA256 `88bb6241ce5b93a27c0714602a0e52d893777bdc4a5cfe54083a2e8b63c293b3`；只读文档核实，非Mac运行证明。
- `2bfb4c8c:handoff/v5-blockers-fix-20261010-r1/INTERFACE_CONTRACT.md`，SHA256 `1a119b2ca5a157d69ed94fe075301b46a712163f115ba6bc9e3d1ca6e94400f3`；只读文档核实，非Mac运行证明。

## 9. 接下来三个工作包与停止条件

### 工作包一：公告真实修订返回与经理恢复读取

- **输入：** 已有392条决定/semantic、原父产品和回执、2bfb4c8c工程已验候选及精确revision绑定。
- **工作：** 原独审给出真实补充返回及SHA；研发沿原create→prepare→register→verify→import→readback接入，验证当前恢复计划与普通读取，显式历史PIT保持。
- **交付：** 公告真实业务结果及原拒绝/未评估项、同run经理保存与普通API读回证据；不以84/126工程测试替代。
- **停止条件：** 原reviewer未返回、身份/绑定/SHA/时间不一致、原owner门禁拒绝、普通读回不是同run。停止相关导入/发布，保留阻断并允许其他独立工作包继续；不伪造PASS、不重做既有语义、不倒填历史。

### 工作包二：超跌trade_date最小兼容修复与真实child读回

- **输入：** 已通过的身份/真实model候选、失败ArrowInvalid证据、panel int64与raw string的日期schema、原193项资产摘要。
- **工作：** 既有本机流程在明确合同边界处理日期类型，验证日期语义不变且无静默缺失/强制填值；制作最小候选并独立核对，复用已过身份/model证据，验证私有child生成、发布及独立读回。
- **交付：** 原算法真实screen结果/资格限制、child run/SHA、193项原资产不变及经理可消费引用。不重新打开外部问题包，不建立平行修复。
- **停止条件：** 类型转换改变日期/行身份、输入实际日期不匹配、仍有ArrowInvalid、child读回不一致、原资产变化或正式准入门禁拒绝。停止该child发布，不松身份/历史/量纲条件，不扩大批量范围。

### 工作包三：三策略统一业务验收与普通页面收口

- **输入：** 工作包一、二的真实已提交结果，已有US四键结果及行业/个股材料路径各自真实状态，原经理代码与页面基线。
- **工作：** 原经理按明确目标日/来源日/cutoff保存三策略；普通API、页面和独立attempt读回同run/SHA；核股票、理由、来源、资格、有效空/未知，验证跨日恢复与显式历史边界。修接口接线所需的最小缺口，不增加策略算法。
- **交付与退出：** 公告、超跌、US三策略业务结果均可见，普通读回一致；US有限范围和未完成材料路径仍明确。之后才安排完整自然调度/连续接续与单模块回滚验收，不以四键自然运行替代本批其余两链。
- **停止条件：** 任一策略只有占位状态/fixture而无实际业务结果或合法有效空，404/503未被准确解决或仍无产品，保存与普通读取identity不一致，历史PIT或其他模块发生回归。健康lane可以保留展示，但首批不得签完成，唯一发布职责不得宣告三策略全量通过。

三个工作包不承诺未经证据支持的工期或完成百分比。业务范围、真实来源或原算法需要改变时先明确差异与影响；不能借迁移绕过原合同。当前文档提交本身不代表上述工作包已执行或已完成。
