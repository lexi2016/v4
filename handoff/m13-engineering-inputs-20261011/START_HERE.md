# 原 M13 工程源码、测试依赖与精确装配

2026-10-11。此次 GitHub 交付仅包含 4 个原 M13 工程输入 ZIP 及装配/缺件文档，保留原文件名和原字节。共享 M13/M14/M18 现场诊断原件未上传，也未拆分或摘取其中的私人操作记录。原 M13 会话此前已有该历史附件；本 GitHub 交付不宣称真实故障证据或真实 owner 输入全部齐备。

## 已经齐全的工程材料

- 固定 `f7cb731c384ee6890a87d16c19a5b5a621779477` 的 M13 SOURCE。
- 原 e06d revision 合成 fixture 与原 1a699a0 offline 合成 fixture，两个版本保持独立。
- 只读 consumer/identity 补件。`overlay/V5/vendor/manager_plan_baseline/contracts/stages.py` 已包含：2036 bytes，SHA-256 `d0ac1771a1005888e53e9a322da65f959cfbcbcc665357b8783d5eb4eda9c6df`。
- 正确装配后，18 个原 SOURCE 文件 + 93 个 overlay 文件组成 111 件消费闭包；原 SOURCE 121 个文件保持原字节，独立装配树共 214 个文件。路径、长度、SHA-256、Git blob 全部静态核验。

## 立即使用

1. 完整下载本目录，包括 `packages/` 的 4 个 ZIP，别只下载本页。
2. 阅读 [ASSEMBLY.md](ASSEMBLY.md)、[MANIFEST.json](MANIFEST.json)、[MISSING_REAL_INPUTS.md](MISSING_REAL_INPUTS.md)。
3. 在本目录执行 `python3 verify_and_assemble.py`，只核材料。
4. 执行 `python3 verify_and_assemble.py --destination /绝对路径/新的M13材料目录`。目的目录必须不存在。它安全解压并把 consumer overlay 并入同一 SOURCE 树，两个 fixture 另置独立目录；不导入或执行产品。
5. 按 ASSEMBLY.md 设置两个不同 fixture 变量，在原项目支持的授权测试环境中执行 22 项合成工程分组，并交完整日志。不要再次因漏复制 overlay 或漏设变量把已有文件报缺。

## 原包身份

| 用途 | 原包 | 字节 | ZIP 文件数 |
|---|---|---:|---:|
| M13 SOURCE | [v5-module13-source-20261010.zip](packages/v5-module13-source-20261010.zip) | 692912 | 121 |
| e06d revision fixture | [V5_M13_ORIGINAL_REVISION_FIXTURE_SUPPLEMENT_20261010.zip](packages/V5_M13_ORIGINAL_REVISION_FIXTURE_SUPPLEMENT_20261010.zip) | 256125 | 48 |
| 只读消费依赖 | [V5_M13_READONLY_CONSUMER_TEST_DEPS_20261010.zip](packages/V5_M13_READONLY_CONSUMER_TEST_DEPS_20261010.zip) | 481846 | 96 |
| 1a699a0 offline fixture | [V5_M13_ORIGINAL_OFFLINE_FIXTURE_SUPPLEMENT_20261010.zip](packages/V5_M13_ORIGINAL_OFFLINE_FIXTURE_SUPPLEMENT_20261010.zip) | 218143 | 36 |

4 个 ZIP 共 301 成员，已核 CRC 与逐件 SHA-256。包 SHA 见 MANIFEST.json，完整成员身份见 [ZIP_MEMBERS.json](verification/ZIP_MEMBERS.json)，交接文件 SHA 见 SHA256SUMS。

## 真正仍缺与执行边界

今天是 2026-10-11：target_date=20261012 是下一个预选目标日，publication_date=20261009 是已经过去的来源公告日。应复用原 cutoff 前已公开的真实原始输入运行原 owner，生成面向 12 日的预选输出；不要求未来 12 日公告或行情，也不能把尚未生成的 analysis/review/decision/import/publication 输出当作用户必须先提供的输入。当前必要原始输入的完整性仍需按原合同核对；旧真实回归的 08/07 REQUEST_PATH 与 758 件原件已由既有 Mac 任务找到并另包独立核验，本工程 commit 不包含该真实输入包，其交付另行记账。须在既有 Mac 工作范围依原 schema 核取原件，不按数字或目录形状造数据，不把有限范围未取得说成整机不存在。

原 `_request` 恰好六键是 target_date、publication_date、manager_root、materials_root、manager_files、material_files，详见 MISSING_REAL_INPUTS.md。不是 source_identity / run_identity / cutoff 的猜测结构。旧真实 20 项和现有材料足够覆盖的 22 项合成工程分组分开，不互相冒充；旧 08/07 输出也不能直接改标为 12 日预选。

本次仅静态核验与源码装配，产品/pytest/fixture/Mac/API/UI/自然运行全部 NOT_RUN。M13 如遇实际源码失败，再按精确 before 做最小修复，交完整 after、正反 diff、SHA 与日志。保留已正确 Reader、独立 Reviewer、PIT、同 SHA 拒绝；无需改的文件给合同证据，不制造空 patch。

consumer、M18、共享 gateway/发布/前端及其他模块文件只是既有测试的只读依赖。不改 main、V4、生产、PIN、frozen owner；不交易、不扩大权限或凭据访问。历史 392 成果保留原身份，不能顶替 10/12。此次也不包含 M18 大包。
