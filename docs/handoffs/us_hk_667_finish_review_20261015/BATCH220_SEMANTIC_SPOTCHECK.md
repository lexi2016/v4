# BATCH220 独立语义抽查 receipt

审查时间：2026-10-15，官方网页复核截至 06:24 UTC 附近。执行者：独立子任务 `us_mapping_220_semantic_audit`；模型按本轮明确指定为 `gpt-6.1-sol` / `high`。未派生子任务。

## 结论与适用范围

**`SOURCE_REVISION_DISPLAY_NON_BLOCKING_WITH_FLAGS`**：本次在新增 180 条中选取的 12 条高风险关系，未发现足以阻断该包作为“来源修订研究材料”显示的核心事实反例。保留 R137 限制文本歧义、R021/R073 身份元数据冲突及独立访问未完成项。此结论不构成 220 条全量事实 PASS，也不构成 180 条新增关系全量独立验收。

- `independent_full_fact_acceptance_count = 0`；12 是定向抽查数，不能显示为全量事实验收数量。
- 只允许显示来源身份、已声明的事实期间、研究用途、closure scope、原限制、当前缺口、下一证据和后续修订；`BOUNDED_RESEARCH_USE_CLOSED` 只限其 scope。
- 选股、权重、预测、PIT、事件触发、回测、真实可成交性均未在本次审查中获得资格。
- `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
- 本 receipt 不验证实际 API/UI 展示行为；由独立工程验收另行出具 receipt。

## 冻结范围与输入

```text
GOAL: 对新增180关系进行12条高风险语义抽查，判断source-revision显示阻断项
WRITER: 本独立审查执行者仅写本receipt
REVIEWER: 与工程writer分离的本独立语义审查任务；不是220全量事实验收
ALLOWED_PATHS: docs/handoffs/us_hk_667_finish_review_20261015/BATCH220_SEMANTIC_SPOTCHECK.md
FORBIDDEN_PATHS: 其他全部文件；源包/数据/engine/评分/BUY/服务/部署
PASS_SIGNAL: 有界source-revision显示裁决、逐样本事实/时点/下一证据、争议/访问缺口可追溯
STOP_RULE: 不执行ZIP脚本，不将定向抽查外推为全量事实通过；不补写业务数据
```

新包：`/Users/lexi/Downloads/US_HK_667_batch11_cumulative220_review_20261015.zip`。父任务提供的身份 SHA256：`8a214c3c10931e2ab807a3f1701449105702c68186a07a3c1da717413e69fab1`；包身份/CRC/字段/守恒由工程检查负责，本任务未重复其机械验收。

旧包：`/Users/lexi/Downloads/US_HK_667_batch2_cumulative40_review_20261015.zip`。本任务用旧包 `04_cumulative_results.csv` 的 `关系编号` 确认以下 12 个样本均不在旧 40 条集合中。主读取新包：

- `11_cumulative_processed_relation_summary.csv`
- `11_累计220条关系摘要_20261015.csv`
- `12_subsequent_research_addenda.json`

样本为定向选取，并非随机样本：`R023, R027, R044, R065, R066, R085, R105, R106, R137, R143, R168, R191`。分别覆盖批次 3、4、5、6、7、8、10、11；此外仅为检验跨版本附注传播，检查旧关系 R021 及共同影响 R073 的附注。所有 ZIP 内容仅由标准库读取；未执行包内任何 Python/脚本。

## 逐条语义结果

### R023｜00010 恒隆集团—TLT｜ETF 宏观背景

- **来源主张**：2026-06-30 掉期后浮息 61%、借款币种 52% HKD / 48% RMB；主用途仅利率背景，明确拒绝 TLT 上涨直接推出股票方向。
- **独立支持与缺口**：[iShares 官方产品页](https://www.ishares.com/uk/professionals/en/products/239454/ishares-20-year-treasury-bond-etf)确认 TLT 跟踪剩余期限超过 20 年的美国国债指数，支持期限/币种错配限制。恒隆[原中报 PDF](https://www.hanglung.com/getmedia/1e608849-0472-4e5a-9487-243de3f9280f/HLG_IR2026_E.pdf)及官方 investor 入口本次工具访问失败；61%/52%/48% 和资本化变化**本次独立数值复核 CANNOT_CONFIRM**，不能因链接存在判通过。
- **当前适用**：宏观背景分类合适；2026H1 债务结构不能充当 10 月即时净利率敞口。没有当前直接合同、持仓或收益方向获证。
- **下一证据**：可读官方 H1 财务原件及后续逐币种重定价/掉期/资本化利息附注，匹配实际本地贷款利差。
- **裁决**：`PARTIAL_PRIMARY_RECHECK / BACKGROUND_ONLY`；允许带来源归属和访问缺口显示，不支持独立事实全通过。

### R027｜00013 和黄医药—HCM｜同发行人 ADS

- **来源主张/独立支持**：[SEC 所载发行人 2026-07-30 中期公告](https://www.sec.gov/Archives/edgar/data/1648257/000110465926088458/hcm-20260730xex99d1.htm)同时列 HUTCHMED、Nasdaq/AIM:HCM、HKEX:13，术语表明确每 ADS 对应 5 普通股。核心身份及单位吻合。
- **当前适用**：仅支持同发行人信息/单位研究；包内没有把 1:5 单位升级为即时价差、可转换或套利资格。
- **下一证据**：现行存托协议、最新发行注销通知/费表、双边同刻价格及 FX；实际交易与结算状态仍未核。
- **裁决**：`SUPPORTED_CORE_IDENTITY_BOUNDARY`；所读披露期间内未见核心矛盾。

### R044｜00020 商汤—NVDA｜未建立具名供应关系

- **来源主张/独立支持**：[NVIDIA FY2027 Q2 官方 10-Q](https://investor.nvidia.com/files/doc_financials/2027/NVDA-2027-Q2-10Q-Final-including-exhibits.pdf)确有少量 H200 许可、特定中国客户及限制/部分出货描述；相关段落未具名商汤。许可存在不能补成商汤具体设备或订单，包内维持 `OPEN` / 未建立有效研究用途符合证据边界。
- **当前适用**：没有证明历史或当前具体供货。本次未独立复核包中每个 OFAC/BIS 法人、规则和许可断言，不授予交易级监管适用结论。
- **下一证据**：具名采购/交付/部署官方材料，型号、买方和最终用户法律实体、期间，以及适用的可核许可证/规则。
- **裁决**：`NO_NAMED_SUPPLY_UPGRADE`；保留 OPEN，不把未具名客户名单当已排除或已证明供货。

### R065｜00087 太古 B—SWRBY｜类别/ADR 双比例

- **来源主张/独立支持**：[太古官方股东资料页](https://www.swirepacific.com/en/investor-relations/shareholder-information/stock-and-credit-information)列 00087 对应 SWRBY、存托人为 BNY，并说明 A/B 每股同为一票及股息单位 5:1；网页标示最近更新为 2025-04-07，不能当 2026 年实时交易确认。
- **当前适用**：发行人/B 类识别获支持；A:B 股息单位 5:1 与每 ADR 底层股数是两件事。包内没有用 Citi 目录值代替 BNY 当前法律/操作条款，保持 OPEN 合适；本次未独立复核最新 ADR 5 股比例/转换状态。
- **下一证据**：BNY 的 SWRBY/CUSIP870794401 现行协议、最新比例、发行注销状态与费用。
- **裁决**：`SUPPORTED_ISSUER_CLASS / ADR_TERMS_OPEN`。

### R066｜00100 MiniMax—AMZN｜技术托管不等于收入合同

- **来源主张/独立支持**：[AWS 官方文章](https://aws.amazon.com/blogs/machine-learning/run-minimax-models-on-amazon-bedrock/)列 Bedrock 的 MiniMax M2/M2.1/M2.5 模型及调用入口，支持技术集成；[MiniMax 官方 H1 2026 业绩公告](https://www.minimax.io/news/minimax-announces-first-half-2026-financial-results-1787744160)确认 00100 主体，63.4% 对应整体 Open Platform 及其他企业服务收入类别。
- **当前适用**：63.4% 不能归于 AWS；AWS token 收费不证明向 MiniMax 付款或其利润。原港股名称空值保留是源身份问题，不得拼接旧 00100 价格历史。包内有限技术 scope 与商业合同缺口分开，未见核心升格。
- **下一证据**：具名商业协议/财报附注，收付款法律实体、许可/分成计量、渠道净收入和确认期间。
- **裁决**：`SUPPORTED_TECHNICAL_SCOPE / COMMERCIAL_ECONOMICS_OPEN`；“具名合同与业务关系跟踪”类别不能在 UI 简化为“已核当前合同”。

### R085｜00136 中国儒意—EA｜历史退出

- **来源主张/独立支持**：[Nasdaq 官方完成更新](https://www.nasdaqtrader.com/TraderNews.aspx?id=ECA2026-545)明确 EA 普通股 CUSIP285512109 的最后交易日为 2026-08-04、停牌生效 2026-08-05。支持排除该旧证券作为现役 Nasdaq 价格节点。
- **当前适用**：停牌不证明儒意商业/IP 合作终止；本次未另复核包中两个开发项目的全部 HKEX 商业事实。包内也未将退出日期当合同终止、最终注销或当日新催化。
- **下一证据**：具名开发/许可的现行签约及承继实体、实际版号/上线、权益分成。历史回测另需完成更新首次公开时间的 PIT 封存。
- **裁决**：`SUPPORTED_HISTORICAL_PRICE_EXCLUSION`；不恢复旧 EA 当前价格用途。

### R105｜00175 吉利—ZK｜停牌/移除阶段

- **来源主张/独立支持**：[SEC 所载发行人合并完成公告](https://www.sec.gov/Archives/edgar/data/1954042/000110465925123525/tm2534059d1_ex99-1.htm)确认 2025-12-22 完成合并、旧股/ADS 注销为对价权利及请求当日停牌；[NYSE 提交的移除通知](https://www.sec.gov/Archives/edgar/data/876661/000087666125001004/ruleprovisionnotice.htm)明确 2026-01-02 开市移除，二者是不同阶段。
- **当前适用**：支持排除旧 ZK ADS；不证明最后真实成交分钟、兑价全部完成、首次并表或当期归母收益弹性。包内没有将 ZK 当 GELHY 同代码别名。
- **下一证据**：官方最后成交/永久证券 ID 与公司行动链；经营用途另取 NCI、股本/融资、分品牌利润桥。
- **裁决**：`SUPPORTED_HISTORICAL_PRICE_EXCLUSION`。

### R106｜00175 吉利—GELHY｜新旧 ADR 项目

- **来源主张/独立支持**：[BNY 2025-08-18 官方新项目公告](https://www.adrbny.com/content/dam/adr/documents/corporate-actions-dr/files/AD2000218.pdf)确认 GELHY、CUSIP36847Q202、Cayman、Sponsored Level I、OTC、每 DR 对应 20 普通股；[Citi 旧项目目录](https://depositaryreceipts.citi.com/adr/guides/pgm_d.aspx?cusip=36847Q103&pageId=16&subpageID=104&typeDisplay=A)列旧 GELYY/CUSIP36847Q103 于 2025-08-18 inactive，并明确同日 BNY 新 sponsored successor 及新代码/CUSIP。
- **当前适用**：新旧代码不是同一时点相互冲突的活跃报价。Country 市场标签不等于注册地。项目存在/目录状态不证明当前 OTC 真实成交或操作转换。
- **下一证据**：现行协议、当日书簿/转换限制、费用税项、同刻有效报价/成交和 FX；总回报历史跨项目衔接仍未验证。
- **裁决**：`SUPPORTED_PROGRAM_SUCCESSION_BOUNDARY`。

### R137｜00288 万洲—SFD｜控股子公司不是母公司 ADR

- **来源主张/独立支持**：[Smithfield 官方 2026Q2 10-Q](https://investors.smithfieldfoods.com/sec-filings/sec-filings/content/0000091388-26-000051/smf-20260628.htm)明确其为 WH Group 间接多数拥有的子公司，IPO 段落列独立普通股及 SFDS UK Holdings 持股链，支持控股关系，不能解释为 WH 的 ADR。
- **当前适用**：包内已把约 87% 限定为 2026-03-24 历史近似值。本次未独立复核该近似数或最新精确比例，不支持 10 月权重/归母利润/等比例股价计算。
- **表述风险**：`current_usage_limits_with_addenda_json` 首项原文为“SFD是WH ADR、87%为当前精确值、子公司市价日变直接记合并损益或等比例股价”，没有否定词。与同一行 verified facts 的“非 WH ADR/历史近似比例”相反，按字段用途它是列举应禁止的误读，不能抽成肯定事实。标记 **`SOURCE_TEXT_AMBIGUITY`**；本审查不改原数据。
- **下一证据**：最新实益持股/资本变化、权益稀释、准则及合并抵销/NCI 调节。显示时保留“使用限制”上下文及上方已证事实，避免孤立摘句。
- **裁决**：`SUPPORTED_MAJORITY_CONTROL / SOURCE_TEXT_AMBIGUITY`；非阻断来源修订显示，不授予当前比例事实通过。

### R143｜00291 华润啤酒—HEINY｜NV/Holding 与穿透比例

- **来源主张**：2026-06-30 的 NV 全资链→40% CRH(Beer)→51.67% 华润啤酒，约 20.668% 只是所报取整比例的乘积；被视为权益不等于经济权益。
- **独立支持与缺口**：[Heineken 官方 ADR 对照页](https://www.heinekenholding.com/investors/share-information/american-depository-receipts)确认 HEINY 对应 Heineken N.V.，HKHHY 对应 Holding，均为 DR:ORD 2:1。本次[华润官方中报目录](https://www.crbeer.com.hk/en/interimReport/index.html)可访问且列 2026-09-08 报告，但所链中报 PDF 工具访问失败；因此完整 40%/51.67% H1 股权链**本次独立正文复核 CANNOT_CONFIRM**。不得用 ADR 页面或已打开的 H1 业绩公告替代股东附注核验。
- **当前适用**：本次支持 NV/Holding 证券识别；来源所报 H1 链及约 20.67% 只可带来源归属、时点与未复核标记展示，不是 10 月当前持股或现金权重。
- **下一证据**：可读的官方 H1 股东附注、后续权益变化与中间公司分配/融资限制、Heineken 应占利润和已收股息桥；许可经济条件单独取得。
- **裁决**：`SUPPORTED_ADR_ISSUER / PARTIAL_PRIMARY_RECHECK`。

### R168｜00325 布鲁可—HAS｜授权/产品收入与合同权益

- **来源主张/独立支持**：[FY2025 官方年报](https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0417/2026041701069.pdf)列 Hasbro 伙伴、TRANSFORMERS 授权地域扩展及该系列收入 RMB951.0m；[H1 2026 官方中报](https://www.hkexnews.hk/listedco/listconews/sehk/2026/0916/2026091600891.pdf)列系列收入 RMB619.0m，总收入 RMB1775.695m。年度总收入 RMB2913.338m 来自年报。
- **当前适用**：可复算年度约 32.64%、H1 约 34.86%，均是产品收入比例；不是授权费、IP 股权或利润 beta。“大多数国家/地区”也不等于永久全球授权。来源维持 OPEN，当前签约子公司、期限、品类/地域负面清单和经济条款未补齐。
- **下一证据**：现行许可/续期摘要，签约主体、国家及 SKU/品类边界、到期/清货、费率和最低保证；再补分 IP 净利与实际动销。
- **裁决**：`SUPPORTED_REPORTED_REVENUE / CURRENT_LICENSE_TERMS_OPEN`。

### R191｜00376 云锋—ETHA｜历史 ETH 与 ETF 公司行动

- **来源主张/独立支持**：[云锋 2025-09-02 官方公告](https://www.hkexnews.hk/listedco/listconews/sehk/2025/0902/2025090202175.pdf)确认当日累计买入 10,000 ETH、含费用总成本 USD44m；[ETHA 官方 SEC 补充招股书](https://www.sec.gov/Archives/edgar/data/2000638/000143774926032082/etha20261002_424b3.htm)确认 2026-10-06 一合三及新 CUSIP46438R204，拆合股不改变信托总资产价值。
- **当前适用**：历史购币不证明 10 月当前净 ETH、托管或对冲；云锋和 ETHA 是底层价格参照，不是已证交叉持股。原始 ETF 序列跨拆合股不可直接比较。包内维持 OPEN；其年度减值/收取权利金额本次未另复核。
- **下一证据**：逐币净量、收取权利交付、出售/质押/对冲、托管限制和会计口径；ETF 调整因子、同 cutoff NAV/成交及云锋有效行情。
- **裁决**：`SUPPORTED_HISTORICAL_PURCHASE_AND_SPLIT / CURRENT_NET_EXPOSURE_OPEN`。

## 旧关系新增附注传播检查：R021 / R073

这不是新增 180 条中的额外事实 PASS，只检验跨版本冲突是否被隐去。

- 附注 `B5L3-SHARED-H-JURISDICTION-20261015` 同时指向 R021、R073，原字段未重写、状态仍 OPEN。独立打开同份 Hyatt 10-Q 的 [SEC 索引](https://www.sec.gov/Archives/edgar/data/1468174/000146817426000025/0001468174-26-000025-index.htm)可见独立 `State of Incorp.` 标签为 IL；[正式正文封面及 Note 1](https://www.sec.gov/Archives/edgar/data/1468174/000146817426000025/h-20260630.htm)为 Delaware，另列 Chicago 办公地址。包中“索引元数据与正文冲突”的陈述有官方支持，不能偷换成“地址州误读已消除全部冲突”。
- 新包 R021 的 `subsequent_research_revisions_json` 保有完整附注，`current_usage_limits_with_addenda_json`、`current_next_key_evidence_with_addenda_json` 已包含新限制和下一证据。
- `11_累计220条关系摘要_20261015.csv` 的 R021“使用限制”和“下一份关键证据”也显示完整附注；因此摘要没有完全遗漏冲突。
- **传播限制**：R021 `current_applicability_gaps_with_addenda_json` 与中文“当前适用缺口”未添加这项身份元数据冲突。只显示旧 gaps、或据旧四十条 fact/current 未变就称“前 40 无实质新增”，会漏报。应消费完整附注/当前限制/下一证据；本任务未验证应用是否如此渲染。
- 下一证据仍是现行章程/州登记及 SEC 修正或官方解释。新增附注不补足酒店合同、产权或开业时刻，不改变 OPEN。

## 未做与停止边界

未完成：220/180 全量官方事实复核、所有 URL 可读性复核、全部当前法律身份/合同、股权即时变动、市场 session/cutoff、行情 owner 读取、PIT、事件、回测、预测、实际 API/UI、自然运行、部署、GitHub 外发。

没有发现核心反例与证明全量正确是不同结论。所有“未独立复核”必须继续保留，尤其 R023 的恒隆财务数值与 R143 的华润 H1 穿透链。此 receipt 仅完成本次有界抽查，停止进一步扩审；工程行为是否满足上述显示约束交独立工程 Reviewer 验收。
