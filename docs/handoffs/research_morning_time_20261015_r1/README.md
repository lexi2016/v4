# Research workbench morning source/time repair — 2026-10-15

The early-morning adapter overwrote the article source with its feed category, producing duplicate `morning` labels. The repair preserves the source, keeps category separately, and centralizes time/source presentation while retaining existing composable exports. Missing capture time and naive publication timestamps remain explicitly unverified, with reasons and the raw publication field; no historical data or timestamps were synthesized.

## Scope and identity

Only three research frontend implementation files and the ResearchView regression tests changed. Canonical source is `/Users/lexi/Desktop/学习/v4_app`. The remote base is `6e0134ef0daaf6525f12176e12b3fe8ceca606e0`; its three pre-existing target files matched the writer before-snapshot byte for byte. The local working-tree baseline commit is recorded separately in `receipt.json`.

The live release was built as an explicit delta on `hk-history-unified-api-20261015-r1`, not by replacing the live app with the dirty canonical checkout. `runtime-active-delta.patch` records the accepted source projection, preserving newer live title/role classification and subject filtering. Shared presentation helper bytes match canonical. The release adds one compiled main asset and updates the main HTML; 1,178 non-delta files remain identical. Build output is deliberately excluded from GitHub.

## Verification

Independent Luna Max reviewer: PASS, no P0/P1/P2 findings in scope. Canonical targeted tests: 40/40; live projection: 14 existing plus 2 independent regression tests. Production build passed. The projection typecheck has the same 34 diagnostics as its active baseline, with no new target diagnostics; this is not a full-project typecheck pass.

API activation and manifest verification passed; before/after morning content hashes match. In-app browser verified three source-preserving morning cards, all eight feed filters, EXACT date changes, LATEST, both WeChat navigation entries, and wide/narrow layout without horizontal overflow. No browser console errors observed. The first original-link click did not expose a new in-app tab, so external article landing is not claimed verified.

## Remaining evidence gaps

- Existing morning artifacts supply no acquisition timestamp or publication timezone. The UI retains `CANNOT_CONFIRM`, explains why, and displays the original publication value.
- Top-level global Refresh Snapshot returns to stage view. The unchanged global navigation was recorded, not expanded into this bounded research repair.
- The selected-day WeChat archive index returned no match. Per user instruction, this module was inspected but not modified.
- Natural scheduled execution was not rerun or verified. No historical inputs, outputs, scheduler configuration, BUY gates, or order paths were changed.

See `receipt.json` for source hashes, release identity, tests, and separated delivery statuses. Private repository sync contains only source, tests, this receipt and the source delta; no raw business data, credentials, dependencies, or compiled distribution.
