"""Read-only frozen-model prediction with the actual HK 3.13 runtime."""
from pathlib import Path
import hashlib
import json
import platform
import time
import shared_data.hk_0_2 as module
import shared_data.hk_history_resolution as resolver
H=Path(__file__).resolve().parent
pub=json.loads((H/'PUBLICATION_RECEIPT.json').read_text())
expected=Path(pub['shared']['app_root'])/'shared_data/hk_0_2.py'
assert Path(module.__file__)==expected
owner=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2')
diagnostics={};started=time.monotonic()
master,master_manifest=module._load_verified_security_master(owner.parent.parent,'20261014')
hold=None
try:
    rows=module.score_frozen_hk_0_2(owner,signal_date='20261014',target_date='20261015',eligible_codes=master,diagnostics=diagnostics)
except module.StoreError as error:
    assert str(error)=='HK_HISTORY_RESOLUTION_PROXY_UNIVERSE_INSUFFICIENT'
    hold=str(error);rows=[]
assert hold is not None or 1<=len(rows)<100
assert all(row['production_allowed'] is False and row['research_only'] is True for row in rows)
assert all(float(rows[i]['score_prob_active'])>=float(rows[i+1]['score_prob_active']) for i in range(len(rows)-1))
receipt=dict(status='HOLD' if hold else 'PARTIAL',reason=hold or 'HK_0_2_TOP100_ROWS_MISSING:'+str(100-len(rows)),
    runtime_python=platform.python_version(),sklearn_version=module._package_version('scikit-learn'),joblib_version=module._package_version('joblib'),
    scorer_module_file=str(expected),scorer_module_sha256=hashlib.sha256(expected.read_bytes()).hexdigest(),
    resolver_module_file=resolver.__file__,resolver_module_sha256=hashlib.sha256(Path(resolver.__file__).read_bytes()).hexdigest(),
    original_master_code_count=len(master),eligible_signal_count=diagnostics.get('signal_row_count'),predicted_row_count=len(rows),
    post_resolution_target_input_count=62,model_prediction_executed=hold is None,
    resolution_excluded_code_count=diagnostics['history_resolution_excluded_code_count'],
    security_master_manifest_sha256=hashlib.sha256(resolver.canonical(master_manifest)).hexdigest(),
    source_model_sha256=module.HK_0_2_MODEL_SHA256,elapsed_seconds=round(time.monotonic()-started,3),
    model_fit_performed=False,publish_called=False,store_write_performed=False,old_cache_reused=False,
    raw_market_values_exported=False,scores_exported=False,production_allowed=False,buy_gate_updated=False,orders_sent=False)
(H/'MODEL_IMPACT_RECEIPT.json').write_text(json.dumps(receipt,sort_keys=True,indent=2)+'\n')
print(json.dumps(receipt,sort_keys=True))
