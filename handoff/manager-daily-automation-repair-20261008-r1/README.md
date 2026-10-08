# 经理选股工作台每日接续修复

> 本包交付原业务链的代码差异、实现测试、独立复验和本机执行入口。真实 10/8 补算、正式 API/页面及连续自然运行仍须现场验收；业务总目标尚未宣告完成。

依据固定问题包 [09f82ac](https://github.com/lexi2016/v4/blob/09f82ac665e36a002e7f67f949b7e38f4e0598bf/handoff/manager-daily-automation-problem-20261008/README.md)，本轮交付原 owner 的每日调用、输入接续、按日计划保存和普通页面读回差异。保留原公告规则、US reviewed 关系范围、超跌筛选规则和研究边界。复用 [0602f34 两项修复](https://github.com/lexi2016/v4/blob/0602f34fd10f7daff9bf688a710835d1bda43865/handoff/issue29-manager-daily-repair-20261008/README.md)，不把它们假定为已经部署。

## 业务问题的直接回答

- **10/8 是否补选完成：尚无完成证据。** 问题包冻结于 10/8 23:46（上海时间）的现场状态仍为计划 `NOT_MATERIALIZED`、US daily `NOT_RUN`、超跌 `CANNOT_CONFIRM`；公告已有合法研究产品。当前轮没有在 Mac 执行正式 owner 或查询新的现场结果。若后来执行已在 10/9，应以真实执行时间标成 10/8 事后研究。
- **之后是否能每天自动完成：尚未通过自然验收。** 代码接线与隔离测试、受保护集成、实际供源、实际启用及连续自然运行是不同证据层。必须取得至少两个连续适用交易日的完整原调度证据后才能宣告业务目标完成。
- **仍需解决哪些现场阻断：** Issue #30 共享发布保护与累计基线、实际原 US 采集任务、公告审核产品的持续生产入口、HK 合法历史资格与价格量纲证据，以及完整应用依赖。具体事实及责任入口见 [输入与运行缺口](docs/INPUT_AND_RUNTIME_GAPS.md)。

## 修复覆盖与原链路

| 断点 | 原 owner / 入口 | 本轮代码实现的行为 |
| --- | --- | --- |
| 原任务只到抓取或 disabled binding | AnnouncementCycleHook、原 worker、同一个 8873 service | 在原 MORNING / PREOPEN / EVENING_NEXT_SESSION 生命周期内接每日调用；提供有界同日迟到补算与可生成 enabled daily 配置的原 renderer，保留所有真实 canary 和来源 gate。 |
| US daily owner 未被调用 | `refresh_us_mapping_research`、原 peripheral reader、原 registry | US 先用独立预算运行并保存同目标日 run；精确 completed session 与 availability；重复、重启、忙、超时和单通道失败保留独立回执。 |
| 公告合法成果未进入计划 | 原 reviewed product validator、import、workspace consumer | 合法产品到达后进入后续原计划评估，保留原股票/理由和 SELECTED/WATCH/未评估语义，保存实际 consumed SHA。 |
| HK child 只做 panel，漏后续原发布 | actual HK child `07aa9770…`、既有 gate/ensure、原 HK upstream | 同次 capture 接续 membership/V2、HK02、master 与完整读回；只认精确日期和原来源，首个失败阶段留证；沿原缓存优先 TDX owner 补合法缺日。共享 latest 的发布时字节封存于本 chain，次日正常推进索引后仍能精确验证旧日，真实旧产物损坏继续拒绝。 |
| 计划与最近失败尝试混淆 | 原 `refresh_workspace_plan`、原 store/history | 按目标日保存不可变产品与同 run attempt，区分已保存计划和后来尝试；同 slot 重放或有足够原证据的恢复不覆盖历史。 |
| 普通页面缺三路读回与日期隔离 | 原 ManagerSelectionView / catalystObservationPanel / dailyChannels / researchAttention | 独立展示公告、US daily、超跌股票与理由、日期、运行状态和缺口；HK_CONNECT 保留资格含义；全部请求日期变化立即作废旧结果。同完整绑定按封存研究上下文重验原来源，另记真实读回时间，避免保存后几秒即失效；真实来源或日期变化仍不认作同一计划。 |

这张表描述代码行为，通过范围见 [测试记录](TESTING.md)、[逐文件清单](source_manifest.json)、[最终独立 review](independent_tests/final_review.json) 和 [分层验收状态](acceptance_status.json)。缺输入保留 unknown/null；只有规则实际评估成功后的空集合才表示零入选。

## 交付组成与保留核对

本包声明 **33 份源码／实现测试文件：20 份生产模块、13 份测试或 fixture**。生产模块分属 API 11 份、普通 web 4 份、actual HK child 4 份、原 HK upstream 1 份。独立测试、原始日志和 review 报告另附，未并入上述实现文件计数。

每份文件均有完整 after、可逆补丁、after SHA256，以及实际应用根的核验要求。21份已有文件另列 before SHA256 和原字节在冻结 GitHub 树中的位置；12份新增文件在供给树中无前像，应用前必须在实际目标根核验该路径不存在。[补丁核验](evidence/package/patch_verification.json) 在6类隔离根完成正向应用、精确文件集合比较和逆向恢复，另核2份已验旧修复的增量。[源码范围核验](evidence/package/source_scope_audit.json) 检查17个本地保留身份，并确认 actual HK 入口的非 HK 部分保持原 AST；这项本地检查不冒充现场 #28 联合保留验收。

[独立包装复核](evidence/package/final_packaging_source_review.json)另核每份冻结前像、目标运行根、after 和补丁重建；[测试证据绑定](evidence/package/review_source_binding.json)将 Writer 和独立 Reviewer 的报告绑定到最终源码 SHA。全包文件身份见 [package_manifest.json](package_manifest.json)，其自引用排除规则写在清单内。

## 如何使用交付

1. 先读 [源与测试基线身份](evidence/test_baseline_identity.json)、`source_manifest.json` 和 [原依赖映射](required_dependencies.json)。这里是不同运行层的最小差异包，不是可整树部署的应用。
2. 由 Issue #30 的唯一集成 owner 在受保护的新累计基线核 before SHA，再应用对应 profile 的有限补丁。API、web、HK child、HK upstream 是不同根；`scheduler_prerequisite` 仅核保留配置，不能把 canonical scheduler 配置复制到现场。
3. 按 [本机执行与验收入口](docs/HOST_EXECUTION.md) 完成真实依赖、绑定、集成、10/8事后补算、API/页面及连续自然日核验。该文件的命令是执行交接，不是已执行回执。
4. 回滚只撤销本轮有限 delta，保留不可变研究 run、历史 attempt 与当前累计功能；不能切回旧整包覆盖 #28。

`source_manifest.json` 列出每个文件的目标 profile/path、原来源/commit、before/after SHA256、完整 after 文件与可逆补丁。workspace/history 同时提供旧 R2 → 合并结果与已验候选 → 本轮增量两个比较口径。

## 日期、能力与验收边界

完整日期和恢复合同见 [OWNER_AND_DATE_CONTRACTS.md](docs/OWNER_AND_DATE_CONTRACTS.md)。时点/幂等要求、保存计划的实际页面读回以及跨日索引合同见 [REVIEW_CONTRACT_DECISIONS.md](docs/REVIEW_CONTRACT_DECISIONS.md)。

US daily 只使用现有 reviewed 关系范围；固定采集配置覆盖不等于全市场映射。US raw attention、daily mapping 和 reviewed 回看分别显示日期与范围。港股报价集合不能替代 Connect membership，TDX 价格补缺不能替代历史资格或单位证明，晚到数据不倒签盘前。

真实 9/30 原 run 的 `HISTORY_SOURCE_INPUTS_CHANGED` 保持拒绝。没有原组件输入摘要时，不能推断是数据变化还是上下文漂移，也不改写历史以消除拒绝。

本轮按问题包的发布边界交付代码、独立测试及执行交接；Mac 补采、POST、启停、启用和部署需由原共享协调流程执行。`NATURAL_SLOT_UNVERIFIED` 将一直保留到实际自然证据齐备。

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`。
