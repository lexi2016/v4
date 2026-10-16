# 2026-10-16 美股 Futu 当前快照观察

本表使用 Futu OpenAPI `get_market_snapshot` 当前快照字段。观察排序指标为 `(last_price / prev_close_price - 1) * 100`，即快照 `last_price` 相对 API `prev_close_price` 的变化；保留每行 `update_time`，并将 `pre_price` 单独列出。该指标不等同于精确的 2026-10-15 美股收盘涨幅，也不证明该观察在 2026-10-16 港股开盘前可得。

没有评分、预测、买入建议或交易授权。港美股关系仅为当前目录研究关系，观察涨幅不表示因果或港股方向。

## 覆盖

- 当前 catalog 共 518 个美股/相关符号，其中 493 个经 catalog 交易所证据分类为 active US-listed security。
- 对排除已证实不提供行情的 OTC-only 市场代码后，Futu 请求 448 个代码，返回 448 行；其中 446 行通过时间戳和价格字段校验。另有 45 个 OTC-only 代码保留为 provider unsupported 缺口，2 行因 update_time 缺失或无法解析而不进入正/负涨分类。
- 映射关系完整覆盖 1003 条，按 OPEN/排除优先级分桶：positive 515、flat-negative 185、missing 57、open 221、excluded 25。
- 正涨关联关系去重后为 427 只港股；完整候选见 `candidate_stocks.csv`，完整关系覆盖见 `futu_relation_coverage.csv`。
- Exact daily-K subset 仅含 3 个 2026-10-15 canary symbols，保存在 `exact_daily_kline_subset.csv`；它们没有混入当前 snapshot 排序。

## 描述性正涨关联观察（前 15）

|序|港股代码 / 名称|正涨关联美股（快照变化，更新时间）|用途范围|研究状态|待补要点|
|---:|---|---|---|---|---|
|1|02595 劲方医药－Ｂ|VSTM Verastem, Inc. (19.715%, R739, 2026-10-16 06:24:13.487)|具名合同与业务关系跟踪|CURRENT_NAMED_LICENSE_PUBLIC_TERRITORY_AND_CONDITIONAL_ECONOMICS_SUPPORTED|Q2 SEC接受时刻未证，仅正文8/6签署；临床数据未独立审计，III期计划及审批未实现；具体未公开里程碑条件、成就通知和后续付款未取；劲方未逐笔拆本协议许可收入、应收及现金；指定session/cutoff、owner市场数据receipt和PIT可得性未提供。|
|2|00763 中兴通讯|ERIC Telefonaktiebolaget LM Ericsson ADS (11.795%, R309, 2026-10-16 06:25:46.071)|产品与行业竞争参照|APPLICABLE_SEGMENT_CONTEXT_WITH_NEW_Q3_DATE_BOUNDARY|ERIC Q3首发时分未独立验证；目标session/owner/PIT及回测未运行。；有限设备行业用途已闭合；同客户重叠、项目份额及定量经营传导未证。|
|3|02586 多点数智|VYX NCR Voyix Corporation (9.884%, R734, 2026-10-15 23:52:00.743)|产品与行业竞争参照|LIMITED_RETAIL_SOFTWARE_DEPLOYMENT_REFERENCE|VYX10-Q精确公开时刻未核；本边不包含Cloopen收购完成核验或其证券现状。；无同地区零售商IT预算/续约/部署到现金的匹配面板；Dmall关联与独立客户续约细项不足。|
|4|00590 六福集团|SIG Signet Jewelers Limited (9.448%, R254, 2026-10-16 04:31:53.299)；GLD SPDR Gold Shares (1.787%, R255, 2026-10-16 06:26:20.255)|产品与行业竞争参照；商品成本与盈利敏感性研究|LIMITED_DOCUMENTED_MECHANISM_CURRENT_NET_EXPOSURE_OPEN；LIMITED_PRODUCT_CHANNEL_REPORT_PERIOD_COMPARISON|3月末之后的滚动库存黄金克重、借贷/期货名义量/方向/到期/展期和净覆盖率未取得；GLD动态表无首发日，指定session行情/NAV/每份金量及V4覆盖未知；两方同地区同品类渠道量价/库存周转和零售净利润未标准化；六福3月末后经营及头寸是否延续未由当前财报重新计量；地区利润桥未逐项核；六福年报精确分发日与指定session证券状态尚缺；指定session/cutoff及V4读取回执未提供。；期末金融敏感度不含产品量价和库存全链，集团当前净敏感度仍不能量化|
|5|06168 周六福|SIG Signet Jewelers Limited (9.448%, R897, 2026-10-16 04:31:53.299)|产品与行业竞争参照|CANNOT_CONFIRM_CURRENT_APPLICABILITY_STATE_ABSENT|具体黄金与钻石占比、直营加盟、同店口径与客户区域未对齐。；证券交易状态、数据时间戳、事件测试、历史PIT与预测效力未验证。|
|6|06181 老铺黄金|SIG Signet Jewelers Limited (9.448%, R899, 2026-10-16 04:31:53.299)|产品与行业竞争参照|CANNOT_CONFIRM_CURRENT_APPLICABILITY_STATE_ABSENT|商品定价机制、地区、库存成本、退税最终到账和同店增长不可直接对齐。；证券交易状态、数据时间戳、事件测试、历史PIT与预测效力未验证。|
|7|02858 易鑫集团|UPST Upstart Holdings, Inc. (8.839%, R797, 2026-10-16 06:15:03.297)|产品与行业竞争参照|DATED_LIMITED_SCOPE_ONLY|UPST个人贷占比、资金承诺与实际信用风险并非易鑫汽车借款池；AI不等风险模型相同。；尚未建立目标交易时点的证券交易状态、PIT数据及逐事件/数据检验；不能用于生产或交易。；易鑫自营融资、融资租赁与平台撮合的风险承担/表内表外口径须分开。|
|8|02338 潍柴动力|PSIX Power Solutions International Inc. (8.615%, R693, 2026-10-15 20:02:32.113)|股权与共同资产敞口研究|DATED_EQUITY_SCOPE_CURRENT_EXTENSION_OPEN|6/30后PSIX精确持股分子/分母、控制协议是否变化未取得。；PSI到潍柴归母贡献的合并调节、少数股东及FX桥未逐项取得。|
|9|09678 云知声|SOUN SoundHound AI, Inc. (7.947%, R960, 2026-10-16 06:27:07.998)|产品与行业竞争参照|CANNOT_CONFIRM_CURRENT_APPLICABILITY_STATE_ABSENT|Specified market-session observability and quantitative data tests not performed；取得SOUN并购后首期合并及备考收入、云知声同期间确认收入和客户续约/项目验收数据，再限定同产品市场。；未建立同客户合同、直接销售或证券联动；U2的模型能力/榜单为公司披露非独立验收。SOUN并购后收入需与有机增长分开，不能把LPSN历史数据回填H1；历史并购完成不构成新催化。|
|10|00917 趣致集团|TTD The Trade Desk (7.800%, R366, 2026-10-16 06:24:59.017)；OUT OUTFRONT Media (0.944%, R365, 2026-10-15 19:54:59.364)|产品与行业竞争参照|SUPPORTED_LIMITED_REPORT_PERIOD_SCOPE|TTD gross spend到净收入费率桥与趣致验收/利润桥尚缺可比量化；未指定session/cutoff或owner权威行情receipt；不能宣称当日交易可用。；相同广告主跨渠道总预算及趣致实际支出/合同未取得；趣致/OUT同市场广告主预算、量价和上刊率对照缺失；趣致9月月报未取得；趣致具名合同、验收/收款与OUT最低保证费的可比利润桥未得|
|11|02723 深演智能|TTD The Trade Desk, Inc. (7.800%, R789, 2026-10-16 06:24:59.017)；PG The Procter & Gamble Company (0.351%, R788, 2026-10-16 06:23:03.030)|产品与行业竞争参照；具名合同与业务关系跟踪|DATED_LIMITED_SCOPE_ONLY|双方take-rate、媒体采购总额/净额、客户集中度与地区没有同口径匹配。；宝洁具体签约实体、金额、产品、交付验收及收入份额未披露。；宝洁客户披露不能推出TTD与深演之间存在交易。；尚未建立目标交易时点的证券交易状态、PIT数据及逐事件/数据检验；不能用于生产或交易。；缺采购方对应确认，不能认为PG母公司直接付款或全球集团采购。|
|12|06683 巨星传奇|FNKO Funko (7.480%, R915, 2026-10-16 04:32:02.985)|产品与行业竞争参照|CANNOT_CONFIRM_CURRENT_APPLICABILITY_STATE_ABSENT|IP权利期限/分成、渠道地区、实际商品销量及最低保底承诺未对齐。；证券交易状态、数据时间戳、事件测试、历史PIT与预测效力未验证。|
|13|09992 泡泡玛特|FNKO Funko, Inc. (7.480%, R997, 2026-10-16 04:32:02.985)|产品与行业竞争参照|CANNOT_CONFIRM_CURRENT_APPLICABILITY_STATE_ABSENT|2026最新地区和品类可比销量、售罄、库存及授权合同更新未验证。；事件与数据检验NOT_RUN；历史PIT NOT_VALIDATED；价格预测UNTESTED。；目标交易会话/截止时点未指定，行情覆盖、消费回执及实时可交易性未核。|
|14|01310 香港宽频|LUMN Lumen Technologies Inc. (7.033%, R516, 2026-10-16 06:24:12.230)|产品与行业竞争参照|DATED_BUSINESS_SCOPE_SUPPORTED; DIFFERENT_GEOGRAPHIES_PERIODS_AND_TRANSACTION_EFFECTS_SEPARATED|缺HKBN企业客户续约/ARPU、服务与产品毛利、capex和回款细分，不能推Lumen订单向香港传导。；缺双方债务/资本回收可比桥及目标session/PIT量价；未证业务合同。；缺相同期间/同网络层级对照；HKBN16个月期及第二次中期结果未取得，LumenAlkira后续并表贡献未核。|
|15|01883 中信国际电讯|LUMN Lumen Technologies, Inc. (7.033%, R617, 2026-10-16 06:24:12.230)|产品与行业竞争参照|DATED_BACKGROUND_APPLICABLE; DIRECT_ECONOMIC_LINK_AND_QUANTIFICATION_NOT_ESTABLISHED|LUMN全部PCF累计签约及中信安全/云网络分项收入未核；59亿美元不替代。；中信9月月报及10月证券变化、目标session/cutoff与PIT未核。；没有可比地区、共同客户/产品订单、定价和留存桥，直接商业关系未建立。|

## 关系覆盖分桶

|分桶|关系数|口径|
|---|---:|---|
|positive|515|CLOSED_RESEARCH_SCOPE 且有效快照指标 > 0|
|flat-negative|185|CLOSED_RESEARCH_SCOPE 且有效快照指标 ≤ 0|
|missing|57|CLOSED_RESEARCH_SCOPE 且未获得有效快照观察|
|open|221|OPEN；不进候选|
|excluded|25|CLOSED_EXCLUDED_SCOPE；不进候选|
|合计|1003|与冻结 R0 的 1,003 条关系守恒|

## 缺口与解释边界

- snapshot 更新时点、`last_price`、`prev_close_price` 和 `pre_price` 按 Futu 原始字段保留在 `snapshot_capture.json`、`futu_symbol_coverage.csv` 与关系覆盖表；排名不使用 `pre_price`。
- 各失败批次按确定顺序拆分，达到单代码、深度或每个初始批次的尝试上限后保留原始错误和终态，不将失败解释为无行情。
- 初次混合批次的 Futu 错误原文示例：`"暂不提供美股 OTC 市场行情 AAGIY"`；初次请求和拆分过程保存在 `snapshot_capture_initial_otc_batch_attempt.json`。
- OPEN 与排除关系即使有行情，也不会进入候选；候选只是研究观察排序，不证明关联有效、事实独立验收、港股方向、预测能力或经济因果。
- 2026-10-15 exact daily-K canary 仅 3 只，用于绑定当日 K 线字段，不作为这次广覆盖 snapshot 的回报替代或排名来源。

## 输入与复现

- catalog projection SHA-256：`fd362d817032f4f0a8f6f033c44df64435232382ea514dc31beee7b285deb0c5`；映射 snapshot SHA-256：`3228f28fdc34cfe36202fa7e5bce1720fe34115a334b77bc6a4468a6013eb1cc`。
- Futu snapshot capture SHA-256：`873e136a1b68ea85d2e3d5ab3f3d1bbb17e85cd091551e7807ee39aa8636674a`；捕获时间（UTC）：`2026-10-16T10:27:32Z`。
- 复现：`'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' docs/handoffs/us_hk_mapping_today_20261016/futu_r1/capture_futu_snapshot.py --verify`。
- 原始 2026-10-15 exact K-line canary 已记录于 `canary.json`，历史查询额度不再扩展。
