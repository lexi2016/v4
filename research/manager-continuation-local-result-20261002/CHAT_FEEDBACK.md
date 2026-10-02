# BR003 与既有 owner 本地接续反馈

**最终更新：官方采集已因连续两批来源时间预算失败而停止。本文件早期B段和检查点保留原貌；当前终态以本段及最终receipt为准。**

最终已查询270/696，未查询426，排队正文0。查询失败14项：原8项目录/空结果未核，加6家HKEX_RESPONSE_TIME_BUDGET_EXCEEDED（HK.01651/01658/01672/01675/01681/01686）。保留可恢复的同一run和旧查询窗口，没有盲重试、重开窗口或改BATCH_SIZE。

204条已观察文档中，156篇BODY_PARSED、25篇FAILED、23篇BODY_UNREADABLE；204不能称为全部成功解析的正文。25项正文失败含18项PDF页数预算、5项PDF字节预算、1项响应体积预算、1项响应时间预算；23项不可读原因为NO_READABLE_PDF_BODY。完整计数和原件SHA/URL样例见DOCUMENT_BODY_STATUS_AND_SAMPLE.json。

最终原入口GET读回与保存产品run/revision/SHA一致；原始91,862,606字节JSON留在本地并记录SHA。实际页面刷新后显示PARTIAL、270/696和204条记录。停止仅证明来源预算阻碍，未证明具体根因，不自动扩大成新抓取器或预算放宽。早期“继续采集”的安排已结束，B不再后台运行。

固定输入：80d4c41ec75aef41a642f1e27d32e472368f4675；其父提交为34e1dc6912100830f42cf0fc90eec72f624afc9a。只反馈实际本地结果，不修改业务代码、不部署失败候选。

## A：精确补丁应用成功，41项验收失败

隔离候选 managerWorkspace.ts SHA256为6eef36501d05334c60e052ec0e344240ce310c6a0a1444a7ce6b8c61be33f9fa，与交付 after pin一致；其余四文件维持d18候选。完整41项只执行一次：6 passed、35 setup errors、0 assertion failures、0 skipped。不能将“0 failures”解释为通过。独立 Reviewer 用同一TypeScript5.9.3严格编译，exit2，确认同一P1。

实际错误：managerWorkspace.ts(669,85): TS2552 Cannot find name 'date'。

遗漏链为：validateResearchAttention已有date（762行）→819行validateAttentionDecision调用→685–687行该函数签名→718行validateAttentionLaneEvidence调用→647–651行该函数签名→669行validCompanyEvidence调用。新补丁只改下游日期校验，却遗漏两个中间函数的参数传递。请仅补完整消费者目标日传递，并保留历史capture date可早于消费者日期、错误owner_document.target_trade_date拒绝的原需求。不得用文档自己的target date自证。

source/failed_candidate/提供本地精确after源码；evidence/junit.xml、pytest.log、FINAL_REVIEW.json和independent_tsc.log给出可复核实跑结果。正式五文件、已有dirty工作、运行release及服务均未被本批修改。DEPLOYED/API_VERIFIED/UI_VERIFIED/BEHAVIOR_VERIFIED均未针对新候选成立。

部署计划曾误选旧com.lexi.v35.local.plist；evidence/DEPLOYMENT_PLAN_SCOPE_CORRECTION.json已纠正。当前8873使用api-only配置，五个前像均存在且匹配。不得将旧plist缺文件/manifest漂移当作当前部署阻碍；真实阻碍是编译失败。

## B：原公告入口的早期推进记录（最终停止见文件首段）

当前日期20261002，既有官方run_id=3350299e0a9b42a3977dcf5d9be4c02c保持不变。查询窗口固定为2026-09-29T16:10:00+08:00至2026-10-01T08:46:37.748536+08:00；不代表10月2日全部新公告。每次原入口最多推进3家，或先处理排队正文。上传时的精确覆盖、已观察正文数和失败项见evidence/OFFICIAL_CHECKPOINT.json，状态明确为RUNNING_CHECKPOINT_NOT_FINAL；Codex继续原owner，不回滚数据、不改BATCH_SIZE、不重开窗口。即使696家全部查询结束，也不得宣称目录翻页穷尽。

东方财富原source-scope分支已真实调用一次：3/3查询成功（HK.00001、00002、00003），窗口内正文0篇，PARTIAL/VERIFIED，exhaustive=false，非全市场扫描。见EASTMONEY_ONCE_RECEIPT.json。未为了制造非零结果改发行人或重复调用。

## C：原注册日线任务不会生成要求的目标日V2资格产物

Scheduler的5项HK bindings均存在并解析成功，research_panel_daily_hk也已注册。不能继续将缺口表述为“本机没有注册入口/没有HK环境变量”。独立只读核对显示：注册任务更新共享HK0.2日线面板，随后ensure_hk_security_master，发布assets/hk_security_master的run/latest；当前调用链没有发布universes/20261002/HK_CONNECT_FULL_MARKET.json，也没有所需producer_owner绑定。目标文件仍缺失。

因此未执行这个会更新日线却不能解决目标V2缺口的任务。qualifications不从价格有效689行、证券主表或D-1名单手拼。Manager consumer仍保留require_v2=True。请依据qualification/source中的8个完整实际文件及SOURCE_INDEX，定位既有owner到现有V2构建/发布的缺失连接；不要新增第二producer、改reader、回填时间或降门槛。pinned stage_center/hk_universe_preflight.py实际SHA9d3d2c2d5ff3bd1c7713a9485e88000ae882f58b0a457b734656094606ba2941已核实，其字节此次补齐。

## 当前页面与运行状态

已打开真实8873完整SPA，计划日20261002、Stage来源日20260925。日线筛选显示共享研究面板的689只待核，并非另建日线数据源。公告区显示真实覆盖和原件数量；东方财富为PARTIAL。

10:02现场workspace读取：US expected session为20261001，原始上涨个股21、行业13，ResearchPeripheralStore来源回执VERIFIED；但快照US_MARKET_SNAPSHOT_NOT_READY，mapping_eligible=false、合格映射0。不能把旧反馈中67张材料的资格拒绝说成这次最新API已经进入材料关系准入。缺目标V2资格是独立存在的下游缺口，当前美股快照未就绪是另一个运行状态；本轮不扩展修复美股采集器。API_SUMMARY与页面全文均已封存，原始73,202,121字节API留本地并记录SHA。

## 下一批有界交付

1. A只补遗漏的两个中间函数参数和对应调用；严格TS编译先通过，再跑原39+新增2项。没有执行能力则标NOT_RUN，不声称41通过。
2. C只依据补齐源码提出或实现原owner的最小资格发布连接，给出准确入口、参数、before/after pins和现有V2 reader读回测试；日线更新逻辑及scheduler配置不扩修。若依旧缺源字节，一次列出准确文件与调用理由。
3. B已按连续两批来源失败停止；最终收据已封存，不自动扩修抓取器或放宽预算。

仍排除日历、BI04、日线补采、BUY、A股Stage、R3A写集合及Vibe8910。Issue8/17保持开放；RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
