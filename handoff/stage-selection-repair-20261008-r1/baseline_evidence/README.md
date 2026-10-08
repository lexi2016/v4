# 冻结输入与当前运行证据的区别

本轮输入来自 [Issue #28](https://github.com/lexi2016/v4/issues/28) 及固定提交
[`00524e9050fe212f87911b56eea1c2db719dd94b`](https://github.com/lexi2016/v4/tree/00524e9050fe212f87911b56eea1c2db719dd94b/handoff/stage-selection-issues-20261008)。
本目录的 `SOURCE_MANIFEST.json` 为该提交的精确原件；本轮从 GitHub 读回后，
对全部 27 个源码/测试切片核对了字节数、SHA-256 与 Git blob SHA-1，结果见
`BASELINE_VERIFICATION.json`。它们是交接时冻结的证据，不是此刻 Mac 运行代码的读回。

本包仅携带本次修改、重放和隔离测试需要的前像、后像及支持文件；其余冻结输入继续
通过上述固定提交引用。支持文件中的 10/5 历史 canonical 和已修 API 均有独立来源清单，
不能整体复制成当前运行 owner。

原状态观察时间固定为 **2026-10-08 09:50:54 +08:00**。当时 A 09:25 有效来源
171/178、后续三个阶段 172/178；四阶段各有 10 个选择结果且保留 PARTIAL_WITH_ROWS。
HK 四阶段输入验证失败，正式 selected_rows 为 null 且没有 selection run/artifact。
这些数值本次未从 live API 重新采样，不能当作此刻状态。

原始行情、业务完整响应、账户/持仓、Mac 认证信息、完整运行包、解释器/venv 均未纳入
此次代码交付。原失败 receipt、旧业务产物和 NATURAL/RECOVERY 声明未修改。
