# M02 · HK行情、证券主表与资格来源

日期：2026-10-10。只对应原M02/P2及P1必要输入，不是旧跨模块B02美股映射批次。Chat负责方案与代码，嘻嘻负责现有Mac落地独立验收。本包仅文档，未执行产品修改/测试/采集/部署。

## 固定依据
- [原总计划](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)
- [迁移执行计划](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)
- [固定代码树](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)
编号沿用原01—18/P0—P5。固定f7cb是静态目标前像，不代表Mac现役版本；部署前查active差异。S=本轮静态源码，R=历史报告，U=未知。文档与旧报告冲突时以新固定源码和带身份回执细分记录，不悄悄抹掉历史。

## 核心合同
target_date、signal_date、eligibility_source_date分别记录；HK证券日历、HK Connect资格日历独立。价格历史/panel、证券主表、membership是三类不同产物：价格可用而资格未知时必须保留两种状态，主表恢复也不证明目标资格齐全。
S：原HK Futu采集、capture gate与panel authority已存在。V5 capture_master是原SDK证据的私有重放发布，hk_membership_recovery只恢复已有SDK，并非新采集；两个reader已有严格源绑定。
R：迁移计划报告HK master恢复读回有证，但目标资格及每日来源完整性未齐；原17:20成功记录属于旧报告，不是本轮自然证据。
最小候选先接一套已有有效的价格/master/membership真实回执，原reader独立确认并交M06/M14；仅缺原件才调既有owner，不重新采集所有来源。

读SOURCE_MAP、PROMPT_FOR_CHAT、ACCEPTANCE。缺active前像不挡静态候选，安装前核。保持原单位/规模/身份门禁，不交易、不改变V4/8910。

