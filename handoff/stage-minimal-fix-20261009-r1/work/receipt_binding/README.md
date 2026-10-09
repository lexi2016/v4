# Stage 回执最小修复候选

固定输入：`28ab2d35020adf031f10f38c1040514fc81b6d66` 的 `handoff/stage-minimal-flow-20261009`。本分工只改 actual Stage / canonical 的 `runner_receipts.py` 和 `slot_execution.py`，四份后像独立交付，未改 runner facade、采集器、原算法、选股存储、scheduler、API 或业务数据。

## 根因与修复范围

实际 `runner_receipts.py` 原 62–83 行只通过既有 `_atomic_json` 覆盖 `receipt.json`。恢复函数虽保留 `attempt_evidence/preserved-<sha>/PRIOR_RECEIPT.json`，普通未来执行没有真实写入时间与每次不可覆盖的 owner 回执。原 slot payload 只有候选 current/run 和选股 envelope，未把候选三件套的 canonical / 文件字节 SHA 分开留在回执，也未记录已保存 SelectionStore 三件套字节。

候选在同一原 owner、原 receipt_root、原 `attempt_evidence` 下，在覆盖 `receipt.json` 前用既有 SafeRoot `require_absent=True` 保存当前回执正文。生成真实 UTC `recorded_at`，清除传入旧时间和旧自指针；原回执历史不补写、不推断时间。新正文 SHA 放到可变回执的 `receipt_history` 中，读者必须重新读取该相对路径、核原字节 SHA 并与去掉 `receipt_history` 的当前回执比对。

**这是原 owner 写入历史，不能证明独立执行或自然触发。** NATURAL 字样、owner 时钟、自己保存的一份文件、读时算出的 SHA，都不能单独令 `execution_verified` 或 `natural_verified` 成为 true。API reader 仍须保留这一界限。

## 精确修改点

- actual `runner_receipts.py` 81–82：在原 `_atomic_json` / `_deadline.receipt_written` 前收集已验证选股文件身份、保存不可覆盖正文。
- actual `runner_receipts.py` 116–122：恢复仅更新本市场 `input_bindings`、`selection_artifacts`、`selection_binding_errors`；兄弟市场沿原 scope 保留，不重算、不重绑。
- actual `runner_receipts.py` 176 起：UTC 时钟、已有 CandidateInput 身份提取、原 SelectionStore exact run 读回、SafeRoot 历史写入。canonical 添加对应 helper，保留其不同的现有前半段。
- actual `slot_execution.py` 30–43、128–130：每次 `_run_one` 的局部回执闭包保留实际 `runner_invoked_at` 和本次已验证候选引用；全部原回执出口仍走 `self._write_receipt`，不存易串 slot 的 runner 实例缓存。canonical 同样按其独立前像修改。

`SOURCE_MANIFEST.json` 给出四份文件的精确前后 SHA 和实际 owner 路径。两个 `patches/*.patch` 已分别正向应用、逐字节核后像、反向还原并逐字节核前像。

## 与 API reader 协议

顶层 `receipt_history`：

```json
{
  "schema_version": "stage_center.runner.history_ref.v1",
  "relative_path": "20261009/STAGE_0940_0945/attempt_evidence/recorded-<sha256>/RECEIPT.json",
  "sha256": "<正文原始字节 SHA256>"
}
```

正文仍为 `stage_center.runner.receipt.v1`；包含 `recorded_at` 与 `record_time_source=OWNER_WRITE_CLOCK_UTC`。`runner_invoked_at` 来自本次原 runner 函数实际进入时间，`runner_clock_source=OWNER_RUNNER_INVOCATION_UTC`，不是人工 `evaluated_at` 或行情 cutoff。

顶层 `selection_artifacts[market]` 的 schema 为 `stage_center.runner.selection_binding.v1`；字段为：

`run_id, artifact_id, algorithm_sha256, raw_artifact_sha256, selected_rows, artifact_relative, manifest_relative, receipt_relative, artifact_bytes_sha256, manifest_bytes_sha256, receipt_bytes_sha256, manifest_canonical_sha256, receipt_canonical_sha256`。

这里的原 SelectionStore `_verify_run` 返回 `artifact_sha256` 是 CSV 文件字节 SHA，而 `manifest_sha256`、`receipt_sha256` 是 canonical JSON SHA。候选明确保留两种语义，绝不把 canonical 摘要写成文件摘要。额外 SafeRoot 原文件读回要与原 `_verify_run` 的 canonical 身份相同，任一文件在验证后变化则该市场记录 `selection_binding_errors`，不把现存的 10 行计算结果删成 0。

读取 API 只可复用已绑定的原 SelectionStore；不得按回执声明的绝对路径扩张读盘。缺少 store 参数时，声明完整的三件套字段也仍为声明。

顶层 `input_bindings[market]` 的 schema 为 `stage_center.runner.input_binding.v1`：A 保留本次 CandidateInput 的 current 原字节 SHA、run、完整行数、三件套 canonical SHA，以及原 strict v3 已提供的三个文件字节 SHA、commit 与证据列表。legacy 缺文件字节字段则原样缺失。A 缺失时借用的 HK 计划载体绝不冒充 A 三件套。

**HK 仍有一项已识别协议缺口：**所附实际 StageUniverseBinding 只暴露 D1 artifact SHA 和三条 evidence，未暴露原 resolver 验证过的 manifest/receipt 字节身份。候选保留真实绑定及 `trio_status=NOT_EXPOSED_BY_STAGE_UNIVERSE_BINDING`，不以 artifact SHA 同填三项。10/8 资格主表本来缺失，本修复不补出该历史输入。此项须由主控结合实际 owner 的准备链处理，不能据本候选宣称 HK 已就绪。

## 验证与状态

最终候选：**39 passed，0 failed，0 errors，0 skipped**，Linux / Python 3.14.7。命令：

```sh
/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python -m pytest -q stage_minimal/work/receipt_binding/tests
```

31 项首次 helper / SafeRoot / 跨市场保护测试，另 6 项原 slot 分支接线测试，2 项真实历史 deadline `complete_receipt` 调用原 writer 回调的测试。后两项使用可控计时器触发截止降级，验新旧 owner 档案均保留并对应最终落盘回执；不等于真实自然时段验收。

SelectionStore 的测试 seam 只替换原 verifier 的返回值来定向验证新读取、摘要语义及验证后篡改；实际三件套文件读写走未改的 SafeRoot。slot 分支测试注入候选与已验证旧选股，不冒充全链行情/评分测试。39 项不包括 A 算法的独立测试数量。

历史失败保留在 evidence：初始默认 Python 缺 pytest；换既有测试环境后原版两个缺口 RED；最后全目录误收旧 RED 用例导致 `39 passed, 2 failed`，旧 RED 脚本保留为 `evidence/baseline_repro.py`；候选 `pytest.ini` 明确只收集 `test_owner_receipt_binding.py` 和 `test_slot_receipt_wiring.py`，39 项全部通过。旧测试路径曾在两次删除后重新出现，因此最终交付仅纳入这两份候选测试，并保留 RED 复现原件及旧失败日志；不把收集范围问题算产品修复。

`references/INDEX.json` 是固定 GitHub commit 中 10/5 canonical 辅助源码的原字节与角色清单。它们用于定向测试与合同分析，不是完整的 10/9 实际 app。deadline SHA 与 10/5 同 owner Stage 清单一致；实际 10/9 依赖仍需 Mac 重读。

状态：IMPLEMENTED / CANDIDATE_TESTED；独立整包审查由主控安排。MAC_INTEGRATED / DEPLOYED / REAL_API_UI / NATURAL_SLOT 均 NOT_RUN。自然调度时钟、真实行情 cutoff、真实候选输入与原结果仍须在本机分别验收。
