# Independent R3 review — HK continuation and verifier repair

## Conclusion

**REVIEWED within this frozen scope. No unresolved reproducible P0/P1 defect after the verifier repair.** The reviewer reproduced and reported one P1 delivery-verification defect with three failing variants; the writer's minimal repair was independently rechecked. HK production replay and synthetic callsite tests passed their stated scope. Actual inputs, the current Mac HK02 producer, live business chain and natural slots remain **NOT_RUN / CANNOT_CONFIRM** as appropriate.

## Verifier P1: profile/path closure — fixed

Original verifier SHA was `53fc956f25875eac850b7dc766b9d95e95a7b8943812158d2c0da894c18fc099`, preserved exactly as `verifier_before_hardening.py`.

The independent `test_verifier_manifest_closure.py` created synthetic packages under `tmp_path` and reproduced:

1. A file record assigned to an undeclared profile, with matching payloads in that undeclared directory, allowed the declared selected profile to report PASS with `source_checked=[]`. A deliberately changed source file (`UNREVIEWED_SOURCE_DRIFT`) was not checked.
2. A declared profile without file records likewise reported PASS with zero source checks despite source drift.
3. A record with logical `ops/owned.py` but payload files named `ops/different.py` passed package/source verification. The after-file tree no longer corresponded to the source path that the receipt claimed to verify.

All three original probes failed their expected rejection assertions (exit 1), recorded in `verifier_manifest_closure_red.log`. Root cause: no file-profile membership or profile nonempty check, and no required correspondence between logical path and side/profile payload path.

The writer added only those checks plus a single-component profile-name check. Repaired verifier SHA is `2ee5276989fd1b3bb523ef74b636b884a63e21d04a0d96c4602abbc0242bf234`. The reviewer inspected the diff against the preserved original and reran the original six verifier tests, all three independent closure regressions and the six first-batch independent probes: **15 passed**, exit 0, `verifier_hardened_independent.log`.

The independent protected-file assertion now accepts `V4_R3_REVIEW_APP_ROOT`, defaulting to the original `ROOT/candidate`. It was run with the explicit candidate root. This is a test portability change only. Updated test SHA: `b74e2e8de4990a1a0c1ea77f009682671ff844482521d3e25755d409f516751b`.

## HK source identity and review

| Role/file | Before SHA-256 | Reviewed after SHA-256 |
| --- | --- | --- |
| `ops/macos_research_panel_daily.py` | `07aa9770c6ae0bb0cfd012e57843a37fedda6724a57cd52d7c339d854fc6609b` | `1963990fcde99b2681c837b8b66ea12f1ab066aba47729af5d0900073bc79ef3` |
| `ops/_macos_research_panel_daily_parts/hk_capture_gate.py` | `d3db5b9644bbf2fb1f4e245717907862ebe1cee2d0f650a8d45d732fd4a71940` | `d07be30a40c35aee9d710fcdcc7ae66b031488cc4c5e7029824e3c76ed3fd71c` |
| `ops/ensure_hk_security_master.py` | `6c341a33c0283b023219c46cc2a1c6aaca49cf4b5dcb88aa2fb5527a13145601` | `495ced4f0f06f170606ee576e035dafc99b540cd9fad0a28f2f2a36e5989ddb9` |
| Existing child namespace | `45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1` | unchanged |

The reviewer compared each before byte string against the R3 `source_snapshot/hk_child_conflict` and each after byte string against original R1 `after/hk_child`. All three replays match exactly. The preserved namespace is byte-identical to R3 current before; its `read_global` function AST equals the original R1 helper. No R1 absent-file assumption was used to overwrite it. Receipt: `hk_source_identity.json`.

Actual nested API consumer: `candidate/v3_shared_data/shared_data/hk_daily_supplement.py`, SHA `f71d6bb8bc0d55a0205d9734562c37d249654e3e39ccc85e18dd6398aa3c3862`. Actual callsite: `candidate/v4/manager_research/workspace_plan.py`, SHA `c734f3e986af81b39bf11c09d93caf7a205526c8b4df940a4beeb011f74e0ebb`. Both remain unchanged from candidate baseline `c973cbc`.

New test file SHA: `686ba041564a07671d550e379cdba2f6e455af2bf2fc7d8b0a0b95792fcfeb23`.

The seven actual API-callsite tests invoke the real `read_verified_daily_supplement` through `_read_hk02_daily_supplement_witness`, rather than replacing that reader. They validate source identities, checksum, cutoff, exact six sessions, pending data, unproven unit semantics and no wrong-date fallback. Source capture construction uses a fake external API under a synthetic temporary authority root; the consumer is guarded against collection. The read-only inventory stays unchanged.

Child tests load the exact frozen child bytes into a temporary source assembly and use candidate code only as explicitly identified dependencies. They exercise the actual CLI entry and original gate: rejecting panel-only readiness, stopping a historical missing-capture attempt before collection, retaining an immutable prior-day chain after pointer promotion, and original-owner synthetic success/cache/tamper or final-readback-rejection paths. The original test's fake Futu/TDX/subprocess boundaries remain synthetic. The R3 actual HK02 snapshot lacks `shared_data/hk_daily_supplement.py`; the explicit negative test preserves `HK_DAILY_SUPPLEMENT_OWNER_UNAVAILABLE` before subprocess or data-directory creation.

The two required prior-source imports are test-only copies:

| File | SHA-256 |
| --- | --- |
| `scripts/live_acquisition/contracts.py` | `ea20a940814915ec1d744b7df23ea48e4287e4baa9716889a648c9210ea3b34e` |
| `scripts/live_acquisition/orchestrator.py` | `a95fa35e17b6090f3bb196ee6bb75a456d9fb918ce64dd4cd78d7d6005d4f46d` |

The reviewer compared copies to the recorded prior-round source bytes and checked the recorded source-origin file SHA (`df62c2c7e7477cd9660acad8dcb05ad1c256228040bb62a6c625f906f21f5e52`). These imports do not establish current Mac runtime closure or restore a producer.

## Actual execution evidence

Python and candidate import environment are the same as the first-batch review. HK invocation additionally sets:

```bash
export V4_R3_HK_CHILD_ROOT=/workspace/scratch/21926b793c00/hk_child_candidate
export V4_R3_INPUT_PACKAGE_ROOT=/workspace/scratch/21926b793c00/input/remote/handoff/manager-daily-failure-20261009-r3/package
export V4_R3_OWNER_TEST_DEPENDENCY_ROOT=/workspace/scratch/21926b793c00/hk_validation/test_dependencies
```

From candidate cwd, actual command:

```bash
/workspace/scratch/a154a3323e32/test_env/bin/python -c 'import r3_scoped_loader; r3_scoped_loader.install(); import pytest; raise SystemExit(pytest.main(["-q", "-s", "-p", "no:cacheprovider", "tests/test_manager_r3_hk_continuation.py"]))'
```

Result: **13 passed**, exit 0, `hk_contracts.log`; logs show actual loaded nested consumer and temporary child module paths with SHAs.

Original supplement suite command, with the same loader and environment:

```text
pytest -q -p no:cacheprovider tests/test_hk_daily_supplement_r4.py
```

Result: **13 passed / 2 failed**, exit 1, `hk_original_contracts.log`. Preserved original failures:

- `test_screen_uses_master_universe_sidecar_volume_and_missing_only_price_overlay`: observed input candidate count 0 vs expected 3.
- `test_complete_panel_history_skips_sidecar_and_preserves_canonical_baseline`: observed input candidate count 0 vs expected 1.

The original test file SHA is `7085f61af64c20f3153ca5e6d7948c0e0e54c3236e2e5ec364b9662d5d1dfc94`. Git diff against `c973cbc` is empty for this test, the nested consumer and workspace callsite. These known failures are retained without weakening unit, cutoff, source or market gates.

From delivery root, verifier repair/portable independent-test invocation:

```bash
V4_R3_REVIEW_APP_ROOT=/workspace/scratch/21926b793c00/candidate /workspace/scratch/a154a3323e32/test_env/bin/python -c 'import r3_scoped_loader; r3_scoped_loader.install(); import pytest; raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", "tests/test_r3_delivery_verifier.py", "independent_review/test_frozen_contracts.py", "independent_review/test_verifier_manifest_closure.py"]))'
```

Result: **15 passed**, exit 0. No actual source, state, plan or service was written. No live owner, source API, production configuration, deployment or GitHub action was invoked.
