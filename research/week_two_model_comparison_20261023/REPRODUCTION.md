# Frozen weekly descriptive comparison

This code uses the existing local source owners and fixed formula implementations. It does not bundle formula text, the source owner, native prices, the registry or input manifests. It is an offline research artifact, with no service, UI, account or trading integration.

The local baseline is `55a5ba0b8aef8e83dfd04fdbabefb8d9baa1d054` on `codex/week-two-model-comparison-20261023`. Runtime is the existing training Python documented in `weekly_compare.py`. Contract and outputs reside at `/Users/lexi/Desktop/学习/因子工厂/research/week_two_model_comparison_20261023`.

Actual stages use:

1. `python -B weekly_compare.py prepare` — immutable intake contract and actual official RUN_STARTED.
2. Freeze `EXECUTION_CONTRACT.json` binding `engine.py`, existing model implementations and source metadata; register its fresh execution ID before numerical checks. `python -B engine.py canary --contract <EXECUTION_CONTRACT.json> --workers 2`.
3. `OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -B engine.py full --contract <EXECUTION_CONTRACT.json> --workers 4` — retained per-50-code checkpoints. Each historical signal bounds raw inputs and events before reanchoring. The same source window is used by both formulas; D23 model B reuses accepted identical 65/67 results. Signal CSVs, tri-state ledgers and all original terminal values are frozen to `SIGNALS_SEALED.json` before benchmark launch.
4. `python -B benchmark.py` — requires and verifies the signal seal, freezes a separate actual benchmark execution and decodes the same-date research ranking. `UNKNOWN` is retained in a separate overlap category; common misses require two explicit `NO` results.

These are historical reproduction command shapes, not permission to overwrite an existing contract, source output or terminated execution. Use a new explicit registered execution ID and new output namespace for a fresh replay; preserve existing passed results. The parent process is the only registrar and output writer. Worker subprocesses perform no registry writes.

The root controller alone owns independent review and authorized remote CAS integration. A Writer receipt is not independent acceptance. Historical eligibility, archived event availability, source/PIT certification and cross-vendor unit parity remain `CANNOT_CONFIRM`. D23 close ranking is unavailable because the existing source ends at D22.

The main-five-day MODEL_B_ALL_RULES.csv files expand only records for which a source was acquired. Each main date omits the two source-UNKNOWN codes × ten long rows. The complete YES_NO_UNKNOWN.csv ledger retains both securities as UNKNOWN and lists all ten unknown_rules; the independent verifier restores rule coverage from this ledger. These CSVs are not complete Cartesian longtables. D23 reuses the older complete longtable semantics.

The repaired D23 research V192 result is seven candidates. The prior RAW5494 result of five candidates used a different input basis, window and source state. These results must not be collapsed or attributed to a single adjustment cause.
