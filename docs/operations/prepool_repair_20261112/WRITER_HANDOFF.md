# Preselection publication repair · 2026-11-12

Candidate only; independent Reviewer acceptance and controller deployment/backfill remain required.

## Frozen scope and provenance

- Goal: verified zero-row V192 must be legal and ineligible; invalid single pools retain rejection evidence while valid siblings publish. Keep complete A inputs, market boundaries, original strict A/HK formal gate and all research safety flags.
- Writer: GPT-6.1 Sol High; branch `codex/prepool-storage-20261112`; worktree `/Users/lexi/.codex/worktrees/prepool-storage-20261112/v4_app`; baseline `ddab09e32dd18d71234d2c699f00f2805934f1a9`.
- Maintenance paths: `domains/_preselection_materializer_parts/row_assembly.py`, `ops/materialize_scheduled_preselection.py`; one necessary regression test and this packet. No canonical or live files changed.
- Main origin: `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-result-receipt-20261112-r1-main/app`.
- The release is a reviewed sequence of deltas. Its top-level source commit does not imply every runtime module matches that commit. Runtime materializer remains inline; maintenance materializer delegates to parts. Controller authorized maintaining the parts and binding a separate minimal runtime delta. `RUNTIME_DELTA.json` pins the original release-manifest SHA and both actual file SHAs, verified against `app_files` before generating edits.
- Do not deploy maintenance modules over the live inline modules. `RUNTIME_DELTA.patch` is the readable exact runtime diff; `RUNTIME_DELTA.json` and `apply_runtime_delta.py` supply checked application/reversal to a separately assembled inactive Main clone. They do not change manifests, owner identities, services, data, permissions, Stage or Vibe.

## Behavior

- A verified empty V192 result uses existing `VALID_EMPTY`, preserves `V192_CANDIDATE_READY_EMPTY` in `cannot_confirm`, keeps source SHA/run/date/count, and sets `stage_selection_eligible=false`. Nonempty V192 output stays `V192_CANDIDATE_READY` and eligible. The pool-store allowlist is unchanged; unrecognized zero-row statuses still fail.
- Publication records each contract-invalid pool as `REJECTED/POOL_CONTRACT_INVALID`, attempts later siblings, and raises the existing aggregate exception after the loop. Immutable conflicts retain `IMMUTABLE_POOL_CONFLICT`; existing data is not overwritten. Formal transient missing lanes remain deferred and preserve their actual reason.
- Runtime `main()` now catches that existing aggregate exception, emits a machine receipt retaining sibling outcomes, returns 1 and reports `POOL_PUBLICATION_REJECTED`. Its existing formal gate is unchanged; empty A/unready HK can therefore keep the overall run `FAILED` while usable A pools are materialized.
- The maintenance main already had the aggregate catch; preserve its separate later market-scope behavior. Do not transfer that broader behavior into Main.
- No source acquisition, model/formula/BUY change, historical recomputation, service action, external action, commit or push was performed by Writer.

## Checks and evidence

Interpreter: `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python` (existing `PANEL_PYTHON`, Python 3.14). Evidence directory: `/Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112`.

1. Regression baseline: `PREPOOL_RED.txt`: 2 failed, 4 passed; failures reproduce illegal V192 empty status and abort before valid siblings. An earlier default pytest temporary-directory cleanup touched a pre-existing inaccessible pytest garbage directory; no business path changed. All subsequent tests used this task's explicit basetemp.
2. Maintenance regression: `PREPOOL_SOURCE_FINAL.txt`: **9 passed**. Covered verified empty/nonempty V192; rejected unexpected empty statuses; invalid first pool plus valid A/HK siblings; immutable conflict; actual HK missing reason; failed CLI JSON receipt. 241 A rows persist and remain in a complete projection despite display `limit=1`; HK rows stay separate; safety flags remain false.
3. Exact runtime delta regression: `PREPOOL_RUNTIME_FINAL.txt`: **9 passed** against the real Main imports/store, with only the two source deltas compiled in memory; no runtime file or business data written.
4. Checked runtime patch application on own two-file temporary copy: apply, verify, rollback, final original SHA check all PASS; copy automatically removed. Current live preimage check PASS. `git diff --check` PASS.
5. Additional compatibility: API groups `test_task5_preselection_producers.py` and `test_preselection_pagination.py` could not collect because the frozen maintenance baseline lacks `infrastructure.runtime_graph.notifications`. `test_current_source_review_repairs_20260928.py`: **11 passed, 12 failed**, every failure from the same missing baseline module. Full errors preserved in `PREPOOL_COMPAT.txt`, `PREPOOL_COMPAT_NARROW.txt`, `PREPOOL_EXISTING_CONFLICT.txt`; not repaired or represented as PASS.

Commands (cwd = worktree):

```sh
"$PANEL_PYTHON" -m pytest -q tests/test_preselection_empty_sibling_publication_20261112.py --basetemp=/Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112/pytest-source-final
V4_PREPOOL_RUNTIME_ROOT='/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-daily-result-receipt-20261112-r1-main/app' V4_PREPOOL_RUNTIME_DELTA='/Users/lexi/.codex/worktrees/prepool-storage-20261112/v4_app/docs/operations/prepool_repair_20261112/RUNTIME_DELTA.json' "$PANEL_PYTHON" -m pytest -q --import-mode=importlib tests/test_preselection_empty_sibling_publication_20261112.py --basetemp=/Users/lexi/Desktop/学习/agents调试/v4_prepool_storage_repair_20261112/pytest-runtime-final
"$PANEL_PYTHON" docs/operations/prepool_repair_20261112/apply_runtime_delta.py --app-root "$V4_INACTIVE_MAIN_CLONE_APP" --action check
"$PANEL_PYTHON" docs/operations/prepool_repair_20261112/apply_runtime_delta.py --app-root "$V4_INACTIVE_MAIN_CLONE_APP" --action apply
"$PANEL_PYTHON" docs/operations/prepool_repair_20261112/apply_runtime_delta.py --app-root "$V4_INACTIVE_MAIN_CLONE_APP" --action verify
```

Controller must update the clone's release manifest/source binding and perform existing owner-transition/rebinding before activation. Rollback before activation: same helper with `--action rollback`; after activation use the existing release rollback/owner mechanism, not in-place file reversal.

## Minimal existing-owner backfill recipe (NOT RUN by Writer)

Use the activated reviewed Main app as cwd, its launcher Python `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python`, and its current plist environment. Preserve the owner authority identity and module paths established by Main activation. Avoid the complete executor (which runs collectors/models/HK acquisition). Read existing source artifacts with the current builder and call the existing publisher directly; this also avoids the unrelated `after_preselection()` asset-completion hook in the full CLI.

The inspected runtime materializer constructs `PreselectionPoolStore(root)` with `write_gate_context=None`, `require_write_gate_context=False`; `scope_gate.assert_write_allowed(None, ...)` returns immediately. The current CLI has no write-authority argument. This is an existing path, not permission to invent a permit, disable a guard, or alter migration controls. If the actual activated owner uses an explicit `StoreGateContext`, supply its existing verified context through that same owner; unknown context is `CANNOT_CONFIRM` and must not be fabricated.

```python
# Run only after controller review/activation, in that Main app and its environment.
import json
from pathlib import Path
from infrastructure.preselection_pool_store import PreselectionPoolStore
from ops.materialize_scheduled_preselection import (
    build_scheduled_artifacts, publish_scheduled_artifacts,
    ScheduledPoolPublicationError, _formal_pool_gate,
)
artifacts = build_scheduled_artifacts(
    trade_date="20261113", signal_date="20261112", selector=None,
    input_root=Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data/preselection_inputs"),
    data_root=Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data"),
    shared_data_root=Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data"),
    shared_package_root=Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-tdx-conflict-repair-shared-20261015-r4/app/upstreams/v3_shared_data"),
)
failed = False
try:
    results = publish_scheduled_artifacts(PreselectionPoolStore(
        Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data")), artifacts)
except ScheduledPoolPublicationError as error:
    results, failed = error.results, True
gate = _formal_pool_gate(artifacts)
print(json.dumps({
    "mode": "BACKFILL", "natural_run": False, "trade_date": "20261113",
    "publication_rejected": failed, "formal_pool_gate": gate,
    "artifacts": results,
    "sources": [{"pool_id": a["pool_id"], "market": a["market"],
                 "status": a["status"], "row_count": len(a["rows"]),
                 "source_sha256": a["source_sha256"],
                 "cannot_confirm": a["cannot_confirm"]} for a in artifacts],
    "RESEARCH_ONLY": True, "production_allowed": False,
    "buy_gate_updated": False, "orders_sent": False,
}, ensure_ascii=False, sort_keys=True))
```

No rows are dumped. Keep the original 17:30/18:00 FAILED receipts. Actual target-date sources, original-owner publication, API response, UI, natural scheduler behavior, deployment, independent verdict and GitHub synchronization remain **CANNOT_CONFIRM / NOT_RUN** until controller obtains their receipts. HK readiness/PIT/semantic business validity are not certified by this repair.
