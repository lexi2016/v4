# 来源、基线与可应用性

## 固定输入

- GitHub Issue：`lexi2016/v4#30`。
- 问题包 commit：`f615f4edcf4eb57aa6cf9ab407f2c2c2ed329a9b`，目录 `handoff/8873-module-isolation-issue-20261010-r1/`。
- 历史可复用交接：`a0a0b88dc133d14ee5763569272c174bcd7cc445`；原生实际切换参考 `source/actual_cutover_reference/api_only_cutover_r2_ready.py`。
- 本地隔离基线 commit：`d8b69322963d7ec5dfd5838849a0b7593e64f904`。

全部 114 source snapshot bytes 均经 Git blob SHA/大小检查并落在精确输入目录，输入自带 `tools/verify_package.py` 实际通过：120 package artifacts、114 source snapshots、JSON/Python syntax、全文件 SHA。包内 `input/` 是该原始问题包的完整逐字节副本，可独立再运行其原校验器。

## baseline 不是当前 live app

`before/` 由 20 个 canonical snapshot、两份同 fixed commit 的必要原有依赖及一份旧 native reference 组成。`full-after/` 为同样闭包加三个新文件，共 26 文件。它不是 114 快照的混合运行 app，更不以 runtime-B 快照替代当前 active。

两份原包缺失但测试所需的依赖从同 commit 现存目录取得，未修改：

| 文件 | 原仓库路径 | Git blob |
| --- | --- | --- |
| `infrastructure/owned_io.py` | `handoff/v4-running-source-20261005/canonical/infrastructure/owned_io.py` | `1b6666551980c44ebb0b05f133c189909d79c7df` |
| `ops/stage_service_overlay_contract.py` | `handoff/v4-running-source-20261005/canonical/ops/stage_service_overlay_contract.py` | `093eb0d78ff23969ffa0cf5f2a28110063d509ee` |

`interprocess_lock.py` 在这两处快照的 Git blob 一致（`a97e733725834235fbcc9129639ae198fa8770cd`）。复用 Stage helper 仅为旧导入/测试依赖；没有改变其行为或启动 Stage。

## 脱敏字节不能混同原 Mac 字节

输入 README/snapshot_integrity 的文字仍写 10 份/89 处，但当前保留的 SOURCE_MANIFEST entries 实际只有 6 份 byte_identical=false，redaction occurrences 合计 82 处。原输入文字不改，差异记录于 review/input_metadata_discrepancy.json；逐文件 payload SHA 全部匹配。实际这些 `/Users/lexi` 路径被替换成 `/REDACTED_LOCAL_HOME`。本轮基线是实际收到的 `copied_sha256`，而不是宣称拿到了那些 `source_sha256` 的原 Mac bytes。

`CODE_SHA256.json` 同时记录本轮 before/after 和可匹配的输入来源，原始 source/copy 对照完整保留在 `input/SOURCE_MANIFEST.json`。补丁必须应用于精确 before，现场有不同源码或本机绑定就重新读取、生成精确 patch 并复核。不得用忽略 SHA、宽松 fuzz、盲目恢复用户名字符串等手法掩盖差异。

## 交付与校验

`runtime.patch` 和 `native-reference.patch` 合起来只改 7 个文件：3 个既有 ops、1 个新 owner 策略、2 个新增测试和1个历史 publisher reference。其他 19 个闭包文件逐字节保留。`reverse.patch` 是两组源码补丁的联合反向撤销。

`tools/verify_delivery.py` 会检查交付文件集合与 SHA、全部 JSON/Python语法，在全新临时副本运行 `git apply --check`/`git apply`，逐文件比较 full-after，再实际应用 reverse.patch 并逐文件比较 before。验证不会启动任何服务，也不把补丁强行应用到用户代码。

GitHub 同步使用新独立 handoff 分支，不改变 default branch，不 merge、不部署。若 ZIP 内含 `REMOTE_SYNC.json`，它记录已提交源/证据快照与关键文件 readback；该传输收据产生在 remote commit 之后，属于 ZIP 附加包装，不宣称 remote commit 自己包含自身的 SHA。
