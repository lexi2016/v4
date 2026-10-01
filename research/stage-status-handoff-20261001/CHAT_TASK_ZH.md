# 给指定Chat的编码任务

用户指定你完成代码，Mac只负责本地交付与独立测试。请基于本交接完成已查明的最小HK修复，不再提交更多诊断计划或扩大修复。先读STATUS_AND_PROBLEMS_ZH.md、CURRENT_BINDINGS.json、FILE_MANIFEST.json和evidence/hk_source_audit.md；源码完整相关文件在source/canonical与source/active，冻结r2差异/preimage在frozen_r2。

GOAL：港股证券开市但港股通休市时，沿原自然owner生产正确价格日的HK输入，合法资格source as-of/capture/身份贯通至projector与Stage；用真实来源刷新下一Connect阶段目标，而不被缺9/30历史authority拖死。

WRITER：本Chat会话。Mac不再另派业务Writer。REVIEWER：Mac独立Luna Max Reviewer。

ALLOWED_PATHS：frozen_r2/batch_manifest.json的13个路径，只改必要项；必要既有依赖限ops/ensure_hk_security_master.py、stage_center/hk_universe_preflight.py、既有shared hk_security_master / acquire_hk_security_master / materialize_stage_universes publisher；active r9单体owner的对应最小hunk。可一并修正App.vue空HK卡片使用合并状态的文案问题，仅显示HK自身证据。其他页面状态不批量改绿。

FORBIDDEN：A新增业务修复/阶段重跑、F5/经理、Vibe8910、collector/provider/selector、BUY/交易/预算、真实数据改写、历史authority/时间补造、第二producer/面板、R4整包覆盖、6项旧catalog/status漂移、服务配置启停/部署。

已知边界：

1. A三日21普通适用阶段均10行历史结果，已收尾。formal selection/任务状态默认不读backfill，普通workbench读backfill，不能把不同入口当A回归。
2. HK9/30八阶段0，D1源具体错误master metadata invalid:'20260929'；9/29尾盘只有ExHQ probe failure证据，不推网络/全阶段同因；9/28旧price日需语义纠正但不补造数据。
3. r2 13文件独立20通过但P1：资格source硬编码上一Connect日9/30+capture同日；真实authority pointer缺，689价格集合与696成员master不能相互替代。9/30历史capture时间缺失的恢复路线已终止。
4. 更新旧结论：10/8 Top100已存在且API/UI100行READY，所有行signal_date仍9/30；现有早期快照不等于10/7→10/8自然刷新或正式输入ready。保留它的真实血缘，Stage应拒绝目标日前一证券日不符的价格。自然HK-only日来源选择必须从原as-of/有效性合同确认，不能只删时间校验。
   原件manifest/receipt时间为9/30 17:30:43，envelope缺target_date/stage_selection_eligible，stage_reuse_status=CANNOT_CONFIRM。原publisher已由普通Stage tick使用、只接受当下上海日期并记录真实capture，preselection owner尚未调用它且master为reuse-only。优先复用该producer，不能新建同源采集链。
5. 实际API是R4 merged，preselection r9 app和20260923-hk02 shared分别绑定，Stage是20261001-stage-pr16-a1445-a0925-crossday-r1；canonical模块化owner与active单体owner不同，分别提供最小补丁，不整文件覆盖。
6. 你已有PR16 e97b9e3 A1445代码保持现状；Mac新17项与原4076→811b只读回放NOT_RUN。只请提供已有A1445完整ZIP可下载链接；不要再编码A，不跨日延长授权、不执行selection。actual Stage context是第三SHA（包内有完整原件），Mac需隔离适配。

PASS_SIGNAL：一轮集中验证HK-only原owner→原publisher（必要时）→shared→projector→Stage的价格日/资格as-of/来源身份；真实seed并读回已有A池保全；双方开市兼容；错价格日/未来source/缺capture/身份损坏反例。保留最终完整来源SHA/日期/market合同，不放松校验凑绿。只报告你实际执行的日志与环境，未跑的Mac/自然验收明确NOT_RUN / CANNOT_CONFIRM。

STOP_RULE：真实源/采集时间缺失保留具体缺口，不能继续历史恢复框架、借master时间给union或靠696数量放行。代码工作不以重建9/30authority为前置。若包确缺必要单一文件，只准确点名文件/合同，不要求再次上传全项目或202行行情。

交付：在GitHub适当隔离分支/Draft PR给固定提交，canonical和三个active基线的完整after与精确patch、before/after SHA清单、目标测试源码/完整stdout-stderr-exit、可下载ZIP、一份Mac一次接续说明。无需重跑代码/输入未变且已独立通过的测试。保持RESEARCH_ONLY=true / production_allowed=false / buy_gate_updated=false / orders_sent=false。不合并、不部署，不宣称阶段恢复或自然成功。
