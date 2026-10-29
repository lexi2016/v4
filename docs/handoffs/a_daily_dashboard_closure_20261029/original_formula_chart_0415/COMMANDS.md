Commands ran from the frozen task worktree. `PANEL_PYTHON` below means the
absolute interpreter:
`/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v4-mac/bin/python`.

1. `PANEL_PYTHON -m pytest -q tests/test_original_formula_projection.py --basetemp=docs/handoffs/a_daily_dashboard_closure_20261029/original_formula_chart_0415/pytest_tmp --tb=short` — 3 passed, 1 setup error (missing new parent directory).
2. Created only the owned handoff directory; `PANEL_PYTHON -m pytest -q tests/test_original_formula_projection.py::test_sha_drift_and_symbol_scope_fail_closed --basetemp=docs/handoffs/a_daily_dashboard_closure_20261029/original_formula_chart_0415/pytest_tmp --tb=short` — 1 passed.
3. Ran the projection command below once with `--symbol 600025.SH`, then once
   with `--symbol 000410.SZ --symbol 920454.BJ`. No sample was recomputed.

```sh
PANEL_PYTHON ops/render_original_formula_projection.py \
  --config docs/handoffs/a_daily_dashboard_closure_20261029/SOURCE_CONFIG.json \
  --coverage '/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/chart_batch_247/coverage_247.json' \
  --product-index '/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/today_full_r1/daily_products/a_share/index.json' \
  --renderer '/Users/lexi/Desktop/学习/因子工厂/research/tdx_panel_parity_20261028_r1/r19_copy/OUTSIDE151_R19/outside151/r19_work/research_reader/index.html' \
  --output '/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/original_formula_chart_0415' \
  --symbol 600025.SH
```

4. `/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node docs/handoffs/a_daily_dashboard_closure_20261029/original_formula_chart_0415/headless_readback.cjs '/Users/lexi/Desktop/学习/因子工厂/research/a_daily_update_path_20261029_r1/dashboard_completion_r1/dashboard_resume_20261030/original_formula_chart_0415'` — all three actual chart readbacks passed; browser/profile closed/removed.
5. Mechanical readback checked every output row's 51/22 shape, exact embedded
   row parity, unchanged original R19 `choose`/`paint`, and all input/output
   reference hashes. Opened all three screenshots with local image inspection.
