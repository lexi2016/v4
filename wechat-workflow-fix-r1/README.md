# WeChat workflow R1 — Mac integrated and independently tested

This bounded export contains the six exact local source/test files integrated for WX-01–11. The original `wechat-workflow-review/` snapshot remains frozen at its prior content; its old manifests and test claims apply only to that original directory.

Local canonical source was updated and independently reviewed on macOS 26.6.2 arm64, Python 3.12.14. Results: 156 passed, 0 skipped, 18 subtests; 37 additional boundary/cache tests passed. The 29 added regressions are included in the 156. Acceptance, exact source hashes, commands, and limitations are in MAC_ACCEPTANCE.json. W files preserve CRLF; normalized candidate content matches. This is a scoped source export, not a full standalone repository or a deployed runtime.

The running 8873 service was not reloaded. Full live API/UI, Drive, actual collection/OCR, market-data and natural-slot acceptance were not performed. Existing damaged versioned archives are not silently repaired or reselected by this change; the prior-performance loader still rejects a damaged canonical summary. No research data or credentials are included.
