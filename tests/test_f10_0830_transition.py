"""Bounded original 0830 receipt replay; ledger mutations are isolated fixtures."""
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from infrastructure import manager_input_attestation as m
from ops.prepare_runtime_governance_publication import validate_transition_receipt

DATA = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
OWNER = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/f10-daily-20261101-c94609b4e5fff848-main/app')
RECEIPT = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/receipts/live/20261102/0830/65f6aea1d6414c74bca6274084dd4605.dispatch-receipt.json')
RECEIPT_SHA = 'cc0bf01feed8bb90934f10e1d6596bd686e3ff1a9b7357a36d7849ef3ddf6304'
CALENDAR = OWNER/'contracts/market_calendar_2026.json'
CUTOFF = datetime.fromisoformat('2026-11-02T08:30:21+08:00')
LATE = datetime.fromisoformat('2026-11-02T23:30:00+08:00')


def transition_expected(**overrides):
    value={'trade_date':'20261102','release_id':'f10-daily-20261101-c94609b4e5fff848-main','app_root':str(OWNER),'calendar_path':str(CALENDAR)}
    value.update(overrides);return value


def synthetic_receipt(slot,target,business='20261102',scheduled=None,finished_at='2026-11-02T18:00:30+08:00'):
    receipt={'schema_version':'v3_5.dispatch.v1','release_id':'f10-daily-20261101-c94609b4e5fff848-main','app_root':str(OWNER),
        'mode':'LIVE','business_date':business,'scheduled_date':scheduled or business,'target_date':target,
        'slot':slot,'run_id':'0'*32,'status':'SUCCEEDED','finished_at':finished_at}
    receipt['ledger_sha256']=m.digest(m.encoded({k:v for k,v in receipt.items() if k!='ledger_sha256'})[:-1]);return receipt


def receipt_item(root,receipt):
    return {'path':str(Path(root)/'receipts/live/20261102'/receipt['slot']/(receipt['run_id']+'.dispatch-receipt.json'))}


@pytest.fixture
def actual_0830(tmp_path):
    if not RECEIPT.exists() or not OWNER.exists():pytest.skip('Original 0830 evidence unavailable')
    assert m.digest(RECEIPT.read_bytes()) == RECEIPT_SHA
    path=tmp_path/'receipts/live/20261102/0830'/RECEIPT.name
    path.parent.mkdir(parents=True);shutil.copyfile(RECEIPT,path)
    return tmp_path,path


def test_original_0830_full_publication_and_dispatch(actual_0830):
    ledger,_=actual_0830
    value=m.read_hourly_attestation(data_root=DATA,owner_root=OWNER,date='20261102',slot='0830',mode='LIVE',
        as_of=CUTOFF,scheduler_ledger_root=ledger,transition_0830_witness=True)
    assert value['completion_witness']['receipt_sha256']==RECEIPT_SHA
    assert value['completion_witness']['release_id']=='f10-daily-20261101-c94609b4e5fff848-main'
    assert value['available_at']=='2026-11-02T08:30:13.488087+08:00'


@pytest.mark.parametrize('mutation,error', [
    ('wrong_workload','HOURLY_COMPLETION_WITNESS_MISSING'),
    ('wrong_payload_sha','HOURLY_COMPLETION_WITNESS_MISSING'),
    ('late_completion','HOURLY_COMPLETION_AFTER_AS_OF'),
])
def test_0830_dispatch_still_requires_original_authority(actual_0830,mutation,error):
    ledger,path=actual_0830;value=json.loads(path.read_bytes())
    row=next(x for x in value['workload_results'] if x['workload_id']=='zsxq_0830')
    if mutation=='wrong_workload':row['workload_id']='another_workload'
    if mutation=='wrong_payload_sha':row['_authoritative_payload']['payload_sha256']='0'*64
    if mutation=='late_completion':value['finished_at']='2026-11-02T08:30:22+08:00'
    value['ledger_sha256']=m.digest(m.encoded({k:v for k,v in value.items() if k!='ledger_sha256'})[:-1]);path.write_bytes(m.encoded(value))
    with pytest.raises(m.PublicationError,match=error):
        m.read_hourly_attestation(data_root=DATA,owner_root=OWNER,date='20261102',slot='0830',mode='LIVE',
            as_of=CUTOFF,scheduler_ledger_root=ledger,transition_0830_witness=True)


def test_transition_witness_rejects_wrong_slot_and_owner(actual_0830,tmp_path):
    ledger,_=actual_0830
    with pytest.raises(m.PublicationError,match='SCOPE_INVALID'):
        m._scheduler_completion_witness({'trade_date':'20261102','slot':'0900','mode':'LIVE'},data_root=DATA,
            owner_root=OWNER,ledger_root=ledger,as_of=CUTOFF,transition_0830_witness=True)
    wrong=tmp_path/'wrong'/'app';wrong.mkdir(parents=True)
    (wrong.parent/'release-manifest.json').write_text('{}')
    with pytest.raises(m.PublicationError,match='OWNER_INVALID'):
        m._scheduler_completion_witness({'trade_date':'20261102','slot':'0830','mode':'LIVE'},data_root=DATA,
            owner_root=wrong,ledger_root=ledger,as_of=CUTOFF,transition_0830_witness=True)


@pytest.mark.parametrize('field,value,error', [
    ('business_date','20261103','IDENTITY_INVALID'),
    ('release_id','wrong-owner','IDENTITY_INVALID'),
    ('finished_at','2026-11-02T08:30:22+08:00','TIME_INVALID'),
])
def test_receipt_set_proof_rejects_wrong_identity_or_time(actual_0830,field,value,error):
    _,path=actual_0830;receipt=json.loads(path.read_bytes());expected=transition_expected()
    item={'path':str(path)}
    validate_transition_receipt(receipt,item,expected,CUTOFF)
    receipt[field]=value
    receipt['ledger_sha256']=m.digest(m.encoded({k:v for k,v in receipt.items() if k!='ledger_sha256'})[:-1])
    with pytest.raises(ValueError,match=error):validate_transition_receipt(receipt,item,expected,CUTOFF)


def test_receipt_target_follows_pinned_next_trade_day(tmp_path):
    for slot,target in (('1800','20261103'),('1605','20261102'),('1540','20261102')):
        receipt=synthetic_receipt(slot,target)
        validate_transition_receipt(receipt,receipt_item(tmp_path,receipt),transition_expected(),LATE)


@pytest.mark.parametrize('slot,target', [('1800','20261105'),('1605','20261103'),('1800','20261102')])
def test_receipt_rejects_target_outside_exact_contract(tmp_path,slot,target):
    receipt=synthetic_receipt(slot,target)
    with pytest.raises(ValueError,match='IDENTITY_INVALID'):
        validate_transition_receipt(receipt,receipt_item(tmp_path,receipt),transition_expected(),LATE)


def test_receipt_rejects_business_scheduled_mismatch(tmp_path):
    receipt=synthetic_receipt('1800','20261103',scheduled='20261103')
    with pytest.raises(ValueError,match='IDENTITY_INVALID'):
        validate_transition_receipt(receipt,receipt_item(tmp_path,receipt),transition_expected(),LATE)


@pytest.mark.parametrize('missing_key', [False,True])
def test_receipt_rejects_missing_pinned_calendar(tmp_path,missing_key):
    expected=transition_expected(calendar_path=str(tmp_path/'missing/market_calendar_2026.json'))
    if missing_key:expected.pop('calendar_path')
    receipt=synthetic_receipt('1800','20261103')
    with pytest.raises(ValueError,match='TRANSITION_CALENDAR_MISSING'):
        validate_transition_receipt(receipt,receipt_item(tmp_path,receipt),expected,LATE)
