# D10 bounded storage capacity recovery

PREPARED_NOT_ACTIVATED. Independent review and controller activation are pending.

Packet: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-storage-recovery-20261110-r2/PACKET.json`
SHA256: `41a8bdc5bd1cd6623f7527445298efeea20683ccbe1262585fdecb52b105e61d`.

The accepted serializer fix remains byte-identical to business commit
`a188b8f0270dd2041e739bd59bdf7a45e5565681` (59 prior tests reused). The experimental
terminal-owner reservation change was rejected, saved as local evidence and
restored to that commit. Every old future reservation and physical byte stays
protected and billed. No reservation semantics, model, pool, formula or data change
is installed by this packet.

The controller-authorized remedy changes exactly
`governance.ordinary_peak_budget_bytes` from 171,798,691,840 (160 GiB) to
240,518,168,576 (224 GiB). Actual observed category baseline132,064,048,368 plus
original formula forecast51,539,607,552 plus ALL outstanding future reservations
34,713,812,416 totals218,317,468,336, leaving22,200,700,240 bytes (~20.68 GiB).
The original48 GiB forecast is unchanged. Disk reserve64 GiB, safety4 GiB,
minimum free10%, debug/quarantine bounds, protected paths, GC=false and dry_run=true
are identical. The user retention decision protects CURRENT/rollback/raw/unfinished
and does not specify160 GiB as a user hard cap; the controller explicitly authorized
this bounded local capacity setting.

New policy keeps the EXACT existing managed-pin-inventory reference. All24 source
bindings are checked without migration. Main app/release/manifest, Stage and API
remain unchanged; no additional history owner or source patch exists. Only two
Main plist environment values change: policy path and SHA. Main plist has no reverse
source pin, so no dependency cycle or extra service migration is required.

The adapter uses existing strict inventories, CAS, idle/descendant checks, drain,
backup, loaded-policy verification and rollback helpers. Only Main may be stopped
or bootstrapped. DEFAULT/A_LONG locks are held; active work rejects before service
control. The actual installed Main gate is called in a short `sys.executable -B`
subprocess bound to the protected inventory's exact app root, under original writer
and registry locks. It checks current APFS free/ratio plus every original reservation
without writing a registry row. Actual formula admission repeats with freshly
measured residents. Preparation passed the actual gate; disk free was about338 GB.

Seven focused tests cover the exact one-field policy, unchanged protections,
retained reservations, genuine low-space rejection, exact pinned preflight,
Main-only install/rollback, busy/review rejection and failed-install restoration.
All24 installed source dependencies and existing inventories passed real candidate
validation. The initial test import exposed that the release-tool tree omits the
governance module; the final subprocess design uses the actual pinned owner instead
of copying business code. No producer, cutover or external action ran in Writer.

Controller commands after actual independent PASS:

```sh
export PANEL_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python'
export BUDGET_PACKET='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-storage-recovery-20261110-r2/PACKET.json'
"$PANEL_PYTHON" -B -m ops.prepare_daily_storage_budget_recovery validate --packet "$BUDGET_PACKET"
"$PANEL_PYTHON" -B -m ops.prepare_daily_storage_budget_recovery activate --packet "$BUDGET_PACKET" --review /absolute/path/to/actual_incremental_review.json
"$PANEL_PYTHON" -B -m ops.prepare_daily_storage_budget_recovery validate --packet "$BUDGET_PACKET" --installed
```

Run from the release worktree. `rollback` uses the same packet/review and exact
`main-policy-backup/main.plist`; it restores only the earlier capacity policy.
Re-admission under that smaller policy may block new work. Never restore research
data or erase task reservations during installation or rollback.

After activation, continue the original formula owner directly from the exact
READY raw authority and accepted-only manifest in
`/Users/lexi/Desktop/学习/agents调试/v4_daily_storage_recovery_20261110/RECOVERY_CONTINUATION_R2.json`.
That descriptor predates this capacity remedy; its observed-block field records
the old160 GiB policy. Verify its exact source SHA before continuing. Use installed
Main environment, actual timestamp, original A_LONG lock and MANUAL_RECOVERY label.
Do not rerun raw capture or spoof success. Preserve12 technical quarantines and all
lifecycle/alias quarantine, then use existing formula/materializer/receipt/derivative
owners. Formula completion, D10 pair/product, API/UI and natural acceptance remain
NOT_RUN by Writer.
