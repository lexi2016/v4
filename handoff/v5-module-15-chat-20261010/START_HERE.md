# 原15号模块 美股到港股映射交接

日期：2026-10-10。用户按原18个模块分别开18个Chat，本包只交原M15“美股到港股映射”。Chat负责M15方案与具体代码；嘻嘻负责材料、Mac隔离落地、必要独验和跨模块问题转交。原01—18/P0—P5保持不变。

本包是编码任务与来源材料，不是已实现、已测试或已部署的产品。请先读[编码任务](PROMPT_FOR_CHAT.md)，再查[固定来源清单](SOURCE_INDEX.md)；候选返回后按[Mac验收与回传](MAC_ACCEPTANCE.md)独立检查。

## M15交付什么

复用原映射算法及持久化合同，在同一精确US session、HK目标日和cutoff下，交出两条路径各自的映射结果、有效空或准确拒绝，保存到M15自有输出并独立读回，提供M18可消费的稳定身份引用。

1. 已审种子daily：原LITE/COHR/AVGO/CIEN四键对应三张可匹配港股卡；另两张宽主题卡没有daily键。保留原关系类型和有限覆盖范围。
2. 原生发行人材料：行业/主题映射与显式US个股关系分别计算。保留港股native identity、主体、正文span、来源SHA、发布时间和真实取得时点。

四键daily不是完整M15。peer不能变成供应关系；taxonomy不是股票关系库；报价上涨不等于港股受益证明。缺材料、取得时点或资格未知，保持缺口，不能造来源/历史时间、扩种子凑数或把缺源画成有效空。

## 与其他Chat的边界

- M03提供精确US来源、原payload/manifest/receipt与session/phase/cutoff证据。采集器、网络、调度和原source store归M03，本Chat不修改。
- M02提供港股原生身份、主表及目标资格。参考日和资格日分开，本Chat不修行情/主表/资格生产。
- M04提供原生研究材料、正文/span和真实取得回执。本Chat不做资料抓取、归档生产或回填时间。
- M18消费M15固定输出，负责经理保存、同run产品/terminal、普通API及页面接入。本Chat不修改共享经理、gateway、前端或部署绑定。

跨模块缺陷交明确请求单，注明owner、固定来源、最小复现、输入输出合同和需要对方提供的结果。独立M15候选不等待其他模块整体完成；但真实输入缺失不能签完整业务通过。13号公告Chat独立推进，不与本包互相覆盖共享文件。

## 当前已知与固定基线

代码观察基线：[f7cb731c384ee6890a87d16c19a5b5a621779477](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)。[原总计划](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)与[迁移执行计划M15](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)保留，两条路径都在范围内。

- 四键保存、读回和页面有历史报告，行业材料/显式个股材料路径仍须按真实输入独验。历史记录不自动覆盖今天的代码和运行状态。
- 旧US owner的persist_daily_run只接now；R3 owner另有timeout_seconds、execution_context、dispatch恢复与_read_exact_run。按M15实际调用需要核完整闭包，不删参数或吞TypeError冒充兼容。
- 原store仅允许恰缺两个可推导字段的精确旧receipt，但M15 bridge的全字典比较又拒绝。消费者可复用原_receipt_matches，原source store及旧receipt字节不改。
- 当前M15 daily manifest为39文件，manager manifest为80文件，M03采集manifest为48文件。它们是不同职责集合，只作为固定清单核对，不相加当覆盖率；完整namespace、常量、JSON及日历依赖不可省略。
- f7cb731c已含与4acb6ae树同blob的采集可信加载边界，不重复修M03。既有18/18是合成工程证据，不是真实采集或自然接续证明。

保留V4现役、BUY门和8910，不交易、不扩大安全权限或凭据访问。本包不操作Mac、不推候选、不部署；不把云端旧PARTIAL/0数据当真实Mac产物。
