# 预选池与阶段对接模拟验收 · 20261015

结论：当前预选池已恢复，更新分支与池读取对接通过；隔离阶段通路通过。**不能据此断言全部自动运行没有问题。**

|检查面|结果|
|---|---|
|20261016 HK预选池|STRICT_0_2_READY，100只，信号日20261015；真实API及刷新UI一致|
|A完整汇总|169只，complete=true；部分子池未确认，PARTIAL_WITH_ROWS允许有效汇总继续|
|现役版本|API hk-tdx-conflict-repair-api-r5、main hk-tdx-conflict-repair-main-r2、Stage hk-auto-execution-audit-r3；完整身份/SHA见evidence|
|更新程序模拟|独立复跑10项通过：已有池复用、仅HK缺失重试、不重跑A、坏SHA/日期/部分回执/并发输入拒绝|
|API隔离/分页|独立复跑10项通过；可选坏池隔离后仍A169/HK100|
|Stage正反模拟|实际_run_one、真实池绑定；不安全时间数据在发布前拒绝；合成09:35时钟下raw A169/HK100、观察各10、临时receipt读回通过|

A正向模拟缺少刻意留空的正式研究上下文，因此实际A builder报ResearchContextError，脚本通过CANNOT_CONFIRM回退选择器验证产物通路；**这10条不能证明A正式策略选股有效**。HK实际four-lane selector使用合成行情，仅证明程序通路。模拟未经过scheduler tick/派发/锁编排，真实分钟/PIT和自然时段仍未验证。今晚Stage为按日历触发的idle状态，不能误判为崩溃。

另有非阻断诊断歧义：负向receipt的first_failed_layer为A绑定层，而终端error描述HK时点校验；失败关闭行为正确，本轮只记录不扩修。

本轮没有修改业务源码、服务、日程或正式产物。正反模拟输出全部在临时目录，RESEARCH_ONLY=true，production_allowed=false、buy_gate_updated=false、orders_sent=false。UI为主控实际刷新观察；独立Reviewer覆盖20项回归及Stage模拟，不冒充独立UI或自然验收。

复跑命令：`PYTHONDONTWRITEBYTECODE=1 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/HK_POOL_STAGE_SIMULATION_20261015/simulate_hk_pool_stage.py`。脚本依赖本机指定已冻结runtime和实际同日输入，不是跨环境自包含包。详细输入SHA、mock边界与独立回执见result.json及evidence。
