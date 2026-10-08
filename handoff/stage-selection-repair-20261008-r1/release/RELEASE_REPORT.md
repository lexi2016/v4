# Issue 28 — release P1 candidate

**The two reproduced release defects have a focused source fix and offline regression coverage. This remains a source candidate, not a deployable package.** Mac adaptation, independent exact-package acceptance, actual service recovery, API/UI and natural execution are NOT_RUN here.

Repository: `lexi2016/v4`. Frozen handoff commit: `00524e9050fe212f87911b56eea1c2db719dd94b`. The five edited preimages were copied from `baseline/source` and verified against `evidence/SOURCE_MANIFEST.json`; none of the baseline bytes was changed. This patch targets the blocked R2 operations slice and its observed external guard. It is not a replacement for canonical, active API, active Stage or active producer code.

## What changed

### 1. Bind and verify the external guard

`api_candidate_recovery.py` now requires `guard_path` and `guard_sha256` in an identity loaded from JSON. The SHA must equal the pinned candidate guard digest; a caller cannot authorize different guard bytes simply by supplying their recomputed hash. The installer requires the same path/digest in the recovery identity, final plan `writer_artifacts`, and exact reviewer scope. The former 19-field scope is rejected; the new exact scope has 21 fields.

Both callers read a regular guard file without following its final symlink, verify its SHA, and compile/execute that exact byte buffer. They do not call `exec_module`, reread the path after hashing, or accept cached bytecode. Recovery validates the guard before any service command, then verifies again when loading it for filesystem work. A test changes the on-disk path after hashing and proves only the verified buffer executes.

The supplied reviewer helper also reads each receipt once for its SHA and JSON parsing, and rejects scope supersets. Missing pins, changed pins and the old plan/scope fail closed.

### 2. Preserve a traceable claim through double failure

The guard now catches every `OSError` from the fallback restore link. `ClaimRecoveryError` carries the retained claim path/SHA, exact active path, phase, intended candidate SHA, and drift receipt path/SHA. The install and recovery wrappers preserve this structure in their exceptions and CLI error JSON. If receipt storage itself fails, the claim identity still survives with an explicit `receipt_error`; no receipt hash is invented.

Recovery accepts an explicit `--claim-receipt-path` plus `--claim-receipt-sha256` in addition to the existing identity and exact confirmation. It validates the receipt digest, API service, exact active path, recognized failed-CAS phase, baseline/candidate digests, and claim path before any service access. A claim must be a regular file in the private `.<active-name>.claim-<32 hex>/before.plist` directory next to the exact active path. Symlink claims, changed bytes and redirected receipts are rejected.

After proving the exact label absent and port free, the guard snapshots the validated claim, writes/fsyncs that snapshot with its mode, rechecks the source claim, and publishes by exclusive hard link. The claim is retained. An existing file or dangling symlink, or a competing path that appears during the link, is never overwritten. Recovery checks the restored bytes and bootstraps only after the normal baseline checks pass. This works for a retained baseline from failed installation and for a retained candidate from a failed rollback; the latter proceeds through the existing candidate-to-baseline path before bootstrap.

A failed claim-recovery attempt preserves the original authorizing receipt for a retry and records the latest failure as additional evidence. Receipt shape errors are controlled `RecoveryError` failures. If a failed attempt has already restored the baseline but receipt writing/readiness fails, use the ordinary baseline recovery path after checking the active baseline; the claim branch intentionally refuses any preexisting active path.

## Verification

Interpreter: isolated **CPython 3.14.7 on Linux** (`work/test-venv/bin/python`). Every fault injection and fixture write used a temporary directory under this release workspace. Actual `/bin/launchctl`, `lsof`, bootstrap and bootout were never run. System recovery commands were handled by an in-process protocol fake; filesystem validation, guard loading, exclusive links, mode checks, receipts and package/review validators remained real.

| Verification | Result | Raw log |
|---|---:|---|
| Original guard side effects, missing-claim route and traceability tests, before production changes | 9 expected FAIL | `logs/01_baseline_p1_red.log` |
| Legacy identity and review contract, before production changes | 3 expected FAIL | `logs/02_baseline_guard_contract_red.log` |
| Original 17 recovery + 9 installation tests on frozen source | 26 PASS | `logs/04_baseline_existing_26.log` |
| Intermediate candidate: retry receipt and malformed phase regressions | 2 expected FAIL, subsequently fixed | `logs/07_candidate_retry_shape_red.log` |
| Original 17 recovery + 9 installation tests on delivered candidate | **26 PASS** | `logs/09_delivered_existing_26_final.log` |
| Final focused P1 suite on delivered candidate | **25 PASS** | `logs/10_delivered_p1_25_final.log` |
| Identical delivered P1 tests against untouched baseline copies | **25 expected FAIL** | `logs/11_delivered_tests_against_baseline_red.log` |
| Preimage SHA/size/Git blob checks; patch applied in a temporary copy; all 8 after-images match delivery manifest | **PASS** | `logs/12_delivery_integrity.log` |

All 26 supplied test methods and their existing behavioral assertions were retained. Their candidate scopes received the required guard binding, and recovery fixtures can identify the guard source explicitly. Because the supplied Mac tests depend on deliberately excluded plists, manifests, release inventories and receipts, `tests/release_test_fixture.py` supplies a small **synthetic unit-test package**. Its PASS/READY strings are parser fixtures in deleted temporary directories. The test named `test_current_failed_r1_review_receipt_cannot_authorize_candidate` used a synthetic FAIL receipt; it did not reread the original private R1 evidence. These results do not revalidate the real R2 package, the original business canary, or the actual 1,013-entry application inventory.

The focused suite covers guard drift before code and service access, symlink guard rejection, verified-buffer execution, legacy identity/scope/plan rejection, self-approved replacement guards, double-link installation and rollback failures, installer wrapper propagation, receipt-storage failure, claim recovery, mode preservation, competing paths, dangling active symlinks, claim/receipt tampering, source/target redirection, malformed phase input, and retry after recovery-link failure.

### Reproduce from the handoff workspace

```bash
work/test-venv/bin/python -B delivery/release/tests/run_existing_suites.py
work/test-venv/bin/python -B delivery/release/tests/test_release_regressions.py
RELEASE_SOURCE_ROOT=work/release/before work/test-venv/bin/python -B delivery/release/tests/run_existing_suites.py
RELEASE_SOURCE_ROOT=work/release/before work/test-venv/bin/python -B delivery/release/tests/test_release_regressions.py
```

The last command intentionally exits 1 against the frozen bugs. The test runner accepts an absolute `RELEASE_SOURCE_ROOT` as well; it expects the `blocked_candidate_ops` and `external_guard_reference` directories beneath it. `release_p1.patch` contains all changed source and new tests; `release_source.patch` contains only the five existing-file changes. The `source/` tree contains full after-images.

## Exact-pin contract migration required

**Do not execute or merely relabel the old final plan or 19-field receipt.** The patch intentionally leaves the existing release/canary/baseline pins intact. It cannot supply new real-host identity, package or reviewer receipts from excluded Mac files.

1. On the owning Mac workflow, verify the then-current API owner and all applicable preimages. The observed guard before-image was `264ad2d3f5535e17f6e7471dc12d7e00452104b505795857e9f0637c0a29e816`. Any changed actual owner/preimage requires a new comparison and review. The guard is an external shared source; applying this reference copy is a separate, explicit adaptation step.
2. Freeze the patched guard bytes and the exact selected path. This candidate guard after-image is `1fd041a3da7f21893ecc70b9d4d0d79936b58cc884cbc17367711917ba798367`. Both helper constants currently pin it. Choosing a different guard path requires matching path changes and new helper hashes; changing guard bytes requires a fresh digest and review.
3. Add that exact `guard_path` and `guard_sha256` to the real recovery identity. Recompute the identity file SHA and update `EXPECTED['candidate_id_sha256']` only from the final reviewed identity bytes. The old identity SHA is deliberately not silently replaced here. Reissue any affected module-review receipt; an older PASS receipt is not proof of these changed module bytes.
4. Freeze the final helper and test hashes. Add the exact guard path/SHA to final-plan `writer_artifacts`, together with the final installer/recovery/test identities. Recompute the plan hash after those bytes are fixed.
5. Regenerate the complete exact scope: its old 19 fields must reflect the final real package and plan, plus `guard_path` and `guard_sha256`. An independent reviewer must inspect the resulting bytes and issue a new exact-scope receipt with its own receipt SHA. Only the normal formal PASS/READY gate can authorize later installation; the old FAILED/NOT_DEPLOYABLE review remains historical evidence.
6. After the existing deployment/recovery authorization and Mac acceptance, a retained-claim recovery uses the reported original receipt path and SHA with `recover-baseline --claim-receipt-path ... --claim-receipt-sha256 ...`. Without a valid bound receipt, missing-active recovery continues to stop. No synthetic fixture receipt in this handoff authorizes host work.

## NOT_RUN and boundaries

- Full actual Mac R2 package, new identity/final-plan generation and frozen review receipt: **NOT_RUN**.
- Independent Mac writer/reviewer acceptance, actual launchd/lsof behavior, service stop/start, live install/rollback/claim recovery: **NOT_RUN**.
- API/UI readback and natural execution: **NOT_RUN**.
- Full repository suite and unrelated HK cutover command flows: **NOT_RUN**; the input is a verified source slice without the full application/package closure. Focused changed behavior and all supplied release test methods were exercised.
- Integration, deployment, business data, model/BUY gates, manager owner, other schedules and Vibe8910: no operation performed.
- No GitHub publish, comment, merge or service operation was performed by this worker.

`RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`.

## Exact source digests

Full before/after SHA-256, byte counts, before Git blob SHA-1 and new-test digests are in `RELEASE_SHA256_MANIFEST.json`.

| Source | Before SHA-256 | After SHA-256 |
|---|---|---|
| `api_candidate_install_r2.py` | `b326d2f68843e1673169bc8d6e36965786f513e19ef2671a64d113284e944200` | `3ddeb297d36f7b825103b8462cd610a14613b73ef95f6940f5a93498339733d6` |
| `api_candidate_recovery.py` | `d42975f459858ed697805c3043090a82102cd2e0d6c28eef07bb4c440e955fbb` | `8a162ce38478c292bf811c827c7616909a91a23a2bb3a1f95c71f208f9a08741` |
| `test_api_candidate_install_r2.py` | `167a43a3b81f1cac11995c107ad1c6a8f09fc7d008aaa157753b46e5ca5c59b6` | `95c71fd7a4ec38828a5e5c44eff7f65bd23e588b943fe7205403b759ee3a45b0` |
| `test_api_candidate_recovery.py` | `871bbf1bf97a537bd40bf0461a00e7702ab9ae2c01d3a558a5bba5716bf77bf8` | `a4b06db6f9b32cc5f8b4d35eceb3910cacb993bba1d4e772acd5491a6c88cd35` |
| `hk_calendar_candidate_cutover.py` | `264ad2d3f5535e17f6e7471dc12d7e00452104b505795857e9f0637c0a29e816` | `1fd041a3da7f21893ecc70b9d4d0d79936b58cc884cbc17367711917ba798367` |
