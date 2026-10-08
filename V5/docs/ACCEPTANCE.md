# V5 foundation R1 — actual verification

This is a partial implementation of PLAN.md, not an operational stock-selection system.

- Source byte validation, strict request/module contracts, isolated composition CAS, health-state separation and legacy result mapping have product code.
- Actual ordinary dot cloud execution: Python 3.12.14, standard-library unittest, 41 tests PASS, no skipped tests. Per-batch RED/GREEN logs retained locally. No Codex cloud task was started for these checks.
- A separate private Python3.14.7 environment with pandas2.3.3/pyarrow24.0.0 was prepared; no claim of full reader or native Mac validation is made.
- Tests use synthetic files and dictionaries. The original rebound reader, complete Parquet path, worker isolation, immutable shadow storage and CLI are NOT yet verified or complete.
- `run_legacy_screen` refuses missing/unverified source closure. OWNER_VERIFIED execution also refuses missing immutable owner snapshot admission. These are intentional incomplete delivery boundaries, not repaired business outcomes.
- No product deployment, V4 changes, new price input, natural execution, stock recommendations or orders.

## Mac independent test request

Fetch the exact supplied remote commit into a NEW isolated V5 test directory. Do not checkout over a V4 workspace.
Record Python/OS and exact commit; no global dependency installation is needed for this foundation suite.

Run from V5:

    PYTHONPATH=src PYTHONDONTWRITEBYTECODE=1 "$SERVICE_PYTHON" -m unittest discover -s tests -v

Expected foundation suite: 41 tests. Report actual stdout, exit code, any differing count and failure trace. Do not modify product code to make it pass. Do not run acquisition, original owners, deploy scripts or V4 services.

The source capsule and dependency closure remain a separate next batch. A foundation PASS is not business migration PASS.
