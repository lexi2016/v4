# M05 R8 independent cloud failure reproduction

Purpose: reproduce the real strict PreselectionPoolStore being rejected because unchanged R8 checks a nonexistent public attribute. This is a BUG reproduction, not a production or positive daily acceptance test. The static reviewer has not run the product or harness.

## Run

Use an already-approved installed Python interpreter. No install, API credentials, data collection, network calls, production paths, V4 edits or product patches are required.

```
bash run_repro.sh /absolute/path/to/existing/python3
```

The launcher verifies fixed ZIP identities, extracts SOURCE into an independent new temporary directory, and overlays the two exact R8 Python files. It intentionally does not use the incomplete R8 patch. It retains stdout, stderr, interpreter, input identities, actual exit code and workspace path.

The Python probe calls the original SOURCE make_lane with nonempty fupan input. It loads the real PreselectionPoolStore and real StoreGateContext through the unmodified _FrozenLoader(_source_bytes()) in a clean namespace, constructs a genuine strict store, and calls unmodified R8 build_m05_daily with correct independent roots and a real shadow marker. A sentinel runner only asserts that assembler execution was never reached; it does not emulate a store or produce results. No FakeStore, subclass, monkeypatch or public-attribute injection is used.

The context is explicitly SYNTHETIC and has no permit; its zero hashes are not authorization. This is appropriate because the demonstrated bug occurs before assembler and before any write/gate-validation method. The probe does not claim permit or successful store-write coverage. It checks that output still contains only the shadow marker.

Expected unchanged-R8 output: `BUG_REPRODUCED: real strict store falsely rejected before assembler and writer; no output write`, exit 0 for the reproduction harness. This means product failure was observed, not that M05 passed. Any other exception is an actual blocked/inconclusive repro and must be reported with the raw traceback, not reclassified as the intended bug. Do not fix or monkeypatch R8 during this run.

## Fixed identities and scope

- SOURCE ZIP: 227457 bytes, SHA256 241f56dbff2bd91514eaa976239007ca53f73d48cfce20bf173fbfadfd6a4d27.
- R8 ZIP: 11491 bytes, SHA256 61164b69960de0741dbaa157e4704cff431538a00eadf99550b0eaa934edfab2.
- Exact artifact identities are also in INPUT_MANIFEST.json.
- Product API is PreselectionPoolStore, not ResearchPeripheralStore.
- SOURCE fixture: V5/tests/test_a_preselection.py:10 make_lane; :77 original cold-loader example.
- SOURCE real strict constructor: V5/vendor/a_preselection_baseline/infrastructure/preselection_pool_store.py:223–243; stores `_require_write_gate_context` and `_write_gate_context`.
- SOURCE five-field context: same vendor root/infrastructure/scope_gate.py:50–62.
- Publisher contract, read only: handoff/v4-running-source-20261005/canonical/ops/materialize_scheduled_preselection.py:478–531. Do not import the old V4 publisher's incomplete closure.

The fixed SOURCE contains the loader and the store dependency closure. This chosen path imports stdlib/fcntl-based store components and uses make_lane's stdlib CSV/JSON generation; it deliberately avoids assembler execution, V192/oracle/parquet, optional research/HK branches and their dependencies. Runtime imports are still unverified until this cloud run. If import fails, record the original error; do not install packages or invent replacements.

Optional separate scope: original 29+1 fixtures may be run on the isolated tree using `PYTHONPATH=<tree>/V5/src python -B -m unittest discover -s <tree>/V5/tests -p 'test_a_preselection*.py' -v`; those can require numpy/pandas/pyarrow. Passing them does not validate R8 daily. Do not fold them into this minimal bug-reproduction result.

No true factory, successful store write/readback, full diagnostics, aggregate-conflict protocol, final same-lock batch identity or production integration is claimed. Those remain separate implementation/acceptance work.
