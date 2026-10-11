# 依赖恢复只读审查

## 结论

`ORIGINAL_COMMITTED_DEPENDENCY_SOURCES_RECOVERED`。通过 GitHub connector 从 `lexi2016/v4` 的固定提交树及其原始 Git blob 找回了满足上传 consumer 接口的 execution_evidence 原版、两种角色的 verified-source HK ensure 原版，以及 HK 历史分钟数据补采原始 runbook。14 个保存 blob 的 Git blob SHA1 与树记录完全匹配，字节数全部一致；另算 SHA256 见下表及 verification_result.json。

原指定 US 提交 `a1b722e4c82defcb9537d5c05915c6a8072c02d3` 本身没有所需新接口闭包：唯一 execution_evidence 原版不含 `research_source_projection` 或 selection_store 参数；三个 ensure 独立原版都没有 `--verified-source-store-root`；完整树无同名 hk_history_backfill.md。

`SINGLE_TOP_LEVEL_RUNTIME_CLOSURE: NOT_FOUND_IN_INSPECTED_REFS`。新 execution_evidence 和两版 ensure 存在于提交内的 handoff 原源目录，未在这些已检查提交的应用顶层找到完整对应模块集合。这不影响精确原字节恢复，但不足以证明某个 Mac release 已装载这些版本。`LOADED_MAC_RUNTIME_IDENTITY: CANNOT_CONFIRM`。本次没有修改 candidate、原附件、控制组或远程仓库，没有部署、运行恢复写入或对外请求补采数据。

## 精确检查范围

| 读取时分支标签 | 固定提交 | recursive tree entries | truncated |
|---|---|---:|---|
| `fixed-us` | `a1b722e4c82defcb9537d5c05915c6a8072c02d3` | 4308 | false |
| `codex/hk-history-backfill-recipes-20261005` | `3ac5233e5928cefef8c1db6896950a1e7cede0cb` | 3 | false |
| `codex/hk-automatic-stages-20261011` | `abb968c99b070da28200ffd3d00fba578fae018d` | 4638 | false |
| `codex/hk-0920-auto-substitute-20261011` | `87853ef6c177f0243667b12b9eae8110c1be0f12` | 4663 | false |
| `codex/hk-dated-name-20261011` | `93b632c2f5e59520f5c1337c3cfe581fc598b4a3` | 4697 | false |

分支名只用于发现，后续树和 blob 均由不可变 SHA 获取。所有五个完整返回树保存在 trees/ 下；本结论不外推未检查的分支、历史提交或 Mac 文件。

## 找回的目标文件

| 文件/角色 | Git blob SHA1 | SHA256 | 字节 |
|---|---|---|---:|
| execution_evidence.py | `3af4fb13f7da60e0822827fb834c671cef16a372` | `1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b` | 25837 |
| ensure_hk_security_master.py / actual_pool_scheduler | `9a538be003e018c9bff1140510ecc34e9bfd9ba3` | `ff03d294128e9fdbe5c319688bea2b8ae1ff1d63afadd51c5a66041e0300321e` | 34014 |
| ensure_hk_security_master.py / canonical_reference | `c24157c7a0185e2bed31b36fdfd9e0d1346ec79a` | `a0f9fd0e2fb438f03109714a41cf3a10b61a85579498e1ceec87126df2d3c319` | 46251 |
| hk_history_backfill.md | `f1e82da005800bb5a9f3b3c4b1c3a61a0939db22` | `d8550ad8016ae6e074f4eaed52a68e6d560f1690b7189d2fff1d80c30cd953a5` | 14245 |

execution_evidence 与两版 ensure 可共同定位在固定提交 `87853ef6c177f0243667b12b9eae8110c1be0f12`（也在已检查的另两个 20261011 HK 提交中出现）。精确路径为：

- `handoff/stage-research-recovery-20261009-r2/after/api/stage_center/execution_evidence.py`。
- `handoff/issue32-stage-autorun-fix-20261009-r1/after/source/actual_pool_scheduler/ops/ensure_hk_security_master.py`。
- `handoff/issue32-stage-autorun-fix-20261009-r1/after/source/canonical_reference/ops/ensure_hk_security_master.py`。

runbook 的固定提交为 `3ac5233e5928cefef8c1db6896950a1e7cede0cb`，路径 `docs/hk_history_backfill.md`。原文完整保存在 blobs/f1e82da005800bb5a9f3b3c4b1c3a61a0939db22/hk_history_backfill.md。它是既有 HK 历史分钟数据补采说明，本身不含 verified-source-store-root 参数文本，也不是新的数据获取授权。

每个目标原文保存在 `blobs/<Git blob SHA1>/<原始文件名>`，没有添加或修改任何 source 行。retrieval_manifest.json 记录每个 blob 在已检查提交中的全部命中路径。

## 与上传 consumer 的配对证据

上传 `active_source/stage_center/consumer.py` 为 37,758 字节，SHA256 `183c0fb9e69fb64f629c965077ae72047c9fcc118f775ce73ad7b7a89e7657fc`，Git blob SHA1 `73a87bae17b933d46ca3036e8253a40d0fc2606d`。它与上述固定 HK 提交顶层 `stage_center/consumer.py` 下载原文逐字节相同。

恢复的 execution_evidence 原版提供：

```python
research_source_projection(source_evidence, trade_date, market)
read_stage_execution(root, trade_date, stage_id, verified_markets,
                     *, selection_store=None, selection_stores=None)
```

同一 handoff 的历史配对 consumer 为 blob `7e434f3935c8dc1ce5de4eca6f99f7719e492a53`；其两处依赖调用与上传 consumer 经 AST 规范化后的调用表达式比较结果为 **True**。具体调用保存在 source_pairing_result.json。此证据确认所恢复模块的接口来源与配对关系，不等于确认整套应用运行行为。

该模块唯一项目级直接导入为 `infrastructure.owned_io.SafeRoot` 和 `.contracts.STAGE_BY_ID`。当前 candidate 的 contracts / owned_io 文件内容在同一固定 HK tree 的 `handoff/stage-research-recovery-20261009-r2/checks/api/support/` 对应路径存在精确 Git blob 匹配。现有完整 92,532 字节 SelectionStore（SHA256 `31e80e068890be03957920870719030463262c78911953541be3074f8650d4c9`）与该 tree 的 `handoff/v4-running-source-20261005/api/stage_center/selection.py` 精确一致。顶层 selection.py 是另一份 31,792 字节实现，不可把该顶层文件视为已验证的完整旧 SelectionStore 替代品。完整 Stage import 和原 SelectionStore 行为的独立审查交由 hk_rebound_review 执行。

## HK ensure 角色与当前前置边界

两版 ensure 均真实定义 `verified_source_store_root` 参数并提供 `--verified-source-store-root` CLI；canonical_reference 还包含 `membership_only` 参数，actual_pool_scheduler 版没有。它们不能仅因同名而互换。

原提交 SOURCE_MANIFEST（blob `72c801a38c89043ac44d9f1453bbc549421f0f02`，已保存原文）记录 actual scheduler ensure 与 actual shared-owner master 的配对，canonical 对应稿必须与匹配的 canonical 前置比较。其 canonical ensure before blob 为 `ec79858502ef793766b71755a037500f0eb2e991`。审查时 candidate ensure 为 `a6c44fc3611df03066792272d939832f7dafe37e`（SHA256 `495ced4f0f06f170606ee576e035dafc99b540cd9fad0a28f2f2a36e5989ddb9`），不是同一 before。因而本审查只交付原源及角色证据，不宣告任一历史 ensure 全文件可直接覆盖 candidate 或 Mac。

原 stage SOURCE_MAP（blob `f984c28f24c86978f31e26e2d8b39b17e70913ff`，已保存原文）也明确标示当时 `current_mac_bytes_verified: false`。本轮没有添加任何实机加载证明。

## 证据文件

- retrieval_manifest.json：仓库、固定 ref、原始路径、blob、保存位置。
- verification_result.json：14 blob 字节数、Git blob SHA1、SHA256、AST 函数签名与 import。
- source_pairing_result.json：上传 consumer 与历史配对调用比较、现有直接依赖的同提交 blob 命中。
- trees/*.json：五个完整 recursive tree 返回。
- blobs/*/*：全部原文，包括被排除的旧接口版本和配对 manifest。
