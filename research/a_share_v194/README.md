# 194-R0 V2 research runner

V2 is explicitly PUBLICATION_TIME_RECONSTRUCTION / DIRECTION_ONLY. It never
sets historical_availability_bound=true or treats reconstructed history as live,
sealed, certified PIT or production. The accepted V1 source is archived locally.

Existing shared producers supply a bound V194_DATASET_MANIFEST_V2 plus separate
candidates, truth and calendar CSVs. Candidate keys and every ranking/split use
(target_date, code). signal_date is the previous trading day, decision_at is
target_date09:25+08, label_end_at is target_date15:00+08; label_available_at is
independent. Truth is joined only for training/evaluation. All 11 exact technical
triggers must be computable: tech_192,B1,B2,B3,BREAKOUT,BREAKOUT_DOJI,M2_MINUS,
M2_PLUS,SINGLE_NEEDLE,THREE_QUARTER_YIN,BRICK_FANBAO. B1 remains J<=13 and
BBI>white>yellow in the bound original engine. Candidate scope is the full
192/ten-buy-point/valid-source OR union, never a Top100 input or V192-only pool.

Source_fupan/source_stage7/source_research are hit, confirmed_absent or unknown.
The candidate model adds the three one-hot states per source and each hit's
interaction with technical_any. Unknown has its own explicit indicator and is
never conflated with confirmed absence. Counts of pools/topics never prove
independent origins. Baseline uses only the exact 11 technical columns. Both
arms share rows/dates/Top50 and L2 logistic C1,seed194,lbfgs,max_iter1000,tol1e-8,
with training-fold-only StandardScaler. There is no tuning.

At least20 eligible non-exposed target_dates are needed. The first floor(N/2)
dates train; remaining dates form expanding five-date evaluation folds including
a short tail. Training label_available_at must be strictly before the first
evaluation decision. The exposed target dates2026-10-16/19/20/21/22 are excluded
from training, OOF and final refit. Empty but otherwise valid candidate dates
retain50 fixed slots and the actual full-universe truth denominator; missing
prices/truth remain missing coverage.

The paired deltaHit@50 oracle uses non-circular five-evaluated-trading-date
moving blocks, uniform starts0..N-5, ceil(N/5) blocks truncated toN,2000 replicates,
seed194 and percentile2.5/97.5 CI. At least20 OOF dates, mean>=1 and lowerCI>0
are all required for an effect-gate candidate; even this remains DIRECTION_ONLY.

run194.py EXECUTION_CONTRACT.json registers before data reads, validates frozen
input/code identities and writes checkpoints/terminal events to the existing
official registry via registry_bridge.py. Stages: canary, oof, refit, predict.
The first real fold canary is cached with input/code/output SHA and reused in
OOF, never refitted merely to repeat it. Refit follows completed OOF and uses
all eligible non-exposed rows with labels available before frozen refit_asof.
Models are JSON coefficients/preprocessing/config/versions; no pickle.

Models record actual trained_asof separately from historical
training_information_cutoff. Historical OOF scores are explicit retrospective
outputs; future batch prediction requires decision_at strictly after BOTH actual
trained_asof and training_label_available_at_max. No unknown future input means
no future prediction artifact. Final in-sample serialization checks are not OOF.

The run config binds input_manifest/input_manifest_sha256, output_dir,
evaluation_asof and refit_asof. A prediction config also binds model_path and
model_sha256. The manifest binds files.candidates/truth/calendar path+sha256,
eligible_target_dates, technical_features, source_state_columns, semantic_ready,
complete_ten_buy_points, reconstruction mode and all four research safety flags.
Model/test/runtime files and MODEL_CONFIG_V2.json are frozen before each run.
Use thread environment caps2 before imports. Tests use only synthetic fixtures
and report synthetic vs real fit counts separately; register before tests.

DataWriter exclusively owns data194.py/test_data194.py and local inputs/.
ModelWriter owns model/test/run/report/bridge and local outputs outside inputs/.
No services/UI/schedulers, external data collection, BUY or order actions.

## Completed frozen R0 result

Independent actual-run receipt2c2dd17611a086f6e7c31351c2400e63f0f1e70786f5740544d6d9a7864edc40
accepted75 artifact SHA/size identities,31744 saved fold predictions,64 final
JSON score checks and6 timing-gate probes with zero new fits. Actual fits10
(2 first-fold canary+6 remaining folds+2 final refits); first fold was reused.
35 complete target dates gave17 initial training dates and18 OOF dates. Both
arms hit92/900 fixed slots from1800 truth positives; mean paired delta0 and
95% blockCI[0,0], common92/new0/lost0. No improvement was observed. The sample
gate18<20 remains CANNOT_CONFIRM_SAMPLE_SIZE / DIRECTION_ONLY; baseline retained.
Only research-source hits on6dates/38candidate rows were informative in the
complete date set; fupan and Stage7 were unknown throughout. This does not
certify three historical sources, all-A coverage, PIT vintage, sealed or live
performance. No future market prediction was fabricated.

Local artifacts (excluded from GitHub) are under the factor-factory project
research/a_share_v194_20261023/: REAL_RUN_ARTIFACT_MANIFEST_V2.json,
REAL_RUN_INDEPENDENT_REVIEW_PASS.json and runs/v194_r0_v2_01/. The run directory
contains final/baseline_model.json and final/candidate_model.json,
final/train_keys.json, baseline_OOF_TOP50.json, candidate_OOF_TOP50.json,
per-fold train/evaluation predictions, OOF_METRICS.json and REPORT.md.

### Read-only artifact reproduction

Use the existing training Python with PYTHONDONTWRITEBYTECODE=1. This verifies
existing identities without fitting, rewriting outputs or re-auditing producers:

```python
import hashlib, json
from pathlib import Path
D = Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_v194_20261023')
binding = json.loads((D / 'REAL_RUN_ARTIFACT_MANIFEST_V2.json').read_text())
for name, expected in binding['artifacts'].items():
    payload = Path(name).read_bytes()
    assert len(payload) == expected['bytes']
    assert hashlib.sha256(payload).hexdigest() == expected['sha256']
print(json.loads((D / 'runs/v194_r0_v2_01/OOF_RESULT.json').read_text())['status'])
```

### Batch prediction entry

`python run194.py PREDICT_EXECUTION_CONTRACT.json` uses run_stage=predict.
Supply a new independently bound V2 candidates/calendar manifest for a genuine
post-training decision; no future truth is required. Bind model_path to the
saved final/candidate_model.json and model_sha256 to its exact bytes. Use a new
execution_id, output_dir, run_config_path/run_config_sha256 and frozen input,
model and source bindings following runtime_v2/REFIT_CONTRACT.json's registry
shape. The runner registers before loading input, rejects historical decisions
at or before actual trained_asof or training_label_available_at_max, and writes
FUTURE_TOP50.json only when the gate passes. Current D23 unlabelled candidates
are historical and are retained without being passed off as future predictions.

Full training reruns need fresh execution IDs and a new output directory; do
not replay completed IDs or repeat accepted fits just to inspect results.

## Source repair R1 (2026-10-24)

The new repaired dataset and actual run are under the local research directory
`a_share_v194_20261023/repair_r1_20261024/`. Frozen parameters,11technical
features, label basis, Top50 and effect gates are unchanged. The retained model
candidate view grew48618->67878; full raw union68043 retains165technical-unknown
keys. Unknown retained historical labels212 (including old95) cause whole-date
label exclusions;35eligible dates become30,15initial train+15OOF.

The actual comparator is **TECHNICAL11_L2_TOP50**, not raw192 natural selections.
Its15OOF hits are66/750 versus94/750 for V194_SOURCE_L2_TOP50; common49/new45/
lost17, mean paired delta1.8666667, block95%CI[0.0666667,3.3333333].15<20OOF
means CANNOT_CONFIRM_INSUFFICIENT_OOF_DATES: effect gate remainsfalse and no
promotion. Actual8fits=2canary+4remainingOOF+2refits; firstfold reused.
Input independent receiptaf080a93e263ca8e510067ed30674935d2fa7e98d079a9a7483078033c0c80fe
and actual reviewe4d179642c96aaba86ff811ed4bd0ef5083866a5d6bdcc33c6c4e5b577959cba
are persisted locally.19465 saved candidate probabilities and all15Top50 sets
change. Source coefficients are nonzero3/3/9 byfold; early fupan/Stage7 training
remainsunknown, so the overall lift is not a per-source causal attribution.

Three-source hit rows differ by scope(all56/eligible30/OOF15):
fupan569/264/264; Stage7109/49/49; research24542/11259/7883. Separate original
pool membership, raw publication mention and report-subject qualification;
subjectfalse does not become an admission filter. Unbound pools/placeholders
stayunknown; undeclared collector compatibility remainsdistinct. Remaining date
and reason tables are linked in local REPORT.md and SOURCE_GAP_SUMMARY.json.

The current delivery dictionary is `CURRENT_DATA_DICTIONARY_CORRECTED.json`,
pointing to actual new `inputs/DATE_POLICY.json`; its immutable parent and
reference-only correction are in METADATA_REFERENCE_CORRECTION.json. Original
training input and43run artifacts are unchanged. `RUNTIME_INPUT_MANIFEST_V2.json`
is only a schema-name projection of final repairedmanifest e5f57acb6e5555f3a08e8e76387b427bf50d57eb57560f6f80de2dda9594bfcf;
no data/PIT/feature gate is relaxed. Use this manifest and a fresh output/ID for
future authorized reruns; do not replay completed IDs.

`extract_source_effect.py` describes saved fold states/coefficients/predictions
without fit. `daily_top100_report.py` exports the existing outcomeTop100 and
raw-field/L2 membership, never recalculating labels. Canonical local scripts are
in repair_r1_20261024; necessary source-only copies are synchronized byRoot.
Downloadable local derived_daily files include DAILY_TOP100_MEMBERSHIP.csv,
DAILY_MODEL_COUNTS.csv, DAILY_RAW192_NATURAL.csv and bothmodel Top50 CSVs.
The1535natural keys/61hits are **冻结tech_192投影（原公式身份另核）**: no TopN/no
fill and no certified Windows realtime192 identity. This is distinct from both
L2 models. No bound names exist; names are blank. Daily parity receipt
5e2a3a10f05534b7750d2dd812aa71f121c87b63b32c1f64fcdf24d167fe464c verifies these
exports without repeating training. New export/review ceiling4threads does not
change the past8fits'2thread setting.

Current work uses an isolated sklearn module/shared data/official registry;
it has not invoked the existing FactorFactory long-history generation/training
pipeline. A separate read-only long-history authority and192identity preflight
must bind those existing entrypoints before long-history computation. No new
producer, services, UI, scheduler, sealed/live or trading acceptance is implied.
