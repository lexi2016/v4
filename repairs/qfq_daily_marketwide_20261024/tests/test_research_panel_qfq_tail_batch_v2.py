"""Synthetic V2 contract boundaries, never actual recovery receipts/admission.

The fixture explicitly substitutes only the two approved metadata digests with
its synthetic scope digests. Production defaults retain the controller pins.
Original formula/Arrow/copy/publication code is invoked without replacements.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import struct

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from ops import research_panel_qfq as qfq
from ops import research_panel_adjustment_inputs as inputs

APP=Path(os.environ['TAIL_V2_ORIGINAL_APP'])
DRIVER=APP/'ops/vendor/data_layer_daily_formula_increment_update_v1.py'
FORMULA=APP/'ops/vendor/build_canonical_formula_research_panel.py'
BASELINE=Path(os.environ['TAIL_V2_BASELINE_CORE'])
SCOPE=Path(os.environ['TAIL_V2_FROZEN_SCOPE'])
ADDITIONS=Path(os.environ['TAIL_V2_ACCEPTED_ADDITIONS'])
REAL_SCOPE_SHA='aec0ce66a1431fb3b23f44b34f7d52717e0823f4742893dc495231f8e6a3b5aa'
REAL_ADDITION_SHA='f8c8c796858c2167b3a1fac2daa4fd54149de542419aa1bc121e814aeea036ee'


def ref(p):return dict(path=str(p),sha256=qfq.sha(p))
def js(p,v):qfq._json(p,v);return ref(p)
def digest_rows(rows):return hashlib.sha256(b''.join(rows[d] for d in sorted(rows))).hexdigest()
def raw_rows(dates):
    return {d:struct.pack('<IIIIIfII',d,1000+i,1010+i,990+i,1000+i,float(100000+i),10000+i,0) for i,d in enumerate(dates)}
def changed_reserved(payload):return payload[:-4]+b'\x01\x00\x00\x00'


@pytest.fixture(scope='module')
def example(tmp_path_factory):
    root=tmp_path_factory.mktemp('synthetic_exact37');data=root/'data';runs=root/'runs'
    dates=pd.bdate_range(end='2026-10-23',periods=280).strftime('%Y%m%d').astype(int).tolist();target=dates[-1]
    frozen=json.loads(SCOPE.read_text());addition=json.loads(ADDITIONS.read_text())
    changed=sorted(r['ts_code'] for r in frozen['source_binding_rows']);archive_only=set(addition['codes'])
    active='999998.SZ';inactive='999997.SH';all_codes=changed+[active,inactive]
    driver=qfq.authorities(DRIVER,FORMULA)[0];all_rows=raw_rows(dates)
    policy=js(root/'policy.json',dict(name=qfq.HISTORY_RESOLUTION,selection_unit='COMPLETE_SOURCE_BAR',price_or_volume_conversion='NONE'))
    archive_container=root/'synthetic_archive.zip';archive_container.write_bytes(b'NOT_REAL_MARKET_SOURCE_SYNTHETIC_TEST_ONLY')
    stocks=[];items={};frames=[];physical={};new_native={};before_native={};reports=[]
    scope=copy.deepcopy(frozen);scope['synthetic_fixture_only']=True
    scope_rows={r['ts_code']:r for r in scope['source_binding_rows']}
    for code in all_codes:
        ds=dates[:-4] if code in changed else dates[:-5] if code==inactive else dates
        archive=root/(code+'.archive.day');archive.write_bytes(b''.join(all_rows[d] for d in ds));archive_ref=ref(archive)
        archive_source=dict(name='archive',kind='archive_member',path=str(archive_container),member=code+'.day',member_sha256=archive_ref['sha256'])
        sources=[archive_source];rawrefs=[dict(**archive_ref,source_role='archive')]
        if code not in archive_only:
            nds=ds[-25:-8] if code in changed else ds[-20:]
            native=root/(code+'.native.before.day');native.write_bytes(b''.join(changed_reserved(all_rows[d]) for d in nds));nr=ref(native)
            sources.append(dict(**nr,name='native',kind='day_bytes'));rawrefs.append(dict(**nr,source_role='native'))
        else:
            nds=ds;native=root/(code+'.native.before.day');native.write_bytes(archive.read_bytes());nr=ref(native)
        stocks.append(dict(code=code,sources=sources))
        item=dict(raw_files=rawrefs,history_start_date=ds[0],history_end_date=ds[-1],events=[],event_coverage_complete=True,publish_roles=['selector','backtest'],history_extension=True,raw_resolution=qfq.HISTORY_RESOLUTION)
        items[code]=item
        frame=qfq.rebuild_symbol(code,item,target,driver);frame['name']='synthetic '+code;frame['field_contract_version']=driver.CONTRACT_PROVENANCE_FIELD_DEFAULTS['field_contract_version'];frames.append(frame)
        if code in changed:
            appended=[d for d in dates if d>nds[-1]]
            after=root/(code+'.native.after.day');after.write_bytes(native.read_bytes()+b''.join(changed_reserved(all_rows[d]) for d in appended))
            before_copy=root/(code+'.isolated_before_copy.day');before_copy.write_bytes(native.read_bytes());before_native[code]=ref(before_copy);new_native[code]=ref(after);physical[code]=appended
            response=js(root/(code+'.synthetic_response.json'),dict(source='SYNTHETIC_TEST_FIXTURE_NOT_PROVIDER_CAPTURE',code=code,rows=[]))
            nr=before_native[code]
            scope_rows[code]['native']['sha256']=nr['sha256'];scope_rows[code]['original_MAC_response']=response
            newrefs=[rawrefs[0],dict(**new_native[code],source_role='native')]
            reports.append(dict(code=code,added_dates=dates[-4:],native_before=nr,native_after=new_native[code],native_appended_dates=appended,native_cutoff=nds[-1],provider_response=response,provider_query_started_utc=scope_rows[code]['source_query_started_utc'],old_native_prefix_unchanged=True,full_seed_gate_passed=True,field_signature_gate_passed=True,returned_continuity_gate_passed=True,old_keys_lost=0,old_values_changed=0,buffer_admitted_as_full_history=False,old_selected_raw_sha256=qfq._tail_selected_bytes_sha(rawrefs,target),staged_sha256=qfq._tail_selected_bytes_sha(newrefs,target)))
    scope_ref=js(root/'synthetic_scope.json',scope)
    addition_ref=js(root/'synthetic_accepted8.json',dict(schema='qfq_archive_only_history_additions_v1',asof_date=target,codes={c:{} for c in archive_only},synthetic_fixture_only=True))
    patch=pytest.MonkeyPatch();patch.setattr(qfq,'TAIL_BATCH_V2_SOURCE_BINDING_SHA',scope_ref['sha256']);patch.setattr(qfq,'TAIL_BATCH_V2_ARCHIVE_ADDITIONS_SHA',addition_ref['sha256'])
    review_obj=dict(schema='qfq_native_tail_recovery_review_v2',verdict='REVIEWED/PASS_EXACT_MAC_NATIVE_TAIL_BATCH_V2',reviewer_id='/independent/SYNTHETIC_FIXTURE_ONLY',asof_date=target,source_binding=scope_ref,network_requests=0,research_only=True,production_allowed=False,buy_gate_updated=False,orders_sent=False,reports=reports,synthetic_fixture_only=True)
    review=js(root/'synthetic_review.json',review_obj)
    config_obj=dict(source_resolution=qfq.HISTORY_RESOLUTION,stocks=stocks)
    config=js(root/'source_old.json',config_obj);retention=dict(source_config=config,source_policy=policy,archive_refs=[ref(archive_container)],accepted_evidence=[])
    for item in items.values():item.update(source_config=config,accepted_evidence=[])
    old=dict(schema='a_share_qfq_adjustment_input_v1',asof_date=target,coverage_end_date=target,price_basis='QFQ_ASOF',volume_basis='QFQ_EVENT_VOLUME',amount_basis='RAW_TURNOVER',convention='SYNTHETIC_V2_ONLY',revision='old',observed_at='2026-10-24T00:00:00+00:00',source_files=[policy,config,ref(archive_container)],symbols=items,history_extension=None,history_retention_binding=retention,retained_history_codes=[],accepted_target_date_floor=1)
    oldref=js(root/'baseline_snapshot.json',old)
    new_config_obj=copy.deepcopy(config_obj)
    for stock in new_config_obj['stocks']:
        code=stock['code']
        if code in changed:stock['sources']=[stock['sources'][0],dict(**new_native[code],name='native',kind='day_bytes')]
    new_config=js(root/'source_new.json',new_config_obj);new_retention={**retention,'source_config':new_config,'accepted_evidence':[review]}
    new=copy.deepcopy(old);new.update(revision='new',history_retention_binding=new_retention,source_files=old['source_files']+[new_config,review,scope_ref,addition_ref,*before_native.values(),*new_native.values()])
    for code,item in new['symbols'].items():
        item.update(source_config=new_config,accepted_evidence=[review])
        if code in changed:item.update(history_end_date=target,raw_files=[item['raw_files'][0],dict(**new_native[code],source_role='native')])
    field=root/'field.csv';field.write_text('synthetic contract\n');identity=qfq.generation_identity(new,DRIVER,FORMULA,field)
    old_identity={**identity,'input_sha256':qfq.canonical_sha(old),'adapter_sha256':qfq.sha(BASELINE)}
    all_frame=pd.concat(frames,ignore_index=True)
    columns=['ts_code','trade_date','open','high','low','close','vol','volume','amount','pre_close','pct_chg','BBI','J','ma60','zge_white_line','zge_yellow_line','name','bars_since_list','field_contract_version','raw_source_role','raw_source_ref_sha256','raw_source_record_index',*qfq.USER_FORMULA_SIGNAL_FIELDS]
    columns=list(dict.fromkeys(columns+[c for c in (*driver.CONTRACT_REQUIRED_V192_SELECTOR_COLUMNS,*driver.V192_ENTRY_FIELDS,*driver.V192_INTERMEDIATE_FIELDS,*driver.CRITICAL_SELECTOR_FORMULA_COLUMNS) if c in all_frame]))
    baseline=all_frame[columns].copy();foreign=baseline.loc[baseline.ts_code.eq(active)].iloc[-2:].copy();foreign.ts_code='00700.HK'
    for name in qfq.USER_FORMULA_SIGNAL_FIELDS:foreign[name]=None
    baseline=pd.concat([baseline,foreign],ignore_index=True);pointers={};roles={}
    for role in ('selector','backtest'):
        meta=dict(**old_identity,generation_id='SYNTHETIC_V2_BASELINE',asof_date=target,history_retention_binding=retention)
        table=pa.Table.from_pandas(baseline,preserve_index=False);typed=pa.schema([pa.field(f.name,pa.int64(),nullable=True) if f.name=='bars_since_list' else f for f in qfq.user_formula_schema(table.schema)])
        table=table.cast(typed).replace_schema_metadata({qfq.META_KEY:json.dumps(meta).encode()});path=root/(role+'.parquet');pq.write_table(table,path)
        pointer=data/role/'CURRENT.txt';pointer.parent.mkdir(parents=True);pointer.write_text(str(path));pointers[role]=pointer;roles[role]=ref(path)
    delta=dict(schema='qfq_native_tail_delta_v2',asof_date=target,baseline_generation_id='SYNTHETIC_V2_BASELINE',baseline_snapshot=oldref,baseline_core=ref(BASELINE),baseline_roles=roles,source_binding=scope_ref,accepted_archive_additions=addition_ref,independent_raw_review=review,
               codes={code:dict(added_dates=dates[-4:],native_before=before_native[code],native_after=new_native[code],native_appended_dates=physical[code],native_cutoff=next(r['native_cutoff'] for r in reports if r['code']==code),independent_review=review) for code in changed})
    delta_ref=js(root/'delta.json',delta)
    yield locals()
    patch.undo()


def bind(e,delta=None,snapshot=None):
    return qfq.tail_delta_binding(delta or e['delta_ref'],snapshot=snapshot or e['new'],pointers=e['pointers'],identity=e['identity'],target=e['target'],retained_history=e['retention'])


def test_v2_exact37_original_pair_rebuild_and_148_selected_keys(example,monkeypatch):
    e=example;called=[];original=qfq.rebuild_symbol;before={r:p.read_bytes() for r,p in e['pointers'].items()}
    def compute(code,*a,**kw):called.append(code);assert code in e['changed'];return original(code,*a,**kw)
    monkeypatch.setattr(qfq,'rebuild_symbol',compute);monkeypatch.setattr(inputs,'existing_day_files',lambda _:[])
    qfq._json(qfq.input_path(e['data']),e['new'])
    result=qfq.run_daily_rebuild(driver_path=DRIVER,formula_path=FORMULA,tdx_root=e['root']/'tdx',data_root=e['data'],pointers=e['pointers'],contract_csv=e['field'],return_root=e['runs'],target=e['target'],workers=1,tail_delta=e['delta_ref'])
    assert result['status']=='CANDIDATE_READY' and sorted(called)==e['changed']
    assert sum(len(x) for x in e['physical'].values())>148
    for role,path in result['candidates'].items():
        old=pq.read_table(e['roles'][role]['path']);new=pq.read_table(path);assert len(new)==len(old)+148
        for code in (e['active'],e['inactive'],'00700.HK'):
            assert old.filter(pa.compute.equal(old['ts_code'],code)).to_pandas().equals(new.filter(pa.compute.equal(new['ts_code'],code)).to_pandas())
        assert result['counts'][role]['old_key_conservation'] and e['pointers'][role].read_bytes()==before[role]
    assert len(list((Path(result['run_dir'])/'symbol_checkpoints').glob('*.parquet')))==37
    assert qfq.computation_kernel_sha(BASELINE)==qfq.computation_kernel_sha(Path(qfq.__file__))


@pytest.mark.parametrize('mutation,match',[
 ('v1_cap','CONTRACT_INVALID'),('schema','CONTRACT_INVALID'),('missing_code','CONTRACT_INVALID'),('extra_code','CONTRACT_INVALID'),
 ('selected_keys','EXACT_CODES_OR_KEYS'),('scope_pin','APPROVED_SCOPE'),('addition_pin','APPROVED_SCOPE'),
 ('old_verdict','ACTUAL_RAW_REVIEW'),('self_review','ACTUAL_RAW_REVIEW'),('missing_report','ACTUAL_RAW_REVIEW'),('extra_report','ACTUAL_RAW_REVIEW'),
 ('physical_equals_selected','PHYSICAL_OR_REVIEW'),('native_cutoff','PHYSICAL_CUTOFF'),('native_before','PHYSICAL_OR_REVIEW'),('provider_ref','PHYSICAL_OR_REVIEW'),
 ('query_utc','PHYSICAL_OR_REVIEW'),('seed_gate','PHYSICAL_OR_REVIEW'),('field_gate','PHYSICAL_OR_REVIEW'),('continuity_gate','PHYSICAL_OR_REVIEW'),('buffer','PHYSICAL_OR_REVIEW'),
 ('selected_hash','SELECTED_KEYS_OR_OLD_RAW'),('old_selected_hash','SELECTED_KEYS_OR_OLD_RAW'),('event','EVENT_OR_THIRD_CODE'),('floor','NON_RAW_SNAPSHOT'),
 ('third_code','EVENT_OR_THIRD_CODE'),('membership','ASOF_OR_MEMBERSHIP'),('source_policy','SOURCE_POLICY'),('drop_closure','SOURCE_CLOSURE'),
 ('archive_changed','ARCHIVE_OR_NATIVE_ROLES'),('native_role_lost','ARCHIVE_OR_NATIVE_ROLES'),('extra_role','ARCHIVE_OR_NATIVE_ROLES'),('archive_raw_changed','ITEM_RAW_ROLES'),
])
def test_v2_rejects_changed_contract_or_recovery_evidence(example,tmp_path,mutation,match):
    e=example;d=copy.deepcopy(e['delta']);s=copy.deepcopy(e['new']);review=copy.deepcopy(e['review_obj']);c=e['changed'][0];normal=next(c for c in e['changed'] if c not in e['archive_only']);report=next(r for r in review['reports'] if r['code']==normal)
    if mutation=='v1_cap':d['schema']='qfq_native_tail_delta_v1'
    elif mutation=='schema':d['schema']='qfq_native_tail_delta_v3'
    elif mutation=='missing_code':d['codes'].pop(c)
    elif mutation=='extra_code':d['codes'][e['active']]=copy.deepcopy(d['codes'][c])
    elif mutation=='selected_keys':d['codes'][c]['added_dates']=d['codes'][c]['added_dates'][:-1]
    elif mutation=='scope_pin':d['source_binding']['sha256']='0'*64
    elif mutation=='addition_pin':d['accepted_archive_additions']['sha256']='0'*64
    elif mutation=='old_verdict':review['verdict']='REVIEWED/PASS_ISOLATED_TWO_STOCK_TAIL_RECOVERY_ONLY'
    elif mutation=='self_review':review['reviewer_id']='/root/security_master_normalization_sol'
    elif mutation=='missing_report':review['reports'].pop()
    elif mutation=='extra_report':review['reports'].append(copy.deepcopy(report))
    elif mutation=='physical_equals_selected':d['codes'][normal]['native_appended_dates']=d['codes'][normal]['added_dates']
    elif mutation=='native_cutoff':d['codes'][normal]['native_cutoff']+=1;report['native_cutoff']+=1
    elif mutation=='native_before':d['codes'][normal]['native_before']['sha256']='0'*64
    elif mutation=='provider_ref':report['provider_response']['sha256']='0'*64
    elif mutation=='query_utc':report['provider_query_started_utc']='2026-10-24T00:00:00+00:00'
    elif mutation in ('seed_gate','field_gate','continuity_gate'):report[{'seed_gate':'full_seed_gate_passed','field_gate':'field_signature_gate_passed','continuity_gate':'returned_continuity_gate_passed'}[mutation]]=False
    elif mutation=='buffer':report['buffer_admitted_as_full_history']=True
    elif mutation=='selected_hash':report['staged_sha256']='0'*64
    elif mutation=='old_selected_hash':report['old_selected_raw_sha256']='0'*64
    elif mutation=='event':s['symbols'][c]['events']=[dict(ex_date=e['target'],a=1.,b=-1.,volume_a=1.)]
    elif mutation=='floor':s['accepted_target_date_floor']=0
    elif mutation=='third_code':s['symbols'][e['active']]['history_start_date']+=1
    elif mutation=='membership':s['symbols'].pop(e['active'])
    elif mutation=='source_policy':s['history_retention_binding']['archive_refs']=[]
    elif mutation=='drop_closure':s['source_files'].remove(d['source_binding'])
    elif mutation=='archive_raw_changed':s['symbols'][normal]['raw_files'][0]['sha256']='0'*64
    elif mutation in ('archive_changed','native_role_lost','extra_role'):
        cfg=copy.deepcopy(e['new_config_obj']);stock=next(x for x in cfg['stocks'] if x['code']==normal)
        if mutation=='archive_changed':stock['sources'][0]['member_sha256']='0'*64
        elif mutation=='native_role_lost':stock['sources']=stock['sources'][:1]
        else:stock['sources'].append(dict(stock['sources'][1],name='other'))
        cr=js(tmp_path/'changed_config.json',cfg);s['source_files'].append(cr);s['history_retention_binding']['source_config']=cr
        for item in s['symbols'].values():item['source_config']=cr
    if review!=e['review_obj']:
        rr=js(tmp_path/'synthetic_changed_review.json',review);prior=d['independent_raw_review'];d['independent_raw_review']=rr
        for item in d['codes'].values():item['independent_review']=rr
        s['source_files'].append(rr);s['history_retention_binding']['accepted_evidence']=[rr]
    dr=js(tmp_path/'changed_delta.json',d)
    with pytest.raises(qfq.QfqGateError,match=match):bind(e,dr,s)


def test_v2_actual_scope_pin_cannot_be_overridden_by_fixture(example,monkeypatch):
    monkeypatch.setattr(qfq,'TAIL_BATCH_V2_SOURCE_BINDING_SHA',REAL_SCOPE_SHA)
    monkeypatch.setattr(qfq,'TAIL_BATCH_V2_ARCHIVE_ADDITIONS_SHA',REAL_ADDITION_SHA)
    with pytest.raises(qfq.QfqGateError,match='APPROVED_SCOPE'):bind(example)


def test_v1_native_physical_and_typed_capacity_remain_strict(tmp_path):
    before=tmp_path/'before.day';after=tmp_path/'after.day';rows=raw_rows([20261019,20261020,20261021]);before.write_bytes(rows[20261019]);after.write_bytes(b''.join(rows.values()))
    qfq._native_tail_extension(dict(**ref(before),name='native',kind='day_bytes'),dict(**ref(after),name='native',kind='day_bytes'),[20261020,20261021],'002961.SZ')
    with pytest.raises(qfq.QfqGateError,match='NATIVE_NEW_KEYS'):
        qfq._native_tail_extension(dict(**ref(before),name='native',kind='day_bytes'),dict(**ref(after),name='native',kind='day_bytes'),[20261021],'002961.SZ')
