# Independent reviewer probes

These tests use synthetic, offline inputs. By default they discover the
`worktrees/manager_automation` sibling of this reviewer directory or use the
current working directory when it is the checkout root. When copied to a
different machine, set `MANAGER_TEST_SOURCE_ROOT` to the absolute checkout
root. The tests prepend that root and its `upstreams` directory to `sys.path`.

Run the Python owner checks from any working directory. The renderer import
closure probe is deliberately excluded; run it separately as a blocked-source
diagnostic below.

```sh
MANAGER_TEST_SOURCE_ROOT=/absolute/path/to/manager_automation \
PYTHONPATH=/absolute/path/to/manager_automation:/absolute/path/to/manager_automation/upstreams \
/absolute/path/to/python -m pytest -q \
  /absolute/path/to/reviewer/test_us_daily_owner_independent.py \
  /absolute/path/to/reviewer/test_daily_full_chain_independent.py \
  -k 'not actual_renderer_and_validator'
```

The currently blocked actual renderer probe is run separately so its missing
shared import closure cannot be confused with the synthetic owner-chain
results:

```sh
MANAGER_TEST_SOURCE_ROOT=/absolute/path/to/manager_automation \
PYTHONPATH=/absolute/path/to/manager_automation:/absolute/path/to/manager_automation/upstreams \
/absolute/path/to/python -m pytest -q \
  /absolute/path/to/reviewer/test_daily_full_chain_independent.py -k renderer
```

HK publication-chain and UI probes live in independent files and are run
against source-specific hashes. Every run record must state its exact test scope,
source SHA-256 values, and any unavailable runtime/model boundary. No probe in
this directory represents natural schedule execution or live source
availability.

## Frozen delta follow-up probes

With the 2026-10-08 candidate source tree, run the independent reviewed-source
window probe and the complete independent HK gate probes with:

```sh
MANAGER_TEST_SOURCE_ROOT=/absolute/path/to/manager_automation \
PYTHONPATH=/absolute/path/to/manager_automation:/absolute/path/to/manager_automation/upstreams \
/absolute/path/to/python -m pytest -q \
  /absolute/path/to/reviewer/test_daily_reviewed_source_window_independent.py \
  /absolute/path/to/reviewer/test_hk_publication_chain_independent.py
```

The source-window test creates reviewed synthetic announcement products through
the original import route. It adds a newly reviewed product for the older
`20261006`/`2026-10-05` pair after a `20261008` plan is sealed, then confirms
the unchanged ordinary dynamic GET exposes the wider saved source-date window,
marks the previous plan stale because the consumed source set changed, and
preserves the prior sealed plan bytes. The HK cross-date case calls the exact
07aa child entry on two synthetic dates using the original collector, original
HK0.2 updater algorithm, V2/master publishers and readers, and chain reader;
the test-only Futu feed, seed model panel, and supplement outcome are documented
in `final_review.json`.

The external TypeScript probes need the checkout's actual Vite dependency tree.
The runner takes `MANAGER_TEST_SOURCE_ROOT`, `V4_TEST_SOURCE_ROOT`, and
`V4_TEST_PYTHON`; `V4_TEST_NODE_MODULES` can override the dependency path. When
run from the reviewer directory, it discovers the sibling worktree and the
local `candidate/apps/web/node_modules` dependency tree by default. It
temporarily copies the reviewer specs into `apps/web/src/manager-selection`,
creates an `apps/web/node_modules` symlink only if absent, runs Vitest, then
removes both temporary paths. It does not add production source files.

```sh
MANAGER_TEST_SOURCE_ROOT=/absolute/path/to/manager_automation \
V4_TEST_SOURCE_ROOT=/absolute/path/to/manager_automation \
V4_TEST_PYTHON=/absolute/path/to/python \
V4_TEST_NODE_MODULES=/absolute/path/to/apps/web/node_modules \
/absolute/path/to/python /absolute/path/to/reviewer/run_ui_actual_route_probe.py
```

The two independent UI assertions exercise the exact TestClient refresh-to-
ordinary-GET DTO and the actual owner fixture. The first sends that route DTO
through `validateManagerWorkspace` and `projectDailyResearchSummary`, checking
the returned `read_at` is at or after both `generated_at` and
`owner_finished_at`. This proves a TypeScript projection contract only; it does
not verify a parent page mount, browser reload, deployed UI, or natural run.
