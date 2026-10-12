# Independent review — minimal API owner R4 ordering

Date: 2026-10-12

## Frozen identity and scope

- Candidate: `integration/minimal-api-owner-r4/app`
- R3 baseline review closure: `receipts/reviewer/minimal-api-owner-r3/r3-review-closure.json`, SHA-256 `41f62684d07bee02e1a7aa58838604d3c6c2243ceef5990f43a909393ee4999e`, verdict `PASS_BOUNDED_SCOPE_WITH_P2_EVIDENCE_GAP`.
- R4 writer closure: `receipts/writer/minimal-api-owner-r4/r4-source-closure.json`, SHA-256 `6667317b06f269cf9685211566643ae5e619227bf03c83845c9ffa56b4d71f37`.
- R3→R4 diff: `receipts/writer/minimal-api-owner-r4/r4-source-delta-r3-to-r4.diff`, SHA-256 `d4f2b60cd0272cb2cba9a3197ca110254d8771649280e7390122b71785173ad1`.
- Release manifest SHA-256: `d8fbb6729a0c3fa94de0c057d4662127e7dc819f8034b964c3719e5a668592dc`; inventory 1,031 entries.
- Exact changed paths: `v4/manager_research/announcement_autorun.py` (SHA-256 `1827d6826280406370a696ab07f3de91e6af834b2431a2e05805d8c5be24a26f`) and `tests/test_manager_hkex_preopen_regression.py` (SHA-256 `dd016a569a81f53334f01183be03774e062b3fd7b06afab1e98012efb7b1d427`).

Review is limited to the changed collection ordering and its delayed-legacy reproduction. No source, canonical, live, service, network, or Git changes were made.

## Verdict

`REVIEWED=FAIL`; `TESTED=PASS` for all nine focused HKEX preopen regressions; `BEHAVIOR_VERIFIED=FAIL` for persistence when full-market work exhausts the shared capture budget before legacy collection.

### P1 — exhausted shared budget can discard the full-market product before commit

R4 moves `collect_official_market_batch(..., budget=budget)` before the legacy issuer batch in `announcement_autorun.py:326-356`, as intended. However, the actual legacy implementation `collect_batch` first captures the active-stock list at `announcement_source.py:857-865`, before its per-issuer budget checks and exception handlers. On a cache miss, `capture()` invokes `budget.before_request()` (`announcement_source.py:727-750`); if the preceding market pass has exhausted the shared 45-second budget, this raises `CaptureBudgetExpired` out of `collect_batch`. The R4 scheduled owner has not yet called `_commit` at that point (`announcement_autorun.py:342-356`); its outer handler marks the attempt FAILED and re-raises (`announcement_autorun.py:392-398`). The just-captured `market_batch` therefore never becomes a persisted product with its directory/body metadata. The cycle child alarm is in the separate caller process (`ops/run_manager_announcement_cycle.py:535-549`), so it does not cancel or commit work in the long-lived API server that owns this source call.

This is a new ordering boundary: a full-market pass may use the entire shared budget before the legacy batch begins. Whether a natural invocation reaches that budget and misses the active-list cache is `CANNOT_CONFIRM`, but the code path permits it. It defeats the intended result on that path because raw transport bytes may remain in the material store while the directory/product and owner coverage receipt are not committed.

The added regression does not cover this exhausted-budget branch. It replaces `provider.collect_announcement_batch` with `slow_legacy_batch` at `test_manager_hkex_preopen_regression.py:393-409`; that stub advances the clock by 48 seconds and returns normally even after the budget has expired. It bypasses the real active-list capture that raises before the per-issuer loop. A bounded exhaustion result from the legacy batch should still allow the already-completed market result to be committed with partial/unqueried-issuer evidence.

## Independent focused tests

Runtime: deployed Python 3.14.6 at `/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python`.

Command: `PYTHONDONTWRITEBYTECODE=1 "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python" -B -m pytest -q -p no:cacheprovider --basetemp="/Users/lexi/Desktop/学习/agents调试/V4_HKEX_DIRECT_PREOPEN_20261012_R1/receipts/reviewer/minimal-api-owner-r4/tmp-hkex-regression-20261012a" tests/test_manager_hkex_preopen_regression.py --tb=short`

Result: `9 passed in 7.07s`. The new delayed-legacy case confirms the market metadata and 06:05 body appear before the fake legacy delay under the unchanged 45-second budget. It does not prove the real exhausted-budget branch described above.

## Boundary

No P0 or additional P1/P2 findings. Actual live capture, active-list cache state, API/UI readback, deployment, and natural-period behavior remain `CANNOT_CONFIRM`. R3 deadline evidence was consumed from the later accepted reviewer closure and was not reopened here.
