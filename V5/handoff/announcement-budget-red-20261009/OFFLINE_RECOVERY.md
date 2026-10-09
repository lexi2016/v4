# 真实序列化缺陷：只允许离线恢复

当前入口须同时遵循 RECOVERY_IDENTITY_FIX.md：新增 --source-app 与 --identity-sha256；下列旧命令须补齐这两个参数。原身份不得改写。

基线 874ff9aaf27a7fb24a2d22c066c7c412dafdff2c。父任务报告 Mac 55 PASS 后唯一真实 T20261009/P20261008 run `16cc60afcb089f11690430b05853114c`：392 条目录、21 页；340 正文完整、52 失败；1026 请求、363.5 秒。未知传输消耗后 BLOCKED，未重试或重置。失败分类为身份不匹配 3、页数超限 1、ValueError 1、门禁拒绝 47。capture exit0 仅表示命令返回，产物仍为 PARTIAL。

只读核验确认 batch 为紧凑 JSON，顶层为两空格缩进；值相同，字节 SHA 不同。旧 run 7536 个文件 SHA 保持不变。上述为父任务提供的 Mac 证据，云端没有访问该 Mac、运行测试或新采集。

## 最小修复与原证据保留

原 CLI `_capture` 对 batch 文件 _load 后 _write_exclusive，导致重新编码；原 terminal validator 正确拒绝与权威 batch receipt 不同的 SHA。现在 `_publish_body_batch` 校验 batch 约定文件名、回执 JSON 与两个权威文件 SHA，原样复制 body_corpus、body_corpus_manifest、batch_receipt；原 batch 生产器、原 validator 均未改。后续新采集路径的修复不授权本次重采。

新脚本 `ops/recover_announcement_evidence_offline.py` 只读取已有状态根。必须指定旧 run、预先核实的 transport_policy.json SHA256 和 body_batch/batch_receipt.json SHA256；要求原状态 BLOCKED、原日期和 run 一致。两个 batch 文件须匹配原回执；旧顶层文件须 JSON 值相同、且仍匹配旧 capture_receipt 原 SHA。若不是纯序列化差异即拒绝，不能重新算旧 receipt 掩盖差异。

输出必须是与旧状态根不重叠、全新、不含符号链接的新目录。工具不获取旧状态根写锁、不写旧文件、不删除或替换链接。复制完整原 evidence 树及旧 policy/identity 到 `original/`，逐文件记录并复核 SHA；新 evidence 的三个顶层文件取 batch 原始字节。旧 capture_receipt 保留在 original 中；新 evidence 的 capture_receipt 是显式离线派生回执，记录原回执 SHA、权威 batch SHA、旧 policy SHA、原 run/status 和 network_requests=0。它不是原回执的覆写或重封。

只有原 validate_terminal_body_capture 对新的完整证据副本实际通过，并且源文件及副本再次核对不变，才生成 recovery_receipt.json。PARTIAL、失败条目和原运行标识不变。失败则新目录保留 OFFLINE_RECOVERY.json、无 verified receipt，不删除调查证据。

旧 BLOCKED policy（含历史和预算）逐字复制。新目录及其子目录被 PrivateOwner 拒绝初始化/捕获；脚本没有 provider、重试、刷新或 import 入口，并在 CLI 安装拒绝网络及 subprocess 的审计钩子。不得删除标记、改 identity、换目录发起 capture 或重新生成预算。本工具不是跨任意复制目录的系统级权限隔离器。

## Mac 单次离线验收

提取本次固定 commit 到全新目录；先校验 SHA256SUMS。原 55 项文件未改，新增文件 `tests/test_offline_evidence_recovery.py` 有 7 项候选：精确字节发布及原终态校验、旧序列化缺陷重现与恢复、权威正文篡改拒绝、顶层 JSON 语义差异拒绝、policy SHA 错误拒绝、恢复根/子根禁止 owner 初始化、缺真实 semantic 仍失败。fixture 是本地受控两条 PARTIAL 响应，仅供回归，不会写入真实恢复产物或充当阅读输出。

```bash
shasum -a 256 -c SHA256SUMS || exit 1
python3 -B -I tests/test_offline_evidence_recovery.py > offline-recovery-validation.log 2>&1
RECOVERY_RC=$?
cat offline-recovery-validation.log
printf 'offline_recovery=%s\n' "$RECOVERY_RC"
test "$RECOVERY_RC" -eq 0
```

完整回归仍为独立进程执行原七个测试文件及本文件，合计 62 项；不能把 import 的测试模块视为已执行。云端所有产品测试 NOT_RUN。Mac 新增实际 RED/GREEN 尚待返回。

## 已有真实 run 的离线接续命令

先经 Mac 验收/独立审核。仅组装到新的 APP 路径，不覆盖 874 app 或原状态根：

```bash
python3 -B -I tools/assemble_owner_app.py --out "$RECOVERY_APP"
python3 -B -I "$RECOVERY_APP/ops/recover_announcement_evidence_offline.py" \
  --source-root "$OLD_PRIVATE_STATE" \
  --output-root "$NEW_OFFLINE_RECOVERY" \
  --run-id 16cc60afcb089f11690430b05853114c \
  --policy-sha256 "$READONLY_POLICY_SHA256" \
  --batch-sha256 "$READONLY_BATCH_RECEIPT_SHA256"
```

OLD_PRIVATE_STATE 必须是已有 874 私有状态根，不是 task 输出报告目录。两个 SHA 应由父任务已核实的只读 core-files.json/原文件记录提供，不能填猜测值。新目录中 `recovery_receipt.json` 为结果证据；须核对 article_count=392、340/52 状态分布、原 policy SHA、原始证据 inventory。若原 terminal validator 另报失败，停止并保存异常，不改源、不跳过 validator，也不重采。

## semantic_catalog 与阅读阶段

prepare 缺 semantic_catalog.json 是独立的真实输入缺失，不由字节修复生成。真实 reader 必须逐条覆盖全部 392 条，保留 52 个失败的缺口和来源绑定；340 完整只表示正文抓取完整，不表示已阅读。不得复用旧阅读/审查结果或填 fixture。新的真实 semantic_catalog 放入新离线恢复根，之后只读 prepare：

```bash
python3 -B -I "$RECOVERY_APP/ops/recover_announcement_evidence_offline.py" \
  --prepare-root "$NEW_OFFLINE_RECOVERY" \
  --semantic-catalog "$NEW_OFFLINE_RECOVERY/semantic_catalog.json"
```

该入口先复核恢复证据 SHA，再调用原 _build(reviewed=False)；不生成 semantic、不写产品、不启动网络或导入。未提供文件仍明确失败。独立 reviewer、build-reviewed、registered handoff 与成功 import/readback 均未被本工具完成或授权绕过，须父任务在真实阅读之后另行安排离线/私有 owner 接续。
