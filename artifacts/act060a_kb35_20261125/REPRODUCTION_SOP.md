# ACT-060A 本地复算

本批固定冻结 42 股研究卡与 ACT-059A 七股补表。工作树基线为 `8a4f86206bafcfa9a77651b8d4eedb213b9bfbd4`。本机原工作区必须可读，包括 ACT-058A、ACT-059A、ACT-057、ACT-056A、PFT ACT-050 原件与 ACT-060A 的 `inputs/`。源码提交提供本轮计算入口，复算仍依赖原位冻结 Reader 和已有本地模块。0 FIT，模型载入、预测、拟合、调参、新评分和交易执行均为零。

在复算工作树的根目录执行。目标 `delivery/` 和 `evidence/` 必须已创建。脚本创建新结果，碰到已存在的本轮同名产物即停止。

```zsh
panel_python='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
act060_batch='/Users/lexi/Desktop/学习/v4_app/artifacts/act060a_kb35_20261125'
act060_script='artifacts/act060a_kb35_20261125/compute060.py'
PYTHONPATH='/Users/lexi/.cache/uv/archive-v0/-GpULTzdgS0ouii5' "$panel_python" -B "$act060_script" --batch "$act060_batch" --canary
PYTHONPATH='/Users/lexi/.cache/uv/archive-v0/-GpULTzdgS0ouii5' "$panel_python" -B "$act060_script" --batch "$act060_batch"
```

单例用民生银行验证零近两年完整波段的冻结历史保底、同股同年匹配、原数与 SVG 对齐，只写单例回执。首次单例在日期覆盖断言退出。当时四个锚和单股历史未覆盖冻结的早期日历部分。重试用 ACT-050 已绑定的 41 股和四个锚的早期日期键补齐日历，对其他股票只读日期和身份键。完整计算投影 35 股所需行情及字段，复用 ACT-058A 母池核验和交易所排程。最终本地通过信号为 `PASS_KB35_RAW_CSV_SVG_AND_PAIR_ALIGNMENT`，回执在 `evidence/ACT060A_COMPUTE_RECEIPT.json`。

## 选择与字段

- 近两年指交易所日期 `20241120` 至 `20261120`，两端包含。波段表保留冻结事件键及缺失窗口。主路径选最新完整 D+20 波段。若近两年无完整波段，取冻结历史最新完整波段，标 `FALLBACK_HISTORY`。备选键供复盘查阅。
- 同股对照使用原合格普通日母池，限制同一自然年。D−1 收盘与白线、黄线分别比较，等于时计在线上，`11` 表示同时不低于白线和黄线。优先已知且双状态相同，再按相距交易所栏数排序，平局取较早日期。若没有相同已知状态，沿同股同年原母池取最近日。D 当日信号和 D 后表现直到排序结束才进入计算。原母池资格已有既定数据成熟性条件。
- 两张 CSV 用 UTF-8 BOM，空值由状态字段解释。配对表 31 个排程栏采用紧凑 JSON，列序见 `bars_layout` 和 `bar_values_layout`。两套 OHLCV、白线和黄线使用可往返的数值表示。原 Reader 前复权与固定事件 D 仿射基底同时保留，缺栏为 JSON `null`。收复和失守认相邻有效栏跨线，首个日期从 D 起搜索。旁列保存 D−9 到 D+20 全部可判定交叉及首个日期的缺证状态。
- 警示从 D+1 起，取白线或黄线下穿，或阴实体且收盘不高于当日高点的 95%。四族和任一冻结信号各记 D−5 到 D+5 首次可见、覆盖和缺证状态，D 当日显隐单记。峰取 D+1 至 D+20 可观察最高价，等高取最早。峰后五个交易栏均可用时才给冻结口径的低点回撤。
- 同基底精确价差先执行 `peak_high_d_basis - close_ret_D20_close_d_basis` 并判正、负、零，然后除以 D 收盘并乘 100。SVG 使用原 Reader 前复权数值和交易所日历，缺有效栏或白黄线则断开。每图带价量坐标、关键日和七字段悬停值。

本地核验覆盖既有文件 SHA、全体冻结事件键、端点和价差、配对原值、CSV 回读、ZIP 及每个 SVG 的元数据、标记与价格线。视觉抽检和 Gemini 核收由主控记录。
