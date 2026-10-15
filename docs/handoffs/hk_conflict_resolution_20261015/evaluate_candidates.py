"""Read-only candidate canaries, dependency impact and exact code identity."""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import time
from types import SimpleNamespace
import urllib.request
import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

H=Path(__file__).resolve().parent
PUB=json.loads((H/'PUBLICATION_RECEIPT.json').read_text())
OWNER=Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/workspace/v3_shared_data/.runtime/data/assets/hk_0_2')
os.environ['V4_HK_HISTORY_RESOLUTION_POINTER']=str(H/'history_resolution_latest.staged.json')
import v4.hk_research_history as adapter
import v4.manager_workbench.api as api
from upstreams.v3_shared_data.shared_data import hk_history_resolution as resolver
from upstreams.v3_shared_data.shared_data import hk_0_2 as scorer

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(name,body):(H/name).write_text(json.dumps(body,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')

identities=[]
for name,module,relative in [('adapter',adapter,'v4/hk_research_history.py'),('api',api,'v4/manager_workbench/api.py'),
        ('resolver',resolver,'upstreams/v3_shared_data/shared_data/hk_history_resolution.py'),('scorer',scorer,'upstreams/v3_shared_data/shared_data/hk_0_2.py')]:
    expected=Path(PUB['api']['app_root'])/relative
    assert Path(module.__file__)==expected,(module.__file__,expected)
    identities.append(dict(module=name,path=str(expected),sha256=sha(expected)))
resolver_sha=sha(resolver.__file__)
for root,relative in [(Path(PUB['shared']['app_root']),'shared_data/hk_history_resolution.py'),
        (Path(PUB['api']['app_root']),'v3_shared_data/shared_data/hk_history_resolution.py')]:
    assert sha(root/relative)==resolver_sha
policy=resolver.ResolutionPolicy(OWNER)
assert len(policy.decisions)==30341
cm=json.loads((OWNER/policy.manifest['bindings']['C_manifest_relative']).read_text())
frame=pd.read_parquet(OWNER/cm['panel_relative'])
frame['trade_date_compact']=frame['trade_date_compact'].astype(str)
original_codes=set(frame.code_norm)
start=time.monotonic();guarded=resolver.guard_score_frame(frame,policy,'20261014')
proof=guarded.attrs['history_resolution_proof'];holds=guarded.attrs['history_resolution_holds']
target_codes=set(guarded.loc[guarded.trade_date_compact.eq('20261014'),'code_norm'])
assert len(guarded)==len(frame.loc[frame.code_norm.isin(set(guarded.code_norm))])
dependency={}
for name in ['_add_daily_features','_add_proxy_labels','_add_proxy_memory']:
    source=Path(scorer.__file__).read_text();node=next(n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name==name)
    dependency[name]=dict(function_sha256=hashlib.sha256(ast.get_source_segment(source,node).encode()).hexdigest(),first_line=node.lineno)
impact=dict(source_rows=len(frame),source_code_count=len(original_codes),retained_rows=len(guarded),retained_code_count=guarded.code_norm.nunique(),
    excluded_code_count=len(holds),signal_date='20261014',original_signal_code_count=frame.loc[frame.trade_date_compact.eq('20261014'),'code_norm'].nunique(),
    retained_signal_code_count=len(target_codes),elapsed_seconds=round(time.monotonic()-start,3),
    excluded_by_field={field:sum(any(field in hold['fields'] for hold in values) for values in holds.values()) for field in resolver.FIELDS},
    entire_sequence_removed_only_for_dependency_hold=True,original_rows_retained_for_clean_codes=True,
    dependency_proof=dependency,price_amount_observation_count=121,trade_dependency='SIGNAL_DATE_ONLY',
    proxy_label_depends_on_rolling_features=False,proxy_label_fields=['high','close','pre_close','amount'],
    proxy_memory_dates_including_signal=120,preclose_predecessor_included=True,model_fit_performed=False)

# An in-memory ordinary append exercises every original column and key.
future=frame.loc[frame.trade_date_compact.eq('20261014')].copy()
future['trade_date_compact']='20261015'
if 'trade_date' in future:future['trade_date']=pd.Series(['20261015']*len(future),index=future.index,dtype=frame['trade_date'].dtype)
appended=pd.concat([frame,future],ignore_index=True)
append_proof=resolver.verify_append_frames(frame,appended,baseline_max='20261014',B_max='20260911')
future_guarded=resolver.guard_score_frame(appended,policy,'20261015')
append_proof.update(simulation='IN_MEMORY_ALL_COLUMNS_ONLY_NO_PROVIDER_CAPTURE',unchanged_contract_required=True,
    scorer_retained_code_count=int(future_guarded.code_norm.nunique()),scorer_signal_code_count=int(future_guarded.loc[future_guarded.trade_date_compact.eq('20261015'),'code_norm'].nunique()),
    all_readers_accept_compatible_current_C_binding=True,old_HK_cache_proof_rejected_until_recomputed=True,
    actual_future_publication_verified=False)

app=FastAPI();app.include_router(api.create_router(SimpleNamespace(config=SimpleNamespace(shared_root=OWNER.parent.parent))))
canaries=[]
with TestClient(app) as client:
    for date in ['20180102','20230630','20260706','20260722','20260909']:
        summaries={}
        for mode in ['usable','audit']:
            started=time.monotonic();response=client.get('/api/v4/manager-workbench/hk-history',params=dict(symbol='HK.00001',start=date,end=date,mode=mode,limit=1))
            assert response.status_code==200,(date,mode,response.text)
            body=response.json();data=body['data']
            assert body['production_allowed'] is False and body['buy_gate_updated'] is False and body['orders_sent'] is False
            assert data['scoring_allowed'] is False and data['research_only'] is True
            assert '/Users/' not in response.text
            summaries[mode]=dict(http_status=response.status_code,row_count=len(data['rows']),quarantine_count=data['quarantine_count'],
                row_sha256=[row['row_sha256'] for row in data['rows']],elapsed_seconds=round(time.monotonic()-started,3),
                counterpart_preserved=all(row['counterpart'] is not None for row in data['rows']) if mode=='audit' and date!='20180102' else None,
                data_sha256=hashlib.sha256(resolver.canonical(data)).hexdigest())
            if mode=='usable' and date in ['20260706','20260722']:assert len(data['rows'])==0 and data['quarantine_count']==1
            if mode=='usable' and date=='20260909':
                assert data['rows'][0]['field_admission']['trade']=='CONFIRMED_KEEP_C'
            if mode=='audit':assert len(data['rows'])==1
        close=client.get('/api/v4/manager-workbench/hk-history',params=dict(symbol='HK.00001',start=date,end=date,fields='close',limit=1))
        assert close.status_code==200
        summaries['close_only']=dict(row_count=len(close.json()['data']['rows']),quarantine_count=close.json()['data']['quarantine_count'])
        canaries.append(dict(date=date,**summaries))
    invalid=[client.get('/api/v4/manager-workbench/hk-history',params=params).status_code for params in [
        dict(symbol='HK.00001',fields='bad'),dict(symbol='HK.00001',mode='bad'),dict(symbol='bad'),dict(symbol='HK.00001',limit=201)]]
    assert invalid==[422]*4

url='http://127.0.0.1:8873/api/v3/stage-center/selection?date=20261015&stage=STAGE_0940_0945&limit=1'
with urllib.request.urlopen(url,timeout=30) as response:market=json.load(response)['markets']['A'];status=response.status
digest=hashlib.sha256(resolver.canonical(market)).hexdigest()
assert digest=='2d709f625c7dff8d81a3777e2bcf672b00a8156278a01febff5403055928c0fb'
assert market['artifact_id']=='selection-b37a1ee172cd45451d78e35b' and market['run_id']=='run-b37a1ee172cd45451d78e35b'
write('ENFORCEMENT_RECEIPT.json',dict(status='WRITER_VERIFIED_PENDING_INDEPENDENT_REVIEW',runtime_python=platform.python_version(),
    actual_module_identities=identities,source_code_sha256=resolver_sha,decision_count=len(policy.decisions),scorer_impact=impact,
    append_impact=append_proof,api_canaries=canaries,invalid_http_statuses=invalid,
    A_control=dict(http_status=status,sha256=digest,artifact_id=market['artifact_id'],run_id=market['run_id'],status=market['status'],rows_exported=False),
    services_changed=False,active_pointer_installed=False,raw_market_values_exported=False))
print(json.dumps(dict(status='WRITER_VERIFIED',impact=impact,append=append_proof),sort_keys=True))
