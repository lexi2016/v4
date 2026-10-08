# HK 三件套候选：Mac 接续验收与真实来源缺口

固定候选提交：`88da6312d3ca1cbe116e87aadb107d7cbd7de2a5`。本次完成 Mac 只读身份检查与隔离测试，没有集成、部署或恢复 `20261008 / STAGE_0930_0935 / HK_CONNECT`。

## 已完成的验收

- Git 固定提交交付目录 160 文件取材，159 项 SOURCE_MANIFEST 校验通过；未收到原 ZIP，不能宣称原 ZIP SHA 已验证。
- Mac ARM64，实际 V4 Python 3.14.6 / pytest 9.1.1。独立 Reviewer 复跑包内固定依赖，两 owner 各 15/15 PASS，无 fail/error/skip。
- 当前 owner 依赖隔离闭包也经独立 Reviewer 复跑，两 owner 各 15/15 PASS。每 owner 17 个当前依赖副本、8 个精确源码切片；30 个克隆文件及 25 个已加载模块身份全部一致。实际 Stage 有 3 项依赖字节区别于包内 supplement，canonical 有 1 项，相关源码快照在 current_dependency_sources/。
- 15 是唯一参数化用例数；跨 owner、依赖范围、Writer 与 Reviewer 的重复执行不累计包装成新增唯一测试数。
- 独立 REVIEWED=PASS，无本次冻结范围 P0/P1/P2；BEHAVIOR_VERIFIED 仅指合成输入下末尾三件套和目录身份检查。完整 Stage runtime 仍 CANNOT_CONFIRM。
- 只读 runtime audit 的 30 个文件均匹配各自冻结前像。两个目标 helper 仍为 `92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735`，候选为 `b20baa18d0ee9748971db835f6fb3dd9a0e1d66aabd8da8d450aee3a4a528a8e`，未复制到现场。

## 当前真正的来源阻塞

SOURCE_GAPS.json 保存本轮只读核对的精确路径与物理 SHA，不含原始行情/股票行。

1. 10/8 上游 0.2 run 的 artifact、manifest、receipt均存在；artifact 为 ce4e9422…，上游 manifest 为0755d987…、receipt为1766e13c…。但100行信号日期与捕获日期均为9/30，使用的TDX面板也仅截至9/30，不能构成要求的10/7评分输入。
2. 本地池 artifact为62d7716c…，本地manifest/receipt为cc476019…/1871468d…。本地三件套完整性与上游source身份是两层，不能把本地hash补进上游字段。上游文件已找到不等于其日期合格。
3. 10/7 close snapshot存在，但缺run/capture及可核验的原始source_input材料；不能代替10/7的TDX Top100评分run。9/30 close snapshot也缺完整独立Connect资格run/capture证据。检查限既有配置来源根，不声称整个磁盘或历史上从不存在。
4. 最新日面板包含10/8数据且于10/8 17:20准备，不能替代10/7截止输入或成为09:30自然槽的证据。
5. 当前receipt仍SETTLED_PARTIAL，1次attempt、retry_exhausted=false，A已有10行、HK无写入且provenance missing。普通replay会跳过，现有特殊rearm不匹配此形状。不得删除或重写receipt/attempt/rearm，也不能覆盖有效A结果。

## 下一步的具体边界

先补齐既有权威链中合格的10/7评分来源三件套、9/30 Connect资格来源和真实capture证明，再由独立验证确认输入。若原时点证据找不回，保持CANNOT_CONFIRM；后补研究只能明确标为历史重建，不能补造成自然/PIT证据。

之后才能为精确Stage owner制定单文件发布/回滚，以及单独的HK-only历史恢复入口。该入口需绑定原失败receipt SHA并保留A已有结果、旧receipt和attempt链；现有代码尚无适用通道，本批未实施。手动/历史恢复永远不能升级为当天09:30自然运行。

本次仅执行用户交回 PROMPT_FOR_MAC 的只读盘点和隔离验收范围，没有服务切换或业务数据修改。此前两项历史P2的Mac38/38与canonical集成状态保留，不因本轮升级为已部署。

## 状态与材料

TESTED / REVIEWED / BEHAVIOR_VERIFIED：仅上述两个隔离范围。
INTEGRATED / DEPLOYED / SLOT_RECOVERED：NOT_RUN。
API/UI/NATURAL_VERIFIED：未完成；真实HK输入和完整Stage运行CANNOT_CONFIRM。
原19项已知基线actual7FAIL/canonical2FAIL本轮未复跑、未解决、未豁免。

writer/MAC_ACCEPTANCE_RECEIPT.json是Writer原始交接，仍保留当时pending Reviewer字样；后续独立结论以reviewer/REVIEW_RECEIPT.md及独立RESULTS/JUnit/imports为准。Writer首次临时wrapper误解析venv symlink导致无pytest、0用例，错误与修正日志保留；没有安装依赖。早期clone-path报告错误记录在Writer回执，独立Reviewer对30文件/25导入重新计算并确认无差异。

writer与reviewer内的run_current_dependency_closure.py是本机验收工具原件，其工作根/输出路径明确固定，复跑需使用新隔离输出，不可覆盖既有证据；两者差异只有OUT。固定候选原源码、patch和完整15项tests在父提交 handoff/issue28-hk-d1-trio-integrity-20261008-r1，无需重复上传。此目录包含本次必要验收脚本、当前依赖差异源码、脱敏身份摘要及独立执行证据，不含原始行情、全量API响应、凭证、配置副本、venv或合成池。

始终保持 production_allowed=false、buy_gate_updated=false、orders_sent=false。
