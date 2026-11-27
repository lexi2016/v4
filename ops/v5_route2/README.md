# V5 路线② Mac 本机候选

`route2.py` 使用同一份固定的 `route2.json` 运行 `close`、`evening` 或 `run`。输入目录为 `../inputs`，隔离输出目录为 `../out`。缺省日期取 Asia/Shanghai。看板初始化后复用本机已固定的原件副本，源目录中的引导 HTML 仅首次需要。当前配置绑定 D26 与 D27 的来源及 SHA-256。D26 的封存回放写到 `out/replay`，D27 的当日观测写到 `out/observed`。release 校验逐件比对 Drive 固定版 ZIP、SHA 清单和本机文件，然后只读加载原版逻辑。源归档、现役 HTML 备份和行情输入不随候选源文件交付。

## 本机结果

| 日期 | 收盘 | 晚间与可见看板 |
| --- | --- | --- |
| 2026-11-26 | 官方 G4 经原版验证与计算。Top200 全对象等同已验收封存榜单，5,571 条可排名，4 条留空。同日归档 PAR 有 5,502 条计算和 73 条隔离记录，109 字段样本与 8 个分片回读目录经原版晚间验证。 | 原版 `evening.assemble_v3` 和 `w10_board.render` 生成本机快照。单独运行晚间入口得到相同 HTML 字节。原版晚间仍有 15 个缺上游项，两份盘前、盘中回执在原版规则下均为 `UNKNOWN`。 |
| 2026-11-27 | 官方 G4 完整下载在 18:01:56 BJT 验证，当日原版 Top200 200 条，5,569 条可排名，6 条留空。 | 同日完整权息、已验前序分片、日更/PAR/109 和选股分组缺证。原版渲染生成当日诊断稿，`CURRENT.json` 引用 11 月 26 日原看板的 stale 视图。 |

- D26 收盘加晚间回执为 `out/replay/runs/20261126_run_3vwyxwrf/RUN_RECEIPT.json`。原渲染 HTML SHA-256 为 `62b363d5c4d6d6c18c410bf9f4c0159453014108c305b105a6cc27074a8f5635`。
- D27 回执为 `out/observed/runs/20261127_run_lva0y7yv/RUN_RECEIPT.json`。最后成功原件 SHA-256 为 `e7091b8a9fb22939e2b860988109c2c2915e045f4a0e6f905aa66f0854d7032d`。带日期和故障说明的 stale 视图 SHA-256 为 `52bdc1e00b0d2be3e92543aca4942592f0a2edfdedacf074984ee7ebbb560021`。
- `view` 只读核验 `CURRENT.json` 的原件、渲染证明和视图 SHA，再返回应显示的 HTML 路径。失败时保留最后成功原字节，另生成带醒目数据日期、尝试日期及转义原因的视图。状态指针原子更换，指针所引证据先落盘。中断的收盘 handoff 不供晚间承接。

## 运行与验证

在隔离工作树的 `candidate` 内运行。D27 的 `MISSING_UPSTREAM` 返回 3。

```sh
PANEL_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python'
"$PANEL_PYTHON" -B route2.py run --date 20261126
"$PANEL_PYTHON" -B route2.py run --date 20261127
"$PANEL_PYTHON" -B route2.py evening --date 20261126
"$PANEL_PYTHON" -B route2.py view --date 20261127
"$PANEL_PYTHON" -B -m unittest -v test_route2
plutil -lint com.lexi.v5.route2.local.draft.plist
```

七项测试覆盖已落盘看板在引导 HTML 缺失后的重放、原件与最新生成快照回退、提交前故障、收盘中断、真实进程锁争用、模拟请求后进程退出与重启、回执核对去重。模拟上传在请求前将 SQLite 状态持久化为 `UNKNOWN_UPLOAD`。回执未知时，同目标同日的相同或变更内容都会保留阻断。当前运行入口保持本机模式，真实上传、未知回执解除和权威远端对账没有启用。

plist 草案的 `ProgramArguments` 采用本机绝对路径，`RunAtLoad` 与 `KeepAlive` 均为 false，没有时钟触发。验证覆盖本机手动重放和语法校验，调度部署、Drive 发布、Dot 接管及自然验收均为 `NOT_RUN`。
