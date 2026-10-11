# WeChat daily integration · October 11, 2026

The accepted R3 recovery fetch/runner and R2 appendix changes are now in the local daily scripts. One existing October 8 article was carried through frozen-package recovery, cached OCR, retained package identity, existing user-provided Chat return normalization/import, Drive original-byte mirrors, and V4 Stage A exact-article-date API/UI readback.

This directory is a delivery snapshot of the actual integrated files and receipts, intended to apply to the existing WeChat workflow at `v3_system/选股池/微信公众号`. It is not a separate application or a second research producer. Six live files changed; `wechat_macos_ocr.py` is included as the already matching dependency, with unchanged SHA. `INTEGRATION.patch` binds the before/after change; `rollback/PRE_INTEGRATION_FILES.json` records the local recovery copies. Prior Mac regression receipts are retained in the parent commit's `wechat-workflow-issue31-mac-r3-20261011` delivery.

The final independent reviewer receipt is authoritative for REVIEWED/BEHAVIOR_VERIFIED; the immutable writer receipt is an earlier handoff snapshot. GitHub remote-tree and branch-head verification is performed after this commit and recorded locally and in Issue #31.

## Evidence

- `INTEGRATION_FILE_HASHES.json`, `INTEGRATION.patch`: exact live code and documentation delta.
- `WRITER_RECEIPT.json`, `reviewer/REVIEW_RECEIPT.json`, `reviewer/REVIEW_FINDINGS.md`: bounded live canary and independent verdict; prior unchanged-hash suites were reused.
- `drive_transport/ROUNDTRIP_RECEIPT.json`: five ZIP transport parts preserve all 56 original frozen members, including 50 images. This does not claim successful download of the original single ZIP container.
- `DRIVE_RETURN_MIRROR_RECEIPT.json`: five immutable new-version return files downloaded as original bytes and matched local SHA256.
- `LOCAL_FORMAT_NORMALIZATION_RECEIPT.json`, `FROZEN_INPUT_EXTRACTION_RECEIPT.json`: lossless format correction and all 53 manifest input sources available in the archive.
- `V4_FULL_SOURCE_INDEX_RECEIPT.json`, `V4_API_VERIFICATION_RECEIPT.json`, `V4_UI_VERIFICATION_RECEIPT.json`: exact article date 20261008, bound sources, readable original report. API source artifacts are honestly NOT_RECHECKED; their byte proof is the extraction receipt.
- `DRIVE_APPENDIX_MIRROR_RECEIPT.json`, `appendix_current/PERFORMANCE_APPENDIX_RECEIPT.json`: complete 108-listing appendix, with current source failures disclosed.
- `START_HERE_DAILY_INTEGRATION.md`: verified Drive links to the report, materials and separate appendix.

## Remaining evidence boundaries

The appendix has 108 unique listings (A81/BJ3/HK24), 0 validated price observations, and 108 CANNOT_CONFIRM rows. A/BJ has PARTIAL coverage 5137/5800, row_count5261, REBUILD_REQUIRED, and no binding to the current 5125-row exact panel. HK lacks the October 7 prior-session receipt and has a panel SHA mismatch. No prices were fabricated, and no alternative market producer was used.

The original Chat research retains PARTIAL_WITH_UNREADABLE for obscured text in IMAGE007, tiny text in IMAGE027 and footnotes in IMAGE043–049. The workflow receipt does not endorse financial research semantics or claim a fresh Chat read. Natural unattended execution is unverified. Public source images, large OCR/market data, original ZIPs, private state and environments are not included in this delivery; the Drive byte receipts bind those artifacts.

RESEARCH_ONLY / WATCH_ONLY / NO_BUY_GATE. production_allowed=false; buy_gate_updated=false; orders_sent=false.
