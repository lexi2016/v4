# Stage four repairs — Writer handoff

Current integration: [API r4 on actual Junda baseline + unchanged accepted r3 Stage/pre-capture](API_REBASE_R4.md). The [F1/F2 r3 repair](REVISION_F1_F2.md) remains the accepted Stage/pre-capture source; its API companion is superseded. The r2 record below is retained as a prior handoff and is superseded for activation identity and independent acceptance.

Status: `WRITER_TESTED_PENDING_INDEPENDENT_REVIEW`. This is not deployment or independent acceptance.

Baseline `684afcc20be355513b52484430533fe8f2d95e53`; branch `codex/v4-stage-four-repairs-20261101`; source root `/Users/lexi/Desktop/学习/v4_app/.task_worktrees/v4-stage-four-repairs-20261101`.

## Frozen result and scope

1. Stage keeps its existing strict hourly attestation implementation. Its sealed config now pins current Main r6 and the two historical owners name-zoom / sop-closure. Actual D30 0900 needs sop-closure; D30 1000–1700 accepted slots need name-zoom; D1101 2000 needs r6. The old c6 binding remains in provenance, outside the trust fallback. No SHA, signature, witness, clock or cutoff relaxation.
2. Stage8 consumes the strict snapshot reader's `eligible_rows`, accepts its row-bearing partial status and retains the original 100-code pool identity/SHA. D30's 99 eligible symbols reach the injected provider; HK.02915 never does. The reader's `rows` includes quarantined rows; merely changing the status check would have been insufficient. The old redundant v1 reopen also rejected actual v2 snapshots and has been removed. Original snapshot bytes stay unchanged.
3. Failed market lanes prevent `SETTLED_PARTIAL` from stopping retries. The new branch uses the original slot lock, shared attempt budget, backoff, exact receipt CAS and existing scoped runner. Old partial receipts lacking retry metadata use only their actual `OWNER_WRITE_CLOCK_UTC` timestamp. Successful sibling market objects/stores are preserved. A late decision returns `afterfact_required`; no formal replay is authorized by it.
4. Candidate execution filtering runs after the complete original SHA chain passes. The real D30 candidate retains original 532 codes/count/SHA, exposes effective 531, and quarantines A.261029. Existing stock/ETF/HK identity rules are reused. Published ranks and original artifacts are untouched. The dedicated A pre-capture owner receives the same boundary.

The source branch lacks several accepted runtime-only modules. This is an explicit overlay package, not a claim that the old source branch independently matches Stage. `prepare_stage_four_repairs.py` first verifies each exact owner manifest and full inventory, clones those bytes, applies only listed deltas, then seals the result. It preserves Stage's namespace calling convention, native 09:25 and raw-retention fixes, API's runtime-only routes/modules and existing UI. `candidate_input.py`, `rtdata.py` and `snapshot_recovery.py` include the actual Stage preimage and preserve its prior accepted behavior. Generated target hunks and before/after SHAs are in each candidate manifest and `writer_evidence.json`.

## Raw retention and concrete recovery

- Existing Stage8 capture and native A capture paths remain the owners. Stage8 provider exceptions now retain the actual requested eligible codes, clocks and original failure even with zero rows.
- Native A attempts now include requested codes; constructor/prepare errors cannot escape the existing attempt record or leave its lock held. Native primary responses enter `raw_batches` before identity/value filtering, including rejected responses.
- Existing collector calls retain their returned rows, zero-row failures and original exceptions in raw `.collector_requests`. These are explicitly non-authoritative diagnostics.
- The existing scoped process seam now retains stdout/stderr before shared HQ/Futu parsing/aggregation in raw `.process_requests`. It preserves timeout partial output, actual command arguments, planned codes, real clocks, return/error and stream SHA. It calls the original process runner once, stores no environment, and resets its ContextVar on exit. Returned text has an explicit reversible encoding. A stream over 64 MiB is marked `CANNOT_CONFIRM_FULL_RESPONSE_NOT_RETAINED` and fails closed; missing output is not invented.
- Afterfact recovery retains each actual returned batch or failed request under existing `snapshot_recovery/raw_requests`, even if later filtering leaves no valid rows or the next batch fails.
- `ops/stage_data_recovery.py` provides exact-date diagnostics and network-denied `select-existing` with original receipt SHA CAS and the original slot lock. The real D30 09:25 observation was copied to an isolated store, read by the original reader, and scored through the original engine into 10 WATCH_ONLY rows. The original receipt bytes remained identical. Missing sealed observations and missing original receipts stay explicit failures.
- The existing SOP was appended, not rewritten. The API reader now verifies the runtime manifest and reads the fixed allowlisted document from that release. The final r2 actual ASGI endpoint returned HTTP200 with the exact sealed document SHA; unknown document returned 422 and bad manifest pin returned 503. It used isolated empty state roots, no listener and no network. Production 8873 remains unchanged.

## Final stable candidates and owners

Bundle: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r2`.

| Role / future owner | App suffix under bundle | Manifest SHA256 |
| --- | --- | --- |
| `com.lexi.stage-center.scheduler` | `stage-four-repairs-20261101-r2-stage/app` | `1fa1cd9cdbdc51132ba533c4db1436b8646ee82d1d9cad6814b358440d4f3c33` |
| API / fixed SOP consumer | `stage-four-repairs-20261101-r2-api/app` | `20cbeddfcf8c49fcb5b391eaa8c640113518c9f17617e2e09d3fe41b3f6e8769` |
| `com.lexi.stage-center.a-opening-precapture` | `stage-four-repairs-20261101-r2-a_precapture/app` | `a4965b571858e19d47a5bacb450aa91cabf528531126be1e55f7949f80281f8b` |

All three full inventories pass: Stage991 / API1329 / A-pre-capture987 entries. These final configs retain their original production state roots and are **prepared but never executed as schedulers**. Every write-capable regression supplied separate temporary roots. Main r6 is a verified dependency and is not changed.

`com.lexi.stage-center.hk-deadline` remains on its original retirement release: its loaded `--deadline-only` branch calls `deadline_chain_check`, reads completed artifacts and reports provider_invocations/business_writes=0; it does not dispatch collection or A pre-capture. No change to it is needed for this execution boundary. Read-only validation there is not upgraded to a new acceptance claim.

Future activation requires independent PASS, re-reading actual loaded owner tuples/leases, verifying these same manifest/config/inventory SHAs, and changing only the authorized owner identities. No plist, running service, live data, scheduler, Main release, UI, formula, weight, TopN, A/HK pool boundary, BUY gate or trading permission changed here. Moving these apps to another root requires a new manifest/identity seal and affected identity/SOP checks; do not reuse these pins after a path change.

## Verification and reuse

Interpreter for every Python command: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python -B`; environment `PYTHONDONTWRITEBYTECODE=1`.

Assembly actually run:

```sh
PYTHONDONTWRITEBYTECODE=1 '/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python' -B ops/prepare_stage_four_repairs.py --output '/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/stage-four-repairs-20261101-r2' --prepared-runtime
```

The regression command is `tests/test_stage_four_repairs.py [explicit test names]`, with `STAGE_FOUR_BUNDLE` set to the exact sealed bundle and `STAGE_FOUR_RESULTS` to its external evidence JSON. The final r2 increment ran tests02/07/08/12; test13 then verified the actual final API endpoint. Passed unchanged cases were not repeatedly rerun. `writer_evidence.json` records all 13 unique case results, their exact artifact paths, pass reuse and final source/delta SHAs.

External evidence root: `/private/tmp/v4-stage-four-repairs-20261101`.

| Case | Evidence / scope |
| --- | --- |
| 01–05 | `regression-r2.json`: real candidate, three actual owners/context, real D30 99-code boundary, real D29 sealed RT_DATA replay, badSHA/late/all-quarantined synthetic negatives; these individual cases passed although the first whole batch failed below |
| 06 | `regression-r3-retry.json`: original receipt with synthetic DUE decision for scope/budget; late does not execute formal |
| 07/02/08/12 | `final-r2-incremental.json`: final r2 collector retention, actual owner/context/seals/SOP, process seam/raw timeout/reset |
| 09 | `real-runner-r3.json`: real StageCenterRunner + exact D30 raw + strict hourly reader + original A engine gives A10; HK immutable six files/object/latest entry unchanged; provider0; isolated replay only |
| 10/11 | `recovery-native-r4.json`: actual existing observation→original engine Top10/WATCH_ONLY/CAS command; native error/constructor/bad-response retention and dedicated pre-capture effective531 |
| 13 | `final-r2-SOP-endpoint.json`: actual final r2 ASGI API endpoint + runtime identity, doc SHA, HTTP200/422/503; isolated state, no listener |

Initial failures remain recorded: first case06 uncovered the old partial receipt's missing retry timestamps; fixed using its observed owner-write clock and replaced by r3 PASS. First case07 was a test fixture using macOS `/var` alias; SafeRoot correctly rejected it. The fixture now uses `/private/tmp`; security rules were not relaxed. `regression-r2-incremental.json` still contains the then-unresolved case06 failure; the later r3 receipt/real-runner PASS is its replacement. No failure artifact was rewritten to PASS.

The final runtime identity/SOP receipt is bound to stable **r2**, not the earlier r1 path. Earlier whole-app test copies were removed after preserving their manifests/delta hashes in `retired-test-candidate-hashes.json`. Original raw/receipts, source inputs and external regression/failure records remain intact. AST parsing and `git diff --check` passed. No raw data, stdout, credentials, runtime app copies or bulk inventory enters Git.

## Gaps and stop boundary

- D30 Stage8 never reached RT_DATA: no D30 sealed RT_DATA capture was found. Its original-time RT_DATA is `CANNOT_CONFIRM_NO_SEALED_RTDATA`. The 99-code test is a boundary probe, not a real D30 complete selection. D29 replay uses its own unchanged date and actual 6.76MB sealed source.
- Successful isolated raw recovery does not alter or certify the failed historical natural run. No timestamp, research input or data source was rewritten to make the test pass.
- `INDEPENDENT_REVIEW`, `DEPLOYED`, listener `API_VERIFIED`, `UI_VERIFIED`, `NATURAL_VERIFIED` and remote Git sync are NOT_RUN by this Writer. In-process endpoint verification is explicitly distinct.
- Network requests not run and upstream values never returned cannot be reconstructed by a failure ledger. Transport return retention proves the returned process payload, not wire-level execution or PIT certification.
- Controller owns independent acceptance and Git push. No push/deploy/merge/service action was performed.

Rollback before activation is to stop using the prepared candidate identities. If later activated under separate authority, restore the recorded prior owner/config/manifest tuples; retain all new raw/failure evidence and consumed attempts. Never overwrite historical original results or reset the retry budget.
