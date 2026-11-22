# PFT 全 A 纯 S 扩样实验

批次 PFT_S_FULL_ASHARE_SCALEUP_20261122_V1。统一 V4 Backtest Reader 上，沪深北 5,485 个可用归并证券完成抽样扫描。训练 450 个 episode，180 正、270 负，其中无旧破黄硬负例 120 个。2026 年全 A 时间外、未见证券 OOS 150 个。两组证券交集为 0。JOINT54、KB47 和 GEMINI R2 已曝光证券整股排除。

| 固定门控后 | LR | RF |
|---|---:|---:|
| JOINT54 Val16 | 16/16 | 16/16 |
| KB11 原图原 D | 10/11，FP 0 | 9/11，FP 1 |
| 全 A OOS 弱标签 | 150/150，BalAcc 1.0000，AUC 1.0000 | 149/150，BalAcc 0.9917，AUC 1.0000 |

- 全 A 盲测采用冻结结构弱标签。标签与特征共用部分结构证据，分数用于衡量规则在未见证券与时段的复现。两张原案例考卷沿用原定见。
- S 实际拟合 2 次，B 实际拟合 0 次。阈值 0.5，两个模型的预测与门控决策锁定后才读取盲测标签。序列化重载、31 项针对性测试与独立代码复核通过。
- 600 个选中截面逐格复算一致。样本准备清单 SHA-256 20f155bdbc82431b86d65e2e29cbeaec7b11d5952448127193bfb119159a6a32。V4 A 股采用 QFQ_ASOF 和 QFQ_EVENT_VOLUME，代次 4ed1e1e3ccc2f1045a83527a470f111b81d96771b105ba92e8348bf7f967b268。
- RESEARCH_ONLY=true，production_allowed=false，buy_gate_updated=false，orders_sent=false。

[签发正文](https://docs.google.com/document/d/10qC4OldmveVlw_7Tv8u-a8dUi1Eqn0TckzDD3eiBfdM/edit) · [共享数据包](https://drive.google.com/file/d/1xBPcYvDLRlDkx-CncPqy1zEG5eB99hoN/view?usp=drivesdk)
