# R3 announcement readback compatibility harness

This folder contains the exact reviewed R3 validator, the focused API readback test, and the R2-to-R3 API-only switch helper/test/runbook. It is separate from the original R2 announcement-import switch under `tools/ops/switch_api_only_announcement.py`.

The focused compatibility test is **NOT_PORTABLE** in this bundle because it requires the exact legacy 2026-10-07 / 2026-10-06 product and catalog fixtures. Those article/catalog payloads are intentionally not included. The review ran the test with local task fixtures and independently reported 4 passed plus 3 malicious reader-gap probes rejected. See `metadata/non_portable_test_fixtures.json` and `metadata/results.json`.

The R3 release is a candidate only. Its source review passed; the R2-to-R3 API-only switch, old/new date-pair API readback, and UI verification remain pending root action.
