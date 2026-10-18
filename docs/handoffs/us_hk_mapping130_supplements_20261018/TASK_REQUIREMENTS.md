# 逐股复用既有美港映射资料，补齐可计算的研究路径

请读取我上传的两个 CSV：`待补映射_泛行业130只.csv` 和 `现有资料库_对应关系.csv`。这 130 只股票全部已经有资料库关系，共 183 条；不要从零重做，也不要把“泛行业无法直接对应代理”说成“该公司没有映射”。

我的用途：根据美国 2026-10-16 周五收盘走势，在港股经理工作台展示潜在受益股票、下跌风险股票和逐股理由。现在补的是截至研究时点可用的公司主营、关联资产与方向解释；不是要求证明历史预测有效，也不是下单或给买卖指令。港股范围沿附件现有月度观察名单，不重新审计全部港股通资格。它是 2026-10-12 的观察范围，不声称已验证未来某天正式资格。

请执行：

1. 先复用每股已有的 relation_id、事实、来源 URL、已核事实和限制。只有确实缺失、过时或相互冲突的事实才联网补证。优先公司年报/中报、港交所公告、公司投资者关系网站；输出可打开的原文链接、报告期或发布日期、关键页码/段落或简短原文。
2. 对每只股票，明确实际主营细分，而非仅重复“软件服务 / 工业工程 / 媒体及娱乐”。找出适合的美国股票或 ETF、关系类别及经济传导机制。例如：同类业务情绪、客户需求、投入成本、持股资产、同一发行人 ADR 等；不同关系不能混用。
3. 优先使用目前已接入行情的 48 个标的：AMD, ARKX, AVGO, BOTZ, CIEN, CLOU, COHR, COPX, DLR, DRIV, EQIX, FCG, GLD, GRID, ICLN, ITA, KBE, LIT, LITE, MU, NLR, NVDA, REMX, SOXX, STX, TAN, UFO, VRT, WDC, XBI, XLE, XLP, XLY, META, GOOG, GOOGL, AMZN, BABA, JD, PDD, DASH, UBER, BKNG, EXPE, TCOM, BIDU, BILI, NTES。确有更合适的外部标的也可提出，但标注 QUOTE_NOT_CONNECTED，不能假装已接入行情。不要为了套入名单，把所有软件公司映射到云计算、所有工业公司映射到机器人或所有媒体公司映射到消费。
4. 每条路径分别说明：代理上涨时该港股是 POTENTIAL_BENEFIT / POTENTIAL_RISK / MIXED / UNCLEAR；代理下跌时同样单独判断，不能机械假定完全反向。注明适用条件、失效条件、信息影响时间尺度。同行股上涨只能支持行业情绪研究假设，不能伪装成客户订单、收入或利润已改善。
5. 同股可保留多条有效路径，不强行合成一个分数。如果不同路径相互矛盾，明确列出；主营事实可信度与股价联动假设可信度分开。没有回测或历史 PIT 验证不等于主营关系不存在，分别标为 prediction_validation=UNTESTED、historical_pit_verified=false，不用它们把所有已有事实一律作废。
6. 一只股票卡住就标记具体缺口并继续下一只，不阻断整批。不要把已有 183 条关系仅因格式、泛行业名称或缺少短线回测而全量标为不可用。也不要为了凑结果造映射、持股比例、订单关系、来源、行情或置信度。
7. 本轮不补 06823、09618、09961；09988 不在本批 130 只重点名单内，无需扩展阿里专题。不要更改任何交易、BUY、生产或股票池规则。RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false。

请按每批 20–30 只交付已完成结果，保留前批成果，失败只补失败记录。交付三份：

- `mapping_supplements.csv`：每行一个“港股—美国代理”路径。
- `mapping_supplements.json`：同内容的结构化版本。
- `unresolved.csv`：确实无法判断的股票、已检查来源、缺少的具体事实和最小下一步。

每条路径字段固定为：

```text
hk_code（五位字符串，保留前导0）
hk_name
existing_relation_id
record_action（REUSE / SUPPLEMENT / REJECT_WITH_REASON）
business_segment
us_symbol
quote_connection（CONNECTED / QUOTE_NOT_CONNECTED）
relation_type
mechanism
proxy_up_effect（POTENTIAL_BENEFIT / POTENTIAL_RISK / MIXED / UNCLEAR）
proxy_down_effect（同上）
conditions
failure_conditions
timescale
fact_confidence（HIGH / MEDIUM / LOW，写明理由）
linkage_confidence（同上；这是研究假设，非预测胜率）
source_urls
source_titles
reporting_period_or_publication_date
source_locator
evidence_excerpt_or_paraphrase
checked_at
remaining_gap
research_status（READY_FOR_RESEARCH / PENDING_FACT / NO_CLEAR_PROXY）
prediction_validation（UNTESTED）
historical_pit_verified（false）
```

最后给出按唯一股票数计的：复用现有关系数、补充后可研究数、仍待核数，以及逐只未完成原因。保留 relation_id 方便回接现有资料库。请直接开始首批，不先写一篇泛泛的方法论。
