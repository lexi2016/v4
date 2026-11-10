from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from infrastructure.research_workbench_v192 import project,version
from infrastructure.research_lane_source import ResearchLaneSource

FLAGS=dict(RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)


def fixture():
    manifest={'path':'/numeric','sha256':'a'*64}
    p=dict(data_date='20261109',source_generation='b'*64,source_identity={'input_sha256':'c'*64,'selector_artifact_sha256':'d'*64},manifest=manifest,
        rows=[{'symbol':'301199.SZ','groups':'original|nav_pullback'}],processed_universe=['301199.SZ','301361.SZ'],row_refs={s:{'path':'/'+s,'sha256':'e'*64} for s in ['301199.SZ','301361.SZ']})
    checkpoints={s:dict(symbol=s,data_date='20261109',display_name='stock '+s,groups='original|nav_pullback' if s=='301199.SZ' else '',pending_groups='',statistics={'groups':[{'cases':['HISTORY_MUST_NOT_ESCAPE']}]},evaluation={'secret_large_history':[1]*100}) for s in p['processed_universe']}
    calls=[]
    source=SimpleNamespace(_a_product_reference=lambda r:deepcopy(checkpoints[Path(r['path']).name]),_a_daily_checkpoint_binding=lambda row,product,symbol,date:calls.append(symbol))
    candidates=[dict(ts_code=s,signal_date='20261109',target_date='20261110',selector_version='v1.9.2',multi_head_final_role='B3_CONTINUATION_ENTRY',final_score='100') for s in p['processed_universe']]
    verified=SimpleNamespace(rows=candidates,run=SimpleNamespace(manifest={'provenance':{'panel_sha256':'d'*64},'signal_date':'20261109','trade_date':'20261110','artifact_sha256':'f'*64},verification={'row_count':2,'artifact_sha256':'f'*64,'run_id':'existing-run','manifest_sha256':'1'*64,'receipt_sha256':'2'*64}))
    binding=lambda:(lambda *a,**kw:verified,Path('/existing-shared'),{'path':'/original-reader','sha256':'3'*64})
    return p,source,verified,binding,calls


def test_independent_membership_preserves_four_groups_and_projects_only_needed_fields():
    p,s,v,b,calls=fixture();before=deepcopy(p)
    result=project(s,p,'2026-11-09','2026-11-10',binding_reader=b)
    assert result['status']=='READY' and result['count']==2 and p==before
    assert calls==['301199.SZ','301361.SZ']
    rows={r['symbol']:r for r in result['rows']}
    assert rows['301199.SZ']['group_states']['original']=='TRUE'
    assert all(x=='FALSE' for x in rows['301361.SZ']['group_states'].values())
    assert rows['301361.SZ']['v192_member'] and not rows['301361.SZ']['eligible_candidate']
    assert all(r['history_rates']=={} for r in rows.values())
    assert 'HISTORY_MUST_NOT_ESCAPE' not in json.dumps(result)
    assert 'evaluation' not in json.dumps(result)


@pytest.mark.parametrize('change',['selector','signal_date','target_date','artifact_hash','row_count','market'])
def test_conflicting_date_or_selector_is_explicit_unknown(change):
    p,s,v,b,calls=fixture()
    if change=='selector':v.run.manifest['provenance']['panel_sha256']='0'*64
    elif change=='signal_date':v.rows[0]['signal_date']='20261106'
    elif change=='target_date':v.run.manifest['trade_date']='20261111'
    elif change=='artifact_hash':v.run.verification['artifact_sha256']='0'*64
    elif change=='row_count':v.run.verification['row_count']=3
    else:v.rows[0]['ts_code']='301199.HK'
    result=project(s,p,'2026-11-09','2026-11-10',binding_reader=b)
    assert result['status']=='CANNOT_CONFIRM' and result['rows']==[] and result['count']==0
    assert result['source_date']=='2026-11-09'


def test_empty_verified_source_and_missing_source_are_distinct():
    p,s,v,b,calls=fixture();v.rows=[];v.run.verification['row_count']=0
    assert project(s,p,'2026-11-09','2026-11-10',binding_reader=b)['status']=='READY_EMPTY'
    def missing():raise ValueError('NO_EXISTING_SOURCE')
    result=project(s,p,'2026-11-09','2026-11-10',binding_reader=missing)
    assert result['status']=='CANNOT_CONFIRM' and result['reason']=='NO_EXISTING_SOURCE'


def test_existing_completion_digest_observes_late_v192_source_metadata(tmp_path,monkeypatch):
    monkeypatch.setenv('V4_WORKBENCH_V192_SHARED_ROOT',str(tmp_path))
    before=version('2026-11-10')
    target=tmp_path/'runs/20261110/A_SHARE_V192_PREMARKET_POOL_V3/run1';target.mkdir(parents=True)
    for name in ['manifest.json','receipt.json','artifact.csv']:(target/name).write_text('{}')
    (tmp_path/'latest.json').write_text(json.dumps({'entries':{'20261110/A_SHARE_V192_PREMARKET_POOL_V3':{'run_id':'run1'}}}))
    after=version('2026-11-10')
    assert before!=after and after['status']=='SOURCE_METADATA_PRESENT'
    assert version('2026-11-11')['status']=='NOT_MATERIALIZED'
    (target/'artifact.csv').write_text('new source')
    assert version('2026-11-10')!=after


def test_processed_company_read_is_opt_in_and_preserves_missing_materials(tmp_path):
    p,s,v,b,calls=fixture();p['rows']=[]
    source=object.__new__(ResearchLaneSource);source.read_a_daily_product=lambda *a,**kw:p;source._a_product_root=lambda:tmp_path
    (tmp_path/'index.json').write_text(json.dumps({'latest_date':'20261109','company_materials':{}}))
    with pytest.raises(ValueError,match='PRODUCT_IDENTITY'):
        source.read_a_daily_company_materials('20261109','301361.SZ')
    result=source.read_a_daily_company_materials('20261109','301361.SZ',allow_processed_symbol=True)
    assert result['status']=='NOT_MATERIALIZED' and result['symbol']=='301361.SZ'
    with pytest.raises(ValueError,match='PRODUCT_IDENTITY'):
        source.read_a_daily_company_materials('20261109','000001.SZ',allow_processed_symbol=True)


@pytest.mark.parametrize('all_invalid',[False,True])
def test_invalid_checkpoint_is_quarantined_without_losing_verified_members(all_invalid):
    p,s,v,b,calls=fixture();before=deepcopy(p)
    original=s._a_product_reference
    def detail(ref):
        row=original(ref)
        if all_invalid or row['symbol']=='301199.SZ':
            row['qualification']={'status':'UNKNOWN','reason':'CURRENT_SYMBOL_HISTORY_END_MISMATCH'}
        return row
    def strict(row,*args):
        if row.get('qualification',{}).get('status')=='UNKNOWN':
            raise ValueError('A_DAILY_SYMBOL_DETAIL_SOURCE_IDENTITY_CONFLICT')
    s._a_product_reference=detail;s._a_daily_checkpoint_binding=strict
    result=project(s,p,'2026-11-09','2026-11-10',binding_reader=b)
    assert result['status']=='PARTIAL' and result['source_count']==2
    assert result['valid_count']==result['count']==(0 if all_invalid else 1)
    assert result['pending_count']==result['excluded_count']==(2 if all_invalid else 1)
    assert {r['symbol'] for r in result['rows']}.isdisjoint(r['symbol'] for r in result['excluded_rows'])
    excluded=result['excluded_rows'][0]
    assert excluded==dict(symbol='301199.SZ',status='CANNOT_CONFIRM',
        reason='A_DAILY_SYMBOL_DETAIL_SOURCE_IDENTITY_CONFLICT',
        qualification_reason='CURRENT_SYMBOL_HISTORY_END_MISMATCH',source_checkpoint=p['row_refs']['301199.SZ'])
    assert p==before


@pytest.mark.parametrize('failure',['checkpoint_date','checkpoint_hash','formula_hash','formula_missing','reader_hash'])
def test_row_local_and_global_failures_remain_distinct(failure):
    p,s,v,b,calls=fixture()
    if failure=='checkpoint_date':
        s._a_product_reference=lambda ref:dict(symbol=Path(ref['path']).name,data_date='20261106')
    elif failure=='checkpoint_hash':
        def corrupt(ref):raise ValueError('A_DAILY_PRODUCT_REFERENCE_SHA_CONFLICT')
        s._a_product_reference=corrupt
    elif failure=='reader_hash':
        def bad_reader():raise ValueError('V192_READER_SHA_CONFLICT')
        b=bad_reader
    else:
        def bad_binding(*args):
            if failure=='formula_missing':raise FileNotFoundError('shared config missing')
            raise ValueError('A_DAILY_SYMBOL_DETAIL_FORMULA_CONFIG_SHA_DRIFT')
        s._a_daily_checkpoint_binding=bad_binding
    result=project(s,p,'2026-11-09','2026-11-10',binding_reader=b)
    if failure.startswith('checkpoint'):
        assert result['status']=='PARTIAL' and result['pending_count']==2 and result['source_count']==2
    else:
        assert result['status']=='CANNOT_CONFIRM' and result['rows']==[]
        assert result['source_count'] is None and result['valid_count'] is None
