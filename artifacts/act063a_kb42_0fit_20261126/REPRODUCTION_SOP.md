# ACT-063A 本地冻结复算

以 ACT-062A 已核收复现提交 `3b8e496f33eca3578c3ce859340ce283c192c513` 为基线。执行器仅消费固定研究原件，保留原文件、运行目录和模型门禁。运行需要本机的 V4 冻结 Reader、ACT-020/024/030/034/037/046、ACT-056A/057/061A、ACT-062A 成品与实下载回执，以及 ACT-062B 两份核收副本。文件身份、权威 Reader、代次、复权、市场和日历校验回执随每次运行保存。不存在模型权重入口。

在本批目录把 ACT-062B 的字典研究和 V1.4 手册原字节副本放入 `input_ingress/`，两个固定原件及其 SHA-256 见 `inputs063.py`。主控在完成交付核验后负责清除这两个批内临时副本。更早的核收原件经只读路径使用。请为每次完整复算选择未用过的 `--run-name`。脚本拒绝覆盖既有结果目录或机器证据文件。

```zsh
panel_python='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
act063_psutil='/Users/lexi/.cache/uv/archive-v0/-GpULTzdgS0ouii5'
act063_src='/Users/lexi/.codex/worktrees/act063a-kb42-0fit-20261126/artifacts/act063a_kb42_0fit_20261126'
cd "$act063_src"
PYTHONPATH="$act063_psutil" "$panel_python" -B run063.py --run-name canary --canary
PYTHONPATH="$act063_psutil" "$panel_python" -B run063.py --run-name independent_reproduction
```

- `inputs063.py` 反查 ACT-061A/062A 跨批 SHA-256，绑定固定股票、两年波段和既有 Reader 投影。ACT-062B 副本用于语义与来源固定。
- `trace063.py` 区分 ACT-024 的原 L50M 股票日与 ACT-034 FULL 就绪 OOS 键。对所有任务日期的 42 股目标投影，原 ACT-020 流动性/ST 代理桥和 ACT-024 X/Y/KEYMETA 逐键对齐。ACT-030 CORE 门禁逐项比较 float32 冻结输入转 float64 后的值，双线含两个原子判据，共八原子。未进入原 L50M 时无 ACT-024 CORE 谓词证据。以 ACT-046 冻结排序复现 2,400 封存席，并核对 ACT-062A 各事件的日期捕获。CORE 比较空间是两输入的同日平均并列分位均值，未发布原始 BLEND 分数。精确排名并列与实际排序浮点并列分列保存。CSV 的事件汇总和逐栏行分开，重复股票日按其各事件槽计，左截窗只覆盖当时没有冻结 OOS 的栏。
- `dq063.py` 按 ACT-057 owning 聚合规则，从两份 ACT-056A 原指纹重算 42 股的峰日长上影分子。原公布率的序列化精度为 `%.10g`，输出另附整数分子分母及约分后的精确率。D−1 比较先保留原 84 行的两位文本，再核 Reader 的白线、黄线位义，最后验证 ACT-062A 无 dtype 读取的数字映射。
- `exit063.py` 从事件 D+1 起做收盘观察。警示沿用冻结 ACT-061A 的当栏规则，等待固定两个后续交易栏，有任何一栏收盘不低于警示栏收盘且不低于双线即为修复。相对 D+20 的差值、事后保持／回吐、最大收盘回撤仅在观察点确定后连接。无成交、滑点、净值回放。预先选择四原型代表及已知早栏缺证共五案，每案做全部 21 个物理前缀与未来置空对照。触发时间缺证不做事后填补。
- `run063.py` 控制读取、计算、核验、写入与阶段耗时。原生线程配置为 Arrow 4 计算／2 I/O、BLAS 1。读量为经脚本实际读到或做校验的可计下界，解码投影数单列。峰值 RSS 来自单计算进程的 Darwin `ru_maxrss`。物理磁盘 I/O 与进程树峰值未测。

本地四件成果与机器证据是 Writer 候选。独立复核、远端五件发布及实下载字节/SHA-256、进度总表追加、最终清理证明由主控完成。保留失败日志与复现所需源指针。当前研究的累计 FIT 保持 291。RESEARCH_ONLY=true、STRICT_PIT=0、TRAIN_ADMITTED=0、NO_GO_BLOCKED=true、production_allowed=false、orders_sent=false、buy_gate_updated=false、知识库训练尚未完成。
