"""SYNTHETIC membership identities are never evidence about real securities."""
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import hashlib
import json
import pytest
from v4.manager_research import connect_selection as cs
from domains import manager_research_evidence as original

CTX = {'plan_trade_date':'20260930','research_cutoff':'2026-09-30T15:00:00+08:00'}
FLAGS = {'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}


def test_unbound_stays_closed_without_reader_call(monkeypatch):
    monkeypatch.setattr(original,'read_universe_evidence',lambda *a,**k: pytest.fail('reader must not run'))
    result=cs.read_scope(CTX)
    assert result['codes']==[] and result['gaps']==['HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND']


def test_explicit_owner_pins_forwarded_not_clock(monkeypatch,tmp_path):
    owner=tmp_path/'owner';owner.mkdir()
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_ROOT',str(tmp_path))
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_ROOT',str(owner))
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_SHA256','a'*64)
    calls=[]
    def read(root,date,**kw):
        calls.append((root,date,kw))
        return SimpleNamespace(codes=['HK.01234'],source={
            'source_date':date,'market':'HK_CONNECT','role':'HK_CONNECT_FULL_MARKET_AUTHORITY',
            'observed_at':'2026-09-30T12:00:00+08:00',
            'available_at':'2026-09-30T15:01:00+08:00','sha256':'b'*64})
    monkeypatch.setattr(original,'read_universe_evidence',read)
    first=cs.read_scope(CTX);second=cs.read_scope(CTX)
    assert first['status']=='OWNER_VERIFIED'
    assert calls[0][2]=={'authority_owner_root':owner,'authority_owner_sha256':'a'*64}
    assert first['source']['available_at']=='2026-09-30T15:01:00+08:00'
    assert first['identity']==second['identity']
    assert cs._scope_error(first,'20260930') is None


@pytest.mark.parametrize('root,sha',[(None,'a'*64),('/tmp/owner',None),('/tmp/owner','x'*64),('relative','a'*64)])
def test_incomplete_or_invalid_pair_never_calls_reader(monkeypatch,tmp_path,root,sha):
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_ROOT',str(tmp_path))
    if root is not None:monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_ROOT',root)
    if sha is not None:monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_SHA256',sha)
    called=[]
    monkeypatch.setattr(original,'read_universe_evidence',lambda *a,**kw:called.append(1))
    r=cs.read_scope(CTX)
    assert called==[]
    assert r['codes']==[] and r['status']=='CANNOT_CONFIRM'
    assert r['gaps']==['HK_CONNECT_TARGET_AUTHORITY_OWNER_BINDING_INVALID']


def test_owner_symlink_parent_rejected(monkeypatch,tmp_path):
    real=tmp_path/'real';(real/'owner').mkdir(parents=True)
    (tmp_path/'link').symlink_to(real,target_is_directory=True)
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_ROOT',str(tmp_path))
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_ROOT',str(tmp_path/'link/owner'))
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_OWNER_SHA256','a'*64)
    called=[]
    monkeypatch.setattr(original,'read_universe_evidence',lambda *a,**kw:called.append(1))
    assert cs.read_scope(CTX)['gaps']==['HK_CONNECT_TARGET_AUTHORITY_OWNER_BINDING_INVALID']
    assert called==[]


def test_no_explicit_pair_keeps_r1_local_reader_mode(monkeypatch,tmp_path):
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_ROOT',str(tmp_path));calls=[]
    def read(*a,**kw):
        calls.append(kw);raise original.EvidenceError('HK_CONNECT_EXACT_UNIVERSE_MISSING')
    monkeypatch.setattr(original,'read_universe_evidence',read)
    r=cs.read_scope(CTX)
    assert calls==[{}] and r['codes']==[]
    assert 'HK_CONNECT_EXACT_UNIVERSE_MISSING' in r['gaps'][0]


def test_original_error_keeps_structured_diagnostic(monkeypatch,tmp_path):
    monkeypatch.setenv('V4_MANAGER_UNIVERSE_ROOT',str(tmp_path))
    def read(*a,**kw):
        raise original.EvidenceError('HK_UNIVERSE_OWNER_SHA_MISMATCH',layer='UNIVERSE_OWNER',kind='CONFLICT',field='source_code_sha256')
    monkeypatch.setattr(original,'read_universe_evidence',read)
    r=cs.read_scope(CTX)
    assert r['authority_diagnostic']['code']=='HK_UNIVERSE_OWNER_SHA_MISMATCH'
    assert r['codes']==[]


@pytest.fixture
def synthetic_authority(tmp_path):
    # Original owner writer helpers only construct a synthetic test fixture.
    # No ensure_hk_connect_universe() or provider calls are made.
    app=Path(original.__file__).resolve().parents[1]
    owner_file=app/'stage_center/hk_universe_preflight.py'
    sha=hashlib.sha256(owner_file.read_bytes()).hexdigest()
    owner=original.load_universe_owner(app,sha)
    root=tmp_path/'synthetic_authority';root.mkdir()
    date='20260930';codes=['HK.'+str(i).zfill(5) for i in range(1,652)]
    plates={p:codes[:] for p in owner.HKCONNECT_PLATE_CODES}
    payload=owner._manifest_payload(date,plates,codes,'2026-09-30T10:00:00+08:00')
    artifact=root/f'universes/{date}/HK_CONNECT_FULL_MARKET.json'
    artifact.parent.mkdir(parents=True);artifact.write_bytes(owner._canonical_json_line(payload))
    chain=owner._authority_payloads(root,date,payload,source_materialization='FRESH_FUTU_ARTIFACT',
         origin_claim='NOT_ASSERTED_REQUIRES_PARENT_SCHEDULER_RECEIPT')
    for key,kind in [('manifest_relative','manifest'),('receipt_relative','receipt'),('current_relative','current')]:
        f=root/chain['paths'][key];f.parent.mkdir(parents=True,exist_ok=True);f.write_bytes(chain[kind+'_bytes'])
    return root,app,sha,owner,chain


def test_original_reader_checks_complete_synthetic_chain_readonly(synthetic_authority):
    root,app,sha,owner,chain=synthetic_authority
    before={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}
    r=original.read_universe_evidence(root,'20260930',authority_owner_root=app,authority_owner_sha256=sha,
        clock=lambda:datetime.fromisoformat('2026-09-30T11:00:00+08:00'))
    assert len(r.codes)==651
    assert r.source['available_at']=='2026-09-30T11:00:00+08:00'
    assert before=={str(p.relative_to(root)):p.read_bytes() for p in root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('change',['date','owner_sha','manifest','receipt_missing','count','ordinary_master'])
def test_original_reader_rejects_invalid_authority(synthetic_authority,change):
    root,app,sha,owner,chain=synthetic_authority;date='20260930'
    artifact=root/chain['paths']['artifact_relative']
    if change=='date':date='20260929'
    if change=='owner_sha':sha='0'*64
    if change=='manifest':(root/chain['paths']['manifest_relative']).write_text('{}')
    if change=='receipt_missing':(root/chain['paths']['receipt_relative']).unlink()
    if change=='count':
        obj=json.loads(artifact.read_bytes());obj['codes'].pop();artifact.write_bytes(owner._canonical_json_line(obj))
    if change=='ordinary_master':artifact.write_text(json.dumps({'trade_date':date,'codes':['HK.00700'],'market':'HK'}))
    with pytest.raises(original.EvidenceError):
        original.read_universe_evidence(root,date,authority_owner_root=app,authority_owner_sha256=sha,
            clock=lambda:datetime.fromisoformat('2026-09-30T11:00:00+08:00'))
