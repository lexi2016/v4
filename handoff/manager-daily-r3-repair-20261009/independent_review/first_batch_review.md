# Independent R3 review — first frozen batch

> Historical first-pass record. Subsequent reviewer probes reproduced a verifier profile/path closure defect after this pass. See `test_verifier_manifest_closure.py` and `verifier_manifest_closure_red.log`; the combined final review supersedes this first-pass conclusion and records the repair verification.

## Scope and conclusion

Independent reviewer did not author or edit candidate production files. Reviewed the fixed product projection patch and two-date tests, the separate Issue30 exact-path policy proposal, the read-only delivery verifier, and the currently drafted Mac handoff. Binding and HK behavior await a separate freeze and are not covered by this conclusion.

**REVIEWED for the first-batch scope. No reproducible P0/P1 finding in the reviewed changes.** This is synthetic code/contract evidence only. Actual Mac integration, deployment, live owner/API/UI, source recovery, target-day products and natural-day business acceptance are **NOT_RUN**.

## Source identity

Candidate baseline is `c973cbc268c686af4492a7dfa4cef8417ca8edf4`.

| File | Reviewed SHA-256 |
| --- | --- |
| `candidate/v4/manager_research/workspace_daily_channels.py` | `e5a74449f211c9e8ecfb4f886317db2263d524f0e29fa7912c9094928a5c6bab` |
| Product projection baseline in `c973cbc` | `de4e91150d3198dda40e170660de8a83c717811d478411941015b7cf1364c15f` |
| `candidate/tests/test_manager_r3_product_contract.py` | `7ecf4789b581818eb516fe420f03f159580f276600ebf0921c73ba3b01c2b21c` |
| Policy before | `1f4afc70d7e5920b67c2b148def6b9167819664c33c92b475d919a097b9dd050` |
| Policy after proposal | `ce74042648405a8de9aa7bd69fd0ac5cbe54e42e29db983d77d7e8519ac4cfac` |
| `tools/verify_delivery.py` | `53fc956f25875eac850b7dc766b9d95e95a7b8943812158d2c0da894c18fc099` |
| `tests/test_r3_delivery_verifier.py` | `7d76e2ce66c445bb01017155419ee84ce4491322acc1aebe522d82702fc99a3f` |
| `HOST_HANDOFF.md` (first reviewed revision) | `9fcf50e6afba6f42047eea14c01d81df1f4d9a81cb188d0167ba7a45ed6ba711` |

The Issue32 three files retain the required task SHAs. `ops/run_v35_macos_scheduler_daemon.py` remains `19e071da0c6b6748465853c4ad86a80d6060524333e9dab21647b67adc8b49ec`. Git diff against the baseline for these four paths is empty. Final combined review will recheck this after all writer freezes.

## Findings and verification

### Product projection and two-date behavior

The production diff is confined to `_references` (+17/-5): retaining native payload/manifest and related scalar identity pointers, and extracting each card's direct `source_refs` with its card anchor. No selection, ranking, owner publication, clock, historical-auto eligibility or safety flag logic is changed. The projection stays nonmutating and does not copy body/evidence structures recursively.

The 9 new product tests use a synthetic `tmp_path` store, original import/refresh/store/GET paths and a local TestClient. They cover 10/8 retrospective dynamic readback with and without a prior eligible historical plan; 10/9 ordinary auto readback of the saved run/SHA/input/context; independent missing channels without other-date fallback; complete source capture distinguished from an unsaved daily mapping; and traceable legitimate empty announcement/US results while retaining unrelated gaps. The fixture intentionally preserves a PARTIAL whole-workspace result where independent channels are missing. It does not assert actual business completion.

Independent in-memory loading of the prechange projection reproduces both native-pointer test failures. No candidate source was edited for this comparison. The repaired projection passes both in the current run. The pre-existing `test_missing_original_archive_is_not_empty_connect_selection` failure is independently reproduced with **both** prechange and current projection: `selection_diagnostics.status` is PARTIAL while the test expects READY. It remains visible; it is not a regression introduced by this projection diff.

### Separate release-policy proposal

The after policy is exactly the before `POLICY` plus the five specified exact `shared` keys, each limited to `manager`. All existing modules, prefixes, shared keys and implementation logic are identical. Independent tests exercise every new path, rejection under all other modules, neighboring filename/path rejection, missing exact declaration rejection, and rejection of a scope carrying the old policy SHA under the proposed new policy. The proposal does not grant directory prefixes or modify the current release-policy source. Adoption and delta generation remain the original shared owner's later responsibility.

### Read-only delivery verifier and handoff

The verifier only reads bounded source/package files and reports JSON. It rejects malformed/traversing paths, source aliases/symlinks, duplicate source records, payload corruption or extra payloads, source before/after mismatch and changed protected bytes. Independent tests verify no fixture byte or mtime change on PASS or rejection. This is a byte-consistency check against the supplied manifest, not an independent release authorization or proof of actual runtime identity. The completed delivery manifest and actual profile patches were not yet available for this first batch; their aggregate application/after-byte verification remains pending.

The handoff keeps an isolated candidate, existing shared owner/lock/delta workflow, exact before checks, one binding with explicit distinct worker/API roots, real canary prerequisites, and separate live acceptance. Its two Bash blocks both pass `bash -n`. The CLI flag contract will be rechecked against the frozen binding renderer. No shown live command was executed.

## Actual commands and results

Environment: `/workspace/scratch/a154a3323e32/test_env/bin/python`, Python 3.14.6, pytest 9.1.1, FastAPI 0.141.1, Starlette 1.6.0, httpx 0.28.1. One upstream Starlette TestClient deprecation warning is retained. Candidate imports use the explicitly scoped test-only loader; this does not establish native full-repository import closure.

Common environment and cwd:

```bash
cd /workspace/scratch/21926b793c00/candidate
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH=/workspace/scratch/21926b793c00/candidate:/workspace/scratch/21926b793c00/candidate/upstreams:/workspace/scratch/21926b793c00/candidate/tests
export V4_R3_POLICY_SOURCE=/workspace/scratch/21926b793c00/release_policy_review/after/ops/api_release_integration.py
```

First-batch verification:

```bash
/workspace/scratch/a154a3323e32/test_env/bin/python -c 'import r3_scoped_loader; r3_scoped_loader.install(); import pytest; raise SystemExit(pytest.main(["-q", "-p", "no:cacheprovider", "tests/test_manager_r3_product_contract.py", "tests/test_manager_daily_channels_20261008.py", "../tests/test_manager_r3_release_policy.py", "../tests/test_r3_delivery_verifier.py", "../independent_review/test_frozen_contracts.py"]))'
```

Result: **43 passed**, one warning, exit 0 (`frozen_contracts.log`). Breakdown: R3 product 9; adjacent daily projection 13; policy proposal 9; verifier 6; reviewer-owned additional probes 6.

For the prechange comparison, read `git show c973cbc:v4/manager_research/workspace_daily_channels.py`, execute those bytes only into the isolated process's imported projection module, then run:

```text
pytest -q -p no:cacheprovider
  tests/test_manager_r3_product_contract.py::test_original_owner_source_pointers_survive_daily_projection
  tests/test_manager_announcement_parity_20261008.py::test_missing_original_archive_is_not_empty_connect_selection
```

Result: **3 failed**, exit 1, expected comparison evidence: two repaired pointer defects plus the preserved old assertion failure (`prechange_product_and_known_failure.log`). The old assertion alone on current bytes is **1 failed**, exit 1 (`current_known_failure.log`).

Machine-readable source/environment receipt: `first_batch_source_identity.json`. Reviewer-only tests: `test_frozen_contracts.py`.

## Preserved execution boundary

No live POST or network owner dispatch, original source capture, business state/plan access, production configuration, service operation, deployment or GitHub write was performed. No candidate production file was modified. Stage, BUY and Vibe8910 were outside the edit scope. Research-only flags remain `RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false; orders_sent=false`.
