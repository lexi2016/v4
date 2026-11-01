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
