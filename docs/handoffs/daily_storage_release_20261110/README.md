# D10 storage repair release

Status: PREPARED_NOT_ACTIVATED; independent review and deployment are pending.
Tool baseline: `9533664efef9a1e1c8f16b4e43eca020a160ef47`.

Packet: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-storage-recovery-20261110-r1/PACKET.json`
SHA256: `1ba798729923924fa8073dfb050a00e9bbe7a072795d0c5f4819d0e147349316`.

Only Main and Stage are service-control targets. Main is a strict clone of the
installed R3 with only `ops/research_storage_governance.py` replaced by the
reviewed exact serializer byte accounting. Stage is its distinct installed
variant with only `len(historical) > 7` changed to `> 8`; the bound full source
packet here preserves that variant instead of overwriting canonical source.
The config repins exact new Main, appends exact old current as eighth history,
and preserves prior seven, transition and all other fields.

The API app, manifest and live plist bytes are unchanged. Stage locators and
Main identity migrate through the previously accepted helpers. All 24 storage
source bindings validate, with final Stage plist before pins before policy
before final Main plist. Policy changes only its managed-pin reference; quota,
protected paths, GC=false and dry_run=true persist. Non-delta app entries remain
identical, including all active A925/Top200/company/score/17 behavior.

Three new release tests passed. Actual candidate preparation validates the full
installed baseline inventories, candidate non-delta hashes, all24 dependencies,
old7 append-only history and exact unchanged API. The transaction reuses accepted
idle/locks/drain/CAS/backup/rollback code with copied globals selecting the local
validator; the original helper module is never mutated. No transaction or
service action was run by Writer. See process HANDOFF.json for all evidence.

Controller commands after actual independent PASS:

```sh
export PANEL_PYTHON='/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python'
export STORAGE_PACKET='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-storage-recovery-20261110-r1/PACKET.json'
"$PANEL_PYTHON" -B -m ops.prepare_daily_storage_recovery_release validate --packet "$STORAGE_PACKET"
"$PANEL_PYTHON" -B -m ops.prepare_daily_storage_recovery_release activate --packet "$STORAGE_PACKET" --review /absolute/path/to/actual_independent_review.json
"$PANEL_PYTHON" -B -m ops.prepare_daily_storage_recovery_release validate --packet "$STORAGE_PACKET" --installed
```

Do not fabricate a review or alter sealed candidates. The controller must hold
original lane locks and wait for live work to finish. Explicit rollback uses
`rollback` with the same packet/review and exact saved baselines. Immediate
failed-cutover recovery retains all business data. After a new owner produces
publications, rollback requires an owner-compatible forward decision because
the old Stage config does not pin the new Main. No late data rollback is certified.

Existing-owner recovery CLI and real timestamp/cutoff constraints are frozen in
`/Users/lexi/Desktop/学习/agents调试/v4_daily_storage_recovery_20261110/RECOVERY_INVOCATION.json`.
No original checkpoints, raw history, pointers, formulas, pools or BUY rules were
changed. Recovery, paired generation, daily package, derivatives, API/UI and
natural observations remain NOT_RUN by Writer.
