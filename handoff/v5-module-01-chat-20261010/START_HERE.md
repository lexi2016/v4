# M01 · A行情与公式面板来源

日期：2026-10-10。本Chat只对应原M01/P2，不是先前跨模块“第一批公告”任务。旧跨模块任务已独立归档，原13/18职责不占用M01编号。

目标：复用原A同步、原公式与面板owner，让精确交易日的原行情→增量接续→原公式/selector-ready面板→M05/M09来源消费可追溯。Chat写方案和代码；嘻嘻负责现有Mac落地与独立验收。此包只准备任务，没有本轮代码、测试、采集或部署。

## 固定依据
- [原总计划](https://github.com/lexi2016/v4/blob/24c6d60d524f43fcf4209ec8b078ec02cb34417e/V5/docs/superpowers/plans/2026-10-09-v5-master-delivery.md)
- [迁移执行计划](https://github.com/lexi2016/v4/blob/d1bf034640ca2e5957423de2745a98e159b69af2/V5/docs/superpowers/plans/2026-10-10-v5-migration-execution.md)
- [固定代码树](https://github.com/lexi2016/v4/tree/f7cb731c384ee6890a87d16c19a5b5a621779477/V5)
编号沿用原01—18/P0—P5。固定f7cb是静态目标前像，不代表Mac现役版本；部署前查active差异。S=本轮静态源码，R=历史报告，U=未知。文档与旧报告冲突时以新固定源码和带身份回执细分记录，不悄悄抹掉历史。

## 已核事实与首个最小候选
S：原a_share_daily_sync及panel parts已存在；公式live流程有已成功generation复用、sync receipt、input manifest和读回，不能用“面板文件存在”替代源与公式双重owner核验。
S：V5有快照校验等共用能力；a_source_daily.py在固定tree尚无。SnapshotRecorder/主表规范化主要是HK SDK合同，不能作为“A已采集”证据。
R：迁移计划旧盘点称17:00配置及10月8日17:11:35成功；仅历史，未核本轮自然生产。活动Windows/Mac authority绑定和来源root仍U。
首个候选应读取一套已存在有效源/公式generation，生成模块私有精确来源binding并供M05/M09消费；仅确缺原件时沿原owner补采。缺active前像仅阻挡安装，不阻挡静态候选。

阅读SOURCE_MAP→PROMPT_FOR_CHAT→ACCEPTANCE。保留V4/8910，不交易，不扩大权限/凭据。

