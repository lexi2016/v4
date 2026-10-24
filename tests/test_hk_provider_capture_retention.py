from __future__ import annotations

import ast
import copy
import datetime as dt
import hashlib
import json
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

import ops.macos_research_panel_daily as producer
import ops._hk_provider_capture as evidence

TARGET='20261023'
BASELINE=Path(__file__).resolve().parents[1]/'.superpowers/sdd/2026-10-23-us-hk-selection-closure/scratch/capture/source-before.py'


def quote(code):
    return dict(code=code,name='Name '+code,update_time='2026-10-23 16:08:09',open_price=10.25,
        high_price=11.5,low_price=9.5,last_price=10.75,volume=1000.4,turnover=30000000.25,
        future_unknown_column={'arbitrary':['kept',1,True]})


class SDK:
    def __init__(self,count=600,change=None,fail_at=None):
        self.codes=['HK.'+str(i).zfill(5) for i in range(1,count+1)]
        self.change=change;self.fail_at=fail_at;self.calls=[];self.closed=False
    def get_plate_stock(self,plate):
        self.calls.append(('get_plate_stock',plate))
        selected=self.codes[:len(self.codes)//2] if plate==producer.HKCONNECT_PLATE_CODES[0] else self.codes[len(self.codes)//2:]
        return 0,pd.DataFrame([dict(code=c,stock_name='Name '+c,extra_plate_column='preserved') for c in selected])
    def get_market_snapshot(self,codes):
        self.calls.append(('get_market_snapshot',list(codes)))
        batch=sum(call[0]=='get_market_snapshot' for call in self.calls)
        if batch==self.fail_at:raise RuntimeError('injected SDK failure')
        rows=[quote(c) for c in codes]
        if self.change:rows=self.change(rows,batch)
        return 0,pd.DataFrame(rows)
    def close(self):self.closed=True


def collect(tmp_path,sdk):
    return producer.collect_hk_futu_rows(TARGET,context_factory=lambda:sdk,
        capture_manifest_path=tmp_path/'capture.json')


def read_refs(refs):
    path=Path(refs['manifest_path']);raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()==refs['manifest_sha256']
    manifest=json.loads(raw);responses=[]
    assert manifest['capture_run_id']==refs['capture_run_id']==path.stem
    for meta in manifest['responses']:
        artifact=meta['artifact'];encoded=(path.parent/artifact['relative']).read_bytes()
        assert hashlib.sha256(encoded).hexdigest()==artifact['sha256']
        response=json.loads(encoded)
        assert response['completed_at']==response['available_at_observed']
        assert dt.datetime.fromisoformat(response['requested_at'])<=dt.datetime.fromisoformat(response['completed_at'])
        responses.append(response)
    tables=[]
    for key,items in [('row_dispositions','rows'),('code_dispositions','codes')]:
        ref=manifest[key];encoded=(path.parent/ref['relative']).read_bytes()
        assert hashlib.sha256(encoded).hexdigest()==ref['sha256']
        tables.append(json.loads(encoded)[items])
    row_ledger,code_ledger=tables
    expected=sum(len(r['sdk_response'].get('row_values',r['sdk_response'].get('rows',[]))) for r in responses)
    assert expected==len(row_ledger)==manifest['response_row_count']
    assert len({(r['batch'],r['ordinal']) for r in row_ledger})==expected
    for row in row_ledger:
        response=manifest['responses'][row['batch']]
        assert row['response_sha256']==response['artifact']['sha256']
        assert row['response_relative']==response['artifact']['relative']
        assert row['ordinal'] < response['row_count']
    assert [r['code'] for r in code_ledger]==manifest['requested_union_codes']
    return manifest,responses,row_ledger,code_ledger


def old_function(name):
    tree=ast.parse(BASELINE.read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==name)
    namespace=dict(vars(producer));exec(compile(ast.Module(body=[node],type_ignores=[]),str(BASELINE),'exec'),namespace)
    return namespace[name]


def test_same_provider_calls_normalized_hash_and_valid_packed_bytes(tmp_path):
    original_sdk=SDK();original=old_function('collect_hk_futu_rows')(TARGET,context_factory=lambda:original_sdk)
    current_sdk=SDK();current=collect(tmp_path,current_sdk)
    assert current_sdk.calls==original_sdk.calls
    assert current_sdk.calls[:2]==[('get_plate_stock',p) for p in producer.HKCONNECT_PLATE_CODES]
    assert [len(c[1]) for c in current_sdk.calls[2:]]==[200,200,200]
    assert current_sdk.closed and original_sdk.closed
    for key,value in original.items():assert current[key]==value,key
    old_packed=b''.join(producer.HK_DAY_STRUCT.pack(*producer._hk_record(row)) for row in original['rows'])
    new_packed=b''.join(producer.HK_DAY_STRUCT.pack(*producer._hk_record(row)) for row in current['rows'])
    assert old_packed==new_packed
    _,responses,ledger,codes=read_refs(current['provider_capture'])
    assert len(ledger)==1200 and len(codes)==600 and all(c['disposition']=='ACCEPTED' for c in codes)
    quote_response=responses[2]
    columns=quote_response['sdk_response']['columns'];values=quote_response['sdk_response']['row_values'][0]
    raw=dict(zip(columns,values))
    assert raw['update_time']=='2026-10-23 16:08:09' and raw['volume']==1000.4
    assert raw['future_unknown_column']=={'arbitrary':['kept',1,True]}
    assert dt.datetime.fromisoformat(quote_response['requested_at'])>=dt.datetime.fromisoformat(responses[1]['completed_at'])
    accepted=[r for r in ledger if r['method']=='get_market_snapshot']
    assert all(r['normalized_row']['volume']==1000 and r['expected_packed_relative'].startswith('vipdoc/ds/lday/71#') for r in accepted)


def test_exclusions_over100_still_reconcile_full_rows_and_codes(tmp_path):
    def change(rows,batch):
        for row in rows:
            if int(row['code'][3:])>600:row['volume']=0
        return rows
    current=collect(tmp_path,SDK(750,change=change))
    assert current['excluded_count']==150 and len(current['excluded_codes'])==100
    manifest,responses,ledger,codes=read_refs(current['provider_capture'])
    assert len([c for c in codes if c['disposition']=='EXCLUDED'])==150
    assert len([r for r in ledger if r['disposition']=='EXCLUDED'])==150
    assert len(current['rows'])==600
    assert all(r['response_sha256'] for r in ledger)


def test_identical_conflicting_unmatched_missing_and_stale_rows(tmp_path):
    def change(rows,batch):
        if batch==1:
            rows=rows[1:]  # requested HK.00001 missing response
            rows[0]['update_time']='2026-10-22 16:00:00'
            rows.append(copy.deepcopy(rows[1]))  # identical HK.00003
            conflict=copy.deepcopy(rows[2]);conflict['turnover']+=1;rows.append(conflict)
            rows.append(quote('US.UNMATCHED'))
        return rows
    current=collect(tmp_path,SDK(610,change=change))
    _,_,ledger,codes=read_refs(current['provider_capture']);indexed={c['code']:c for c in codes}
    assert indexed['HK.00001']['disposition']=='MISSING_RESPONSE'
    assert indexed['HK.00002']['disposition']=='EXCLUDED'
    assert indexed['HK.00004']['disposition']=='PENDING_CONFLICT'
    assert len([r for r in ledger if r['disposition']=='DUPLICATE_IDENTICAL'])==1
    assert len([r for r in ledger if r['disposition']=='CONFLICTING_SNAPSHOT'])==2
    assert any(r['disposition']=='UNMATCHED_CODE' and r['code']=='US.UNMATCHED' for r in ledger)
    assert 'HK.00004' not in {r['code'] for r in current['rows']}


@pytest.mark.parametrize('field,value',[('open_price',True),('volume',False),('turnover',float('inf')),('last_price',float('nan'))])
def test_boolean_nonfinite_financial_values_saved_but_excluded(tmp_path,field,value):
    def change(rows,batch):
        if batch==1:rows[0][field]=value
        return rows
    current=collect(tmp_path,SDK(601,change=change))
    _,responses,ledger,codes=read_refs(current['provider_capture'])
    assert codes[0]['disposition']=='EXCLUDED' and 'non_numeric_fields' in codes[0]['reasons']
    raw=dict(zip(responses[2]['sdk_response']['columns'],responses[2]['sdk_response']['row_values'][0]))
    if isinstance(value,bool):assert raw[field] is value
    else:assert raw[field]=={'$float':repr(value)}


def test_unknown_typed_fields_are_preserved(tmp_path):
    def change(rows,batch):
        if batch==1:
            rows[0]['decimal']=Decimal('1.2300');rows[0]['missing']=pd.NA
            rows[0]['bytes']=b'\x00\x01';rows[0]['timestamp']=dt.datetime(2026,10,23,16,8,tzinfo=dt.timezone.utc)
        return rows
    current=collect(tmp_path,SDK(change=change));_,responses,_,_=read_refs(current['provider_capture'])
    raw=dict(zip(responses[2]['sdk_response']['columns'],responses[2]['sdk_response']['row_values'][0]))
    assert raw['decimal']=={'$decimal':'1.2300'} and raw['missing']=={'$missing_scalar':'NAType'}
    assert raw['bytes']=={'$bytes_hex':'0001'} and raw['timestamp']['$datetime'].startswith('2026-10-23')


def test_mid_batch_failure_retains_prior_responses_and_error(tmp_path):
    sdk=SDK(fail_at=2)
    with pytest.raises(evidence.CaptureFailure) as raised:collect(tmp_path,sdk)
    manifest,responses,ledger,codes=read_refs(raised.value.capture_refs)
    assert manifest['status']=='FAILED' and sdk.closed
    assert len(responses)==4 and responses[-1]['error']=={'type':'RuntimeError','message':'injected SDK failure'}
    assert len(ledger)==800 and len(codes)==600
    assert any(c['disposition']=='NOT_REQUESTED_AFTER_ABORT' for c in codes)
    assert any(c['disposition']=='NOT_EVALUATED_AFTER_ABORT' for c in codes)


def test_missing_capture_and_initial_write_failure_prevent_provider_calls(tmp_path,monkeypatch):
    sdk=SDK()
    monkeypatch.delenv('V35_HK_CAPTURE_PATH',raising=False)
    with pytest.raises(evidence.CaptureFailure,match='PATH_REQUIRED'):
        producer.collect_hk_futu_rows(TARGET,context_factory=lambda:sdk)
    assert not sdk.calls
    def blocked(*args,**kwargs):raise OSError('injected storage failure')
    monkeypatch.setattr(evidence,'_write',blocked)
    with pytest.raises(OSError,match='storage failure'):collect(tmp_path,sdk)
    assert not sdk.calls


def test_partial_write_failure_stops_capture_and_keeps_prior_manifest_refs(tmp_path,monkeypatch):
    original=evidence._write
    def write(path,raw,*,immutable):
        if 'response-0003' in path.name:raise OSError('injected batch storage failure')
        return original(path,raw,immutable=immutable)
    monkeypatch.setattr(evidence,'_write',write)
    with pytest.raises(evidence.CaptureFailure) as raised:collect(tmp_path,SDK())
    manifest,responses,_,_=read_refs(raised.value.capture_refs)
    assert manifest['status']=='FAILED' and len(responses)==3
    assert 'storage failure' in manifest['error']


def test_unsupported_sdk_extra_value_stops_publication(tmp_path):
    def change(rows,batch):
        if batch==1:rows[0]['unknown_object']=object()
        return rows
    with pytest.raises(evidence.CaptureFailure) as raised:collect(tmp_path,SDK(change=change))
    manifest,responses,_,_=read_refs(raised.value.capture_refs)
    assert manifest['status']=='FAILED' and responses[-1]['serialization_complete'] is False


def test_same_caller_lane_receipt_links_actual_pack_and_failure(tmp_path):
    calls=[]
    def authority(*args):calls.append(args);return dict(status='READY',through_date=TARGET,panel_sha256='a'*64)
    outcome=producer._run_hk_retained(TARGET,receipt_root=tmp_path/'receipts',tdx_root=tmp_path/'tdx',
        updater_script=Path('/synthetic/updater'),python_executable='/synthetic/python',asset_root=tmp_path/'assets',
        context_factory=lambda:SDK(),authority_runner=authority)
    assert outcome['status']=='READY' and len(calls)==1
    receipt=producer._receipt(tmp_path/'receipts','HK',TARGET,outcome)
    refs=receipt['provider_capture'];read_refs(refs)
    lane=json.loads(Path(refs['lane_receipt_path']).read_bytes())
    assert hashlib.sha256(Path(refs['lane_receipt_path']).read_bytes()).hexdigest()==refs['lane_receipt_sha256']
    assert len(lane['packed']['files'])==600 and lane['authority']['panel_sha256']=='a'*64
    for row in outcome['rows'][:3]:
        raw=(tmp_path/'tdx/vipdoc/ds/lday'/('71#'+row['code'][3:]+'.day')).read_bytes()
        assert raw==producer.HK_DAY_STRUCT.pack(*producer._hk_record(row))
    failed=producer._run_hk_retained(TARGET,receipt_root=tmp_path/'failed',tdx_root=tmp_path/'unused',
        updater_script=Path('/synthetic/updater'),python_executable='/synthetic/python',asset_root=tmp_path/'assets',
        context_factory=lambda:SDK(fail_at=2),authority_runner=authority)
    assert failed['status']=='FAILED' and len(calls)==1 and not (tmp_path/'unused').exists()
    failed_receipt=producer._receipt(tmp_path/'failed','HK',TARGET,failed)
    assert failed_receipt['provider_capture']['lane_status']=='FAILED'
    read_refs(failed_receipt['provider_capture'])


def test_non_hk_functions_and_main_outside_hk_runner_are_unchanged():
    old=ast.parse(BASELINE.read_text());new=ast.parse(Path(producer.__file__).read_text())
    old_functions={n.name:n for n in old.body if isinstance(n,ast.FunctionDef)}
    new_functions={n.name:n for n in new.body if isinstance(n,ast.FunctionDef)}
    for name,node in old_functions.items():
        if name in ('collect_hk_futu_rows','main'):continue
        assert ast.dump(node,include_attributes=False)==ast.dump(new_functions[name],include_attributes=False),name
        assert ast.get_source_segment(BASELINE.read_text(),node)==ast.get_source_segment(Path(producer.__file__).read_text(),new_functions[name]),name
    assert set(new_functions)-set(old_functions)=={'_run_hk_retained'}
    for tree in (old_functions['main'],new_functions['main']):
        for index,node in enumerate(tree.body):
            if isinstance(node,ast.FunctionDef) and node.name=='run_hk':
                tree.body[index]=ast.Pass()
    assert ast.dump(old_functions['main'],include_attributes=False)==ast.dump(new_functions['main'],include_attributes=False)



def test_non_ok_sdk_payload_and_duplicate_columns_preserved_before_rejection(tmp_path):
    class NonOK(SDK):
        def get_market_snapshot(self,codes):
            self.calls.append(('get_market_snapshot',list(codes)))
            return 7,{'error':'original error payload','unknown_error_field':[1,2]}
    sdk=NonOK()
    with pytest.raises(evidence.CaptureFailure) as raised:collect(tmp_path/'nonok',sdk)
    _,responses,_,_=read_refs(raised.value.capture_refs)
    assert responses[-1]['return_code']==7
    # A non-frame mapping is still captured as the complete SDK error payload.
    assert responses[-1]['sdk_response']['value']=={'error':'original error payload','unknown_error_field':[1,2]}
    class DuplicateColumns(SDK):
        def get_market_snapshot(self,codes):
            self.calls.append(('get_market_snapshot',list(codes)))
            return 0,pd.DataFrame([[codes[0],1,2]],columns=['code','extra','extra'])
    with pytest.raises(evidence.CaptureFailure) as raised:collect(tmp_path/'duplicate',DuplicateColumns())
    _,responses,ledger,_=read_refs(raised.value.capture_refs)
    assert responses[-1]['sdk_response']['columns']==['code','extra','extra']
    assert responses[-1]['sdk_response']['row_values']==[['HK.00001',1,2]]
    assert ledger[-1]['disposition']=='NOT_EVALUATED_CAPTURE_ABORTED'


def test_immutable_run_reuse_cannot_overwrite_frames(tmp_path):
    current=collect(tmp_path,SDK());read_refs(current['provider_capture'])
    pins={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}
    second=SDK()
    with pytest.raises(evidence.CaptureFailure,match='ALREADY_EXISTS'):collect(tmp_path,second)
    assert not second.calls
    assert pins=={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in tmp_path.iterdir()}


def test_authority_failure_retains_pack_and_capture_refs(tmp_path):
    def authority(*args):raise RuntimeError('injected authority failure')
    outcome=producer._run_hk_retained(TARGET,receipt_root=tmp_path/'receipts',tdx_root=tmp_path/'tdx',
        updater_script=Path('/synthetic/updater'),python_executable='/synthetic/python',asset_root=tmp_path/'assets',
        context_factory=lambda:SDK(),authority_runner=authority)
    assert outcome['status']=='FAILED'
    read_refs(outcome['provider_capture'])
    lane=json.loads(Path(outcome['provider_capture']['lane_receipt_path']).read_bytes())
    assert lane['status']=='FAILED' and len(lane['packed']['files'])==600
    assert 'authority failure' in lane['error']



def test_manifest_storage_failure_reports_durable_status_and_stops(tmp_path,monkeypatch):
    original=evidence._write
    def write(path,raw,*,immutable):
        if path.name=='capture.json' and len(json.loads(raw).get('responses',[]))>=3:
            raise OSError('injected progress write failure')
        return original(path,raw,immutable=immutable)
    monkeypatch.setattr(evidence,'_write',write)
    sdk=SDK()
    with pytest.raises(evidence.CaptureFailure) as raised:collect(tmp_path,sdk)
    refs=raised.value.capture_refs;durable=json.loads(Path(refs['manifest_path']).read_bytes())
    assert refs['status']==durable['status']=='PENDING'
    assert refs['retention_status']=='INCOMPLETE_STORAGE_FAILURE'
    assert len(sdk.calls)==3 and sdk.closed
    assert (tmp_path/'capture.response-0002.json').is_file()  # raw file survives despite progress failure



def test_object_missing_code_keeps_every_physical_sdk_row(tmp_path):
    class MissingCode(SDK):
        def get_market_snapshot(self,codes):
            ret,frame=super().get_market_snapshot(codes)
            frame['code']=frame['code'].astype(object)
            if len([c for c in self.calls if c[0]=='get_market_snapshot'])==1:
                frame.at[1,'code']=pd.NA
            return ret,frame
    with pytest.raises(evidence.CaptureFailure) as raised:collect(tmp_path,MissingCode())
    manifest,responses,ledger,codes=read_refs(raised.value.capture_refs)
    assert manifest['status']=='FAILED'  #599 valid rows are below the unchanged600 gate
    assert len(ledger)==1200  #600plate +600quote rows, all physical refs retained
    invalid=[r for r in ledger if r['disposition']=='INVALID_CODE']
    assert len(invalid)==1 and invalid[0]['batch']==2 and invalid[0]['ordinal']==1
    assert invalid[0]['code'] is None and invalid[0]['reasons']==['missing_or_malformed_code']
    assert codes[1]['code']=='HK.00002' and codes[1]['disposition']=='MISSING_RESPONSE'
    raw=responses[2]['sdk_response'];row=dict(zip(raw['columns'],raw['row_values'][1]))
    assert row['code']=={'$missing_scalar':'NAType'}


def test_precise_provider_exception_is_durable_and_preserved_as_cause(tmp_path):
    class PreciseFailure(SDK):
        def get_market_snapshot(self,codes):
            self.calls.append(('get_market_snapshot',list(codes)))
            raise RuntimeError('precise provider failure details')
    with pytest.raises(evidence.CaptureFailure,match='precise provider failure details') as raised:
        collect(tmp_path,PreciseFailure())
    assert type(raised.value.__cause__) is RuntimeError
    assert str(raised.value.__cause__)=='precise provider failure details'
    manifest,responses,ledger,codes=read_refs(raised.value.capture_refs)
    response=responses[-1]
    assert response['outcome']=='SDK_EXCEPTION'
    assert response['error']=={'type':'RuntimeError','message':'precise provider failure details'}
    assert response['sdk_response']=={'kind':'SDK_EXCEPTION_NO_RESPONSE'}
    assert manifest['error']=='RuntimeError:precise provider failure details'
    assert 'FRAME_SCHEMA_UNUSABLE' not in str(raised.value)
    assert len(ledger)==600 and len(codes)==600


def test_missing_code_then_provider_abort_keeps_all800_rows(tmp_path):
    class MissingThenAbort(SDK):
        def get_market_snapshot(self,codes):
            ret,frame=super().get_market_snapshot(codes)
            frame['code']=frame['code'].astype(object)
            frame.at[1,'code']=pd.NA
            return ret,frame
    with pytest.raises(evidence.CaptureFailure) as raised:
        collect(tmp_path,MissingThenAbort(fail_at=2))
    manifest,responses,ledger,codes=read_refs(raised.value.capture_refs)
    assert manifest['status']=='FAILED' and len(ledger)==800
    quotes=[r for r in ledger if r['method']=='get_market_snapshot']
    assert len(quotes)==200
    assert sum(r['disposition']=='INVALID_CODE' for r in quotes)==1
    assert sum(r['disposition']=='NOT_EVALUATED_CAPTURE_ABORTED' for r in quotes)==199
    assert len(codes)==600 and responses[-1]['outcome']=='SDK_EXCEPTION'
