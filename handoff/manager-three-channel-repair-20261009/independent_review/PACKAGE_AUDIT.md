# Independent package audit: three-channel repair

## Verdict

**REVIEWED_PRE_FINAL_CHECKSUM_AND_REMOTE_READBACK.** The frozen package payload matches the source and tests covered by the independent source review. Its three patches apply and reverse correctly. The corrected host procedure runs successfully in a fresh, disposable reconstruction of the complete scoped baseline. No package finding remains open in the audited scope.

One P2 handoff defect, **IR-PKG-01**, was reproduced and closed: the frontend command needed an explicit working directory. The package owner corrected only `HOST_HANDOFF.md` and the corresponding explanation in `TESTING.md`. Runtime source, application tests, the Vitest configuration, and the source manifest did not change for this closure. The failed execution remains available below.

This audit precedes the addition of this report, its evidence, the final package checksum list, ZIP creation, and remote publication readback. It does not certify those later artifacts. The source verdict remains [REVIEWED_WITH_KNOWN_BASELINE_FAILURE](FINAL_REVIEW.md); the broader compatibility suite still has the independently reproduced, unchanged baseline failure.

## Audited snapshot and identity

| Item | Independently checked result |
|---|---|
| Package | `manager-three-channel-repair-20261009` |
| Files in the frozen snapshot | **189**, totaling **2,759,556 bytes** |
| Source manifest SHA-256 | `ccd38bc88ab8aa2231e844ef581470bea32545f7d48f988996dc9290f9689e9d` |
| Fixed source transport commit | `b19eb112bd641ca97cac1246af7c81d8873641f4` in `lexi2016/v4` |
| Declared prior R3 candidate | `ca01c4d0260fecf7aae3c89e96899f36901bf8f7` |
| Isolated local Git baseline | `7ca0190a721a7fd0fc0c88b79a872889867d111f` |
| Changed payload | **7 runtime files and 6 test files**; 8 before-images and 13 after-images, 21 payload files total |
| Unchanged test support | **16 files**, matched to fixed-source blob identities and the reviewed application bytes |
| Preserved Issue32 references | **3 files**, matched to baseline bytes |
| Reused verification tools | **2**, byte-identical to their declared captured source paths |

Every runtime/test after-image matches both the independently reviewed SHA-256 and the current isolated candidate file. Every existing before-image matches its SHA-256, size, Git blob ID, and declared path in the captured fixed-commit tree. The five added tests correctly have no before-image. The test-source manifest agrees with the six test rows in the source manifest. Each patch SHA and profile file count also matches its manifest entry.

The source roles remain distinct. In particular, the API profile includes the original announcement owner reference and HK upstream source alongside the R3 API candidate. This is an explicitly assembled source preimage, not a claim that all six paths are present in a current API or worker process. This reviewer used the captured fixed-commit GitHub tree and did not perform a new remote lookup during the package audit. The prior independent source audit already verified all 1,028 baseline files and all 69 input-package files; see [source identity receipt](source_identity_receipt.json).

The complete file-to-SHA map for the audited 189-file snapshot is in [package_audit_receipt.json](package_audit_receipt.json). The snapshot remained unchanged throughout the final flow and the subsequent read-only evidence checks.

## Patch application, support files, tests, and rollback

The packaged read-only verifier passed. The packaged replay tool independently reconstructed each profile, checked its preimage, applied it, verified its after-image and file set, reversed it, and recovered the original file tree. The reviewer then exercised the host process against a separate full baseline reconstruction, rather than relying only on the replay tool's result.

| Profile | Changed files | Forward check/application | After verification | Reverse check/application | Restored before verification |
|---|---:|---|---|---|---|
| `api_r3_candidate` | 6 runtime | PASS | PASS, including 3 preserved files | PASS | PASS |
| `web_r3_candidate` | 1 runtime | PASS | PASS | PASS | PASS |
| `test_delta` | 6 tests | PASS | PASS | PASS | PASS |

The full-flow source copy began as a Git archive of the isolated baseline. All **1,028** file hashes were checked before proceeding. The reviewer removed the 16 known test-support files only within that new disposable copy so the documented support-copy step had real missing files to restore. All three profile before-checks passed, the patches were applied in the documented order, and all 13 after-images matched the manifest.

The exact Python support-copy body from `HOST_HANDOFF.md` then restored all 16 missing files. Three additional isolated scenarios verified its important failure behavior:

- With one already-identical file and 15 missing files, it preserved the existing bytes and added the missing files. Repeating the copy added zero files.
- With a conflicting existing file placed after otherwise missing entries, it failed before writing any pending file. The preflight loop therefore did not leave a partially copied set in this case.
- With an `apps` parent symlink pointing outside the temporary target, it rejected the escaping destination and left both the target's file snapshot and the outside directory unchanged.

The reviewer executed the **exact corrected shell block from host section 5**, using the handoff directory as the starting working directory. The shell block itself changes the frontend working directory to the new temporary source's `apps/web` directory.

| Verification in that reconstructed copy | Result |
|---|---|
| Packaged scoped Python runner | **43 passed, 1 existing warning**, exit 0; 8.78 seconds |
| Packaged Vitest command, two named suites | **25 passed**, exit 0 |
| After-image hashes following tests | All 13 unchanged |
| Reverse order | `test_delta`, then `web_r3_candidate`, then `api_r3_candidate` |
| Full tree after reverse and removal of test-only JUnit/symlink | **All 1,028 baseline file hashes restored exactly** |
| Disposable full-flow directory | Removed after verification |

The Python 43 are the existing three-channel core: announcement 20, US mapping 11, and HK reader 12. The frontend 25 are the new 13 plus the existing daily-automation 12. These are fresh executions of overlapping cases already reported elsewhere; they must not be added to the source review's 174 passing compatibility cases or its separate 13-case frontend check. The known baseline parity failure is outside this 43-case core and remains documented in the source review.

Evidence: [provided verifier](package_provided_verify.log), [provided three-profile replay](package_provided_replay.log), [actual host test output](package_host_tests.log), [host Python JUnit](package_host_core_results.xml), and the exact command/working-directory/environment/log-hash records in the [audit receipt](package_audit_receipt.json). The extracted [support-copy body](host_support_copy_snippet.py) and [host test shell block](host_test_commands.sh) record the text actually exercised.

## IR-PKG-01 — P2, resolved: frontend command lacked an explicit cwd

The first full host-flow attempt ran the documented Vitest command from the package directory. All required environment variables and the clean reconstructed source were present, and the Python core had passed. Vitest found the two named suites but failed before collecting their test cases:

```text
Cannot find module '/src/api/managerWorkspace.threeChannel.spec.ts'
Cannot find module '/src/api/managerWorkspace.dailyAutomation.spec.ts'
Test Files  2 failed (2)
Tests  no tests
```

The initial instructions did not state a working-directory step for that command. A separate fresh disposable copy demonstrated that the same source, tests, configuration, environment, and argv passed **25 cases** when launched from its `apps/web` directory. The source-root directory also passed in that focused probe. The package owner then wrapped the documented frontend command in a subshell with:

```bash
cd "$V4_REVIEW_ROOT/apps/web"
```

The final full-flow rerun launched the exact revised section from the previously failing package cwd and passed all 43 Python and 25 frontend cases before completing rollback. This closes the handoff issue without modifying candidate behavior. The original pre-correction document bytes were not retained before the owner applied the correction; the original failed output and invocation evidence were retained, and the final documents are bound by the audited inventory.

Evidence: [initial failed frontend output](package_host_web_initial_failure.log), [finding record](package_host_cwd_finding.json), [cwd probe command receipt](package_host_web_cwd_probe.json), [successful source-web-cwd probe](package_host_web_source_web_cwd.log), and [final corrected host output](package_host_tests.log).

## Documentation, evidence, and exclusions

The six root documentation/status files were checked against the package payload, source review, focused results, and original task/acceptance scope. They identify the before-image assembly, limit the patch to a new temporary source copy, explain that the package is not a complete deployable application, and distinguish synthetic acceptance from actual live recovery. The support-copy and rollback instructions preserve the distinction between patched files and temporary test support, JUnit output, and dependency symlinks. No live collection, import, scheduler/configuration change, service restart, deployment, BUY, Stage, or Vibe command is part of the host procedure.

The reported test counts are supported and their overlap is explicit. The existing `READY`-versus-`PARTIAL` compatibility failure is neither hidden nor weakened. Missing US reviewed/registry JSONs are described as a fixture limitation of the fixed source assembly; the tests use explicitly synthetic registry material, not newly deployed runtime configuration. The namespace loader and untested full native import graph are also disclosed.

All **24** evidence files referenced by the final independent source receipt match their recorded byte counts and SHA-256 values inside this package. All **66** already-resolvable local Markdown links existed, and no local Markdown target escaped the package root. At the audited snapshot there were only the declared pending destinations: this report, linked from README and TESTING, and the future `PACKAGE_SHA256SUMS`, linked from README. These pending destinations require the final assembler's post-addition link check.

The package snapshot contained no symlinks, dependency environments, Git metadata directories, Python cache files, compiled distribution directories, or the prohibited raw-data/archive/image/key file types checked by the audit script. The named private-key and common token-pattern scan found no matches. That limited scan is recorded as such; it is not a claim of exhaustive secret detection. The manifest's 7-runtime/6-test change list, source identity checks, and unchanged-byte checks are the substantive scope evidence.

The historical announcement first break, historical US trigger-to-plan causal break, missing 16:01 raw HK index replay, and inner cause of the 17:23 `StoreError` remain `CANNOT_CONFIRM`. The package does not turn the 695/Futu observation into proof of an exact D1 master, and this audit does not claim that today's stock selection has been restored.

## Reproduction and remaining handoff checks

The reviewer ran the cloud audit from `/workspace/scratch/21926b793c00/three_channel`:

```text
PYTHONDONTWRITEBYTECODE=1 /workspace/scratch/a154a3323e32/test_env/bin/python independent_review/audit_package.py
```

The [audit script](audit_package.py) reconstructs disposable source roots, verifies payload identity, invokes the packaged tools, extracts the host snippets, exercises support-copy failures, runs the host tests, and checks the complete rollback. Its paths identify the recorded cloud environment; it is reviewer evidence, not a portable Mac installer. The portable procedure remains the root `HOST_HANDOFF.md`.

After this report and its evidence are added, the final assembler must verify the checksum list against the final package, verify all final links, and bind ZIP and GitHub content to the published commit. The ZIP/remote receipt must be produced after publication and must not be represented as a self-referential commit payload. Those later checks are **NOT_RUN by this audit** and have separate ownership and receipts.

Mac native acceptance, the full application import graph, full TypeScript build/typecheck, full repository tests, live API/UI readback, live announcement/market operations, shared business state mutation, service or scheduler changes, deployment, and natural-session acceptance remain **NOT_RUN**. The reviewer edited no runtime source or application test. This report certifies the reviewed candidate package and its isolated handoff process only within those stated limits.
