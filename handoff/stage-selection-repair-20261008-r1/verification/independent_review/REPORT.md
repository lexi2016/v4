# Issue #28 — independent whole-candidate source review

## Verdict

**CHANGES_REQUIRED for the initially frozen source candidate: 0 Critical, 2 Important, 0 unresolved Minor.** A separately reported runner Minor was corrected by the coordinator during this review. All supplied suites pass, but the two independent probes below reproduce material paths that those suites miss.

This is one independent review of the candidate bytes recorded in [IDENTITY_CHECKS.json](IDENTITY_CHECKS.json), against frozen commit `00524e9050fe212f87911b56eea1c2db719dd94b`. It is not deployment approval. Corrections being prepared after these findings were sent are outside this initial review verdict; their changed hashes and focused closure results must be recorded separately. Once both findings are closed, the appropriate overall ceiling is **PASS_WITH_DEPLOYMENT_GAPS**, never live-ready on this evidence.

Reviewer: delegated `independent_review`, which authored none of the candidate implementation. No agents were dispatched. Product/test originals were read only. Synthetic probes, source copies and logs stayed in local review/temporary directories. No Mac, service, collection, Stage run, business artifact or network action was performed by this reviewer.

## Scope and verification

Read `AGENTS.md`, the authoritative `evidence/README.md`, `evidence/SOURCE_MANIFEST.json`, `work/IMPLEMENTATION_PLAN.md` and `delivery/OPEN_ITEMS_AND_LOCAL_ACCEPTANCE.md`. Reviewed the actual before/after differences, changed functions and their caller/store boundaries across auction, release, HK and reused pool API code. The declined judgments below are part of the result.

Independent checks confirmed all 27 baseline files against size, SHA-256 and Git blob SHA-1. All 76 auction manifest entries, 35 HK entries and 29 pool support entries matched their recorded identities. Four patch applications—two auction owners, release and HK—reconstructed the exact candidate bytes and then the exact frozen before bytes in reverse. See [PATCH_REPLAY.json](PATCH_REPLAY.json).

The installed interpreter was Linux x86_64 Python 3.14.7. These are independent reruns of supplied tests, not 182 newly authored tests:

| Batch | Independent result | Scope |
| --- | ---: | --- |
| Auction, canonical builder | 31 PASS | Real frozen adapter/selector, historical store/consumer, exact route AST HTTP |
| Auction, actual Stage builder | 31 PASS | Same cases against the different actual-owner builder |
| Release, original suites | 26 PASS | Original behavior assertions on synthetic package/plist fixtures |
| Release, P1 regressions | 12 PASS | Guard drift and retained-claim recovery |
| Release, additional boundaries | 20 PASS | Link races, actual child exit after rename, receipt faults, path/type rejection |
| HK | 51 PASS | Actual monolith/ops, pinned canonical shared support, unchanged Stage validator body |
| Pool | 11 PASS | Seven reused cases plus four new fallback cases; real pool storage and exact route AST |

The auction and pool runs retain the declared Starlette TestClient deprecation warning. Full current-owner app startup is not represented by these harnesses. Baseline red counts quoted by the authors were inspected but not rerun by this reviewer; the independent work above verifies the after suites and frozen patch/before identities.

## Important findings

### IR-01 — installer executes a drifted recovery helper before checking its pin

**Location:** initial `delivery/release/after/blocked_candidate_ops/api_candidate_install_r2.py:180`, called at `:316`, before the check at `:319–320`.

**Reviewed installer SHA-256:** `74e25d0a3d0b0f40f93c200d98620d1dea4c507dd40e328a510d4a6f9ce13762`.

`verify_review_receipt()` invokes `verify_guard_binding()` before validating the recovery helper hash from the plan. `verify_guard_binding()` immediately performs a normal `from api_candidate_recovery import ...`. Consequently, drifted recovery source executes before the installer rejects its hash. This is a new load-order regression: the original installer checked the helper hash before its later reviewer-verification import.

The synthetic probe puts a modified recovery helper at the configured helper path and gives the plan a different frozen helper hash. That helper writes a marker at module import. The installer then raises the expected hash-drift error, **after the marker already exists**. No real service or active file is needed to reproduce this.

```bash
references/work/test-venv/bin/python -B work/independent_review/probe_recovery_load_order.py
```

Observed: `drifted_helper_executed_before_rejection=true`, error `recovery helper hash differs from frozen plan`, service calls `0`. See [PROBE_RELEASE_LOAD_ORDER.json](PROBE_RELEASE_LOAD_ORDER.json). The probe defaults to the preserved initial candidate; `ISSUE28_REVIEW_INSTALLER` can explicitly select another installer for focused correction verification.

**User impact:** the new guard gate is partly entrusted to executable bytes whose own required review pin has not yet been checked. An eventual STOP does not undo code already executed during import. This undermines the release task's reject-drift-before-execution guarantee.

**Minimal correction:** perform the guard path/raw-byte check without importing an unchecked recovery helper. Before using the recovery helper, check its own frozen pin and bind execution to those same checked bytes and the intended path. Cover both `verify/review-check` and installation entry paths. Add an import-side-effect regression and a changed-file-after-check case; preserve the existing exact guard checks and claim behavior. Refresh the helper/plan/scope hashes affected by that correction.

### IR-02 — rejecting stale HK reuse aborts valid A materialization

**Location:** initial `delivery/hk/after/active_producer_reference/ops/materialize_scheduled_preselection.py:245–251`; main calls assembly before materialization at `:342–358`.

**Reviewed ops SHA-256:** `25623e0ddd684a9e400aeaea5b9911ff35da7c615bdf3e288dd1fbd76874d331`.

The freshly verified HK projection is built inside an HK-only error handler, but the reused-HK comparison is outside it. A stale/foreign reused object raises `ValueError` from the whole `build_scheduled_artifacts()` call. Valid A artifacts already assembled are never returned or passed to `materialize_preselection_date()`. The author regression at initial `tests/test_hk_split_date_binding.py:536–559` explicitly expects this whole-batch exception, so the green suite currently reinforces the wrong isolation behavior.

```bash
references/work/test-venv/bin/python -B work/independent_review/probe_hk_reuse_isolation.py
```

The same synthetic source without reuse returns A status `V192_CANDIDATE_READY`, one row and `stage_selection_eligible=true`. Adding only a reused HK object with missing historical provenance produces `ValueError: reused HK pool does not match verified exact-source projection`, returning no artifacts. See [PROBE_HK_REUSE_ISOLATION.json](PROBE_HK_REUSE_ISOLATION.json). The actual A adapter executes; only its upstream data is synthetic.

**User impact:** a bad HK source blocks valid A results, contrary to the `AGENTS.md` DECISION_LOCK and the requested A/HK separation. This is more than returning a retryable HK status: the entire writer path is skipped.

**Minimal correction:** isolate rejected HK reuse, expose its explicit `CANNOT_CONFIRM` reason and continue every valid A artifact. Preserve the old HK trio. Merely moving the exception into the existing handler is insufficient if the resulting missing HK object is then written over an immutable existing HK object: the real store raises `conflicting preselection-pool materialization`, and the simple materialization loop would stop before the later WeChat A lane. Skip/quarantine the rejected HK write while preserving complete A output. Verify this at CLI plus real-store level, including the A lane after HK in the list and unchanged old HK bytes.

The eager A/HK pair read at `main():333–341` also aborts before assembly when a reused HK trio is missing/corrupt. That eager pair-read behavior predates this patch; it is an existing boundary of the same reuse path, and should be handled by the same narrow HK quarantine policy, without rewriting unrelated A producers.

## Corrected Minor

**IR-M01, coordinator-reported:** auction `run_focused.py` resolved a relative `--output` in the parent but launched pytest with another cwd, leaving metadata `counts={}` even though product tests ran. The coordinator added `options.output = options.output.resolve()` at line 24. The revised runner bytes are covered by the matching package manifest. The coordinator's same-relative-path rerun records `31 / 0 / 0 / 0`; see `delivery/verification/HARNESS_RELATIVE_OUTPUT_FIX.json`. This reviewer inspected the correction/evidence and independently obtained correct counts using absolute output directories. No product finding remains from this runner issue.

## Boundaries that passed this source review

- **Auction semantics:** original values reach both different owner adapters; missing, nonpositive, invalid and nonfinite previous close remain null with a reason. Observed flat price remains numeric zero. The final assignment after `**card` prevents the generic last/open fallback from replacing the daily auction change. No new score formula or Top10 rule was introduced. Restored real gap values do change new scores/ranks, and the candidate reports that effect. Whole rows participate in run identity, and old slot conflicts prevent silent historical replacement.
- **Auction persistence:** the supplied historical store persists the complete selection envelope in the manifest, with receipt and identity verification. Its legacy CSV remains a fixed projection. This supports the three-file candidate without inventing schema/API edits; it does not establish that absent current-owner store/consumer bytes behave identically.
- **Release claim path:** for the reviewed guard, candidate-link plus rollback-link failure retains the exact claim and a SHA-bound failure/reservation receipt. Recovery validates path shape, private directory, regular-file bytes and SHA, publishes a checked snapshot via exclusive link, and refuses existing/intervening targets. The source tests include a real POSIX child exit after rename. Explicit receipt selection is required; there is no discovery of the “latest hidden file.” Old same-identity receipts are retained, not automatically treated as evidence of the latest attempt. No age-based expiration contract was supplied, so age alone is not reported as a defect.
- **HK dates and provenance:** the new explicit target/price/eligibility arguments are checked with the original calendar APIs. Missing/unknown/wrong sessions, unsupported old reader, foreign source identity and incomplete split-date provenance fail closed. Capture text is decoded from source provenance, retains its precision/timezone, and is checked against the eligibility date. The Stage validator is unchanged. IR-02 is the exception to the otherwise demonstrated HK-only failure handling.
- **Pool reuse:** the exact API fallback retains local A ownership, uses an integrity-verified target-date HK trio, computes complete counts/fingerprints before pagination and refuses wrong-target or corrupted HK sources. Tests and support substitutions are disclosed. No additional pool product edits were introduced in this batch.

## Explicitly declined judgments and deployment gaps

| Item | Status and reason |
| --- | --- |
| Current API/Stage/producer/guard identity | CANNOT_CONFIRM beyond the frozen supplied slices; no current Mac readback |
| Full auction current-owner dependency closure | NOT_RUN: actual selection facade/store/consumer/namespaces and current API are absent; historical support is not the runtime owner |
| Full API `create_app`, routers/middleware/config | NOT_RUN: route AST harnesses exercise exact selected functions, not application startup |
| HK actual scheduler caller/shared owner/calendar/store identity | CANNOT_CONFIRM: only two actual-owner source files are supplied; canonical support is separately identified |
| Real 10/7 HK price inputs and 9/30 eligibility provenance | NOT_RUN: raw originals and complete source trios are absent; absence from this package does not prove absence on Mac |
| HK Stage selection and genuine empty selection | NOT_RUN: the strict validator was exercised, but no actual Stage selection run was produced; input failure must remain null/missing-run |
| Release full identity, manifest, inventory and executable final plan | CANNOT_CONFIRM: source-only plan is correctly not executable; old identity pins require actual-owner refreezing |
| Independent deployment approval, macOS launchd, live API/UI | NOT_RUN and NOT_DEPLOYABLE on this review; temporary fake service protocols are not service evidence |
| Natural execution, original-slot capture and complete PIT chain | NOT_RUN: cannot infer natural verification or historical availability from offline success |
| A missing 6–7 source rows and research/news numeric semantics | NOT_RUN: per-symbol diagnostics and the authority/quality-field contract are absent; no alias/zero-fill fix is justified |
| Historical 8/25, 9/30 and 10/7 source gaps / three known P2s | Remain CANNOT_CONFIRM or their recorded P2 state; not repaired or re-certified here |
| Power-loss durability, broader unchanged HK guard CLI, adversarial host compromise | Not certified: only the scoped API guard load/CAS/claim behavior and process-exit faults were exercised |

All safety statements remain `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`. This review must not be used to alter the old FAIL/NOT_DEPLOYABLE receipt or to relabel synthetic support as live evidence.
