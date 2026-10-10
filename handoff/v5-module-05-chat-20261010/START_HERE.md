# M05 · A预选池（原七来源）

日期：2026-10-10。独立Chat只负责原M05/P2，依赖M01/M04及已有D-1复盘来源。Chat写方案和代码，嘻嘻现有Mac落地独验。本包只文档，未写产品代码、测试或部署。

## 固定依据
- [原总计划](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)
- [迁移执行计划](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)
- [固定代码树](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)
编号沿用原01—18/P0—P5。固定f7cb是静态目标前像，不代表Mac现役版本；部署前查active差异。S=本轮静态源码，R=历史报告，U=未知。文档与旧报告冲突时以新固定源码和带身份回执细分记录，不悄悄抹掉历史。

## 当前源码事实
S：f7cb的run_a_preselection已经支持v192/fupan/stage7/wechat/baimao/research六lane；research包含hourly优先+preview条件fallback。因此旧迁移计划的“五lane未接research”已被89ea56f后源码推进，不应重做。
七来源沿原业务保留，六lane不等于漏一个新池，也不能为计数再造并列research池。当前适配仍是只读组装，未发布正式PreselectionPoolStore。
最小下一候选：复用已验research工程行为，补真实来源合同剩余断点与模块私有保存/独立回读，再向M07交原consumer一致引用；不重写去重或评分。

## 固定基线与历史测试的差异
S：f7cb当前a_preselection.py原字节SHA256=e666660830b2f088c51ba00b9fafdefcf966efb798c25a5c21b18ba1c74aa74b，Git blob=05dd0b28f14bd794890f514e130d8090a1b0438b，29,140 bytes；与下列29项历史final adapter不同。已按connector原字节重算blob吻合，本包没有对当前SHA运行测试。不能把历史final通过覆盖f7cb。

## 已定位历史证据（R，本轮不重跑）
[89ea56f修复独审](https://github.com/lexi2016/v4/blob/89ea56f0ce7c0270df9228d6d50b7e57d4ce5176/V5/docs/reviews/2026-10-10-m05-research-owner-review.md)和[原receipt](https://github.com/lexi2016/v4/blob/89ea56f0ce7c0270df9228d6d50b7e57d4ce5176/V5/docs/reviews/2026-10-10-m05-research-owner-receipt.json)已connector读取。
- 最终writer 29/29；独审2个source-shape用例及1个worker-boundary用例分别通过，共3项独审，不能合并宣称32项全套。
- final adapter SHA256=ab023e461aa816064347d5619e07276d635f24db5d7aacf693034d2903a72472；full log SHA256=82e7fda63c81af64a2df5f9277b6691167ed8f611811de24a1a087169f8cbada。
- archived owner parity采用较早adapter SHA705534230375dc0fd237acb5c203c84f5bcfd2c405210caee85aef4e2f13426d：20261009/信号20261008为211行；20261012/信号20261009为152行但只有周五材料，周一窗口不全。不是final-SHA差分重跑。
- 真实preview fallback、完整周一09:00窗口、PIT、自然运行及V192 verified-empty仍未证；不以合成fallback补齐。

先读SOURCE_MAP→PROMPT_FOR_CHAT→ACCEPTANCE。缺active前像不挡静态候选，安装前核。保留V4、BUY及8910。
