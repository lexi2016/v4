# Independent final review — manager workspace validator restoration

**Verdict: PASS for the isolated, one-file frontend repair and focused regression gate.** No open Critical, Important, or Minor code findings were identified. Full Mac integration, deployment, live API/UI, and natural-run acceptance remain **NOT_RUN**; live readiness remains **CANNOT_CONFIRM**.

Review date: 2026-10-09. Reviewer: `/root/final_code_review`, independently dispatched for the final source/test review. The reviewer changed only files under `review/final/`; production source, original tests, services, business data, and GitHub were not modified by this reviewer.

## 1. Exact scope and identity

Requirements reviewed: `input/FIX_REQUEST.md`, `docs/superpowers/plans/2026-10-09-manager-validator-restoration.md`, workspace `AGENTS.md`, and the supplied original regression classification. The two referenced Mac parent instruction files are unavailable in this Linux workspace. This review follows the supplied workspace rules and does not assume Mac runtime access.

Supplied repository base: `63e75b7af02866c2d19a484b9561416cb13efd84`. This workspace is an isolated source export rather than a local Git checkout. File identities were independently verified below; remote commit/file readback and GitHub synchronization belong to the main agent's separate packaging gate.

Deliverable root: `v4/handoff/manager-validator-restoration-20261009-r1`.

| Role | File or directory | Independently verified SHA-256 |
| --- | --- | --- |
| Frozen active-before reference | `active-reference/apps/web/src/api/managerWorkspace.ts` | `6bd208174c650beb1b089058de458643beb601a97455ff472330984e88dd6d7d` |
| Integrated candidate before repair | `before/apps/web/src/api/managerWorkspace.ts` | `35a879624032cfffb1c3e4afba3c4ae6298df7d5dffb5db90d9ad42142f496ee` |
| Repaired candidate | `after/apps/web/src/api/managerWorkspace.ts` | `2c02d4cff38d749fcad91b892da83029c8269287fbb867a2216f09ef8aa2c43f` |
| Minimal production patch | `runtime.patch` | `51937766ff6f9e53fc17c831c069ac58b3a62e5982700b90f732e2fb442a4190` |
| Final supplemental coexistence spec | `tests/apps/web/src/api/managerWorkspace.validatorRestoration.spec.ts` | `9b67eaf14ddd5828bb81245ec8aaf1c2861e9b4059a857e4e1ae507be611c2b0` |

Actual test source: `/workspace/scratch/0e089a11ee60/work/repaired/app/apps/web/src/api/managerWorkspace.ts`, matching the repaired candidate SHA above. The active reference and integrated-before export also match their corresponding `input/source/` files. The canonical Mac project `/Users/lexi/Desktop/学习/v4_app`, API runtime, and Stage runtime were not inspected; none of these exports is asserted to be the current live identity.

## 2. Findings by severity

| Severity | Open findings | Assessment |
| --- | ---: | --- |
| Critical | 0 | No safety bypass, trading side effect, or destructive change introduced by the patch was found. |
| Important | 0 | Required validators and calls are restored; backward compatibility and the retained three-channel contract pass their focused gates. |
| Minor | 0 | No outstanding source or final test-deliverable issue was found within this review scope. |

A test-evidence consistency observation was closed during review: the initial prepared supplemental spec used a string error matcher, while its final review source used `toThrowError(new Error(error))`. The main agent synchronized the final stricter spec to all intended locations. The reviewer then reran all 109 tests against SHA `9b67eaf…`, with hashes checked before and after execution. The first passing run is retained as superseded evidence and is not the basis for the final verdict.

## 3. Source and contract review

### Minimality and candidate preservation

The production patch targets one path and contains **119 added lines, zero removed lines**. An independent unified-diff parser checked every context byte and hunk length: forward application reconstructs the exact repaired candidate; reverse application reconstructs the exact integrated-before candidate. These checks ran in memory and did not modify either source export. See [patch-review.json](patch-review.json).

An independent TypeScript AST comparison established that:

- All four restored interfaces and all four restored functions match the active reference exactly.
- All 14 supporting declarations used by the restoration remain identical between the active reference, integrated candidate, and repaired candidate.
- All 86 named declarations already present in the integrated candidate are preserved after accounting only for the two restored optional properties and three restored call sites.
- Each restored validator has exactly one intended call site. Nested observation/input validation runs within `validateResearchAttention`; cross-field display validation runs after nested workspace validation and before read-context checks and successful return.

The optional properties remain `observation_only?: IndependentAnnouncementObservations` and `input_diagnostics?: ResearchInputDiagnostics`. Missing fields retain historical compatibility; present `null` or malformed fields enter validation and reject. Evidence: [source-review.json](source-review.json), plus the passing legacy/missing-field and malformed-field cases in [all109.log](all109.log).

### Safety, source, time, and witness enforcement

At repaired source lines 1116–1194, the exact active validators restore these behaviors:

- Observation containers and cards require the existing research-only safety flags. Scored/formal promotion, focus eligibility, qualification, BUY permission, and exhaustive-universe claims remain prohibited for independent observations.
- Observation symbols, source-bound identity, support subject/polarity/quote, duplicate identity, card count, unique-symbol count, and rejection reasons are checked. At least one body reference must bind to the observation's document SHA. Supplied top-level reference `source_url` values pass through the unchanged HTTPS HKEX host validator.
- Observation clocks retain explicit time zones, real calendar-date checks, and hour/minute/second bounds. Valid minute-only ISO clocks remain accepted; hour 24 and rollover dates reject. The card-level PIT order remains `start <= published <= retrieved <= available <= cutoff`. Present reference clocks in the reference/body/directory/mapping objects retain explicit validity and cutoff checks.
- Input diagnostics preserve separate official-announcement, Eastmoney-selection, and US-relation lanes. Counts are validated without converting unknown coverage to zero. Scope input/admitted/rejected sums, target date, membership identity, formal calendar/owner status, non-exhaustiveness, and US assessed-state completeness are enforced.
- Cross-field checks compare shared formal membership/calendar fields without conflating scope counts with focus counts. A promoted observation membership must have the target-date identity and the required existing selection witness; scope fallback applies only when that selection membership is absent. A conflicting existing selection witness cannot be replaced by a convenient scope witness.

These are frontend checks of the supplied DTO and its internal provenance bindings. This review does not authenticate live owners or reconstruct missing source/PIT evidence.

### Retained new contract and type compatibility

The candidate's date binding, daily-channel, execution/readback, screen-count, and standing-relation ordering code remains unchanged. Restored research checks continue to use the workspace/plan target date. They do not substitute the distinct selection/publication binding dates. The candidate's valid unknown-count screen branch remains distinct from a verified numeric zero result.

The final supplemental tests combine the restored observation/input payload with distinct channel dates and an unknown-count screen. They exercise safety, US completeness, calendar SHA disagreement, request-date disagreement, the unknown-count branch, minute-only clocks, hour-24 rejection, and input non-mutation. The original adjacent specs additionally retain verified legitimate-zero and actual synthetic Python DTO coverage.

An independently executed strict TypeScript check of `src/api/managerWorkspace.ts` and its transitive TypeScript imports exited **0 with no diagnostics**, using TypeScript **5.9.3**. This is a changed-source check; a full application build was not run. Exact command and result: [typecheck-run.json](typecheck-run.json), [typecheck.log](typecheck.log).

## 4. Independent test evidence

The final independent run completed at **2026-10-09 13:31:07–13:31:13 UTC**, exit **0**.

| Suite | Passed | Failed |
| --- | ---: | ---: |
| Unchanged `issue8R2.spec.ts` | 76 | 0 |
| Unchanged `managerWorkspace.threeChannel.spec.ts` | 13 | 0 |
| Unchanged `managerWorkspace.dailyAutomation.spec.ts` | 12 | 0 |
| Final `managerWorkspace.validatorRestoration.spec.ts` | 8 | 0 |
| **Total** | **109** | **0** |

Environment: Linux x86_64, Node **v24.19.0**, Vitest **4.1.10**, jsdom, Python **3.12.14**, task-local PyArrow **24.0.0**. Test cwd: `/workspace/scratch/0e089a11ee60/work/repaired/app/apps/web`. One worker, sequential test files, isolated Vite cache, and `PYTHONDONTWRITEBYTECODE=1` were used. The exact command and environment are in [test-command.txt](test-command.txt) and [test-run.json](test-run.json); full test identities and output are in [all109.json](all109.json) and [all109.log](all109.log).

The three original specs and two original fixture files match `input/tests/` in all three prepared application copies: **15/15 byte comparisons pass**. All four final supplemental-spec copies have the same strict matcher SHA. The three renderer support copies match frozen `input/support/researchAttention.active-api.ts`, SHA `9b9ea7aef33e504da7d99f2b16b1e632448a63dfe0971ae275730e6311c5ce3a`. Test/source/support hashes were unchanged across the final execution. See [test-integrity.json](test-integrity.json) and [test-run.json](test-run.json).

The reviewer inspected the main agent's matched reproduction reports: active reference **76 passed**, integrated-before candidate **45 failed / 31 passed**. The 45 failed test identities exactly equal the candidate-only failures in the supplied frozen Mac classification, and every one passes in this reviewer's repaired-source run. These baseline/candidate runs were read and checked by the reviewer, not independently re-executed. See [comparison-review.json](comparison-review.json).

The earlier shared renderer failures and missing-PyArrow setup failures remain separate retained evidence in the main agent's work logs. The correction used isolated support/runtime dependencies; it did not alter a production renderer or any original acceptance test. This Linux test environment differs from the supplied Mac Python **3.14.6** comparison environment.

## 5. Considered behavior left outside this repair

- Replacing `observationTime` with another candidate timestamp helper was declined: the active helper's minute-only acceptance and hour-24 rejection are part of the requested restoration.
- Broadening source-reference schema rules, adding intra-reference clock-order rules, changing membership witness precedence, or adding stricter requirements to historical optional payloads would change the frozen contract. This repair restores its existing checks and leaves those potential policy changes to a separately scoped owner decision.
- Restoring the entire active source file, modifying the renderer, or revising the date/screen/standing-relation code would discard or alter candidate behavior outside the authorized one-file restoration. The additive patch avoids those changes.
- The 14 pre-existing failures in the supplied broader 229-test Mac comparison were not investigated, rerun, or declared resolved. The focused 109-test result does not replace that wider classification.
- Canonical/API/Stage integration, frontend bundling, deployment, service control, Vibe 8910, live data acquisition, A/HK pool policy changes, and BUY/trading behavior changes are outside this review and were not performed.

## 6. Acceptance status

| Gate | Reviewer status |
| --- | --- |
| Exact one-file candidate repair | **PASS** |
| Independent source/patch review | **PASS** |
| Independent focused tests and strict changed-source typecheck | **PASS** |
| Full frontend build / broader frontend matrix | **NOT_RUN** |
| Full Mac/canonical/API/Stage integration | **NOT_RUN** |
| Deployment and service cutover | **NOT_RUN** |
| Live API/UI acceptance | **NOT_RUN** |
| Natural-date/natural-slot acceptance | **NOT_RUN** |
| Current live runtime identity and readiness | **CANNOT_CONFIRM** |
| GitHub synchronization/readback | Main-agent gate; **NOT_RUN by this reviewer** |

The exact repaired candidate is suitable for handoff to the local integration and independent deployment-review stages. A production-readiness decision requires those separate gates and the retained wider failure/PIT evidence.
