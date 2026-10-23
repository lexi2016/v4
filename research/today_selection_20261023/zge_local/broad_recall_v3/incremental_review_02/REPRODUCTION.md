# Ten-route canary source archive

Scope: `PASS_TEN_ROUTE_CANARY_ONLY`. The unchanged original independent canary evidence plus two incremental synthetic assertions passed. This does not certify data recovery, full-pool recall, live Futu/Windows parity, model performance, or V4 deployment. Full05 is HOLD/CONTRACT_ONLY; second screening has not run.

The six self-written source/test/config files are archived unchanged. Two small fixtures are purely mathematical, not real market rows: `test_canary.synthetic_streams()[0]` uses fixed NumPy `arange`/sinusoidal close and volume, fixed jumps/pullbacks, first 301 rows; the first fixture changes final VOL to null, the second also changes final C to null. Synthetic date strings and the symbol identifier do not describe observed prices. Their frozen SHA and independent results are in the allowlist/summary.

This package is NOT self-contained or installed. `formula_kernel.py` requires the original local user formula, parser, and fixed-commit brick dependencies at its declared paths with matching SHA; see SOURCE_DEPENDENCY_IDENTITIES.json. Those source bytes are excluded under the no-vendor/no-user-formula upload restriction. Existing NumPy/pandas runtime is required; the old real-sample suite additionally requires its private frozen local inputs. No real sample, private source/panel manifest, root registry, or market data is uploaded.

Historical incremental command (already executed independently; do not re-run merely to archive):

```sh
PYTHONDONTWRITEBYTECODE=1 /Users/lexi/Documents/Codex/2026-08-13/factor-mining-mac/.venv-training-v1/bin/python -B /Users/lexi/Desktop/学习/因子工厂/worktrees/zge_local_selection_20261023/research/today_selection_20261023/zge_local/broad_recall_v3/test_partial_unknown.py /Users/lexi/Desktop/学习/因子工厂/research/today_selection_20261023/zge_local/broad_recall_v3/incremental_review_02/REVIEW_CONTRACT.json
```

The original local REVIEW_CONTRACT and prior review receipt remain prerequisites: the test intentionally verifies their frozen identities and source/fixture paths. These local evidence contracts are not in this minimal Git package. To reproduce elsewhere, first obtain the required fixed source and evidence through the authorized local path, prepare a new contract binding the same bytes and output directory, register START, and run only the intended incremental scope. Do not present copied files as an immediately runnable or deployed product.

The independent reviewer used the same frozen test via runpy with its directory on sys.path, suppressing only its optional receipt write after all assertions; its own receipt is the evidence summarized here. No production change, repeated old-suite check, full-pool run or new market request was performed during packaging.
