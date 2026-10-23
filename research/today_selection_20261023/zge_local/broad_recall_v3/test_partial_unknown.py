"""Two incremental OR/unknown cases only; no old suite or market input scan."""
import sys
sys.dont_write_bytecode=True
import hashlib,json,math,os
from pathlib import Path
import numpy as np
import formula_kernel as kernel

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def deny(event,args):
    if event.startswith(('socket.','sqlite3.connect','subprocess.Popen')):raise RuntimeError('OFFLINE_TEST_FORBIDDEN_PROVIDER')
def run(contract_path):
    cp=Path(contract_path);c=json.loads(cp.read_text());sys.addaudithook(deny)
    before={path:sha(path) for path in c['frozen_unchanged_sources']}
    assert before==c['frozen_unchanged_sources'],'SOURCE_IDENTITY_DRIFT'
    old=Path(c['inherited_review_receipt']);assert sha(old)==c['inherited_review_receipt_sha256'],'INHERITED_REVIEW_DRIFT'
    assert json.loads(old.read_text())['review_status']=='CANNOT_CONFIRM_CANARY_PASS'
    results=[]
    for case in c['fixtures']:
        p=Path(case['path']);assert sha(p)==case['sha256'],'FIXTURE_BYTES_DRIFT'
        source_bytes=p.read_bytes();fixture=json.loads(source_bytes);raw={k:np.asarray(v,dtype=float) for k,v in fixture['raw'].items()}
        arrays={k:v.copy() for k,v in raw.items()}
        row=kernel.evaluate_stock(fixture['code'],fixture['dates'],raw)
        states={r['rule_id']:r['status'] for r in row['rules']}
        assert row['candidate']==case['expected_candidate'],(case['id'],row['candidate'],states)
        if case['id']=='KNOWN_BRICK_HIT_PLUS_VOLUME_UNKNOWN':
            assert states['BRICK_FANBAO']=='TRIGGERED',states
            assert states['B2']=='DATA_UNAVAILABLE' and states['BREAKOUT']=='DATA_UNAVAILABLE',states
            assert row['execution_status']=='PARTIAL' and row['candidate']=='YES'
            assert row['hit_rules'] and row['unknown_rules']
        else:
            assert row['candidate']=='UNKNOWN' and row['candidate']!='NO' and not row['hit_rules'] and row['unknown_rules']
        assert p.read_bytes()==source_bytes,'FIXTURE_FILE_MUTATED'
        for key in arrays:assert np.array_equal(raw[key],arrays[key],equal_nan=True),'INPUT_ARRAY_MUTATED:'+key
        results.append(dict(case_id=case['id'],fixture_sha256=case['sha256'],history_rows=len(fixture['dates']),signal_date=fixture['dates'][-1],candidate=row['candidate'],execution_status=row['execution_status'],hit_rules=row['hit_rules'],unknown_rules=row['unknown_rules'],rule_states=states,caller_input_unchanged=True))
    after={path:sha(path) for path in c['frozen_unchanged_sources']};assert after==before,'SOURCE_MUTATED'
    receipt=dict(status='TWO_CASE_INCREMENT_READY_PENDING_INDEPENDENT_REVIEW',cases=results,unchanged_source_hashes=after,inherited_review_sha256=c['inherited_review_receipt_sha256'],old_suite_rerun=False,real_market_rows_read=0,network_calls=0,full_pool_run=False,production_source_changed=False,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
    out=Path(c['output_directory']);out.mkdir(parents=True,exist_ok=True);p=out/'PARTIAL_UNKNOWN_RECEIPT.json';p.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n');print(json.dumps(receipt,ensure_ascii=False));return receipt

if __name__=='__main__':run(sys.argv[1])
