# Issue #28 — targeted independent closure of IR-01 and IR-02

## Result

**Both Important findings are CLOSED on the final source bytes below. Source-only verdict: PASS_WITH_DEPLOYMENT_GAPS.** No unresolved Critical, Important or Minor finding remains from the initial review and this requested, narrowly bounded follow-up.

This is not an independent deployment approval. `DEPLOYABLE=NOT_DEPLOYABLE_PENDING_ACTUAL_OWNER_FREEZE_AND_DEPLOYMENT_ACCEPTANCE`; no live readiness is claimed. The initial `REPORT.md` and `REPORT.json` retain their original **CHANGES_REQUIRED** verdict and are byte-identical. Their original probe result files also remain unchanged. The requested correction review is recorded here rather than rewriting the failed initial evidence.

| Final reviewed file | SHA-256 |
| --- | --- |
| `delivery/release/after/blocked_candidate_ops/api_candidate_install_r2.py` | `b348859aa5a0e3e94ecb1bc6b431590adc91c7c3346039ea82543f4487fe561e` |
| `delivery/release/after/blocked_candidate_ops/api_candidate_recovery.py` — unchanged | `4db1f38580d972ffe40c08a54e54c671023d18391f854f0b2f09d481e311ce24` |
| `delivery/release/after/external_guard_reference/hk_calendar_candidate_cutover.py` — unchanged | `932c1d1e4d6111faba8cee92f9a3ed0014018f71f986c4237346974260e5e69d` |
| `delivery/hk/after/active_producer_reference/ops/materialize_scheduled_preselection.py` | `e8f412ae44ceb708fb4480a3d20906cfbf057051e14ec49bb70efbca0b82b638` |
| `delivery/hk/after/active_producer_reference/domains/preselection_materializer.py` — unchanged | `1187afe30c1f0614ddcd33f52eb3d82511d98ffe62b3fa5d4bf02f661b1ef290` |

No product or supplied test sources were edited by this reviewer. Only independent review scripts/evidence were written. The two original probes received an optional output-directory argument through an environment variable so their logic could be rerun without overwriting initial results.

## IR-01 — CLOSED

The installer now checks guard bytes locally, without importing recovery. It pins recovery to its compiled expected SHA, verifies the plan's recovery pin against that value, and reads recovery before invoking it. `import_recovery()` uses the configured file path and `_import_pinned_module()`, which reads one regular-file buffer, verifies its SHA, and executes `compile(raw, ...)` on that same buffer. It does not depend on the ordinary import search path, a previously cached recovery module, a later file reread or cached bytecode.

The relevant final code is `api_candidate_install_r2.py:87–119` (checked-source loader), `:218–221` (guard binding without recovery import), `:329–336` (direct receipt verification) and `:340–382` (plan and helper pin order). The guard loader uses the same checked-byte loader at `:387–390`.

The original independent probe, rerun with explicit `ISSUE28_REVIEW_INSTALLER` pointing to the final delivered installer, now reports:

- `drifted_helper_executed_before_rejection=false`;
- expected `recovery helper hash differs from frozen plan` rejection;
- zero service calls and no real active paths touched.

All **five supplied helper-load regression cases passed**: reject helper drift before top-level code; guard/package verification does not import recovery; direct receipt checking pins recovery; the pinned path ignores import-path shadowing; replacing the helper file after verification executes only the already-checked bytes and is rejected on the next load. These tests use synthetic files and explicitly prohibit real subprocess/service access.

Evidence: [original probe rerun](closure/PROBE_RELEASE_LOAD_ORDER.json), [five-case execution](closure/RELEASE_HELPER_LOAD.json), and [raw log](closure/release_helper_load.log).

## IR-02 — CLOSED

The final scheduler isolates a rejected cached HK object into an explicit in-memory `CANNOT_CONFIRM` result (`:246–268`). Missing/invalid cached HK reads are handled separately from the A fallback (`:350–368`). Main filters the rejected HK object out of the publication list (`:384–404`), keeps the rejection reason in the output, and sends every remaining A artifact through the original materialization function. This avoids both the initial whole-batch exception and an attempted overwrite of an existing immutable HK trio.

The original independent assembly probe, rerun with explicit `ISSUE28_REVIEW_HK_OWNER` pointing to the final delivered owner, now returns the eligible one-row A artifact both with and without stale HK reuse. All **eight corrected supplied reuse contracts passed**; 47 unrelated tests were deselected. Their coverage includes old price, missing provenance, foreign source/rows, CLI materialization and preservation of the old HK state.

Because those eight tests assert the primary A pool but do not explicitly assert a **nonempty A lane after HK**, the reviewer added one bounded CLI/real-store probe for precisely that remaining part of IR-02. It invokes the real primary A adapter, the real WeChat builder and the real pool store with synthetic inputs. Four other A lanes retain their legitimate missing/empty contracts. No optional producer implementation was changed or newly certified.

| Cached HK condition | Result | All six A artifacts persisted | Nonempty WeChat lane after HK | Existing HK state |
| --- | --- | --- | --- | --- |
| Mismatched projection | PASS | Yes | 2 rows | Artifact/receipt bytes and manifest entry unchanged |
| Missing artifact | PASS | Yes | 2 rows | Artifact remains absent; receipt and manifest entry unchanged |
| Corrupt artifact JSON | PASS | Yes | 2 rows | Corrupt bytes, receipt and manifest entry unchanged |
| Corrupt receipt hash | PASS | Yes | 2 rows | Artifact, corrupt receipt and manifest entry unchanged |
| Corrupt HK manifest entry | PASS | Yes | 2 rows | Artifact/receipt and corrupt entry unchanged |
| Entire HK cache absent | PASS | Yes | 2 rows | No HK artifact, receipt or entry created |

Every case preserves the stage-eligible primary A row and both WeChat rows, and every A artifact is verifiably readable from the real store. Shared-source and input files remain byte-identical. The overall CLI correctly returns `1 / FAILED` for unresolved HK upstream readiness while A publication completes; HK reports `CANNOT_CONFIRM` and `NOT_PUBLISHED_EXISTING_SLOT_PRESERVED`. This is not a claim that HK has recovered.

Evidence: [original probe rerun](closure/PROBE_HK_REUSE_ISOLATION.json), [eight-case execution](closure/HK_CORRECTED_REUSE.json), [six-condition CLI evidence](closure/HK_ALL_A_PUBLICATION.json), and [independent probe](closure/probe_hk_all_a_publication.py).

## Follow-up execution scope

This follow-up ran **13 supplied focused test instances**, **two original reviewer probes**, and **six cases in one additional IR-02 publication probe**, on Linux x86_64 Python 3.14.7. It did not repeat the initial 182-instance suite or start a new broad review. The coordinator's separately reported full release regressions and final patch replays are not counted as this reviewer's executions.

Commands, explicit final-source environment bindings and fresh results are preserved under `closure/`. [CLOSURE.json](CLOSURE.json) records the machine verdict, final identities, evidence hashes and unchanged initial-report hashes.

## Remaining NOT_RUN / CANNOT_CONFIRM boundaries

All deployment/data limitations in the initial review remain in force:

- Current API/Stage/producer/guard owner identity beyond supplied frozen slices: **CANNOT_CONFIRM**; no current Mac readback.
- Full current auction store/consumer/namespaces and current API dependency closure: **NOT_RUN**; historical support is not the current owner.
- Full `create_app`, middleware, routers and real configuration: **NOT_RUN**; previous API results use exact route AST harnesses.
- HK actual scheduler caller, shared owner, calendar and store runtime identity: **CANNOT_CONFIRM**; only supplied owner slices were exercised.
- Real 10/7 HK price originals and 9/30 eligibility source/capture/PIT: **NOT_RUN**; synthetic fixture dates do not establish historical availability.
- Actual HK Stage selection, real selection run/SHA and genuine empty selection: **NOT_RUN**; missing input remains unbound/null, not a valid zero result.
- Actual release identity, full manifest/inventory and executable final plan: **CANNOT_CONFIRM** pending owner-specific refreezing.
- Independent deployment acceptance, macOS launchd, live API/UI and service readiness: **NOT_RUN**; deployment remains unapproved.
- Natural execution, original-slot capture and complete PIT chain: **NOT_RUN**.
- Per-symbol A coverage gaps and research/news quality-field ownership/semantics: **NOT_RUN** and unchanged.
- Historical date source gaps and the three known P2s: **unchanged and not re-certified**.
- Power-loss durability, unrelated unchanged HK guard CLI and broader host-compromise behavior: **not certified** by these scoped checks.

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`. No Mac, service, collection, Stage run, business data, deployment or external message action occurred during this follow-up.
