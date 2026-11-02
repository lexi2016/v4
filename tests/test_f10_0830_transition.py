"""Bounded original 0830 receipt replay; ledger mutations are isolated fixtures."""
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import pytest
from infrastructure import manager_input_attestation as m
import ops.prepare_runtime_governance_publication as publication
from ops.prepare_runtime_governance_publication import (
    embedded_publication_rows,
    frozen_transition_binding,
    omitted_owner_for_stage,
    prepare_owner_proofs,
    validate_transition_publication_set,
    validate_transition_receipt,
)

DATA = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data')
OWNER = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/f10-daily-20261101-c94609b4e5fff848-main/app')
RECEIPT = Path('/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher/receipts/live/20261102/0830/65f6aea1d6414c74bca6274084dd4605.dispatch-receipt.json')
RECEIPT_SHA = 'cc0bf01feed8bb90934f10e1d6596bd686e3ff1a9b7357a36d7849ef3ddf6304'
CALENDAR = OWNER/'contracts/market_calendar_2026.json'
CUTOFF = datetime.fromisoformat('2026-11-02T08:30:21+08:00')
LATE = datetime.fromisoformat('2026-11-02T23:30:00+08:00')
F10_BINDING = {
    'app_root': str(OWNER),
    'release_id': 'f10-daily-20261101-c94609b4e5fff848-main',
    'manifest_sha256': '3f9a184c28884411bfc79872b44e6b2189cd33a44bc8413da0f79b9644a83388',
    'trade_date': '20261102',
}


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


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _publication_folder(root):
    return root/'data/research/hourly/publication/live/20261102'


def _embedded_file(root,slot,value):
    path=_publication_folder(root)/f'{slot}.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')
    return path


def _later_owner(root,slot='2200',*,artifact_raw=None,receipt_raw=None,**overrides):
    trade_date='20261102'
    artifact_raw=(json.dumps({'slot':slot,'fixture':'artifact'}).encode()
                  if artifact_raw is None else artifact_raw)
    receipt_raw=(json.dumps({'schema_version':'v3_5.hourly_research_receipt.v1',
        'archive_date':trade_date,'slot':slot,'mode':'LIVE','production_allowed':False,
        'buy_gate_updated':False,'orders_sent':False}).encode()
        if receipt_raw is None else receipt_raw)
    artifact=root/f'data/research/hourly/live/{trade_date}/{slot}.json'
    receipt=root/f'data/receipts/research/hourly/live/{trade_date}/{slot}.json'
    for path,raw in ((artifact,artifact_raw),(receipt,receipt_raw)):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    payload={'schema_version':'v4.hourly_research_publication.v1','trade_date':trade_date,
        'slot':slot,'mode':'LIVE','RESEARCH_ONLY':True,'production_allowed':False,
        'buy_gate_updated':False,'orders_sent':False,
        'artifact_ref':f'research/hourly/live/{trade_date}/{slot}.json',
        'artifact_sha256':_sha(artifact_raw),
        'receipt_ref':f'receipts/research/hourly/live/{trade_date}/{slot}.json',
        'receipt_sha256':_sha(receipt_raw)}
    payload.update(overrides)
    publication=_publication_folder(root)/f'{slot}.json'
    publication.parent.mkdir(parents=True,exist_ok=True)
    publication.write_text(json.dumps(payload),encoding='utf-8')
    return publication,payload,artifact,receipt


def _validate(root,embedded,paths):
    return validate_transition_publication_set(
        embedded,paths,trade_date='20261102',data_root=root/'data')


def test_later_owner_publication_is_validated_outside_frozen_proof(tmp_path):
    embedded={'0830':[{'slot':'0830','fixture':'embedded'}],
              '0900':[{'slot':'0900','fixture':'embedded'}]}
    for slot,values in embedded.items():_embedded_file(tmp_path,slot,values[0])
    _later_owner(tmp_path)
    paths=sorted(_publication_folder(tmp_path).glob('*.json'))
    diagnostics=_validate(tmp_path,embedded,paths)
    assert [row['slot'] for row in diagnostics]==['2200']
    assert set(embedded)=={'0830','0900'}
    rows=embedded_publication_rows(embedded,paths)
    assert [row[0] for row in rows]==['0830','0900']
    assert all(path.stem!='2200' for _,path,_ in rows)


@pytest.mark.parametrize('field,value',[
    ('schema_version','v3_5.dispatch.v1'),('trade_date','20261103'),
    ('slot','2210'),('mode','BACKFILL'),('RESEARCH_ONLY',False),
    ('production_allowed',True),('buy_gate_updated',True),('orders_sent',True)])
def test_later_owner_publication_rejects_wrong_identity(tmp_path,field,value):
    publication,payload,_,_=_later_owner(tmp_path)
    payload[field]=value;publication.write_text(json.dumps(payload))
    paths=sorted(_publication_folder(tmp_path).glob('*.json'))
    with pytest.raises(ValueError,match='TRANSITION_PUBLICATION_EXTRA_IDENTITY_INVALID'):
        _validate(tmp_path,{},paths)


@pytest.mark.parametrize('field,value',[
    ('artifact_ref','research/hourly/live/20261102/other.json'),
    ('receipt_ref','receipts/research/hourly/live/20261102/other.json'),
    ('artifact_sha256','abc'),('receipt_sha256','0'*63)])
def test_later_owner_publication_rejects_unbound_refs(tmp_path,field,value):
    _later_owner(tmp_path,**{field:value})
    paths=sorted(_publication_folder(tmp_path).glob('*.json'))
    with pytest.raises(ValueError,match='TRANSITION_PUBLICATION_EXTRA_REF_INVALID'):
        _validate(tmp_path,{},paths)


@pytest.mark.parametrize('field,error',[
    ('artifact_sha256','ARTIFACT_SHA_MISMATCH'),('receipt_sha256','RECEIPT_SHA_MISMATCH')])
def test_later_owner_publication_rejects_hash_mismatch(tmp_path,field,error):
    _later_owner(tmp_path,**{field:'0'*64})
    paths=sorted(_publication_folder(tmp_path).glob('*.json'))
    with pytest.raises(ValueError,match='TRANSITION_PUBLICATION_EXTRA_'+error):
        _validate(tmp_path,{},paths)


@pytest.mark.parametrize('which,error',[
    ('artifact','ARTIFACT_MISSING'),('receipt','RECEIPT_MISSING')])
def test_later_owner_publication_requires_cited_files(tmp_path,which,error):
    _,_,artifact,receipt=_later_owner(tmp_path)
    (artifact if which=='artifact' else receipt).unlink()
    paths=sorted(_publication_folder(tmp_path).glob('*.json'))
    with pytest.raises(ValueError,match='TRANSITION_PUBLICATION_EXTRA_'+error):
        _validate(tmp_path,{},paths)


def test_later_owner_receipt_must_echo_slot_date_mode_and_safety(tmp_path):
    for index,(field,value) in enumerate([
            ('slot','2210'),('archive_date','20261103'),('mode','BACKFILL'),
            ('production_allowed',True),('buy_gate_updated',True),('orders_sent',True),
            ('RESEARCH_ONLY',False)]):
        root=tmp_path/str(index)
        publication,payload,_,receipt=_later_owner(root)
        receipt_value=json.loads(receipt.read_bytes());receipt_value[field]=value
        raw=json.dumps(receipt_value).encode();receipt.write_bytes(raw)
        payload['receipt_sha256']=_sha(raw);publication.write_text(json.dumps(payload))
        paths=sorted(_publication_folder(root).glob('*.json'))
        with pytest.raises(ValueError,
                match='TRANSITION_PUBLICATION_EXTRA_RECEIPT_IDENTITY_INVALID'):
            _validate(root,{},paths)


def test_embedded_publication_set_still_requires_regular_exact_files(tmp_path):
    embedded={'0830':[{'slot':'0830'}],'0900':[{'slot':'0900'}]}
    first=_embedded_file(tmp_path,'0830',embedded['0830'][0])
    second=_embedded_file(tmp_path,'0900',embedded['0900'][0])
    assert _validate(tmp_path,embedded,[first,second])==[]
    with pytest.raises(ValueError,match='TRANSITION_PUBLICATION_RECEIPT_SET_MISMATCH'):
        _validate(tmp_path,embedded,[first])
    target=tmp_path/'target.json';target.write_text('{}')
    second.unlink();second.symlink_to(target)
    with pytest.raises(ValueError,match='TRANSITION_PUBLICATION_SET_INVALID'):
        _validate(tmp_path,embedded,[first,second])
    second.unlink();_embedded_file(tmp_path,'0900',embedded['0900'][0])
    odd=_publication_folder(tmp_path)/'08300.json';odd.write_text('{}')
    with pytest.raises(ValueError,match='TRANSITION_PUBLICATION_SET_INVALID'):
        _validate(tmp_path,embedded,[first,second,odd])


def test_old_owner_publication_bytes_still_exact(tmp_path):
    embedded={'0830':[{'slot':'0830'}]}
    path=_embedded_file(tmp_path,'0830',{'slot':'0830','drifted':True})
    assert _validate(tmp_path,embedded,[path])==[]
    with pytest.raises(ValueError,match='TRANSITION_EMBEDDED_PUBLICATION_MISMATCH'):
        embedded_publication_rows(embedded,[path])


def _transition_stage(tmp_path,binding):
    stage=tmp_path/'stage'/'app'
    (stage/'infrastructure').mkdir(parents=True)
    shutil.copyfile(Path(__file__).resolve().parents[1]/'infrastructure/manager_input_attestation.py',
                    stage/'infrastructure/manager_input_attestation.py')
    (stage/'stage_center_tick_config.json').write_text(
        json.dumps({'research_transition_owner_binding':binding}),encoding='utf-8')
    return {'app_root':str(stage),'release_id':'r10-stage','manifest_sha256':'a'*64}


def _frozen_binding(**overrides):
    return {**F10_BINDING,**overrides}


def test_transition_owner_proof_uses_frozen_stage_binding_with_newer_live_main(tmp_path):
    if not OWNER.is_dir() or not (OWNER.parent/'release-manifest.json').is_file():
        pytest.skip('Frozen f10 transition owner unavailable')
    stage_info=_transition_stage(tmp_path,dict(F10_BINDING))
    ledger=tmp_path/'ledger';(ledger/'receipts/live').mkdir(parents=True)
    _later_owner(tmp_path)
    newer_main={'V4_APP_ROOT':'/v4-unified-release-20261102-r7-main/app',
        'V4_RELEASE_ID':'v4-unified-release-20261102-r7-main',
        'V4_RELEASE_MANIFEST_SHA256':'789ab62196867c26375df833762e2e90b1d3cea690ef22b71a60092589f6da77',
        'V4_DISPATCH_LEDGER_ROOT':str(ledger),'V4_DATA_ROOT':str(tmp_path/'data')}
    receipt={'roles':{'stage':stage_info},'live_preimages':{'main':{'environment':newer_main}}}
    proof=publication.transition_owner_proof(receipt,as_of=LATE)
    assert newer_main['V4_RELEASE_ID']!='f10-daily-20261101-c94609b4e5fff848-main'
    assert proof['owner']==F10_BINDING
    assert proof['matching_receipts']==[]
    assert proof['publications']==[]
    assert proof['ledger_root']==str(ledger)


def test_transition_owner_proof_rejects_non_frozen_binding(tmp_path):
    stage_info=_transition_stage(tmp_path,_frozen_binding(release_id='another-main'))
    receipt={'roles':{'stage':stage_info},'live_preimages':{'main':{'environment':{}}}}
    with pytest.raises(ValueError,match='TRANSITION_OWNER_IDENTITY_INVALID'):
        publication.transition_owner_proof(receipt,as_of=LATE)


@pytest.mark.parametrize('name,binding',[
    ('not_dict',[]),
    ('extra_key',{**F10_BINDING,'extra':'x'}),
    ('missing_key',{key:value for key,value in F10_BINDING.items() if key!='release_id'}),
    ('relative_root',_frozen_binding(app_root='relative/app')),
    ('wrong_basename',_frozen_binding(app_root='/tmp/not-app')),
    ('empty_release',_frozen_binding(release_id='')),
    ('nonstring_manifest',_frozen_binding(manifest_sha256=1)),
    ('wrong_release',_frozen_binding(release_id='another-main')),
    ('wrong_manifest',_frozen_binding(manifest_sha256='0'*64)),
    ('wrong_trade_date',_frozen_binding(trade_date='20261101')),
])
def test_frozen_transition_binding_rejects_invalid_or_mutated(name,binding):
    with pytest.raises(ValueError,match='TRANSITION_OWNER_IDENTITY_INVALID'):
        frozen_transition_binding({'research_transition_owner_binding':binding})


def test_frozen_transition_binding_rejects_missing_or_wrong_manifest(tmp_path):
    app=tmp_path/'fake'/'app';app.mkdir(parents=True)
    with pytest.raises(ValueError,match='TRANSITION_OWNER_IDENTITY_INVALID'):
        frozen_transition_binding({'research_transition_owner_binding':_frozen_binding(app_root=str(app))})
    (app.parent/'release-manifest.json').write_text(json.dumps({'release_id':F10_BINDING['release_id']}))
    with pytest.raises(ValueError,match='TRANSITION_OWNER_IDENTITY_INVALID'):
        frozen_transition_binding({'research_transition_owner_binding':_frozen_binding(app_root=str(app))})


def test_frozen_transition_binding_rejects_manifest_release_disagreement(tmp_path,monkeypatch):
    app=tmp_path/'fake2'/'app';app.mkdir(parents=True)
    (app.parent/'release-manifest.json').write_text(json.dumps({'release_id':'another-main'}))
    monkeypatch.setattr(publication,'sha',
        lambda raw: publication.TRANSITION_OWNER['manifest_sha256'])
    with pytest.raises(ValueError,match='TRANSITION_OWNER_IDENTITY_INVALID'):
        frozen_transition_binding({'research_transition_owner_binding':_frozen_binding(app_root=str(app))})


def _owner_receipt(ledger,slot,release_id,app_root,name):
    path=ledger/'receipts/live/20261102'/slot/f'{name}.dispatch-receipt.json'
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps({'release_id':release_id,'app_root':app_root,
                                'status':'SUCCEEDED','slot':slot}),encoding='utf-8')
    return path


def test_prepare_owner_proofs_scans_frozen_binding_despite_newer_current_main(tmp_path,monkeypatch):
    if not OWNER.is_dir() or not (OWNER.parent/'release-manifest.json').is_file():
        pytest.skip('Frozen f10 transition owner unavailable')
    ledger=tmp_path/'ledger'
    _owner_receipt(ledger,'1500',F10_BINDING['release_id'],F10_BINDING['app_root'],'frozen')
    current=_owner_receipt(ledger,'2200','v4-unified-release-20261102-r7-main',
                           '/v4-unified-release-20261102-r7-main/app','current')
    main_env={'V4_DISPATCH_LEDGER_ROOT':str(ledger),
              'V4_RELEASE_ID':'v4-unified-release-20261102-r7-main',
              'V4_APP_ROOT':'/v4-unified-release-20261102-r7-main/app'}
    stage_config={'research_transition_owner_binding':dict(F10_BINDING)}
    expected,proof=omitted_owner_for_stage(stage_config,main_env)
    assert expected==F10_BINDING
    assert proof['release_id']==F10_BINDING['release_id']
    assert [Path(row['path']).name for row in proof['matching_receipts']]==['frozen.dispatch-receipt.json']
    monkeypatch.setattr(publication,'transition_owner_proof',
        lambda *args,**kwargs:{'matching_receipts':proof['matching_receipts']})
    final_proof,transition=prepare_owner_proofs(stage_config,main_env,{},as_of=LATE)
    assert final_proof['admission']=='TRANSITION_OWNER_RETAINED_NOT_ZERO'
    assert transition['matching_receipts']==proof['matching_receipts']
    current_set=publication.omitted_owner_proof(str(ledger),'v4-unified-release-20261102-r7-main',
        '/v4-unified-release-20261102-r7-main/app')['matching_receipts']
    assert [Path(row['path']).name for row in current_set]==['current.dispatch-receipt.json']
    monkeypatch.setattr(publication,'transition_owner_proof',
        lambda *args,**kwargs:{'matching_receipts':current_set})
    with pytest.raises(ValueError,match='TRANSITION_RECEIPT_SET_CHANGED_DURING_PREPARE'):
        prepare_owner_proofs(stage_config,main_env,{},as_of=LATE)


def test_prepare_owner_proofs_without_binding_keeps_current_main_contract(tmp_path):
    ledger=tmp_path/'ledger';(ledger/'receipts/live').mkdir(parents=True)
    main_env={'V4_DISPATCH_LEDGER_ROOT':str(ledger),'V4_RELEASE_ID':'current-main',
              'V4_APP_ROOT':'/current-main/app'}
    proof,transition=prepare_owner_proofs({},main_env,{},as_of=LATE)
    assert proof['matching_receipts']==[]
    assert proof['release_id']=='current-main'
    assert transition is None
    _owner_receipt(ledger,'2200','current-main','/current-main/app','current')
    with pytest.raises(ValueError,match='OMITTED_MAIN_HAS_RECEIPTS_COMPATIBILITY_REQUIRED'):
        prepare_owner_proofs({},main_env,{},as_of=LATE)


def test_prepare_owner_proofs_rejects_non_frozen_binding(tmp_path):
    ledger=tmp_path/'ledger';(ledger/'receipts/live').mkdir(parents=True)
    main_env={'V4_DISPATCH_LEDGER_ROOT':str(ledger),'V4_RELEASE_ID':'current-main',
              'V4_APP_ROOT':'/current-main/app'}
    stage_config={'research_transition_owner_binding':_frozen_binding(release_id='another-main')}
    with pytest.raises(ValueError,match='TRANSITION_OWNER_IDENTITY_INVALID'):
        prepare_owner_proofs(stage_config,main_env,{},as_of=LATE)
