# ACT-062A 本地冻结复算

基线 96a5efe0d2ea70aa89b0e66f5662250c95246fdc。执行入口只读取已封存 ACT-024、034、037-F01、046、050、056、057、058、060、061 研究原件、应用同一 2026-11-20 冻结 Reader 并输出本批派生成果。未调用拟合、预处理拟合、聚类、模型加载、预测、调参、模拟或生产入口。冻结累计研究 FIT=291，全部输出仅研究使用。

在本批工作树逐项校验并准备两份只读输入：ACT-056B 的 1_KB41_Stock_Cards!A1:Z52 原范围、UNFORMATTED_VALUE 无损行数组副本 input_ingress/act056b_stock_cards.json，以及 ACT-061B 原件 input_ingress/ACT061B_KB42_MANUAL_V1_3.md。可再生本批原件副本仅供执行，交付实下载核验结束后清理。原 Google Drive 文件和本机已核收证据保持原状。

运行方式（使用同一冻结 Reader 已验证 Python 和 ACT-061A 已采用 psutil 缓存，只读依赖）：

~~~sh
cd /Users/lexi/.codex/worktrees/act062a-kb42-0fit-20261125/artifacts/act062a_kb42_0fit_20261125
act062_panel_python='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
act062_psutil='/Users/lexi/.cache/uv/archive-v0/-GpULTzdgS0ouii5'
PYTHONPATH="$act062_psutil" "$act062_panel_python" -B run062.py --canary
PYTHONPATH="$act062_psutil" "$act062_panel_python" -B run062.py --run-name primary
~~~

复算时须换未占用运行名称。成果与运行证据分别在 results/运行名称 和 evidence/运行名称_writer_evidence.json，盲包与揭盲密钥是物理隔离的两个文件。两文件、原始输入/快照、运行输出及日志均不提交 Git。不可扩大现役共享 Reader、权重或门禁的范围。本轮 Git 仅同步此 SOP 和六份最小复现代码。对账参考为既有冻结 ACT-046 两组合席位的逐键原件与无四舍五入归约回执；Top-50 依据其 ACT039/ACT042 历史排名规则复原，无独立旧 Top-50 成员表。现有冻结分数均只读；没有生成新的评分。T+5 原收益分别用 ACT-024 观察标签，同日所有 ACT-024 Y 键的 T+5 中位数用于原冻结超额归约。CORE/FULL 距离按 Reader 交易所日历，OOS 窗未覆盖的临界栏保留，不当作证实未命中。

标签字典历史买点 T+5、D 后观测和配对收益与前窗列分别命名。每个前窗描述使用其 D−1 已物理截止的数值，整股历史汇总仍有反向选样，跨期可用性须另检验。盲包阶段 A 仅 [-15,0]，阶段 B 到截点；ZIP 中各阶段只能读到该阶段文件自己的数值，不含代码、名称、日期及结局。保持优先补足六只低上影覆盖股、四原型、每组八案；写入压缩前逐案校验并扫过整个 ZIP。ACT-062B 在盲判封口后再独立开启揭盲密钥。
