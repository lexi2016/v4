# Independent review: minimal API owner R4-R2

**Scope:** frozen R4-R2 source delta only, against the R4 candidate. Read-only review; no source, configuration, service, live state, canonical, or Git changes.

**Identity checked**

- Candidate app: `integration/minimal-api-owner-r4-r2/app`
- Writer closure: `receipts/writer/minimal-api-owner-r4-r2/source-closure.json`, SHA-256 `37b354c9eb1f2dc343bf0d2f5281981937acc26476ae8d5d71d163de1ddc4b80`
- R4-to-R4-R2 delta: `receipts/writer/minimal-api-owner-r4-r2/source-delta-r4-to-r4-r2.diff`, SHA-256 `ad1d1c08ff0fc79850603535a1faea337cc9cec84e906b0485cf49618101bfd1`
- Release manifest: SHA-256 `042ed01b839516d52f7e243b5ad7a56eece19e6de346d9f5c8cfb539058a5c59`
- The actual delta contains only `v4/manager_research/announcement_autorun.py` (SHA-256 `9bdb97998408016628149f1dc8bf9a56a072b45abb1fe4aa6b7f93df3d716a5a`) and `tests/test_manager_hkex_preopen_regression.py` (SHA-256 `53e2d93b92307a29c7421509acdd27ff04f0f415e38daddfcafc5be60abbe4d3`), matching the frozen closure.

## Verdict

- `REVIEWED=PASS` for the bounded R4-R2 defect.
- `TESTED=PASS`: all 10 focused HKEX preopen regression tests pass on deployed Python 3.14.6.
- `BEHAVIOR_VERIFIED=PASS` for the deterministic cache-miss/budget-boundary case below.
- Findings: P0 none; P1 none; P2 none within the frozen scope.

## Evidence

The unmodified legacy `collect_batch` fetches the active-stock list before entering its per-issuer exception handler (`v4/manager_research/announcement_source.py:858-862`). The R4-R2 owner catches only `CaptureBudgetExpired` around that existing collector, records the diagnostic reason, then commits the market result and marks the attempt partial with incomplete issuer coverage (`v4/manager_research/announcement_autorun.py:349-365, 383-400`). The 45-second and 57-request limits remain unchanged. Other exception classes still reach the existing failure handler.

The added regression invokes the real scheduled owner and real legacy collector with an empty active-list cache. Its synthetic monotonic clock places the directory response at 44.5 seconds and the PDF response at the 45-second boundary. It verifies that the official market directory and body SHA are committed, the attempt is PARTIAL, all six selected issuers remain explicitly unqueried, the failed-issuer list is empty, and neither a cache entry nor transport call is fabricated for the expired active-list request. This covers the reported loss path directly.

Reviewer command, run from the candidate app directory:

```sh
PYTHONDONTWRITEBYTECODE=1 "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" -B -m pytest -q -p no:cacheprovider --basetemp="/Users/lexi/Desktop/学习/agents调试/V4_HKEX_DIRECT_PREOPEN_20261012_R1/receipts/reviewer/minimal-api-owner-r4-r2/tmp-hkex-regression-20261012" tests/test_manager_hkex_preopen_regression.py --tb=short
```

Result: `10 passed in 7.08s`.

The writer closure reports a pre-fix red replay; I did not independently rerun the frozen baseline. The candidate remains `NOT_ACTIVATED`. Real network latency, current API/UI behavior, and natural-slot behavior are `CANNOT_CONFIRM`; this review establishes only the local source behavior under the stated virtual-clock regression.
