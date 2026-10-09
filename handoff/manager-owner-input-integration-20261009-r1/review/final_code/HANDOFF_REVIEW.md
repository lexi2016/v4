# Independent handoff review — owner-input integration R1

## Scope and provisional assessment

Reviewed package: `/workspace/scratch/0e089a11ee60/v4/handoff/manager-owner-input-integration-20261009-r1`.

**The reviewed package accurately separates the scoped two-file repair from the remaining test failures, missing real owner inputs, Mac integration and deployment. No Critical or Important package/source defect was found.** Three minor presentation/size/command-record issues were reported to the coordinator. Final confirmation of their corrected package and remote publication remains pending in this revision of the report.

This review is read-only on package contents, source roots, Git index and branches. It writes this report and uses disposable patch-replay directories beneath the established reviewer root. No business suite was rerun during this handoff review. The production-source verdict remains the separately recorded `FINAL_CODE_REVIEW.md`.

## Package and source verification

The initially reviewed manifest SHA-256 is `add1e67d4af3d201ba0245921ee0975d31cb3c5288616d3b89aa2a3035aff8aa`.

Independent inventory found 132 manifest payloads, 133 physical regular files including the intentionally non-self-listed `MANIFEST.json`, no missing/unlisted payload, and no symlinks. All listed SHA-256 values and sizes matched. Package size was 2,677,802 bytes. All 18 included test/fixture files match the corresponding candidate test bytes.

The only production paths in `runtime.patch`, `production_changes`, `before/` and `after/` are:

| Path | Exact before SHA-256 | Exact after SHA-256 |
|---|---|---|
| `v4/manager_research/connect_selection.py` | `eaa01a13d8065b11cc8397a12edaad8b892f183158aa1f9475d29645dee09d83` | `238f608d8b130aaed6ecfeaea6a66550bf918045c82adeb9aa3ce4f7000ea291` |
| `v4/manager_research/workspace.py` | `a6225ef5583a73c066a5c31400f84e237aaceb63abefcf199cfb8c9b8af7dcdc` | `7a4875f1ab5ba46ac6c18bdaffe2c103a136734fda276fbee918163332844bb0` |

Both package preimages and postimages were compared directly to the reviewed baseline/candidate source bytes. The patch is exactly two files with four added and three removed lines; it contains no service, configuration, API schema, Stage, BUY or Vibe changes.

### `verify_delivery.py` safety and execution

At `tools/verify_delivery.py:24`, reads reject absolute/parent-escaping payload paths and paths resolving outside the intended root. At `:52`, production paths must match the hard-coded two-file allowlist. Actual target checks at `:60` only resolve, read and hash files. The 16 manifest R2 context entries include the two modified targets, for which the chosen before/after hash takes precedence.

At `:72`, patch operations use a new temporary directory containing copies of the package before files. `git apply --numstat` is checked against the allowlist, then forward and reverse application are each compared byte-for-byte to the expected copies. The verifier does not execute a production module or run an owner. Temporary paths were explicitly directed under the reviewer directory using `TMPDIR`; temporary replay does not modify the real source target.

Executed on CPython 3.12.14 with both `PYTHONDONTWRITEBYTECODE=1` and `-B`:

| Source root / expected image | Result |
|---|---|
| `four_function_gaps/work/baseline/app`, `--expect before --check-r2-context` | exit 0, PASS; 132 payloads, 16 R2 context entries, patch apply and rollback PASS, target_writes=false |
| `four_function_gaps/work/repaired/app`, `--expect after --check-r2-context` | exit 0, PASS; same checks |
| `four_function_gaps/work/baseline/app`, deliberately `--expect after --check-r2-context` | exit 1, `TARGET_SHA_MISMATCH: v4/manager_research/connect_selection.py` |

Full invocation for each row used:

```text
/workspace/scratch/0e089a11ee60/four_function_gaps/runtime_locked/bin/python -B
/workspace/scratch/0e089a11ee60/v4/handoff/manager-owner-input-integration-20261009-r1/tools/verify_delivery.py
--source-root <the absolute source root in the table>
--expect <before or after> --check-r2-context
```

The environment additionally set `TMPDIR=/workspace/scratch/0e089a11ee60/four_function_gaps/review/final_code`; the cwd was that reviewer directory. Independent hashes of all non-cache/non-transport source files before and after these three executions confirmed both real source trees remained identical.

## Verification of reported results and boundaries

The reviewer independently parsed all eight final JUnit XML files. The counts and failure-node set differences match the human documents and `evidence/VALIDATION_SUMMARY.json`:

| Group | Baseline | Candidate |
|---|---:|---:|
| Focused new tests, 20 | 17 PASS / 3 FAIL | 20 PASS / 0 FAIL |
| Adjacent owner contracts, 113 | 112 PASS / 1 FAIL | 112 PASS / 1 FAIL |
| Supplied regressions, 103 | 78 PASS / 25 FAIL | 78 PASS / 25 FAIL |
| Existing announcement, 59 | 58 PASS / 1 FAIL | 58 PASS / 1 FAIL |
| Total, 295 per variant | **265 PASS / 30 FAIL** | **268 PASS / 27 FAIL** |

There are zero candidate-only failed nodes. The three baseline-only failures are exactly the repaired wrong-selection reuse, volatile read-clock stale, and persisted-availability missed-stale cases. There are no skipped cases in these XML totals. Reviewer repetitions and the 5 PASS / 2 FAIL plus 4 PASS edge/classification observations are explicitly excluded from 295, preventing double counting.

The following material limitations are accurately disclosed:

- `RESULTS_AND_BOUNDARIES.md:42` retains the two cross-cutoff reuse FAIL expectations and explains the unchanged research-cutoff identity. Fixed-cutoff retries and saved-context GET stability are the proven guarantee; new cutoff can mean a new run.
- `RESULTS_AND_BOUNDARIES.md:55` and `MAC_APPLY_AND_ACCEPTANCE.md:83` distinguish the exact-date master/panel gap from the volume reader's capability gap. Direct source inspection confirmed `_screen_panel_volume_evidence` at `workspace_plan.py:920` and `_screen_supplement_volume_evidence` at `:965` retain NOT_PROVEN; adding arbitrary unit/lot fields does not create a valid owner attestation.
- `RESULTS_AND_BOUNDARIES.md:61` distinguishes the uploaded old CLI from already-fixed Git test support. Their actual source hashes independently match `bfb853fb982e0b2da1024fa942ae9dc5d67fa88a8d112f46054608641129c1ee` and `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38`. The included comparison artifact records expected old receipt validation failure, current-support success, zero readback mutation and no real-data/natural claim. The document does not propose replacing Mac CLI with unverified support bytes.
- `RESULTS_AND_BOUNDARIES.md:92` preserves the actual `RUNNING → SUCCEEDED_EMPTY → FAILED` journal sequence as a failed strict-order assertion. It states that tested final calls/GET reject failures but does not claim concurrency, process interruption or natural I/O semantics were verified.
- `TESTS_AND_ENVIRONMENT.md:7` correctly preserves the actual `PYTHON_314_REQUIRED` failure on Python 3.12.14. Mac/Python >=3.14 results are NOT_RUN.
- Supervisor tests that stopped while copying missing `apps/__init__.py` remain pytest FAIL, while their intended business binding assertions are correctly NOT_RUN. Missing frozen fixtures, V2/calendar contract skew, catalog contract differences and journal/mock cases are separately classified rather than dismissed as one harmless class.
- `CURRENT` is explicitly separated from full business completeness and valid-empty evidence. Missing announcement capture/review/import, target HK V2 binding and exact-day/volume inputs remain CANNOT_CONFIRM/PARTIAL. The four safety flags remain unchanged.

`MAC_APPLY_AND_ACCEPTANCE.md` confines application and reversal to a new verified isolated copy, requires before/after SHA agreement, warns against overwriting parallel changes, and separates source rollback from business-state or service rollback. The documented POST query parameters match the existing router signature at `manager_research_router.py:246`. Mac owner actions and live GET/UI acceptance are instructions for later authorized work, not claimed executed work.

## Findings

### Critical

None found.

### Important

None found in the reviewed source/package. Publication is still pending; no remote synchronization success may be claimed before commit and critical-file readback.

### Minor

**H1 — Over-broad label for the 20 focused cases.** `RESULTS_AND_BOUNDARIES.md:13` originally called all 20 cases an actual application chain. Their actual composition is 12 create_app cases and 8 direct native-consumer cases. The coordinator accepted a wording correction throughout the package. Final corrected bytes remain to be checked.

**H2 — Two redundant full reviewer source-hash snapshots.** `review/final_code/independent_source_before.json` and `final_support_source_before.json` were each 262,855 bytes. They substantially repeat `support_provenance.json`, final per-tree `source_identity.json` and compact reviewer comparison results. The coordinator accepted replacing these two package copies with a SHA/size/source-path index while retaining originals in the working review directory and preserving all FAIL artifacts. This reduces approximately 0.5 MB without discarding an otherwise unrecorded behavior or source identity. Final replacement index remains to be checked.

**H3 — Historical CLI result command shorthand is not a literal runnable command.** `review/announcement/reference_readback_compatibility_result.json` records relative `runtime_locked/bin/python` and `review/announcement/...` paths but its recorded cwd is the baseline app root, where those relative paths do not exist. This is a historical command-metadata limitation, not evidence that the preserved comparison result is false. Document the correct path mapping and identify the old field as shorthand rather than silently rewriting the historical record or describing it as the exact final argv. Main-suite exact argv records are separate and were not implicated.

The prior source-review plan-checkbox observation is resolved by the updated implementation plan: code and test/document steps are completed, Git publication remains pending. That pending state is appropriate.

## Final-package and remote gates

Pending at this report revision:

1. Read corrected focused-case labels, snapshot index and historical-command note; verify their new manifest bytes and re-run only the package validator.
2. Review final remote parent/commit/tree, exact allowed changed paths and critical-file SHA readback after publication. Repository privacy and branch absence were reported by the coordinator but have not been independently re-fetched by this reviewer.

No additional business-suite rerun is required for these documentation-only finalizations. The source candidate is ready for the documented bounded handoff, with real integration/deployment/API/UI/natural acceptance explicitly outstanding.
