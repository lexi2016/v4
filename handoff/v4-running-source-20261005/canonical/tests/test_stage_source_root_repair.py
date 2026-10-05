"""Synthetic pool trios with real V4 readers, commit, CAS and locks. No network."""
import hashlib
import inspect
import json
from pathlib import Path
from unittest.mock import patch
import pytest
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.stage_acquisition_universe_commit import StageAcquisitionUniverseCommit, EvidenceIdentity
from stage_center.input_contracts import REQUIRED_A_STAGE_POOL_IDS, a_pool_contract
from ops import materialize_stage_acquisition_universe as mat
from ops._run_stage_center_nodes_parts.node_entry import _materialize_candidate_body

DATE = '20260928'
RELEASE = 'synthetic-source-root-repair'

def pools(root, count=2):
    root.mkdir(parents=True, exist_ok=True)
    store = PreselectionPoolStore(root)
    for idx,pool_id in enumerate(REQUIRED_A_STAGE_POOL_IDS[:count]):
        status,producer,role = a_pool_contract(pool_id)
        payload = dict(schema_version='v3_5.preselection_pool.v1',trade_date=DATE,pool_id=pool_id,
            display_name=pool_id,market='A',status=status,producer_id=producer,source_role=role,
            source_path='synthetic-only/'+pool_id+'.json',source_sha256=hashlib.sha256(pool_id.encode()).hexdigest(),
            rows=[dict(pool_id=pool_id,symbol=f'A.{idx+1:06d}',market='A')],cannot_confirm=[],
            production_allowed=False,buy_gate_updated=False,orders_sent=False)
        store.materialize(payload)
    return store

def require_root_api():
    assert 'preselection_source_root' in inspect.signature(mat.materialize_stage_acquisition_universe).parameters

def scope():
    return {'Path':Path,'Mapping':dict,'PREP_NODE_ID':'PREP_0915',
        '_calendar_gate':lambda *a,**k: {'status':'ELIGIBLE'},
        '_candidate_current_is_verified':lambda *a,**k:None,
        '_safe_flags':lambda:dict(production_allowed=False,buy_gate_updated=False,orders_sent=False)}

def test_prepare_forwards_explicit_source_not_candidate(tmp_path):
    src=tmp_path/'source';src.mkdir();dst=tmp_path/'target';calls=[]
    def materializer(root,date,**kwargs):
        calls.append((root,date,kwargs));return dict(status='READY',trade_date=date)
    out=_materialize_candidate_body(scope(),dict(candidate_acquisition_root=str(dst),preselection_source_root=str(src)),DATE,materializer=materializer)
    assert calls[0][2].get('preselection_source_root') == src
    assert calls[0][0] == dst and out['status']=='READY'

def test_prepare_does_not_swallow_unsupported_keyword_and_retry(tmp_path):
    src=tmp_path/'src';src.mkdir();dst=tmp_path/'dst';calls=[]
    def old(root,date): calls.append(1);return {'status':'READY'}
    out=_materialize_candidate_body(scope(),dict(candidate_acquisition_root=str(dst),preselection_source_root=str(src)),DATE,materializer=old)
    assert out['status']=='CANNOT_CONFIRM' and not calls

def test_explicit_root_publish_uses_source_and_writes_only_target(tmp_path):
    require_root_api();src=tmp_path/'src';dst=tmp_path/'dst';pools(src)
    before={str(p.relative_to(src)):p.read_bytes() for p in (src/'preselection_pools').rglob('*') if p.is_file()}
    result=mat.materialize_stage_acquisition_universe(dst,DATE,preselection_source_root=src,release_id=RELEASE)
    assert result['artifact']['codes']==['A.000001','A.000002']
    assert result['artifact']['preselection_source_root']==str(src)
    assert not (dst/'preselection_pools').exists() and not (src/'current').exists()
    assert before=={str(p.relative_to(src)):p.read_bytes() for p in (src/'preselection_pools').rglob('*') if p.is_file()}
    again=mat.materialize_stage_acquisition_universe(dst,DATE,preselection_source_root=src,release_id=RELEASE)
    assert again['idempotent'] is True

def test_explicit_missing_source_never_falls_back_to_target(tmp_path):
    require_root_api();dst=tmp_path/'dst';pools(dst)
    with pytest.raises((ValueError,OSError)):
        mat.materialize_stage_acquisition_universe(dst,DATE,preselection_source_root=tmp_path/'missing',release_id=RELEASE)
    assert not (dst/'current').exists()

def test_legacy_same_root_still_publishes(tmp_path):
    pools(tmp_path);out=mat.materialize_stage_acquisition_universe(tmp_path,DATE,release_id=RELEASE)
    assert out['artifact']['row_count']==2

def test_explicit_empty_relative_symlink_source_rejected(tmp_path):
    require_root_api();pools(tmp_path/'good');(tmp_path/'alias').symlink_to(tmp_path/'good',target_is_directory=True)
    for value in ['',Path('relative'),tmp_path/'alias']:
        with pytest.raises((ValueError,OSError)):
            mat.materialize_stage_acquisition_universe(tmp_path/'out',DATE,preselection_source_root=value,release_id=RELEASE)

def test_corrupt_one_lane_does_not_erase_valid_other_lane(tmp_path):
    require_root_api();src=tmp_path/'src';store=pools(src)
    artifact,_=store._relative(DATE,REQUIRED_A_STAGE_POOL_IDS[0]);(src/artifact).write_text('{}')
    result=mat.materialize_stage_acquisition_universe(tmp_path/'dst',DATE,preselection_source_root=src,release_id=RELEASE)
    assert result['artifact']['codes']==['A.000002']
    assert result['artifact']['pool_diagnostics'][REQUIRED_A_STAGE_POOL_IDS[0]]

def test_source_changed_between_proposal_and_locked_read_is_rejected(tmp_path):
    require_root_api();import infrastructure.stage_acquisition_universe_commit as cm
    src=tmp_path/'src';store=pools(src);dst=tmp_path/'dst'
    original=cm._revalidate_physical_snapshot
    def mutate(root,date,expected,*,lock_lease):
        artifact,_=store._relative(DATE,REQUIRED_A_STAGE_POOL_IDS[0]);(src/artifact).write_text('{}')
        return original(root,date,expected,lock_lease=lock_lease)
    with patch.object(cm,'_revalidate_physical_snapshot',mutate),pytest.raises(ValueError,match='snapshot changed'):
        mat.materialize_stage_acquisition_universe(dst,DATE,preselection_source_root=src,release_id=RELEASE)
    assert not (dst/'current').exists()

def test_explicit_same_root_does_not_break_legacy_current(tmp_path):
    require_root_api();pools(tmp_path)
    old=mat.materialize_stage_acquisition_universe(tmp_path,DATE,release_id=RELEASE)
    now=mat.materialize_stage_acquisition_universe(tmp_path,DATE,preselection_source_root=tmp_path,release_id=RELEASE)
    assert now['idempotent'] is True and old['artifact']==now['artifact']

def test_both_native_locks_remain_held_during_publication(tmp_path,monkeypatch):
    require_root_api()
    from infrastructure.interprocess_lock import owned_interprocess_lock
    src=tmp_path/'z_source';dst=tmp_path/'a_target';pools(src)
    original=StageAcquisitionUniverseCommit._write; checks=[]
    def checked(secure,relative,value):
        for root in (src,dst):
            with pytest.raises(ValueError):
                with owned_interprocess_lock(root/'.import.lock',timeout_seconds=.02,timeout_message='synthetic-lock-contention'):pass
            checks.append(str(root))
        return original(secure,relative,value)
    monkeypatch.setattr(StageAcquisitionUniverseCommit,'_write',staticmethod(checked))
    mat.materialize_stage_acquisition_universe(dst,DATE,preselection_source_root=src,release_id=RELEASE)
    assert len(checks)>=6

def test_wrong_source_binding_in_proposal_is_rejected(tmp_path):
    require_root_api();src=tmp_path/'src';pools(src)
    artifact=mat.build_artifact(tmp_path/'dst',DATE,preselection_source_root=src)
    artifact['preselection_source_root']=str(tmp_path/'wrong')
    identity=EvidenceIdentity(owner_id='V3_5_STAGE_CENTER',producer_id='ops.materialize_stage_acquisition_universe',release_id=RELEASE,lane_id='A_SHARE_STAGE_ACQUISITION')
    with pytest.raises(ValueError,match='root binding mismatch'):
        StageAcquisitionUniverseCommit(tmp_path/'dst',preselection_source_root=src).publish(artifact,identity=identity)
    assert not (tmp_path/'dst/current').exists()

def test_cross_root_successor_uses_same_source_and_raw_current_cas(tmp_path):
    require_root_api()
    from infrastructure.data_store import _sha256,_canonical_bytes
    from infrastructure.stage_acquisition_universe_commit import STRICT_ROLE
    src=tmp_path/'src';dst=tmp_path/'dst';store=pools(src,count=4)
    mat.materialize_stage_acquisition_universe(dst,DATE,preselection_source_root=src,release_id=RELEASE)
    current=dst/f'current/{DATE}/{STRICT_ROLE}/current.json';token=hashlib.sha256(current.read_bytes()).hexdigest()
    pool_id=REQUIRED_A_STAGE_POOL_IDS[3];art,rec=store._relative(DATE,pool_id)
    payload=json.loads((src/art).read_text());payload['rows'].append(dict(pool_id=pool_id,symbol='A.000005',market='A'))
    digest=_sha256(payload);receipt=store._receipt(trade_date=DATE,pool_id=pool_id,artifact_path=art,artifact_sha256=digest,payload=payload)
    manifest_path=src/f'preselection_pools/{DATE}/manifest.json';manifest=json.loads(manifest_path.read_text());manifest[pool_id]=digest
    (src/art).write_bytes(_canonical_bytes(payload));(src/rec).write_bytes(_canonical_bytes(receipt));manifest_path.write_bytes(_canonical_bytes(manifest))
    out=mat.materialize_stage_acquisition_universe_successor(dst,DATE,preselection_source_root=src,release_id=RELEASE,expected_current_sha256=token,reason='synthetic append')
    assert out['artifact']['codes']==['A.000001','A.000002','A.000003','A.000004','A.000005']
    assert hashlib.sha256(current.read_bytes()).hexdigest()!=token
    with pytest.raises(ValueError):
        mat.materialize_stage_acquisition_universe_successor(dst,DATE,preselection_source_root=src,release_id=RELEASE,expected_current_sha256='0'*64,reason='synthetic wrong token')

def test_explicit_overlapping_roots_rejected(tmp_path):
    require_root_api();pools(tmp_path/'source')
    with pytest.raises(ValueError,match='overlap'):
        mat.materialize_stage_acquisition_universe(tmp_path/'source/child',DATE,preselection_source_root=tmp_path/'source',release_id=RELEASE)

def test_cli_forwards_source_root(monkeypatch,tmp_path,capsys):
    require_root_api();calls=[]
    def spy(root,date,**kw):calls.append((root,date,kw));return {'status':'SYNTHETIC_NOT_PRODUCTION'}
    monkeypatch.setattr(mat,'materialize_stage_acquisition_universe',spy)
    assert mat.main(['--data-root',str(tmp_path/'dst'),'--preselection-source-root',str(tmp_path/'src'),'--trade-date',DATE,'--release-id',RELEASE])==0
    assert calls[0][2]['preselection_source_root']==tmp_path/'src'
