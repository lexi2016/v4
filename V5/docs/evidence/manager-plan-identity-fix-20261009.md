# Hash-only screen cutoff correction

Parent: 945b89d7c3411a4913f50c4472514a61676c621e.

Mac evidence: announcement 6 PASS (5.966s); actual 33/54/75 consumption,
original plan/same-run attempt readback and composed output <=16MiB asserted.
Exact temporary plan ID and output byte count were not retained and are not
claimed here. The 429-source and 758-input SHA sets stayed unchanged.

P2 RED: actual adapter 1 FAIL on STALE_INPUTS_CHANGED (.642s); production
projection 1 PASS / 1 FAIL (.047s), with cutoff-only hash drift reproduced and
source/session/phase/admission changes still invalidating identity.

This correction deep-copies the screen only for hashing and excludes exactly
`data_context.research_cutoff` from that hash input. The returned market_screen,
its actual cutoff, all session/phase/source/eligibility/gap fields and caller
inputs are retained. No files containing saved plans or sealed attempts are
migrated or rewritten. Pre-fix saved identities may be stale across this version
change; that is not silently upgraded to CURRENT. The regression refreshes a
new candidate plan and requires subsequent unchanged-source reads to remain
CURRENT with the same run and immutable saved bytes.

The production source manifest and adapter PIN are updated. Original announcement
reader files and the original RED fixture remain unchanged. Cloud checks are
AST, exact changed-file scope, manifest digests and git diff only; no product
execution, deployment or live schedule changes.

Existing Mac task: run targeted manager and announcement checks, then the
existing full-suite command once if the targeted candidate passes:

```sh
PYTHONPATH=V5/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s V5/tests -p 'test_manager_plan*.py' -v
PYTHONPATH=V5/src PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s V5/tests -p 'test_manager_announcement_binding.py' -v
```

Next coding work: original UI date-binding / misleading 503 message. The separate
announcement acquisition budget task owns its files; no changes to that task.
