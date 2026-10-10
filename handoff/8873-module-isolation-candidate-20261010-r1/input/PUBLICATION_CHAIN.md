# 8873 发布链：已读源码与未闭环调用点

## 1. 当前服务的 app 组合与静态入口（runtime-B 源快照）

父任务报告当前 PID `67464`、127.0.0.1:8873、release `hk-three-stage-20261010-r1`，源码根为 `source/runtime-B-release/app/` 对应的 B app 根。Writer 没有读取进程/LaunchAgent，也未核验 full release-manifest SHA；运行身份的此部分来自主控交接，具体 receipt 见 `EVIDENCE.json`。

该 runtime app 的 `apps/api/v35_api/run.py` 调 `create_app`；`app.py` 单点导入和注册 preselection、manager research/workbench、research lane、runtime/runtime graph、review、research、baimao 等 router，再把 `apps/web/dist` 的 `_RevalidatingStaticFiles` 挂到 `/`。这是一个 gateway 进程的共享路由/静态整合面。Source snapshot 里完整保留 `app.py` 和直接 registered router files，便于 Chat 读取真实组合，而不把整个 release 或 `dist` 带进包。

Vite `apps/web/vite.config.ts` 声明三个输入 HTML：根入口、`daily-research-command/index.html`、`manager-selection/index.html`；默认构建到共享 `dist`。`release_candidate_sources.copy_dist` 会复制整个 `dist` 树。前端源码/build inputs 已从 B release 完整快照到 `source/runtime-B-release/app/apps/web/`，不含 `dist` 与 `node_modules`。因此当前静态 artifact 是全站共用边界，模块源码 delta 不能静默带回旧 dist。

## 2. canonical 工作树里的可复用候选发布底层

以下代码来自 dirty/untracked canonical working tree，不代表 HEAD、运行中的 B release 或远端已部署版本；逐文件 provenance/SHA 在 `SOURCE_MANIFEST.json`。当前 B app 快照不存在这些 publisher modules。

- `ops/build_release_candidate.py::build_module_candidate` 验证 role、candidate 目录和 receipt 边界，并调用 `api_release_integration.build_integrated_app` 从 active release 建完整 app snapshot，再应用显式 SHA-pinned delta；写 `candidate_status=READY_FOR_REVIEW`，且 `launchctl_called=false`。
- `ops/api_release_integration.py::read_active_release` 读取 plist/release-manifest/inventory identity；`build_integrated_app` 校验 delta receipt 并应用 delta；`_verify_delta_files`/`verify_api_release_candidate` 比对目标 delta 与 non-delta inventory，校验当时 current active 是否仍与 base identity 一致。`shared_api_release_lock` 委托 `infrastructure.interprocess_lock.owned_interprocess_lock`。
- 这个是可复用的 exact-base/explicit-delta/lock/CAS/non-delta preserve 底层。其现存 gateway role 只约束 service role；正常 gateway delta 未被业务 module path allowlist 约束，candidate receipt 的 `module_role` 不等于独立用户业务 `module_id`。必须在已复核真实 8873入口内补 module ownership 和 shared path冲突语义，不能把低层机制的存在写成业务模块已隔离。
- `ops/prepare_api_only_cutover.py::render_module_cutover` / `render_cutover` 和 builder 只生成 staged plist 与 cutover plan。源码明确 `launchctl_called=false`，无 live install/reload。模块 role contract 的 stage、manager 目标分别是 8874/8875；这拓扑不是 8873 内模块独立发布的答案。
- `tools/prepare_api_module_candidates.py::prepare` 是候选制备脚本，架构审阅发现使用本机绝对路径；将其作为待适配入口证据，不将其直接声称为可移植或已接线。

## 3. 尚未证明的发布/回滚阶段

本包收录到的 canonical 代码能够准备并验证 candidate/cutover plan，但 builder/cutover 文件头与 `launchctl_called=false` 明确表明它们不执行服务切换。Writer 未找到/未核实当前 B service 实际调用它们的入口。因此以下均保持 `CANNOT_CONFIRM`，不填造部署步骤：

1. 真实 8873 candidate command 或调用 adapter 是否消费这些 canonical helpers；
2. 正式 plist/pointer 原子替换命令、失败时当前服务连续性和 live health readback；
3. 模块级 reverse-delta rollback 与后续模块保留；现有 plan 的 role-local plist rollback不证明 same-gateway module rollback；
4. module-level frontend build/output manifest owner 和 build id 与 current `/` mounted dist 的 readback；
5. 运行态 owner state roots、source/data 互不写回证明。

下游实现从只读新抓的 active identity 开始，找准确调用命令/adapter及 cutover receipt；不使用旧 snapshot 覆盖 live base。测试只证明 isolated simulation；公开/生产服务切换须另行授权。

## 4. 可复用测试及缺少的验收

包内完整复制当前工作树的 `tests/test_api_release_integration.py`、`tests/test_api_module_release.py`、`tests/test_api_module_proxy.py`。前两者覆盖部分 release base/delta/role mechanism；proxy tests 测候选应用代理。它们不验证用户所需五模块 allowlist、同一 8873 入口接线、shared static 保持、并行候选安全、反向 delta rollback 或 live service behavior。Chat 必须新增 `CHAT_TASK.md` 所列合成隔离集成测试，且在完整 V4 checkout+对应 Python/npm deps 环境执行。
