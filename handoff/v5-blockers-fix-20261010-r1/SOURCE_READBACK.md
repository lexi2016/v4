# 输入来源及可验证范围

固定交接 commit：`46081f5bcfb5f0c9e63aaa8b2b7baf65ae191eff`。三个源代码根按原 commit 分别取得，没有把其中一个根覆盖成另一个版本。

| 源代码 | commit | 原仓库路径 |
|---|---|---|
| 经理与每日接线 | `3d9541aca3e5d28e94109609940503cca239b9fe` | `V5` |
| 超跌身份 | `ebe5944ecfbec2f6a161793d7c11946dea063e57` | `V5` |
| 公告 revision owner | `e06d143e881c66c22053a5c594b9c0be21d5be34` | `V5/handoff/announcement-budget-red-20261009` |

原 ZIP 的工具二进制读取未成功，因此没有声称下载、解压或核验完整 ZIP。改用已取得的 ZIP 文件/SHA 索引，在上述固定源 commit 按路径取回源码，并验证 Git blob 与 SHA256。

- 实取 **1177 个源路径、403 个唯一 Git blob**。
- **1173 个路径**与公开的 ZIP SHA256 索引一致。
- **全部 1076 个 Python 源路径**的字节与 ZIP 索引一致。
- 4 个差异仅为两个源根的 `contracts/review_readback_source_manifest.json`，以及 e06d 的 `REVIEW_FIX.md`、`SOURCE_MANIFEST.json`：本轮取得原 commit 文件，ZIP 索引对应脱敏版。它们不在运行时代码修复范围。
- 原 ZIP 之外不可读取的私有 traceback、原 reviewer 返回及其他 Mac 私有证据没有冒称已经检查；本轮诊断以实际取得的冻结源码及新鲜复现为依据。

[完整逐路径证明](evidence/SOURCE_FETCH_VERIFICATION.json) · [摘要](evidence/SOURCE_SUMMARY.json) · [前后 SHA 清单](CHANGE_MANIFEST.json)。
