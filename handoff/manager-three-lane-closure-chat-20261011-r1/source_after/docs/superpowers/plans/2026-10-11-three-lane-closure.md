# V4 three-lane closure implementation plan

> For agentic workers: use superpowers:executing-plans. Root is the sole Writer; independent agents inspect and review without editing production files.

**Goal:** Repair the supplied V4 source snapshot's proven history, owner-import and selection-readback faults, and deliver evidence for each acceptance condition without promoting research, backfill or synthetic tests to live completion.

**Architecture:** Retain the original owners, stores, selection algorithms and original validators. Work only on the 126-file attachment snapshot in an isolated candidate; missing dependencies may be assembled for testing only after matching a fixed repository blob. Distinguish historical cutoff, explicit current review, and natural execution.

**Tech Stack:** Project Python >=3.14; TypeScript/Vue. Local test runtime is Python 3.14.8 with pytest 9.1.1. Mac runtime and loaded module identity remain unverified.

**Spec:** input/V4_三路选股闭环_问题包_20261011/README_提交给Chat.md and evidence/DATA_GAPS_必须解决.md (preserved in delivery reference).

## Global constraints

- No new producer; no strategy, BUY, Stage ranking or Vibe8910 changes.
- RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false.
- Preserve all current HK/US source changes and canonical uncommitted modifications.
- Original source snapshots are exact input bytes, not proof of the live process's loaded code.
- No fabricated dates, source inputs, owner receipts, natural runs or valid zero results.
- Whole task remains PARTIAL unless A/H/O/I/R/D/N have required real evidence.

## Review focus

- Post-cutoff journals must never exclude an unbound or potentially eligible historical run.
- A malformed/missing receipt must not create READY_EMPTY or turn backfill into formal selection.
- Exact publication/selection/plan dates and explicit read mode must survive page reload.
- A missing peripheral lane must not suppress an independently verified lane.
- Metadata-only registry churn must not authorize ignoring a real payload, receipt, path, date or cutoff mutation.

## Task 1: Bounded historical selection

Files: workspace_history.py; tests/test_three_lane_history_20261011.py.

Interfaces: keep select_plan(store,date,boundary) and _read_candidate validation unchanged; add a negative-only predicate reading the original exact-run workspace_plan_runs receipt through SafeRoot with a small bound. A valid terminal successful plan-owner attempt started strictly after cutoff proves that exact run cannot supply a consumable historical plan. Never consult attempt latest for plan latest.

- [x] Build real SafeRoot/store fixtures with seven large plans and original sealed late receipts; observe cumulative scan failure before edits.
- [x] Add bounded journal exclusion; count metadata reads in the same scan budget; unknown/invalid/unbound receipts use existing validation/failure semantics.
- [x] Test exact boundary, early start/late finish, missing and corrupted receipt, wrong run/date/owner, symlink, unchanged product checksum and archive bytes.

## Task 2: Prove or repair registry identity pollution

Files: tests/test_three_lane_identity_20261011.py; workspace_identity.py only if a reproduced owner-shape or propagation defect requires a change.

Interfaces: keep semantic_digest, identity_component and input_identity_diagnostics; use original ResearchLaneSource and stores to produce actual complete binding shapes.

- [x] Reproduce manifest-only change across several original archive/hourly bindings.
- [x] Verify payload/receipt/path/date/cutoff and source_row mutations still change identities.
- [x] Do not relax the already-valid recognizer on speculation; report the exact missing saved/current input evidence if supplied 10/12 summary cannot be reproduced.

## Task 3: Unify registered announcement import

Files: service.py; announcement_analysis.py and/or existing workspace_announcements.py; manager_research_router.py; tests/test_three_lane_announcement_20261011.py.

Interfaces: preserve legacy import_product behavior; put registered-reference validation, original import, receipt creation/reuse and final consumption readback behind the existing service owner. HTTP route delegates. No synthetic success receipt for an unregistered product.

- [x] Reproduce direct-service/HTTP receipt discrepancy with an original registered fixture.
- [x] Serialize the complete owner receipt operation; preserve same-product receipt bytes/timestamp on retry and reject conflicts.
- [x] Verify original catalog, product, judgment, registry, receipt and cutoff validators still reject wrong inputs.

## Task 4: Use actual selection outputs in daily channels

Files: workspace_daily_channels.py, workspace.py, connect_selection.py, research_attention.py/workspace_plan.py only for proven source binding omissions; tests/test_three_lane_daily_20261011.py.

Interfaces: daily_channels keeps the existing schema; oversold projects original research_selection ledger, preserving decision/source identities. HK can claim completion only from an original formal Stage consumer result and execution evidence. Native source pointer fields survive compact projection. Run/SHA readiness is tied to matched owner readback.

- [x] Reproduce strict-row bypass, false empty readiness, announcement-to-HK contamination and dropped source pointers.
- [x] Reuse original final research ledger and original Stage reader contract where available; preserve unknown until binding is proven.
- [x] Separate plan container identity from screen/decision identity, preserve full excluded/unresolved accounting.
- [x] Validate partial lanes, real saved zero, missing input and rejected backfill independently.

## Task 5: Explicit review and URL date continuity

Files: workspace.py; catalystObservationPanel.ts; dailyChannels.ts/API validators only when interface changes require them; focused Python and frontend tests.

Interfaces: auto keeps original saved as-of replay; explicit dynamic reads actual current cutoff. Existing API selection_date/announcement_date arguments are forwarded only when explicitly chosen; server default publication date remains authoritative.

- [x] Reproduce explicit dynamic using frozen cutoff and real panel GET/POST losing bindings.
- [x] Forward dates, persist/restore view, clear stale results on changed pair and guard against late responses.
- [x] Run actual DOM behavior tests for requests and reload, preserving independent child panel architecture.

## Task 6: Independent review and delivery

- [x] Run targeted production-code tests and document pre-existing stale fixture failures and missing full-app modules.
- [x] Independently review final diff and re-run behavior tests; fix material findings with failing regressions first.
- [x] Preserve before/after files, unified patch, source manifest, exact test logs, acceptance A/H/O/I/R/D/N table, Mac source-CAS integration/rollback steps and concrete outstanding owner evidence.
- [ ] Synchronize only necessary deliverable bytes to a new private-repository handoff branch as authorized by project AGENTS; verify remote commit and key file bytes. Do not merge/deploy or modify live data.

## Execution record

Final isolated checks: backend 68 passed (66 new plus 2 existing), independently repeated; frontend 43 passed (34 new plus 9 existing), 1 unavailable Mac fixture intentionally not run, independently repeated. Strict TypeScript checks passed. Independent reviews closed 2 backend and 3 frontend Important findings. Native Stage execution module, Mac live process, raw historical/input artifacts and natural run evidence remain unavailable. Source candidate is PARTIAL; I/R exact real cases are not claimed as resolved. See the handoff results and post-push receipt for synchronization completion.
