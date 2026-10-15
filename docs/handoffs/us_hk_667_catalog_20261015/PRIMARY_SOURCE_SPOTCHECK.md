# 美股→港股映射一级来源抽查

研究员：`/root/mapping_primary_sources`，独立 Luna Max，只读。
查阅时间：2026-10-15 09:58:37 +08:00。主控按研究员返回整理本记录。
输入ZIP SHA256：`dac3c820fcd6919fabdccc9c37ee9055b729b200fcde5e48f0dcf527de81bc6d`。

本次定向抽查10条关系：8条的所述日期事实或组成事实获得一级来源支持；未发现来源冲突；2条历史事实有支持、当前适用性仍为CANNOT_CONFIRM。这个计数不表示8条具有当前预测资格，也不表示667只股票、1003条关系已全量事实验收。独立全量事实验收NOT_RUN，预测全部UNTESTED，旧997边比较NOT_RUN。

|原关系|已核事实和来源|日期与适用性|原报告对照及限制|
|---|---|---|---|
|R001 00001→CVE OWNERSHIP|长和2026H1披露Cenovus为上市联营公司，应占净盈利41.60亿港元。[长和中期业绩分析](https://www.ckh.com.hk/upload/assets/downloads/en/e_IR_2026_Operations_Analysis_20260813.pdf)；CVE同时有上游和下游业务，[Cenovus Q2业绩](https://cenovus.com/News-and-Stories/News-releases/2026/3335023)。|2026-08-13、2026-07-29；支持2026H1报告期事实。|与原报告一致。当前精确权益及估值敏感度未核；油价不代表CVE或长和全部利润。|
|R002 00001→HCM OWNERSHIP|长和通过间接子公司持有HUTCHMED权益，[长和中期业绩分析](https://www.ckh.com.hk/upload/assets/downloads/en/e_IR_2026_Operations_Analysis_20260813.pdf)；HCM上市与ADS身份由[SEC中期文件](https://www.sec.gov/Archives/edgar/data/1648257/000110465926088458/hcm-20260730xex99d1.htm)支持。|2026-08-13、2026-07-30；2026H1。|一致。当前经济权益比例未核；这是间接权益，不是同发行人。|
|R003 00001→VOD TRANSACTION_EVENT|49% VodafoneThree权益出售已完成并收到43亿英镑现金，[长和完成交易公告](https://www.ckh.com.hk/tc/media/press_each.php?id=3477)。|2026-07-30完成；历史事件。|一致。不得继续视为持续持股/利润传导。|
|R004 00001→BLK TRANSACTION_EVENT|2025公告为原则性安排，[港交所公告](https://www1.hkexnews.hk/listedco/listconews/sehk/2025/0304/2025030402128.pdf)。[BLK 2026Q3业绩](https://www.blackrock.com/corporate/newsroom/media/press-releases/blackrock-reports-third-quarter-2026)只能支持公司身份，不能证明交易交割。|2025-03-04、2026-10-14；当前交易状态CANNOT_CONFIRM。|一致。需最新最终协议、审批与交割证据，不能把管理资产当自有资产。|
|R722 02525→HSAI SAME_ISSUER|[SEC 6-K](https://www.sec.gov/Archives/edgar/data/1861737/000110465926082432/tm2620203d1_6k.htm)确认普通股拆8、ADS比例改为1:8、ADS总数不变；[2025 20-F](https://www.sec.gov/Archives/edgar/data/1861737/000110465926048025/hsai-20251231x20f.htm)载变更前比例及同发行人身份。|2026-07-10生效。|一致。现行1:8不得回填拆股前历史。预测及套利效果未核。|
|R564 01511→HSAI SUPPLY_CHAIN|[禾赛2021合作公告](https://www.hesaitech.com/hesai-and-uisee-reached-strategic-partnership-expanding-autonomous-driving-ecosystem/)与[2023 UISEE案例](https://www.hesaitech.com/how-does-uisee-become-the-ai-driver-of-the-world/)支持历史合作和产品使用。|2021-12-08、2023-06-29；当前合同CANNOT_CONFIRM。|一致。2026中期报告URL本次工具无法打开；body_opened原字段不算本次证明。当前采购、续约和排他性均未核。|
|R843 03690→DASH BUSINESS_PEER|[美团中报](https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0929/2026092900008_c.pdf)披露核心本地商业和新业务；[DoorDash 2025 10-K](https://www.sec.gov/Archives/edgar/data/1792789/000179278926000013/dash-20251231.htm)含DoorDash/Wolt/Deliveroo和40多国市场，Deliveroo收购2025-10-02完成。|2026-09-29、2026-02-18提交。|基本一致。功能同业是有限分析推断，非股权/合同关系。补充DASH并非只经营美国，不能把美国订单直接类比中国需求。|
|R027 00013→HCM SAME_ISSUER|[HUTCHMED SEC中期文件](https://www.sec.gov/Archives/edgar/data/1648257/000110465926088458/hcm-20260730xex99d1.htm)：港交所/AIM普通股，Nasdaq ADS，每ADS=5普通股。|2026-07-30；支持报告期身份。|一致。之后证券结构变更和实时报价未核；与00001→HCM权益边分开。|
|R994 09987→YUMC SAME_ISSUER|[百胜中国2025年报](https://www.hkexnews.hk/listedco/listconews/sehk/2026/0416/2026041601400.pdf)说明NYSE YUMC/港股9987均为普通股，两地可互换，2022年双重主要上市。|港交所2026-04-16发布。|一致。1:1是相同普通股单位的推导，不是ADS比例；实际过户时效未核。|
|R144 00293→BNO COMMODITY_EXPOSURE|[国泰2026中期业绩](https://news.cathaypacific.com/the-cathay-group-announces-its-2026-interim-results)披露航油成本；[2025年度业绩](https://www.cathaypacific.com/content/dam/cx/about-us/investor-relations/announcements/en/2025-cx-annual-results-en.pdf)披露净燃油成本313.44亿港元及部分Brent条款套保；[BNO官方说明](https://www.uscfinvestments.com/bno)为Brent近月原油期货基准。|2026-08-05、2026-03-11、产品页2026-10-15查阅。|一致。航油成本敞口与期货代理不是航油现货，也不构成股价因果；套保、展期、附加费和需求可抵销影响。|

所有方向、传导幅度和投资收益仍属待验证研究推断。当前事实适用性、报告期事实和预测资格分别处理；本次未修改原始关系行或给任何关系授予生产资格。

RESEARCH_ONLY=true；production_allowed=false；buy_gate_updated=false；orders_sent=false。
