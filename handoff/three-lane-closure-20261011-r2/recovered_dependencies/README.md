# 找回原依赖的交付位置

`DEPENDENCY_RECOVERY_REVIEW.md`、retrieval_manifest、verification_result、source_pairing_result 保留 Reviewer 原记录，描述的是其原审阅目录布局。本精简交付不包含五份完整 Git tree 或被排除的旧版本；14 个原 blob 的逐字节校验结果仍完整保留。原报告中的 trees/、blobs/ 路径不是本包中的可执行路径。

本包携带以下必要原字节，未修改文件内容：

| 原 Git blob SHA1 | 原文件/角色 | 本包相对路径 |
|---|---|---|
| `3af4fb13f7da60e0822827fb834c671cef16a372` | Stage API execution_evidence | `stage_api/execution_evidence.py` |
| `9a538be003e018c9bff1140510ecc34e9bfd9ba3` | actual pool scheduler ensure | `actual_pool_scheduler/ensure_hk_security_master.py` |
| `c24157c7a0185e2bed31b36fdfd9e0d1346ec79a` | canonical reference ensure | `canonical_reference/ensure_hk_security_master.py` |
| `f1e82da005800bb5a9f3b3c4b1c3a61a0939db22` | 原 HK 分钟补采说明 | `docs/hk_history_backfill.md` |
| `72c801a38c89043ac44d9f1453bbc549421f0f02` | ensure 原角色/前后镜像清单 | `original_role_evidence/SOURCE_MANIFEST.json` |
| `f984c28f24c86978f31e26e2d8b39b17e70913ff` | Stage 原 source map | `original_role_evidence/SOURCE_MAP.json` |

完整 SHA256、字节数、固定 commit 与原路径见原报告和 verification_result.json；现场如需被排除版本或完整树，可以按 retrieval_manifest 的固定 SHA 从原仓库重取。不要用分支现头代替该固定原版本。

这些文件用于恢复可核对的原接口及角色，均不在自动 changes.patch 内。不能从 Linux 测试组装缺件推断 Mac 同一文件也缺失；先读实际角色、当前源字节与已验收后续修复，再决定恢复/合并。两个 ensure 同名却不同角色，不可互换。原 reader/reference 的副本也出现在 checks/hk_rebound/verified_references，仅用于独立复跑。
