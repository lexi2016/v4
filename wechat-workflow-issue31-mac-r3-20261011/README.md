# Issue #31 R3 — actual Mac acceptance

PASS for the frozen R3 candidate on macOS 26.6.2 arm64 with Python 3.12.14. Independent review found no open P0/P1/P2.

Candidate source and patch are pinned to [fd57619a](https://github.com/lexi2016/v4/tree/fd57619a99dfe88266f1e2d78475b94ffdd161c4/wechat-workflow-fix-issue31-r3). No additional product-code changes were made on Mac.

Read [independent findings](reviewer/REVIEW_FINDINGS.md) and [review receipt](reviewer/REVIEW_RECEIPT.json). The independent full recovery suite passed 25 tests plus 3 subtests; the focused 8 plus 3 overlap and must not be added to that total. Actual runner adoption, default fetch reuse and prepare_ocr passed on an isolated historical article copy. All 50 images and existing OCR/source bytes remained unchanged except the permitted slice manifest refresh. Seven rejection probes and image-dimension tampering failed closed. No new network, collection or OCR attempts. R2 Vision cache evidence was reused, not rerun.

TESTED: independent rerun PASS. REVIEWED: PASS. BEHAVIOR_VERIFIED: frozen actual Mac scope PASS. INTEGRATED=false; DEPLOYED=false. Issue #31 remains open. Drive full ZIP raw-byte readback remains CANNOT_CONFIRM (prior HTTP403/code1010); no repeat attempt or sharing change.

This directory contains selected acceptance receipts and logs, not the original article, images or OCR content. evidence_inventory.json inventories local Writer evidence; it does not claim every listed local file was uploaded. DELIVERY_MANIFEST.json lists only the files included in this GitHub delivery. Writer HANDOFF reflects its historical pre-review status; the independent review is the final verdict.
