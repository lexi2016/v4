# A925 three-consumer closure release

R3 closes the actual Main consumer gap found after R2. No R2 activation occurred.
R1 remains the unsealed inventory-rejection evidence; R2 packet and tools remain
immutable. Business final handoff HEAD is `083e07706007de75de596d5dff06949065497648`.

Packet: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-a925-readiness-20261110-r3/PACKET.json`

SHA256: `0770cb7a873fcde10a27eb1269a5bfa22b296bbc87b6b6c2085c12215f392aa4`

## Final scope

The strictly cloned Main contains one source delta: append the exact new15fd
algorithm SHA to its existing SelectionStore allowlist. The API has the same
one-line compatibility change in its distinct active-source variant. Stage has
the original six repair files plus its exact attestation history bound6->7 delta.
No whole canonical or sibling variant overwrites a runtime app.

Main manifest seals first. Stage current owner binds that exact new Main root,
release, manifest path and SHA. The original six historical owners and 11/06
transition retain every field; old Main29ac is appended as the seventh exact
historical owner. Config otherwise changes only release_id. Stage own arguments,
config locator and first PYTHONPATH segment migrate to its new app; the second
shared dependency, calendar and RunAtLoad=false remain unchanged.

API/Stage final plists -> pins -> policy -> final Main plist form a single DAG.
Pins migrate expected_main_app_root and only the API/Main/Stage source path
prefixes and live-plist hashes. Main plist is not reverse-pinned. Policy changes
only its inventory reference; protection limits/paths, GC=false and dry_run=true
remain. Main manifest storage_phase2.policy stays historical provenance; actual
configured_policy reads the final environment path and SHA. The production
Main implementation verified all 24 draft-substituted source bindings.

Strict base inventories include the restored original sealed Stage test-cache
bytes; no inventory exception or cache exclusion was added. All non-delta app
entries remain intact, including Top200 frontend, company/score/17 assets,
market_quality and all model/formula rules. No live publication or job replay is
part of this packet.

## Incremental verification

Three new release tests passed: exact owner repin plus old-current history,
Main self locator/identity migration, and Main root/source pin migration with
cycle rejection. Unchanged Stage locator, idle/drain/CAS/backup/recovery behavior
reuses the prior five-plus-one release tests; unchanged business/P2 tests reuse
the existing matched PASS scope.

CANDIDATE_CHECK.json uses the actual v4-mac interpreter. Stage, API and Main
SelectionStore readers all read new15fd and oldeee20 ten-row products. The Main
StageSelectionConsumer.get and original consume_shared_stage_selection listener
each consume ten A rows from an isolated fixture, with producer_called=false.
Only the already computed Writer envelope is serialized into an isolated store;
no provider, scheduler, collector, daily job or live artifact producer is run.

The real candidate read_stage_hourly_attestation resolves 20261110/0900 through
the exact old Main29ac historical pin and real completion witness. This is a
read-only historical-owner verification, not new Main natural execution. Pure
due comparison yields the same PREP_0915 before/after; seven settled stages are
not rearmed. Candidate homepage identity and frontend build pass at 200/VERIFIED.
Live product index, raw/selection pointers and all observed D9/D10 receipts have
identical before/after hashes. Runtime UI and a new natural run remain NOT_RUN.

## Controller commands after actual joint PASS

Use the real independent review JSON containing verdict PASS and the exact
packet_sha256 above. Do not synthesize a review.

```sh
cd /Users/lexi/.codex/worktrees/a925-main-consumer-release-20261110
export PANEL_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python'
export A925_PACKET='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-a925-readiness-20261110-r3/PACKET.json'
"$PANEL_PYTHON" -B -m ops.prepare_a925_mainclosure_release validate --packet "$A925_PACKET"
"$PANEL_PYTHON" -B -m ops.prepare_a925_mainclosure_release activate --packet "$A925_PACKET" --review /absolute/path/to/actual_joint_review.json
"$PANEL_PYTHON" -B -m ops.prepare_a925_mainclosure_release validate --packet "$A925_PACKET" --installed
```

DEFAULT/A_LONG locks are nonblocking. Main must have no active descendants;
Stage must be calendar-idle, checked again immediately before bootout. A busy
job rejects cutover before service operations; wait for it to finish. Never kill
healthy work to install this packet. Old PIDs and descendants must actually exit
and the API listener must close. All three CAS plists install before any
bootstrap; loaded identity/policy references and serving API identity are checked.

Immediate failed-cutover recovery restores the exact previous tuple and retains
all data. Explicit rollback uses the same original backups:

```sh
"$PANEL_PYTHON" -B -m ops.prepare_a925_mainclosure_release rollback --packet "$A925_PACKET" --review /absolute/path/to/actual_joint_review.json
```

Rollback is an installation transaction, not permission to reverse research
data. Before a later rollback, the controller must check whether new Main has
already produced natural publications: original Stage config does not pin the
new Main as historical. Such a later rollback requires an owner-compatible
forward repair decision; do not restore old data or claim the old tuple accepts
new-owner publications. No late data rollback is certified by these checks.

ACTIVATION_RECEIPT.json records success/failure/recovery. Recovery CANNOT_CONFIRM
requires controller diagnosis; concurrent third-party changes are never
overwritten. Do not edit sealed tools, imported helpers or bound business
handoffs without preparing a fresh packet.
