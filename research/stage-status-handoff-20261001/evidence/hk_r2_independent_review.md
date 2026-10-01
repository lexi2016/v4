# Independent review — HK calendar policy lane delta r2

Review scope is the frozen `hk_calendar_policy_lane_delta_20261001_r2` patch only. No activation, shared-data write, or live canary was performed.

## Verdict

`REVIEWED_WITH_P1`: the split-date wiring is internally consistent and its focused tests pass, but the requested 2026-10-07 → 2026-10-08 path is not acceptable against the persisted source and current producer behavior. The exact 2026-09-30 security-master snapshot is not reusable for the exact-date universe resolved by this code; a fresh collection is stamped with capture time at execution, while the new reader requires that capture date to remain 2026-09-30. Target runtime behavior therefore remains `CANNOT_CONFIRM` until a provenance-valid source path is resolved. Do not claim opening readiness from the fixture tests.

## Frozen delta integrity and focused tests

- Packet: `batch_manifest.json` SHA-256 `788d25e1c2233b89e03bf3fadea43fc1b736ca27626335d696d02a5f5cfd6c59`; `batch.patch` SHA-256 `dfcd98158139f4180db8b7cef04265168d763b0707de22a0198c607b58a5321c`; writer receipt SHA-256 `2b4a3fbb1eb8b81e15dfdf5b31abe312a6ad8159c4792348d0adeb4f86ab941f`.
- The 13 unified-diff paths exactly match the 13 manifest entries. All 13 current after-images match the manifest's byte counts and SHA-256 values, including both test files; no unmanifested patch path was found.
- Focused reviewer rerun on the frozen after-images, using the configured Python 3.14.6 runtime: `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. /Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python -B -m pytest -q --basetemp=/tmp/v4-hk-lane-r2-review-20261001 tests/test_preselection_market_calendar_lanes.py tests/test_hk_signal_calendar_boundary.py` → **20 passed**.
- The code computes dates for target `20261008` as price/signal `20261007` and HK Connect eligibility `20260930`; `infrastructure/scheduling/_executor_registry_parts/preselection.py:374-382` forwards eligibility date to `ops.ensure_hk_security_master`, and `:400-408` forwards both dates to `scripts.materialize_hk_0_2`. The candidate reader in `upstreams/v3_shared_data/shared_data/hk_0_2.py:1099-1106` requires Shanghai capture date to equal eligibility date.

## P1 — persisted 2026-09-30 master is not reusable by the exact-date producer

A read-only call to the candidate `ensure_hk_security_master(..., trade_date="20260930", reuse_only=True)` against the configured v35 store and its pinned shared package failed with `HK security-master exact-date authority unavailable for reuse: 20260930`. This mode cannot collect or publish.

Exact source comparison:

- Store root: `/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data`.
- The exact-date resolver reports `HK_CONNECT authority current pointer missing`; the permitted fallback is the exact-date HK 0.2 panel. Its `panel_latest.json` SHA-256 is `7e6afb9a77daf98687a064e3970a8deb2e1ac794b85a66316e0e807651323480`, pointing to `panels/20260930-151fbe7168ef/manifest.json` (raw SHA-256 `a4ae58a8606bc86b85a2200ab08103373d2e204b9ac2bb9778cdc8d6d01c51f2`), which binds panel SHA-256 `151fbe7168efefc769e51920d8c153e92c1d4659a46cc76b100fa7182e5f51ec` and `panel_max_date=20260930`. `_load_exact_date_hk_panel_codes(store, "20260930")` resolves **689** expected codes, canonical SHA-256 `33215df7fd109cba5597f9d4f920e5887e5856f2fa23c7328b8cb597b50332c2`.
- The shared security-master `latest.json` SHA-256 is `ee8a8f9db495e066035d6c806cf6a027555a9cedfc4c0d1611867486cc131f13`; its `20260930` entry points to run `49ffde1ebebdc85e4680e701`. Verified manifest path `assets/hk_security_master/runs/20260930/49ffde1ebebdc85e4680e701/manifest.json` has raw SHA-256 `acb3308410a8601651818b14fb519ff39a019adadc37ac3beec86c8cad5d5eb5`, artifact SHA-256 `754794679937494dc8dc6cdc8dfbd14dfa4b070ea709f551874e39006aa712dd`, receipt SHA-256 `6d4a078ec83a9f0418f20b865eb0bfbee094e35ca683786b0bc73ebc427c6aa9`, `captured_at=2026-09-30T17:20:08+08:00`, row count **696**, and `universe_codes_sha256=162fb3ec7f50a1130f202be9d39461218260e57cc9b1cefb279d629828885e09`.
- The 696 stored master codes are not the 689 exact-panel codes: all 689 panel codes are present, but the master has seven extra codes (`HK.00853`, `HK.02172`, `HK.02252`, `HK.02825`, `HK.03167`, `HK.03443`, `HK.03469`). Therefore the manifest universe hash and row set fail the exact reuse condition.

The decision path is explicit in `ops/ensure_hk_security_master.py:863-882` (authority resolution and missing-pointer exact-panel fallback), `:887-918` (hash + exact-code-set reuse check and `reuse_only` failure), and `:920-936` (on non-reuse, live Futu collection then publication with `captured_at=datetime.now().astimezone()`). The reader then rejects any capture whose Shanghai date is not the eligibility date at `upstreams/v3_shared_data/shared_data/hk_0_2.py:1099-1106`. Thus a later collection cannot repair a 2026-09-30 historical capture without violating the reader's explicit time contract. The current stored master has a matching date stamp, but is not the source set the producer now resolves; preserve both facts.

`CANNOT_CONFIRM`: no verified, exact-date master source for the 2026-09-30 eligibility universe was observed. The target 2026-10-08 shared Top100 does not yet exist, and no target execution was attempted.

## P2 — A-share artifact-retention acceptance is not directly tested

`tests/test_hk_signal_calendar_boundary.py::test_hk_materializer_preserves_existing_split_date_target` seeds a fake existing READY **HK** target and a generic `existing-target.json` sentinel. The lane-matrix tests assert calendar admission and A producer omission on HK-only sessions, but do not seed and verify an existing A-share artifact survives the same session. This is a test-coverage gap; no A overwrite defect was demonstrated. Report A-preservation behavior as `CANNOT_CONFIRM` until an A-specific existing-target assertion is supplied.

## Boundaries

This review establishes source/diff integrity and focused test behavior only. No source code, data store, launch configuration, or service was changed. No activation, API/UI, natural-opening, or production behavior was verified. Research-only and order/gate safety are unaffected by this read-only review.
