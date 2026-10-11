# PROBLEM：V4 三路选股发布后的剩余问题

请读取本文件与 evidence/，基于真实运行身份修复下面问题，返回可集成补丁和针对性验收证据。不要重做已通过的整轮审计。当前交付面是本地 V4 8873；用户要实际三路股票名单及准确失败原因。

## 1. 固定日期、口径与当前基线

- 本次验收目标/计划/选股日：2026-10-09；公告来源日：2026-10-08。
- 历史视图 cutoff：2026-10-09 09:30 Asia/Hong_Kong。现在回看是2026-10-11读取后续材料的事后研究，不能冒充10/09盘前结果。
- 超跌动态页面的数据日实际为20261009；历史视图所需行情基准为20261008。先核这两个口径，不得直接混用。
- 已部署候选：release-candidate-20261011-r1；manifest SHA f2940d02d408b52bde35258b2366e32a4b7e3ad59193b313b243677d590eae1d。发布时PID3299、cwd及8873监听一致；本文件不是后续实时进程状态承诺。
- 唯一canonical源码：/Users/lexi/Desktop/学习/v4_app。已部署app：/Users/lexi/Desktop/学习/agents调试/V4_THREE_LANE_LOCAL_INTEGRATION_20261011_R1/release-candidate-20261011-r1/app。
- 私有GitHub基线：lexi2016/v4，分支codex/three-lane-local-integration-20261011-r1，提交6955d7069c7098a7a3a68c0a6617975dac920eb1；剩余问题 https://github.com/lexi2016/v4/issues/34，HK数据依赖关联#32。
- runtime_source是实际已部署且独立验收代码；canonical_source是保留本地已有改动后合入的代码，完整集成仍有缺口。请先核对身份再改，不能整文件覆盖。

## 2. 已确认的页面结果

| 路线 | 现在回看结果 | 未完成部分 |
|---|---|---|
| 公告 | PARTIAL：55研究候选、32条件观察、73未评估；owner receipt VERIFIED | 产品真实available_at为2026-10-10T17:09:10Z，晚于10/09 cutoff；55不证明历史盘前选股成立 |
| 港股通 | CANNOT_CONFIRM；无可核验正式名单，数量未知 | 动态缺口HK_ORIGINAL_STAGE_DATE_OR_MARKET_MISMATCH；历史HK_ORIGINAL_STAGE_SELECTION_NOT_AVAILABLE |
| 超跌 | PARTIAL：214研究候选、286观察、34待核 | run_id/product_sha256缺失、attempt NOT_VERIFIED、formal_selection_input=false，量纲/历史仍有37个gap |

55与214在修复发布前已存在，不是本轮新选出的股票。formal/focus没有可核验名单；不能解释成成功扫描后的有效0结果。历史视图三路仍CANNOT_CONFIRM。

## 3. 按顺序处理的问题

### P1：历史读取失败必须定位到具体原始条件

修复前HISTORY_RUN_BYTES_BOUND_EXCEEDED；修复后仍SOURCE_FAILED，原因变成HISTORY_SOURCE_VALIDATION_FAILED。优先从workspace_history.py中异常转换、原计划验证、exact owner attempt journal和cutoff路径定位。该通用错误不是已查明根因。保留当前64MiB/32MiB/64-run界限和晚attempt规则；不能靠放大阈值、忽略坏来源或使用晚到计划补历史来通过。

预期：指出具体source/run、失败字段或合同和复现；完成最小修复。如确实无法恢复原时点证据，应返回可追溯不可恢复结论和清晰页面原因，而不是承诺历史选股已恢复。

### P1：动态旧计划仍STALE_INPUTS_CHANGED

旧run acf0f1ed3e824237a562ebbf7b656b8d、consumed=false。API变化组件见API_RESULT_SUMMARY.json；实际页面也显示stale。区分本次语义迁移带来的身份变化与真实来源变化。沿原Manager owner形成具有真实事后cutoff的新计划，再验证同输入连续读取稳定。只修已证明的无关全局manifest抖动；保留日期、市场、具体payload/receipt SHA与PIT绑定。不得强行让旧身份相等或隐藏stale。

预期：原owner新run/product/receipt、API consumed/readback、重载UI一致；输入确实变化时仍能准确判stale。

### P1：HK正式名单的原owner与数据依赖未闭环

10/08 panel存在；单位证据NOT_PROVEN。权威索引缺10/08 security-master，现有10/09快照晚于开盘；10/09 canonical D-1 Top100未产出、receipt EXPECTED_MISSING。现有10/08 Top100 signal_date=09/30，不能替代。详见owner-data-audit.json。

预期：仅沿已有authority/owner核exact-date source、D-1池和Stage manifest/receipt/artifact三件套。能恢复则保留真实来源/available_at/run/SHA并验证页面名单；无原时点证据则明确10/09不可恢复及缺件，不造第二producer，不将BACKFILL放入formal。

### P1：超跌缺少可消费的来源身份及量纲证据

214只是研究台账候选，34只历史/量缺件，全局量纲未证。核原owner的60个完整交易日、前5个完整交易日成交量、来源单位、逐股coverage，保留缺失/null和来源SHA。补采沿已有tdxpy/TDX链并先读docs/hk_history_backfill.md，不默认消耗Futu历史额度。

预期：原owner产物和run/product/receipt可核，日期及量纲正确；输出实际股票与逐股理由、待核原因。未验证前保持PARTIAL与formal_selection_input=false。

### P1：canonical与发布版本的源码/接口集成差异

已直接核实：runtime workspace_plan_autorun.py有owner_plan_readback，canonical该文件没有；canonical中部分新增测试因此导入失败。补充快照已含这两份依赖，不能只拿workspace_history单文件修。另attention映射测试返回空cards，是否本批引入尚未确认。

预期：在保留canonical既有US owner、日期绑定等功能的前提下，修复具体接口/调用兼容；仅针对已变行为独立复跑。不得把已部署候选与canonical混称同一已验代码。

### P2：已存在的公告未评估与自动链路边界

公告73项未评估保留逐项原因，不将未评估算未入选；已有有效owner导入回执不重复导入。独立HKEX目录仍未运行/覆盖未知，Eastmoney不能代替。scheduler/自动binding固定旧US发布根，本轮API发布没有同步改它；后续自然时段需独立验收。

## 4. 复现入口

- 历史页面：http://127.0.0.1:8873/manager-selection/?date=20261009&plan_date=20261009
- 现在回看：同页选择“现在回看”，URL带view=dynamic。
- GET /api/v4/manager/research/workspace?date=20261009
- GET /api/v4/manager/research/workspace?date=20261009&view=dynamic&selection_date=20261009&announcement_date=20261008
- GET /api/v4/manager/research/announcements/analysis?date=20261009&publication_date=20261008

证据摘要带响应SHA、状态、计数与运行身份。本包不含原始行情、巨型API响应、账号、配置环境变量或凭证；详细原产物在原owner本地。context是相关文件快照，不是完整可运行应用，缺真实依赖/数据时必须明确记录，不得加离线shim冒充验收。

## 5. 实施和交付要求

先冻结唯一目标、Writer/Reviewer、精确允许路径、PASS/STOP。先处理历史读取/动态身份/canonical接口，再按独立数据依赖处理HK与超跌；一个阶段一条可证伪验收，不反复跑整套。单例通过再扩相应范围。保持V4页面、布局和工作流；保留Vibe8910。

返回：具体根因与最小修复说明；基线身份、文件before/after SHA、可应用增量补丁；准确命令/环境/结果和独立Reviewer receipt；每路实际名单/计数/run/product/来源/待核原因；部署/API/UI/natural分别标状态。云端无法本地部署就明确未执行，交由原本地主控集成验收，不自评全部完成。未解决数据缺口列出原owner需要提供的准确产物，而不是笼统要求补数据。

研究边界：RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。真实交易、模型门禁、第二底板或新权限均不在本问题授权中。
