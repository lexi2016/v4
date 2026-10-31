# D30逐股源修复、历史标签与日更工作台链路

本批证据目录：`/Users/lexi/Desktop/学习/因子工厂/research/workbench_daily_chain_completion_20261031_r1`（下称B）。冻结入口为B/SCOPE.md、BASELINE.json、SOURCE44_ADDENDUM{,_R2}.json、SCHEDULER_OWNER_ADDENDUM.json。唯一业务Writer为daily_chain_completion_writer；独立验收由主控另派只读Sol High进行。本交接是候选交接，安装、API/UI与自然时段状态分别记录，不能由本文推定通过。

用户入口为 `http://127.0.0.1:8873/research-panel/workbench.html`；无date默认最新**已提交**研究日，后续真实完成事件可跟随新日。显式`?date=2026-10-29`及手动选择历史日期保持固定，只更新目录与新日提示。同日更新保留既有选择与图窗；跨日走原loadDay清理旧上下文。无效或未物化日期不借用旧名单。

## 原身份与交付基线

本地任务worktree基于69d31e8971f38a00b4e76f84c48b45f08a3e4cb2（精确值以BASELINE.json为准），它不是GitHub选择性交付14da59的本地checkout。实际Main基线为`sop-binding-parallel-20261030-r3-main/app`，实际API为`workbench-company-state-20261030-r1-api/app`。SOURCE_OVERLAY.json和SCHEDULER_SOURCE_OVERLAY.json逐文件记录接受的现役源码来源；不以旧本地snapshot覆盖现役依赖。主控负责GitHub scoped commit与完整远端读回，不merge。

原式、51字段/22绘图、数值分组、收益规则、EventCaseCache核心均保持。CAUSAL_PREFIX_REUSE_PROVENANCE.json记录从旧已接受实现仅移植因果prefix校验的函数范围、原SHA与接口parity；没有整文件覆盖旧owner。全程 `RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false`。

## 44逐股实际结果

B/execution/source44/admission-r2/RESULT.json是**实际原A-Sync**回执：38 ACCEPTED、6 QUARANTINED、failures=[]。原汇总status为FAILED，因为原契约要求所有目标均准入；本批保留该原值，不将其改称全价成功。6项为002717/002827/601326/605258/688121有据无有效D30 bar，以及301139于10/28正式摘牌。5停牌的原因支持与源无bar不等于精确全天/PIT认证；不会继续补造价格或无限重试。

31原ratio项复用原外部SHA固定seed descriptor，由原gate实际验证通过；601091走原首五市场session IPO边界，920002以真实旧pair/现prefix绑定通过。没有改ratio阈值或原价格。8只7/22坏记录来自已校验Dot原包（37成员SHA/CRC），替换完整OHLCVA，保留native reserved字段；其中002731仅量额坏，其他7只还坏OHLC。没有重跑云端9项测试或整市场抓取。

原51记录分类中的43条signature停牌占位（00273139+3011394）只从派生副本排除，并保留逐32B beforeSHA和原字节。第一错误修复后又暴露：002731三个暂停期伪bar；两BJ6/18完整坏bar；另7股30条OHLC/amount冲突。所有增补均绑定精确symbol/date/before32B SHA、全字段源行和原TDX来源，不能只改量额或调expected close凑过关。纯小量volume差异保留未改，报告为未认证等价；未新增容差或假定所有≤99股差异正常。

6BJ真实category1行动来自已捕获官方GBBQ、原parser/policy及已校验parsed-cache closure；supplemental exact-pair证据明确为当前NONPIT capture，未冒充旧adopted snapshot，也未宣称Futu等价。00273110/23为发行人公告明确的退市整理首日不限涨跌幅，独立于IPO和公司行动，绑定精确两日全row及官方PDF SHA。负例包含前后交易日、错股、错PDF、错row、普通交易日。

原native7股实际尾日止于8/31或9月初。201条缺失历史尾行复用Dot完整RAW/原3股SDK160回应；仅4BJ缺10/29，预期D29官方input确实不存在，才沿原TDX owner每股一次count2，无retry。D30仍由原已存G4DAY包准入。SOURCE_TAIL_REUSE_RECEIPT.json保留查找、缺件和复用边界。

301139虽不准入D30，其已证7/22坏bar/4占位历史更正仍保留。因此激活是**39份native版本：38当前有效＋301139仅历史**。5停牌文件不写。NATIVE_ACTIVATION_PLAN.json含每个canonical beforeSHA、新不可变候选SHA与备份路径；原件在独审前未改。

## 64历史缺项

原D30候选172，原108已完整，64确缺220521日期。原结果首轮冻结为B/execution/history64/BATCH_INITIAL_TERMINAL.json，SHA864944f9c4e4da334d5b48db1d08950f89252b116e5dc811363e875c4b8020bf：64/64、failures=[]、总覆盖220649=原128＋本次220521、formula calls0，耗时2908.29秒。D29/247及原收益保留。

HISTORY64_REUSE_RECEIPT.json证明原batch重复读取3.68秒、449个stock/row/history/journal/event-case文件byte+mtime不变，新增标签/收益/公式计算0。RESULT.json幂等回读只改汇总计时，首轮原回执另存不可变。64出版候选为execution/history64/stage-r2/PLAN.json：原名单172身份、108结果、图与非统计字段保持，64统计/历史覆盖和事件引用由原sync owner锁/CAS更新。D30此前不存在的display_names/company_materials sidecar保持缺失，不套用D29。

原producer的同日新generation重建增加逐股retained full-result复用：全prefix/config/calendar/basis、原owner identity、51/22结果形状和原分组parity一致才复用；仅global generation变化不重算旧公式。3市场正例及改prefix/日历反例已定向通过。历史标签仍保留原entry身份，persistent EventCaseCache保留原收益。真正发生修订的输入按原owner计算，不能通过新identity掩盖漂移。

## Top200与自动链

D30最终候选为B/execution/top200/CANDIDATE_R3.json：5575目录=5569当日有完整OHLC且量额>0可排名＋2缺价＋4正价无成交。5573只表示正价/可算涨幅记录；不称其全部有效成交。200全部有真实OHLCVA，与6已知no-currentbar交集空；200成员、顺序、涨幅及原结构与已PASS试版完全一致。原结构计算0。行业/题材/结构统计的母集合改为5569 eligible成员，R1/R3差异单列，UNKNOWN不当失败。

主命中使用交易日历T-1冻结池对T榜：D30对应D29 247→14；D30 172→同日Top20029仅事后对照。两种分母均列Top实际N与候选去重N；组重叠不重复累计总命中。图审仍UNKNOWN_NOT_REVIEWED，没有冒称0只通过。原469实验池未混入。

future T由原scheduler A分支的成功、新跑或配对receipt复用共同调用complete_daily_derivatives。它沿原adapter/worker/持久缓存只补实际新候选缺史，再生成真实当日日包Top200、统计、原index与完成事件。新日期自动进入history目录。已有同日contract/checkpoint断点复用，不因可用内存变化创建新contract。失败先写对应日期attempt；即使已有同日旧product，也不能将旧版本冒称这次源成功。休市/时窗仍由原A gate决定。

Top200未来按61个原市场session读取有界列窗口，调用冻结试版原feature/stats纯函数。D30来源修订时仅比较旧/新61日投影、计算实际变动股票的结构，其他结构复用；不扫描/重算全历史，不重新执行试版runner。目录、source、NONPIT与资格限制均保留。

A_LONG继承FD验证名字、日期、slot、regular file及inode，独立probe证明锁已持有，再验证传入FD为原open description并dup。只close dup，不LOCK_UN父锁；invalid/closed/unlocked/other inode或同inode独立FD不能绕锁。手工入口保留原锁路径。API frontend-build旧错误来自旧env release ID/manifest SHA失配，新的原release工具生成精确绑定，无需改runtime_graph业务代码。

## 执行与验收入口

使用绝对解释器`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python -B`，Python子进程用sys.executable。node为`/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node`。batch启动时实测18核/128GiB和余量，原14worker/28queue保留系统24GiB；future按实时CPU/内存导出，不固定2/4进程。

不要再启动64 batch或云9tests。候选/执行命令、日志和逐项结果见B/FINAL_DIFF_MANIFEST.json、WRITER_HANDOFF.json。原命令入口：bootstrap_stock_event_history.py --settings contracts/workbench_daily_chain_completion_v1.json；sync_stock_history_completion.py --batch .../history64 --root 原DAILY --stage ...；apply_d30_source_repairs.py --followup只重用已存源，已有阶段结果不可覆盖；activation必须使用精确plan及独审scope SHA receipt。

激活依赖顺序、精确39份native、Main/API/plist/env/pointer beforeSHA、失败回退见B/ACTIVATION_PLAN.json与NATIVE_ACTIVATION_PLAN.json。独审前未覆盖canonical价格、未切Main/API、未启停服务/计划。原D29消费者与completion watcher保持。先发布已完成64，再修native及原paired source，再用原producer生成新immutable版本；修复后新候选数量允许改变，保留旧172/247，不为凑数改公式。新增候选若缺历史由同owner补缺，不将64全批再跑。

Registry使用原builder materialize/锁/单事件验证与append+fsync+readback，保留所有旧prefix字节。新suffix通过；旧event6763既存生命周期冲突仍CANNOT_CONFIRM，不声称全registry认证。REGISTRY_INDEX/SOURCE44_REGISTRY_INDEX记录route/event/execution/correction计数及外部持久化未知。

最终独审、GitHub远端、实际安装、API/UI读回、自然slot各自记实际状态；自然时段未发生保留NATURAL_SLOT_UNVERIFIED。中央SOP_SINGLE_STOCK_REPAIR.md由主控单独追加，本Writer不并发写它。

## R2独审精准返修

原REVIEW.json及REVIEW_REPRO.py保留FAIL原件。F1为已成功paired source但当日index/date/product/chart叶缺失时，原retry仅读缓存，未恢复物化。现窗口内先检查精确当日数字与图表绑定；缺失时调用原materialize_daily_product(data_root,target,output_root)，复用其原checkpoint/retained结果，再验证实际叶子。源采集和paired generation不重跑，history_dates默认空。恢复失败以原同日身份抛出FAILED，不能让外层SUCCEEDED。已齐全的第二次retry不调用materializer。恢复时无法仅从汇总证明实际新算数量，numeric_recomputed保留null；不冒称0，source_recomputed/provider_invoked为false。

F2为窗口外成功源复用的alert-only原因原先只放在嵌套chart_leaf，wrapper误进衍生计算。现顶层传递该窗口裁决，wrapper同时识别两层原因并返回SKIPPED_OUTSIDE_WINDOW，materializer及history/Top200衍生入口均不调用，不发送新的完成事件。

R2定向覆盖缺index、缺date、缺product、缺chart descriptor/manifest、未完成chart receipt、恢复后第二次复用、恢复IO失败、15:39/17:00/隔日09:00有成功源缓存组合；11项PASS。相邻继承锁2项PASS沿原FD语义，64与其余独审已PASS范围不重跑。R2交接见B/WRITER_HANDOFF_R2.json、FINAL_DIFF_MANIFEST_R2.json和ACTIVATION_PLAN_R2.json；原R1清单与计划保留。

## R3补齐F1当前配对源身份

原REVIEW_R2.json及其复现保留。此前同日旧完整叶虽然内部引用合法，仍可能属于上一generation。现复用前使用已验证源receipt与原panel_contract读取selector/backtest的footer，核对两侧日期、generation/input、snapshot及指针当前字节，再按原SourceContext既有identity字段绑定product/source_generation和manifest generation/input/snapshot。无需再扫描多GB全历史或交易日历。任何身份不符，先调用原materializer恢复，再做同样身份验证；没有把旧数字只重绑新metadata。恢复后仍旧则同日FAILED，不转成衍生成功。

新增generation、input、selector artifact SHA、snapshot四种同日变更回归，均在旧product/chart字节保持原样时先触发原owner恢复，第二次才可复用；另覆盖materializer返回旧叶仍拒绝成功。新增5项与受共享fixture影响的6项缺叶用例共11项PASS。F2和其他独审PASS继续复用；Native39计划SHA保持613843d2a3f77eeb45d106bd44e2c87de44c6ccbc028e16296d8dfde757a4ea2不变。最终业务候选交接为WRITER_HANDOFF_R3.json/FINAL_DIFF_MANIFEST_R3.json/ACTIVATION_PLAN_R3.json。

## R4现役source policy组合修复

实际安装后原gate报A_DAILY_SOURCE_POLICY_UNBOUND，失败原件保留。原因是旧本地snapshot的policy earliest_slot1610未覆盖为真实现役source owner已接受的1540。本次仅恢复1540，五个无bar事实及301139生命周期事实不变，不放宽原source校验或自然窗口。新增测试直接加载实际Main source owner，验证候选1540可加载、旧1610被拒绝。R3其他业务PASS不重开。

已实际发布64历史、替换39份native及保存原件；首个MainR1已安装，但首轮source gate因上述绑定中止，paired/API/UI仍未验收。后续历史D30显式手动回放仅消费已存SHA固定input，复用原OfficialDailyPackage验证；不再次下载、改时钟或宣称自然运行。Main新base保留已接受turnover commit d469ccf9fd29c61269dd818787aa9200cc6f75e3的qfq/helper与原acceptance；14da59+本批32文件不是完整Main快照。


## R5: verified lifecycle source policy continuation

Actual MainR2 source run completed5540 accepted/268 quarantined, zero technical failures; the paired owner then rejected301139 because downstream factor-cache only knew the old29 fixed-asset facts. This is a metadata/proof binding failure, not a request to recollect5808 or recompute64.

Start factor-cache from exact accepted MainR2 SHA6757f2bada82fe222ef224fbf58361a7f499f4c8664575b9d1a0abe7a9ecf568. The only existing function AST change is `_verified_sop_skip`; one exact301139 source-policy helper is added. Provider/event/carry/volume/math and every other top-level AST node remain identical. Producer propagates actual policy path+SHA rather than asserting the old7403 lifecycle asset contains301139. Exact official notice SHA8025a2... and delisting effective20261028 remain bound; no current bar is created. Fourteen focused producer/consumer and negative/legacy tests passed.

New factor SHA requires reviewed transitive acceptance. Prepare immutable proposal for the existing two successors, preserve complete prior acceptance/entries/proofs and original primary/oracle. Preserve the accepted turnover QFQ kernel and helper unchanged. Use the original `_convention_tuple_accepted` and original publication lock/CAS; no new gate or third entry. Pending candidate stays rejected until actual independent review. The isolated modeled-finalized gate fixture is TEST_ONLY_NOT_ACTIVATABLE, not an approval.

After the affected independent review, COW MainR3 from actual MainR2 and install only the exact three source owner files. Keep APIR1 and all static assets intact. Under original A_LONG and publication locks, single301139 original producer emits a new metadata proof (zero native writes/provider calls); CAS-merge only its proof fields into full-source summaries/progress/CSV while keeping5540,268,5808,raw FAILED semantics and other5807 records unchanged. Save immutable preimages and exact corrected versions. Resume original paired/daily chain from this completed source evidence. Source or tuple failure retains evidence and rolls back own exact writes; natural slot remains unverified.

Rebuild dependencies: R5 proposed Git delivery was a scoped33-path overlay on14da59 (local preparation only); it is not a complete Main snapshot. Preserve the independently accepted turnover commit `d469ccf9fd29c61269dd818787aa9200cc6f75e3`, QFQ adapterdf0c3f48... and helpera05f2f93... and their original acceptance proofs.


## R7: bounded same-asof paired repair

R6 is actually installed as MainR3 PID51605 (manifest350ac966...), with original source5540/5808 accepted,268 quarantined,technical failures0. Native39 and64 labels are completed and are not repeated. The original default QFQ entry would rebuild every available full prefix after the global tuple/input revision. R7 confines reuse to the explicitly SHA-bound D30 source-repair descriptor; other asof dates keep the original owner behavior. This is not certification of arbitrary future source revisions. Labels and returns continue through the existing persistent prefix/event cache.

The original writer now compares actual prior committed two-role source identities, full byte-level raw prefixes and filters, events, history/basis, calendar and original mathematical code before retaining unchanged Arrow rows. Actual private preparation produced5775 price symbols; binding gives5737 unchanged and38 changed/new, with301139 no longer in active inputs. Only those38 are submitted to original rebuild_symbol. Unchanged price/formula/return arrays retain their original buffers including valid-NaN/null layouts; original old-key, foreign-market and target-key conservation remain active.

Original D30 metadata already captured30 successful A-share responses. Their code/asof/capture/queried_at/response bytes stay unchanged; current reuse provenance is separate. Six newly active BJ codes have exact installed RequestRehab.pack_req rejections recorded on the actual10/31 timestamp, before request bytes exist. This is local SDK capability, not an OpenD quote or historical/PIT evidence; network/price requests0. The original TDX official terms fallback and NONPIT caveats remain. _fresh, original provider/event/affine/carry mathematics and ordinary other-asof paths are unchanged. A typed load revalidates the same source/config/SDK identities.

Real canary scope is frozen at7 stocks: unchanged000063.SZ/600016.SH/920006.BJ have0 original rebuild calls and exact retained price/formula/return arrays; changed002335.SZ/603629.SH/920002.BJ each have1 original rebuild call. Extra920003.BJ has1 call only and covers the corrected6/18 and7/22 complete OHLCVA and new SDK-unsupported/TDX fallback; source-selected raw and original adjusted values equal the corrected source, two-role keys228→237 are preserved. No source-input or first6-stock rerun accompanies this extra sample. Negative raw/floor/event/history/code/formula/calendar/basis/schema/metadata/provider/time/SDK-byte cases fail closed. All first-accepted oracle and computation kernel identities are retained through the original derived exact-two-successor path.

Turnover is independent context. Actual6f selector has2,537,710 old nonnull rates; backtest has no turnover columns; both have5502 D30 rows with missing turnover. Retained Arrow price rows pass only target context to unchanged DailyTurnover.apply_target. Only missing D30 context is filled, all old nonnull values and historical NA remain. The separate12m historical overlay is not promoted or advertised complete.

301139 has five exact native corrections: July22 full valid row plus removal of Aug31/Sep1/Sep2/Sep7 signature placeholders. Old6f accepted selector/backtest both contain0 rows for it; its old quarantine explains the signature failure. Thus old accepted history keys remain0→0, not an entire-history deletion. This batch truthfully delivers its corrected native history and effective10/28 delisting/current nonadmission. It does not claim that301139 paired history was backfilled.

Deployment after the affected independent review uses a COW MainR4 from actualMainR3; only qfq/factor-cache and this machine contract differ, with original helper and all other dependencies preserved. It binds the descriptor date/path/SHA in the real manifest/plist/process env, then resumes source evidence with0 full5808 sync reruns and original paired/daily/Top200 continuation. Before review, this is prepared source/canary evidence, not installed/paired completion.

Git delivery uses the existing PUBLIC lexi2016/v4 repository without changing visibility. Current task scope is34 source/test/doc paths; delivery additionally references the unchanged accepted helper blob from commitd469ccf9fd29c61269dd818787aa9200cc6f75e3, SHAa05f2f93d2920ec03a1f080367e78d9815c0e960a7535e585af43a4e0f6f58c0 (35 path readback). Its original independent review is reused; helper source is not edited. Remote delivery happens after actual local acceptance, and is not yet claimed.


## R9 actual chain and R10 current metadata publication

Main5 installed with original exact38 checkpoint recovery. Formal same-asof generation d22220537892215832f0c01faeaadd11e282b4d65debf979152597a00d1829b5 committed both original panels:5737 prices reused,38 recovered,0 new rebuild; each17,155,806 rows. Target turnover5243 filled/297 unknown; original selector2,537,710 nonnull values preserved. Native39/source5808/history64 are completed and not repeated. Native301139 history repair does not imply paired backfill: accepted historical keys0→0, current nonadmission remains. Full source remains PARTIAL/NONPIT; next natural15:40 is unverified.

The exact002731 consumer derives its missing D30 history-end and only genuinely missing accepted-evidence lookup from the SHA-pinned original data chain. The original helper's target-set, raw-price and nonempty/file/SHA acceptance checks remain active. Both original UNKNOWN reasons are retained. The saved original single-stock computation is not selected; final172 membership and all172 original PNGs stay unchanged. Other5807 current row references remain byte-identical. The current172 history view validates actual full prefix, calendar, rule, basis, projections and cached labels before original Staging/CAS; original64 stock-result/cache identities and mtimes remain unchanged. No label or return calculation is performed by publication. Top200 refreshes only the numeric parent reference after same-source exact-membership guards;200 winners/structures/industry/theme statistics remain unchanged.

Normal entry is the existing A daily executor at15:40;16:10/16:40 missing-leaf retries converge on its original materializer and complete_daily_derivatives. Retain the real source receipt, checkpoint and original lane identity on retry; no blanket rerun. For an already committed same-source numeric product with complete retained current labels, the exact current-view call is ops.research_panel_top200.publish_current_history_view(context, daily_product_root, staging_directory). It validates all selected caches and source identities; same view returns NO_NEW_COMPLETION. It cannot fill actual history gaps.

R10 actual commands, using the absolute v4-mac Python, are prepare_current_binding_install_r10.py then activate_reviewed_main_r10.py then run_current_binding_r10.py, all under this task evidence directory and only after the bound independent REVIEW_R10 PASS. The installer retains original release leases/lane locks, plist CAS, process cwd readback and automatic failure rollback. rollback_current_binding_r10.py restores only the exact own published index/event/cache preimage, rejects later CAS drift, preserves immutable artifacts and refreshes derived statistics; it does not revert other releases or current API. Actual result/API/UI readback will be appended after activation.

Current API belongs to the separately accepted zge-skill-d28-20261031-r2-api overlay and is not replaced by Main6. Rebuild delivery requires parent b4c5926c93992db307ef0e37ba32da76319cc861 with its accepted host and three served model/UI JS; the earlier static builder alone does not reproduce this overlay. Root's accepted delivery rebase manifest binds the exact ordering/bytes. Final readback scope is34 task paths (host from accepted overlay) plus unchanged accepted turnover helper(d469) and company-local(14da),36 paths, with4 foreign overlay paths preserved separately. No source/data files, private evidence or runtime credentials are uploaded with source.

## R10 actual acceptance and R11 original chart readiness

Main6 is actually installed PID74795/manifest f32d922fafcbf8c1e6f9958d5802eef80e58195502f16410a6d11f744e98ac74. The saved002731 original result was published once, with no new formula execution during publication; candidate membership172 stays unchanged. Actual current172 history view and Top200 parent are published; same-view/single-row repeats return NO_NEW_COMPLETION. API current/catalog return200 with172, D29 remains247; frontend-build is VERIFIED. Workflow observation2026-11-02 has execution_ref=null and CANNOT_CONFIRM_NO_RECEIPT, preserving missing actual execution rather than borrowing D29.

Source technical failures0 does not mean all conditions are known. Final5808 projection retains727 rows with UNKNOWN groups:270 source qualification UNKNOWN plus457 condition UNKNOWN despite qualification accepted. Original reason counts are stored in CURRENT_UNKNOWN_SUMMARY_R10.json; labels can overlap, and47 rows have no original reason text. Overall source remains PARTIAL/NONPIT. All38 source44 repaired current stocks now have ACCEPTED reader qualification; five suspended stocks plus301139 remain nonadmitted. Native39 includes301139 history-only; its accepted paired history remains0→0.

Actual UI exposed a direct race: iframe load fired while original RESEARCH_PANEL_STATE existed but original async compressed data had not filled rows/view. Restoring the user's80-bar window/selected125 at that time was overwritten by the original renderer's later120-bar initialization. R11 starts from exact accepted currentR2 bootstrap355f6370..., preserves every skill/model/source function, and waits for the original renderer's existing documentElement.dataset.loaded===symbol marker and real rows/view. A MutationObserver is canceled on clear, new context/document and newer frame load; no polling or renderer/math modification is added. Actual original172 PNGs and all data/Main6 remain untouched. Private preview proves exact same-day window/point, selection/group/sort, fixed D29 and nonempty honest company MISSING states.

The maintained source research/stock_panel_collab_20261030/mac-host/bootstrap.mjs and served alias research-panel/workbench-host/bootstrap.mjs must have the same reviewed SHA. Rebuild order is the fixed base builder, the accepted b4c R2 model/local/bootstrap overlay, then the reviewed R11 bootstrap from the maintained source. The latest bootstrap retains R2 and original V4 modes. Delivery scope becomes35 task paths plus2 accepted dependency blobs(37), with the other3 foreign model/host-related source paths preserved separately. R11 deployment uses COW API3 based on actual accepted API R2; exactly one static bootstrap changes, all API app files, model/local JS, source/data, Main6 and runtime bindings remain preserved. Actual final API3/UI results will be appended after the bounded independent review and installation.


## Final actual local acceptance (R11)

Completed local research chain acceptance; research data stays PARTIAL/NONPIT. Main6 PID74795 manifest f32d922fafcbf8c1e6f9958d5802eef80e58195502f16410a6d11f744e98ac74 and API3 PID75726 manifest1a50161179604043a303d055f7e61ccb4c073d2236ea8a681c4660f0832195b2 are installed with actual config/process bindings. API3 derives from accepted R2 and changes one bootstrap only; all1305 application files and other483 static assets are preserved. Raw source and served alias both SHA5ac3c987195334b6660b97515bfae47cfb36826fd61f70d895a5ad702ec95fb7.

Actual frontend-build VERIFIED binds API3; current catalog/day reads200 with172 and explicitD29 remains247. At1600 and694 pixels, same-day saved completion invalidation plus real GET preserves selected stock/group/sort, window start100/count80 and selected125. Screenshots show no new overlap/width overflow;0page/http errors. Explicit historicalD29 displays the newer-date hint while staying fixed. The dedicated browser was awaited closed and isConnected=false; no user tabs were controlled. Cross-date auto-follow and company state identity tests reuse matching actual-data private preview; D30 missing materials are honestly MISSING, while the actual D29 screenshot retains received company/finance data.

Actual report is LOCAL_ACTUAL_ACCEPTANCE_FINAL.json under this task evidence root; final44 table is D30_44_ACTUAL_DISPOSITION_FINAL_R10.csv. It records38 current readerACCEPTED, five suspended plus301139 nonadmitted, native39 with301139 historical-only. Labels64 are published:220521 newly filled,220649 total including128 prior dates; zero new labels/returns on repeat. Current172 full-history view is committed with exact original64 result references. Top200 has200 winners from5569 eligible(directory5575=5569+2missing+4positive-no-trade); D29 frozen247→14 is the main cross-day coverage(14/200 and14/247). Same-day172→29 is descriptive only. Source-level5540accepted/268quarantined/technical0 and current-reader5538accepted/270UNKNOWN remain distinct; final projection retains727UNKNOWN, including457 accepted-source conditionUNKNOWN. No all-stock/all-data PASS is claimed.

Use the default latest committed research entry http://127.0.0.1:8873/research-panel/workbench.html ; explicit historical example appends ?date=2026-10-29. Existing Main scheduler owns normal15:40 and16:10/16:40 retry entries; do not replace them with this task's historical D30 replay. Current history metadata publication uses publish_current_history_view(context,root,stage) only when every selected cache's actual prefix/rule/calendar/basis and current label has been verified complete; actual gaps use original incremental bootstrap. The one-off R10/R11 review-bound operators preserve their reviewed phase hashes and are historical receipts, not generic future-date commands. Original installer has verified lease/CAS automatic failure rollback; reviewed rollback_current_binding_r10.restore uses its exact own before/after references under the original A_LONG lease, rejecting later changes. Keep source evidence, original backups, immutable releases and checkpoints.

Natural next15:40 remains NATURAL_SLOT_UNVERIFIED. Workflow sourceD30 resolves observation2026-11-02 with execution_ref=null and CANNOT_CONFIRM_NO_RECEIPT, not an oldD29 receipt or clock-derived completion. No source5808/native39/price38/history64/chart172 recalculation accompanies R11. GitHub is delivered separately by root using parentb4c plus exact37 scoped paths(35 task+2 accepted dependencies), preserving three other foreign model paths. Source-only delivery excludes private market/material files and runtime evidence. See CURRENT_DELIVERY_MANIFEST.json and the subsequent remote readback receipt for actual external commit; this document does not claim a commit before it exists.
