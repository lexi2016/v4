# Frozen source and installed readback

This fix changes the existing build seam and bootstrap, not the vendor framework.
The source delivery parent is `d1b9ae61310cd7f828a078e12255050ada7820bf` in
`lexi2016/v4`. Twelve accepted build/host dependency blobs were compared with that
commit before delivery and matched the accepted local source.

The builder already takes an explicit `--dot-root`. Its immutable vendor input is
the separate checkout of `lexi2016/v4` commit
`0ae4a66d90c12a0d0335b5f7f65b528879c5e9cf`, under
`research/dashboard_framework_collab_20261030`. All 46 blob IDs at that commit
match `research/stock_panel_collab_20261030/mac-host/DOT_SOURCE_LOCK.json`.
The parent delivery commit's framework directory has nine later changes; do not
pass that later directory as the fixed46 input and do not overwrite those changes.
This reuses the existing external frozen-input build contract.

With `PANEL_PYTHON` set to an existing project Python, `DELIVERY_ROOT` the current
delivery checkout, `FROZEN_ROOT` a checkout of the fixed commit above, and
`BUILD_OUTPUT` a new output directory, the original build entry is:

```sh
"$PANEL_PYTHON" "$DELIVERY_ROOT/ops/build_mac_workbench.py" \
  --dot-root "$FROZEN_ROOT/research/dashboard_framework_collab_20261030" \
  --receipt "$DELIVERY_ROOT/research/stock_panel_collab_20261030/mac-host/DOT_SOURCE_LOCK.json" \
  --output "$BUILD_OUTPUT"
```

Independent review: `REVIEWED_PASS`, no findings; review receipt SHA-256
`efc93972a11789374d22ef2019f8e87a1f7545d41125092f07fac4f08a8fa793`.
Existing host/build checks: 22 passed. Browser behavior checks passed at
694×869, 1440×869 and 390×869 before installation and against the actual
installed page, with no JavaScript page errors. Browser contexts and the owned
headless browser closed normally; no user window or input control was taken.

Installed local API release: `workbench-filter-layout-20261030-r1-api`.
API PID changed from 7521 to 34371 through the existing owner lease/CAS and
atomic-plist API-only cutover. The old release and original API plist remain
available for rollback. Main, scheduler and business data were untouched.
All application bytes and 481 non-delta static assets were preserved through an
APFS clone. Actual same-origin GET readback matched these reviewed static hashes:

| Asset | SHA-256 |
| --- | --- |
| `workbench.html` | `5799e8a390f3e81f73eb743f433fe5b8001f5ecad867abc715eba822b37592fa` |
| `workbench-host/bootstrap.mjs` | `839b7464016097c23f6ec95b98dea3a2bb7c73358e2fc2bb7be7761d0e03e2be` |
| `workbench-host/dot/shell/workbench.local.mjs` | `e072278b3098ffd9e24c28c184779cad474cd56d0ba0a032b24d143f2ca38713` |

The user URL retains `date=2026-10-29`. Saved candidate count remains 247,
page size 40 and page count 7. Last page contains seven rows. Source/observation
dates, formula, API, renderer, eligibility and trading gates are unchanged.
This verifies the requested layout behavior; it does not certify financial
semantics, PIT, natural market execution, strategy effectiveness or 469-stock
integration. Those are outside this UI repair.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false;
orders_sent=false.
