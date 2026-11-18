# V4 current-universe projection validation

The product-only source patch applies to the exact combined Main daily-product preimage and produces the recorded daily-product postimage. The prepared `v4-panel-throughput-storage-20261118-r2` bundle remains immutable but is **NOT_DEPLOYABLE** because it also contains an unnecessary Workbench host passthrough delta that can break reads of older products. No replacement bundle was built here.

The focused regression `tests/test_v4_current_universe_scope.py` passed 2 tests against the exact daily-product source in the prepared r2 Main app, using the configured Main Python runtime. It verifies the four strict eligibility fields and keeps near matches and missing metadata active. The test does not exercise a live Workbench/API host.

The exact D18 pair snapshot (`54f9474006c480a47303c18e4b2fd9a22132609cf44f229de63c68cb7d8a37a0`, snapshot SHA-256 `d98b51c1ef798ad662f775e86c5db2d5428af8088c31f0e70c2cc30748031fed`) yields 5,842 original target codes, 5,580 active codes, and 262 excluded codes: 232 `VERIFIED_BSE_OLD_CODE_REPLACED` and 30 `VERIFIED_DELISTED_NO_CURRENT_BARS`. Eight other eligible records remain active.

The earlier r2 candidate verifier passed its exact Main/API/Stage inventories, deltas, storage policy semantics, 94 managed pins, 4 readers, and recorded live plist preimages; that verdict does not establish deployability after the host-compatibility finding. Stage forward and rollback each matched 19 existing witnesses. The Stage capacity suite passed 17 tests; pytest emitted 5 temporary-cleanup warnings for an immutable pre-existing file under pytest's temp directory.

Independent combined review, activation, natural daily execution, storage-effect measurement, and user-facing natural-run verification remain `NOT_RUN`/`PENDING`. No panel data or sealed D18 artifact was changed; no service was activated or restarted.
