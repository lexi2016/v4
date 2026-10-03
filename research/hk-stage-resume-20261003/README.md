# V4 港股阶段选股接续问题包 · 2026-10-03

本包为冻结源码与证据切片，不是完整可运行应用，不可整树部署。用户分工：Codex 主控编排、问题包和验收；Chat 分析问题并提供代码；Luna Max 适配落地、测试与反馈；独立 Luna Max Reviewer 验收。

## 复用已完成工作

用户共享会话 cx_6ac058877ed08191af91ba8cce7ec93c 最后消息对应同一 HANDOFF_20261003.md；用户本轮确认，且文件与本轮附件 SHA 完全一致：9a73fb5d42bc86cf646c81e4845a1b92b72c45376ae8ad394a7417fb002fbf42。

- R7 显示/API 语义修复已上线；既有独立 focused API 和真实 Store→consumer 链验收复用，不重写。
- 既有 32-cell API 矩阵：20 CANNOT_CONFIRM、12 OBSERVATION_UNVERIFIED；本轮不重复全矩阵。
- 早前预选池 R3 已验范围复用，不重新实现。
- 历史20项缺失审计复用：19 PIT_UNSAFE、1 ORIGINAL_CAPTURE_MISSING。没有新原始输入，不补写正式历史结果，不重写四个已有selection。
- 本轮新补：旧池绑定候选独立审核，20 focused PASS；相邻13 PASS/1导航失败在原部署baseline也重现。见 evidence/independent_binding_review.json。

## 当前版本与目录角色

- API plist仍绑定 hk-stage-display-r7-20261003-a1b7613a2b0fbb29，healthz=ok，readyz三交易标志false；stage plist独立绑定20261002-hk-open-stage-r1。配置/健康读回不冒充自然运行证明。
- `candidate/`：已有旧池绑定候选，runner最小diff只涉及 prior Connect observation，不是API前端基线。
- `deployed_stage_baseline/`：stage R1原文件，只读对照。
- `deployed_api_reference/`：API R7普通页面源码，内联 App.vue。
- `canonical_reference/`：本机当前正式研发源码快照，App已拆app_shell、preselection已拆子模块，禁止整文件以部署版覆盖。
- `evidence/`：Writer回执及本轮独立审核摘要。路径与SHA详见SOURCE_MANIFEST.json。

## 问题A：HK证券开市、Connect休市日期的导航

冻结候选与stage基线均重现：`tests/test_hk_observation_calendar_20260925.py::test_date_catalog_keeps_hk_open_today_navigable_without_promoting_it_as_a_pool` 期望navigation_date=20260925，实际20260924。这不是runner候选新回归。

部署版domains/preselection.py使用通用known_non_trading_dates判断导航，与逐市场日历不一致；返回也缺hk_observation_only_dates。修复应复用已有逐市场日历，只使HK观察日可导航，不能把该日期伪装成当日有效预选池或当前Connect资格。canonical对应拆分模块须分别适配。

## 问题B：普通页面与API观察行不一致，以及深链接初始化

页面Reviewer首次验收报告：9/30缺失结果已正确显示待确认/缺少正式产物；9/28 09:30–09:35 API有10条OBSERVATION_UNVERIFIED，页面却显示历史回补读取失败且无观察行；直接打开带date/stage参数的URL初始为日期未指定、09:25。稳定读回补充见evidence/ui_review.json，结论以该文件为准。

请检查部署版App.vue中的URL初始化、历史回补读取和候选行优先级，并对照canonical app_shell拆分结构。保留观察标签、未验证原因和formal_eligible=false；不得通过升格观察为正式或放宽后端条件使页面出现行。

## Chat交付与验收

1. 先列出复用项，不重做显示后端、32-cell API矩阵、预选池R3、历史缺失审计或已通过的prior-binding逻辑。
2. 按问题A/B给出最小补丁与针对性测试，明确部署版与canonical的对应路径和前像SHA；必要文件不足时给精确路径清单。
3. 若提供既有binding最小适配，保留其已验语义，明确canonical前像不同；不得整体替换runner。
4. 本机Luna完成适配、测试并由独立Reviewer复跑；Chat环境未运行的项目明确NOT_RUN。
5. 页面必须在稳定加载后核对URL日期/阶段、9/30缺失态、9/28十条观察行与名称/原因；不能以API正确代替UI。

边界：不接管经理公告/US链，不动Vibe8910、不改A股DECISION_LOCK、模型或BUY。RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。禁止新producer、当前池填历史、伪造capture/cutoff；未证明的PIT保持CANNOT_CONFIRM。自然运行保持NATURAL_SLOT_UNVERIFIED。
