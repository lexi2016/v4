# Exact r8 integration: prepare first, no live action yet

The actual immutable parent is r8, manifest0de62ef4..., plist5d5c01d3..., inventory97b803c3.../1274. The new isolated candidate is `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-date-top20-api-20261020-r1`. It may be created once and never overlaid if already present. Any current parent/plist/inventory drift stops this preparation rather than following another owner's changes.

Only these source byte changes are proposed: the three already independently accepted backend files from US_MAPPING wiring, plus this round's independently accepted frontend files among Workbench.vue/useWorkbench.ts/api.ts/types.ts/workbench.css. The final frontend PREPARED raw SHA is 1fa62966c23663e99331ef9f7a150d23aebcc89a63024920d7eab1db00d54fc9 and DELTA raw SHA is b789fac96ac28754d9c600d930ecf0d930360c7e5977712e37e032a51e040f50. Exactly five production sources are copied from its frozen actual-r8 staged source root, never the divergent task-WT source. Two regression specs are source delivery artifacts, not runtime overlay entries. No other frontend source, package, announcement, research store, scheduler or business module may change.

`RUNTIME_PREPARE_API.py` is a prepare-only helper. It requires a raw-SHA-bound `RUNTIME_FRONTEND_BINDING.json`; that binding will reference the source Writer's actual frontend receipt and exact JSON-pointer proofs for the r8 build parent and each file hash. It validates every backend/front preimage and after file, clones the entire actual r8 release, applies only the frozen allowlist, recomputes full application inventory and proves every non-delta entry identical. New static files are limited to manager-selection HTML and its needed hashed assets; existing hashed assets may only be reused at identical bytes, never overwritten. All root/daily HTML and old assets stay unchanged. The manifest truthfully records both source receipts, exact overlay and retained historical parent sidecars; no whole-Git equivalence is claimed.

The helper backs up exact parent plist bytes locally and generates a proposal changing only API release/cwd/PYTHONPATH/manifest bindings. No actual plist is written. The old r6/calendar/wiring candidates are not release parents for this task.

## Frozen result and publisher rebind

The old R2 publisher SHA753d1fc6... and result receipt8318f445... are fixed inputs. Preparation copies the five existing pipeline artifact files at identical bytes into `local_only/runtime/pipeline-store`; it does not execute a pipeline or update any business field. New run05d40e7775c44304bbd98016194b0d0e, batch6b1f625..., full input2d9ed180..., product62e4ea7d... and all source/processing dates remain fixed. The old original source run52d6d87... and its history remain untouched.

The publisher copy changes only candidate root/manifest/proposal SHA, receipt filenames/hashes, local artifact paths and helper hash metadata. R2's code for raw receipt binding, immutable expected-new-pointer985b91b1..., full idempotence, running state plus positive PID/lsof cwd, and lock-protected pointer preimage/rollback is retained verbatim. `RUNTIME_PUBLISHER_REBIND.json` will enumerate every literal replacement and both code hashes. The original old helper/receipts/artifacts stay unchanged. No new JobCoordinator is created against live state.

The exact target20 NEXT_DAY preimage remains pointer81ea8ec3... naming52d6d87..., or this stage stops. Target20 INTRADAY pointer264aa593... naming15:03 run e96a793... and all MANUAL/PREOPEN/history entries remain unchanged. The accepted prepared run's generated time10:24 must not be advanced to force default ordering. Later UI readback must explicitly select05d40 and separately report the existing date's default/latest version. The new saved result is MANUAL processing recovery over original US19/HK16/target20/source cutoff05:44, never natural success.

R8's store/service/jobs/input validation/engine core/display read dependencies have the same bytes as the reviewed old candidate. Contracts adds only JobState.USER_STOPPED; API adds only announcement execute-preprocessed/stop routes. These parallel changes remain in r8, and the existing snapshot/product model and US read/redaction routes remain intact. The compatibility receipt records their exact hashes; no unrelated repair is proposed.

## Later activation and publication, subject to separate continuation

After independent frontend/candidate/rebind PASS, the controller must explicitly continue live actions. At that time re-freeze current loaded PID/cwd and the exact r8 plist/manifest/inventory and proposal. Require no QUEUED/RUNNING Workbench attempt, no direct API child and no established TCP8873 connection owned by that same PID. A healthy task is not interrupted; a missing safe gap stops rather than creating another waiter or killing work.

After the final guard, write exact local proposed plist bytes, execute one `/bin/launchctl bootout gui/501/com.lexi.v35.api-only`, observe print RC113 absence within16 seconds, then one `/bin/launchctl bootstrap gui/501 /Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist`. Preserve original KeepAlive/RunAtLoad behavior. On unexpected lifecycle inspect actual state before any bounded recovery; do not blindly repeat commands. Read back new running PID/cwd/manifest, health/ready/date-list identity, manager HTML/assets and unchanged root/daily assets. No scheduler/producer changes.

Only after exact API runtime readback: run rebound publisher `--check-only --prepared-sha256 <frozen RUNTIME_RESULT_PREPARED raw SHA>`, then at most one `--publish` with that same frozen SHA. Old-pointer drift or partial/unknown publication stops. Exact already-published snapshot/product/complete pointer is read back without repeating writes. Do not submit a business POST, retry old failed jobs, refresh quotes or alter historical inputs.

API rollback uses the exact backed-up r8 plist only when the live pointer/lifecycle is still owned by this candidate; skip bootout if already absent, otherwise one bootout/absence/bootstrap with original bytes. Result rollback uses the retained R2 guarded old-pointer restoration and keeps appended new history. No other phase pointer, data, old candidate or parallel release is reverted. Both rollback paths are prepared, not exercised.

This handoff freezes candidate/manifest/proposal, the exact frontend overlay, new publisher/result receipt and commands, and a compact sync allowlist. Incremental review is limited to new frontend acceptance, actual r8 preservation and metadata-only publisher rebind/direct check. Existing backend/pipeline/R2 guard PASS is reused. Live activation, publication, API/UI acceptance and natural operation remain NOT_RUN.

## Final prepared bindings and exact commands

Candidate app: `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/workbench-date-top20-api-20261020-r1/app`. Manifest SHA `7bfd33c541b5bb19724f313e8df7deae1877b5ca96379215f3ebd61e723049b8`, candidate receipt SHA `145d40406e698859a43d7766da3c67ccf1a579a994567bda1cc6b6fa203bb105`, proposed plist SHA `fdc3e9536b892952fa404658e00fd6042c162f82df8302bbc1a6fe928db2f752`. Inventory1276 entries/aggregate `a1c2dcd47565e39315a269970e3a97c6a36bc4d7c1f64fcea36fa8d141d0a080`; exact11delta=3backend+5frontend production+manager HTML+2newassets. All non-delta parent entries and all root/daily HTML/oldassets preserved. Candidate is frozen; preparation helper is not a retry/overlay command.

Publisher SHA `98c642786209b9518d5152e6371813b465e5a0e4c7c467b7d94dca9b638757de`; raw result receipt SHA `bc8f3de8ddcac53c6a6c2c5fa360119f4ecab56531caeb3f73faca210740e958`. From this task WT, the exact check-only command already completed RC0:

```sh
'/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python' -B docs/handoffs/workbench_date_top20_20261020/RUNTIME_PUBLISH_RESULT.py --check-only --prepared-sha256 bc8f3de8ddcac53c6a6c2c5fa360119f4ecab56531caeb3f73faca210740e958
```

After independent PASS and explicit continuation only, recheck all above raw hashes, r8 full inventory/plist5d5c01d3..., same loaded PID16695/cwd, retained target20 pointer81ea8ec3..., no active QUEUED/RUNNING attempt, no direct child, no established socket8873. Any drift stops. Proposal is `DOCROOT/local_only/runtime/api-candidate.plist`; backup is `api-parent.plist` with exact original SHA5d5c01d3.... Only after those conditions, copy exact proposal bytes to the existing API plist and run these lifecycle commands once in this order:

```sh
/bin/launchctl bootout gui/501/com.lexi.v35.api-only
/bin/launchctl print gui/501/com.lexi.v35.api-only
# print must show absent RC113 before bootstrap; bounded observation <=16 seconds
/bin/launchctl bootstrap gui/501 '/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist'
/bin/launchctl print gui/501/com.lexi.v35.api-only
```

Inspect actual state if any command fails; no blind retry. Require running positive PID/candidate cwd/manifest, 8873health/ready/date-list exact identity and static HTTP rawSHA. Then the same check-only command may be used for the live-stage precondition (this handoff's check-only does not assert active deployment). The one publication command is identical except `--publish`; the conditional pointer-only rollback is identical except `--rollback`. Do not invoke `--prepare`; frozen business artifacts are reused without execution. API rollback is exact backed-up r8 plist bytes and the same bounded absence/bootstrap lifecycle, only while the active release still belongs to this candidate. No old state/history is deleted; result rollback only restores NEXT_DAY if the complete new pointer985b91b1... remains exact. Current actual activation/publication/rollback/API/UI/natural checks all NOT_RUN.

Incremental Reviewer scope: final frontend metadata hashes/source-location provenance (source/build PASS reused); candidate full1276entryinventory/exact11delta/all other r8 entries and assets; proposal field allowlist; R2 literal rebindings, frozen05d40 five artifact hashes and no pipeline rerun; direct check-only and immutable pointer/idempotence/runningPID/lock guards retained. Existing backend, full pipeline, original R2 guard tests and frontend tests/build are unchanged PASS inputs and are not re-run for this metadata-only integration. Scheduler remains PENDING_PARENT_DRIFT_NOT_DEPLOYED.
