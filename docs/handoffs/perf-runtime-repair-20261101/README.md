# Four bounded repairs · 2026-11-01

Status: source behavior implemented and its prior 13-test PASS reused unchanged; revised release helper **7 tests PASS**; real pinned-live preflight and private candidate preparation **PASS**. First independent review failed on helper compatibility and recovery CAS; both defects were revised and await incremental review. Activation, API/UI and natural-run acceptance: **NOT_RUN by Writer**. Controller owns review, integration, authorized activation and GitHub sync.

Frozen scope: fix incorrect candidate root in the next immutable release, date-cache freshness on publication into existing date directories, actual bounded stage-batch deadlines/resource usage, and unsafe rollback instructions. Writer owns only `domains/preselection.py`, the stage-batch timeout changes in `apps/api/v4_api/app.py`, the two existing focused tests, the new release-helper test, this handoff directory, and the external audit report rollback section. Baseline `bbed661f1441239f7a06f093418efb6ceab0c7cc`; branch `codex/perf-runtime-repair-20261101`. No business/data/model/trading changes, live writes, service action, Vibe8910 changes, commit or push by Writer. Stop after focused checks and independent frozen-scope PASS; incompatible inherited bytes, unknown service/listener state or CAS conflict stop activation.

## Source behavior and oracle

- Cache freshness stats the pool root plus eight-digit date directories and their `manifest.json` metadata, at both canonical and configured source roots. This catches the official `PreselectionPoolStore.materialize` publication into a pre-existing `20260820` directory whose parent pool-root mtime remains unchanged. It preserves original SHA verification in the catalog body. It reads no raw pool contents on the warm path. Current roots: 6 + 69 date directories, one metadata pass **0.019871 s**; full API latency after deployment is NOT_RUN.
- A process-wide executor has at most eight active/admitted tasks and no unbounded submission queue. Per-request worker limits, including one worker, use the same deadline. Saturated or timed-out reads return collected summaries using the existing response/safety contract. Running Python threads cannot be forcibly cancelled; at most eight stalled reads retain slots until completion. Repeated requests cannot create additional pools/threads or enqueue more stalled reads. A saturated read can return an incomplete/empty stage map; no empty-map claim of completed selection is added.
- `release_repair.py` derives each reviewed hunk from the frozen Git baseline and current reviewed source, requires exact unique context against pinned live bytes, and preserves inherited SOP/router arguments and every other non-delta file. The actual package uses `module_role=api`, has no `deployment/api_module_contracts.json`, and is incompatible with the newer gateway/stage/manager high-level integration API. The revised helper loads the pinned deployed official `inventory_tree`, `inventory_digest`, `_diff_proof` and `_verify_delta_files` functions and applies task-specific exact plist/manifest/schema/two-delta checks. It preserves `module_role=api`, corrects candidate root/app/release ID, updates inventory plus `app_files`, and replaces the inherited incompatible `api_integration` record with explicit `repair_integration` provenance bound to the original manifest SHA. No existing validator or role contract is modified.
- Before service changes the helper validates candidate inventory and imports the candidate's actual dispatcher/frontend identity readers in a subprocess using the staged plist environment. Activation takes the existing API release lock, compares the exact live plist SHA, unloads once, polls job absence **and** port 8873 absence (20 s bound), atomically replaces the plist and bootstraps once. Readiness checks launchd/listener PID binding, health, safety flags, release/manifest and frontend identities. Bootstrap/readiness failure preserves the error and attempts one safe automatic restoration of the prior exact plist, with the same unload and readiness checks. Recovery checks CAS **before** any second unload and checks again before replacement. An owner change during the first unload stops without a second unload or overwrite. Ambiguous job/listener state or CAS conflict does not trigger blind bootstrap or overwrite.

The rollback target is the exact pre-repair `perf-date-list-20261101` release. It retains its previously observed frontend-root defect; rollback verifies its known dispatcher/runtime identity and safety flags, without claiming its frontend identity is repaired. The original `bak-before-perf-20261101` backup remains untouched. Only the API LaunchAgent is in scope; no scheduler/other service is touched.

## Commands and evidence

Run from the task checkout with:

```bash
PANEL_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python'
TASK_ROOT='/Users/lexi/Desktop/学习/v4_app/.task_worktrees/perf-runtime-repair-20261101'
cd "$TASK_ROOT"
"$PANEL_PYTHON" -B -m pytest -q -p no:cacheprovider --basetemp=/tmp/v4-perf-writer-final-20261101 tests/test_stage_timeline_batch.py tests/test_date_list_performance_contract.py tests/test_perf_runtime_repair_release.py
"$PANEL_PYTHON" -B docs/handoffs/perf-runtime-repair-20261101/release_repair.py check
```

Historical source batch: **18 passed in 0.86 s** (13 source tests plus the first 5 helper tests). Revised helper only: **7 passed in 0.29 s**; the 13 unchanged source tests are reused. The current `check` result is `PINNED_LIVE_PREFLIGHT_PASS` with 1,301 actual deployed entries; `git diff --check` is clean. The source overlay SHA values below are unchanged. Tests cover the exact official publication regression, serial/parallel response deadline, 20 repeated stalled reads and slot recovery, inherited bytes, unload/listener ordering and timeout, CAS rejection, automatic restoration/readiness. Initial test attempt hit unrelated pre-existing pytest garbage-directory EPERM during cleanup and a test-harness recovery assertion against a shutdown executor; the harness was corrected and a task-specific basetemp used. No historical pytest directories were deleted.

The revised helper was authorized to prepare the private candidate after its tests passed. This exact command succeeded once (new private candidate only; **do not rerun against the existing target**):

```bash
"$PANEL_PYTHON" -B "$TASK_ROOT/docs/handoffs/perf-runtime-repair-20261101/release_repair.py" prepare
```

The fixed target is `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/perf-runtime-repair-20261101-r1`. Preparation refuses an existing target; it checks space for twice the active app plus 1 GiB, clones only the current app and overlays reviewed changes. On interruption preserve the partial candidate and error for controller diagnosis; do not rerun blindly. Review `prepared-candidate.json` in this handoff (exact copy of the real `repair-preparation.json`) and its inventory/identity results before activation. Preparation completed with 1,301 entries, 1,299 non-delta entries preserved, exactly two changed paths, candidate dispatcher identity valid and frontend `VERIFIED` (`main-C4Mq08oe.js`). Initial prepared manifest SHA `1c1895521af351118d85e826d8014ad9b9c96e54d5a3dc30a5a51b1a3e61c11f` and initial receipt SHA `ef52beb743621955a666781b215b2df9ac1c86139d06914dff883c9158cbc55b` are superseded by the final metadata correction below; the old receipt remains in `prepared-candidate-before-top-level-fix.json`. Live plist SHA remained `9d4a872d3d0b7f6246f209969f1dbe31a97fc260ecb77d76e8f498326752f908`.

Controller activation command (service change; **NOT_RUN by Writer**):

```bash
"$PANEL_PYTHON" -B "$TASK_ROOT/docs/handoffs/perf-runtime-repair-20261101/release_repair.py" activate
```

Rollback after a successful activation:

```bash
"$PANEL_PYTHON" -B "$TASK_ROOT/docs/handoffs/perf-runtime-repair-20261101/release_repair.py" rollback
```

The helper emits a success receipt only after live validation; any automatic-rollback failure reports both primary and recovery errors. A graceful unload of a process with permanently stalled threads can exceed the bounded wait; the helper stops with the existing plist preserved and requires controller diagnosis. It never sends an unverified bootstrap retry.

`source-receipt.json` freezes source/test/helper SHA and exact targeted command. The real-base overlay check produced:

| Path | Overlaid live SHA-256 |
| --- | --- |
| `apps/api/v4_api/app.py` | `1f51339e55d12e1b544aec227a8288f30a1f60cb0829cdb3e5c4af2c1bb65801` |
| `domains/preselection.py` | `27570df644a7d4b2962c83951dc358d648855e70f5a3100a5133dda5b12ceaea` |

External report changed only its rollback instructions: `/Users/lexi/Desktop/学习/agents调试/v4_code_audit_20261101/PERF_FIX_RESULT.md`.

`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`. PIT, market-data validity and strategy/trading acceptance remain outside this software repair and **CANNOT_CONFIRM**.

## Incremental revision evidence

The first review's P1 was a real preflight failure: high-level integration required a missing role contract and rejected the existing `api` module role. The revised test reads the actual pinned plist/manifest and complete live inventory, without a mocked compatible contract. P2 was an owner conflict during initial unload: the first recovery path performed a second unload before checking ownership. The new regression changes the plist during initial unload, verifies only one unload is called, and preserves the other owner's bytes.

Executed incremental command:

```bash
"$PANEL_PYTHON" -B -m pytest -q -p no:cacheprovider --basetemp=/tmp/v4-perf-helper-revision-20261101 tests/test_perf_runtime_repair_release.py
"$PANEL_PYTHON" -B "$TASK_ROOT/docs/handoffs/perf-runtime-repair-20261101/release_repair.py" check
"$PANEL_PYTHON" -B "$TASK_ROOT/docs/handoffs/perf-runtime-repair-20261101/release_repair.py" prepare
```

No role-contract creation, role renaming, service action, live plist change or source-behavior change occurred during this revision. The lock wrapper uses the already observed V4 API `.com.lexi.v4.api.release.lock` owner path and existing `.mutex` protocol; it does not resolve the incompatible retired V35 gateway contract.

## Final metadata-only identity correction

The third focused review found top-level `release_id`/`app_root` still referring to the prior release even though nested `candidate` fields were correct. This was a real detailed-runtime `release_id_status=DRIFT`. The helper now synchronizes both representations and records the actual current source worktree. `source_commit` is explicitly the frozen baseline; `source_provenance` sets `commit_contains_repair=false`, marks `REVIEWED_UNCOMMITTED_DELTA`, and binds the two reviewed source files by SHA. It does not invent a commit containing the changes.

Two exact regressions passed (**2 passed, 7 deselected in 0.03 s**); the earlier source and seven helper checks are reused. The isolated check now calls the candidate's actual `_runtime_identity`, requires `release_id_status`, `app_root_status` and manifest-SHA status `VERIFIED`, compares declared pins to the staged plist environment, and rejects every other detailed `DRIFT`. Only the comparison against the still-active old plist and its aggregate are excluded. The excluded comparison remains visible as `DRIFT`; receipt/runtime-inventory/dependency statuses remain the actual `MISSING`, without upgrading them to `VERIFIED`.

One authorized metadata-only operation succeeded; **do not repeat**:

```bash
"$PANEL_PYTHON" -B -m pytest -q -p no:cacheprovider --basetemp=/tmp/v4-perf-helper-identity-final-20261101 tests/test_perf_runtime_repair_release.py -k 'top_level or detailed_identity'
"$PANEL_PYTHON" -B "$TASK_ROOT/docs/handoffs/perf-runtime-repair-20261101/release_repair.py" repair-prepared-metadata
```

The operation regenerated manifest/source provenance and staged plist from the original live base, while preserving the existing app and delta receipt. Before replacement it preserved old manifest, staged plist and preparation receipt in the candidate's `metadata-before-top-level-identity-fix/`. No cloning, app-byte write, live plist write or service action occurred. Complete application inventory SHA remains `9772f211dd1cc8f6ac9e7097ade338216410fe854ecec54120cfa140263fde36`.

Final current candidate pins:

| Artifact | SHA-256 |
| --- | --- |
| `release-manifest.json` | `8f93397a31986a1871276ee90b7f4d89e2a31d5691eeb6ea529e0cbea67a481b` |
| `config/com.lexi.v4.api.plist` | `f390eab840f8c6871985c79b88c8fa748c43539bc934fd6994464451408d0dd5` |
| `repair-preparation.json` / handoff `prepared-candidate.json` | `e4251dd54c483cb3be10730a95892016284831b13dcaf2f45fa8652a97c5a684` |

Status remains `PREPARED_NOT_ACTIVATED`, awaiting the final focused independent review. The activation command above is unchanged. Live API/UI and natural-runtime acceptance are **NOT_RUN**. The detailed identity aggregate can remain `CANNOT_CONFIRM` after activation because missing receipt/runtime evidence is outside this repair.
