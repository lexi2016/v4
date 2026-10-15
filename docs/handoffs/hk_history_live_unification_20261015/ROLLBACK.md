# API-only activation and rollback boundary

This release was activated on 2026-10-15 and passed independent online review at
2026-10-15T06:14:12.250258+00:00 (see ONLINE_REVIEW.json). It changes only
`v4/hk_research_history.py` and `v4/manager_workbench/api.py` from the actual API base.
`api.plist.before` contains the exact original plist bytes; `api.plist.staged`
changes only APP_ROOT, PYTHONPATH, release ID, manifest path/hash and WorkingDirectory.
All manager state, source/data roots, safety settings and scheduler bindings are preserved.

## Required before activation

1. Independent reviewer verifies the frozen source/delta hashes, 10 tests and 5 subtests,
   all five real-key route canaries, protected identities, and staged plist preservation.
2. Confirm original API plist SHA is
   `20604d1b3daf2e6e77d2f1d64e42d865baa26e04bafdecf83231447685d3e5e3`.
   Confirm scheduler plist remains
   `317feeec98a924129f7926488b04a634f48fe6db54e53c32273fd5a4e6781e12`.
3. Read current manager_auto_research and manager_workbench task/attempt state using their
   existing authoritative roots. Wait for healthy QUEUED/RUNNING work to drain; do not kill it.
   The existing unrelated `/tasks/status` 500 is not a reason to alter that route.
4. Hold `ops.api_release_integration.shared_api_release_lock` for the API plist;
   call `verify_api_release_candidate` with `active_pointer='base'` and
   `require_shared_lock=True`. A changed base stops the cutover.
5. Use only the API LaunchAgent `com.lexi.v35.api-only` for a graceful stop/start and
   replace its plist with the already-reviewed staged bytes. Leave the scheduler alone.
   Do not migrate manager roots or run the full candidate builder.

## Required after activation

While holding the same release lock, verify the candidate with
`active_pointer='candidate'`. Confirm actual process cwd/environment/release manifest
bind to `hk-history-unified-api-20261015-r1/app`, then query the five frozen HK keys
through online port 8873. Check both raw source variants, row/source hashes, field masks,
`UNRESOLVED_SOURCE_SEMANTICS` and `NO_CANONICAL_SCORING_ADMISSION`; scoring remains false.
Read the A control market only, hash compact sorted JSON, and require
`2d709f625c7dff8d81a3777e2bcf672b00a8156278a01febff5403055928c0fb`,
artifact `selection-b37a1ee172cd45451d78e35b`, run
`run-b37a1ee172cd45451d78e35b`. Do not export A rows.

## Rollback trigger and action

If online candidate binding, HK behavior or A control changes unexpectedly, stop only
the API LaunchAgent gracefully under the shared release lock, restore the exact bytes
from `api.plist.before`, then start only `com.lexi.v35.api-only`. Confirm the old release
`hk-execution-evidence-api-20261015-r1` and original plist SHA, and read the A control again.
Retain the candidate, old release, owner materials, aliases and failure receipts.
The scheduler, panel_latest, canonical panels, model/scorer and all other data stay untouched.

The two material packages already moved into C ownership by same-volume rename remain
there during API rollback. Both old package aliases point directly to those same bytes.
The old API never depended on the new descriptor or adapter, so API rollback needs no
data copy or reverse move. Any requested source-layout rollback must use the pinned
SOURCE_MOVE_RECEIPT identities and a separately scoped owner decision; it must not create
another history copy or silently rewrite canonical C data.

This is research-only history access. Units, currency, adjustment basis and PIT remain
unknown. C precedence does not prove C's historical baseline or isolate its existing scorer.
`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
