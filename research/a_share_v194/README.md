# 194 source/resonance research runner

This module consumes a frozen derived CSV from existing shared producers. It
does not fetch data, generate buy points, change services, or submit orders.
All results remain research-only. Current real-data training is blocked pending
independent lineage/design review. Synthetic canary results are engineering only.

`model194.py train EXECUTION_CONTRACT.json` runs fixed L2 logistic regression
(C=1, lbfgs, seed=194, max_iter=1000, tol=1e-8) for a technical baseline and the
same model plus source/pool memberships and resonance counts. Both use exactly
the same rows. StandardScaler is fitted separately on each training fold only.
`model194.py predict EXECUTION_CONTRACT.json` loads plain JSON coefficients and
writes daily Top50 candidates without loading sklearn or deserializing pickle.
Both commands append RUN_STARTED before loading input rows and append a terminal
event on success/failure through the existing official registry adapter.

Input requirements and unresolved semantic bindings are frozen in the local
`research/a_share_v194_20261023/INPUT_CONTRACT_V1.json`. Every labelled row has
signal_date, code, signal_at, available_at, label_end_date, a binary label, and
all configured technical/source/pool columns. Dates use ISO YYYY-MM-DD and
timestamps include timezone offsets. `available_at` is the latest availability
across every feature dependency, including source nonmembership evidence.
Unknown or unavailable features fail closed for both arms; they are never zero.
Historical absent membership can be zero only with independently bound coverage.

Splits carry train_end, eval_start/end, truth_asof, an explicit producer calendar
evaluation_dates, and kind=oof/final/diagnostic. Training labels ending on or
after eval_start are purged. Evaluation labels must have matured by truth_asof.
Overlapping evaluation folds and non-diagnostic evaluation on the five exposed
2026-10-16/19/20/21/22 dates are rejected. Explicit calendar dates retain empty
candidate days in the 50-slot/day denominator; shortages receive no padding.
Full-universe truth counts are separate from candidate positives and slots.

Pool/source membership counts describe memberships, not independent origins.
An independent-origin count is optional and requires a separately bound mapping
from all source flags to verified origin groups. No source count is inferred
from namespaces or pool names. Exact 192 and ten main-chart buy-point semantics,
including B1 J<=13 and BBI>white>yellow, must be supplied by the existing producer
and reviewed before a real fit; this module does not recreate old formulas.

Outputs are separated per split and arm: train keys, JSON model, probabilities,
daily Top50, and metrics. The JSON export is read back and prediction parity is
checked before publishing the run result. Output paths must be new, preserving
prior runs. Models are empirical research outputs, not promotion receipts.
Primary paired deltaHit@50 and block-bootstrap acceptance remain pending the
final design contract; this engineering version reports deterministic counts
without inventing a promotion threshold or claiming an out-of-sample victory.

The CLI execution contract must have execution_kind=TRAIN/PREDICT,
run_config_path and run_config_sha256, plus the usual registry bridge fields.
The run config binds input_csv/input_manifest and their SHA256, output, and
model_config for training or model_path/model_sha256 for prediction. Every
execution needs a distinct registry execution_id and a new output path.

Tests: `python -m unittest discover -s PATH_TO_MODULE -p test_model194.py -v`.
Register the frozen ENGINEERING_CANARY execution before running tests. They use
only synthetic fixtures and record synthetic and real fit counts separately.
The executable CLI forces OMP/OpenBLAS/MKL thread counts to 2; callers importing
the module must set those variables before NumPy imports.
