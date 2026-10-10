# 8873 模块级发布隔离问题包

**状态：`READY_FOR_REVIEW`。** 本包只为既有 GitHub Issue [#30](https://github.com/lexi2016/v4/issues/30) 补充可复核的当前发布链、源码快照和验收合同；没有实现模块隔离，没有改业务代码、配置、服务或运行数据，也没有发布。用户已暂停选股恢复补丁，选股修复不在本任务范围。

Issue #30 的历史交接 commit 是 `a0a0b88dc133d14ee5763569272c174bcd7cc445`，目录 `handoff/api-module-release-20261008/`。旧交接应作为复用与差异核对输入；其 5 文件/18 测试记录不代表当前真实入口已接线。当前 canonical 工作树中已有 `api_release_integration` 和候选构建/切换计划代码，本包完整收录其相关源码、直接 helper、契约与定向测试，避免另造发布器。

## 当前证据支持什么

主控交接报告 8873 为 PID `67464`、`127.0.0.1:8873`，源目录为 runtime-B 的 `app/`，服务标签 `com.lexi.v35.api-only` 以 `/usr/bin/env KEY=VALUE` 参数形式提供环境。完整环境未收集；Writer 未读写进程、plist、服务或业务数据。当前 release id 被交接为 `hk-three-stage-20261010-r1`，release-manifest 的完整磁盘 SHA 与服务 reload/health readback 未由本包 Writer 复核，故仍 `CANNOT_CONFIRM`。

随包的精确前后快照证明两个被采样的文件版本不一致：canonical runner 与 runtime-B runner 不同，canonical `workspace_plan.py` 与 runtime-B 版本也不同。它证明源码基线存在差异，**不能单独证明当前正在发生覆盖事故**。这一区别记录在 `EVIDENCE.json`。

runtime-B 的完整 `apps/api/v35_api/app.py` 将多个 API router 组装到同一个 FastAPI 应用，并将同一 Vite `dist` 挂载到 `/`。现有 canonical 工作树已有精确 active-base、delta receipt、跨进程锁与 CAS 校验的发布底层，但其 gateway 角色没有业务 `module_id` 路径 allowlist；现有 `stage` 与 `manager` role 是独立 8874/8875 服务角色，不能作为“同一个 8873 内各业务模块独立发布”的验收结果。候选工具能从完整 active app 快照加显式 delta 生成 immutable candidate；cutover 脚本只生成 plist/计划且显式不调用 `launchctl`。真实 8873 候选入口是否使用同一锁/guard、实际服务 reload/health、模块级 reverse-delta 回滚仍需在后续实现任务中验证。

## 包含内容

- `CHAT_TASK.md`：真实 8873 单服务边界、实施问题、验收矩阵和停止规则。
- `MODULE_MAP.json`：当前 runtime-B 实际 route/build seams 与候选 publisher role；未知业务 owner 和 workspace-folder 路由映射明示 `CANNOT_CONFIRM`。
- `PUBLICATION_CHAIN.md`、`EVIDENCE.json`：从 active source 到已读候选机制的证据链和缺口。
- `SOURCE_MANIFEST.json`：所有源快照的源根、用途、完整字节数、SHA-256、工作树/运行版本身份和复制校验；`PACKAGE_SHA256SUMS.txt` 覆盖每个其他包内文件。
- `source/`：canonical publisher/candidate/router 源、runtime-B app/router、生产前端源码及 Vite build inputs。runtime-B 前端 `src/` 下的所有 test/spec 与 fixture 文件均已从包内排除；其中发现的真实 owner observations 与依赖它的 adapter/spec 单独记录在 `SOURCE_MANIFEST.json`。canonical publisher 定向测试保留。保留文件为完整源文件而非摘录；10 个文件中的 89 处 `/Users/lexi` 本机绝对路径已统一替换为 `/REDACTED_LOCAL_HOME`，原 SHA 与包内 SHA 分列于清单。
- `tests/`：canonical 已存在的发布器/代理定向测试。测试依赖完整 V4 checkout 和项目 Python/npm 依赖，没有在本问题包中运行。
- `evidence/`：此前采集的两个 canonical 与两个 runtime-B before 快照。

`apps/web/dist`、`node_modules`、venv、运行 manifest、完整环境变量、认证资料和大型 API body 均未复制。runtime-B 前端 `src/` 下的 test/spec 与 fixture 资料均未纳入包；已发现的真实 owner observation fixture 及其 adapter/spec 也按此范围排除。该排除不修改原始 runtime-B 源。根 Python `pyproject.toml`/`uv.lock` 与前端 `package.json`/`package-lock.json` 纳入，以标明可复跑依赖；测试仍需完整 checkout。

用户在 `助手`、`数据`、`个股`、`牛股学习`、`Z哥方法论` 下的具体工作区目录到 8873 API `module_id` 的一对一归属没有可用代码证据。本包不猜，也不把工作区目录复制进发布源。通过信号是后续实现候选覆盖 `CHAT_TASK.md` 的隔离矩阵并经不同 identity Reviewer 复跑；本问题包本身不构成 `REVIEWED`、`BEHAVIOR_VERIFIED` 或部署。金融标志保持 `RESEARCH_ONLY=true`、`production_allowed=false`、`buy_gate_updated=false`、`orders_sent=false`。
