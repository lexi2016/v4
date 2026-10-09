# 独立 Reviewer 入口

请使用不同 agent identity 的 Luna Max Reviewer（read-only），增量审查本目录与同名 ZIP 的实际字节。初次 `REVIEWED_PACKAGE=FAIL` receipt 和报告保留在 `../review/`；不得覆盖或重标该历史结果。本次目标仅是确认 source-preimage 缺口是否以可移植、可复核方式修复，并确认包仍与 frozen PASS scope 一致，没有把设计/Writer receipt 升格为实现或行为验收。

从 E 工作区根执行：

```sh
python3 tools/verify_manager_evidence.py
python3 package/tools/verify_delivery.py --package-root package
python3 package/tools/verify_delivery.py --package-root package --verify-source-provenance
python3 package/tools/verify_delivery.py --package-root package --zip V4_MODULE_RELEASE_ISOLATION_20261009_problem_package.zip
```

逐项检查：

1. 对照 `ORIGINAL_SCOPE.md`、`ARCHITECTURE_RECEIPT.json`、`ARCHITECTURE_HANDOFF.md`、`FACTS_INFERENCES_GAPS.md` 和精简运行图，确认实际事实、推断、CANNOT_CONFIRM 与 DESIGN_ONLY 边界一致。
2. 检查 `ROUTE_CONTRACT.md` 与 `route_contract.json` 包含 6 个 Stage route、当前 17 个 Manager research endpoints、workbench route 和 Manager 只读 stage-selection consumer；默认离线 verifier 应从 ZIP 内 source snapshot 校验 SHA-256、大小、Git blob SHA-1、manifest closure，以及 research/workbench/Stage-selection AST。`--verify-source-provenance` 是额外 Mac 路径检查。
3. 检查 `IMPLEMENTATION_SCOPE.md`、`CHAT_IMPLEMENTATION_PROMPT.md` 与 architect exact file plan 一致，保留唯一 8873/static owner、原算法和 data/state owner、原 release guard、独立锁/rollback、安全 flags；没有实现或发布动作。
4. 检查交叉发布矩阵可证伪，Stage 发布不改变 Manager PID/manifest/source/binding/run，反向同样；离线不 fallback，known route wrong method 405，POST no retry，module rollback 不暴露旧 handler。
5. 检查 package manifest/ZIP SHA、压缩包 inventory、内容字节、source manifest、外部源引用 SHA 与 README command 可重复。确认两个角色 plist 仍为明确 ABSENT，两个并行实现路径均为 `PARALLEL_IMPLEMENTATION_IN_PROGRESS/NOT_BASELINE` 且未打入 ZIP。

输出：`REVIEWED: PASS` 或 `REVIEWED: FAIL`、P0/P1/P2、实际命令结果和具体 findings。单独写 `BEHAVIOR_VERIFIED: CANNOT_CONFIRM`：本批没有隔离实现、测试、集成、服务或自然时段运行，问题包 review 不能替代它们。不要重跑 R3/HK 业务 suites，不触碰业务代码、服务、LaunchAgents、shared state 或 GitHub。
