# ACT-016 参数卡四段样本外回放

本批以 ACT-015 封存的 2023–2026 折外预测和相同 V4/ACT-013 数据源为输入。2026 年回放截至 11 月 20 日，四段共 940 个交易日。ACT-015 保守全轨 T+3/T+5 必须逐日精确复现。研究执行不改变 S_FROZEN_V1 或实盘门禁。

使用项目解释器从源码根运行如下入口，输入路径与文件名可用 `--help` 核对。

1. `python -m ops.pft_act016_calibrate_2022`。用 2023 两个隔离证券折的已归档模型，对 2022 年收盘时可用特征评分。样本证券与其评分模型训练证券互斥。该种子供 2023 起始门槛，后续年度增加此前已封存年度的预测。完整种子按清单 SHA 复用。
2. `python -m ops.pft_act016_replay`。核验上游密封清单，计算年度扩展三分位和 B1/B2 的历史折外 RF Q80。B3 用门控后 S 概率与 B 概率相乘。强、震荡、弱市的新开仓预算按 100%、50%、0% 除以持有期限，对应最多 3、2、0 只。
3. 检查 `pre_execution_seal.json`、`baseline_parity.json`、`daily_nav.parquet`、`portfolio_ledger.parquet`、`metrics.csv` 和 `replay_manifest.json`。临时执行行情仅留在进程内存中。

固定止损以实际开仓价及可用日 K 最低价判断，在后续首个允许方向成交的开盘卖出。流动性筛选按 D 日 V4 原始人民币成交额 1 亿元，排在取 TopK 之前。买卖分别扣 7.5 bp 与 12.5 bp。云端 GBDT 与本地 ACT-015 RF 分数单位不同，基于本地历史分数重定 Q80。当前前复权快照的历史逐日版本 CANNOT_CONFIRM。

运行 `pytest` 检查 `tests/test_pft_act016_replay.py` 和既有 ACT-015 专项测试。研究标志为 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
