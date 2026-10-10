# Offline test support

The product change is only `../runtime.patch`. This directory is an isolated test
scaffold and must not be copied into the Mac production application.

## Provenance and reproducibility

- `current/` contains nine unchanged files needed by the focused tests or static
  entrypoint review. Their bytes match the uploaded fixed snapshot or the exact
  recovered SHA listed by the problem report. The source gate checks them as
  unchanged prerequisites.
- `upstream/` contains the 26 frozen missing modules actually loaded by the final
  Python/TypeScript tests. Their repository source locations and hashes are in
  `../reports/test_support_sources.json` and `backend.support_sources.json`.
  **Their current deployed identity is unverified.** They allow an offline module
  test; they do not prove compatibility with the complete running application.
- `DEPENDENCY_CLOSURE.json` lists every included current/upstream module and hash.
  The final test JSON also records the loaded-module identity for each run.
- `vendor/linkedom-worker.mjs` is unmodified official WebReflection/linkedom
  `worker.js`, tag `v0.18.12`, git blob
  `21ed3f9cf1d80eebb2d0448d95c0dd080a5fd9fe`, SHA256
  `196efeb17c260e001979dbc54a3c30e701a881c6e8a3eedaddc5ad83c99ee5ff`.
  Its original ISC license is `vendor/LINKEDOM-LICENSE`, upstream blob
  `48afbe52afb5895b682e9b877bae10f96049a446`.

## Portable entrypoint

From the package root:

```bash
python3 tools/run_offline_tests.py --side after --report-dir /tmp/v4-manager-r1-after
python3 tools/run_offline_tests.py --side before --report-dir /tmp/v4-manager-r1-before
```

The before run is expected to exit nonzero because it runs the repair regressions
against the actual original bytes. The after run must pass. Both assemble a
temporary source root and leave delivered files unchanged. `--suite backend` or
`--suite frontend` selects one side of the test coverage. `--node /absolute/path`
selects a Node runtime. Outputs must be outside the package.

The optional benchmark can use Python namespace-package overlays directly:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=after:test_support/current:test_support/upstream \
  python3 tests/benchmark_backend_identity.py --rows 1970 --repeats 3 \
  --output /tmp/v4-manager-r1-attention-benchmark.json
```

The included benchmark JSON is one retained synthetic timing result, not a live
latency claim. Re-running a benchmark naturally produces different timing samples.

## Scope

Backend fixtures are temporary synthetic archive/receipt and sealed-plan objects.
They exercise original source/plan guards, but they are not live owner receipts
or a complete `_compute_workspace`/HTTP execution. Source support is intentionally
frozen, not fetched or installed while the tests run.

The frontend mounts the actual TypeScript panel, response validator and renderers.
Only fetch responses are synthetic; an unconfigured fetch fails closed. It uses
Node's experimental TypeScript transform and LinkeDOM, with two explicit shims
for `select.value` and reflected `details.open`. Tests explicitly dispatch
`toggle` for details. There is no browser layout, paint, screenshot, native
details click, real navigation or live service. Reports retain
`DOM_INTEGRATION / LIVE_API_UI_NOT_RUN`.

The normal project Vitest suite, TypeScript type checking, Vue/Vite build, real
browser, Mac owner, deployment and natural-session acceptance remain `NOT_RUN`.
