# Manager owner input integration repair — implementation plan

> For agentic workers: use superpowers:executing-plans for root implementation and a fresh independent final review. Initial announcement, HK and plan investigations are independent read-only tasks.

**Goal:** Repair reproduced R2 owner/readback integration defects while retaining exact owner, date, SHA, PIT and stale-input guards.

**Architecture:** Keep the supplied R2 create_app injection, original owner/import paths, readers, store and plan schema. Correct two comparisons in two existing manager modules; add behavioral regressions through the real application factory with isolated synthetic owner artifacts.

**Tech Stack:** Python, FastAPI, pytest; frozen uv.lock dependencies. Available test interpreter is CPython 3.12.14; project >=3.14 and actual Mac acceptance remain separate.

**Spec:** ../request/CHAT_REPAIR_REQUEST.md, FOUR_ISSUE_MATRIX.md and DAY_RUN_REUSE_AND_INTEGRATION.md in that same request directory.

## Global constraints

- Fixed input ZIP SHA256: 67098b73089120e7f1758835ce48ce48258ff427a84faca6a19d2415f0306726; both uploads are identical.
- Fixed candidate identity: a7f5d09fb19de10564925757207977aadc080cc1; the 20 supplied R2 target files control production preimages.
- Preserve the only canonical Mac project and shared 8873 entry; no second producer, collector, data layer or user panel.
- Preserve RESEARCH_ONLY=true, production_allowed=false, buy_gate_updated=false, orders_sent=false; no Stage, BUY or Vibe runtime changes.
- No live data, owner state, deployment, service start/stop or natural-run claims. Temporary synthetic artifacts are explicitly test inputs.
- Missing source/root/exact-date/cutoff proof remains CANNOT_CONFIRM or PARTIAL; stock_count=0 alone is not VALID_EMPTY.
- GitHub delivery uses a new independent work branch and exact allowed paths, followed by commit/file readback. No merge or deployment.

## Review focus

- Read clocks may vary without changing immutable authority input identity; persisted publication availability must still affect identity.
- Scheduled idempotency must compare the same three date bindings enforced by ordinary GET.
- Same-binding scheduled retries must reuse the verified run without rewriting immutable history.
- A supported binding change or source SHA change must still produce STALE_INPUTS_CHANGED until the original owner refreshes.
- Missing announcement review, exact-date master or volume-scale attestation must stay visible after the two fixes.

## Task 1 — Reproduce the fixed input and actual application behavior

- [x] Verify both ZIPs, the 63-file package manifest and all 51 source snapshot hashes.
- [x] Record the exact R2 vs reference roots and historical evidence limits.
- [x] Assemble isolated test support from verified frozen Git bytes; record incomplete-closure and version alignment separately from production changes.
- [x] Run actual create_app announcement import/GET and HK V2/master/panel consumption regressions.
- [x] Demonstrate same app-bound owner refresh -> CURRENT and detached reader -> STALE_INPUTS_CHANGED.
- [x] Demonstrate RED: an unchanged V2 artifact with changed read_at becomes stale; a scheduled default-date dispatch reuses a different selection-date product.

## Task 2 — Stable membership source identity

**Modify:** v4/manager_research/connect_selection.py, filter_cards.
**Tests:** test_manager_app_plan_identity_20261009.py and test_manager_hk_authority_app_wiring_20261009.py.
**Interface:** filter_cards(cards, scope, target_date=...) returns original admitted cards with verified membership metadata; source.read_at remains in top-level diagnostics.

- [x] Independently fail a constant-witness, changed persisted available_at case on the baseline.
- [x] Exclude only source.read_at from identity-bearing membership_source; retain persisted available_at and all original source lineage.
- [x] Run read-clock and source-change regressions; expect CURRENT only for unchanged immutable inputs, STALE for changed source provenance.

## Task 3 — Full scheduled date-binding identity

**Modify:** v4/manager_research/workspace.py, refresh_workspace_plan scheduled duplicate check.
**Tests:** test_manager_app_plan_identity_20261009.py; existing scheduled plan and exact-page binding tests.
**Interface:** refresh_workspace_plan keeps its signature, immutable run products and owner attempt checks.

- [x] Require existing.workspace.date_bindings == prepared.date_bindings before ALREADY_MATERIALIZED.
- [x] Run the real dispatch branch -> ops wrapper -> autorun -> injected owner case; expect a new correct-binding run and CURRENT GET.
- [x] Verify unchanged dates/inputs still reuse the existing verified run; changes never relabel an old immutable product.

## Task 4 — Regression, independent review and delivery

- [x] Run final focused suites against both fixed preimages and final candidate; retain and classify pre-existing/unsupported fixture failures.
- [x] Use one fresh reviewer for source, tests, mutation coverage and delivery claims; fix material findings with RED -> GREEN.
- [x] Create minimal patch, full before/after sources, manifests, exact commands, owner/consumer matrix, Mac apply/readback/rollback instructions.
- [x] Preserve initial setup failures and genuine regression failures, without inflating counts or reclassifying unavailable inputs as success.
- [ ] Publish new handoff branch and ZIP, read back remote commit and critical files; report Mac/API/UI/natural acceptance as NOT_RUN.

## Final acceptance notes

- Final paired suite: baseline265 PASS/30 FAIL, candidate268 PASS/27 FAIL,295 tests each. The3 resolved failures are the independent behavioral regressions. No new failure node.
- Same-binding/same-cutoff scheduled retry verified; advancing the owner cutoff creates a new run through existing market_screen context identity. Preserve the reviewer2 FAIL probes and4 PASS classification; no stripping of PIT context.
- Original journal strict-order assertion remains FAIL; real tested final read failures return no success and subsequent GET refuses consumption. Concurrent/crash semantics NOT_RUN.
- Independent source review complete; final delivery/readback review and remote publication are the remaining closure actions.
