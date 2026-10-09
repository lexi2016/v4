# Manager 三通道接入修复包

本包给 Chat 阅读和提出最小接入修复。主目标是复用已经存在的 owner 输出和 R2 workbench reader/consumer，定位现有数据在 producer → artifact → reader → plan → GET readback 链路的断点。请 Chat 直接用包内代码作为固定 R2 候选参照；Mac 侧负责把修复落到本地源码后接入真实输入、运行 owner 并做 app-wired 复验。这里没有附原始市场行、owner state、凭证、截图、dist 或 node_modules。

关键材料：

- DAY_RUN_REUSE_AND_INTEGRATION.md：单日 owner 调用、产品字段、消费者接口、2026-09-30 / 2026-10-07 / 2026-10-09 证据差异，以及 Chat/Mac 分工。
- FOUR_ISSUE_MATRIX.md：四个冻结问题、现有 owner、最小接受条件和安全边界。
- CHAT_REPAIR_REQUEST.md：可直接复制给 Chat 的工作说明。
- SOURCE_SNAPSHOT_MANIFEST.json：每个 source/test 快照的原始路径和 SHA-256。
- evidence/：只保留元数据投影，不含原始股票列表或市场 payload。
- code/：固定 R2 修复目标、2026-09-30 R3 参考源码、2026-10-07 announcement consumer 源码，以及 2026-10-09 实际 owner runner/checker。
- 工具目录中的 synthetic contract fixture 只是离线接口契约 smoke，不是市场数据、不构成产品成功结果。

本包构建验证：IMPLEMENTED=package；从 ZIP 解压根目录（包含 `package/` 的目录）运行 `python3 package/tools/contract_smoke.py` 已 PASS（仅 synthetic fail-closed envelope）。R2 app-wired 10/09 exact-input read 仍是 0 stocks、三个通道 CANNOT_CONFIRM、plan STALE_INPUTS_CHANGED；这些零行不是 VALID_EMPTY，也不能称作完整选股。API/UI/NATURAL 和修复后的真实输入集成均 CANNOT_CONFIRM。
