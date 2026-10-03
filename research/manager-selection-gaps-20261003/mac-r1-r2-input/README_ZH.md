# Issue8 R1 本机验收及 R2 最小补充输入

原候选ZIP SHA256 d9e2e643877c16fc9fccc6ea35add6e65cf3c4f4fbcc362b4d5b602de7d86517。后端runtime.patch SHA256 8b1b614b59f06f62b8a64b4fd738f0d2ed82cb6b460f9b359ddd7ad952de8c88。继续原Issue #8，不新开重复问题。

## 已核实
Mac原服务Python3.14.6完整隔离R9候选、真实native import：Writer 113测试通过；独立验收以附带Reviewer最终receipt为准。真实日历SHA匹配，10/2港股证券开市、港股通休市，formal_selection NOT_APPLICABLE，membership缺件仍CANNOT_CONFIRM。活动服务尚未切换，canonical仍未覆盖，两个文件存在canonical漂移，不得用整个after覆盖工作区。

## R2必须补齐的页面接线
active R9 renderer只遍历attention.cards；新observation_only/input_diagnostics/formal_selection不显示，TS类型/validator也未覆盖。source/为活动R9的3个前端文件、相关已有测试及package.json，逐文件SHA在SOURCE_MANIFEST.json。
沿用已审后端结果，只做最小类型/语义校验与页面接线。将独立公告观察明确显示为研究观察/资格未确认，不与正式候选、scored cards、focus混淆；休市显示正式选股当日不适用；来源覆盖/缺口分别解释。旧payload应兼容，缺字段不能变READY/有效0。保持#22成功原因文案、#24保存读回及现有页面功能。
前端只读展示不改变正式资格/排序/BUY，不以9条/5股固定值硬编码验收。加入真实形态payload的渲染/校验测试，覆盖缺字段、休市、部分覆盖、未知资格、非法时间/安全字段。

## US单条原始证据已补齐
Writer通过既有ResearchLaneSource和_read_archive核验HK.00300原文章，payload/receipt/manifest与冻结引用一致。原source_row的available_at、retrieved_at均缺key，material对应值null；不是卡片层漏传。collected_at/first_seen_at存在，均为2026-09-29T21:03:02+08:00；目前语义未证明，不能擅自映射。详见Writer receipt字段存在性、类型、值和原owner摘要。
因此R2禁止无证据新增时间别名fallback。若需要进一步研究collected_at/first_seen_at等价性，先明确所需原owner producer/contract具体文件，由本地提供；现有缺口继续CANNOT_CONFIRM，不造时间、不改历史数据、不另采集。时间合法仍需独立HK/US主体关系证据。

## 交付
提供在R1后端基础上的R2增量runtime.patch、完整after、before/after SHA、测试与回滚说明。后端若未变化复用既有验收，不重做大计划读取/广泛采集。未完成页面接线前不宣称UI_VERIFIED；自然时段未验收。RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。Stage/BUY/Vibe8910/服务/调度/历史状态禁止改动。

## 最终独立验收
Reviewer native113/113 PASS；3个after SHA匹配；真实日历与冻结子树只读重投影：9观察/5股，0 scored，READY_WITH_GAPS，安全标记不变。BEHAVIOR_VERIFIED仅离线限定范围。Reviewer日历probe未绑定owner root，因此该probe的ROOT_NOT_BOUND不代表活动R9配置；活动原owner缺件事实使用Writer同环境回执。原owner单条由Writer验证，Reviewer未重复读取。未部署/API/UI/自然验收。
