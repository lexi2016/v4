"""New native-tail delta boundaries only; synthetic execution requires START."""
import copy
import json
import hashlib
from pathlib import Path
import struct

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ops import research_panel_qfq as qfq
from ops import research_panel_adjustment_inputs as inputs

W=Path(__file__).resolve().parents[1]
DRIVER=W/'ops/vendor/data_layer_daily_formula_increment_update_v1.py'
FORMULA=W/'ops/vendor/build_canonical_formula_research_panel.py'
BASELINE_CORE=Path('/Users/lexi/Desktop/学习/因子工厂/research/a_share_local_panel_completion_20261024/residual_recovery_r1/original_producer_delta_r1/research_panel_qfq_before.py')


def ref(path):return dict(path=str(path),sha256=qfq.sha(path))
def js(path,value):qfq._json(path,value);return ref(path)
def raw(path,dates,start=10.):
    path.write_bytes(b''.join(struct.pack('<IIIIIfII',d,int(round((start+i/100)*100)),int(round((start+i/100)*100))+10,int(round((start+i/100)*100))-10,int(round((start+i/100)*100)),float(100000+i),10000+i,0) for i,d in enumerate(dates)))
    return ref(path)


@pytest.fixture(scope='module')
def example(tmp_path_factory):
    root=tmp_path_factory.mktemp('tail_delta');data=root/'data';runs=root/'runs';driver=qfq.authorities(DRIVER,FORMULA)[0]
    dates=pd.bdate_range('2025-01-01',periods=280).strftime('%Y%m%d').astype(int).tolist();target=dates[-1]
    changed=['002961.SZ','688110.SH'];active='002612.SZ';inactive='603007.SH';codes=changed+[active,inactive]
    policy=js(root/'policy.json',dict(name=qfq.HISTORY_RESOLUTION,selection_unit='COMPLETE_SOURCE_BAR',price_or_volume_conversion='NONE'))
    review=js(root/'restoration_review.json',dict(verdict='REVIEWED/PASS_ISOLATED_TWO_STOCK_TAIL_RECOVERY_ONLY',synthetic=True))
    source_stocks=[];items={};frames=[];composites={};approved=[]
    for code in codes:
        ds=dates[:-4] if code in changed else dates[:-5] if code==inactive else dates
        archive=raw(root/(code+'.archive.day'),ds)
        native=raw(root/(code+'.native.day'),ds[-20:],start=99.)
        sources=[dict(**archive,name='archive',kind='day_bytes'),dict(**native,name='native',kind='day_bytes')]
        source_stocks.append(dict(code=code,sources=sources))
        item=dict(raw_files=[dict(**archive,source_role='archive'),dict(**native,source_role='native')],history_start_date=ds[0],history_end_date=ds[-1],events=[],event_coverage_complete=True,publish_roles=['selector','backtest'],history_extension=True,raw_resolution=qfq.HISTORY_RESOLUTION)
        items[code]=item
        frame=qfq.rebuild_symbol(code,item,target,driver);frame['name']='dated '+code;frame['field_contract_version']=driver.CONTRACT_PROVENANCE_FIELD_DEFAULTS['field_contract_version'];frames.append(frame)
        if code in changed:
            tail=raw(root/(code+'.tail.day'),dates[-4:],start=12.76)
            composite=root/(code+'.native_composite.day');composite.write_bytes(Path(native['path']).read_bytes()+Path(tail['path']).read_bytes());composites[code]=ref(composite)
            approved.append(dict(code=code,added_dates=dates[-4:],old_keys_lost=0,old_values_changed=0,old_raw32_prefix_unchanged=True,buffer_admitted_as_full_history=False,staged_sha256=hashlib.sha256(Path(archive['path']).read_bytes()+Path(tail['path']).read_bytes()).hexdigest()))
    review=js(root/'restoration_review.json',dict(verdict='REVIEWED/PASS_ISOLATED_TWO_STOCK_TAIL_RECOVERY_ONLY',synthetic=True,reports=approved))
    config=js(root/'source_old.json',dict(source_resolution=qfq.HISTORY_RESOLUTION,stocks=source_stocks))
    retention=dict(source_config=config,source_policy=policy,archive_refs=[],accepted_evidence=[])
    for item in items.values():item.update(source_config=config,accepted_evidence=[])
    old=dict(schema='a_share_qfq_adjustment_input_v1',asof_date=target,coverage_end_date=target,price_basis='QFQ_ASOF',volume_basis='QFQ_EVENT_VOLUME',amount_basis='RAW_TURNOVER',convention='SYNTHETIC_DELTA',revision='old',observed_at='2026-10-24T00:00:00+00:00',source_files=[policy,config],symbols=items,history_extension=None,history_retention_binding=retention,retained_history_codes=[],original_quarantine_eligible={c:dict(original_status='PREVIOUSLY_QUARANTINED_NOW_ACCEPTED') for c in changed},accepted_target_date_floor=1)
    old_ref=js(root/'baseline_snapshot.json',old)
    new_config=copy.deepcopy(json.loads(Path(config['path']).read_text()))
    for stock in new_config['stocks']:
        if stock['code'] in changed:stock['sources'][1]=dict(**composites[stock['code']],name='native',kind='day_bytes')
    new_config_ref=js(root/'source_new.json',new_config)
    new_retention={**retention,'source_config':new_config_ref,'accepted_evidence':[review]}
    new=copy.deepcopy(old);new.update(revision='new',history_retention_binding=new_retention,source_files=old['source_files']+[new_config_ref,review,*composites.values()])
    for code,item in new['symbols'].items():
        item.update(source_config=new_config_ref,accepted_evidence=[review])
        if code in changed:
            item['history_end_date']=target;item['raw_files'][1]=dict(**composites[code],source_role='native')
    field=root/'field.csv';field.write_text('synthetic contract\n')
    identity=qfq.generation_identity(new,DRIVER,FORMULA,field)
    old_identity={**identity,'input_sha256':qfq.canonical_sha(old),'adapter_sha256':qfq.sha(BASELINE_CORE)}
    all_frame=pd.concat(frames,ignore_index=True)
    columns=['ts_code','trade_date','open','high','low','close','vol','volume','amount','pre_close','pct_chg','BBI','J','ma60','zge_white_line','zge_yellow_line','name','bars_since_list','field_contract_version','raw_source_role','raw_source_ref_sha256','raw_source_record_index',*qfq.USER_FORMULA_SIGNAL_FIELDS]
    columns=list(dict.fromkeys(columns + [c for c in (*driver.CONTRACT_REQUIRED_V192_SELECTOR_COLUMNS, *driver.V192_ENTRY_FIELDS, *driver.V192_INTERMEDIATE_FIELDS, *driver.CRITICAL_SELECTOR_FORMULA_COLUMNS) if c in all_frame]))
    baseline=all_frame[columns].copy()
    foreign=baseline.loc[baseline.ts_code.eq(active)].iloc[-2:].copy();foreign.ts_code='00700.HK'
    for name in qfq.USER_FORMULA_SIGNAL_FIELDS:foreign[name]=None
    baseline=pd.concat([baseline,foreign],ignore_index=True)
    # Real excluded sidecars stay outside the accepted rows and unchanged.
    sidecar=root/'excluded.parquet';pq.write_table(pa.table(dict(ts_code=['301139.SZ'],trade_date=[20260831],close=[None])),sidecar)
    pointers={};roles={}
    for role in ('selector','backtest'):
        meta=dict(**old_identity,generation_id='synthetic-baseline',asof_date=target,history_retention_binding=retention)
        table=pa.Table.from_pandas(baseline,preserve_index=False)
        typed=pa.schema([pa.field(f.name,pa.int64(),nullable=True) if f.name=="bars_since_list" else f for f in qfq.user_formula_schema(table.schema)])
        table=table.cast(typed).replace_schema_metadata({qfq.META_KEY:json.dumps(meta).encode()})
        path=root/(role+'.parquet');pq.write_table(table,path);pointer=data/role/'CURRENT.txt';pointer.parent.mkdir(parents=True);pointer.write_text(str(path));pointers[role]=pointer;roles[role]=ref(path)
    delta=dict(schema='qfq_native_tail_delta_v1',asof_date=target,baseline_generation_id='synthetic-baseline',baseline_snapshot=old_ref,baseline_core=ref(BASELINE_CORE),baseline_roles=roles,codes={code:dict(added_dates=dates[-4:],independent_review=review) for code in changed})
    delta_ref=js(root/'delta.json',delta)
    return dict(root=root,data=data,runs=runs,driver=driver,target=target,changed=changed,active=active,inactive=inactive,pointers=pointers,roles=roles,old=old,new=new,retention=retention,identity=identity,delta=delta,delta_ref=delta_ref,field=field,sidecar=sidecar)


def test_original_paired_producer_computes_only_changed_codes_and_preserves_floor(example,monkeypatch):
    e=example;called=[];original=qfq.rebuild_symbol;side_bytes=e['sidecar'].read_bytes();before={r:p.read_bytes() for r,p in e['pointers'].items()}
    def compute(code,*args,**kwargs):
        assert code in e['changed'],'Unchanged-security feature recomputation'
        called.append(code);return original(code,*args,**kwargs)
    monkeypatch.setattr(qfq,'rebuild_symbol',compute);monkeypatch.setattr(inputs,'existing_day_files',lambda _:[])
    qfq._json(qfq.input_path(e['data']),e['new'])
    result=qfq.run_daily_rebuild(driver_path=DRIVER,formula_path=FORMULA,tdx_root=e['root']/'tdx',data_root=e['data'],pointers=e['pointers'],contract_csv=e['field'],return_root=e['runs'],target=e['target'],workers=2,tail_delta=e['delta_ref'])
    assert result['status']=='CANDIDATE_READY' and sorted(called)==e['changed']
    for role,path in result['candidates'].items():
        old=pq.read_table(e['roles'][role]['path']);new=pq.read_table(path)
        assert len(new)==len(old)+8
        for code in (e['active'],e['inactive'],'00700.HK'):
            a=old.filter(pa.compute.equal(old['ts_code'],code));b=new.filter(pa.compute.equal(new['ts_code'],code))
            assert a.to_pandas().equals(b.to_pandas())
        counts=result['counts'][role];assert counts['target_date_symbols']==3
        assert counts['old_key_conservation'] and counts['unchanged_active_rows']==280
        assert counts['unchanged_inactive_rows']==275
        assert e['pointers'][role].read_bytes()==before[role]
    assert e['sidecar'].read_bytes()==side_bytes
    assert result['history_retention_binding']==e['new']['history_retention_binding']
    assert len(list((Path(result['run_dir'])/'symbol_checkpoints').glob('*.parquet')))==2
    assert qfq.computation_kernel_sha(BASELINE_CORE)==qfq.computation_kernel_sha(Path(qfq.__file__))


@pytest.mark.parametrize('mutation,match',[
    ('event','EVENT_OR_THIRD_CODE'),('third_code','EVENT_OR_THIRD_CODE'),('floor','NON_RAW_SNAPSHOT'),('membership','ASOF_OR_MEMBERSHIP'),('source_policy','SOURCE_POLICY'),
])
def test_delta_rejects_non_tail_changes_before_build(example,mutation,match):
    e=example;s=copy.deepcopy(e['new'])
    if mutation=='event':s['symbols'][e['changed'][0]]['events']=[dict(ex_date=e['target'],a=1.,b=-1.,volume_a=1.)]
    if mutation=='third_code':s['symbols'][e['active']]['history_start_date']+=1
    if mutation=='floor':s['accepted_target_date_floor']=0
    if mutation=='membership':s['symbols'].pop(e['active'])
    if mutation=='source_policy':s['history_retention_binding']['archive_refs']=[{}]
    with pytest.raises(qfq.QfqGateError,match=match):qfq.tail_delta_binding(e['delta_ref'],snapshot=s,pointers=e['pointers'],identity=e['identity'],target=e['target'],retained_history=e['retention'])


def test_native_composite_rejects_changed_old_bytes_or_wrong_tail(tmp_path):
    old=raw(tmp_path/'old.day',[20261019]);new=raw(tmp_path/'new.day',[20261019,20261020])
    qfq._native_tail_extension(dict(**old,name='native',kind='day_bytes'),dict(**new,name='native',kind='day_bytes'),[20261020],'002961.SZ')
    with pytest.raises(qfq.QfqGateError,match='NEW_KEYS'):
        qfq._native_tail_extension(dict(**old,name='native',kind='day_bytes'),dict(**new,name='native',kind='day_bytes'),[20261021],'002961.SZ')
    bad=raw(tmp_path/'bad.day',[20261019,20261020],start=99.)
    with pytest.raises(qfq.QfqGateError,match='OLD_NATIVE_BYTES'):
        qfq._native_tail_extension(dict(**old,name='native',kind='day_bytes'),dict(**bad,name='native',kind='day_bytes'),[20261020],'002961.SZ')


def test_prefix_local_values_cannot_change_but_asof_changes_are_enumerated():
    old=pa.table(dict(trade_date=[20261019],close=[10.],user_v1_B1=[0],user_v1_sell_signal_display_asof=[1]))
    new=pa.table(dict(trade_date=[20261019,20261020],close=[10.,11.],user_v1_B1=[0,1],user_v1_sell_signal_display_asof=[0,1]))
    changes=qfq.tail_delta_prefix(old,new,[20261020],'002961.SZ');assert changes[0]['reason']=='ORIGINAL_ASOF_DISPLAY'
    bad=new.set_column(2,'user_v1_B1',pa.array([1,1]))
    with pytest.raises(qfq.QfqGateError,match='PREFIX_VALUE_CHANGED'):qfq.tail_delta_prefix(old,bad,[20261020],'002961.SZ')


def test_delta_failure_never_soft_quarantines_previously_accepted_history(example,monkeypatch):
    e=example
    qfq._json(qfq.input_path(e['data']),e['new'])
    monkeypatch.setattr(inputs,'existing_day_files',lambda _:[])
    def fail(*args,**kwargs):raise qfq.QfqGateError('EXACT_NEW_RAW_GATE_FAILURE')
    monkeypatch.setattr(qfq,'rebuild_symbol',fail)
    before={r:p.read_bytes() for r,p in e['pointers'].items()}
    with pytest.raises(qfq.QfqGateError,match='EXACT_NEW_RAW_GATE_FAILURE'):
        qfq.run_daily_rebuild(driver_path=DRIVER,formula_path=FORMULA,tdx_root=e['root']/'tdx',data_root=e['data'],pointers=e['pointers'],contract_csv=e['field'],return_root=e['root']/'failed_delta_runs',target=e['target'],workers=1,tail_delta=e['delta_ref'])
    assert {r:p.read_bytes() for r,p in e['pointers'].items()}==before
    assert not list((e['root']/'failed_delta_runs').rglob('candidate_receipt.json'))


def test_review_pass_for_other_code_cannot_admit_unreviewed_tail(example):
    e=example;s=copy.deepcopy(e['new']);delta=copy.deepcopy(e['delta'])
    report=json.loads(Path(delta['codes'][e['changed'][0]]['independent_review']['path']).read_text())
    report['reports'][0]['code']='000999.SZ'
    bad=js(e['root']/'wrong_code_review.json',report)
    s['source_files'].append(bad);s['history_retention_binding']['accepted_evidence'].append(bad)
    delta['codes'][e['changed'][0]]['independent_review']=bad
    wrong=js(e['root']/'wrong_code_delta.json',delta)
    with pytest.raises(qfq.QfqGateError,match='REVIEW_CODE_KEYS_OR_COMPLETE_SOURCE'):
        qfq.tail_delta_binding(wrong,snapshot=s,pointers=e['pointers'],identity=e['identity'],target=e['target'],retained_history=e['retention'])
