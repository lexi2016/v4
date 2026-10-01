# HK calendar lane and dual-date source delta r2

Status: corrected writer batch frozen for independent review. This r2 packet supersedes the r1 packet after independent review found a P1 owner-to-projector date-threading gap. No active service, shared-source store, V4 primary store, or trading/BUY write was performed.

The P1 gap was that the original preselection owner calculated a separate Connect eligibility/security-master date, but did not forward it to the scheduled projection CLI. The projector then defaulted HK eligibility to the A/global signal date, so a valid split-date HK pool failed the Stage validator. The corrected batch now forwards `--hk-eligibility-source-date` from the exact date computed by the original owner, parses it in `ops/materialize_scheduled_preselection.py`, and passes it through the verified HK reader. Calls that omit the new optional argument keep the prior same-date behavior. A/global `--signal-date` remains unchanged.

The parameterized regression now captures the exact original owner arguments for `20260925 -> 20260928` and `20261007 -> 20261008`, feeds those generated arguments into the actual scheduled projector CLI, writes the resulting HK pool through the existing `PreselectionPoolStore`, and validates that saved artifact with the actual Stage `_validate_hk_d1`. The required pairs are price/eligibility `20260925/20260924` and `20261007/20260930`.

A second regression invokes the original HK materializer CLI with the split-date arguments while its verified-reader boundary returns an existing READY target. It asserts the target is returned as `already_exists`, the rebuild function is never called, and a sentinel in the store remains byte-identical.

Frozen evidence:

- `batch.patch` SHA256: `dfcd98158139f4180db8b7cef04265168d763b0707de22a0198c607b58a5321c`
- `batch_manifest.json` SHA256: `788d25e1c2233b89e03bf3fadea43fc1b736ca27626335d696d02a5f5cfd6c59`
- The manifest records 13 scoped paths with exact preimage and after SHA256. `preimage/` preserves the r1 source baseline; new test files have no preimage. Patch application was checked from those preimages, then applied in a temporary copy; every resulting file byte-matched its recorded current after image.

Focused verification:

```text
PYTHONPATH=. ./.venv/bin/pytest -q --basetemp=/tmp/v4-hk-lane-r2b-20261001 tests/test_preselection_market_calendar_lanes.py tests/test_hk_signal_calendar_boundary.py
20 passed in 0.16s

git diff --check -- [11 scoped source paths]
exit 0
```

`git apply --check` and temporary preimage application/after-byte comparison also passed. The first r2 test run exposed only test assertion assumptions (fixed dates and an incorrect expectation that a PARTIAL projection exits nonzero); with corrected assertions, both exact owner-to-projector-to-Stage cases pass.

CANNOT_CONFIRM: active V3.5 owner integration, live HK source generation, Stage historical recovery, and natural-run behavior remain unverified. Do not activate this delta or write producer data until the independent r2 review and combined inactive candidate review pass.
