# 2026-10-16 美股收盘后观察名单

本结果是 2026-10-17 23:10 HKT 通过 Futu OpenAPI `get_market_snapshot` 取得的收盘后快照观察。Futu 文档说明美股 `update_time` 使用美东时间；`last_price`、`prev_close_price`、`pre_price` 和 `after_price` 分别保留。涨幅按 `(last_price / prev_close_price - 1) × 100` 计算，盘前和盘后价格不进入公式。该数据不是独立核验的官方日 K 收盘 bar，不代表预测、因果影响、买入建议或交易授权。参考：[Futu 官方快照字段说明](https://openapi.futunn.com/futu-api-doc/quote/get-market-snapshot.html)。

- 目标美股交易日：`2026-10-16`；对应下一港股交易日：`20261020`。HKEX 2026 日历列明 2026-10-19 休市，故目标不是周一；[HKEX 2026 日历](https://www.hkex.com.hk/-/media/HKEX-Market/Mutual-Market/Stock-Connect/Reference-Materials/Trading-Hour%2C-Trading-and-Settlement-Calendar/2026-Calendar_pdf_e.pdf)。
- Futu 对既有 448 个非 OTC 美股代码请求并返回 448 行；446 行的更新时间为 10/16 美东 16:00 或以后且价格字段有效，2 行缺少有效日期时间或价格，保留为 `CANNOT_CONFIRM`，不补值。采集时间 `2026-10-17T23:10:34.936+08:00` 至 `2026-10-17T23:10:35.544+08:00`。映射库证券范围包含基金等非普通股标的；关联用途和证券类别按现有关系保留。
- 映射：667 只港股、1,003 条关系；overlay SHA-256 `3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c`。闭环研究范围 757 条、OPEN 221 条、排除 25 条。
- 关系分桶守恒：positive 270、flat-negative 430、missing 57、open 221、excluded 25，合计 1003。OPEN/排除优先于行情方向并且不入观察候选。
- 正涨且至少有一条闭环研究关系的美股共 128 个；这些代码按快照涨幅排序，映射关系仅表示已有研究用途，不能解释为全部直接业务或股票联动。

## 美股正涨观察前 20

排序只反映 Futu 快照 `last_price` 相对 `prev_close_price` 的变化；完整 448 代码覆盖见 `us_stock_coverage.csv`。

|序|美股代码|名称|Futu快照涨幅|更新时间（美东）|正涨映射关系数|关联港股代码|
|---:|---|---|---:|---|---:|---|
|1|AAPG|亚盛医药|+4.629%|2026-10-16 20:02:28.996|1|06855|
|2|CRBP|Corbus Pharmaceuticals|+4.388%|2026-10-16 19:30:04.422|1|01093|
|3|KMI|金德尔摩根|+4.205%|2026-10-16 20:02:23.316|1|00934, 00956, 03369|
|4|TS|泰纳瑞斯钢铁|+3.738%|2026-10-16 19:30:05.320|2|00568, 01921|
|5|BNO|美国布伦特原油基金有限合伙企业|+3.592%|2026-10-16 20:02:23.623|3|00019, 00087, 00293, 00467, 00568, 00857|
|6|LANV|复朗集团|+3.231%|2026-10-16 16:00:00|1|00656|
|7|CVE|Cenovus能源|+3.034%|2026-10-16 19:57:28.030|1|00001, 00006, 01038|
|8|USO|美国原油ETF|+2.829%|2026-10-16 20:02:25.043|3|00135, 00753, 00883, 01055|
|9|NGG|英国国家电网公司|+2.719%|2026-10-16 19:30:04.070|2|00006, 01038|
|10|PM|菲利普莫里斯|+2.651%|2026-10-16 20:02:22.382|1|00363|
|11|AA|美国铝业公司|+2.548%|2026-10-16 19:58:53.643|4|01378, 02600, 02610, 02788|
|12|YETI|YETI Holdings|+2.499%|2026-10-16 19:30:04.907|1|01910|
|13|XOM|埃克森美孚|+2.462%|2026-10-16 19:57:25.311|1|00857, 00883|
|14|NEM|纽曼矿业|+2.427%|2026-10-16 20:02:16.570|3|00340, 01787, 03330, 03939|
|15|PEP|百事可乐|+2.422%|2026-10-16 20:02:18.451|2|00220, 00322, 00506|
|16|NTR|Nutrien|+2.414%|2026-10-16 19:30:05.075|1|00297|
|17|BKR|Baker Hughes|+2.390%|2026-10-16 19:47:51.917|1|03899|
|18|SLB|斯伦贝谢|+2.336%|2026-10-16 19:55:18.660|3|00631, 01033, 02883|
|19|AMT|美国电塔|+2.156%|2026-10-16 20:02:14.432|1|00788|
|20|LYB|利安德巴塞尔|+2.138%|2026-10-16 20:02:28.782|2|00338, 02768, 06067|

## 映射港股观察前 20

按每只港股最高一条正涨闭环关系的快照涨幅降序展示；所有正涨关系、用途、状态、证据 ID 和待补要点见完整 CSV。研究状态不因本次价格变化升级。

|序|港股代码 / 名称|涨幅最高的关联美股（快照涨幅，关系）|正涨闭环关系数|用途范围|研究状态|待补要点|
|---:|---|---|---:|---|---|---|
|1|06855 亚盛医药|AAPG (+4.629%, R929)|1|同发行人证券联动研究|CANNOT_CONFIRM_CURRENT_APPLICABILITY_STATE_ABSENT|比例只建立单位换算，不保证即时可转换、无摩擦套利或同日可交易；汇率、存托费用、税务、交易时段、流动性和新发行稀释另核。（另有 2 项）|
|2|01093 石药集团|CRBP (+4.388%, R442)|1|具名合同与业务关系跟踪|LIMITED_RESEARCH_DATED_SCOPE|未取得下一里程碑的完整触发细则和石药对CRBP单独收入/应收确认（另有 2 项）|
|3|00934 中石化冠德|KMI (+4.205%, R369)|1|产品与行业竞争参照|SUPPORTED_LIMITED_REPORT_PERIOD_SCOPE|两边液体资产同口径费率、固定/最低承诺与到期合同未核（另有 2 项）|
|4|00568 山东墨龙|TS (+3.738%, R244)|1|产品与行业竞争参照|SUPPORTED_LIMITED_REPORT_PERIOD_SCOPE|缺同规格/认证/地区客户的份额、订单与售价对照（另有 2 项）|
|5|01921 达力普控股|TS (+3.738%, R627)|1|产品与行业竞争参照|DATED_PRODUCT_PEER_ONLY|缺中标逐项合同、验收/交货及付款进度；未核具体CNPC采购签约法人。（另有 1 项）|
|6|00293 国泰航空|BNO (+3.592%, R144)；BA (+0.784%, R145)|2|具名合同与业务关系跟踪；商品成本与盈利敏感性研究|COST_BACKGROUND_ONLY_NET_SENSITIVITY_OPEN；ORDER_TRACKING_VALID_AS_OF_2026H1_NOT_DELIVERY_CONFIRMED|未来各季/逐份套保覆盖、名义量、执行价、期限、对手及实际现金结算仍未验证；报告期套保收益不能替代这些参数。（另有 3 项）；逐架最新排产、净价格/补偿/付款余额及H1后订单修订未完整核；有限订单追踪不声称今日合同全部条款已更新。（另有 2 项）|
|7|00467 联合能源集团|BNO (+3.592%, R210)|1|商品成本与盈利敏感性研究|LIMITED_PRICE_SCENARIO_BACKGROUND_LIVE_OPERATIONS_AND_HOLDINGS_OPEN|天然气逐合同国际油价复核公式、实际周期、上下限与有效期（另有 4 项）|
|8|00857 中国石油股份|BNO (+3.592%, R339)；XOM (+2.462%, R340)|2|产品与行业竞争参照；商品成本与盈利敏感性研究|APPLICABLE_LIMITED_COMMODITY_PROFIT_SENSITIVITY_FRAMEWORK；LIMITED_PEER_USE_SUCCESSOR_IDENTITY_REVISED|44页摘要非完整中报；油种Brent基差/结算滞后、库存/套保及分部税费净弹性未核全（另有 3 项）；未核指定session当前上市/停牌与行情覆盖（另有 2 项）|
|9|00656 复星国际|LANV (+3.231%, R270)|1|股权与共同资产敞口研究|LIMITED_JUNE_EQUITY_PATH_WITH_SEPTEMBER_PARENT_IDENTITY|10月最新LANV完全摊薄权益/净债务、母公司资金支持与所有期后公司行动未穷尽，排除实时净敞口及估值敏感性。（另有 2 项）|
|10|01038 长江基建集团|CVE (+3.034%, R409)；NGG (+2.719%, R410)|2|产品与行业竞争参照；股权与共同资产敞口研究|LIMITED_NETWORK_REGULATION_COMPARISON；SUPPORTED_DATED_COMMON_ASSET_SCOPE|HMLP最新有日期资本登记及各持股载体/电能间接穿透比例未取得（另有 3 项）；长建各网络精确最新股比、监管许可全文及项目分派限制未逐项穿透；不能由同行资料填补。（另有 1 项）|
|11|00753 中国国航|USO (+2.829%, R305)|1|商品成本与盈利敏感性研究|SUPPORTED_LIMITED_REPORT_PERIOD_SCOPE|缺10月USO实际持仓、展期日表、NAV/市价与owner receipt（另有 3 项）|
|12|00883 中国海洋石油|USO (+2.829%, R354)|1|商品成本与盈利敏感性研究|LIMITED_OIL_PRICE_MECHANISM_BACKGROUND; NO_RETURN_EQUIVALENCE|量化或交易研究仍缺中海油油种定价期、当前基差和PSA/税费边际桥（另有 2 项）|
|13|01055 中国南方航空股份|USO (+2.829%, R418)|1|商品成本与盈利敏感性研究|LIMITED_RESEARCH_BACKGROUND_ONLY_NOT_TRADE_READY|缺中国航煤现货/采购价与WTI的同日同币种基差（另有 4 项）|
|14|00006 电能实业|NGG (+2.719%, R015)；TLT (+0.100%, R016)|2|产品与行业竞争参照；利率汇率与风险偏好背景|LIMITED_CONTEXT_AFTER_ASSET_DISPOSAL；WEAK_MACRO_CONTEXT_ONLY|各项目允许回报与实际净回报和权重未逐项核（另有 2 项）；现金/负债/对冲及当地监管全穿透尚缺（另有 2 项）|
|15|00363 上海实业控股|PM (+2.651%, R187)；AWK (+1.428%, R186)|2|产品与行业竞争参照|LIMITED_TOBACCO_PRODUCT_AND_SUBSTITUTION_BACKGROUND；LIMITED_WATER_BUSINESS_COMPARISON_APPLICABLE_NOT_DIRECT_LINK|南洋地区/品牌收入利润份额及PM实际重叠客户未披露，不能量化替代或方向。（另有 2 项）；逐中国水务合同/最新净权益、收费及真实回款/投入未穿透，阻止项目估值和量化传导升级。（另有 2 项）|
|16|01378 中国宏桥|AA (+2.548%, R543)|1|商品成本与盈利敏感性研究|LIMITED_RESEARCH_SCOPE_ONLY|两端现行能源/氧化铝采购与销售合同指数、库存滞后及地区溢价未同口径核。（另有 1 项）|
|17|02600 中国铝业|AA (+2.548%, R740)|1|商品成本与盈利敏感性研究|LIMITED_ALUMINA_ALUMINUM_PRODUCER_COST_SCOPE_NET_EXPOSURE_PENDING|缺中铝同期间外售/自用氧化铝吨数与内部抵销量价桥（另有 3 项）|
|18|02610 南山铝业国际|AA (+2.548%, R746)|1|商品成本与盈利敏感性研究|DATED_LIMITED_SCOPE_ONLY|未来投产实际日期/产量、外销与内部转移、能源和铝土矿净敞口仍缺。（另有 2 项）|
|19|02788 创新实业|AA (+2.548%, R795)|1|商品成本与盈利敏感性研究|DATED_LIMITED_SCOPE_ONLY|创新外销与内供氧化铝比例、煤/电长协及实际绿电比例未建完整敏感性表。（另有 2 项）|
|20|01910 新秀丽|YETI (+2.499%, R623)|1|产品与行业竞争参照|LIMITED_PRODUCT_REGION_COMPARISON_POST_ACQUISITION_BOUNDARY|未取得包袋独立利润及双方同口径采购/促销矩阵（另有 3 项）|

## 来源与可复现性

- 快照 capture SHA-256：`8e1548621c5c37e74a084c64e42ff4029b97f7dd852782dea74f493ca693301e`；capture payload SHA-256：`5fc36d2408e94f49d3f5732cdd513fe90760f5435d0e7886e8b07a01a5e0262d`；canary 文件 SHA-256：`f997df280b3719e25aad09721c92962e09fe586ad9bf0bc4deb3450ae30092f0`。
- 映射快照文件 SHA-256：`f819ca2f036953d0989a2a28127072d41ac7e051f209087a38953299251a0df3`；canonical snapshot SHA-256：`3228f28fdc34cfe36202fa7e5bce1720fe34115a334b77bc6a4468a6013eb1cc`；目录完整性 SHA-256：`fd362d817032f4f0a8f6f033c44df64435232382ea514dc31beee7b285deb0c5`。
- 精确日 K close：`CANNOT_CONFIRM`（本次只请求快照接口，未请求历史 K 线）。历史 PIT：`NOT_VALIDATED`；预测：`UNTESTED`；事件/数据检验：`NOT_RUN`。
- 闭环范围、可证关系用途和当前状态沿用映射文件；positive 表示观察筛选结果，非证据独立验收、预测或交易信号。
- 金融安全：`RESEARCH_ONLY=true`; `production_allowed=false`; `buy_gate_updated=false`; `orders_sent=false`。

复算：`'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_friday_close_20261017/scripts/build_friday_us_observations.py --verify`
