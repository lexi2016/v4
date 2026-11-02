"""Real Stage downstream publication contract with isolated ledger mutations."""
import json
from pathlib import Path
import pytest
from infrastructure import manager_input_attestation as m
from tests.test_f10_stage_binding import isolated


def rewrite(fixture, mutation):
    root = Path(fixture['config']['research_scheduler_ledger_root'])
    files = list((root/'receipts/live/20261101/2300').glob('*.dispatch-receipt.json'))
    assert len(files) == 1
    payload = json.loads(files[0].read_bytes())
    payload['status'] = 'FAILED'
    payload['selected_workload_ids'].append('fupan_close_materials')
    payload['invoked_workload_ids'].append('fupan_close_materials')
    payload['workload_results'].append({'workload_id':'fupan_close_materials','status':'FAILED','failure_class':'UPSTREAM_NOT_READY',
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False})
    hourly = next(row for row in payload['workload_results'] if row['workload_id']=='hourly_research')
    if mutation == 'hourly_failed': hourly['status'] = 'FAILED'
    if mutation == 'wrong_owner': payload['release_id'] = 'unapproved-owner'
    if mutation == 'wrong_payload_sha': hourly['_authoritative_payload']['payload_sha256'] = '0'*64
    if mutation == 'late_completion': payload['finished_at'] = '2026-11-01T23:59:59.999999+08:00'
    payload['ledger_sha256'] = m.digest(m.encoded({k:v for k,v in payload.items() if k!='ledger_sha256'})[:-1])
    files[0].write_bytes(m.encoded(payload))
    assert (fixture['stage']/'infrastructure/manager_input_attestation.py').read_bytes() == Path(m.__file__).read_bytes()
    return payload


def test_successful_hourly_remains_readable_when_sibling_failed(isolated):
    payload = rewrite(isolated, 'sibling_only')
    value, evidence = isolated['read']()
    assert payload['status']=='FAILED'
    assert value['completion_witness']['run_id']==payload['run_id']
    assert value['completion_witness']['release_id']=='workbench-daily-chain-20261031-r6-main'


@pytest.mark.parametrize('mutation,expected',[
    ('hourly_failed','HOURLY_COMPLETION_WITNESS_MISSING'),
    ('wrong_owner','HOURLY_COMPLETION_WITNESS_MISSING'),
    ('wrong_payload_sha','HOURLY_COMPLETION_WITNESS_MISSING'),
    ('late_completion','HOURLY_COMPLETION_AFTER_AS_OF'),
])
def test_workload_witness_still_requires_exact_hourly_authority_and_cutoff(isolated,mutation,expected):
    rewrite(isolated,mutation)
    with pytest.raises(m.PublicationError,match=expected): isolated['read']()


def hourly_fixture(tmp_path,*,slot='1800',target='20261103',authority_target=None,date='20261102'):
    """Synthetic original-dispatch chain for the next-target slot date contract."""
    owner=tmp_path/'owner'/'app';owner.mkdir(parents=True)
    (owner.parent/'release-manifest.json').write_text(json.dumps({'release_id':'synthetic-owner'}))
    data=tmp_path/'data';ledger=tmp_path/'ledger';artifact=f'research/hourly/archive/{date}/{slot}.json'
    (data/artifact).parent.mkdir(parents=True);payload={'synthetic':True};(data/artifact).write_bytes(m.encoded(payload))
    record={'trade_date':date,'slot':slot,'mode':'LIVE','artifact_ref':artifact,'source_input_sha256':'b'*64,
        'available_at':'2026-11-02T17:59:00+08:00'}
    authority={'schema_version':'v3_5.hourly_research_run.v1','status':'SUCCEEDED','capture_origin':'ORIGINAL_SLOT',
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,'business_date':date,
        'target_date':authority_target or date,'slot':slot,'mode':'LIVE','payload_path':artifact,
        'payload_sha256':m.digest(m.encoded(payload)[:-1]),'external_source_sha256':record['source_input_sha256'],
        'hourly_publication':record}
    run_id='1'*32;name=run_id+'.dispatch-receipt.json'
    receipt={'schema_version':'v3_5.dispatch.v1','business_date':date,'scheduled_date':date,'target_date':target,
        'slot':slot,'mode':'LIVE','run_id':run_id,'receipt_path':f'receipts/live/{date}/{slot}/{name}',
        'release_id':'synthetic-owner','status':'SUCCEEDED','finished_at':'2026-11-02T18:00:30+08:00',
        'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
        'selected_workload_ids':['hourly_research'],'invoked_workload_ids':['hourly_research'],
        'started_workload_ids':['hourly_research'],'succeeded_workload_ids':['hourly_research'],
        'workload_results':[{'workload_id':'hourly_research','status':'SUCCEEDED','exit_code':0,
            'modules':['ops.run_zsxq_hourly_delta','ops.collect_hourly_research_input','ops.run_hourly_research'],
            'production_allowed':False,'buy_gate_updated':False,'orders_sent':False,
            '_authoritative_payload':authority}]}
    receipt['ledger_sha256']=m.digest(m.encoded({k:v for k,v in receipt.items() if k!='ledger_sha256'})[:-1])
    folder=ledger/f'receipts/live/{date}/{slot}';folder.mkdir(parents=True);(folder/name).write_bytes(m.encoded(receipt))
    return record,owner,data,ledger


def test_next_target_slot_accepts_frozen_calendar_target(tmp_path):
    record,owner,data,ledger=hourly_fixture(tmp_path,target='20261103')
    witness=m._scheduler_completion_witness(record,data_root=data,owner_root=owner,ledger_root=ledger,as_of=m.aware('2026-11-02T23:00:00+08:00'))
    assert witness['run_id']=='1'*32 and witness['finished_at']=='2026-11-02T18:00:30+08:00'


@pytest.mark.parametrize('target',['20261102','20261105'])
def test_next_target_slot_rejects_wrong_target(tmp_path,target):
    record,owner,data,ledger=hourly_fixture(tmp_path,target=target)
    with pytest.raises(m.PublicationError,match='HOURLY_COMPLETION_WITNESS_MISSING'):
        m._scheduler_completion_witness(record,data_root=data,owner_root=owner,ledger_root=ledger,as_of=m.aware('2026-11-02T23:00:00+08:00'))


def test_non_next_target_slot_accepts_business_date(tmp_path):
    record,owner,data,ledger=hourly_fixture(tmp_path,slot='1605',target='20261102')
    witness=m._scheduler_completion_witness(record,data_root=data,owner_root=owner,ledger_root=ledger,as_of=m.aware('2026-11-02T23:00:00+08:00'))
    assert witness['run_id']=='1'*32


def test_authority_payload_target_must_remain_business_date(tmp_path):
    record,owner,data,ledger=hourly_fixture(tmp_path,target='20261103',authority_target='20261103')
    with pytest.raises(m.PublicationError,match='HOURLY_COMPLETION_WITNESS_MISSING'):
        m._scheduler_completion_witness(record,data_root=data,owner_root=owner,ledger_root=ledger,as_of=m.aware('2026-11-02T23:00:00+08:00'))
