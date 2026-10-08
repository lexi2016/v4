# 独立审查证据目录

`REPORT.md/json` 记录初次冻结候选的 CHANGES_REQUIRED，`CLOSURE.md/json` 记录对最终精确
SHA 的定向修正验收。两者是两个时点的证据；后者不覆盖前者，也不构成 Mac 部署审批。

`initial_candidate/` 是被审首版源码/测试的只读证据副本，**不能作为本轮最终后像使用**。
实际交付后像只从包根的 `auction/after`、`hk/after`、`release/after` 取得。
原 probe 结果保留，修正后的结果位于 `closure/`。

独立原 probe、命令和路径按其生成时的 `issue28/work/independent_review` 工作布局原样保存，
不是部署入口。此处复制路径不重写历史脚本或日志；原脚本复现时需要按记录恢复该临时布局和
显式 source 环境绑定。可直接从解压包根复跑的191项产品/回归入口见顶层 README 第4节。
`check_patch_replay.py` 同样记录初次冻结候选，最终源码的可移动重放入口是
包根 `verification/replay_patches.py`。

所有行情、来源、capture、plist 和 PASS receipt 都是离线合成 fixture。初次182项通过、
修正后13项定向通过、两个原 probe 及六场景 CLI probe 分别计数，不相加冒充新增测试总数。
现场 owner、完整应用、真实 HK 数据和自然运行的未验收边界见 CLOSURE 的最后一节。
