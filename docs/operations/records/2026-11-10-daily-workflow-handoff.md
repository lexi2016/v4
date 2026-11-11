# V4会话交接：修复验收、每日看板与研究闭环

登记：2026-11-10。时区：Asia/Shanghai。最后一次本轮日更核查：2026-11-10 16:13:58 +08:00。本文用于新会话接续，旧PID、日期和任务状态均须在续行时重查。

## 先看这五点

1. 本轮09:25输入与读取兼容修复已部署，独审、实际安装、API及既有页面通过；首次新09:25自然运行定在下一交易日2026-11-11，尚未发生。
2. 研究日包完成后已有自动更新看板的owner/索引/事件路径；新版每日自然闭环仍待验收，不是“所有模块无条件全自动”。
3. 16:13快照中，11月10日A源回执仍FAILED，错误`QfqGateError: OFFICIAL_DAILY_SOURCE_NOT_READY`；正式日包latest_date=20261109，11月10日API为NOT_MATERIALIZED。此为当时状态，不能永久锁成今天最终结果，下一会话先查原任务/回执。
4. 每天17:00的选股交付自动化ID=17已存在且ACTIVE，原prompt已覆盖富途、逐股表现、Chat基本面/卡点/重大事项研究、旧成果归档及兼容V4回传。配置存在不证明每天都成功；本轮没有改自动化、服务或调度。
5. 新规程和本交接已加进源码`docs/SOP.md`；在线SOP读取现役封签文档，本次线上文档发布NOT_PUBLISHED，不能把源码更新说成网页已展示。

日常操作看[日更规程](../DAILY_RESEARCH_DELIVERY_SOP.md)，完整时间表在其第2节；研究用[固定Chat提示词](../DAILY_CHAT_RESEARCH_PROMPT.md)；本轮只读结果见[机器快照](2026-11-10-daily-workflow-check.json)。

## 一、用户已确认的要求

- 唯一研究入口V4/8873，沿现有正式数据owner、manifest/run/generation/SHA，不建平行面板、行情源或producer。
- A股预选池有有效可追溯股票即可汇总进入阶段选股，空/缺/partial子池只隔离自身；输入完整去重，不用页面200行当输入上限。A/HK分开。
- 数值选股、去重与未知统计先完成，再看图。已有标签/历史位置/关键K/收益缓存优先复用，只补新股、缺件、成熟或修订项。
- 研究面板、看板/工作台、原图、评分和研究建议都应保持；五分持股评分及有仓/无仓两情境建议沿原KB规则，不让基本面文字直接覆盖原评分。
- v1.9.2与原公式分别对照、独立分组。四组、全池、模型和阶段口径不混淆。
- A主要日包争取每交易日17:00前更新好，17:00准时触发交付；HK现役17:20、晚间补充及完整Chat研究时间另列，不能承诺同样17:00前全齐。
- 富途按下一观察交易日O的月日命名；最新规则不是组号逐批加一。D=20261109/O=20261110组1110；D=20261110/O=20261111组1111。休市跳过，跨年用完整O与回执区分同名。
- 每次交付全名单当日表现，并让Chat增量更新基本面、产业链卡点、三个行业二筛、实控人资本运作意愿/执行能力、三层债务套现压力及潜在重组/收购事项。调查异常交易方法，不用公开量价认定“老鼠仓”，不编重组概率。
- Chat成果回网盘后核身份/覆盖/来源，再经既有owner同步公司材料与行业二筛至看板，回读API/代表页面；不兼容先NOT_IMPORTED，不临时造第二数据层。
- 网盘先查后传、引用旧ID。2026-11-10新规则：以成功回执、ID和链接完成交付，不例行重下载/远端SHA回读；Git仍按明确合同核远端commit及关键文件SHA。

## 二、截至本轮的修复验收

以下完成状态来自各批终验记录；表内历史日期的数量不代表当前日。无需重做已匹配PASS。

|问题|已完成与证据|仍有边界|
|---|---|---|
|日期框空白/不能选，运行及前端身份待确认|发布身份/manifest一致性修复，11/9配套发布后API/页面日期切换验收通过|当前API身份重新GET为VERIFIED；本轮没有重新做整个日期页面全量测试|
|基本面明明已回包却显示未收录|11/9公司资料时点/日期精度reader修复及371份资料正式接入；未来资料/身份冲突仍拒绝|新模型独有股票需要对应有效材料；未知不可用旧日期资料硬填|
|五分评分、无仓/有仓建议消失|11/9恢复原评分/建议物化与展示；371中361 COMPLETE、10 PARTIAL_UNKNOWN的历史记录保留|不是Chat生成的分数，也不宣称所有新股都完整|
|v1.9.2只有19只、与原公式差异|20261109模型19、原公式31、交集1；单独模型组已接入|研究四组去重371与主预选池19不是同一口径，不强凑数量|
|模型独有股K线/评分缺件|17缺件补齐、2复用，19/19原图及五分评分；已部署并抽验603286/301361/301199|自然每日completion新增模型股仍待新回执；D2/D5未物化留空|
|行业二筛及回包看板更新|20261110六只增量数据独审PASS并经既有owner发布；保留365原行及原财务/评分/行情|不是对所有公司重新研究；海外时点及日本/韩国缺件仍按实际来源|
|Top200全池/阶段统计口径|11/10 Top200范围/回执路径修复，保留历史榜单/名单；36全池命中与2阶段命中已逐股追踪|11/9实际阶段仅1/7，不能把该历史缺口补成自然成功|
|09:25零开盘价被当真实价格|本轮native输入修复、可选字段未知状态、Stage/API/Main三处新旧读取兼容、owner绑定闭合；独审PASS后部署r3|观察最新价不是竞价撮合；首次修复后09:25自然运行未发生|

原终验入口：

- 11/9资料/日期/评分/独立组：[FINAL_DELIVERY.json](/Users/lexi/Desktop/学习/agents调试/v4_daily_materials_release_repair_20261109/FINAL_DELIVERY.json)。
- 模型19股图/评分：[FINAL_DELIVERY.json](/Users/lexi/Desktop/学习/agents调试/v4_v192_assets_and_dot_handoff_20261109/FINAL_DELIVERY.json)。
- 20261110海外行业二筛：[推荐说明](/Users/lexi/Desktop/学习/agents调试/v4_crossmarket_rescreen_20261110/CROSSMARKET_RECOMMENDATIONS.md)、[实际接入](/Users/lexi/Desktop/学习/agents调试/v4_crossmarket_rescreen_20261110/PUBLICATION_RESULT.json)、[API/UI](/Users/lexi/Desktop/学习/agents调试/v4_crossmarket_rescreen_20261110/API_UI_VERIFICATION.json)。
- 11/9基本面与实际图形十股研究：[既有结果](/Users/lexi/Desktop/学习/agents调试/v4_daily_materials_release_repair_20261109/TEN_STOCKS_RESEARCH_20261109.md)、[跟踪顺序](/Users/lexi/Desktop/学习/agents调试/v4_daily_materials_release_repair_20261109/WATCH_PRIORITY_20261109.md)。这是历史研究，不是11/10新推荐。

## 三、本轮09:25修复的精确结果

证据根：`/Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110`，从[REPAIR_RESULT.md](/Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110/REPAIR_RESULT.md)进入，不重跑旧测试。

- 原20261109请求487只，返回472只，全部36只总池命中股均已请求且拿到quote；不是原总池股票没传进去。
- 472条中460条open_price=0，旧映射同时把open和last写0，造成虚假-100%、分数归零；36只池命中股的34只受影响。
- 修复用有效最新价作为`NATIVE_LAST_PRICE_OBSERVATION`，未就绪开盘/高低/量额保留None和field_readiness，WATCH_ONLY/NO_BUY。正常开盘分数保持；公式系数、Top10、模型、HK和BUY门保持。
- 原472条旧分数/Top10精确复现，另一天320条回归；正常开盘12/20条未变。21针对测试与42实际依赖测试通过，两项旧provider夹具失败已在原版本复现并保留；可选字段15条完整入口增量通过。
- 新算法SHA：`15fd78695c5c0b345dcbf6b32f884320b1fb51b3f9b40876bfe83fe9655fa896`。API和Main各自源版本只增精确allowlist项；Stage历史owner上限6→7，原六项、11/6过渡保持，追加本次替换旧Main。
- 真实Main旧reader曾拒绝新产物，因此r2未部署；r3补齐后独立增量REVIEWED/PASS。实际安装24项源绑定校验通过，三个实际安装reader及Main消费者各读10行，旧Main今天09:00真实见证仍通过。
- 同一份11/9旧快照离线新Top10命中3只，原自然Top10为2只；不证明策略高命中、历史PIT或未来收益。当前历史页面保留原2/200，未用离线结果覆盖。
- 本轮两日原始快照及11/9七份自然回执共9件SHA保持。没有手工重放作业或改写历史。

关键验收：

|层级|状态|回执|
|---|---|---|
|源码/针对验证|完成|业务HANDOFF及原失败/成功证据|
|独立验收|REVIEWED/PASS|[INDEPENDENT_REVIEW_R3.json](/Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110/INDEPENDENT_REVIEW_R3.json)|
|实际部署|完成|[ACTIVATION_RECEIPT.json](/Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110/ACTIVATION_RECEIPT.json)|
|安装依赖及新旧消费者|通过|[三消费者核验](/Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110/INSTALLED_CONSUMER_AND_WITNESS_VERIFICATION.json)|
|正式API及历史模块回归|通过|[ACTUAL_API_VERIFICATION.json](/Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110/ACTUAL_API_VERIFICATION.json)|
|正式既有页面|代表验收通过|[UI_VERIFICATION.json](/Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110/UI_VERIFICATION.json)|
|首次新09:25自然运行|NOT_YET_OCCURRED|2026-11-11 09:25后查真实快照/receipt/产物/API，不强制重放|
|Git同步|已核远端commit及关键文件|[GITHUB_SYNC.json](/Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110/GITHUB_SYNC.json)|

安装后15:55自然任务：HK尾盘READY，但冗余PREP_0915因新Stage身份遇到D10旧封存READY330输入而拒绝，整个tick CANNOT_CONFIRM/exit3，不能记整槽成功。旧输入严格读取通过；17:00仅hourly，17:30/18:00预选不发布此acquisition；明天用新日期分区，未发现同类身份冲突阻断这些路径的证据。明日实际运行仍NOT_RUN。按冻结范围停止，没有为了消除单日冗余告警放宽校验、覆盖旧current或新建迁移机制。详见[只读诊断](/Users/lexi/Desktop/学习/agents调试/v4_a925_price_readiness_repair_20261110/PREP_CURRENT_IDENTITY_DIAGNOSIS.json)。

已修复的本批副作用也保留：一次基线pytest改写原Stage两件测试cache，已保存变更字节并CAS恢复封签原字节；后续测试隔离且关闭cache。没有改manifest校验或排除源文件。不要重新删除这些失败/恢复证据。

## 四、当前身份与数据入口

身份快照已于16:10通过正式frontend-build接口复核；续行仍需刷新，以下不是永远固定的当前版本。

|角色|release|manifest SHA256|
|---|---|---|
|API|v4-a925-readiness-20261110-r3-api|dec319be02f69095d5e53b6a4fc96c69b2731ecd32ba8ee31d5b7259acaa57b6|
|Main|v4-a925-readiness-20261110-r3-main|ef1fe8701ca953eab207428a0913813340588989f1fb34552efb22473a8f0d29|
|Stage|v4-a925-readiness-20261110-r3-stage|813d595dd27c2af31007e5ee9d3ddf56cadde21170f17221320db4f944c563bc|

运行候选根：`/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-a925-readiness-20261110-r3`。各role下`app`和`release-manifest.json`是封签运行版本，不能直接改。

- 唯一源码：`/Users/lexi/Desktop/学习/v4_app`；其当前`claude/v4-typecheck-budget-20261029`分支仍有其他工作未提交改动，禁止reset/clean/stash覆盖。
- 本轮实现工作树：`/Users/lexi/.codex/worktrees/a925-price-readiness-20261110`；业务独审commit `083e07706007de75de596d5dff06949065497648`；最终文档commit `63f18e6548a5fff6804377bd61b188a6ae9dda01`。
- 发布工具工作树：`/Users/lexi/.codex/worktrees/a925-main-consumer-release-20261110`；commit `9533664efef9a1e1c8f16b4e43eca020a160ef47`。两个codex分支已推既有`lexi2016/v4`，未merge。
- 正式日包根：`/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share`。先读index，再读D的manifest/artifact；不得用latest代替历史日期。
- 原producer receipt：`/Users/lexi/Library/Application Support/com.lexi.v35.local/state/research_panel_daily/receipts/a-YYYYMMDD.json`。
- 原native快照：`/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data/stage_inputs/native_opening/YYYYMMDD/STAGE_0925/snapshot.json`。
- Stage自然回执：`/Users/lexi/Library/Application Support/com.lexi.v4.local/state/stage/receipts/YYYYMMDD/<STAGE>/receipt.json`；选股产物根为同级`state/stage/selection`。
- Main使用的V35 data根和Stage V4 data根不同；这是现役既有绑定，不擅自迁根。看板消费通过统一API/合同，不新增物理副本。
- Python：`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python`。

最小只读核查入口：

```text
GET /api/v4/runtime-graph/frontend-build
GET /api/v4/research/a-share/daily-product?date=YYYYMMDD&symbol=000410.SZ
GET /api/v4/research/a-share/company-materials?date=YYYYMMDD&symbol=000410.SZ
GET /api/v4/operations/sop?doc=overview
http://127.0.0.1:8873/research-panel/workbench.html?mode=latest
```

新日期必须绑定自身generation/input SHA，不能把示例symbol/旧日期硬编码成日常范围。`v4-read` skill可用于其固定health/identity/stage/pools GET，读取成功只证明HTTP层。

## 五、自动同步到底到哪一步

现役代码证据已在机器快照绑定文件SHA：

1. Main `infrastructure/scheduling/executor_registry.py` 的 `_run_a_daily` 在原A日更返回后继续派生产物，`_run_a_daily_source`在15:40/16:10/16:40窗口内核同代已完成产物并复用缺件检查点。
2. 原 `ops/research_panel_daily_product.py` 负责正式日期索引、原图、score_action、v192_assets、statistics与daily_completion事件。API与现有工作台读取这一套产物。
3. `ops/research_panel_top200.py:complete_daily_derivatives`负责同源Top200/历史统计，F10为独立可失败模块。缺件保持状态，不清空合法日包。
4. 因此“新日包成功→看板数据更新”已有集成；实际当前浏览器是否收事件、切日和显示新值仍要UI验收。新的基本面不是凭数值选股自动产生，Chat返回后仍需校验接入。
5. 自动化17按原技能操作富途与Chat，依赖Codex运行、Mac解锁、富途/Chat可用、容量与网盘权限。它不是无GUI依赖的后台API守护服务；不能承诺关机/锁屏后照常完成。

本批不为文档重跑正式日更、不提交新Chat、不写富途1111。原因是当前D11/10正式日包未物化且本任务为交接记录，不能用11/9名单冒充新日。

## 六、已交付名单和研究成果从哪里接

### 已核验的上一批（历史事实）

D=20261109、O=20261110、四组去重371，导航小K253、原公式31、回踩121、突破46（各组重叠，不能相加当去重）。富途1110完整回读371，missing/extras均空；部分简称变化保留，证券身份已核。入口：[原交付result.json](/Users/lexi/Desktop/学习/agents调试/v4_daily_panel_futu1110_20261109/result.json)。不要再次导入同批。

原研究批次：`FUTU1110_D20261109_O20261110_36931cd377ba`；名单SHA `36931cd377ba693c671af73878549b7c152e42e3b5427f022c0cd04acd41d251`。

- Chat：[原会话](https://chatgpt.com/c/6af19a82-23f0-83ee-b811-1b83b7221449)，已发送，后续回包已在资料修复批核验接入，不要沿用最早TASK_RECEIPT的“NOT_IMPORTED/THINKING”作为最终状态。
- Drive：[原交付目录](https://drive.google.com/drive/folders/1Yo7ScEfrT-zTxJfWbXbI71zoTZpcPzef)。已有文件ID在[CHAT_SUBMISSION_RECEIPT.json](/Users/lexi/Desktop/学习/agents调试/v4_daily_panel_futu1110_20261109/CHAT_SUBMISSION_RECEIPT.json)，不重复上传。
- 回包校验：[FINAL_QA.json](/Users/lexi/Desktop/学习/agents调试/v4_daily_materials_release_repair_20261109/research_return/package/FINAL_QA.json)。371全名单覆盖，包括本批实控人、行业二筛等结构化表；QA PASS是批次/结构证据，不等于逐条公告全文认证。
- 实际导入与展示以资料修复批最终FINAL_DELIVERY及API/UI为准。模型新增17股不能假定都在原371基本面材料中。

### 更早的未完研究

`FUTU117_PREANNOUNCEMENT_20261109`为源11/6、观察11/9、387只。已收1152文件且哈希/387覆盖通过，但缺`CONTROLLER_INTENT_AND_PRESSURE.csv`和`MOUSE_TRADING_METHODS.md`，曾归档为PARTIAL，不能称全部完成。[RECEIPT_QA.json](/Users/lexi/Desktop/学习/agents调试/v4_daily_panel_futu1110_20261109/previous_research/RECEIPT_QA.json)。若已有新补件先核新回包，不能直接重开整批。

旧119的15只/81只研究有独立回执；11/9记录中81只仍在运行而未归档。本文没有打开浏览器检查现在是否完成，当前状态CANNOT_CONFIRM。先查原回执/原会话，结束后收结果再归档，不重复发研究。

## 七、下一会话按这个顺序接

1. 先读本文件、日更SOP和RUN_LEDGER，再核实际时钟/交易日、Main/API/Stage release与任务状态。不要照旧PID操作，不恢复旧暂停任务。
2. 若仍在11/10下午，查看原15:40/16:10/16:40任务的真实进度及最新D10 receipt。16:13的官方源未就绪是快照，不是最终断言；健康运行等待检查点，不重复启动。若最终失败，保存准确断点，不拿D9正式包同步1111。
3. 数据齐备后继续原完成事件链：核同D/generation的日包、四组、原图、评分、v1.9.2模块、Top200、公司材料与行业二筛；核API及最少代表页面。先复用，不全历史重算。各缺件单列，不把partial伪装READY。
4. 查看既有自动化17和当批交付回执，避免与其并行写富途/Chat。同代完整名单准备好后按O命名富途1111或日历给出的真实目标组，回读完整股票集合并排除同码指数。v1.9.2单独组仍保持，未经新范围指令不偷偷合并富途名单。
5. 冻结全名单及当日表现，先查网盘原ID，只上传增量；填本批prompt，内置浏览器同批只提交一次，保存Chat URL和发送状态。
6. 收取已结束旧研究，机械全覆盖+内容3代表核验，兼容合同经既有owner接入，再回读API/UI；缺件继续补充prompt，不重做全批。归档与导入分别记，运行中研究不取消。
7. 到11/11真实09:15/09:25后，验本轮修复的首次自然输入及新算法产物：无零价伪造、未知字段如实、时间≤截止、三个消费者、owner见证、实际Top10和API。没有真实时段证据保持NOT_RUN，不强制重放补一个PASS。
8. 命中率仍低时另冻结选股评价：解释Top10名额、并列分数/排序、资料缺分与市场差异，做同池同输入的独立对照；本轮只修输入，不授权为追Top200改公式/系数或回填历史。不要把离线2→3解释为策略已优秀。
9. 下次正常发布将本次SOP文档纳入manifest、重新封签并验线上SOP。当前reader有固定文档白名单，新文件链接不等于网页新增可选文档；若要新tab需另做最小行为变更。不要直接篡改现役封签目录。

## 八、本次文档交付范围及明确未执行

本轮为A类文档/只读核查：新增日更SOP、完整Chat模板、交接和机器快照，更新源码SOP入口；逐链接与JSON解析检查后存独立codex文档分支，保留canonical原有其他改动。没有业务代码变更、训练、回测、服务重启、调度改时、富途写入、Chat新提交、Drive上传或网页SOP发布。

没有新增自动化或监控，不把本次读取等同于明天有人自动盯到09:25。既有17:00自动化继续按原配置；是否自然执行必须看其任务回执。本文件不替代必要的后续自然验收。

首次接续可直接使用：

> 请先读V4源码的docs/operations/records/2026-11-10-daily-workflow-handoff.md和docs/operations/DAILY_RESEARCH_DELIVERY_SOP.md，并查当前日期、release和原任务回执。按第七节续行同目标，只补未完成项，不重做已验收修复，不重复公式/上传/富途/Chat，不改模型、BUY或既有调度。先说明当前D/O日包是否齐备及下一真实断点，再继续看板、富途和研究回包闭环；新自然验收与历史离线结果分开记录。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
