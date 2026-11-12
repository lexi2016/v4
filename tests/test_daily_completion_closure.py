import copy
import gzip
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as physical
import pytest

from infrastructure.research_workbench_quote_reference import SourceCloseReferences
from ops import bootstrap_stock_event_history as history
from ops import research_panel_chart_blocks as blocks
from ops import research_panel_daily_product as owner
from ops import research_panel_logical as logical
from ops import research_panel_top200 as daily

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
GEN, INPUT, DAY = 'a'*64, 'b'*64, '20261111'
BASIS = dict(price_basis='QFQ_ASOF', amount_basis='RAW_TURNOVER', volume_basis='SOURCE_SHARES')


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return ref(path)


def ref(path):
    return dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def product_fixture(tmp_path, *, modern=True, overlay=False, repeat_metadata=False):
    root=tmp_path/'run';root.mkdir()
    snapshot=tmp_path/'snapshots'/'immutable.json' if modern else root/'snapshot.json'
    snapshot_ref=write(snapshot,dict(asof_date=int(DAY)))
    generation_meta=write(root/'generation.json',{'generation_id':GEN})
    contract=dict(generation_id=GEN,input_sha256=INPUT,asof_date=int(DAY),snapshot_file_sha256=snapshot_ref['sha256'],market_basis={'A':BASIS},generation_manifest_path=generation_meta['path'])
    symbols=['000001.SZ','600000.SH','920001.BJ']
    table=pa.table(dict(ts_code=symbols,trade_date=[DAY]*3,close=[10.,20.,30.],pct_chg=[1.,-2.,0.],amount=[1000.,2000.,3000.]))
    table=table.replace_schema_metadata({b'a_share_qfq_contract_v1':json.dumps(contract).encode()})
    selector=root/'selector.parquet'
    if overlay:
        base=root/'base.parquet';physical.write_table(table,base)
        descriptors=[logical.descriptor(base,key_rows={s:[0]for s in symbols})]
        if repeat_metadata:
            second=root/'second.parquet';physical.write_table(table,second)
            repeated=logical.descriptor(second,key_rows={s:[0]for s in symbols})
            repeated['metadata_refs']*=3
            descriptors.append(repeated)
        selector.write_bytes(logical.anchor_bytes(table.schema,descriptors,rows=3))
    else:physical.write_table(table,selector)
    selector_sha=ref(selector)['sha256']
    identity=dict(generation=GEN,input_sha256=INPUT,asof=int(DAY),snapshot=snapshot_ref,selector_artifact_sha256=selector_sha,basis=BASIS)
    stage=dict(status='READY',selector_pointer_ready=True,generation_id=GEN,input_sha256=INPUT,target_date=int(DAY),snapshot_file_sha256=snapshot_ref['sha256'],candidate_sha256={'selector':selector_sha},selector=str(selector),candidates={'selector':str(selector)},market_basis={'A':BASIS},**FLAGS)
    stage_ref=write(root/'stage_status.json',stage)
    receipt=dict(generation_id=GEN,input_sha256=INPUT,target_date=int(DAY),adjustment_snapshot=snapshot_ref,candidate_sha256={'selector':selector_sha},**FLAGS)
    receipt_ref=write(root/'candidate_receipt.json',receipt)
    row=dict(symbol=symbols[0],data_date=DAY,qualification=dict(status='CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH',source_generation=GEN,target_date=DAY,snapshot_path=str(snapshot),snapshot_sha256=snapshot_ref['sha256'],producer_receipt_path=receipt_ref['path'],producer_receipt_sha256=receipt_ref['sha256']),**FLAGS)
    row_ref=write(root/'row.json',row)
    product=dict(data_date=DAY,source_generation=GEN,source_identity=identity,rows=[dict(symbol=s)for s in symbols],row_refs={symbols[0]:row_ref},manifest={'sha256':'c'*64})
    return product,dict(root=root,stage=stage_ref,snapshot=snapshot_ref,receipt=receipt_ref,row=row_ref,selector=selector)


@pytest.mark.parametrize('modern,overlay',[(False,False),(True,False),(True,True)])
def test_close_reference_keeps_legacy_and_reads_immutable_logical_source(tmp_path,modern,overlay):
    product,paths=product_fixture(tmp_path,modern=modern,overlay=overlay)
    result=SourceCloseReferences().read(product)
    assert result['status']=='BOUND_SOURCE_CLOSE' and result['available_count']==3
    assert result['quote_role']=='SOURCE_DATE_CLOSE_REFERENCE' and result['source_date']=='2026-11-11'
    assert result['source_asof'] is None and result['source_asof_precision']=='DATE_ONLY'
    assert result['rows']['600000.SH']==dict(symbol='600000.SH',price=20.,change_percent_source=-2.,amount_source=2000.)
    assert result['rows']['920001.BJ']['price']==30.
    assert not (paths['root']/'observations').exists()
    assert SourceCloseReferences().read(product)==result


@pytest.mark.parametrize('kind',['row_sha','receipt_sha','snapshot_identity','stage_generation','selector_bytes','logical_block'])
def test_close_reference_still_rejects_real_source_drift(tmp_path,kind):
    product,paths=product_fixture(tmp_path,overlay=kind=='logical_block')
    if kind=='row_sha':Path(paths['row']['path']).write_text('{}')
    elif kind=='receipt_sha':Path(paths['receipt']['path']).write_text('{}')
    elif kind=='snapshot_identity':product['source_identity']['snapshot']['sha256']='f'*64
    elif kind=='stage_generation':
        p=Path(paths['stage']['path']);v=json.loads(p.read_text());v['generation_id']='f'*64;p.write_text(json.dumps(v))
    elif kind=='selector_bytes':paths['selector'].write_bytes(paths['selector'].read_bytes()+b'bad')
    else:
        p=paths['root']/'base.parquet';p.write_bytes(p.read_bytes()+b'bad')
    with pytest.raises((ValueError,KeyError)):
        SourceCloseReferences().read(product)


def test_close_reference_does_not_relabel_another_day_or_duplicate_scope(tmp_path):
    product,_=product_fixture(tmp_path)
    product['data_date']='20261112'
    with pytest.raises(ValueError,match='PRODUCT_IDENTITY'):SourceCloseReferences().read(product)
    product['data_date']=DAY;product['rows'].append(product['rows'][0])
    with pytest.raises(ValueError,match='SCOPE_INVALID'):SourceCloseReferences().read(product)


def test_unknown_model_admission_does_not_hide_another_valid_source_witness(tmp_path):
    product,paths=product_fixture(tmp_path)
    first=json.loads(Path(paths['row']['path']).read_text())
    good=copy.deepcopy(first);good['symbol']='600000.SH'
    product['row_refs']['600000.SH']=write(paths['root']/'good_row.json',good)
    first['qualification']={'status':'UNKNOWN','reason':'HISTORY_END_METADATA_MISSING'}
    product['row_refs']['000001.SZ']=write(Path(paths['row']['path']),first)
    value=SourceCloseReferences().read(product)
    assert value['available_count']==3 and value['rows']['600000.SH']['price']==20.


def chart_fixture(tmp_path):
    config={'sha256':'d'*64};identity=dict(generation=GEN);inventory={'assignments':[{'name':'x'}],'drawings':[]}
    def block(path,dates,values,previous=()):
        result=dict(formula_sha256='e'*64,rows=[dict(trade_date=d,values={'x':v},drawings=[])for d,v in zip(dates,values)])
        value=dict(storage_schema=blocks.VERSION,symbol='000001.SZ',data_date=DAY,identity=identity,config=config,bar_dates=[20261110,20261111],inventory=inventory,formula_result=result,history_blocks=list(previous))
        path.write_bytes(gzip.compress(blocks.canonical(value),mtime=0));return ref(path)
    old=block(tmp_path/'old.json.gz',[20261110],[1])
    current=block(tmp_path/'current.json.gz',[20261111],[2],[old])
    spec=dict(storage_schema=blocks.VERSION,symbol='000001.SZ',data_date=DAY,source_identity=identity,lineage={'config':config},source_cache=current)
    spec_ref=write(tmp_path/'projection.spec.json',spec)
    payload=gzip.compress(blocks.canonical(blocks.projection_payload(spec)),mtime=0)
    virtual=dict(path=spec_ref['path'],spec=spec_ref,sha256=hashlib.sha256(payload).hexdigest(),bytes=len(payload),encoding='gzip',virtual=True)
    return current,virtual


def test_history_loader_reads_original_virtual_and_retained_blocks(tmp_path):
    current,virtual=chart_fixture(tmp_path)
    assert virtual['sha256']!=virtual['spec']['sha256']
    assert [r['values']['x']for r in history.load(current)['formula_result']['rows']]==[1,2]
    assert history.load(virtual)['formula_result']==history.load(current)['formula_result']
    plain=write(tmp_path/'legacy.json',{'legacy':True})
    assert history.load(plain)=={'legacy':True}
    assert history.load(write(tmp_path/'legacy_list.json',[1,2]))==[1,2]


@pytest.mark.parametrize('kind',['virtual_sha','spec_bytes','retained_bytes','relative_path','different_spec_path'])
def test_history_loader_does_not_bypass_transport_shas(tmp_path,kind):
    current,virtual=chart_fixture(tmp_path)
    if kind=='virtual_sha':virtual['sha256']='f'*64
    elif kind=='spec_bytes':Path(virtual['spec']['path']).write_text('{}')
    elif kind=='retained_bytes':Path(current['path']).write_bytes(b'corrupt')
    elif kind=='relative_path':virtual['path']='relative.spec.json'
    else:virtual['path']=str(tmp_path/'different.spec.json')
    with pytest.raises(ValueError):history.load(virtual)


def coverage_fixture(tmp_path, *, incomplete=True):
    identity=dict(generation=GEN);config={'sha256':'c'*64};rows=[];refs={}
    for symbol,available,evaluated in [('000001.SZ',10,3 if incomplete else 10),('600000.SH',8,8)]:
        row=dict(symbol=symbol,data_date=DAY,historical_coverage=dict(available_prefix_dates=available,evaluated_count=evaluated,known_full_history=available==evaluated,missing=['HISTORICAL_FULL_CONDITION_BOOTSTRAP']if available!=evaluated else[]),**FLAGS)
        refs[symbol]=write(tmp_path/(symbol+'.json'),row);rows.append(dict(symbol=symbol))
    product=dict(data_date=DAY,source_identity=identity,source_generation=GEN,source_config=config,rows=rows,row_refs=refs,**FLAGS)
    product_ref=write(tmp_path/'product.json',product)
    manifest_ref=write(tmp_path/'manifest.json',dict(data_date=DAY,source_generation=GEN,artifact=product_ref))
    write(tmp_path/'index.json',dict(dates={DAY:manifest_ref}))
    context=SimpleNamespace(target=int(DAY),identity=identity,generation=GEN,config_ref=config,unchanged=lambda:None)
    return context,refs


def test_daily_history_only_reports_real_gaps_without_bootstrap(tmp_path,monkeypatch):
    context,_=coverage_fixture(tmp_path)
    monkeypatch.setattr(daily,'run_incremental_history',lambda *a,**k:pytest.fail('daily must not bootstrap'))
    got=daily.daily_history_coverage(context,tmp_path)
    assert got['status']=='PARTIAL_NEEDS_EXPLICIT_BOOTSTRAP'
    assert got['incomplete_stocks']==1 and got['complete_stocks']==1 and got['missing_label_date_count']==7
    assert got['history_bootstrap_in_daily_path']is False
    assert got['new_label_evaluations']==got['new_return_evaluations']==0


def test_daily_history_reports_complete_without_inventing_missing_values(tmp_path):
    context,refs=coverage_fixture(tmp_path,incomplete=False)
    assert daily.daily_history_coverage(context,tmp_path)['status']=='COMPLETE_NO_HISTORY_GAPS'
    path=Path(refs['000001.SZ']['path']);path.write_text('{}')
    with pytest.raises(ValueError,match='DAILY_SOURCE_PIN_DRIFT'):daily.daily_history_coverage(context,tmp_path)


@pytest.mark.parametrize('history_status',['PARTIAL_NEEDS_EXPLICIT_BOOTSTRAP','CANNOT_CONFIRM'])
def test_daily_current_modules_continue_while_history_remains_partial(tmp_path,monkeypatch,history_status):
    context=SimpleNamespace(target=int(DAY),generation=GEN)
    monkeypatch.setattr(owner,'SourceContext',lambda *a:context)
    monkeypatch.setattr(daily,'bind_completed_source_provenance',lambda *a:{'status':'EXACT_COMPLETED_SOURCE'})
    monkeypatch.setattr(daily,'run_incremental_history',lambda *a,**k:pytest.fail('must not bootstrap'))
    monkeypatch.setattr(daily,'publish_current_history_view',lambda *a,**k:pytest.fail('must not certify incomplete history'))
    if history_status=='CANNOT_CONFIRM':
        def coverage(*a):raise ValueError('OLD_HISTORY_PROOF_UNAVAILABLE')
    else:
        def coverage(*a):return dict(status=history_status,incomplete_stocks=318,missing_label_date_count=947908,history_bootstrap_in_daily_path=False)
    monkeypatch.setattr(daily,'daily_history_coverage',coverage)
    monkeypatch.setattr(daily,'build',lambda *a:({'actual_current_payload':True},{'reused':False}))
    monkeypatch.setattr(daily,'stage',lambda *a:{'original_owner_plan':True})
    monkeypatch.setattr(daily,'record_daily_attempt',lambda root,receipt:daily.save(root/'attempt.json',receipt))
    calls=[]
    def publish(plan):calls.append(('top200',plan));return {'status':'PUBLISHED_CURRENT_TOP200'}
    monkeypatch.setitem(sys.modules,'ops.sync_stock_history_completion',SimpleNamespace(publish=publish))
    def f10(ctx,receipt_ref,root,**kwargs):
        receipt=daily.load(receipt_ref)
        assert receipt['data_date']==DAY and receipt['source_generation']==GEN and all(receipt[k]==v for k,v in FLAGS.items())
        assert receipt['status']=='COMPLETE_DESCRIPTIVE_NONPIT' and receipt['completeness_scope']=='CURRENT_DAY_DERIVATIVES'
        assert receipt['history_status']==history_status and receipt['historical_completion']is False
        calls.append(('f10',receipt_ref));return {'receipt':{'fake_offline_fixture':True}}
    monkeypatch.setitem(sys.modules,'ops.research_panel_f10',SimpleNamespace(complete_f10=f10,publish_f10_completion=lambda *a:{'status':'OFFLINE_FIXTURE'}))
    monkeypatch.delenv('V4_WORKBENCH_STATISTICS_ROOT',raising=False)
    write(tmp_path/'index.json',{})
    write(tmp_path/'a_sync_authority'/'official_daily'/DAY/'input.json',{'offline_source_fixture':True})
    result=daily.complete_daily_derivatives(tmp_path,int(DAY),tmp_path,tmp_path,tmp_path)
    assert result['status']=='COMPLETE_DESCRIPTIVE_NONPIT' and result['historical_completion']is False
    assert result['history']['status']==history_status and [x[0]for x in calls]==['top200','f10']
    if history_status.startswith('PARTIAL'):
        assert result['history']['missing_label_date_count']==947908
    else:assert result['history']['error']=='OLD_HISTORY_PROOF_UNAVAILABLE'
    assert not (tmp_path/'continuations'/DAY/GEN/'history').exists()


def provenance_fixture(tmp_path):
    from ops.research_panel_reader_compat import semantic_reader_identity
    context,_=coverage_fixture(tmp_path)
    actual=tmp_path/'actual_reader.py';actual.write_text('# existing approved after reader\n')
    reader_ref=ref(actual);before=b'# frozen original mathematical reader\n';before_sha=hashlib.sha256(before).hexdigest()
    mathematical=dict(path=str(actual),sha256=before_sha)
    proofs={}
    for name in ['old_app','new_app']:
        directory=tmp_path/name;directory.mkdir();(directory/'before.py').write_bytes(before)
        oracle_ref=write(directory/'oracle.json',dict(status='PASS',before_sha256=before_sha,after_sha256=reader_ref['sha256']))
        proof_ref=write(directory/'proof.json',dict(schema='v4.reader.transport_equivalence.v1',scope='EXACT_ARROW_BLOCK_TRANSPORT_ONLY',config=context.config_ref,
            before_sha256=before_sha,after_sha256=reader_ref['sha256'],historical_reader=mathematical,before_source='before.py',oracle=dict(file='oracle.json',sha256=oracle_ref['sha256'])))
        math,proof=semantic_reader_identity(reader_ref,context.config_ref,proof_path=proof_ref['path']);assert math==mathematical
        proofs[name]=dict(actual_reader=reader_ref,transport_equivalence=proof)
    accepted={**context.identity,'asof':int(DAY),'reader_provenance':proofs['old_app']}
    context.identity={**context.identity,'asof':int(DAY),'reader_provenance':proofs['new_app']}
    context.reader_ref=reader_ref;context.cache_reader_ref=mathematical;context.reader_transport_provenance=proofs['new_app']['transport_equivalence']
    index=json.loads((tmp_path/'index.json').read_text());manifest=json.loads(Path(index['dates'][DAY]['path']).read_text());product=json.loads(Path(manifest['artifact']['path']).read_text());product['source_identity']=accepted
    manifest['artifact']=write(tmp_path/'product.json',product);manifest_ref=write(tmp_path/'manifest.json',manifest);write(tmp_path/'index.json',dict(dates={DAY:manifest_ref}))
    return context,accepted,actual


def test_completed_context_reuses_only_fully_revalidated_original_proof(tmp_path):
    context,accepted,_=provenance_fixture(tmp_path)
    old=copy.deepcopy(context.identity)
    result=daily.bind_completed_source_provenance(context,tmp_path)
    assert result['status']=='REVALIDATED_ORIGINAL_COMPLETED_TRANSPORT_PROOF'
    assert context.identity==accepted and old!=accepted
    assert {k:v for k,v in old.items()if k!='reader_provenance'}=={k:v for k,v in context.identity.items()if k!='reader_provenance'}
    assert daily.bind_completed_source_provenance(context,tmp_path)['status']=='EXACT_COMPLETED_SOURCE'
    assert daily.daily_history_coverage(context,tmp_path)['status']=='PARTIAL_NEEDS_EXPLICIT_BOOTSTRAP'


@pytest.mark.parametrize('kind',['proof_bytes','old_oracle','old_source','reader_bytes','config','core','mathematical_reader','missing_proof'])
def test_completed_context_rejects_real_identity_or_original_proof_drift(tmp_path,kind):
    context,accepted,actual=provenance_fixture(tmp_path)
    proof=accepted['reader_provenance']['transport_equivalence']
    if kind=='proof_bytes':Path(proof['equivalence_proof']['path']).write_text('{}')
    elif kind=='old_oracle':Path(proof['oracle']['path']).write_text('{}')
    elif kind=='old_source':Path(proof['before_source_snapshot']['path']).write_text('changed')
    elif kind=='reader_bytes':actual.write_text('changed')
    elif kind=='config':context.config_ref={'sha256':'f'*64}
    elif kind=='core':context.identity['input_sha256']='f'*64
    elif kind=='mathematical_reader':context.cache_reader_ref={**context.cache_reader_ref,'sha256':'f'*64}
    else:Path(proof['equivalence_proof']['path']).unlink()
    before=copy.deepcopy(context.identity)
    with pytest.raises((ValueError,FileNotFoundError)):daily.bind_completed_source_provenance(context,tmp_path)
    assert context.identity==before


@pytest.mark.parametrize('target,operation',[('block','change'),('block','remove'),('metadata','change'),('metadata','remove')])
def test_warm_logical_close_cache_rejects_dependency_drift_like_cold_read(tmp_path,target,operation):
    product,paths=product_fixture(tmp_path,overlay=True)
    reader=SourceCloseReferences();assert reader.read(product)['available_count']==3
    dependency=paths['root']/('base.parquet'if target=='block'else'generation.json')
    if operation=='remove':dependency.unlink()
    else:dependency.write_bytes(dependency.read_bytes()+b'changed')
    for current in [reader,SourceCloseReferences()]:
        with pytest.raises((ValueError,FileNotFoundError)):current.read(product)


def test_warm_logical_cache_deduplicates_metadata_and_does_not_reread_rows(tmp_path,monkeypatch):
    import infrastructure.research_workbench_quote_reference as quotes
    product,paths=product_fixture(tmp_path,overlay=True,repeat_metadata=True)
    metadata=paths['root']/'generation.json';counts={'metadata_hash':0,'table_reads':0}
    original_sha=quotes._sha;original_table=logical.parquet.read_table
    def checked_sha(path):
        if Path(path)==metadata:counts['metadata_hash']+=1
        return original_sha(path)
    def table(*a,**k):counts['table_reads']+=1;return original_table(*a,**k)
    monkeypatch.setattr(quotes,'_sha',checked_sha);monkeypatch.setattr(logical.parquet,'read_table',table)
    reader=SourceCloseReferences();first=reader.read(product)
    assert counts=={'metadata_hash':1,'table_reads':1}
    assert reader.read(product)==reader.read(product)==first
    assert counts=={'metadata_hash':1,'table_reads':1}
    cached=next(iter(reader._cache.values()));assert not cached[1][0]._files


def test_physical_warm_close_cache_keeps_existing_no_table_reread(tmp_path,monkeypatch):
    product,_=product_fixture(tmp_path)
    reader=SourceCloseReferences();first=reader.read(product)
    monkeypatch.setattr(logical.parquet,'read_table',lambda *a,**k:pytest.fail('physical cache hit reread table'))
    assert reader.read(product)==first
