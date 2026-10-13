# 明早调度与完整阶段输入预检 · 20261014

目标：既有预选池自动生成、早盘刷新及完整 A/HK 输入；用户要求主助手直接处理，不派子智能体。本次自测通过，独立 Reviewer NOT_RUN；自然时段 NOT_RUN。

## 已验证与最小修复

- 实际 stage-center 源码 `build_artifact` 读取完整物理子池，未走页面分页。现有 A 股主池82、复盘观察56、Stage7分时10、研究推荐191，去重292只；逐只对比292基线无遗漏。HK精确前一交易日20261013 Top100，共100只，与A股分离。
- `infrastructure/scheduling/_executor_registry_parts/preselection.py:242`：主池已经生成时仍解析收盘面板，供两个复盘池生成；不重复运行主池评分。现役调度旧结构已经具备此行为，此项修复canonical回归风险。
- `infrastructure/scheduling/_executor_registry_parts/research_jobs.py:6`：成功的LIVE 08:30/09:00研究任务调用已有研究池刷新函数；盘中和历史路由不刷新。失败明确返回UPSTREAM_NOT_READY，不冒充更新成功。
- `infrastructure/_stage_acquisition_universe_contracts_parts/snapshot_provenance.py:68`：拒绝来源状态诊断统一大写。原先小写available与下游合同不一致，导致被隔离的坏池仍阻止有效兄弟池发布；修复后坏池仍不可用、非有效空池，原始SHA保留。
- 现役调度HK证券字典来源从共享工作区外层对齐既有`.runtime/data`，仅在精确父子关系且权威目录存在时应用。canonical已有此路径归一逻辑；只投影到现役旧结构，不改全局环境变量，不新建producer。

## 自动时序

- A日面板17:00、HK日面板17:20 → 次日预选池17:30/18:00。
- 08:30研究更新、09:00小时研究更新 → 既有研究池刷新 → 09:15候选准备 → 09:25及各阶段自然选股。
- 已检查stage-center登记的09:34/39/44、10:29、13:14、14:59等预采集和对应阶段触发；20261014的A/HK/港股通本地日历均为完整交易日。
- 隔离先前完成回执的调度探针正确选中08:30、09:00、17:00、17:20、17:30、18:00。空ledger初次探针优先补15:00旧任务属既有追赶行为，不是本次修复。

## 验收边界

- Python环境：`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`。
- `python -m pytest -q tests/test_morning_preflight_20261014.py tests/test_a_next_pool_recovery_20261014.py tests/test_preselection_pool_partial_read.py tests/test_strict_stage_acquisition_v4.py`：30 passed。初次测试暴露上述大小写问题，修复后旧测试错误的available/valid_empty断言同步更正；保留三次日志。
- 发布候选实际模块检查坏池隔离、超过200行、partial有效行。使用真实物理池隔离发布候选，再经read_candidate/build_plan，09:25、09:30–09:35、09:45–10:30、14:45–15:00均读取A292/HK100；A股大池使用现有TDX完整输入路径。此为离线真实输入验证，不代表行情已采集或自然选股完成。
- 新池生成路径以外部producer替身验证7个既有模块被调用及来源参数，不声称已执行未来行情生产。
- 8873 API与真实浏览器读回：A主82、分时10、复盘56、研究191、HK100；A汇总第一页200、第二页92。临时浏览器返回第一页时一次selector超时，后续DOM已出现研究191行；该工具异常单独保留，用户页面未改。已关闭临时页。
- 缺失公众号旧池、白毛映射仍保留缺口，不阻止有效A股输入。两个复盘池继续DATA_PARTIAL，未补造缺失视频、L2或4只原始分钟资料。
- 明天外部数据是否准时到达、每阶段自然执行及结果页面仍需实际验收，不能保证未来运行。已沿用本聊天明早及下午监控。

## 运行身份及证据

- 唯一源码：`/Users/lexi/Desktop/学习/v4_app`；本地基线commit `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054`。
- Scheduler：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/morning-pools-20261014-r1/app`，manifest SHA256 `300c2456d3fbeaef0e8dc024f5d2e461fcdba2991be8670024be5bb63a204169`；基于最新manager-workbench v14调度候选，保留并行修改。
- Stage-center：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/morning-stage-20261014-r1/app`，manifest SHA256 `0ddaeb2b8a61cb6e9611ac6b29185c583b25d6ef4534737ca1ce7f1499e3539e`；基于hk-natural-capture-20261014。
- API本次未变：`/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/a-pool-labels-20261014-r1/app`。8910未动。
- 调度plist及manifest读回通过；scheduler进程running，stage-center按日历等待。scheduler首次bootstrap返回5，退出释放后一次重试成功，原结果保留。
- 本机证据：`/Users/lexi/Desktop/学习/agents调试/V4_MORNING_PREFLIGHT_20261014`，含scope、before、this-turn.diff、source-shas、candidate-stage-consumption、generation-routing、schedule-probe、deployment-verified、ui-verification及测试日志。原始数据、运行配置和完整响应不上传。
- 私有GitHub以`codex/a-review-pool-gaps-20261014`的`6d8c5cb11e7d9aa11ae8c3ca4321763a37f3b9aa`为父提交，另建`codex/morning-preflight-20261014`仅同步本轮源码、必要测试和本说明。该工作分支不是完整运行包；未同步全仓其他未提交文件。同步结果及远端读回SHA保存在本机github-sync.json。

研究约束保持：RESEARCH_ONLY=true、production_allowed=false、buy_gate_updated=false、orders_sent=false。
