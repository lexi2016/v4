# 给 Chat 的修复请求：R7 真实接口集成失败

请基于本包实际的 7 个源码文件、当前 R7 原始/续接控制文件、官方 `registry_adapter` / `execution_guard_core` / builder / validator，以及真实失败 stdout/terminal，定位并修复真实集成边界。任务目标是形成可由项目 Writer 独立审核、可直接应用的最小补丁，并给出一个后续单命令。

## 真实故障

1. 已应用用户上传的 R7 patch（安装后 13/13 文件 SHA 符合）。第一条真实链命令在 `control_and_runtime_preflight` 退出 2：`RegistryIntegrityError: unsupported event_profile fields: ['candidate_id']`。终态在 `actual_pipeline_failure_01/`。
2. 保留该失败后，第二条真实 resume invocation 在 `input_admission` 退出 2：`INPUT_ADMISSION_RELEASE_BINDING_FILE_IDENTITY_MISMATCH`。该流程在打开目标数据文件前失败；终态在 `actual_pipeline_failure_02/`。
3. 两次真实调用都没有 fit/predict/model-load/truth。后续两次只读 control probe 也分别失败：01 因原 event identity guard，02 当时的源版本漏导入 `PANEL_HEADER_RECOVERY_OUTPUT_PATH`；这些历史错误按当时代码分别记录，不能用后来当前源码倒推说旧探针通过。probe 03 目前只有合同/绑定，`CONTRACT_ONLY_NOT_COUNTED`。

离线 84 项验证通过可作为补充背景，不能代替与当前实际 `OfficialRegistryAdapter`、`ExecutionGuard`、R7 contract/binding/release/grant 做的真实接口预检查。请不要只提交 mock 通过或静态自评。

## 修复边界

- 不修改 R7 route/candidate/grant/execution/action key，也不重置或追加 R7 准入 debit。当前逻辑准入 debit=1 已消耗；保留两次真实失败和 probe 01/02 的原始事件/回执。
- 不改冻结输入、64 列特征、训练标签、模型参数、指标、阈值、sealed truth、source provenance、费用或评估逻辑；不复制或携带 raw arrays、panel data、truth、权重或模型文件。
- 保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。目前 `fit/predict/model-load/truth=0`。
- 只做 target-free 的真实适配器/控制文件预检查；通过必须由实际代码路径、当前控制文件与官方 adapter/builder/validator 共同证明，产出可复核 stdout/terminal/identity receipt。若需更改已绑定文件，请给出精确变更文件、before/after SHA 与完整依赖重绑。

## 交付

请返回：

1. 最小 unified diff/可应用补丁，明确当前源码 SHA 前置条件。
2. 对真实 `OfficialRegistryAdapter` 和当前 resume controls 的 target-free preflight 命令及机器可读结果；不能把 84 项离线测试当成该结果。
3. 预检查独立通过后供 Writer 运行的**一条**后续命令，使用锁定 Python 3.13，并在同一进程按 R7 已授权路径完成准入、一次 fit、完整 predict、不可变 seal 和 seal-bound evaluation。不要在 Chat 环境读取真实数据或启动真实链。
4. 说明每个复用的既有失败/控制回执和需要的SHA重绑定；不得覆盖已有失败产物。

如 target-free 真实预检查未通过，请停在最小可解释阻断点，不给虚假的已修复/训练完成/效果结论。