# Top200 bounded release handoff

R2 is prepared and read-only tested. Independent joint review and controller
activation remain required. Business source is `28f12f21`; business handoff HEAD
is `eedd3c03`. R1 remains frozen as the failed receipt-path candidate and must
not be activated.

Packet: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-top200-scope-20261110-r2/PACKET.json`

SHA256: `57d42d857f022d157ad3a1106d0ef01d20f42eb363bce3a81c34a22f6e9793b9`

Only the API app has five business/build deltas. Existing hashed assets remain.
Main uses the same app, release, manifest, arguments and source; its plist changes
only the two retention-policy references. Stage is neither modified nor targeted
by service operations. New policy changes only its pin-inventory reference; pins
change only API plist SHA and API app source locators. Actual Main policy reader
and 24 `_checked_file` references passed with explicit draft-plist substitution.
Main manifest `storage_phase2.policy` is historical provenance; the actual
`configured_policy()` authority is the plist environment path and SHA.

The candidate ASGI date list, frontend build, Top200 dated GET and native index
returned 200. API identity and JS/CSS bytes matched the new manifest. D9 pool is
487/36; existing stage selection is 10/2 with one available stage and six failed
receipts retained. Product index, latest selection and historical receipts did
not change. No research, scoring, module publication or producer replay occurs.

## Controller commands after joint PASS

Use the real review JSON with `verdict=PASS` and the exact `packet_sha256` above.
The review file must exist; do not synthesize it. Run from the release worktree:

```sh
cd /Users/lexi/.codex/worktrees/top200-scope-release-20261110
export PANEL_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python'
export TOP200_PACKET='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-top200-scope-20261110-r2/PACKET.json'
"$PANEL_PYTHON" -B -m ops.prepare_top200_scope_release validate --packet "$TOP200_PACKET"
"$PANEL_PYTHON" -B -m ops.prepare_top200_scope_release activate --packet "$TOP200_PACKET" --review /absolute/path/to/actual_joint_review.json
"$PANEL_PYTHON" -B -m ops.prepare_top200_scope_release validate --packet "$TOP200_PACKET" --installed
```

The tool takes DEFAULT and A_LONG locks without waiting, requires Main to have no
descendants, and rejects a busy service before stopping anything. Wait for healthy
jobs to finish if it rejects; do not cancel them. It drains each old PID and all
captured descendants and waits for API listener closure before bootstrapping.
API/Main plists use CAS replacement and exact backups; partial failure restores
the old tuple. Loaded policy environment and serving API manifest are checked.
Stage remains outside the service-control set. There is no data publication step.

Explicit rollback, only if needed, restores API/Main plists and retains all data:

```sh
"$PANEL_PYTHON" -B -m ops.prepare_top200_scope_release rollback --packet "$TOP200_PACKET" --review /absolute/path/to/actual_joint_review.json
```

Read `ACTIVATION_RECEIPT.json`; a recovery `CANNOT_CONFIRM` requires controller
diagnosis. The tool does not grant permission to overwrite concurrent changes.
Live UI and natural-run verification are controller tasks, not claimed here.

Necessary source files and compact evidence are listed in `HANDOFF.json`.
Runtime candidates, built dist, source data and local failure traces are excluded
from Git. Do not edit the sealed tool or imported helpers without a new packet.
