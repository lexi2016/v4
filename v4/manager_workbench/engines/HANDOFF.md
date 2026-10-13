# A research engine, MWB_V1_20261013 (candidate)

Owner: Issue #40 (A). Immutable requirement base: `lexi2016/v4@5017c9125bd970e0bcd5d7bb6efcdae63c58742f`.
No old-manager imports, producer/collector, storage, API, task process, credentials or trading actions.

## Public calls

```python
from v4.manager_workbench.inputs import load_inputs
from v4.manager_workbench.engines import run_lanes, merge_decisions, evaluate_review
batches = load_inputs(context, adapters)       # dict of lane -> callable(context) returning InputBatch
results = run_lanes(context, batches, semantic_executor)
stocks = merge_decisions(context, results)      # all HK stocks, not UI-paginated
summary = evaluate_review(frozen_snapshot, complete_close_input)
```

InputBatch, LaneResult, StockDecision and ReviewSummary follow `MWB_V1_20261013`. **B is the sole owner of public typed classes, canonical SHA serialization and schema samples**: its separately authored, fixed contract commit is `lexi2016/v4@761df4b6e7d712a28794c440c9e77fa3cdb8d3cb` (Issue #39). The A public facades return B Pydantic types when B is present; their fallback JSON mappings exist only for isolated testing and do not create competing B classes. The two independent branches must be combined by Mac in the sequence B fixed contract → A candidate → B runtime, without an A-owned edit to any B path.

The authoritative adapters are injected by B/Mac and must return exact market, date, owner, signed/hash-pinned scope and availability-time metadata. `load_inputs` never fetches from the network or browser; unbound/mismatched adapters result in `INPUT_MISSING`, not `READY_EMPTY`. The US batch `universe_ref` must carry the actual configured 33 symbols, verified US session and calendar. Oversold requires verified prior HK trading session, 60 distinct earlier verified high sessions, five earlier verified volume sessions, comparable units and monthly Connect membership; `Decimal` implements the fixed 0.8 AND 1.5 rules. No additional threshold or source is invented.

Reader and Reviewer use separately configured models, fixed prompts, structured semantic outputs and B's executor. Articles and Reader JSON are untrusted `materials`, never instructions. Execution evidence must prove distinct process identities, source/body/output SHAs and tool isolation; otherwise that article is `UNASSESSED`. The executor may provide `read_cached(task_id)`; only fully revalidated exact hashes and completed-before-cutoff cached results are reused. No direct Codex or model CLI call is performed here.

Stage is a reference unless the original owner provides independently verifiable formal admission receipt and rule. Close-observation rows are never promoted. `evaluate_review` requires a complete, same-date, same-market, same-scope close ranking; neither late Top20 nor truncated UI rows feed `run_lanes`.

## Test and deployment boundary

```bash
PYTHONPATH=. python -m pytest -q tests/manager_workbench/engines
```

Candidate engine suite: **39 passed** locally with Python 3.13, pytest, and a locally reconstructed B Pydantic type subset (not a byte-identical copy of the B commit); also `python -m compileall -q v4/manager_workbench` passed. Synthetic market data and a **fake** semantic executor only. Independent Reviewer (different Luna Max identity): **NOT_RUN** (not available in this execution environment). Tests against the exact B source bytes, full repository suite, actual model canary, market owner/date binding, Mac end-to-end/API/UI and natural 09:25/intraday/16:30 behavior: **NOT_RUN**. No runtime service or UI switched. RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.


## Evidence & integration guardrails

- Source authority: all five B `Lane` identifiers come through `load_inputs(context, injected_adapters)`; no auto-collector and no manufactured missing-source counts. Exact scopes, captures, monthly membership identities and historical market calendars remain Mac-owned adapter inputs.
- B integration: merge or checkout `761df4b6e7d712a28794c440c9e77fa3cdb8d3cb` first in an **isolated integration workspace**. Overlay the A-allowed files only, run both B contract tests and A engine tests and compare actual serialized `InputBatch`, `LaneResult`, `StockDecision`, `ReviewSummary` with B's canonical fixture/schema. The A branch intentionally does **not** fork B paths.
- Runtime security: real semantic execution must remain blocked until B's sandboxed executor can prove `tool_isolation=VERIFIED`; the `READER` and `REVIEWER` process/execution identities must differ. A never starts Codex, changes global permissions, reads credential roots or persists snapshots.
- Governance: A candidate is `IMPLEMENTED` / `SYNTHETIC_TESTED`; `INDEPENDENT_REVIEWED`, `INTEGRATED`, `DEPLOYED`, `API_VERIFIED`, `UI_VERIFIED`, `BEHAVIOR_VERIFIED` and `NATURAL_VERIFIED` are all `NOT_RUN`. Keep unchanged V4/BUY/Vibe8910.
