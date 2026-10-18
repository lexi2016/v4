# Issue45 Phase 4 Independent Source Review

**Verdict: PASS** for the frozen Phase 4 canonical source/test candidate and its three immutable source patches. This review does not apply the candidate or push it.

The reviewed merge is PR #46, head `ba685ea604af12e517f1ede773feaf3e38ef4600`, merge commit `475f9d6bb44d17b8bc948f755c3e7ba2b7b8a088`. The writer receipt is `SOURCE_INTEGRATION_RECEIPT.json`, SHA-256 `a7968fa36363b115da17db1683a7b70478f8fa1a9e3b2e11ae233de29cb6ac43`.

## Candidate and diff

All 11 staged candidate files match the receipt hashes, and all 10 existing canonical preimages still match their recorded preimage hashes; the eleventh file is a new regression test. Against the exact merged-source snapshot, only `ops/run_us_market_slot.py` and `tests/test_run_us_market_slot.py` differ. The implementation anchors POST_CLOSE HK target selection to the resolved US session date while retaining the existing `business_date` fallback outside POST_CLOSE. The regression test covers `20261020/0415 -> US 20261019 -> HK target 20261020`.

The exact candidate path and all 11 before/after SHA-256 values are recorded in `SOURCE_INDEPENDENT_REVIEW.json`.

## Immutable release patches

Each source-only patch hash, base/target release identity and manifest SHA, and every delta file target SHA are bound in the JSON review. I independently checked and applied each patch in a temporary mirror of its exact base release, then confirmed each patched delta file byte-matches the corresponding target release. Base non-delta conservation is 1,186/1,186 for digest, 851/851 for manager, and 1,222/1,222 for API with zero mismatches.

- Digest: `futu-board-map-us-20261018-r1` -> `issue45-pr46-us-digest-20261018-r2`, manifest `73db17d4a3d8af900f00ca056716a20f289b4df90b5f862d1207790f1a18e201`, patch SHA `edab3f0869d41739815af145b216abe844ce3de4390b8537d3c944bc26abc0f1`. Its runtime-workload delta sets the US digest `target_date_role` to `TARGET_DATE`; the calendar and wrapper deltas match the deployed release files.
- Manager: `zsxq-pdf-metadata-scheduler-20261018-r1` -> `issue45-pr46-manager-scheduler-20261018-r2`, manifest `58e3f267ce1fec7af8104df379378a6f0b234faa2b6453174a12681ea0226969`, patch SHA `155cb425eb36d2bb7401270e2df1b996160c197c90761503eab8cd5fdc76dd9d`.
- API: `futu-board-map-api-20261018-r1` -> `issue45-pr46-api-20261018-r3`, manifest `40872d5013f2239b40821f8547e65bcfed0af58102efb16113a38f2f5bc401e9`, patch SHA `5d216fe26ebb1c122ecb0b79fac15acd12fc12058f45e55ed80a8d8b146ecbb4`.

## Independent behavior tests

I used a disposable mirror of the exact merged-source tree overlaid with the 11 staged files. Python ran with `-B` and `PYTHONDONTWRITEBYTECODE=1`; pytest disabled its cache and wrote its base directory inside the temporary mirror. Import-origin assertions confirmed the reviewed modules loaded from that mirror. Both POST_CLOSE date oracles passed. The focused suite returned **30 passed, 1 failed**.

The sole failure is `tests/test_manager_us_mapping_bindings_r3.py::test_source_binding_carries_configured_quote_scope_and_proposal_sources`: its fixture writes an artifact for 20261017 while requesting target 20261020 / US session 20261016, so exact owner-manifest binding fails with `US_OWNER_ARTIFACT_MANIFEST_BINDING_INVALID`. The same fixture failure was previously reproduced on the refreshed active API baseline. This is a P2 baseline fixture caveat, not a regression in this candidate; exact-date validation remains unchanged. No P0 or P1 finding was identified.

## Boundary

Phase 4 source review is PASS and supports the root’s exact-preimage compare-and-swap decision. Canonical files were not applied by this reviewer; no GitHub commit/push, live release/service change, API/UI check, or natural target-date acceptance is claimed here. Natural autonomous behavior remains `CANNOT_CONFIRM`. Financial safety remains research-only; production, BUY-gate, and order flags are false.
