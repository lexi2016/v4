# 10 月 9 日自动阶段选股：开盘前阻断问题包

**唯一目标：准备好目标日 2026-10-09 的有效预选池，让原定时任务自动产生阶段选股结果，并在 V4/8873 页面读回。** 用户原称“明天”；核查跨过午夜，本文始终固定 10 月 9 日，不顺延成 10 月 10 日。

这是给蔡凯的代码问题交接。不要继续泛化 API 架构或发布框架，不把 218 项源码测试通过当成目标日业务成功。当前最重要的不是“测试数更多”，而是下面的实际链路能跑通。

## 1. 当前结论：10/9 港股尚未就绪，A 股有后台行但页面读不到

| 环节 | 2026-10-08 23:56 至 10-09 00:10 +08 核查结果 | 意味着什么 |
|---|---|---|
| 10/9 A 股主预选池 | 后台 37 行，声明 V192_CANDIDATE_READY，信号日 10/8 | 不是全部没生成；仍须真实 consumer/来源验收 |
| 10/9 A 股研究推荐池 | 后台 186 行，声明 RESEARCH_RECOMMENDATION_POOL_READY | 与主池按代码初步合并为 216 个键；不是已验收的 Stage 输入数 |
| 10/9 港股 Top100 | 0 行 EXPECTED_MISSING 占位，非有效池 | 港股阶段的前提没有满足 |
| 10/9 港股上游评分 run | 精确目标目录不存在 | 不能从空占位宣称 Top100 已准备 |
| 10/8 港股证券主表 | latest 只有截至 9/30 的 36 个日期条目，缺 10/8 | 阻断 10/9 池的精确日期输入 |
| 10/8 17:30、18:00 预选调度 | 选中 preselection_pools，但 UPSTREAM_NOT_READY，started_workload_ids=[] | 不是 producer 已运行完成；具体 gate 明细尚缺证据 |
| 现役预选池 API | date=10/8 和 10/9 都 HTTP 200 / DATA_BLOCKED_EMPTY / 0 行 | 页面空还叠加 API 读取回归，不能仅凭该提示诊断数据不存在 |
| 10/8 HK Stage | 每个已记录阶段均在 exact input binding 被拒绝 | 没进入正常选股计算，不是有效筛选后没有股票 |
| 10/9 自然阶段 | 核查在凌晨，09:xx 时段尚未到 | 未发生的自然结果不能预先判成功或失败；目前有明确风险 |

机器摘要见 [CURRENT_READBACK.json](CURRENT_READBACK.json)、[A_POOL_SOURCE_STATE.json](A_POOL_SOURCE_STATE.json)、[HK_READINESS_STATE.json](HK_READINESS_STATE.json)。只上传计数、错误和哈希，没有原始股票行情。

## 2. P1：10/9 港股池缺失的具体故障链

```text
10/9 目标需要 10/8 价格与 10/8 港股通资格输入
  → hk_security_master/latest.json 没有 entries["20261008"]
  → 现役 loader 读取该键，抛 KeyError '20261008'
  → 精确 HK 输入合同校验失败
  → 10/9 本地池写成 EXPECTED_MISSING / 0 行
  → 没有可供 Stage 消费的合格 Top100
```

占位错误原文：`HK_0_2_EXACT_INPUT_CONTRACT_INVALID:HK security master verification failed: HK security-master metadata invalid: '20261008'`。

证券主表索引 SHA `7547d5c65a773ebeb51a81ec0a1ab173dc311ee3009b61088bede48260bcd763`；10/9 港股占位 SHA `3d00fc3ebd27df59724d808277d256d4636aedde1d0c3dc620a34c99fa166f7f`；receipt SHA `de4422c1367561988f1fa56dfb6cd7215cf65f19e99943f345fbbf4804708f51`。原路径和 manifest SHA 见机器摘要。

**自动恢复为什么没有完成：**现役 `executor_registry_preselection.py` 调 `ops.ensure_hk_security_master` 时明确传入 `--reuse-only`；这个模式只能复用已有精确日期条目，不能生成缺失的 10/8 主表。与此同时，17:30、18:00 的 dispatcher 已在 workload 启动前报 UPSTREAM_NOT_READY。两项已分别确认，但现有 receipt 没给出完整 gate 明细，不能擅自说该 gate 唯一原因也是主表缺失。

**修复任务：**沿既有 security-master owner 补齐“采集/生成 → 校验 → 发布精确日期 entry”的调度依赖，再让已有 HK 0.2 producer 生成目标 10/9 Top100。先判断当前 canonical 是否已有可复用实现，再做实际 owner 的最小适配；不能仅删 `--reuse-only`、绕过 gate 或塞一份伪造主表让检查变绿。校验缺日期时应报清楚缺哪个输入，避免只有 KeyError 字符串。

另外，**10/8 价格面板是否已独立刷新尚未确认**。主表补齐后仍要核精确 10/8 价格输入、评分 run、100 个唯一 HK 代码及上游三件套，不能把第一个报错消失当整条链路成功。

## 3. P1：10/8 港股阶段为什么全部失败

现役 Stage 日志对 09:25 至 15:55 各记录阶段都报：`HK D1 split-date eligibility provenance missing`。

10/8 上游 run 虽写目标 `trade_date=20261008`，实际 capture/start/finish 是 **9/30 17:30:43**，100 行的 signal_date、截止与价格仍是 9/30；本地池又缺 `price_signal_date`、`eligibility_source_date`、`historical_provenance` 等合法分日期来源绑定。100 行“存在”并不代表它们符合 10/8 阶段输入。

10/8 正确边界是价格 10/7、此前港股通资格 9/30；10/9 则应为价格和资格均 10/8。日期依据见 HKEX [2026 Stock Connect 日历](https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/Stock-Connect/Reference-Materials/Trading-Hour%2C-Trading-and-Settlement-Calendar/2026-Calendar_pdf_e.pdf)和[香港证券市场假期通知](https://www.hkex.com.hk/-/media/HKEX-Market/Services/Circulars-and-Notices/Participant-and-Members-Circulars/SEHK/2025/ce_SEHK_CT_075_2025.pdf)。**不要把 10/8 的分日期故障机械套到 10/9；也不要以 10/9 日期一致就忽略当前缺主表/评分 run。**

修复 producer 的目标日、价格日、资格日传递及真实来源绑定；Stage 严格校验保留。上游 artifact/manifest/receipt 和本地池 snapshot 三件套必须分开，不能用本地 SHA 代替上游来源身份。不得把 9/30 旧数据重标成 10/8，也不得改历史 capture 时间。

## 4. P1：已有 A 股池为什么页面仍为空

现役 API 仍是 `manager-workbench-r1-mac-20261008-api-r2`。此前整体 API 发布漏带预选池两处修复：传递配置来源根，以及空本地池分支处理。当前 API 从缺目标池的根读取，所以连实际存在的 10/9 A 股两组数据也显示为空。

接口的泛化原因 `V3.5 independent preselection producers have not materialized this date.` **不能证明目标池不存在**；10/8、10/9 都有反例。需要恢复真实来源读取，并显示分市场/子池缺失原因：A 股有有效可追溯输入就继续，坏来源只隔离；HK 空占位不得冒充合格池，也不能反过来全局阻断 A。

这一 consumer/API 修复已有 [Issue #30 源码候选 2ead7eb9](https://github.com/lexi2016/v4/tree/2ead7eb9e9f067b69610d24990bc47f792bc75b4/handoff/issue30-api-module-isolation-20261008-r1)。**直接复用，不重写发布框架。** Mac 独立复跑 218/218 已通过；真实来源、完整 app 与经理联合 canary 尚未运行，未部署，页面未恢复。Mac 候选已构建但未独立验收，不能直接执行旧 plan。精确状态见 [ISSUE30_MAC_STATUS.json](ISSUE30_MAC_STATUS.json)。

## 5. 必须针对实际 owner 修，避免“canonical 改好了但运行的还是旧版”

| 面 | 实际身份 | 本包源码目录 |
|---|---|---|
| API 页面读取 | manager-workbench-r1-mac-20261008-api-r2，app before SHA 90a2bf… | 复用 2ead7eb9 的原像/后像及 Mac 状态 |
| 预选 producer executor | V3.5 release 20260929-manager-1555-pytdx-r1 | source/actual_pool_scheduler |
| HK shared owner | V3.5 release 20260923-hk02-owner-rebase-r2 的 upstreams/v3_shared_data | source/actual_shared_owner |
| 完整 Stage | 调试目录 issue23_runner_helper_r3/stage_r1_binding_candidate_r3/app | source/actual_stage |
| 统一源码项目 | /Users/lexi/Desktop/学习/v4_app，有既有未提交修改 | source/canonical_reference，仅比较参考 |

本包提供实际执行文件、不同的 canonical 对应文件及逐文件 SHA，见 [SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。canonical 的 executor 已拆到 `_executor_registry_parts/preselection.py`，**不是直接拿它覆盖旧单文件 executor**。这些是定位切片，不是完整可部署应用；缺其他依赖时定点索取，不凭 main 或旧快照拼造现役闭包。

本批修复唯一目标链路；不顺带迁移整个旧系统、改模型、改选股排名或处理历史所有 P2。

## 6. 必须返回的最小交付与验收

1. **输入准备：**用原 owner 生成并验证 10/8 主表和价格输入，产出目标 10/9 上游 Top100 三件套与本地池；100 唯一 HK 代码、精确日期、来源 SHA 和 capture 可追溯。缺输入要给具体原因，不能用 EXPECTED_MISSING 或旧日替代。
2. **调度闭环：**查清 preselection_pools 的 UPSTREAM_NOT_READY 依赖链。缺失主表/价格的准备工作必须能被合法触发，不能让负责准备输入的任务又永久依赖同一缺失产物。给失败原因、可恢复重试与成功回执；不能仅证明调度器进程存在。
3. **阶段消费：**使用真实目标池做隔离单阶段 canary，证明原 Stage 能绑定并生成选择结果。正常空选允许，但必须有 verified run/artifact，和输入失败严格区分。不删除/重置已保存的历史 settled slot。
4. **预选池页面：**完整现役 app 加最小 consumer 修复，真实日期 A/HK 结果与来源一致；分页只影响展示，完整输入不以 200 行截断；经理公告、日期隔离和 workspace 行为保留。不能只用合成 A=2 的测试替代真实源。
5. **发布与自然运行：**返回精确前像/后像、当前 owner 适配、定向测试、最小可回退发布步骤。由本机独立验收后发布相关研究服务，再检查真实 API 和重载页面，最后核 10/9 自然运行 receipt 的目标日、输入 run/SHA、实际加载版本和结果。手工 canary 不能报 NATURAL_VERIFIED。

现役 Stage 计划触发：09:15、09:25、09:35、09:40、09:45、10:30、13:15、15:00、15:50、15:55。**输入与部署验收应在第一轮 09:15 准备/触发前就绪**，不是等 09:25 再发现缺池。09:20/09:25 的实际采集窗口和阶段绑定仍以原合同核验；计划存在不等于届时一定成功。若开盘前仍缺关键来源，明确 BLOCKED，不承诺“保证成功”。

用户已明确要求：蔡凯完成代码后，由本机测试并发布，目标是 10/9 自动阶段成功。该授权限本目标必要、可回退的本地研究服务，不扩到真实交易、外部生产、无关服务或数据改写。当前这轮只提交问题包，没有部署。

## 7. 不混入本批及安全边界

历史 A 股 09:25 昨收持久化、研究字段、嵌套历史 provenance P2 等继续关联 [#28](https://github.com/lexi2016/v4/issues/28)，不让它们掩盖当前港股池与自动运行阻断。已有历史两项 P2 的 Mac 38/38 与 HK trio 合成 15/15 结果保留；它们不证明本次目标输入已准备。

保留 V4/8873 唯一入口、原权威 producer、A/HK 分离、Vibe8910 原样；需要历史行情时沿现有缓存优先 TDX/tdxpy 链，不另建底板。`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。不上传原始行情、账户、凭证、完整 plist/环境、venv 或 dist。
