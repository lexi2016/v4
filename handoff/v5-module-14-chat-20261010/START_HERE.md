# M14｜超跌研究与选股
日期：2026-10-10。原总计划模块14，P1；不要使用早期盘点把14记成US映射。此包只准备独立Chat编码交接，未改产品代码、未测试、未操作Mac或部署。

## 交给Chat的方式
先读本页和SOURCE_MAP.md，再按PROMPT_FOR_CHAT.md交完整候选；ACCEPTANCE.md用于嘻嘻的Mac验收和问题回传。Chat写方案与代码，嘻嘻负责本机落地、测试及页面验收。若原超跌Chat或Mac已有候选在推进，先接收其固定候选和回执，不重新开平行修复。

## 目标与边界
复用原HK02来源及原strict/near两门，补真实来源准入、精确保存/独立读回并交M18消费。M02拥有HK采集、主表与资格源；M14消费其提交证据并拥有超跌计算/准入。M18拥有经理保存和普通同run读回；共享UI、gateway、调度/发布配置走统一集成请求，M14不直接覆盖。
保留V4、8910、原算法与研究安全字段，不交易，不改BUY门，不扩系统权限或凭据。不能改标签、填0、缩减分母或降低门槛换取“通过”。

## 已核事实与必须复用的进展
- 固定V5观察F：f7cb731c384ee6890a87d16c19a5b5a621779477。原总计划24c6d60d524f43fcf4209ec8b078ec02cb34417e；迁移计划d1bf034640ca2e5957423de2745a98e159b69af2。源码存在不代表Mac当前已加载。
- 旧ebe5944ecfbec2f6a161793d7c11946dea063e57的身份阻塞不能继续写成未修。已有报告分别为身份18通过、原回归77通过/4跳过、显式验收38通过/1跳过，真实model也有通过回执；本包未重跑，测试数不相加。
- F已含修好的_same_code完整18个code字段比较，以及_align_repair_trade_dates存储兼容。后者所在rebound_panel_repair.py与R准入包source/rebound_panel_repair.py Git blob完全一致：af95f98728ad0d83ff4b02f14446ee922120ff3b。旧int64/string ArrowInvalid是历史阻塞，不能再写一套同修复；先核Mac现有child/候选是否使用这些字节及其真实发布结果。
- R准入包仍有真实来源、单位、成员、信任与same-run缺口。历史样本67必需cells中56缺失、2个trade不一致；历史membership 698与panel 695差3码。仅属于该历史目标证据，不能套到当前目标。logical自摘要与raw-byte SHA不同不是损坏，原错误诊断已撤回。694_BATCH_HOLD不因日期兼容或算术通过自动解除。
- D已有Decimal 80%边界修复。本轮静态确认F的rebound vendor主筛选行935和manager vendor主筛选行1264仍是float乘法。不能直接贴D整个patch：D前像是另一个V4 current-live文件，而F的rebound observation还按源码行号/SHA抽取AST。需最小移植、更新相应pin/抽取合同并回归，不重写策略。
- F daily_rebound_owner固定调用S独立checkout；S的rebound_daily是numeric observation幂等封装，selection_status仍CANNOT_CONFIRM。F自身没有rebound_daily.py，不可假设主树已有它，更不能把daily成功当正式入选。

## 两门与准入分别成立
1. 收盘价≤此前60个HK证券交易session最高价×0.8。60-session高点包含原规则允许的半日session。
2. 当日成交量÷此前5个完整HK交易session平均成交量≥1.5；量能窗口不含半日。当前screen以完整signal session为合同，不能自行放开半日signal。
两门且数据已知为strict；恰一门通过且另一门明确失败为near；未知归pending/unknown，双门明确失败为excluded。成交额、低点反弹、20日背景量只是观察。另一rebound_v3_metrics四项函数有不同调用场景，不能拿来替换主筛选。
这些数字成立仍不证明价格基础/币种、成交量单位/scale、完整panel/master、实际资格、PIT或正式准入。

本包五层验收全部NOT_RUN。最终需真实原件→原算法/准入→不可变产物/独立读回→M18普通页→自然接续/回滚；只有观察数字或HTTP 200不算M14完成。

