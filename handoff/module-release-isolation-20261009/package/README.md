# Stage / 经理 API 发布隔离问题包

本包把现有运行耦合证据、唯一 architect 的只读设计、实现参考和可机读的归档验收放在一起，供唯一实现 owner 按冻结边界制作隔离候选并交独立 Reviewer 验收。本包不是并行实施派工。

**状态：问题包已组装；隔离实现、测试、集成、部署和行为验证均未在本批执行。** 架构来源状态为 `DESIGN_ONLY`。本包不表示 Stage 或经理模块已经独立，也不证明某次历史覆盖事故的因果链。首次独立包审查记录仍保留在 `../review/`，其 `REVIEWED_PACKAGE=FAIL` 仅指出当时 ZIP 未包含 source preimages；本次增量把原始字节加入包内并增加离线校验，尚未获得独立复审 PASS。

## 先读

1. `FACTS_INFERENCES_GAPS.md`：证据事实、推断和不能确认项。
2. `ARCHITECTURE_HANDOFF.md`：architect 冻结的目标边界和候选实现计划。
3. `ROUTE_CONTRACT.md`：固定路由 owner，以及从当前经理 router AST 逐项提取的 17 个 research endpoint。
4. `IMPLEMENTATION_SCOPE.md` 与 `ACCEPTANCE_ROLLBACK_MATRIX.md`：逐文件范围、交叉发布验收和回退规则。
5. `CHAT_IMPLEMENTATION_PROMPT.md`：可直接交给 Chat 的实现任务。
6. `REVIEWER_ENTRY.md`：独立 read-only Reviewer 的精确入口、命令和 verdict 边界。
7. `source_manifest.json` 与 `source_snapshot/`：20 个源码/配置 preimage 的精确原始字节、SHA-256、大小及计算所得 Git blob SHA-1。固定 remote/ref 不可确认；`module_proxy.py`、`api_module_contracts.json` 当前处于 `PARALLEL_IMPLEMENTATION_IN_PROGRESS/NOT_BASELINE`，不冻结其工作树字节。

`evidence/` 和 `manager_evidence/` 是包内精简证据；`source_snapshot/` 是可移植 preimage；绝对路径只记录来源 provenance。默认 verifier 检查包内每个 preimage 的 SHA、大小、Git blob SHA-1、闭包和冻结 route AST，不依赖外部 Mac 路径。`--verify-source-provenance` 额外检查外部原始路径；其他机器没有这些路径时，只能确认包内字节，并将外部原件身份标为 `CANNOT_CONFIRM`。

## 验收本包

在问题包工作区根目录执行：

```sh
python3 tools/verify_manager_evidence.py
python3 package/tools/build_delivery_zip.py --package-root package --output V4_MODULE_RELEASE_ISOLATION_20261009_problem_package.zip
python3 package/tools/verify_delivery.py --package-root package --zip V4_MODULE_RELEASE_ISOLATION_20261009_problem_package.zip
```

从 ZIP 解压后可在解压目录运行 `python3 tools/verify_delivery.py --package-root .`；这会离线校验包内证据字节和源码 preimages。`tools/verify_manager_evidence.py` 会读取 manifest 指向的 Mac 原始证据路径，因此只在这些外部路径可用的现场运行。加 `--verify-source-provenance` 可选地复核 source manifest 指向的原始源码路径；其他机器没有这些路径时，外部源码身份保持 `CANNOT_CONFIRM`。

ZIP 的 SHA-256 写入旁边的 `V4_MODULE_RELEASE_ISOLATION_20261009_problem_package.zip.sha256`。`package/package_manifest.json` 列出包内所有非 manifest 文件的精确 SHA。打包器按固定 ZIP 时间戳和排序生成归档，避免把工作区文件时间当版本身份。

## 状态边界

经理 R3 receipt 的 writer-only 离线结果仍为 `66/0`、`36/0`、`18/0`；独立 review pending，共享发布 not run。旧 HK supplement 的 `12/3` failure 保留为 `FAIL_RECORDED`。Stage 本机测试、构建、canary 和部署均 `NOT_RUN`；历史 Linux 287 项测试不能代替本机复跑。详见两侧固定证据和 manifest。
