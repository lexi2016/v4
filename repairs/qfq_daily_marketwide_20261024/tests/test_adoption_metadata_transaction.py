"""Temporary-file transaction tests using the actual original publisher/gate."""
import copy
import importlib.util
import json
from pathlib import Path
import sys

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
W = Path('/Users/lexi/.codex/worktrees/local-panel-history-20261024/v4_app')
sys.path.insert(0, str(W))
from ops import research_panel_qfq as q

spec = importlib.util.spec_from_file_location('adoption_helper', HERE/'adopt_existing_candidate.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


def ref(path):
    return dict(path=str(path), sha256=a.digest(path))


def save(path, value):
    q._json(path, value)
    return ref(path)


@pytest.fixture
def case(tmp_path):
    root = tmp_path/'data'
    cache = root/'runtime/cache/data_layer_daily_formula_increment_update_v1'
    cache.mkdir(parents=True)
    stage = tmp_path/'staged'
    stage.mkdir()
    backup = tmp_path/'backups'
    backup.mkdir()
    source_file = tmp_path/'provider.csv'
    source_file.write_text('original observations\n')
    snapshot = dict(asof_date=20261023, source_files=[ref(source_file)])
    snapshot_ref = save(tmp_path/'snapshot.json', snapshot)
    keys = ('driver_sha256','formula_sha256','adapter_sha256','input_adapter_sha256',
            'factor_cache_sha256','tdx_adapter_sha256','user_formula_sha256','field_contract_sha256')
    identity = {k: k for k in keys}
    identity.update(input_sha256=q.canonical_sha(snapshot), generation_id='accepted_candidate')
    rows = [dict(ts_code=c, trade_date=d, BBI=1., zge_white_line=2., zge_yellow_line=3., J=4., B1=0, B2=1, B3=0)
            for c in ('002612.SZ','001283.SZ') for d in (20261022,20261023)]
    pointers, candidates = {}, {}
    for role in ('selector','backtest'):
        pointers[role] = root/({'selector':'data_layer_interface_current/CURRENT_SELECTOR_READY_PANEL.txt',
                                'backtest':'backtest_panel_interface_current/CURRENT_BACKTEST_BASE_PANEL.txt'}[role])
        old = tmp_path/f'old_{role}.parquet'
        old.write_bytes(b'old accepted baseline '+role.encode())
        q._write(pointers[role], (str(old)+'\n').encode())
        panel = tmp_path/f'new_{role}.parquet'
        table = pa.Table.from_pylist(rows).replace_schema_metadata({q.META_KEY:json.dumps(identity).encode()})
        pq.write_table(table,panel)
        candidates[role] = ref(panel)
    original = dict(asof_date=20261023,input_sha256='old',observed_at='original actual observation time',
                    required_dates={c:[20261022,20261023] for c in ('002612.SZ','001283.SZ')},
                    source_files=[ref(source_file)], rows=[{**r,**{k:format(r[k],'.3f') for k in ('BBI','zge_white_line','zge_yellow_line','J')}} for r in rows])
    original_ref = save(backup/'original_oracle.json',original)
    oracle = {**original,'input_sha256':identity['input_sha256'],'derived_binding_only':True,'new_observation':False}
    receipt = dict(status='PASS_FUTU_DISPLAY_ORACLE',asof_date=20261023,code_binding=q._code_binding(identity),
                   input_sha256=identity['input_sha256'],candidate_sha256={r:v['sha256'] for r,v in candidates.items()})
    receipt_ref=save(tmp_path/'independent_parity_receipt.json',receipt)
    convention=dict(status='PASS',reviewer_id='independent',initial_asof_date=20261023,
                    convention='original_convention',code_binding=q._code_binding(identity),initial_oracle_receipt=receipt_ref)
    next_baseline=dict(schema='qfq_expected_current_v1',roles={r:dict(pointer_path=str(pointers[r]),
        pointer_sha256=__import__('hashlib').sha256((v['path']+'\n').encode()).hexdigest(),
        target_path=v['path'],target_sha256=v['sha256']) for r,v in candidates.items()})
    afters={'qfq_adjustment_input.json':snapshot,'qfq_readiness.json':dict(generation_id=identity['generation_id']),
            'qfq_expected_current.json':next_baseline,'qfq_futu_oracle.json':oracle,'qfq_convention_acceptance.json':convention}
    metadata=[]
    for i,(name,value) in enumerate(afters.items()):
        target=cache/name
        before=None
        if i != 1:  # Exercise originally absent metadata on rollback.
            target.write_bytes(('old '+name+'\n').encode())
            b=backup/name;b.write_bytes(target.read_bytes());before=ref(b)
        metadata.append(dict(path=str(target),before=before,after=save(stage/name,value)))
    config=dict(data_root=str(root),pointers={r:str(p) for r,p in pointers.items()},candidates=candidates,
                snapshot=snapshot_ref,identity=identity,target=20261023,convention='original_convention',
                expected_baseline=q.baseline_binding(pointers),metadata=metadata,original_oracle_backup=original_ref,
                publisher_source=ref(Path(q.__file__)),publisher_sha256=a.digest(q.__file__),code_refs=[ref(Path(q.__file__))])
    return dict(config=config,root=tmp_path,pointers=pointers)


def freeze(case):
    root=case['root']; config_ref=save(root/'plan.json',case['config'])
    review_ref=save(root/'review.json',dict(decision='PASS_DEFAULT_CANDIDATE_ADOPTION_INTEGRATION',
        writer_id='writer',reviewer_id='independent',plan_sha256=config_ref['sha256'],helper_sha256=a.digest(a.__file__)))
    start_ref=save(root/'start.json',dict(event_type='RUN_STARTED',decision='RUN_STARTED',execution_id='test_execution'))
    go_ref=save(root/'go.json',dict(decision='GO_DEFAULT_CANDIDATE_ADOPTION',review_ref=review_ref,
        execution_id='test_execution',plan_sha256=config_ref['sha256']))
    return config_ref,review_ref,go_ref,start_ref,root/'outer_journal.json'


def assert_original(case):
    for r,p in case['pointers'].items():
        assert p.read_text().strip()==str(case['root']/f'old_{r}.parquet')
    for m in case['config']['metadata']:
        assert a.current(m['path'])==a.payload(m['before'])


def test_success_reuses_original_gate_and_pair(case):
    args=freeze(case)
    assert a.adopt(q,*args)['status']=='COMMITTED'
    for r,p in case['pointers'].items(): assert p.read_text().strip()==case['config']['candidates'][r]['path']
    assert json.loads((case['root']/'publish_pair.json').read_text())['status']=='COMMITTED'


@pytest.mark.parametrize('fail_at',['metadata_first','metadata_last','selector','backtest','after_pair'])
def test_failure_restores_metadata_and_both_pointers(case,monkeypatch,fail_at):
    args=freeze(case);original=q._write;fired=False
    metas=case['config']['metadata']
    def write(path,data):
        nonlocal fired
        target={'metadata_first':Path(metas[0]['path']),'metadata_last':Path(metas[-1]['path']),
                'selector':case['pointers']['selector'],'backtest':case['pointers']['backtest'],
                'after_pair':case['root']/'outer_journal.json'}[fail_at]
        should_fail=(Path(path)==target and (fail_at!='after_pair' or b'"status": "COMMITTED"' in data))
        if should_fail and not fired: fired=True;raise OSError('injected precise boundary failure')
        return original(path,data)
    monkeypatch.setattr(q,'_write',write)
    with pytest.raises(OSError,match='injected'):a.adopt(q,*args)
    assert fired;assert_original(case)
    assert json.loads(args[-1].read_text())['status']=='ROLLED_BACK'


def test_stale_baseline_rejected_without_writes(case):
    args=freeze(case);other=case['root']/'third_party.parquet';other.write_bytes(b'third party')
    case['pointers']['selector'].write_text(str(other)+'\n')
    with pytest.raises(q.QfqGateError,match='EXPECTED_OLD'):a.adopt(q,*args)
    assert not args[-1].exists()
    for m in case['config']['metadata']:assert a.current(m['path'])==a.payload(m['before'])


def test_metadata_third_party_is_preserved_on_rollback(case,monkeypatch):
    args=freeze(case);original=q.publish_pair
    victim=Path(case['config']['metadata'][0]['path'])
    def conflict(*x,**kw):
        victim.write_bytes(b'third party metadata')
        raise OSError('third party injected')
    monkeypatch.setattr(q,'publish_pair',conflict)
    with pytest.raises(a.AdoptionConflict,match='METADATA_OWNERSHIP'):a.adopt(q,*args)
    assert victim.read_bytes()==b'third party metadata'
    assert json.loads(args[-1].read_text())['status']=='ROLLBACK_REQUIRED'


def test_source_closure_overlap_rejected(case):
    c=case['config'];snapshot=json.loads(a.source(c['snapshot']).read_text())
    snapshot['source_files'].append(dict(path=c['metadata'][0]['path'],sha256='not needed for overlap rejection'))
    c['snapshot']=save(case['root']/'overlap.json',snapshot)
    with pytest.raises(a.AdoptionConflict,match='SOURCE_CLOSURE'):a.adopt(q,*freeze(case))
    assert_original(case)


def test_original_oracle_observation_change_rejected(case):
    m=next(m for m in case['config']['metadata'] if Path(m['path']).name=='qfq_futu_oracle.json')
    p=Path(m['after']['path']);v=json.loads(p.read_text());v['observed_at']='invented new observation';m['after']=save(p,v)
    with pytest.raises(a.AdoptionConflict,match='OBSERVATION_CHANGED'):a.adopt(q,*freeze(case))
    assert_original(case)


def test_source_closure_byte_drift_rejected_before_writes(case):
    args=freeze(case)
    (case['root']/'provider.csv').write_bytes(b'changed provider response')
    with pytest.raises(a.AdoptionConflict,match='IMMUTABLE_REF_CONFLICT'):a.adopt(q,*args)
    assert not args[-1].exists()
    assert_original(case)


def test_original_release_gate_rejects_value_mismatch(case):
    # Change both retained observations consistently; actual candidate parity must still fail.
    c=case['config'];p=Path(c['original_oracle_backup']['path']);v=json.loads(p.read_text());v['rows'][0]['BBI']='9.999'
    c['original_oracle_backup']=save(p,v)
    m=next(m for m in c['metadata'] if Path(m['path']).name=='qfq_futu_oracle.json')
    p=Path(m['after']['path']);v.update(input_sha256=c['identity']['input_sha256']);m['after']=save(p,v)
    with pytest.raises(q.QfqGateError,match='PROVIDER_CONVENTION_CONFLICT'):a.adopt(q,*freeze(case))
    assert_original(case)


def test_approval_is_bound_to_exact_plan(case):
    args=list(freeze(case));p=Path(args[2]['path']);v=json.loads(p.read_text());v['plan_sha256']='other';args[2]=save(p,v)
    with pytest.raises(a.AdoptionConflict,match='CONTROLLER_GO'):a.adopt(q,*args)
    assert_original(case)


def test_interrupted_transaction_recovery(case,monkeypatch):
    args=freeze(case);original=q._write
    def crash(path,data):
        if Path(path)==case['pointers']['backtest']:raise KeyboardInterrupt('crash')
        return original(path,data)
    monkeypatch.setattr(q,'_write',crash)
    with pytest.raises(KeyboardInterrupt):a.adopt(q,*args)
    monkeypatch.setattr(q,'_write',original)
    assert a.recover(q,args[0],args[-1])=='ROLLED_BACK'
    assert_original(case)
