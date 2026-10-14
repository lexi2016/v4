# 2026-10-14 HK receipt read repair and display diagnosis

Baseline: a845bf6309b11b9ae8a8de39caac5b11e74d1e04, private lexi2016/v4. Source root: /Users/lexi/Desktop/学习/v4_app.

## Final scope and runtime

Only the exact-date stage receipt reader changed: remove its one-MiB override and reuse SafeRoot's existing bounded 64-MiB default, retaining regular-file/O_NOFOLLOW/path/JSON/schema/safety validation. Attempt-journal limits are unchanged. The canonical reader was absent and was reconciled from the actual API release, preserving its existing selection-store and journal checks.

Reader before SHA256: 1be96e736fda2863f6f8ff2315e8879a98499bbd30f5a911b46423c4dc6f094b
Reader after SHA256: f378aaeadc8178e6482f6155095c4947e4c0387f46eec2f2b820f929c53e8a6c
Actual API app: /Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-display-20261014-r1/app
Manifest SHA256: b70f8fbe7f4069e5f4661935e701aad2d21bd0274e10a2767d8a78bf03e5a016
Parent runtime and rollback plist recorded in local evidence. API was cloned from the current US-factor count-fix release, preserving parallel changes. API app.py is byte-for-byte restored to the parent. Stage service, 8910, raw data, selection artifacts, receipts and trading gates were not changed by this HK repair.

## Verification

Python: existing v3.5-mac runtime venv. Command: `python -m pytest -q tests/test_hk_display_receipt_20261014.py`; 3 passed. Tests cover valid >1-MiB receipt, symlink rejection, malformed JSON rejection, and no natural-verification promotion.
Actual 09:35 receipt: 1,282,218 bytes, valid JSON, previously refused at 1,048,576 bytes. After activation both A_SHARE and HK_CONNECT API selection references are BOUND_TO_VERIFIED_SELECTION. Real refreshed 8873 page no longer reports HK_EXECUTION_SELECTION_BINDING_CANNOT_CONFIRM. Execution/natural verification remains unconfirmed; reader success does not supply independent run provenance.
IMPLEMENTED / DEPLOYED / API_VERIFIED / UI_VERIFIED. Independent REVIEWED and BEHAVIOR_VERIFIED: NOT_RUN (user requested direct handling without subagents). Test results are primary-assistant verification.

## Findings retained, no gate or selection edits

09:30-09:35: exact D-1 100 codes captured, 40 rising at pre-capture, 4 also meet turnover >= HKD20m, all 4 meet volume_ratio >=1. Existing filter yields HK.02476, HK.02656, HK.06166, HK.09903. Four output rows are not evidence that only four stocks were collected.

Existing selector incorrectly conflates 96 inactive rows with missing_symbols and sets PARTIAL_WITH_ROWS. This semantic issue is recorded, not changed in this receipt-reader patch. Four-lane rows also explicitly set formal_eligible=false, so observation/unverified display remains; formal status and BUY were not promoted.

HK UI explicitly labels the displayed figure as stage change. HK.02656 stage change 6.4935% is correct versus stage open 3.08 to 3.28; daily change 14.087% uses previous close 2.875. A provisional display substitution was fully reverted after checking the actual label. Final source and UI preserve stage change.

Local evidence: /Users/lexi/Desktop/学习/agents调试/V4_NATURAL_MONITOR_20261014/hk-display-fix (scope, source backups, filter counts, candidate/activation, api-final.json, ui-final.txt). Raw financial data is not included in GitHub sync.
