# V4 Workbench Top200 group candidate

Status: `CANDIDATE_NOT_DEPLOYED`.

The candidate adds Top200 as a filter inside the existing stock list. It reuses the existing `StockPanelHost.paintTop200()` request and forwards that response once to the list. It does not fetch or store a second Top200 copy, add Top200 to `day.rows` or `GROUPS`, or change B23/PB2/研报 membership. Formula-pool members keep the existing chart/detail path and display their Top200 rank. A Top200-only row shows its close, daily change, amount, and rank with explicit formula-pool and chart-unavailable status.

## Asset ownership and integration

- Served UI assets are rooted at the active API release's `research-panel` directory and pinned by `research-panel-assets.json`. The exact baseline was read from `/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-workbench-jp-kr-context-20261118-r1-api/`.
- The current Main snapshot's `ops/build_mac_workbench.py` is a separate build input (SHA-256 `97da5a22438aa8df31a5c89cc6881aa39a096c1fc6f57f11078b97f14d071fd6`). This candidate does not modify that external snapshot or run its build. The static API asset root is the serving owner for this proposed cutover.
- To integrate, place the three files under `overlay/` at the same relative paths in the detached replacement API release's static root, then use the included 493-entry `research-panel-assets.json`. Its unchanged 492 records retain their original SHA values. Do not duplicate the full static tree; the overlay contains only two modified assets and one new helper.
- The active API plist must point `V4_RESEARCH_PANEL_ROOT` and `V4_RESEARCH_PANEL_ASSET_MANIFEST` to that same detached candidate release. Parent/controller owns this integration and any eventual activation.

## Exact candidate files

| Relative path | Bytes | SHA-256 |
| --- | ---: | --- |
| `workbench-host/bootstrap.mjs` | 34,350 | `403207bb80597b8f46e9e279018ce6a7a1f0a4a52286e61e5db4587b3e06be22` |
| `workbench-host/dot/shell/workbench.local.mjs` | 61,405 | `83587177505456c9bf526b31eb3a8fe9f46d155b072acfb01d68eb42bd4d1084` |
| `workbench-host/top200-group.mjs` | 2,441 | `c673b7f74205982b9ca8cff46618c9a34cba410fb3a605dd7b0832880390e0fa` |
| `research-panel-assets.json` | 79,588 | `acf58256cff1483d95e4d19dbbae6a060c39a9c77ba19ab68f15d9726ea3d4ca` |

`overlay.patch` is a unified diff against those exact active API assets.
The two modified static output files remain in the local overlay for the controller's candidate packaging. Git synchronization includes the patch, the new helper source, updated manifest, tests, and concise receipts; it excludes those two raw static outputs.

## Focused verification

- `node --test docs/handoffs/v4_workbench_top200_group_20261118/tests/top200-group.test.mjs`: 4 passed. Covers ordered 200 rows, partial/empty states, stale date, duplicate identity, rank gaps, and research flags.
- `node --check` passed for the three JavaScript assets.
- Live API read for 2026-11-18 returned exactly 200 rows ranked 1–200; the daily formula endpoint had 29 rows and overlapped 17 Top200 rows. `920924.BJ` is a Top200-only example; its formula daily-K endpoint returned HTTP 404 (`WORKBENCH_DAILY_K_SYMBOL_NOT_BOUND`), which the UI presents as unavailable.
- Live API read for archive date 2026-10-28 returned `CANNOT_CONFIRM_NOT_MATERIALIZED`; the validator maps this to the explicit empty/not-materialized list state instead of retaining 11/18 rows.
- Manifest comparison found exactly three changed paths: the two existing assets and the new helper. The other 492 asset hashes are unchanged. Only the existing Top200 fetch remains in `bootstrap.mjs`.
- Isolated Playwright smoke intercepted only the three candidate JS assets while the HTML and API remained served by `127.0.0.1:8873`. It verified D18 rank 1 and 200, visible price/change/amount, 192/PB2 counts 24/6, the rank-1 chart-unavailable state, exactly one Top200 GET per date, the 10/28 not-materialized state, and rejection of an injected stale D18 event after switching to 10/28. No uncaught page errors. Full evidence is in `BROWSER_SMOKE.json`.

Not run: deployment, API restart, or a build through `ops/build_mac_workbench.py`. The live page was not changed.
