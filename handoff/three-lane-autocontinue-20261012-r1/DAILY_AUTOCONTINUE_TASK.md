# 10月12日三路名单与每天自动接续：Chat修复任务及验收合同

这是 GitHub #35 的本轮增补，目标为20261012公告、超跌、美股驱动三路真实研究名单，以及此后每天沿原链自动更新。用户自行提交给Chat并交回补丁，本地主控收到后独立验收、合入、发布8873，再做API/UI与自然时段验收。15分钟跟进任务已经删除，不建新闹钟，不自动向Chat发送消息。

## 先区分成功的旧链与未完成的每日接续

已经存在公告原owner成功导入的其他日期产品：target20261008/publication2026-10-07有33条入选，target20261009/publication2026-10-08有55条入选。这证明原采集、正文、分析、注册、导入、读取链路已有成功实例。target09后一个产品事后才可用，不能当10/9盘前证明。不得把这两个日期的产品或名单复制到target12。

20261012也不是从未保存：10/11 14:04–14:05 +08已有MANUAL_REFRESH计划，run=1e9d511515de47599f05539e43e79b81。22:41 +08现役API仍返回STALE_INPUTS_CHANGED、consumed=false，stocks/focus为空。新增材料与分析后，旧计划输入身份确实变了；应沿原owner更新，而不是把状态硬改CURRENT或削弱输入检查。

## 当前基线与源码身份

- 私有仓库原部署背景基线：2324ec87daf94802a6d40872f4c0f629a1bb138e。
- 本增补上一固定提交：568a23081b6e7f8c029a108426170a293ed720ef，分支codex/three-lane-autocontinue-20261012-r1。
- ACTIVE API app：V4_THREE_LANE_LOCAL_INTEGRATION_20261011_R1/release-candidate-20261011-r1/app；manifest SHA=f2940d02d408b52bde35258b2366e32a4b7e3ad59193b313b243677d590eae1d。
- Chat R2固定交付：ffa22c87b9aee6e434f28eb0d6698a2aec239176。运行版4路径与canonical5路径已在Mac做候选合入；未独立验收、未发布。候选manifest SHA=b1e05f88c129d5555281cfaf997fe2f8227efd1c77bb51bf18b3d0eac8c487fb。R2不能冒充现役运行版本，也不能声称解决了本#35每日接续。
- 本目录source/active提供当前原链所需源码；source/canonical_after_r2为当前未发布canonical增量；patches/runtime_source_r2.patch和R2_SHA_MANIFEST.json用于在原runtime_source上准确构造R2运行版。CURRENT_SOURCE_MANIFEST.json逐项给出身份、字节数、SHA256与Git blob SHA。只准hunk/三方最小合入，不整文件覆盖其它并行修改。
- 此前7份自动原链增补仍在handoff/three-lane-local-integration-20261011-r1/runtime_source：ops/run_manager_announcement_cycle.py、infrastructure/scheduling/manager_announcement_supervisor.py、v4/manager_research/{plan_owner_dispatch.py,us_mapping_research.py,announcement_catalog.py,announcement_autorun.py}、ops/manager_announcement_body_batch.py。

## 断点一：输入更新后，原计划更新与同run读回未闭环

精简证据定位：LIVE_EVIDENCE_SUMMARY.json 的 identity.changed_component_receipt 直接投影原API diagnostics中的逐组件 saved/current SHA；CATALOG_OWNER_METADATA.json直接投影原目录owner的COMPLETE、readback_status、页数和readback，不含正文或大响应。补充7份原链源码SHA见本目录SUPPLEMENTAL_SOURCE_MANIFEST.json。

现场saved input identity=4d253adb9e279c3764b7a556ba44624cc3f26420a2d2c34459fe760bbba7f81b；current=e3471732ee6a6f1d55106382aac35239655f3558d7b98a52320abd977d487db3；22:41读回changed_components为research_attention.material_input和research_attention.projection。旧计划拒绝消费是正确保护，故障目标是补上原owner自动重算、保存、terminal attempt与同run读回。

本地R2 Writer回归观察：canonical test_scheduled_existing_plan_is_not_reused_when_inputs_changed报WORKSPACE_PLAN_SAVE_READBACK_FAILED。源码在terminal成功attempt写入前进行_readback_plan，需核对它与新增owner_plan_readback要求的同run terminal证据之间的兼容性。这里只是具体定位线索；云端旧fixture或测试缺字段不能直接证明现役服务同根因。需单例复现和独立验收后再给结论，禁止为绿灯绕过原校验。

修复要求：
1. 只沿ManagerResearchJobService.refresh_workspace_plan与现有workspace_plan_autorun/plan_owner_dispatch入口接续，不新建producer。
2. 真实材料或评估变化时生成新run；新计划与终态attempt身份一致并可消费。日期、市场、cutoff、读合同、来源SHA仍严格校验。
3. 同日期同有效输入多次触发只复用有效当前run，不重发、不重复落盘；单纯读取时钟变化不能无意义重算。
4. 原产品与attempt写入失败、中断或身份不匹配时保留准确错误；下一合法原触发能恢复，不能把失败产物当成功或永久卡住。

## 断点二：发布API、Manager绑定与原自然触发身份不一致

现役API使用三路R1 app；外层scheduler仍保留已验收HK app，Manager子链绑定仍指向此前US daily chain集成app。保留外层HK调度不等于Manager绑定已随API更新。现役runtime_gaps包括NEXT_SCHEDULE_UNVERIFIED_ORIGINAL_RUNTIME_PLAN_READER_NOT_SUPPLIED和STAGE_EXECUTION_LEDGER_NOT_EXPLICITLY_BOUND；没有证据证明Manager目标12原计划已被自然触发。10/11晚外层20:01失败属于微信预选输入，不能冒充Manager失败或成功。

必须沿现有Manager supervisor -> binding -> run_manager_announcement_cycle -> plan_owner_dispatch -> 原owner -> 归档/计划 -> API读回接线。核对实际APP_ROOT、源码/manifest/SHA、允许日期、真实时钟、绑定与子进程，保持现有共享发布锁、CAS及回滚合同。按需补必要Manager绑定，而不是为此整体替换HK scheduler或复制一套调度服务。

另有R2接线缺口：ACTIVE apps/api/v35_api/app.py已创建shared_selection_consumer，但manager_research_job_service构造没有传workspace_stage_selection_reader；R2方法已能接受原正式消费者。若该依赖影响三路资格，最小接入既有消费者get()只读口，保持allow_backfill=False、日期/市场/原执行回执校验。不能将STAGE观察对象冒充正式产物。

## 断点三：target12三路逐日原产物未完成

| 路线 | 当前事实 | 原链修复目标 |
| --- | --- | --- |
| 公告 | 原owner目录COMPLETE/VERIFIED，target12/publication09，383条/21页；正文319条成功、64条失败；语义NOT_REVIEWED、原分析NOT_IMPORTED | 沿已有正文/判断/注册/导入链处理目标窗口，逐项保留已评估、未评估及错误，生成原owner产品及selection，不复制旧55只 |
| 超跌 | 10/09来源可投影214候选、34待核，PARTIAL；60日历史/前5日合同与成交量量纲/原owner计划证据未闭环 | 沿已有tdxpy/TDX及共享权威面板核缺口与量纲，保存target12原研究名单并读回逐股理由、来源及待核项 |
| 美股 | current_context_us_session=20261009已存在原始来源payload；target12 daily_run=NOT_RUN、DAILY_MAPPING_NOT_MATERIALIZED | 在原链真实允许时段消费US来源、全部原reviewed assessment及既有HK关系，生成target12归档与名单；保留全量发现及逐项映射/不入选/未评估原因 |

公告原目录run=1f816c69f65c4170b86e9eb8df25fd85，catalog SHA=1711c75a927b57bd5581eaaa505f29d649f11d14ce6a10d75e27f427fb115866。正文batch于10/11 22:37:40 +08结束：383终态、319 COMPLETE_CONTENT_API_BODY、64 BODY_CAPTURE_FAILED（62 BODY_CAPTURE_FAILED:ValueError，2 BODY_CONTENT_116_H_STOCK_IDENTITY_MISMATCH）；314秒、854物理请求。不能凭62个ValueError推断无正文或更改来源身份，必须沿原日志/缓存逐项定位并有界恢复。正文运输成功不等于语义判断或入选。原始响应、正文和业务数据仅保留Mac本地，不上传。

今天10/11是周日，target12每日自然槽尚未到；NOT_RUN不能自动视为当天scheduler故障。可以完成候选工程验证和目标输入准备，但禁止假时钟/改日期模拟自然通过。若原允许窗口决定12日才产生产品，应说明确切原槽和依赖，届时验收；不能把任意手动回放写成自然结果。

## 必须同时通过的验收要求

| 验收场景 | 唯一可接受的行为/证据 |
| --- | --- |
| target12真实名单 | 公告、超跌、美股三路分别有实际代码/名称/数量/逐股理由，selection_date=plan_date=20261012；公告和US来源日遵守原合同与窗口。新run/product/selection/输入及原owner receipt SHA齐备；合法空名单必须有真实执行和评估证据 |
| API与页面 | 原owner保存/同run读回、8873 API与重新加载V4原页面三者同日期、同run、同SHA、同名单/待核状态；不把API 200或卡片可见当通过，不改变V4布局和工作流 |
| 新输入接续 | 在隔离小样本中加入真实来源变化，旧计划仍正确stale，新owner run成功保存且读回CURRENT/consumed；旧封存run保留。每个变化组件可追溯 |
| 同输入幂等 | 对同一日期、输入和配置连续触发原入口两次，无新增重复产物/重复导入，run及selection SHA稳定；读取时钟变化不产生无意义过期 |
| 跨日 | 沿原交易日历与真实允许槽自动选择下一目标日及完成行情/公告/US来源日；不可消费另一日期latest，周末/休市有明确未到期/不适用状态。禁止照搬12日名单到后续日期 |
| 每路失败与恢复 | 单项正文/一只股票缺数据按原合同隔离并显示待核，不使无关路线无法执行；整路缺产品保留NOT_RUN/NOT_IMPORTED/失败，不伪装0。修复输入后下一次原触发可接续且无重复 |
| 真正每日自动运行 | 无人工POST、无手工改计划、无新闹钟，由原scheduler/Manager子链真实触发；有slot/target/source date、binding与源码SHA、dispatch/attempt终态、原产品归档，随后API/UI同run读回。至少target12自然槽；后续每天沿同一合同核对，尚未到的日期明确NATURAL_SLOT_UNVERIFIED |
| 回归与边界 | 不破坏已跑通日期的原消费与名单；10/9事后计划不变盘前证据；A/HK保持分离、HK权威资格不被绕过，BUY/交易门禁与Vibe8910保持 |

## Chat交付与Mac接续

先复现一个输入变化/保存读回小样本及原binding接续；一批一次主要变量。返回基于明确源码SHA的最小可应用补丁、修改前后SHA、新增必要测试、实际命令/结果与未执行项。说明runtime与canonical各自补丁及适用基线；不同源不能整体互相覆盖。不要只交报告或空ZIP。

现有R2本地Writer结果仅辅助：focused canonical 5 pass、candidate US/date subset 12 pass；广泛canonical 35 pass/3 fail，candidate 12 pass/3 fail，其中后者含旧调度fixture缺同run terminal attempt的情况，必须先区分fixture与真实行为。未有独立Reviewer复跑，不标TESTED/BEHAVIOR_VERIFIED。相关失败摘录已在本目录LOCAL_R2_RESULT_SUMMARY.json。

云端无Mac真实运行/数据时，DEPLOYED、API_VERIFIED、UI_VERIFIED、BEHAVIOR_VERIFIED、NATURAL_VERIFIED均NOT_RUN/CANNOT_CONFIRM。补丁由用户交回后，本地主控派唯一Luna Max Writer合入、不同identity Reviewer独立复跑，通过才用原可回退流程发布8873并验收12日三路及每日更新。工程、手动、事后回看、自然运行分别记录。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。

