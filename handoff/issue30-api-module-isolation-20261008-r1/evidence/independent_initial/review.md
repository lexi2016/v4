# Issue #30 独立审查检查点

**结论：CHANGES_REQUESTED。结论仅适用于下面 SHA 冻结的 SOURCE_CANDIDATE。**

已确认并由主控接受修订的 5 项 Important：4 类功能/写入/身份/恢复问题，以及非 delta 目录保留缺口。没有确认的 Critical。现有发布 85、预选池 26、actual 21 个用例分别通过；独立补充验收有 7 次真实失败。这些通过结果不构成源码审查通过，更不构成部署或业务恢复通过。

本检查点用于让原作者修复；所有发现保持 OPEN_ACCEPTED_FOR_REVISION。主控已在进行后续修订，本报告不评价后于以下 SHA 的字节。Reviewer 没有修改候选、原 input 或任何 Mac 服务/业务路径。

## ReviewedSHAs

| 源码文件 | 审查 SHA256 |
| --- | --- |
| `candidate/ops/api_release_integration.py` | `0b9d3b678dc7e875b9514bd8b66b7e8fc69229759c366ef0df776126746180bf` |
| `candidate/ops/build_release_candidate.py` | `2645e7c4923df1d78eeaaf086ce90a01202852c9063a6e0e0f109add3b0f107d` |
| `candidate/ops/prepare_api_only_cutover.py` | `0fee40c13bdb76d8d4d7b5b0068eb8b6e7cade9187a5f3c3154b7d6238a1af4c` |
| `candidate/ops/create_api_module_delta.py` | `04e67a3ce948eecf9dac04083277bd919c7ec8880ec5814bbe57e7a5ba8d0072` |
| `work/cutover_analysis/candidate/api_only_cutover_r2_ready.py` | `931a9e2749adee74ad4b7021b9f7451aaf9c905c586003250adec9cc14a9a364` |
| `work/preselection_scope/after/apps/api/v35_api/app.py` | `5d344dfe902db37f81e06d1d401e9a7e20ae910d8f7647b732ae2b3ba4f019e5` |
| `work/preselection_scope/after/apps/api/v35_api/preselection_router.py` | `718d54a6c6aa8cde2871ce4dc41cbc1d825f199a57b605e4f5ec70d8c4fe19ae` |
| `work/preselection_scope/after/apps/api/v35_api/preselection_service.py` | `ecf1c410e5c4671297d2054e695abe41fd32edd44caa24b2276e8c714108500f` |

输入冻结 commit：`a0a0b88dc133d14ee5763569272c174bcd7cc445`。发布侧另 5 个 ops 是精确历史测试依赖，不代表当前 R2 runtime，也不计作本轮 4 个产品修改；其 SHA 与测试 SHA 在 `initial_release_shas.json`。actual 初次审查在 `frozen_initial/` 保存了 931a… 脚本与 0b9… core，以免作者修订混入已报告结果。

## 已确认问题

### R1 · Important · Git-tracked module additions cannot use the API builder

**位置：** `candidate/ops/api_release_integration.py:731-734`, `candidate/ops/build_release_candidate.py:420-434`, `candidate/ops/release_candidate_sources.py:68-78`

The core requires all additions absent from active to equal explicit_untracked_paths, while the builder rejects any tracked path in that list. A reviewed preselection_service.py that has been git added/committed is rejected both with and without the option. Git tracking state should not invalidate a fully pinned, owned module addition.

**修订目标：** Allow receipt-declared tracked additions; retain explicit approval and exact scope validation for current untracked source files.

**最小复现：** `test_release_review_probes.py::test_committed_reviewed_module_addition_can_be_built`。2 failures: EXACT_UNTRACKED_APPROVAL without option, already tracked with option.

**证据：** `release_probes.log`, `release_probes.xml`, `release_probes_run.json`。状态：OPEN_ACCEPTED_FOR_REVISION。

### R2 · Important · Scheduler staging follows a late candidate config symlink outside the candidate

**位置：** `candidate/ops/build_release_candidate.py:569-571`, `candidate/ops/build_release_candidate_stage.py:181-184`

After render_cutover has safely staged config, replacing candidate/config with a symlink causes the subsequent historical scheduler helper to mkdir/open through it and write com.lexi.v35.scheduler.plist outside the candidate. Final API integration only checks app, and the builder can return success. The historical helper is an active write dependency of this product entrypoint.

**修订目标：** Keep every builder output write anchored to verified candidate directory descriptors and reject an aliased/replaced config before any outside write.

**最小复现：** `test_release_review_probes.py::test_scheduler_staging_cannot_follow_late_config_symlink`。1 failure: outside-config/com.lexi.v35.scheduler.plist exists after the build.

**证据：** `config_escape.log`, `config_escape.xml`, `config_escape_run.json`。状态：OPEN_ACCEPTED_FOR_REVISION。

### R3 · Important · Non-delta directory preservation is not bound by candidate verification

**位置：** `candidate/ops/api_release_integration.py:_inventory_snapshot`, `candidate/ops/api_release_integration.py:_verify_delta_files`, `candidate/ops/api_release_integration.py:_candidate_identity`

Directory modes are copied at build time but omitted from manifest inventory and base-versus-candidate comparison. A post-build chmod of candidate/app/apps/api from 0755 to 0777 passes verification with unchanged files, manifest and receipt. Current-call physical snapshots only establish self-consistency. Empty directory set preservation has the same structural omission; the recorded minimal runtime probe tests mode changes.

**修订目标：** Bind and compare original directory set and mode, including app root and empty directories; allow only clearly scoped new ancestors required by allowed additions.

**最小复现：** `test_release_review_probes.py::test_verifier_rejects_undeclared_directory_mode_change`。1 failure: expected rejection, verify_api_release_candidate returned PASS.

**证据：** `release_probes.log`, `release_probes.xml`, `release_probes_run.json`。状态：OPEN_ACCEPTED_FOR_REVISION。

### R4 · Important · Legacy SHA recovery promotes inconsistent market/code identities as valid A rows

**位置：** `work/preselection_scope/after/apps/api/v35_api/preselection_service.py:316-325`

The newly reachable recovery calls the historical _canonical_a_symbol helper, which can ignore contradictory market or symbol fields. A row with market=US and symbol=A.000020, or market=A plus symbol=HK.00700 and code=000020, is accepted as the only valid A input after another pool SHA failure. Both return PARTIAL_WITH_ROWS and A count 1; the contradictory HK symbol can be rewritten to A.000020. Strict trio SHA does not prove semantic identity consistency.

**修订目标：** Validate every present market/code identity field as a consistent A identity before counting/recovering; quarantine inconsistent inputs, retain the original block if no valid A remains, and preserve all source bytes.

**最小复现：** `test_preselection_review_probes.py::test_sha_recovery_does_not_promote_inconsistent_market_identity`。2 failures: both inconsistent rows promoted; source JSON hashes unchanged.

**证据：** `preselection_identity_probes.log`, `preselection_identity_probes.xml`, `preselection_identity_probes_run.json`。状态：OPEN_ACCEPTED_FOR_REVISION。

### R5 · Important · An interrupted automatic rollback has no protected operator recovery continuation

**位置：** `work/cutover_analysis/candidate/api_only_cutover_r2_ready.py:1570-1578`, `work/cutover_analysis/candidate/api_only_cutover_r2_ready.py:1721-1722`

A simulated candidate bootstrap failure followed by a transient restore rename failure leaves the candidate plist and no loaded service, with an intact original backup. The operation receipt is overwritten as ROLLBACK_INCOMPLETE without the full prepared before/after/integration/base contract. After the transient fault clears, the public rollback entrypoint rejects that receipt because it accepts only successful switches. Execute cannot resume from the candidate pointer either.

**修订目标：** Preserve the prepared transaction and exact original base contract across failures. Provide an explicit guarded continuation for prepared/incomplete operations that still validates the shared lease, receipt, backup, known pointer and known/unloaded runtime; keep unknown identities rejected. Interface details belong to the writer.

**最小复现：** `test_actual_review_probes.py::test_operator_can_resume_after_transient_automatic_restore_failure`。1 failure: API_ONLY_ROLLBACK_RECEIPT_IDENTITY_INVALID after both injected faults are removed; preimage is intact and current pointer is still the known candidate.

**证据：** `actual_recovery_probe.log`, `actual_recovery_probe.xml`, `actual_recovery_probe_run.json`。状态：OPEN_ACCEPTED_FOR_REVISION。

## 独立运行与环境

Python：`/workspace/scratch/25c09a595aec/issue28/references/work/test-venv/bin/python`，3.14.7；Linux 6.18.44 x86_64。每次命令、cwd、环境覆盖、exit code、JUnit 和日志均在对应 `*_run.json`、`.xml`、`.log` 中。测试只用临时合成目录；actual 的 launchctl、loaded state、HTTP 均为测试模拟，绝无真实服务或网络业务调用。

| 运行 | 结果 | 范围 |
| --- | --- | --- |
| `release` | 85 PASS | 当前 active + delta、schema/ownership/mode/lock、builder/prepare |
| `preselection` | 26 PASS；1 条已知 Starlette 弃用警告 | 完整新 router/service、精确 app 注册语句、真实历史支持与合成池；不是完整 R2 create_app |
| `actual` | 21 PASS | SHA 固定 actual/core，合成发布与回滚状态机 |
| `release_probes` | 3 FAIL | 已提交新增文件两种参数用法；目录 mode 漂移 |
| `config_escape` | 1 FAIL | 后续 scheduler 暂存穿越 config symlink |
| `preselection_identity_probes` | 2 FAIL | 未知显式市场与 A/HK 代码冲突被恢复为有效 A |
| `actual_recovery_probe` | 1 FAIL | 暂时恢复故障解除后仍无可用公开续恢复入口 |

Reviewer 自迁移 actual 测试时首次漏带 `probe_cutover_boundaries.py`：20 PASS / 1 FileNotFound；已保存为 `actual_missing_support.*`。复制原探针的精确字节后，完整 21 个实际复跑通过。这个缺件属于审查环境，不列为产品缺陷，不抹去原日志。

原补充探针未改。`checkpoint_probes/` 保存本检查点精确副本；`review.json` 的 `original_probe_sha256` 固定其字节，后续修订应另存结果，不覆盖现有 FAIL。

## DeclinedToJudge

- Any revision after the ReviewedSHAs below. Writers are revising the accepted findings; no item is closed by this checkpoint.
- Complete current R2 runtime identity and 1016-entry app closure: only one exact R2 app.py byte identity and bounded historical supports are available.
- Full R2 create_app startup, real manager announcement/workspace/date-isolation business behavior, real source A=178/HK=100 canary, API/UI reload, and natural-time execution: NOT_RUN.
- Mac launchd, filesystem flags/xattrs semantics and deployed publishers on the user machine: no Mac paths or live services were operated.
- Global retirement/migration of unpublished publisher entrypoints: shared flock coordinates only cooperating migrated publishers.
- Untrusted-code adversaries able to monkeypatch arbitrary interpreter state or ignore publication locks: same-byte pinning and cooperative locking are not an OS sandbox.
- New release/R3 runtime pins and an executable deployment adapter: frozen actual script intentionally retains R2 pins and is not directly usable for a new release.
- The complete shared-file byte preservation proof and final patch/package roundtrip will be checked against the final revision; this checkpoint reviewed extracted implementation and documented proof but does not independently certify full business equivalence.
- Merge, deployment, trade/BUY changes, producer/data repair, and unrelated Issue #28 data/PIT problems: out of scope and not authorized by this review.

## 后续关闭条件

等待作者交付冻结后的 core/builder、预选池 service 与 actual 续恢复修订。以原失败探针和必要已有回归重新执行，核验实际 SHA、pin 接线及 shared app 非目标字节保留。只有定向复验实际通过后才关闭问题；本检查点不自动批准 merge、部署或新运行 pins。
