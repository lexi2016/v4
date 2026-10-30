# Workbench engineering candidate · 2026-10-30

Status: IMPLEMENTED / TARGETED_TESTED / BUILT. Independent review, integration,
installation, real browser and natural-slot acceptance belong to Root. This
handoff does not claim those stages passed.

The fixed Dot framework remains the 46-file 0ae4a66 source lock. Its 48-file
remote successor is not overwritten or implicitly imported. All seams are in
our derived Mac host. The builder checks each exact source SHA, unique anchor
and block order before writing output, and exports a deterministic runtime
allowlist. The existing individual `daily.html` remains reachable.

## Behavior and source boundaries

- Day/list and saved statistics have independent manifests. A day GET reads one
  product summary and one small saved rates projection; it never opens 247 full
  products/checkpoints or evaluates historical labels/returns.
- Saved observations, overseas materials and execution receipts have their own
  content versions. The GET-only `/workbench/days/{source_date}/events` SSE
  observes committed files using the existing research SSE pattern. Events only
  invalidate views; fresh GETs validate identity before replacing content.
- List/statistics refresh preserves selected stock, group, sort, pagination and
  chart window. Date/generation changes rebind explicitly. Async replies use
  the day/request serial; replayed events cannot supply old content directly.
- Only headers sort. D+2/D+5 show positive fraction and valid n. Zero sorts as a
  value, unavailable/immature rows sort last in both directions. The all-group
  view uses the first TRUE group in the established group order; each rate's
  visible sublabel and title name that group. Detail event lists locate exact event dates in the
  existing renderer, without recomputing an event or return.
- `chart_review=UNKNOWN_NOT_REVIEWED` remains compatible with Dot validation.
  User postponement is a separate `execution_status=DEFERRED_USER`.
- Twenty original plan nodes show actual evidence, source/recorded times,
  material links, errors and missing inputs. Bad evidence is isolated per node.
  `NOT_DUE` expires to `CANNOT_CONFIRM_OVERDUE`; a clock never makes a node
  completed. Changing date reloads the workflow using `?source_date=` and
  discards evidence from another observation date.
- A current original A-lane receipt can be projected for nodes15/17. A top-level
  dispatcher success is never used as business completion. A READY A receipt
  only completes node15 when its SHA matches the same-day numeric product's
  selector artifact. Node17 cannot infer a retry from main-run success.
- Company holder changes preserve the existing statistical/disclosure dates,
  source and evidence status. Missing comparable periods remain unknown.
  Report metadata/source links and stored-reference gaps remain distinct from
  full-text readability or fact acceptance.

## Exact deployment roles

Root must transplant the allowlisted files into copies of the actual live roles,
not replace a role with this entire worktree.

API app: `infrastructure/research_workbench_host.py`. Keep the accepted live
`research_router.py` workbench inclusion; its equivalent source is in the
allowlist and was already present before this Writer. Keep the live accepted
`research_lane_source.py`, SSE owner, static mount and other routes.

Main app: `ops/research_panel_daily_product.py`, `ops/build_mac_workbench.py`,
and the already accepted `domains/research_event_case_cache.py` plus
`domains/research_daily_statistics.py` dependencies. Their exact frozen SHAs are
listed in the source freeze's deployment dependencies; the statistics source
SHA is part of the SQLite namespace and must match the accepted store.
The current live Main has no daily product reader methods, so statistics
materialization deliberately reads the producer's hash-bound saved refs and
has no dependency on a newer API reader. Preserve the accepted live gate at
`ops/macos_research_panel_daily_gate.py`; it already calls the owner with
`Path(V4_A_SHARE_DAILY_PRODUCT_ROOT)/'daily_products/a_share'`.

Observation caller app: `ops/collect_workbench_observations.py`,
`ops/run_workbench_observation_slot.py`,
`infrastructure/research_workbench_host.py`, the existing calendar/parser
modules. Invoke with the same installed interpreter using `-m` from its app
root. This Writer installs no job.

Static: build output's `MAC_RUNTIME_ASSETS.json` enumerates workbench paths and
SHA. Preserve the original46 vendor bytes, existing individual assets and
static mount. `research-panel/code-map/` is an incremental, sanitized source
map; its source evidence and Archify explanation are separate from runtime
acceptance. Root may add its existing static paths to the bound asset manifest.

Main environment bindings:

```text
V4_A_SHARE_DAILY_PRODUCT_ROOT=<existing today_full_r1 parent root>
V4_RESEARCH_EVENT_LABEL_SOURCE_ROOT=<accepted daily_products/a_share directory>
V4_RESEARCH_EVENT_CASE_CACHE=<existing unique event_outcomes.sqlite3>
V4_WORKBENCH_STATISTICS_ROOT=<statistics projection root>
```

The original A_LONG owner remains responsible for serialization. The daily
owner compares the index captured before computation with the index immediately
before publication and fails on CAS movement. It restores labels only via
accepted `history_sync.stock_results -> RESULT.history_cache` refs, verifies
rule/config and consumed old price prefix, then appends the current evaluation
in the new original daily checkpoint path. Frozen R2 checkpoints remain read-only.
Cache semantic identity reuses the original reader ref, formula/rule and basis;
generation/asof alone does not invalidate mathematical outcomes. Revisions,
maturity and missing-price repair use the original cache's dependency checks.

## Reproduction

Use Root's absolute `PANEL_PYTHON`, the existing task worktree, and the actual
fixed46 source directory. Never run this against the remote48 source silently.

```sh
"$PANEL_PYTHON" -B -m ops.build_mac_workbench --dot-root "$DOT46" --receipt research/stock_panel_collab_20261030/mac-host/DOT_SOURCE_LOCK.json --output "$CANDIDATE_STATIC"
"$PANEL_PYTHON" -B -m ops.build_mac_workbench --statistics-product-root "$ACCEPTED_PRODUCTS" --output "$STATISTICS_ROOT"
DOT_FRAMEWORK_SOURCE_ROOT="$DOT46" "$PANEL_PYTHON" -m pytest -q tests/test_mac_framework_host.py tests/test_daily_product_durable_cache.py tests/test_workbench_observations.py --basetemp="$OWN_TEST_TEMP"
```

The statistics command only projects saved, identity-checked values. It does not
open the SQLite cache, call formula engines or recompute labels/returns.

Rollback: restore only Root's prior role/static manifests and the preinstall
allowlisted bytes under the existing release lock/CAS. Preserve data, accepted
labels/outcomes, old failures and original artifacts. A source rollback does
not erase newly saved valid data.

RESEARCH_ONLY=true; production_allowed=false; buy_gate_updated=false;
orders_sent=false. Financial chart-pattern review remains user-postponed.

## User-entry migration delta

The default `daily.html` request now307-redirects to the reviewed exported
`workbench.html` while retaining the original query string. This is conditional
on `workbench.html` being in that role's static allowlist; other roles retain
their prior behavior. The fixed `legacy-daily.html` alias explicitly serves the
old daily bytes through the same safe path/hash checks. The top link and material
reference call it `旧版单股归档`, carry the selected source date, and never point
back to the migrated default entry.

The new entry accepts ISO or eight-digit `date`. A requested day absent from the
catalog remains selected as `未物化 / CANNOT_CONFIRM` and reads only that day.
Malformed dates fail visibly and never select the latest catalog date. Existing
stage query parameters survive migration; Stage/homepage behavior is unchanged.

The former daily HTML/JS are still used by the explicit archive alias and are
not deletion candidates while that alias remains. Frozen vendor sources,
original single-stock renderer dependencies, active sources and rollback copies
also remain in use. Root owns any bounded move to a pending-deletion directory;
this Writer performs no bulk move or deletion.
