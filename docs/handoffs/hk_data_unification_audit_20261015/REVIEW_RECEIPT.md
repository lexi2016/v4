# 独立审阅历史与最终回执

审阅对象：`REPORT.md`、`SCOPE.md` 及其冻结的 HK 三套数据审计材料。此文件归档独立 Reviewer 的历史反馈和最终最小 receipt；文中不包含本文件自身 SHA。

## 历史失败记录

### 首轮：两个 P2

首轮独立 Reviewer 判定 `FAIL`，提出两项冻结范围内的 P2：

1. B/C 行键并集误写为 `1,038,908`；依行数和交集计算应为 `1,037,908`。
2. 迁移方案没有明确现有 API LaunchAgent 的 manager 根绑定、同一 manifest/run_id/SHA 的 reader receipt 验收及失败时恢复旧配置。

当时最小 receipt 原文：

> `REVIEWED_FAIL_P2 ×2; PASS_READ_ONLY_VERIFY; 8/8 artifacts; migration NOT_RUN; source/PIT/unit/consumer binding CANNOT_CONFIRM.`

后续文档修订已更正并集数，并列出两个 manager 根的旧值、V4 目标、reader receipt 验收和回退条件。

### 第二轮 delta：一个剩余 P2

第二轮独立 Reviewer 确认并集数与 manager 根目标/回退问题已闭环，但指出切换整个 manager shared root 前，仍需明确盘点全部非 HK/A 资产及证券主表的直接和间接依赖，并要求切换后文件等价及消费者输出不变的读回门禁。scheduler plist 完整路径亦待以已核身份补入。

当时最小 receipt 原文：

> `REVIEWED_FAIL_P2_ROOT_DEPENDENCY_GUARD_INCOMPLETE; prior P2 arithmetic and manager-root target/rollback closed; PASS_READ_ONLY_VERIFY reused (8/8); migration NOT_RUN; non-HK/A dependency equivalence CANNOT_CONFIRM.`

## 最终独立复核

最终 Reviewer 核对的文档 SHA-256：

- `REPORT.md`：`b74df7ad1751389f2c069dc95a7e54b8a531300d5e91f0854d82e31dcf0e2b91`
- `SCOPE.md`：`0f48a7a5634e811380f8375030c2e1f8e4170c1d11a3bda78bab2a8daf637c46`

最终复核确认：阶段 0/4 已要求盘点 manager shared root 的完整依赖闭包，逐项登记所有非 HK/A 资产和证券主表的源/目标、SHA 与消费者，并在切换后核验文件等价及消费者输出不变；任一依赖未知即禁止切根，只保留旧根或不接入 manager reader 的隔离 HK 版本，不扩大 A 范围。`V35_RESEARCH_DATA_ROOT` 保持原值；回退记录了两个 manager 根旧值和旧 C `panel_latest.json` 原始字节/指向。B/C 并集 `1,037,908` 正确。

Reviewer 另核 scheduler LaunchAgent 路径 `/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist` 的 SHA-256 为 `317feeec98a924129f7926488b04a634f48fe6db54e53c32273fd5a4e6781e12`，与报告一致。只读复算复用先前独立 `PASS_READ_ONLY_VERIFY` 回执，8/8 产物一致；本次文档 delta 和状态归档均未重跑。

最终最小 receipt 原文：

> `REVIEWED_PASS; audit report REVIEWED; read-only recomputation TESTED (prior independent PASS_READ_ONLY_VERIFY, 8/8); migration NOT_RUN; actual consumer binding, PIT, unit semantics and migration outcomes CANNOT_CONFIRM.`

## 机械状态归档

本 Writer 仅将待审状态更新为最终 receipt 指定状态，并将只读复算状态记为 `TESTED`；没有改数据结论、迁移方案实质、脚本或审计 metadata。核审前与状态归档后的文档 SHA 分开登记：

| 文件 | Reviewer 核审 SHA-256 | 状态归档后 SHA-256 |
|---|---|---|
| `REPORT.md` | `b74df7ad1751389f2c069dc95a7e54b8a531300d5e91f0854d82e31dcf0e2b91` | `f212622c3a75235609f95f1f460bc7f743bffa68bc97be689cbdf5a4fd7ed3dc` |
| `SCOPE.md` | `0f48a7a5634e811380f8375030c2e1f8e4170c1d11a3bda78bab2a8daf637c46` | `391ce3ffd66472a9bab364dcb84ec6b6b1af2e7d174d8e2ed1a6e693301ddc29` |

未变更身份：`recompute_hk_pool_audit.py` SHA-256 `b338c936117b9a48142dc649a30eeb71348c85c4c7fcb1a2bbd8bffdcdf6fbad`；`audit_manifest.json` SHA-256 `eaa3121ddcac50631fe7d55a2870b1fb439bbf58caa18895784412f6ac15d589`。迁移仍为 `NOT_RUN`。真实 consumer 绑定、历史成员资格/PIT、行情来源与单位语义，以及迁移结果继续为 `CANNOT_CONFIRM`。
