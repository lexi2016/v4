"""Candidate-only lifecycle binding, source evidence and bounded resume."""
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_daily_product as product
from ops import research_panel_lifecycle as life
from ops import research_panel_qfq as q


def ref(path):
    return {'path':str(path), 'sha256':q.sha(path)}


def test_lifecycle_item_binds_the_reviewed_reader_required_references():
    entry = dict(symbol='920201.BJ', listing_date=20261001, adjustment_events=[], raw_files=[{'path':'/raw'}],
                 listing_binding={'path':'/listing'}, history_metadata={'path':'/history'},
                 row_lineage_receipt={'path':'/lineage'}, adjustment_binding={'path':'/adjustment'})
    item = life._item(entry, 20261030)
    assert item['accepted_evidence'] == [entry[k] for k in
        ('listing_binding','history_metadata','row_lineage_receipt','adjustment_binding')]
    assert item['history_start_date'] == 20261001 and item['history_end_date'] == 20261030


def test_effective_daily_scope_requires_the_shared_reader_exact_sets():
    old={'000001.SZ'}; new={'920201.BJ'}
    snapshot={'original_target_codes':sorted(old),'lifecycle_addition_codes':sorted(new),
              'effective_target_codes':sorted(old|new)}
    helper=SimpleNamespace(_lifecycle_scope=lambda *args:{'old_codes':old,'new_codes':new})
    assert product._verified_lifecycle_scope(helper,snapshot,{}, {},20261030,'a'*64)==sorted(old|new)
    with pytest.raises(ValueError,match='DAILY_LIFECYCLE_EFFECTIVE_SCOPE_CONFLICT'):
        product._verified_lifecycle_scope(helper,{**snapshot,'effective_target_codes':sorted(old)}, {}, {},20261030,'a'*64)
    helper._lifecycle_scope=lambda *args: (_ for _ in ()).throw(ValueError('READER_SOURCE_MISMATCH'))
    with pytest.raises(ValueError,match='READER_SOURCE_MISMATCH'):
        product._verified_lifecycle_scope(helper,snapshot,{}, {},20261030,'a'*64)


def test_typed_end_rebind_compares_original_fields_and_nulls(tmp_path):
    old=tmp_path/'old.parquet';new=tmp_path/'new.parquet'
    schema=pa.schema([pa.field('ts_code',pa.string()),pa.field('trade_date',pa.int32()),pa.field('close',pa.float64())])
    values=pa.Table.from_arrays([pa.array(['002731.SZ']*2),pa.array([20261029,20261030],type=pa.int32()),
                                 pa.array([None,float('nan')],type=pa.float64())],schema=schema)
    pq.write_table(values,old);pq.write_table(values.append_column('kb_b1',pa.array([None,False])),new)
    assert product._lifecycle_old_stock_exact(old,new,'002731.SZ')==2
    changed=values.set_column(2,schema.field('close'),pa.array([float('nan'),float('nan')],type=pa.float64()))
    pq.write_table(changed,new)
    with pytest.raises(ValueError,match='TYPED_END_LIFECYCLE_OLD_NULL_CHANGED:close'):
        product._lifecycle_old_stock_exact(old,new,'002731.SZ')


def test_two_stock_typed_facts_are_explicitly_scoped_and_sha_bound(tmp_path):
    fact=tmp_path/'fact.json'
    fact.write_text(json.dumps(dict(schema='a_share_exact_two_typed_metadata_v1',status='PREPARED_NOT_ADMITTED',
        target_date=20261030,stocks={'301314.SZ':{},'301468.SZ':{}},historical_PIT=False,**q.FLAGS)))
    context=SimpleNamespace(target=20261030)
    with pytest.raises(ValueError,match='TYPED_TWO_FACT_SCOPE_CONFLICT'):
        product._lifecycle_two_exact_typed_end(context,'000001.SZ',{},ref(fact))
    with pytest.raises(ValueError,match='DAILY_SOURCE_PIN_DRIFT'):
        product._lifecycle_two_exact_typed_end(context,'301314.SZ',{},dict(path=str(fact),sha256='f'*64))


def test_missing_typed_fact_does_not_promote_original_unknown():
    original={'status':'UNKNOWN','reason':'CURRENT_SYMBOL_HISTORY_END_MISMATCH'}
    context=object.__new__(product.SourceContext)
    context.target=20261030;context.helper=SimpleNamespace(verify_symbol_admission=lambda *args:original)
    context.footer={};context.receipt={};context.quarantine={};context.generation='a'*64
    context.quarantine_ref={'path':'/unused'};context.snapshot={'lifecycle_additions':{'path':'/unread'},'symbols':{'301314.SZ':{}}}
    context.config={}
    assert context.qualify('301314.SZ')==original


def test_lifecycle_resolution_checks_both_actual_role_keys(tmp_path,monkeypatch):
    codes=['920201.BJ','301686.SZ']; target=20261030; generation='a'*64
    additions={'path':'/descriptor','sha256':'b'*64}
    entries={code:dict(symbol=code,dates=[20261029,20261030],listing_date=20261029,
                       raw_files=[{'path':'/raw/'+code}],row_lineage_receipt={'path':'/lineage/'+code}) for code in codes}
    snapshot={'lifecycle_additions':additions,'symbols':{code:{'events':[]} for code in codes}}
    metadata={q.META_KEY:json.dumps(dict(generation_id=generation,input_sha256=q.canonical_sha(snapshot),
                                      asof_date=target,lifecycle_additions=additions)).encode()}
    oldrefs={};newrefs={}
    for role in ('selector','backtest'):
        old=tmp_path/(role+'-old.parquet');new=tmp_path/(role+'-new.parquet')
        pq.write_table(pa.table({'ts_code':['000001.SZ'],'trade_date':[20261030]}),old)
        pq.write_table(pa.table({'ts_code':[c for c in codes for _ in range(2)],
                                 'trade_date':[20261029,20261030]*2}).replace_schema_metadata(metadata),new)
        oldrefs[role]=ref(old);newrefs[role]=ref(new)
    reader_path=tmp_path/'reader.py';reader_path.write_text('# independently pinned reader placeholder\n')
    def date_map(path,wanted):
        table=pq.read_table(path,columns=['ts_code','trade_date']);out={code:[] for code in wanted}
        for code,day in zip(table['ts_code'].to_pylist(),table['trade_date'].to_pylist()):
            if code in out:out[code].append(day)
        return out
    monkeypatch.setattr(life,'_reader',lambda path,digest:SimpleNamespace(_lifecycle_panel_dates_map=date_map))
    descriptor={'baseline_roles':oldrefs,'baseline_snapshot':{'path':'/baseline'},
                'original_sync_receipt':{'path':'/sync'},'source_descriptor':{'path':'/source'},
                'symbols':{c:{'source_entry_sha256':q.canonical_sha(entries[c])} for c in codes}}
    verified={'descriptor':descriptor,'descriptor_ref':additions,'source':{'symbols':entries},'reader_ref':ref(reader_path)}
    dest=tmp_path/'resolution.json'
    result=life.write_pair_resolution(snapshot,verified,target,generation,newrefs,dest)
    value=json.loads(dest.read_text())
    assert result==ref(dest) and set(value['codes'])==set(codes)
    assert value['codes'][codes[0]]['roles']=={'selector':'PASS','backtest':'PASS'}
    assert life.write_pair_resolution(snapshot,verified,target,generation,newrefs,dest)==result
    bad=tmp_path/'bad.parquet'
    pq.write_table(pa.table({'ts_code':[codes[0]],'trade_date':[20261030]}).replace_schema_metadata(metadata),bad)
    with pytest.raises(q.QfqGateError,match='LIFECYCLE_RESOLUTION_PANEL_KEYS:backtest'):
        life.write_pair_resolution(snapshot,verified,target,generation,{**newrefs,'backtest':ref(bad)},tmp_path/'bad.json')


def test_bounded_existing_panel_batch_resumes_without_recomputing(tmp_path,monkeypatch):
    by_bucket={}
    for i in range(1,100):
        code=f'{i:06d}.SZ';bucket=q._bucket(code)
        by_bucket.setdefault(bucket,[]).append(code)
    bucket,codes=next((b,v[:2]) for b,v in by_bucket.items() if len(v)>=2)
    source=pd.DataFrame([dict(ts_code=c,trade_date=20261030,open=1.,high=1.,low=1.,close=1.,
                              vol=1.,pre_close=1.,pct_chg=0.,ma60=1.,zge_yellow_line=1.,
                              user_v1_sell_signal_daily=0) for c in codes])
    spools={}
    for role,frame in (('selector',source.rename(columns={'vol':'volume'})),('backtest',source)):
        path=tmp_path/(role+'.parquet');pq.write_table(pa.Table.from_pandas(frame,preserve_index=False),path)
        spools[role]={bucket:path}
    parts=tmp_path/'parts';parts.mkdir();run=tmp_path/'run';run.mkdir()
    contract=Path(q.__file__).resolve().parents[1]/'contracts/a_share_kb_full_research_v1.json'
    identity={'research_scope':'ADMITTED_A_SHARE','full_research_contract_sha256':q.sha(contract)}
    snapshot={'symbols':{c:{'history_start_date':20261030} for c in codes}}
    produced=[]
    def seed(code,source,item,start,target,identity,baseline,parts_root,driver,generation):
        file=Path(parts_root)/(code+'.parquet');receipt=Path(parts_root)/(code+'.receipt.json')
        if not file.exists():file.write_text(code);receipt.write_text('{}');produced.append(code)
        return code
    monkeypatch.setattr(q,'_kb_seed_checkpoint',seed)
    args=(spools,snapshot,20261030,identity,{'selector':'1'*64,'backtest':'2'*64},parts,
          None,None,None,1,'thread',run,'c'*64)
    first=q._kb_seed_checkpoints(*args,max_new=1)
    assert first['status']=='PARTIAL_CHECKPOINT_BATCH' and first['new_checkpoints_written']==1 and len(produced)==1
    second=q._kb_seed_checkpoints(*args,max_new=1)
    assert second['status']=='COMPLETE' and second['new_checkpoints_written']==1 and len(produced)==2
    third=q._kb_seed_checkpoints(*args,max_new=1)
    assert third['status']=='COMPLETE' and third['new_checkpoints_written']==0 and len(produced)==2
    (parts/(produced[0]+'.receipt.json')).unlink()
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_INCOMPLETE_CHECKPOINT'):
        q._kb_seed_checkpoints(*args,max_new=1)


def test_inflight_batch_preserves_every_failure_before_stopping(tmp_path,monkeypatch):
    by_bucket={}
    for i in range(1,100):
        code=f'{i:06d}.SZ';by_bucket.setdefault(q._bucket(code),[]).append(code)
    bucket,codes=next((b,v[:2]) for b,v in by_bucket.items() if len(v)>=2)
    source=pd.DataFrame([dict(ts_code=c,trade_date=20261030,open=1.,high=1.,low=1.,close=1.,
                              vol=1.,pre_close=1.,pct_chg=0.,ma60=1.,zge_yellow_line=1.,
                              user_v1_sell_signal_daily=0) for c in codes])
    spools={}
    for role,frame in (('selector',source.rename(columns={'vol':'volume'})),('backtest',source)):
        path=tmp_path/(role+'.parquet');pq.write_table(pa.Table.from_pandas(frame,preserve_index=False),path);spools[role]={bucket:path}
    parts=tmp_path/'parts';parts.mkdir();run=tmp_path/'run';run.mkdir()
    contract=Path(q.__file__).resolve().parents[1]/'contracts/a_share_kb_full_research_v1.json'
    identity={'research_scope':'ADMITTED_A_SHARE','full_research_contract_sha256':q.sha(contract)}
    def fail(code,*args):raise q.QfqGateError('REAL_SOURCE_FAILURE:'+code)
    monkeypatch.setattr(q,'_kb_seed_checkpoint',fail)
    with pytest.raises(q.QfqGateError,match='REAL_SOURCE_FAILURE'):
        q._kb_seed_checkpoints(spools,{'symbols':{c:{'history_start_date':20261030} for c in codes}},
            20261030,identity,{'selector':'1'*64,'backtest':'2'*64},parts,None,None,None,2,'thread',run,'c'*64,max_new=2)
    files=list((run/'failures').glob('*.json'))
    assert len(files)==2 and {json.loads(p.read_text())['symbol'] for p in files}==set(codes)


def test_original_spools_are_pinned_to_owner_and_every_bucket(tmp_path):
    owner=ref(Path(q.__file__).resolve());baseline={'selector':'1'*64,'backtest':'2'*64}
    def save(name,value):
        path=tmp_path/name;path.write_text(json.dumps(value,sort_keys=True));return ref(path)
    inputs=save('inputs.json',{'qfq_source':owner})
    run=save('run.json',{'schema':'v4.full_owner_lifecycle_bounded_run.v1','status':'FAIL','stage':'OWNER_RUN'})
    roles={};buckets={}
    for role in ('selector','backtest'):
        bucket=tmp_path/(role+'.parquet');bucket.write_bytes(('same original rows '+role).encode());buckets[role]=bucket
        roles[role]=save(role+'.receipt.json',{'source_sha256':baseline[role],'row_copy':'ARROW_V1',
                                               'files':{'0':ref(bucket)}})
    descriptor=save('descriptor.json',dict(schema='a_share_original_spool_reuse_v1',status='OWNER_PRODUCED_ARROW_BUCKETS',
        baseline_panel_sha256=baseline,owner_source=owner,owner_inputs=inputs,owner_run_receipt=run,roles=roles,**q.FLAGS))
    binding=q._bound_full_research_spools(descriptor,baseline)
    assert binding['roles']['selector'][0]==buckets['selector']
    q._check_full_research_spool_stamps(binding)
    buckets['selector'].write_bytes(b'changed')
    with pytest.raises(q.QfqGateError,match='FULL_RESEARCH_SPOOL_CHANGED_DURING_BUILD'):
        q._check_full_research_spool_stamps(binding)
    with pytest.raises(q.QfqGateError,match='SOURCE_BINDING_FAILED'):
        q._bound_full_research_spools(descriptor,baseline)
