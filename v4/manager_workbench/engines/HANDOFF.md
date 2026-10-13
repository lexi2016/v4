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

InputBatch, LaneResult, StockDecision and ReviewSummary field names follow `COMMON_CONTRACT.md` (`MWB_V1_20261013`). These are plain JSON-compatible mappings for the isolated A tests. **B is the sole owner of public typed classes and JSON samples**: when B's fixed commit is available, bind its types/semantic executor and verify serialization/contract tests before any Mac integration. This A branch does not create competing B types.

The authoritative adapters are injected by B/Mac and must return exact market, date, owner, signed/hash-pinned scope and availability-time metadata. `load_inputs` never fetches from the network or browser; unbound/mismatched adapters result in `INPUT_MISSING`, not `READY_EMPTY`. The US batch `universe_ref` must carry the actual configured 33 symbols, verified US session and calendar. Oversold requires verified prior HK trading session, 60 distinct earlier verified high sessions, five earlier verified volume sessions, comparable units and monthly Connect membership; `Decimal` implements the fixed 0.8 AND 1.5 rules. No additional threshold or source is invented.

Reader and Reviewer use separately configured models, fixed prompts, structured semantic outputs and B's executor. Articles and Reader JSON are untrusted `materials`, never instructions. Execution evidence must prove distinct process identities, source/body/output SHAs and tool isolation; otherwise that article is `UNASSESSED`. The executor may provide `read_cached(task_id)`; only fully revalidated exact hashes and completed-before-cutoff cached results are reused. No direct Codex or model CLI call is performed here.

Stage is a reference unless the original owner provides independently verifiable formal admission receipt and rule. Close-observation rows are never promoted. `evaluate_review` requires a complete, same-date, same-market, same-scope close ranking; neither late Top20 nor truncated UI rows feed `run_lanes`.

## Test and deployment boundary

```bash
PYTHONPATH=. python -m pytest -q tests/manager_workbench/engines
```

Candidate unit tests use synthetic data and a **fake** semantic executor only. B fixed contract commit: **NOT_AVAILABLE at coding time**. Actual model canary, market owner/date binding, independent reviewer of this code, Mac end-to-end/API/UI and natural 09:25/intraday/16:30 behavior: **NOT_RUN**. No runtime service or UI switched. RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false.
