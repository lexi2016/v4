# Fresh independent source review — V4 owner-input integration candidate

## Assessment

**READY AS THE SCOPED REPAIR CANDIDATE, subject to accurate delivery claims. No Critical or Important defect introduced by the two production changes was found.** This is approval of the exact two-file candidate under the fixed-input, fixed-date-binding, fixed-research-cutoff contract. It is not deployment approval, Mac runtime acceptance, natural-run acceptance, or confirmation that the four original business-input gaps have been filled.

The independent final-support run reproduced the baseline's three behavioral failures and observed all 20 focused tests pass on the candidate. Additional reviewer-local tests established immutable prior-run preservation for both scheduled kinds and both date fields, retained native V1 semantics, and same-cutoff reuse when the V2 witness clock advances. Two deliberately stronger cross-cutoff reuse expectations failed and remain recorded as FAIL. Follow-up diagnostics confirmed the only changed projection inputs were the two research-cutoff fields; those failures do not establish a defect in this patch or authorize weakening the original cutoff contract.

**Delivery documentation and remote Git synchronization have not yet been reviewed in this source report.** They require a separate final readback before those claims can be accepted.

## Scope and exact identity

- Baseline: `/workspace/scratch/0e089a11ee60/four_function_gaps/work/baseline/app`.
- Candidate: `/workspace/scratch/0e089a11ee60/four_function_gaps/work/repaired/app`.
- Frozen candidate reference: `a7f5d09fb19de10564925757207977aadc080cc1`.
- Governing production preimages: `input/package/code/r2_chat_patch_target`, not a different canonical/API/Stage snapshot sharing that Git commit.
- Read requirements: `CHAT_REPAIR_REQUEST.md`, `FOUR_ISSUE_MATRIX.md`, `DAY_RUN_REUSE_AND_INTEGRATION.md`, and `docs/superpowers/plans/2026-10-09-manager-owner-input-integration.md`.
- Source roots, index and branches were read-only throughout this review. Reviewer files and all new synthetic test artifacts were written only beneath `review/final_code`.

| Production path | Baseline SHA-256 | Candidate SHA-256 |
|---|---|---|
| `v4/manager_research/workspace.py` | `a6225ef5583a73c066a5c31400f84e237aaceb63abefcf199cfb8c9b8af7dcdc` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` |
| `v4/manager_research/connect_selection.py` | `eaa01a13d8065b11cc8397a12edaad8b892f183158aa1f9475d29645dee09d83` | `238f608d8b130aaed6ecfeaea6a66550bf918045c82adeb9aa3ce4f7000ea291` |

Independent SHA comparison found only these two source paths differ between the assembled baseline and candidate. Both baseline production files match the exact package preimages. A final provenance readback checked 1,065 expected support/attachment paths using `support_provenance.json`, `import_support_adaptation.json`, and `api_support_alignment.json`: baseline had no missing or mismatched path; candidate differed only in the two intended production paths. This verifies the assembled test tree against the recorded recipe. It does not authenticate that recipe as the currently running Mac process.

The first 20-test run preceded the final identical support alignment of `v4/manager_research/announcement_observation.py`. That source changed in both trees to frozen API SHA `8e58cab8e9e398d7c628c2f994a5005442d3a6c5ba5f218a155d949b8af74f54`. The final 20-test rerun used that aligned support; `api_support_alignment.json` SHA was `a51bc22bb3de4f8525366b9397272222d4f0ead357e3c5fd01116f9a6a9c2ec8`. Production/support text did not change during the final matched-root run. Bytecode and transport staging were excluded from the reviewer source comparison; no claim about unrelated processes' bytecode-cache activity is made.

## Strengths

### 1. The clock correction is tied to the native V2 contract

At `connect_selection.py:106`, the existing consumer explicitly calls the native reader with `require_v2=True`. It does not inject the research cutoff as a fake observation clock. At `connect_selection.py:108`, the existing checks independently reject wrong source date/market, missing timestamps, and persisted acquisition or availability after cutoff.

The native V2 reader validates the persisted capture/publication chain before constructing its source. `domains/manager_research_evidence.py:244` checks the publication digest, `:252` reads persisted acquisition/availability, and `:258` obtains the separate read witness. Its output at `:269` retains acquired/observed/available timestamps and puts the witness in `read_at` at `:271`.

The change at `connect_selection.py:189` therefore removes the correct volatile field from identity-bearing `membership_source`. It retains persisted `available_at`, acquisition/observation times, source SHA, owner identity, run identifiers and artifact references. The diagnostic top-level source still exposes `read_at`. This fixes both the false-stale case and the opposite missed-stale case without removing real provenance from admitted material cards.

Native V1 is different: `domains/manager_research_evidence.py:366` obtains the witness and `:374` calls that witness `available_at`; V1 has no `read_at`. The patch does not globally redefine that field. `read_scope` requires V2, and `_scope_error` at `connect_selection.py:155` accepts only target-date V2 semantics; previous-session capture is expressly rejected for formal eligibility at `:160`. A reviewer-local test read a real synthetic V1 authority twice, confirmed its native witness-based `available_at` changed, and confirmed that V1 could not enter the target-date V2 card path.

### 2. Scheduled reuse now enforces the same complete date identity as GET

The added equality at `workspace.py:1172` sits inside the existing store transaction, after preparation with the current injected readers. Reuse still requires a verified original-owner attempt, matching execution kind, input identity and semantic version, and admissible generation/cutoff/deadline timestamps.

`get_workspace` constructs the three normalized fields at `workspace.py:488`. Ordinary GET already checks the full saved/current binding at `:1031`. The scheduled change closes the case in which `selection_date` changes while the admitted projection identity happens to be equal. Unknown legacy bindings cannot silently match a newly prepared complete binding.

The positive retry tests confirm unchanged complete bindings keep the same run and SHA without rewriting manager files. Reviewer tests also changed each of `selection_date` and `announcement_date` for both `SCHEDULED_MORNING` and `SCHEDULED_PREOPEN`: the corrected call created a distinct run, all prior immutable plan/attempt bytes remained identical, and default GET read the new correct binding as CURRENT.

### 3. Source admission, genuine stale guards and safety remain visible

The candidate does not add collectors, producers, import paths, service routes or UI layers. The only production diff is one source-field exclusion correction and one equality condition. Existing target authority binding, market/date checks, source hashes, original owner attempts, deadlines and ordinary stale comparison remain intact.

The focused tests exercise the actual application factory, private-package manager service and in-process GET/import paths where stated. They also include direct native-consumer tests; the 20 tests must not all be described as HTTP integration cases. The imported announcement fixture is explicitly synthetic, but exercises the original registered capture/Reader/Reviewer/import contract and rejects changed Reader bytes on subsequent GET. HK negative cases preserve unbound/wrong-date/wrong-owner/altered-chain/late-input failures. The app-level screen case retains exact D-1 master identity and unproven volume-scale evidence as PARTIAL with unknown candidate count.

The empty-root plan can legitimately be CURRENT as a verified saved PARTIAL product. This does not turn zero stocks into VALID_EMPTY or prove missing business inputs. The tests assert owner attempt PARTIAL, visible gaps, false natural-run status and the unchanged four safety flags.

## Findings by severity

### Critical

**None found in the scoped production diff.**

### Important

**No Important production defect introduced by the scoped diff was found.** The following is an important acceptance/claims limitation, not a request to broaden the patch:

**I1 — Cross-cutoff scheduled reuse is not part of the proven idempotency guarantee.**

- Locations: `workspace.py:1164`, `workspace_projection.py:475`, `workspace_projection.py:492`, `workspace_plan.py:158`.
- Concrete trigger: with identical synthetic source bytes and dates, call a scheduled owner at 08:00:00, then at 08:00:30; equivalently 09:28:00 then 09:28:30 for pre-open.
- Observed result: two reviewer expectations of ALREADY_MATERIALIZED failed; the owner produced a new CURRENT run and a new input identity.
- Independent diagnosis: a pass-through trace of the real projection found exactly `.market_screen.data_context.research_cutoff` and `.plan_context.research_cutoff` differed in the projection inputs. The full screen object is hashed. The separate V2 witness correction is working: holding the owner research cutoff fixed while advancing its read witness and completion clock passes for both scheduled kinds and reuses the same immutable run.
- Assessment: the cross-cutoff calls have different evaluation contexts. The supplied evidence does not establish that those contexts may safely be collapsed. Preserve both FAIL records and state that same binding plus same cutoff is idempotent; a later cutoff may generate a new original-owner run. Do not claim all same-source refreshes across time reuse one product, and do not remove cutoff fields merely to make the stronger expectation pass.

### Minor

**M1 — The implementation-plan status boxes were stale when read.**

- Location: `docs/superpowers/plans/2026-10-09-manager-owner-input-integration.md:46`, Tasks 2–4.
- Concrete trigger: the source changes and final focused tests exist while those task checkboxes still show pending.
- Recommendation: update the plan/evidence index during final delivery so readers can distinguish completed code and offline tests from pending documentation/Git readback and explicitly NOT_RUN Mac gates. This is documentation bookkeeping, not a source blocker.

The pytest warning about the locked Starlette/httpx TestClient combination is recorded. No dependency change is requested for this two-file repair.

## Independent execution and results

Runtime: `/workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python`, CPython 3.12.14, Linux x86_64. The project declares Python >=3.14; the available interpreter is outside that declared range. Every reviewer pytest command used `PYTHONDONTWRITEBYTECODE=1`, `-p no:cacheprovider`, and a distinct `--basetemp` under `review/final_code`. No real source transport, securities data or production owner state was used. Synthetic app fixtures deny external socket transport and close the exercised manager service.

| Run | Result | Meaning |
|---|---|---|
| Initial support, baseline focused suite | 17 PASS / 3 FAIL | Three expected behavioral failures; retained as pre-final-support evidence |
| Initial support, candidate focused suite | 20 PASS | Superseded by final-support rerun for final claims |
| Final aligned support, baseline focused suite | 17 PASS / 3 FAIL | Scheduled wrong-selection reuse, witness-clock false stale, persisted-availability missed stale |
| Final aligned support, candidate focused suite | 20 PASS | All scoped regression/admission tests pass |
| Reviewer-local additional edge suite | 5 PASS / 2 FAIL | Four changed-binding immutable-history cases and native V1 case pass; two stronger cross-cutoff reuse expectations fail |
| Reviewer-local clock classification suite | 4 PASS | Both same-cutoff witness retries reuse; both advancing-cutoff cases traced to unchanged screen-context semantics |

The final 20-test command, run separately from each corresponding app root, was:

```bash
PYTHONDONTWRITEBYTECODE=1 \
PLAN_AUDIT_APP_ROOT="<baseline-or-candidate-app-root>" \
V4_TEST_APP_ROOT="<same-app-root>" \
/workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python -m pytest \
  -q -p no:cacheprovider \
  --basetemp="<review/final_code/tmp_baseline_final-or-tmp_repaired_final>" \
  --junitxml="<review/final_code/baseline_final.xml-or-repaired_final.xml>" \
  tests/test_manager_app_plan_identity_20261009.py \
  tests/test_manager_app_announcement_chain_20261009.py \
  tests/test_manager_hk_authority_app_wiring_20261009.py
```

Exact working directories, environment variables and argv for all six runs are saved in `review_commands.json`. Result files: `baseline_final.log/xml`, `repaired_final.log/xml`, `edges_final.log/xml`, `clock_classification.log/xml`. The two reviewer source files are `test_independent_edges.py` and `test_clock_boundary_classification.py`; they remain review evidence rather than an additional production patch. `independent_final_verification.json` and `independent_provenance_readback.json` record source and provenance checks. No failed result was deleted, marked xfail, or relabeled as PASS.

## Behaviors declined to judge

| Behavior or claim | Status and reason |
|---|---|
| Real 2026-10-08 announcement capture, distinct actual Reader/Reviewer work and import for selection 2026-10-09 | CANNOT_CONFIRM: no real artifacts/state; synthetic contract coverage cannot establish those identities or analysis quality |
| Real exact-target 2026-10-09 HK Connect V2 authority root, membership and cutoff provenance | CANNOT_CONFIRM: no authenticated current owner root/manifest/state in this environment |
| Real 2026-10-08 master, HK02 panel and volume-unit/scale attestation | CANNOT_CONFIRM/PARTIAL: offline tests demonstrate required contract and retained gaps, not the missing business artifacts |
| Historical 2026-09-30 independent success | CANNOT_CONFIRM: required independent runner receipt is outside the located evidence; absence here is not evidence that the reported run did not exist |
| All real four channels fully working, or empty stocks being a verified full-scope empty result | CANNOT_CONFIRM: current input omissions remain; saved PARTIAL CURRENT is not full channel completion |
| Identical source files across a later research cutoff always reuse one scheduled run | Not promised: actual observed behavior creates a new run; see I1 |
| Current Mac canonical/API/Stage process identity, Python >=3.14 behavior, port 8873 HTTP/UI | NOT_RUN: this was a Linux reconstructed-source test environment, not the Mac runtime |
| Scheduling admission, launchd/service configuration, natural morning/pre-open operation | NOT_RUN: direct owner/dispatch-branch tests do not establish scheduler admission or natural execution |
| BUY/Stage/Vibe 8910 business/runtime acceptance | NOT_RUN; no changes or service actions were made, and test safety flags stayed unchanged |
| Complete repository test-suite health | Not independently claimed: the reviewer ran the bounded suites above; parent-wide additional failures require their own exact evidence/classification |
| GitHub push/remote critical-file SHA readback, deployment, rollback execution | Not part of this source review; final documentation and remote evidence remain separately reviewable |

## Recommendations

1. Deliver only the two exact production changes as the minimal patch, plus the necessary tests and concise source/provenance/result evidence. Keep reconstructed support adaptations explicitly outside the production overlay.
2. Make fixed full date bindings and fixed research cutoff explicit in the same-input/reuse acceptance statement. Preserve the stronger cross-cutoff FAIL observations without treating them as permission to weaken PIT checks.
3. Preserve separate statuses for candidate code review, isolated tests, actual integration, Mac runtime/API/UI and natural operation. The candidate is ready for controlled owner integration review; it is not a deployed or business-complete result.
4. On the authorized Mac integration step, compare exact preimage SHAs, verify actual canonical/API identities, supply the missing owner artifacts through their existing contracts, and perform GET readback against saved run/product/input SHA. Keep real missing or changed sources fail closed.

## Readiness statement

The exact two-file repair is a sound candidate for the stated fixed-context defects. The evidence supports stable V2 identity under witness-clock changes, preserved invalidation under persisted availability changes, and complete scheduled date-binding comparison with immutable-run preservation. There is no evidence here that the missing real owner inputs have become available, that current Mac processes run these bytes, or that deployment/API/UI/natural acceptance has occurred.
