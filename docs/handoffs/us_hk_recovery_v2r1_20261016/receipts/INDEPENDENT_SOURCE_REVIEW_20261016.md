# Independent source candidate review

Reviewer: independent Luna Max reviewer, read-only outside this receipt.
Scope: source candidate only, per `SCOPE.md`; no runtime, service, configuration, deployment, scheduler, trading, or financial assertion verification.

## Verdict

- `REVIEWED=PASS`
- `TESTED=PASS`
- `BEHAVIOR_VERIFIED=PASS` for the frozen source-candidate behavior exercised by the focused suites.
- Candidate `PASS`; no actionable P0, P1, or P2 findings.

The source receipt's 667 stocks / 1,003 relations reconcile to 757 `CLOSED_RESEARCH_SCOPE`, 25 `CLOSED_EXCLUDED_SCOPE`, and 221 `OPEN`. The 782 combined closures are explicitly distinguished from accepted mappings. The implementation keeps the original catalog and old 700-relation overlay SHA-bound, records `status_crosswalk=NOT_ESTABLISHED`, and retains zero independent fact acceptance plus the PIT, prediction, event-test, and evidence-gap markers. The loader binds all 1,003 records to original relation order and symbols; summary output omits the full record by default, while exact-RID lookup returns the full record. Relevant code: `us_mapping_catalog.py` lines 302-449, 526-555, 558-615, and `Workbench.vue` lines 529-590.

## Findings and limits

No actionable correctness, security, or behavioral-regression finding was found in the frozen candidate diff.

`CANNOT_CONFIRM`: factual correctness of the financial assertions, PIT validity, prediction validity, and event/data-test validity. The package itself marks independent fact acceptance as 0, historical PIT as `NOT_VALIDATED`, prediction as `UNTESTED`, and event/data tests as `NOT_RUN`; this review does not promote those claims.

`CANNOT_CONFIRM`: live API/UI runtime, deployment, GitHub synchronization, or natural-slot behavior. Those are outside this source-candidate review and remain for the separate integration phase. The targeted API contract test runs through the in-process router only.

The writer receipt records repository typecheck exit 2 for existing unrelated errors in `managerWorkspace.attention.spec.ts`, `api/us_factor.spec.ts` (missing fixture), and `ManagerSelectionView.spec.ts`; no changed mapping source was reported. This review did not rerun repository-wide typecheck.

## Independent evidence

The current source and builder SHA-256 values below match `SHA256_INVENTORY.json`. The source patch reverse-check succeeded against the current files. Recomputed preimage SHA-256 values match `PREIMAGE_SHA256.json`. The immutable inputs match the frozen identities.

| Path | SHA-256 |
|---|---|
| `v4/manager_workbench/us_mapping_catalog.py` | `ec327cb99e72b9dd982f1238e459b79b657697501f02ac66a598752a94245031` |
| `tests/manager_workbench/test_us_mapping_catalog.py` | `1f316adee7ad4ef4539ba8fc9b1dcf6d22d57aa7f3a07a3b2845d5b53272eaf3` |
| `apps/web/src/manager-workbench/Workbench.vue` | `7e77b6602400ecec58865dfc19b7a7bc7ae3c234c65bf28f93ec3a258ab96478` |
| `apps/web/src/manager-workbench/types.ts` | `93d29e1dde2686f85f4f17159e5edc023cf6d59a5d9bf8473eab45f5f4626939` |
| `apps/web/src/manager-workbench/__tests__/us_mapping_catalog.spec.ts` | `7b90fa8ea13df10c0bbb398af59976e9249f11c90fe00297e88c0938e5e41b6d` |
| `docs/handoffs/us_hk_recovery_v2r1_20261016/builders/build_recovery_overlay.py` | `b4c76ce4d1d437c9a161a4862d0360ae3656b52c3e656a66e99d64135658beb1` |
| `v4/manager_workbench/research_data/us_hk_667_recovery_overlay_20261016.json` | `3289f0329f0fe2e447a70386341790cb9821df2e76d13a650143fe07f9e9e91c` |
| Immutable original catalog | `3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671` |
| Immutable prior 700 overlay | `d45d44fb074fc82923a0af5e37a8d645923a84acb48dc2bb1794b1f4ddc98c69` |
| `diff/SOURCE_DIFF.patch` | `31700c81e81e92b0e53d263a20ce6c65691de2ec29979710ee5d4ea6cbff15d5` |
| User recovery ZIP identity | `48f1124c10ed3440c22910a9125038748c08d673fc3ec543635cc9aae0b344d4` |

The user ZIP was present at the frozen path (508,906,833 bytes); the focused backend suite's reproducibility branch therefore ran and confirmed that the builder's canonical output matches the pinned projection. The full raw-ZIP integrity audit was not repeated.

## Tests rerun by reviewer

1. From `/Users/lexi/Desktop/学习/v4_app`:

   ```sh
   PYTHONPATH=/Users/lexi/Desktop/学习/v4_app .venv/bin/pytest -q --basetemp=docs/handoffs/us_hk_recovery_v2r1_20261016/tests/pytest_tmp tests/manager_workbench/test_us_mapping_catalog.py
   ```

   Exit 0: 17 passed in 13.49s; one Starlette/httpx deprecation warning.

2. From `/Users/lexi/Desktop/学习/v4_app/apps/web`:

   ```sh
   npm test -- src/manager-workbench/__tests__/us_mapping_catalog.spec.ts
   ```

   Exit 0: 1 test passed in 834ms.

3. From repository root:

   ```sh
   git apply --reverse --check docs/handoffs/us_hk_recovery_v2r1_20261016/diff/SOURCE_DIFF.patch
   ```

   Exit 0; the frozen patch matches the current candidate against its preimages.

Focused backend coverage includes closure/exclusion/open and no-edge boundaries, summary versus exact-RID full payload, old 700 history retention, tamper rejection, builder reproducibility, and the in-process API route (`test_us_mapping_catalog.py` lines 386-513). The frontend test covers on-demand loading, exact-RID detail, status display, and safety-limited rendering.
