# HK announcement candidate import and release runbook

This runbook binds the reviewed source aggregate `b5ea2c12b3c0ad380f308fd7fffc849383bbe9656ea44e0b2f9f8bbcd0f06d49`. Parent-controlled release preparation and isolated lifecycle verification completed. The first shared activation attempt failed during LaunchAgent bootstrap; the parent restored the exact prior plist and prior API. The saved failure and recovery evidence remain task-local. No catalog or analysis product was imported into the active owner.

## Current owner and release contract

The recovery receipt last observed PID `10546`, label `com.lexi.v35.api-only`, application root `/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-daily-pool-recovery-r1-20261007-api-candidate/app`, and restored LaunchAgent plist SHA-256 `068a471484a592c9fa7cfc55843d8b22abb57e962469bb5e4ae065902b37798b`. Treat that PID as an observation only: every operator resolves the current PID, working root, exact plist, manager/data roots, release manifest, and research-only flags from the existing LaunchAgent immediately before use. If any of those bindings changed, stop and reconcile the new active owner.

The LaunchAgent's existing `ProgramArguments`, data roots, Stage selection root, safety variables, stdout/stderr paths, `KeepAlive`, and label are copied from the loaded owner configuration. The release operator changes only `V35_APP_ROOT`, `V35_RELEASE_ID`, `PYTHONPATH`, `V35_RELEASE_MANIFEST_PATH`, `V35_RELEASE_MANIFEST_SHA256`, and `WorkingDirectory`. It stages four reviewed backend files, both accepted frontend TypeScript files, and the 11-file dist (`798,364` bytes; SHA-256 `efbc2fa26319219afcd465e90733dfd426f5ee96e052a6dd1e8d4060743d0b47`). The new release manifest is regenerated from the staged tree and keeps `RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, and `orders_sent=false`.

Before parent-controlled release activation, recheck the active PID/root/LaunchAgent and the Stage application baseline. The operator does not edit the scheduler plist, other LaunchAgents, Vibe configuration, Stage data, or trading gates. Activation and rollback use only `launchctl bootout` / `bootstrap` for `gui/<uid>/com.lexi.v35.api-only`; after bootout, the repaired operator waits up to 20 seconds for that exact label to disappear before replacing the plist or bootstrapping. A timeout records an indeterminate attempt and does not replace the plist or issue bootstrap.

## First activation failure and bounded retry identity

The first staged plist passed `plutil -lint`; its parsed values and types match the prior plist except for the expected release root, release id, Python path, manifest path/SHA, and matching `WorkingDirectory`. The concise system log excerpt is saved at [ROOT_LAUNCHD_ACTIVATION_RACE_EVIDENCE.json](ROOT_LAUNCHD_ACTIVATION_RACE_EVIDENCE.json). At 18:17:42.799 CST, launchd signaled prior PID 1137 and scheduled cleanup; at 18:17:42.803, the immediate bootstrap failed with code 37, `Operation already in progress`; launchd removed the prior label at 18:17:42.952. The failure was a bootout/cleanup race, not a malformed plist. The parent restored the exact prior plist and verified the old 9/29 API contract plus the new-date pre-import state in `ROOT_ACTIVATION_FAILURE_RECOVERY_RECEIPT.json`.

The failed transaction and activation receipt are immutable. A retry must use a new release name and transaction directory, pass the exact failed transaction root and recovery receipt to `prepare`, and re-read the current active baseline. The new operator refuses a retry without those links, refuses ambiguous prior failures, and verifies that both recovery and failed-receipt hashes remain unchanged on every later transaction verification. The parent has not run this retry; the operator delta must receive its own independent review first.

After an independent pass of the launchd-unload wait delta, the parent may prepare a distinct `announcement-daily-20261007-r2` candidate. Use the new reviewed ops approval receipt supplied by the parent/reviewer; the earlier receipt predates this operator delta.

```sh
STAGED_R2="/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-daily-20261007-r2/app"
FAILED_TX="$TASK/daily_runs/20261007_20261006/active_import/release_transactions/announcement-daily-20261007"
RECOVERY="$TASK/ROOT_ACTIVATION_FAILURE_RECOVERY_RECEIPT.json"

"$PY" "$OPS" prepare --active-release-root "$ACTIVE" --staged-release-root "$STAGED_R2" \
  --approval "$APPROVAL" --superseded-failed-transaction-root "$FAILED_TX" \
  --recovery-receipt "$RECOVERY"
"$PY" "$OPS" verify --active-release-root "$ACTIVE" --staged-release-root "$STAGED_R2"
```

Only after the new stage and current active owner are independently reverified may the parent use the corresponding new `STAGED_R2` path with the reviewed activation approval. Do not retry the original `announcement-daily-20261007` transaction or remove its attempt marker/receipt.

The previously captured 2026-09-29 owner remains the compatibility guard: source `COMPLETE`, analysis/selection `VERIFIED`, 140 issuer rows, 23 selected, exact old owner bytes. The target 2026-10-07 / publication 2026-10-06 API was last observed `NOT_RUN` / `NOT_IMPORTED` / `NOT_ASSESSED`; this must be rechecked before stage activation or import. The accepted source catalog is already in task-local isolated state: run `028ce0e6bdc448248c21f1da3cf1b2f6`, SHA `0cc10a09e8a06514a1981d2dad0642ac2e294e67ace71e8843f1afcd0de2df7e`, 580 notice rows, 584 code associations, 524 distinct source codes, issuer count unknown, Connect `NOT_ASSESSED`.

## Read-only preflight and prepare

Use the same Python runtime as the service:

```sh
PY="/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python"
TASK="/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_DAILY_REPAIR_20261007"
ACTIVE="/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-daily-pool-recovery-r1-20261007-api-candidate/app"
STAGED="/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-daily-20261007/app"
OPS="$TASK/guarded_announcement_release_transaction.py"
APPROVAL="$TASK/RELEASE_OPS_REVIEW_APPROVAL.json"

"$PY" "$TASK/guarded_announcement_import.py" --preflight --release-root "$ACTIVE"
```

No PID is pinned. The operator resolves the current PID from the loaded LaunchAgent; an optional `--pid` is only a guard and must equal that value. Exit 2 means `BLOCKED`: preserve the receipt and inspect the current owner/state rather than overwriting it.

After an independent ops `REVIEWED_PASS` for the exact frozen ops receipt, and after the parent verifies the current Stage baseline, prepare and inspect a new isolated release:

```sh
"$PY" "$OPS" prepare --active-release-root "$ACTIVE" --staged-release-root "$STAGED" --approval "$APPROVAL"
"$PY" "$OPS" verify --active-release-root "$ACTIVE" --staged-release-root "$STAGED"
```

Preparation refuses an existing stage or transaction, verifies all six source-file hashes and dist bytes, regenerates the staged release manifest, preserves the loaded LaunchAgent plist byte-for-byte, and writes a candidate LaunchAgent plist under the task-local transaction directory. It does not activate or change the live plist.

## Temporary isolated API lifecycle

After independent ops review, the parent can exercise the real candidate and rollback service lifecycle without changing the shared owner. This operation uses port `18873`, task-local manager/data/Stage roots, and three short-lived API child processes: prior release, staged candidate, then prior release again. It does not register a LaunchAgent, use the shared Stage/Vibe state, import announcement data, or alter the active `8873` process. Each child is terminated before the next starts; logs and a receipt remain in the task directory.

```sh
"$PY" "$TASK/isolated_announcement_release_lifecycle.py" \
  --active-release-root "$ACTIVE" --staged-release-root "$STAGED" \
  --port 18873 --confirm-isolated-lifecycle
```

A successful result is only `PASS_ISOLATED_CANDIDATE_AND_ROLLBACK_API_LIFECYCLE`. It establishes temporary process startup, date-bound API empty-state readback, and cleanup on an isolated port. It is not a deployment, active LaunchAgent switch, imported catalog, semantic selection, browser UI, or natural-run receipt. `ISOLATED_LIFECYCLE_INDETERMINATE` requires reading its task-local log/receipt and confirming all child processes stopped before any retry.

## Parent-controlled 8873 activation and rollback

Only after the reviewer passes the frozen ops aggregate, the parent verifies Stage/API baselines, and the parent issues the exact release approval receipt may it activate the shared API:

```sh
"$PY" "$OPS" activate --active-release-root "$ACTIVE" \
  --staged-release-root "$STAGED" --approval "$APPROVAL" --confirm-activation
```

The operator re-reads launchd owner identity, refuses plist/PID/root/source drift, records a one-attempt marker, boots out only the existing API label, atomically replaces that LaunchAgent plist with the staged copy, bootstraps the same label, then confirms the new process root, six source hashes, dist and manifest hashes, unchanged 9/29 contract, and target pre-import state. An indeterminate receipt blocks retry; do not manually start a second process or restore files without parent reconciliation.

Before target catalog import, repeat the read-only preflight. The import requires the exact reviewed catalog/run/date/source hashes and uses only saved task-local Eastmoney page refs through the existing `accept_saved_date_catalog_refs` owner; it makes no network request and creates no second producer:

```sh
"$PY" "$TASK/guarded_announcement_import.py" --preflight --release-root "$STAGED"
"$PY" "$TASK/guarded_announcement_import.py" --apply --confirm-apply \
  --approval "$TASK/OPS_REVIEW_APPROVAL.json" --release-root "$STAGED"
```

Catalog acceptance is limited to the exact run/date/SHA, 580 rows, 584 associations, 524 distinct source codes, unknown issuer count, and Connect `NOT_ASSESSED`. It does not complete body semantics, stock-selection decisions, analysis import, browser UI, or natural daily coverage.

Import rollback is a separate exact-owner action and must complete before release rollback if the catalog was imported. Release rollback requires a successful activation receipt, candidate PID and current LaunchAgent plist match, the target back at pre-import state, the exact saved prior plist bytes, and unchanged legacy API/owner bytes:

```sh
"$PY" "$TASK/guarded_announcement_import.py" --rollback --confirm-rollback \
  --approval "$TASK/OPS_REVIEW_APPROVAL.json" --release-root "$STAGED"
"$PY" "$OPS" rollback --active-release-root "$ACTIVE" \
  --staged-release-root "$STAGED" --approval "$APPROVAL" --confirm-rollback
```

`PASS_RELEASE_ROLLED_BACK_AND_API_READBACK` is emitted only after launchd reloads the preserved prior plist and the prior release source hashes, 9/29 owner/API contract, and 10/7 pre-import state read back. Any attempt marker or indeterminate receipt blocks retry. Candidate files and content-addressed material blobs are preserved.

## Daily date and product boundaries

The controller's 06:30 Asia/Hong_Kong rule pairs the previous natural calendar date as publication date with the run date when it is an HK securities session, otherwise the next HK session. The existing `contracts.trading_calendar` HK owner was inspected for target-session resolution. Each `(target_trade_date, publication_date)` pair remains an independent product. If a missed window includes Saturday and Sunday, a Monday target can have two publication dates while the existing default API/UI date is only the previous HK session; use the explicit `publication_date` parameter to read/import each date separately. Never merge different publication dates into one catalog or mark one date as complete coverage of a multi-day gap. Missed dates need separate exact source-bound receipts and existing-owner catch-up.

The accepted source supports explicit `publication_date` in candidate API/UI code and tests. Candidate behavior is source/test evidence only; live browser UI remains `CANNOT_CONFIRM`. Daily heartbeat setup is controller-owned and has not been changed by this writer. A future natural 06:30 run needs its own pair-bound source/run/API receipt.

## Evidence status

The independent source/UI receipt covers the accepted 12 source/test files. The independent semantic reader receipts and source-bound body corpus cover factual materials; some article bodies have material NUL gaps. PDF derivative binding is separately `REVIEWED_PASS` for 41 sidecars and does not by itself verify economic meaning. Article-specific semantic decisions and the final selected-stock list still require product review. No active catalog import, 8873 activation, browser UI, or natural daily run is claimed by this runbook.
