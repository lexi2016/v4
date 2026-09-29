# 经理工作台修复：固定交接入口（2026-09-29）

请先阅读 [给 Chat 的任务书](00_%E7%BB%99Chat%E7%9A%84%E4%BB%BB%E5%8A%A1.md)。本分支用于公告采集、美股映射和清晨计划刷新三项修复。

- [活动 API 源码](sources/active_api/) 与 [活动调度器源码](sources/active_scheduler/) 是修复前像；[隔离 HKEX 候选](sources/isolated_hkex_candidate/) 仅供参考。
- [完整问题包及原始证据](V4_MANAGER_REMAINING_REPAIR_20260929_R1.zip)：3,847,173 字节；SHA256 `40188d9b9d25e70f793dce24948724ada89d0778180ca9822147d4461c5f7f63`。
- GitHub 展开显示源码、测试、配置、任务书和摘要。**完整 API 原件与详细 evidence 在上述 ZIP 内**；下文以及 PACKAGE_MANIFEST 中的路径以 ZIP 内部为准，不表示所有证据都已展开为仓库文件。
- 请在此分支基础上生成修复分支/补丁，保留 SOURCE_PINS 的 before 身份，返回完整 after、测试、采用和回退步骤。此分支不是全量 V4 工程，也不是已修复或已部署版本。
- 仓库保持私有；main 和本机活动服务不受本次上传影响。

---

# V4 Manager remaining repair input package

This package contains exact active API and scheduler source contexts, selected existing tests and receipts, one current full API observation, original stored research source payloads referenced by representative US relation-audit rows, and a copy-ready Chat task. The task asks for three exact-baseline repairs plus a complete `after/` tree containing every changed/added runtime, scheduler, config, test, and fixture file.

Chat's work phase is offline: no network requests, no probe execution, and no active runtime/config changes. The requested `LOCAL_ACCEPTANCE.md` must separately describe a future bounded local path using a newly selected, verifiably nonempty official announcement: original owner → original store → current API/consumer readback → independent review → only then daily announcement scheduling enablement, with rollback. Historical same-input empty requests must not be repeated without new evidence; a missing fresh positive input is `CANNOT_CONFIRM`, not a permanent prohibition on local network acceptance.

`SOURCE_PINS.json` distinguishes active release source, isolated HKEX candidate, canonical repository tests, historical receipts, and original research payloads. `PACKAGE_MANIFEST.json` hashes the archive contents. The two root `.raw.json` files are complete raw GET response bodies; request/time/status/byte count/SHA are in sibling `.request.json` files.

The HKEX evidence records historical genuine empty official results and no accepted nonempty body. This describes the captured evidence only; future acceptance needs a new bounded input with a verifiable nonempty official announcement. Do not run historical bundled tools or repeat an unchanged empty query.

This is a source/problem handoff only. It does not claim source repair, integration, deployment, runtime activation, browser acceptance, or natural-time behavior. Research flags remain `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
