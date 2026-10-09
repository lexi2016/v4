# Independent review: three-channel candidate

## Verdict and limits

**REVIEWED_WITH_KNOWN_BASELINE_FAILURE.** I found two P2 validation defects in the proposed candidate, reproduced them with independent synthetic probes, and verified their closure in the final runtime bytes below. No candidate P0, P1, or P2 finding remains open in this reviewed scope. The selected compatibility suite is **not wholly green**: it contains one unchanged baseline failure that is preserved and reported separately.

This verdict covers isolated candidate source, its focused synthetic tests, and source identity. It is not deployment, live API/UI, natural-session, or historical remediation acceptance. Package forward/reverse replay, archive hashes, and remote handoff identity require their separate audit evidence. The reviewer edited no runtime or existing application test file; independent probes, runners, logs, and reports were written only below `three_channel/independent_review`.

## Reviewed identity and scope

The input package is `handoff/manager-three-channel-problems-20261009` from `lexi2016/v4` transport commit `b19eb112bd641ca97cac1246af7c81d8873641f4`. Its declared frozen R3 candidate reference is `ca01c4d0260fecf7aae3c89e96899f36901bf8f7`. The assembled local baseline is Git HEAD `7ca0190a721a7fd0fc0c88b79a872889867d111f`, with runtime root `/workspace/scratch/21926b793c00/three_channel/app`. These are distinct identities; none is presented as the identity of a current deployment.

The independent audit read before-images from baseline Git objects and matched all **1,028** file byte counts, SHA-256 values, and Git blob IDs to their source paths in the captured fixed-commit remote tree. It separately verified all **69** downloaded input-package files against that tree. This reviewer did not perform a new remote lookup; the captured fixed-commit tree is the external identity basis. See [source identity receipt](source_identity_receipt.json).

The worktree contains exactly seven changed runtime paths and six changed/added test paths within the allowed problem scope. `apps/web/node_modules` is a test-only dependency symlink and must not be included in the deliverable. The original US algorithm, reviewed relation rules, scoring thresholds, source collectors, scheduler configuration, service definitions, Stage, Vibe, and BUY paths are outside the changed runtime list.

### Exact reviewed runtime after-images

| Runtime path | After SHA-256 | Bytes |
|---|---|---:|
| `apps/api/v35_api/manager_research_router.py` | `5c2bb2aa5716726295811eee7919dce1e36420ce027589b0e467351b79b7fd7a` | 35556 |
| `apps/web/src/api/managerWorkspace.ts` | `35a879624032cfffb1c3e4afba3c4ae6298df7d5dffb5db90d9ad42142f496ee` | 109896 |
| `ops/run_manager_daily_announcement.py` | `aee0e5c31f30b296864a7ad81263fbc748b65cb9b4d443f83a756019cbc94a38` | 42910 |
| `upstreams/v3_shared_data/shared_data/hk_security_master.py` | `aa197bb1b7e01bd80d1f2e79681f5f17a80d4b4b82143906eae37b71b92f3a5b` | 18863 |
| `v4/manager_research/plan_owner_dispatch.py` | `e4ff0cf9a9aa5af2277ff0c91773dfbb05b656121a65850bc2087b850f8e2bee` | 53361 |
| `v4/manager_research/workspace_announcements.py` | `82187a190f2a308cc193473a9583f0c8edb82782ce45217a1dce8c866f172f0b` | 167803 |
| `v4/manager_research/workspace_plan.py` | `881599ba5a68badd7e18271c57666937f3e954088dfcfcb4c827dcf99419be7f` | 107076 |

The source receipt also records every before SHA-256 and all six test after-images. The final Python, boundary, and frontend command receipts independently record these runtime hashes before and after execution and show no runtime or selected test-source drift during their runs.

## Findings and resolution

### IR-ANN-01 — P2, resolved: source identity could be absent or coerced

The initial new CLI readback validator accepted a self-consistent legacy projection whose catalog SHA and run ID were absent from the manifest, source projection, and consumption chain. Equal missing values satisfied the comparisons, so `_readback` returned `OWNER_READBACK_VERIFIED`. This was a malformed synthetic API response, not a verified production import. The first independent probe failed as expected because no rejection occurred.

The first closure required the consumption schema and identifier shapes. A focused follow-up used an actual synthetic owner API readback, the already-supported legacy receipt form, and a coherently substituted numeric catalog identity. Calling `str(...)` before the shape check still accepted a 64-digit JSON number. That second case was recorded before requesting a final native-string guard.

The final validator requires the original consumption schema, native-string catalog/handoff/judgment SHA-256 values, and native-string source/evidence run IDs, while retaining date, manifest digest, product, owner receipt, current handoff, availability, and safety bindings. Both independent announcement probes now reject their malformed inputs. The existing legitimate current and legacy readback cases also pass, including byte preservation of the legacy receipt. See [initial red probes](boundary_checks.log), [type-closure red probe](boundary_closure_checks.log), and [final boundary result](boundary_final_checks.log).

### IR-US-01 — P2, resolved: arbitrary artifact text could escape through diagnostics

A malformed failed owner DTO with `run_id=None` and non-digest `artifact_sha256` text was copied into `us_mapping_preparation`. The plan still materialized, but the purported artifact field was neither a persisted identity nor a bounded diagnostic. The independent probe demonstrated the text in the actual synthetic POST response.

The final router requires a null artifact when no run exists, or native-string run32/SHA64 values followed by the existing exact persisted-run readback. Invalid values yield a sanitized failed preparation diagnostic while the independent plan continues. The independent regression and the permanent US diagnostic cases pass. The owner algorithm and producer are unchanged.

## Behavior reviewed

**Announcement.** The original capture path copies the producer's corpus, corpus manifest, and batch receipt bytes without JSON reformatting. The fresh synthetic capture reaches the real body validator, saved Reader/Reviewer fixture artifacts, registered handoff, owner import, readback, and workspace consumer. Missing capture/Reader/Reviewer artifacts are rejected before import. Reader and Reviewer identities must be nonblank and distinct after stripping whitespace. Full stored-product validation remains in the existing owner chain; the CLI validates the returned projection without constructing a fake product. The cross-channel case confirms an imported announcement remains consumed while the US lane reports missing input, with exact product/handoff identities, unchanged evidence bytes, and no new source transport calls.

**US mapping.** The existing manual plan POST prepares the original US owner with its existing five-second budget, takes a subsequent server clock for the plan cutoff, and verifies persisted references. GET remains read-only. Future targets skip the US preparation while preserving the prior plan behavior. Missing inputs, owner import/runtime errors, malformed diagnostics, and timeout/busy outcomes remain visible without preventing unrelated plan materialization. A real blocked synthetic source reader verifies the timeout, no plan re-entry, no late publication, and one occupied reader lane. Morning dispatch uses each already-admitted slot for its immutable US trigger: a later slot can observe later-arriving exact-session input, while replay of the same slot stays idempotent. PREOPEN policy and algorithm thresholds are unchanged. The synthetic valid-empty case remains 33/33 configured/available, four reviewed symbols, zero matches, and `full_market_coverage=false`.

**HK screen and frontend.** The screen imports the supplied upstream reader explicitly. It reads one exact-date index observation and returns names plus witnesses derived from the same verified manifest, receipt, and artifact bytes. Missing exact-date entries are distinguished from malformed evidence; no neighboring-date or 695/Futu substitution is introduced. Receipt date, run identity, safety flags, manifest/artifact checksums, and cutoff remain enforced. Missing or unverifiable input produces `CANNOT_CONFIRM`, `counts_known=false`, null counts, and empty candidate arrays. A valid exact-date synthetic master reaches the actual screen but retains missing volume-unit proof as a gap and pending row; it does not invent a tradable selection. The frontend validator accepts this explicit unknown-count contract, rejects unsupported count/readiness claims, and retains the older numeric DTO compatibility path. Layout code is unchanged.

## Fresh verification evidence

All rows below were executed by this reviewer against the frozen source hashes above. Counts from overlapping suites are not added together.

| Check | Result | Interpretation |
|---|---|---|
| Combined focused Python selection, 13 selected modules/node selections | **174 passed, 1 failed**, 175 total; exit 1 | Only the preserved baseline parity failure remains. |
| Three-channel core within that combined selection | **43 passed**: announcement 20, US 11, HK 12 | A subset of the 174 passes, not an additional 43. |
| Independent malformed-boundary probes | **3 passed**; exit 0 | Closes the two P2 findings, including the numeric-identity follow-up. |
| Frontend contract suite | **13 passed**; exit 0 | Includes two DTOs generated by the actual Python HK reader, plus DOM/contract checks. |
| Unchanged-baseline parity reproduction | **1 failed**; exit 1 | Same assertion and `PARTIAL` versus `READY`; all 1,028 baseline files were SHA-verified first. |
| Changed Python syntax and patch whitespace | **11 Python files parsed; `git diff --check` exit 0** | Syntax/whitespace evidence; not a full native import or build. |
| Baseline/input source identity | **1,028 / 69 files verified** | Exact local byte-to-captured-tree match. |

Commands run from `/workspace/scratch/21926b793c00/three_channel`:

```text
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/a154a3323e32/test_env/bin/python independent_review/run_review_checks.py python _final
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/a154a3323e32/test_env/bin/python independent_review/run_review_checks.py boundary _final
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/a154a3323e32/test_env/bin/python independent_review/run_review_checks.py web _final
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/a154a3323e32/test_env/bin/python independent_review/check_baseline_failure.py
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/a154a3323e32/test_env/bin/python independent_review/audit_source_identity.py
```

The command receipts contain the expanded exact argv, working directory, environment overrides, source hashes, return code, elapsed time, and log SHA. See [Python receipt](python_final_checks_receipt.json), [boundary receipt](boundary_final_checks_receipt.json), [web receipt](web_final_checks_receipt.json), and [baseline receipt](baseline_failure_receipt.json).

The environment was Linux with Python 3.14.6, pytest 9.1.1, pandas 3.0.6, pyarrow 24.0.0, FastAPI 0.141.1, Starlette 1.6.0, httpx 0.28.1, and Node v24.19.0. Python used the existing `r3_scoped_loader` namespace bootstrap with parent package attributes linked. This avoids unrelated package-initializer imports missing from the scoped export; it does not supply missing business implementations. The application modules under review, real stores, owner builders, validators, and route functions still execute from the assembled source. Frontend checks use Vitest/jsdom and a test-only dependency symlink. See [environment and syntax receipt](environment_and_syntax.json).

### Preserved failures

The existing `test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection` expects selection diagnostic `READY`; both the unchanged baseline and final candidate produce `PARTIAL`. Its fixture also retains source/selection gaps. I did not weaken this test or classify the selected suite as all passing. See [baseline failure](baseline_failure.log) and [final combined output](python_final_checks.log).

The initial combined run was **172 passed, 2 failed**. Its other failure was the still-in-progress cross-channel fixture's expectation of `INPUT_MISSING` while the actual builder returned `FAILED` because the scoped tree lacks the reviewed/registry JSONs. The writer completed the test with explicitly synthetic, correctly shaped registry inputs already used by the US fixtures, without adding runtime fallback data. The final cross-channel assertion passes. That initial failure and both validation-defect red runs remain in the review evidence. The one existing screen-summary test change from zero to null is the intentional unknown-count contract change, and its frontend counterpart is covered by the contract tests.

## Historical unknowns and unrun acceptance

The package still cannot establish the announcement's first live break among trigger, capture, external handoff, and import. The US live trigger-to-plan causal break also remains `CANNOT_CONFIRM`. Neither binding observations nor the synthetic valid-empty result prove that historical cause.

The supplied 16:01 projection says the requested 20261008 HK index key was absent; the original historical `latest.json` is unavailable, so exact historical input replay remains `CANNOT_CONFIRM`. The later read-only reproduction observed a different index SHA and still no 20261008 key. The 17:23 live session was 20261009 and only exposed `StoreError`; its inner cause remains `CANNOT_CONFIRM`. The candidate preserves missing-input uncertainty and diagnoses an observed input; it does not materialize or repair a missing authoritative master. The 695/Futu snapshot is not accepted as a D1 master substitute.

Full native package imports, full TypeScript typecheck/build, Mac acceptance, current live API/UI reload/readback, real capture/import/collection, shared-state writes, scheduler/configuration/service changes, merge/deployment, BUY/Stage/Vibe behavior, and natural-session outcomes were **NOT_RUN**. The synthetic Reader/Reviewer artifacts are regression fixtures, not formal production review or evidence of actual remediation.

The machine-readable review is [final_review_receipt.json](final_review_receipt.json). Package transport/replay audit evidence is deliberately separate from this source verdict.
