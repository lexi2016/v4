# A09:25 price-readiness release handoff

R2 is prepared and tested. Independent review and controller activation remain
required. Business repair is `e2c3940b329063fcb065a4e37ee5130b95b52d10`;
business handoff HEAD is `5e3820da77f33499bd769c7d054dd0e0082de33e`.

Packet: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-a925-readiness-20261110-r2/PACKET.json`

SHA256: `dd4b2085b4e01a12666ad22e56d5b67fd9f985c5101d6e0b2e7c77af392441ee`

## Frozen change and preservation

The Stage app clones the restored exact 1003-entry live inventory, then overlays
six Writer-frozen files and changes only config.release_id. The API app clones
the deployed Top200 r2 inventory, then adds one explicit algorithm SHA to its
existing SelectionStore allowlist. No frontend, formula, model, market_quality,
company material or score module changes occur. All non-delta inventory entries
remain byte-identical.

Stage plist changes only release identity, its own command/config locators and
the first PYTHONPATH segment from old-app/upstreams to new-app/upstreams. The
second shared dependency, calendar, RunAtLoad=false and all other configuration
remain unchanged. Current Main owner29ac, six historical owners and the 11/06
transition retain every field. Main app/release/manifest/arguments stay fixed;
only its two policy environment references change.

The acyclic dependency chain is API/Stage final plists -> 24-source pins ->
policy -> Main policy path/SHA. No Main plist reverse pin exists. Protection
parameters and protected paths remain unchanged; GC stays disabled and dry-run.
Main's historical manifest storage_phase2.policy remains provenance. Actual
configured_policy authority is the plist environment path/SHA, checked using
the current Main implementation.

The first preparation correctly rejected two changed sealed pytest-cache files
before cloning or producing a packet. The controller retained their changed
bytes and restored exact original sealed bytes by CAS. R1 remains a failed,
unsealed directory. R2 uses the original strict inventory validator with no
exception. See PREPARE_FAILURE_R1.json, STAGE_BASELINE_DRIFT.json and the bound
controller CACHE_RESTORATION.json.

## Verification boundary

Five targeted release tests passed; the subsequent exact Stage PYTHONPATH locator
test passed. Existing unchanged Main policy constraints and drain/CAS/recovery
primitives reuse their prior PASS scope. No tests ran with an active app as cwd.

CANDIDATE_CHECK.json records the actual v4-mac production interpreter. Candidate
Stage serializes the already computed Writer envelope into a fresh isolated
store; Stage and API both verify new15fd and oldeee20 algorithms, ten rows each.
No collector, network quote request, daily job or live publication is invoked.
Actual Main configured_policy and 24 checked source references pass with explicit
draft-plist substitutions. Candidate homepage date-list/frontend-build are
200/VERIFIED with the new API manifest; Top200 index bytes remain identical.

At the observed 15:31 time, pure _node_candidates yields only PREP_0915 under
both config release IDs; all seven settled stages remain excluded. This is a
read-only due comparison, not execution. Receipt paths and slot idempotency use
date/stage/candidate identities, not config.release_id. RunAtLoad remains false,
so bootstrap does not launch an expired-slot replay. Existing recovery policy is
preserved. Live product index, raw/selection pointers and D9/D10 receipt hashes
were unchanged during the check.

Real API/UI acceptance and the first new natural run remain NOT_RUN by Writer.
Historical 11/09 receipts stay original; retrospective isolated results do not
certify a corrected historical natural run, matched auction price, strategy lift
or PIT eligibility.

## Controller commands after actual joint PASS

Use the real review JSON containing verdict PASS and the exact packet_sha256
above. Do not synthesize a review. Run from the frozen release worktree:

```sh
cd /Users/lexi/.codex/worktrees/a925-price-readiness-release-20261110
export PANEL_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python'
export A925_PACKET='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-a925-readiness-20261110-r2/PACKET.json'
"$PANEL_PYTHON" -B -m ops.prepare_a925_readiness_release validate --packet "$A925_PACKET"
"$PANEL_PYTHON" -B -m ops.prepare_a925_readiness_release activate --packet "$A925_PACKET" --review /absolute/path/to/actual_joint_review.json
"$PANEL_PYTHON" -B -m ops.prepare_a925_readiness_release validate --packet "$A925_PACKET" --installed
```

The tool obtains DEFAULT/A_LONG locks without waiting, rejects active Main
descendants, and rejects any running Stage before service operations. It checks
Stage idle again immediately before bootout. Wait for healthy jobs to finish if
rejected; do not cancel them. Old PIDs and descendants must actually exit, and
the API listener must close, before the new API starts. CAS guards all three
plists and exact backups. The complete tuple installs before any bootstrap;
loaded identities, Main policy references and serving API identity are checked.
No business publication or data rollback step exists.

Explicit rollback restores the previous Top200-r2 API, same Main identity with
its previous policy reference, and the original Stage plist, retaining all data:

```sh
"$PANEL_PYTHON" -B -m ops.prepare_a925_readiness_release rollback --packet "$A925_PACKET" --review /absolute/path/to/actual_joint_review.json
```

Partial activation failure invokes exact previous-tuple recovery. Inspect
ACTIVATION_RECEIPT.json; recovery CANNOT_CONFIRM requires controller diagnosis.
Concurrent third-party changes are never overwritten. Do not edit sealed tools,
imported helpers or bound source handoffs without a new packet.
