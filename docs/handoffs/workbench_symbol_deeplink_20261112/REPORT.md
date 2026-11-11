# Workbench direct-symbol selection fix

## Scope and evidence

- Baseline: `94c2a3dd659dc8c24344858dfe9bd7a8e993c231`; branch: `codex/workbench-symbol-deeplink-20261112`.
- Original failure is preserved at `/Users/lexi/Desktop/学习/agents调试/v4_daily_panel_futu1112_20261111/WORKBENCH_INITIAL_DEEP_LINK_FAILURE.json`: URL requested `600018.SH` for source day `2026-11-11`, while the loaded 426-row workbench selected `000159.SZ` and displayed its chart.
- The canonical source `apps/web/public/research-panel/workbench-host/dot/shell/workbench.local.mjs` matched the read-only active candidate byte-for-byte before editing (SHA-256 `86ae6ee169ecc96fd81a1444eb9811e635c70b55553916f53eda4ca74b61892e`). The runtime `kb-single-stock.mjs` and `bootstrap.mjs` have no tracked source mapping in this baseline; neither was modified.

## Cause and change

`loadDay()` cleared the current selection and eventually called `renderList(true)`, which always selected the first filtered row. That selection opened the single-stock host; its route writer replaced the requested `symbol` with the first row. The workbench now captures the URL symbol before async day reads, selects and pages to that symbol if it belongs to the current day's filtered rows, and preserves the existing first-row default when no symbol was requested. Malformed, duplicate, or out-of-candidate symbols retain the fallback and display `CANNOT_CONFIRM` with the actual fallback symbol.

Changed files:

- `apps/web/public/research-panel/workbench-host/dot/shell/workbench.local.mjs`
- `tests/frontend/test_workbench_symbol_deeplink.mjs`
- `docs/handoffs/workbench_symbol_deeplink_20261112/REPORT.md`

## Verification

- `node --test tests/frontend/test_workbench_symbol_deeplink.mjs` — PASS, 4 tests: valid deep link beats first row; no deep link preserves first-row behavior; malformed/duplicate/missing candidate falls back explicitly; `loadDay()` captures and passes the route selection to the first render.
- `node --check apps/web/public/research-panel/workbench-host/dot/shell/workbench.local.mjs && node --check tests/frontend/test_workbench_symbol_deeplink.mjs` — PASS.
- `git diff --check` — PASS.
- The independent three-market search/click run is separate evidence and does not replace the original direct-link FAIL.

## Not run / handoff

- No candidate rebuild, live-file write, service action, deployment, or post-fix browser run was performed. The runtime integration depends on the existing external KB host files; the root owner should exercise the direct URL after integrating this branch into a test candidate.
- Independent read-only review remains with the root owner. This is source/test PASS only, not deployed or UI-verified acceptance.
