# Full US-to-HK industry mapping delivery — 2026-10-19

## Behavior

The existing V4 path now consumes all 1,003 preserved relationships and all 667 catalog stock identities. Subindustry peer observations and conditional economic routes are explicit; broad sector ETFs and same-issuer ADRs remain background. Valid unique peer members receive equal weights; missing members retain a partial coverage record. Conditional routes preserve their original conditions and do not claim active transmission without a verified trigger. The page shows per-stock routes, peer coverage, quote gaps, and opening/post-open status.

The 18 catalog stocks with no relationship and 31 monthly-pool-only stocks are distinct. No relationship was invented for either set. The 698-stock monthly research pool is preserved. Source market returns are not HK predicted returns or trade returns.

Full publication initially failed when an 82,083,879-byte result exceeded the existing 64 MiB read cap. The narrow repair permits 128 MiB only for plan snapshots and PUBLISH checkpoints, including immutable collision readback. The global SafeRoot and other record limits remain unchanged. Both runtime R2 releases differ from their R1 baselines only in store.py; the failed attempt remains preserved.

## Actual US 16 October result

- Manual run: `571e25ceffed46528fbc6b8ea45de3d3`; target HK session `20261020`.
- Job: `DONE` / `PARTIAL`, no failed steps and no failure code.
- Requested source symbols: 547; valid date-bound quotes: 490; isolated source gaps: 57. The existing owner published one historical-backfill artifact; no second provider capture was used for the repaired run.
- Catalog relations: 1,003 unique records; 933 quote-bound, 70 with explicit quote gaps.
- Monthly pool: 698 unique stocks; 300 observations, 355 unassessed, 43 unmapped. Potential benefit and risk lists are both zero under the frozen policy.
- Peer observations: 337 groups across 280 HK stocks; source moves are 119 up, 212 down, 2 flat and 4 unknown. These groups are not a ranked HK opportunity or profitability claim.
- All 698 stocks show `PENDING_OPEN`; the target opening had not occurred at the run cutoff. No post-open return, probability or opportunity score was fabricated.

Outer legacy candidate counts (701 stocks, including 3 outside-pool observations) and the original 36 relation rows / 19 HK targets remain separately labelled; they do not truncate the full catalog results.

## Provenance and validation

Base commit: `46ec29868c5ba684d2d5c9b4cec143bc8c2143f5`.
Work branch: `codex/full-us-hk-mapping-consumption-20261019-r1` in the authorized `lexi2016/v4` repository.
Source workspace and per-file before/after SHA-256 are recorded in `SOURCE_DELIVERY_MANIFEST.json`. Runtime overlays preserve the existing API/scheduler differences; the canonical workspace's unrelated edits were not overwritten.

Independent source/identity and real-input candidate reviews are preserved in `INDEPENDENT_REVIEW_R2.json` and `INDEPENDENT_REVIEW_BEFORE_PUBLISH_REPAIR.json`. The incremental persistence review is `INDEPENDENT_PUBLISH_REPAIR_REVIEW.json`: focused pytest passed 3 tests, exact saved checkpoint publication and API readback passed on both inactive candidate roots, and the 128 MiB + 1 byte boundary remained rejected. Prior valid mapping tests were reused rather than repeated without changes. One unrelated legacy fixture failure had been reproduced on the baseline and was not changed.

API R2 manifest: `9cdbb692be8630425792449ce00ff7710ad4253c9f36c9c20f4f5d32478805e7`.
Scheduler R2 manifest: `f273d60db4935d6654df3d9042a837002f0d5606d2bace03cac4bdf3ea0b42be`.
Actual snapshot SHA-256: `7346b4635d9b3784194738806cd5663470db5dd3a850a0552bf228846bb30788`.
Input payload SHA-256: `e60cf4282db3394061edebf930e07588bf67fe516ef217e02b45993fdec7861e`.

Local deployment receipts verify both loaded runtime identities, inventories and unchanged configurations. Scheduler cutover preserved the PDF queue records. Saved API responses, full expanded accessibility readback, and screenshots identify the same run. Final independent live acceptance is `REVIEWED/PASS` in `INDEPENDENT_LIVE_REVIEW.json`: manual-run `BEHAVIOR_VERIFIED`, `API_VERIFIED` and loaded-page `UI_VERIFIED`. Natural-session results remain unverified.

## Boundaries

`RESEARCH_ONLY=true`, `production_allowed=false`, `buy_gate_updated=false`, `orders_sent=false`.
Target-date formal Connect eligibility remains `CANNOT_CONFIRM`; historical PIT, natural-slot execution and strategy effectiveness are unverified. The data is a historical-backfill observation and this single-day run demonstrates engineering consumption/publication/display only. Strict V1 research and missing-HK-history work remain paused.

Source synchronization includes only necessary source, tests, frozen policy and compact evidence. Raw material, quote payloads, runtime releases, large API responses, logs, screenshots, credentials, node_modules and dist remain local. No merge or visibility change is authorized by this delivery.
