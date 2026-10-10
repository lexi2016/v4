# 架构与明确的设计边界

## 复用位置

现有 `ops/api_release_integration.py` 仍拥有完整 inventory、exact base、delta proof、跨进程锁和候选验证。新 `ops/api_business_modules.py` 只做纯策略校验，没有文件写入、服务控制、另一个锁或另一个 publisher。`ops/build_release_candidate.py` 在原入口增加 `--api-module-id`，`prepare_api_only_cutover.py` 复用原 plist rewrite，只在同一 gateway 内准备候选。

`gateway/stage/manager` 仍是 service role；业务 `module_id` 必须是另一个字段。本次不更改 Stage/manager role 的旧断言或契约，不启用这些服务。

## 权威、基线和候选

active plist 通过 `V35_API_MODULE_OWNERSHIP_PATH` 与 `V35_API_MODULE_OWNERSHIP_SHA256` 绑定外部契约。解析要求 schema、APPROVED 状态、非空 approval_id、精确文件路径、每路径唯一 owner、完整声明的 dependency graph、精确 method/path 路由、UNCHANGED state compatibility，以及显式 protected_external_roots。状态/批准信息由外部受信配置表达；字符串本身不是独立审核证明。谁有权写 active 配置、批准内容是否完整，属于另行现场审核边界。

未知 module、缺契约、契约 SHA 改变、重复 JSON key、重复/祖先重叠路径、glob、路由冲突、依赖环、未知依赖均拒绝。普通业务模式还硬性拒绝 gateway 组合点、ops/infrastructure/deployment、公共 contracts/config、整个 apps/web；即使契约写为某模块所有也不会自动解锁共享面。

构建时，原跨进程锁覆盖 active 身份读取、完整 app copy、delta 校验、manifest 和 plist plan 生成。每份 receipt 绑定 base release id/path、manifest SHA、完整 inventory digest、generation、业务 module/owner contract SHA 和逐文件 before/after/diff proof。候选不能静默 rebase。对当前源边界含 state/运行产物/venv/隐式 symlink 的业务快照，保守拒绝，须先独立确认和整理源边界。

普通共享锁能协调使用该锁的发布者；不宣称能防止拥有文件系统写权限、故意绕过所有约定的外部进程篡改 live 文件。

## 为什么完整快照仍能独立发布

完整快照是既有启动模型的工件形式。A 修改只影响 A 的精确 delta；B 的基线是 A 发布之后的整个 active 快照。因此 B 自动带着 A 的最新文件，不从 B 旧工作目录复制整个应用。non-delta 完整 inventory（包含文件 mode）在构建和提交验证时再次比较；静态目录也完整参加该比较。

同 G 的两个候选即使由两个进程分别持有，第二个提交仍会因当前 base 与声明 base 不一致而拒绝。重建必须由调用者明确执行，并生成新的 receipt/manifest；不会将旧审批自动转到新基线。

## Reverse delta 与保留链

`prepare_module_rollback` 在当前 gateway 锁内读取 current、目标发布和保留的父链，验证目标确是祖先且属于 forward 模块发布。它按目标父版本的实际 bytes/mode 生成 reverse delta，并绑定当前 base/generation。A 当次新增的文件以严格声明的删除表示；普通 forward 删除仍拒绝。

若目标之后存在同模块更新或依赖它的后续模块，目标当前字节不再等于其 after image，契约/launch binding 变更，或链上证据缺失/损坏，就拒绝。再次构建/提交 reverse 候选时会独立重算反向配方，调用者不能把 arbitrary bytes 包装为 rollback。

为保护所有 retained immutable releases，输出边界会验证当前记录的完整父链。**必须保留这条链的源码、manifest 和 delta receipts；缺失/损坏历史会阻止进一步业务构建/回滚。** 本候选没有实现链压缩、归档恢复或垃圾回收审批。

## 写入边界

同一保护函数用于 candidate、build/failure receipt、reverse source 输出。保护目录包括 active LaunchAgents 目录、所有保留 release、外部契约文件、契约显式 protected_external_roots，以及两种 plist 环境声明中的全部绝对路径值。相对 ROOT/PATH/FILE 绑定拒绝。两处同名值均受保护，不静默覆盖其中之一。success receipt 必须位于 candidate 之外，有已存在的 exact parent。直接 plan renderer 也会在写 staged config 前拒绝 symlink/alias。

保护已声明的绝对路径不能证明所有动态消费者都已枚举：CLI 根、默认 home 目录、嵌套 bindings、产物内 locator 仍需 owner 审核补齐。完整源码缺失时不能批准真实模块；外部根列表为空仅表示审核者明确声明无额外根，不能由助手自行据此推断。

## 历史原生入口和失败恢复

`publisher_reference/api_only_cutover_r2_ready.py` 是任务提供的历史实际入口参考。改动接到其真实 `_locked`、`_run_switch`、preflight、atomic replace 前后和 readback 位置；没有伪造当前 Mac 发布命令。五文件 guard closure 在导入前验证固定 SHA，新的 standalone 调用从已验证 bytes 编译，拒绝异源 module cache/恶意 pyc。它不声称对任意预加载进程中同路径对象的内存字节码做完整证明。

公开 `_run_rollback` 不再回切旧整包；它要求 reverse-delta 走正常候选提交。仅保留失败事务对“紧邻当前前像”的紧急恢复。可证明属于本事务且仍可识别的候选可恢复；已加载但身份不足/不运行的状态仍返回 ROLLBACK_INCOMPLETE，不能在证据不足时强行停止未知进程。

原生参考的 47 个旧部署常量保持不变；旧 pins 阻止它冒充新现场发布。把该静态接线移植到届时真实命令、重新 staging 和审核，仍需现场只读绑定和另行服务动作授权。
