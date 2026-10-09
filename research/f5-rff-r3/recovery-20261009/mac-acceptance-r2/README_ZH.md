# Issue #33 R2 本机新绑定阻断反馈

## 发现

Issue #33 的 R2 receipt-pin 修复本身已通过固定范围验收：独立 Reviewer 对 38 项合同测试和 CLI help 均判 PASS，P0/P1/P2 均为 0。R2 metadata-only prepare 也只执行了一次，成功生成新的 unsigned spec/binding。

随后对这两份实际新绑定的独立审查发现 1 个 P1：冻结 evaluator 的包依赖闭包不完整。settings.py 导入同包 common.py、features.py，并读取 config/base_features.json、config/contract.json；当前 binding 的七个 executable helpers 中没有这些依赖。rff_saved_eval_worker.py 会拒绝 allowlist 之外的 spike5.* 模块来源，因此 _load_evaluators 在 saved-score evaluation 前会报 UNBOUND_FROZEN_PACKAGE_DEPENDENCY。Runner 会在启动被监控 worker 前持久化 RUN_STARTED，所以必须在任何启动事件前解决并独立验证依赖闭包。

这不是 R2 的 start/terminal receipt SHA pin 修复仍失败。R2 测试和实际 metadata prepare 均通过；阻断发生在实际生成的 binding 的 evaluator 依赖闭包审查。

## 证据与状态

- 固定来源：lexi2016/v4@4be3c657c04cb3431d19a83cf584bdb2a0481dac，R1 base=3764032a16f3cd9db88ec0dca122fd5d01c167b。
- R2 contracts source SHA256=e41ab4b41c8386875b14515e34c7609e108db17b538ed43eebe7f76fc3394ba6（生产 delta +11/-2）；contract tests SHA256=95b1baa54699bd6a791f03f67a9f1f54acc98866783c16db0077ef8b429db4b6。
- 独立合成验收：38/38 tests、CLI help 均 PASS。
- 本机 prepare：唯一一次，exit 0；status=PREPARED_UNSIGNED_REQUIRES_LOCAL_REVIEW_AND_PARENT_RELEASE。
- 实际新 RUN_SPEC SHA256=53db55d73b305d9bafa0af6d60b9d216a668aefdc329901f528013962f079a50；INPUT_BINDING SHA256=1231b165213786c451f66a83fd52ff01f03077ce0f684905427702eadfd8feed。
- 后续独立绑定审查收据 SHA256=9910e624dfe8635766a3b31731d014df5bbbd5443b5f755d88bd52bb47ab49cd，结论=BLOCKED_P1，P0/P1/P2=0/1/0。
- Mac RSS 后端 smoke=PASS_MAC_RSS_BACKEND_SMOKE，仅为软件资源监控后端检查，不是 evaluator 或研究评价通过。
- 未发 parent release；本次新 execution 未启动，未 append registry，fit/predict/model load 均为 0，score/Top3/truth/label 行未读取。

## 依赖身份边界

包内附带了按新配置所指向的现有 frozen evaluator package 读取的当前源码/JSON 配置快照，供复现路径和依赖关系。settings.py 当前 SHA 被本次新 binding 记录；common.py、features.py、两个 JSON 配置没有出现在该 binding 中。它们的历史冻结 SHA 保持 CANNOT_CONFIRM。随包的当前 SHA 只标识本地证据副本，不能冒充历史 pin。

## 最小修复要求

从现有 producer/evaluator 包恢复完整、可追溯的传递依赖闭包，把每个依赖的路径与历史可证 SHA 绑定到新的输入合同，并在 RUN_STARTED 前验证路径、SHA 和允许的 module origin。若历史身份材料缺失，应保留 CANNOT_CONFIRM 并先恢复原 producer 证据。

不要删掉或泛化 worker allowlist，不要造简化 settings.py 或第二 evaluator，不要改变指标、门槛、标签、TopN 或真值。

## 附件

FEEDBACK.json 是机器反馈正文；PACKAGE_MANIFEST.json 与 SHA256SUMS.txt 列出附件摘要；完整证据由 ZIP 提供。此包只写入本地，尚未提交 Issue。
