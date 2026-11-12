# 原公式与 v1.9.2 的规则差异

本批只比较既有候选名单和规则，不评价收益优劣，不修改公式、评分或 BUY 门。原公式采用 `d35c9a30…` 的原文解释器；v1.9.2 采用冻结的 `v1.9.2_FMLA04_TRACE_AWARE_WAIT_SPLIT`。

| 项目 | 工作台“原公式” | v1.9.2/FMLA04 |
|---|---|---|
| 原始信号范围 | 一级：B3 或零上二金；二级：B1/B2/突破/突破接十字星/零下二金之一，且不同时计一级 | 先满足金砖、共振、主/次买点等既有 entry_pool 条件 |
| 附加判断 | 同一关键K前的红绿量条件、锚点适用性、既有风险处置 | 多头评分角色为 B2_FRESH 或 B3_CONTINUATION；risk_chase_score < 45；fresh/continuation >= 70 或 final_score >= 85 |
| 其他角色 | 原式信号满足并通过附加条件即可命中 | 等回调、主升持有、人工待核及风险角色不因原式有信号就自动变为候选 |
| 关系 | 覆盖多种原式触发类型 | 另有评分与角色路径；不能假定是“原公式名单”的严格子集 |
| 排名 | 原式命中不等于优先买入 | 分数和排序仅供复核，不能当买入顺序 |

原公式在两个来源日的已保存结果（分支允许重叠，不能把分支计数相加当股票去重数）：

| 来源日 / 观察日 | 去重 | 一级 / 二级 | B1 | B2 | B3 | 突破 | 突破十字 | 零上二金 | 零下二金 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 11/11 / 11/12 | 44 | 3 / 41 | 5 | 0 | 0 | 15 | 7 | 3 | 14 |
| 11/12 / 11/13 | 40 | 2 / 38 | 17 | 0 | 0 | 9 | 7 | 2 | 5 |

原式数值中买点和卖点标记可能同日出现：11/11 的44只中有3只，11/12 的40只中有11只。当前“原公式”组的附加风险过滤与原式“卖点”字段定义不同；本批记录该差异，不自动修改选股规则。原图数值已保存不等于逐图人工验收或通达信原生等价认证。

同日集合交集与逐股差异另见最终对比报告；必须先通过同来源日期、权威 selector SHA 和 generation 身份核对。缺产物或来源冲突不得记为模型选出0只。

可追溯入口：

- 原式信号：[core.py](/Users/lexi/Desktop/学习/Z哥方法论/research_workflow_v2/integration/core.py:51)
- 原式原文：[公式原文](/Users/lexi/Desktop/学习/agents调试/Z哥方法论/bot216_prefilter_handoff_20261026/original/source_engine/panel_rebuild_20261023/formula/USER_MAIN_CHART_FORMULA_MESSAGE_EXACT_UTF8.txt:66)
- 原式附加过滤：[research_daily_product.py](</Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-storage-compaction-20261112-r1/main/app/domains/research_daily_product.py:663>)
- v1.9.2现役冻结角色：[原角色脚本](/Users/lexi/Desktop/学习/牛股学习/A股研究/_legacy_research_review/99_model_discovery_experiments/bull_agent_self_iteration_workbench_20260514/fmla04_return_driven_self_iteration_20260518/run_fmla04_return_driven_self_iteration_20260518.py:237)，SHA256 `950b14447cb61049fb44efa46a10dfa6b3d5374188e212f8aff06fee1ab326c1`。

`RESEARCH_ONLY=true`，`production_allowed=false`，`buy_gate_updated=false`，`orders_sent=false`。
