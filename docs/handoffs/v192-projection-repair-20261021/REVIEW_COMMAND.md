# Independent synthetic review

Run once. This invokes all22 exact frozen test bodies and parameter cases directly, replacing only the pytest session receipt-writing fixture with the outer registry/SHA/resource assertions and stdout. Test functions and source remain byte-identical. No production files, market inputs, cache, pyc or receipts are written.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 OPENBLAS_NUM_THREADS=4 OMP_NUM_THREADS=4 /Users/lexi/Desktop/学习/v4_app/.venv/bin/python - <<'PY_REVIEW'
import hashlib, importlib.util, json, resource, sys, time
from pathlib import Path
import numpy as np
import pytest
started=time.monotonic()
batch=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_v192_signal_pool_return_stability_v1/batches/v192_logic_input_diagnostic_20261020')
worktree=Path('/Users/lexi/.codex/worktrees/v192-projection-repair-20261021/v4_app')
contract=json.loads((batch/'FIX_CONTRACT.json').read_text())
review=json.loads((batch/'FIX_REVIEW_CONTRACT.json').read_text())
events=[json.loads(line) for line in (batch.parents[3]/'contracts/EXPERIMENT_REGISTRY.jsonl').read_text().splitlines() if line.strip()]
matching=[e for e in events if e['execution_id']==review['execution_id']]
assert len(matching)==1 and matching[0]['event_type']=='RUN_STARTED'
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()
assert matching[0]['contract_sha256']==sha(batch/'FIX_REVIEW_CONTRACT.json')
assert review['contract_sha256']==sha(batch/'FIX_CONTRACT.json')
assert matching[0]['code_sha256']==contract['code_sha256']
testpath=worktree/'tests/test_v192_increment_projection.py'
assert sha(testpath)==contract['test_sha256']
spec=importlib.util.spec_from_file_location('independent_projection_tests',testpath)
t=importlib.util.module_from_spec(spec);sys.modules[spec.name]=t;spec.loader.exec_module(t)
assert sha(t.PAYLOAD)==contract['code_sha256'] and sha(t.ORIGINAL)==contract['origin_sha256'] and sha(t.CANONICAL)==contract['canonical_sha256']
def modules():
    canonical=t.load(t.CANONICAL,'review_projection_canonical')
    repaired=t.load(t.PAYLOAD,'review_projection_repaired')
    repaired._CANONICAL_FORMULA_MODULE=canonical;repaired.CANONICAL_FORMULA_PATH=t.CANONICAL
    return repaired,canonical
passed=0
t.test_canonical_projection_canary(modules());passed+=1
t.test_full_partition_parity_and_only_target_fields_changed(modules());passed+=1
for field in t.REQUIRED:
    with pytest.MonkeyPatch.context() as mp:
        t.test_missing_required_projection_fails_closed(modules(),mp,field)
    passed+=1
for field,value in [('kdj_d',np.nan),('ref_score_close_up',np.inf),('brick_original_b1',np.nan)]:
    with pytest.MonkeyPatch.context() as mp:
        t.test_nonfinite_required_projection_fails_closed(modules(),mp,field,value)
    passed+=1
assert passed==22
wall=time.monotonic()-started;peak=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
assert wall<=60 and peak<=2147483648
print(json.dumps({'status':'INDEPENDENT_SYNTHETIC_22_FROZEN_ASSERTIONS_PASS','passed':passed,'wall_seconds':wall,'peak_rss_bytes':peak,'market_rows_read':0,'file_writes':0,'formal_data_writes':0,'pointer_writes':0,'network_calls':0,'model_fit_predict_calls':0,'labels_truth_read':False},sort_keys=True))
PY_REVIEW
```
