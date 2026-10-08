# 本轮仍未证明的项目与精确后续输入

基线：[Issue #28 冻结说明](https://github.com/lexi2016/v4/blob/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/stage-selection-issues-20261008/README.md)。
当前现场状态只对应 2026-10-08 09:50:54 +08:00 采样。没有用此后的时钟推断
未采样阶段已经失败，也没有在本轮重新读取 Mac 的业务数据。

## 港股真实生产与调用仍是 P1 验收缺口

已证明旧实际 materializer 入口不能表达行情／资格的两个日期，且投影时丢弃
严格消费者所需的来源字段。本包为这两个实际文件提供兼容后像。以下闭包没有
随 27 文件切片提供，不能以 canonical 或较早的 API／Stage 文件替代：

- `hk-research-calendar-all-r1-20261007-scheduler/app` 实际
  `infrastructure/scheduling/executor_registry.py` 及它对物化入口的参数接线。
- 同一生产链真正加载的 `shared_data/hk_0_2.py`，包含包根、文件 SHA、入口签名。
  canonical 中具备双日期支持，不证明实际加载的是同一后像。
- 同一 producer 实际 `infrastructure/preselection_pool_store.py` 及所属
  readers/sources/transactions 支持文件的 SHA，确认可接受合法 provenance 字段。
- 活动服务的有限 owner／参数清单与不可变 manifest 引用；无须上传完整 plist、
  环境变量、凭证、行情行或业务回执。

Luna Max 需先核实际加载身份，再使原 scheduler 传入目标日 20261008、HK 行情日
20261007、资格日 20260930；A 日期保持自身合同。未补齐前状态为
`CANNOT_CONFIRM_ACTIVE_DEPENDENCY_CLOSURE`，不得直接激活两个后像。

10/7 原始行情是否确实存在仍是 CANNOT_CONFIRM。本包不宣称不存在，也未采集。
须沿原共享 owner 查实际 run/artifact/manifest/receipt、SHA 与取得时钟。
若只能事后补采，继续使用原 TDX/tdxpy 链并标明真实取得时间及研究身份。

## P2 与历史数据

| 项目 | 已知事实 | 本轮处理及尚需证据 |
| --- | --- | --- |
| A 行情覆盖 | 09:25 来源 171/178；之后前三盘中阶段 172/178 | 保留 PARTIAL_WITH_ROWS。缺失代码及逐请求诊断未上传；需逐只核规范化代码、请求市场、精确日期/窗口、返回/异常和原因。没有改市场映射或声称全覆盖。 |
| 研究与新闻评分 | 小时源 9 条 stock-pool / 9 条 article；witness 的 morning-news article_count=0 | 活动 loader 明确不把 research_score 当 quality_score；类别 item_quality 也不等于数值 quality。候选与来源交集、numeric quality 语义、V4 权威归属、不可变来源绑定均未闭合；没有 alias 或缺值填零。 |
| 逐 run 执行身份 | 前四阶段 execution_verified=false；部分声明 NATURAL、部分 RECOVERY | 没有改旧 receipt。需要同一 run 的输入、代码、配置、不可变 manifest、执行回执与独立读取记录；selection 已存在不能证明自然运行。 |
| 自然时段 | 四阶段 natural_verified=false，recorded_at=null | 历史缺证据保留 NATURAL_SLOT_UNVERIFIED。未来自然时段由原 owner 留存真实原件；本轮未调度或模拟自然证据。 |
| 历史收盘源码 | 已有独立 51 项 focused PASS；扩展 70 PASS / 3 基线同样 FAIL，未部署 | 保留原已验后像及 FAIL，不重写已通过文件、不把源码测试当日期数据恢复。 |
| 8/25 | 缺 manifest/receipt/provenance | CANNOT_CONFIRM；不能默认标记来源或 PIT 已核。 |
| 9/30 | 原捕获晚于目标收盘 | 保留事后来源边界，不补造当时捕获时间。 |
| 10/7 | 当时限定根下未发现上游原始来源 | 限定检索范围内的缺口；不是全部源不存在的证明。 |
| 三项历史 P2 | provenance 日期上界、嵌套字段白名单、8/25 source/PIT 不确定标记 | 本轮未修改这些已验源码；需原 owner 的明确嵌套合同和实际前像后定向处理，不能以默认值解除。 |

## 保留已有任务边界

#10 的 9/30 观察例外不适用于 10/8；#11 旧重试故障不等于今天竞价问题；
#21 已恢复的深链接不重做，其他旧 UI 验收没有复跑；#23 旧 pin 不重新使用或
自动刷新。经理台已有 R3、本包只给源码候选；Vibe8910、模型、BUY 与无关调度均不改。
