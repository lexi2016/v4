# G2 日更与历史工作暂存状态

状态：WIP，非部署候选；只包含源码和测试。基线 `e1a042c2abdc975d24531ba21e7695e9c2cb6c82`。G2 成对候选 generation `bfd455c86915918360d9f15c907b72e435b9e46cd8f931db3d6b8f6f7d67ab0b` 为隔离研究结果，未切换全局面板指针。

当前全A自然日更尚不可用：新bar或历史修订缺可认证的完整递推状态，普通路径 fail-closed；只有显式至多三股隔离 canary 允许重算完整前缀。真实 daily pair attestation 和新增股票准入继承、原完成事件接线、publish 前覆盖门、自然运行均 OPEN。旧3股实际工作台与本批隔离计算不是同一部署状态。

针对性校验：使用项目解释器 `/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python` 运行 `-m pytest -q --basetemp=/tmp/panel-g2-daily-isolated-tests-20261102-r3 tests/test_full_research_daily_binding.py tests/test_retained_history_batches.py`，16 passed。真实 G2 同输入 NOOP 只证明0计算/0复制；真实旧 f1b 错误行动规则被拒绝。三股追加及单股合成历史修订只验证来源、旧前缀保留与sidecar继承，实际发生全前缀计算。

历史 owner 隔离批次：5839 范围，5456 新算、101 checkpoint 复用、14 旧历史复用、268 UNKNOWN、0失败；源为 f1b 代，G2 logical 视图继承需使用显式等价证明，不得改称历史源属于G2。

证据目录：`/Users/lexi/Desktop/学习/agents调试/DOT_TO_LOCAL_QWEN_MIGRATION_V1_20261101/kb_panel_upgrade_20261101/panel_bulk_upgrade_20261102_r1/`。工作状态索引 `DAILY_G2_WORK_IN_PROGRESS_R1.json` SHA256 `c7dc47751cef973f16e750c47ad37bb06484fdaa1294a5823b27e0200ba52604`；真实旧行动拒绝回执 `f1b_stale_action_rejection_owner_r1/RECEIPT.json` SHA256 `2813a237d5837c2df0911c86a8da759c3ff29bd04f827e9cfd61852224823514`。上述索引建立后新发现的未变股整段 sidecar 消费和完整 producer attestation 状态仍以当前证据为准。

仅 `RESEARCH_ONLY=true`，`production_allowed=false`，`buy_gate_updated=false`，`orders_sent=false`；不能作交易指令或宣称 PIT。

| 本批文件 | 基线 SHA-256（无则 ABSENT） | 当前 SHA-256 |
| --- | --- | --- |
| `ops/bootstrap_stock_event_history.py` | `301b4eee937c321337559ba43afcdd7b882567da7251faedefa7cea23102a41c` | `f2a76560537c29afd4c078bc6bba98709315ccada95d4caa4ffe3019c19c0690` |
| `ops/kb_action_authority.py` | `235b63f16bfdcedf12e3214a9ba2b0dc4ef2ba93c2a07f80873de4ddc5be63e9` | `0b7a4820a1e387ed4e3496f01d207b20f4f70b423b10f01f8439b3f0d16d583d` |
| `ops/research_panel_daily_product.py` | `c973a2e35d5f781cda21a03ce926519f333afd52198da5984fbe01bf1c905308` | `ae717ec0bcdcf41042af97c1914b82988d9f7a1a58e11eea5c05e1a85cbb18b6` |
| `ops/research_panel_f10.py` | `8c17e7905de4310d65e34589abd62cf32a0cc1a70ed6b3c5048d52707d7f6bd6` | `84f1a3988757775af326c9bc00512b4824c0e8ce4a4f4c8dc739526fb60d4083` |
| `ops/research_panel_qfq.py` | `71c3f6930be705cf97e68fa974470d24503fe49be3e5fa956be053e7a0c3b0e6` | `202480b22797e5f3a10e12a99656e1e96657be7d371f26b36d7cec4d452555ca` |
| `ops/research_panel_action_delta.py` | `ABSENT` | `5623e11a94e6fdfd7643094213e2135d95199fbd2dcc875b3a94fe116efeed03` |
| `ops/research_panel_daily_107_binding.py` | `ABSENT` | `803440cd8d134ae470a4df458ae6b88ac814a9013e492166a1882690ead9fd7e` |
| `ops/run_retained_history_batches.py` | `ABSENT` | `14a4d97122148fad5c5aea55bc200facae2629c6640a2bbaba9a6ef874d3a190` |
| `tests/test_kb_action_authority.py` | `16321223cdc93dafe2d8a9dea04bf5c3a6ecb6a32bbf7e004a9220936ba54ade` | `6c7aac11b0aece5d78547e6736fe6e1ab08961f471aa9852c3c8dcf15147979d` |
| `tests/test_research_panel_f10.py` | `44fd840aabcc47fa8bd1a72d8c814f6a2c80b70806f29c9cd90b70bf7a22d123` | `c367fc6580aed0d40fbc38965a73d6c30411406568ab8268738ada6a36363d43` |
| `tests/test_full_research_daily_binding.py` | `ABSENT` | `f216d3bfb9f69a7b1061feac49848347b436e4cc64b82cfe7cdbc801f253fe8b` |
| `tests/test_research_panel_action_delta.py` | `ABSENT` | `b7de108a562fa719f4e6ab44c3cf2dbc10e10c142071d737ae485cfa8a55d483` |
| `tests/test_retained_history_batches.py` | `ABSENT` | `14aec1248d833d2dfe7a2435a77195fcd5cfdbc79c5110a52ead1780c59effcc` |
