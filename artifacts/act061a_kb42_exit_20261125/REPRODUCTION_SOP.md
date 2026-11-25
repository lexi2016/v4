# ACT-061A 冻结复算

基线为 `5477c6a3440fdec9dbf7d90b61e520e74fe9626b`。沿用本机原工作区的 ACT-056A、057、058A、059A、060A 和 PFT ACT-050 已封存原件以及 2026-11-20 V4 冻结 Reader。复算工作树提供本批两个入口和 ACT-060A 已提交依赖。运行仍需本机原件、冻结 Reader 及其本地依赖。

每轮都先在隔离复算目录准备 `inputs/`、`evidence/`、`delivery/`。按本批回执校验并配齐 `inputs/`，包括派发和手册快照、来源清单及对照前生成的 42 主路径锁表。不要在已交付目录覆盖同名产物。两个计算可串行执行，均先进行单例。

```zsh
panel_python='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
act061_psutil='/Users/lexi/.cache/uv/archive-v0/-GpULTzdgS0ouii5'
act061_batch='/absolute/path/to/act061a-reproduction'
act061_code='artifacts/act061a_kb42_exit_20261125'
PYTHONPATH="$act061_psutil" "$panel_python" -B "$act061_code/exits061.py" --batch "$act061_batch" --canary
PYTHONPATH="$act061_psutil" "$panel_python" -B "$act061_code/exits061.py" --batch "$act061_batch"
PYTHONPATH="$act061_psutil" "$panel_python" -B "$act061_code/controls061.py" --batch "$act061_batch" --canary
PYTHONPATH="$act061_psutil" "$panel_python" -B "$act061_code/controls061.py" --batch "$act061_batch"
```

- 波段输入固定为旧 7 股 108 条和其余 35 股 475 条。完整 20 栏 562 条，另 21 条原样保留缺证。先以精确同基底峰高减 D+20 收盘判符号，再除以 D 收盘转百分比。
- 逐股表的 `STOCK` 行为 42 股画像。`CROSSTAB` 至少保留四原型、二结局、四路径各个组合。`TEST` 行给出有效 N、检验、效应和 BH 校正。组内波段有时间依赖，原型 D 只有一只证券。结果用于观察历史路径。
- 35 个主案使用 ACT-060A 原键。旧七股各取 ACT-059A 最近完整事件，因为旧核收资料每股有两个极端案例。主案在读取对照结局前写入键锁。民生银行 2024-11-14 为历史保底，移出近两年波段统计分母。
- 对照沿用冻结普通日资格。候选锚与主案相差至少 25 个交易日，排除该股所有已知反向事件的 D−5 到 D+20，主案与对照两个 D 到 D+20 窗零重叠。候选须通过距冻结日、同基底 20 栏可用性及 D−1 白黄线精确状态检查。先同年，再跨年，按相距交易日与日期择近。日期锁定后才读取对照信号和表现。跨年差异需供逐案解释。
- 84 案 CSV 的上下文按声明的字段顺序解析。图包索引位于 `PAIR_INDEX.csv`，可按股和事件键对回完整波段。配对 SVG 为历史结局分层对照，每幅使用当案 Reader 前复权价格和成交量，跨案视觉高度需参照各自数轴。
- 本批 FIT、预处理拟合、聚类、模型载入、预测、新评分、调参、模拟买卖、生产写入及订单均为零。累计研究 FIT 291。历史 STRICT_PIT=0，训练仍未准入。
