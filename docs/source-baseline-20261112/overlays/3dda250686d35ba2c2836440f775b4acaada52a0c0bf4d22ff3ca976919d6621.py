"""Real evidence canaries; fixtures are copied unchanged from the supplied ZIP."""
from pathlib import Path
import csv
import copy
import hashlib
import json
import os
import pytest

FIXTURES = Path(os.environ.get('V4_0918_FIXTURES', Path(__file__).parent / 'fixtures' / 'history_0918'))
FLAGS = {'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}

def missing(store, pool_id='a_d1_premarket_pool'):
    from domains.preselection_materializer import build_expected_missing_pool
    payload=build_expected_missing_pool('20260918',pool_id=pool_id,display_name=pool_id,market='A',reason='EXACT_INPUT_MISSING')
    result=store.materialize(payload)
    return payload,result['sha256']

def test_v192_owner_has_bound_source_recovery():
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    assert callable(getattr(PreselectionPoolStore,'recover_v192_original',None)), 'bound original source recovery is missing'

def test_real_v192_remains_historical_unproved(tmp_path):
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    store=PreselectionPoolStore(tmp_path/'data'); old,sha=missing(store)
    assert callable(getattr(store,'recover_v192_original',None)), 'bound original source recovery is missing'
    result=store.recover_v192_original(FIXTURES/'v192_original_trio',signal_date='20260917',target_date='20260918',expected_sha256=sha)
    p=store.read_pool('20260918','a_d1_premarket_pool')
    assert len(p['rows'])==91
    assert p['status']=='PARTIAL_WITH_ROWS' and p['source_role']=='RAW_SOURCE'
    assert p['stage_selection_eligible'] is False
    assert p['historical_provenance']['producer_equivalence']=='CANNOT_CONFIRM'
    assert p['source_sha256']=='8f3edb703b7ebb58144259dfc5d30466e1a3d7239afc2173d47a9a8dc3d88c22'
    assert all(p[k] is False for k in FLAGS)

def test_stage7_owner_has_real_source_entry():
    # Inspect the module before importing: the deployed full owner depends on
    # pyarrow, which is unrelated to this CSV-only historical operation.
    app = Path(__import__('infrastructure.historical_pool_sources', fromlist=['x']).__file__).parents[1]
    p=app/'ops/materialize_d1_review_lanes.py'
    assert 'def recover_stage7_original(' in p.read_text(), 'independent Stage7 owner recovery is missing'

def test_bridge_accepts_proved_partial_not_ready(tmp_path):
    from infrastructure.review_core_stage7_pool_source import _project
    from infrastructure.isolated_package_loader import load_isolated_package_module
    app = Path(__import__('infrastructure.historical_pool_sources', fromlist=['x']).__file__).parents[1]
    normalizer = load_isolated_package_module(Path(os.environ.get('V4_REVIEW_CORE_TEST_ROOT', str(app/'upstreams'))), package_directory='review_core', module_leaf='stage7_sources', namespace_prefix='test_rework_stage7')
    _normalize_rows = normalizer._normalize_rows
    src=FIXTURES/'stage7_original_trio'
    raw=list(csv.DictReader((src/'artifact.csv').open(encoding='utf-8-sig')))
    rows=_normalize_rows(raw,'20260917','20260918')
    hashes={n:hashlib.sha256((src/n).read_bytes()).hexdigest() for n in ['artifact.csv','manifest.json','receipt.json']}
    paths={'current':str(src/'manifest.json'),'artifact':str(src/'artifact.csv'),'manifest':str(src/'manifest.json'),'receipt':str(src/'receipt.json')}
    coverage={'requested_rows':189,'source_rows':185,'missing_symbols':['SZ.920275','SZ.920699','SZ.920045','SZ.920438'],'raw_status':'PARTIAL_WITH_ROWS','original_temporal_cutoff_safe':False,'row_temporal_cutoff_safe':True}
    artifact={'artifact_role':'D1_STAGE7_REPLAY_POOL_V1','artifact_version':'V1','source_role':'A_SHARE_1MIN_STAGE_1445_1500','target_date':'20260918','signal_date':'20260917','status':'PARTIAL','rows':rows,'row_count':185,'source_merge_role':'SOURCE_ONLY','stage_selection_eligible':False,'source_run_id':'20260917-a_share_1min_stage_1445_1500-6adb6908c89a5f29','source_sha256':hashes['artifact.csv'],'source_artifact_sha256':hashes['artifact.csv'],'source_manifest_sha256':hashes['manifest.json'],'source_receipt_sha256':hashes['receipt.json'],'source_paths':paths,'coverage_evidence':coverage,**FLAGS,'safety_flags':FLAGS}
    result={'artifact':artifact,'role':'D1_STAGE7_REPLAY_POOL_V1','trade_date':'20260918','target_date':'20260918','signal_date':'20260917','status':'PARTIAL','rows':rows,'row_count':185,'source_merge_role':'SOURCE_ONLY','stage_selection_eligible':False,'paths':paths,'run_id':'derived-canary','artifact_sha256':'1'*64,'manifest_sha256':'2'*64,'receipt_sha256':'3'*64,'cannot_confirm':['4 source symbols missing'],**FLAGS,'safety_flags':FLAGS}
    out=_project('20260918',tmp_path,result)
    assert len(out['rows'])==185 and out['status']=='PARTIAL'
    assert out['coverage_evidence']==coverage

# These use complete, supplied CSV trios; only placeholders and fault injection
# are synthetic. No source flag/hash is promoted in a positive canary.
import copy
import os
import shutil
import subprocess
import sys
from infrastructure.historical_pool_sources import verify_original, APPROVED, coverage
from infrastructure.stage_acquisition_universe_contracts import read_strict_a_preselection_snapshot
from infrastructure.preselection_pool_store import PreselectionPoolStore

def seed(store, pool_id):
    payload, digest = missing(store, pool_id)
    return {"sha256": digest, "payload": payload}



def recover_stage(root, expected):
    from ops.materialize_d1_review_lanes import recover_stage7_original
    app = Path(__import__('infrastructure.historical_pool_sources', fromlist=['x']).__file__).parents[1]
    # The producer's review_core is an excluded external dependency: the tests
    # bind the supplied, patched stage copy explicitly, never pretend it exists.
    package_root = Path(os.environ.get('V4_REVIEW_CORE_TEST_ROOT', str(app / 'upstreams')))
    return recover_stage7_original(source_dir=FIXTURES / 'stage7_original_trio', data_root=root,
        review_core_package_root=package_root, review_core_store_root=root.parent / 'review_core',
        signal_date='20260917', target_date='20260918', expected_sha256=expected)


def test_real_stage7_end_to_end_and_full_strict_snapshot(tmp_path):
    store = PreselectionPoolStore(tmp_path / 'data')
    old = seed(store, 'a_d1_stage7_fenshi_review_pool')
    result = recover_stage(store.root, old['sha256'])
    assert result['status'] == 'PARTIAL_WITH_ROWS'
    assert result['bridge_readback']['status'] == 'PARTIAL'
    assert result['bridge_readback']['coverage_evidence'] == coverage()
    assert result['bridge_readback']['source_paths']['current'] == ''
    assert len(result['bridge_readback']['rows']) == 185
    assert result['pool_readback']['artifact']['stage_selection_eligible'] is True
    snap = read_strict_a_preselection_snapshot(store, '20260918', 1)
    assert snap.stage_selection_eligible is True
    assert snap.row_count == 185  # UI display limit must not truncate input
    assert not snap.blocking_reasons
    assert snap.pool_contribution_counts['a_d1_stage7_fenshi_review_pool'] == 185
    again = recover_stage(store.root, old['sha256'])
    assert again['pool_recovery']['idempotent'] is True
    assert again['pool_recovery']['sha256'] == result['pool_recovery']['sha256']
    assert not list(store.root.rglob('fupan.csv'))
    assert not (store.root / 'stage_inputs/20260918/STAGE_1445_1500.json').exists()


def test_v192_unproved_lane_does_not_block_stage7(tmp_path):
    store = PreselectionPoolStore(tmp_path / 'data')
    stage = seed(store, 'a_d1_stage7_fenshi_review_pool')
    v192 = seed(store, 'a_d1_premarket_pool')
    recover_stage(store.root, stage['sha256'])
    store.recover_v192_original(FIXTURES / 'v192_original_trio', signal_date='20260917', target_date='20260918', expected_sha256=v192['sha256'])
    snap = read_strict_a_preselection_snapshot(store, '20260918', 200)
    assert snap.row_count == 185 and snap.stage_selection_eligible is True
    assert snap.pool_contribution_counts.get('a_d1_premarket_pool', 0) == 0
    assert len(store.read_pool('20260918', 'a_d1_premarket_pool')['rows']) == 91


@pytest.mark.parametrize('kind', ['stage7','v192'])
@pytest.mark.parametrize('mutation', ['missing_csv','missing_receipt','bad_sha','bad_run','bad_date','missing_row','bad_cutoff','fake_one_row','symlink'])
def test_original_source_negative_cases(tmp_path, kind, mutation):
    source = tmp_path / 'untrusted'
    shutil.copytree(FIXTURES / f'{kind}_original_trio', source)
    csv = source / 'artifact.csv'
    if mutation == 'missing_csv':
        csv.unlink()
    elif mutation == 'missing_receipt':
        (source / 'receipt.json').unlink()
    elif mutation == 'symlink':
        csv.unlink(); csv.symlink_to(FIXTURES / f'{kind}_original_trio/artifact.csv')
    elif mutation in {'bad_sha','bad_run','bad_date'}:
        path = source / 'receipt.json'
        data = json.loads(path.read_text())
        field = {'bad_sha':'artifact_sha256','bad_run':'run_id','bad_date':'trade_date'}[mutation]
        data[field] = {'bad_sha':'a'*64,'bad_run':'fake-run','bad_date':'20260921'}[mutation]
        path.write_text(json.dumps(data))
    elif mutation == 'bad_cutoff':
        csv.write_bytes(csv.read_bytes().replace(b'14:59', b'15:01').replace(b'17:30', b'18:30'))
    else:
        lines = csv.read_bytes().splitlines(keepends=True)
        csv.write_bytes(b''.join(lines[:-1] if mutation == 'missing_row' else lines[:2]))
    with pytest.raises((ValueError, OSError)):
        verify_original(source, kind)


@pytest.mark.parametrize('kind', ['stage7', 'v192'])
def test_wrong_requested_date_rejected(tmp_path, kind):
    with pytest.raises(ValueError, match='20260917 -> 20260918'):
        verify_original(FIXTURES / f'{kind}_original_trio', kind, signal_date='20260918', target_date='20260921')


def test_v192_owner_rejects_untrusted_payload_even_with_consistent_trio_sha(tmp_path):
    store = PreselectionPoolStore(tmp_path / 'data')
    old = seed(store, 'a_d1_premarket_pool')
    fake = store.read_pool('20260918', 'a_d1_premarket_pool')
    fake.update(status='V192_CANDIDATE_READY', source_role='SHARED_VERIFIED_V192',
                producer_id='v3_shared_v192_consumer_v1', source_path='untrusted/fake.csv',
                source_run_id='20260918-a-share-v192-premarket-pool-v3-fake',
                source_sha256='a'*64, source_artifact_sha256='a'*64, source_row_count=1,
                rows=[{'symbol':'A.000001', 'market':'A', 'recommendation_status':'WATCH_ONLY', **FLAGS}],
                stage_selection_eligible=True)
    with pytest.raises((ValueError, OSError)):
        store.materialize(fake)
    assert store.read_pool_snapshot('20260918','a_d1_premarket_pool')['artifact_sha256'] == old['sha256']


def test_bad_cas_does_not_overwrite(tmp_path):
    store = PreselectionPoolStore(tmp_path / 'data')
    old = seed(store, 'a_d1_premarket_pool')
    with pytest.raises(ValueError, match='compare-and-swap'):
        store.recover_v192_original(FIXTURES / 'v192_original_trio', signal_date='20260917', target_date='20260918', expected_sha256='a'*64)
    assert store.read_pool_snapshot('20260918','a_d1_premarket_pool')['artifact_sha256'] == old['sha256']


@pytest.mark.parametrize('write_number', range(1,8))
@pytest.mark.parametrize('failure', ['raise','hard_exit'])
def test_v192_all_owner_write_boundaries_recover(tmp_path, write_number, failure):
    store = PreselectionPoolStore(tmp_path / 'data')
    old = seed(store, 'a_d1_premarket_pool')
    # Real process death, after each of the existing revision/trio write points.
    program = r'''
import os,sys
from pathlib import Path
from infrastructure.preselection_pool_store import PreselectionPoolStore
s=PreselectionPoolStore(Path(sys.argv[1])); real=s._write; count=0
point=int(sys.argv[4]); failure=sys.argv[5]
def write(path,payload):
 global count
 real(path,payload); count+=1
 if count==point:
  if failure=='hard_exit': os._exit(23)
  raise OSError('injected write failure after persisted boundary')
s._write=write
try:
 s.recover_v192_original(Path(sys.argv[2]),signal_date='20260917',target_date='20260918',expected_sha256=sys.argv[3])
except OSError:
 sys.exit(24)
'''
    run = subprocess.run([sys.executable, '-c', program, str(store.root), str(FIXTURES/'v192_original_trio'), old['sha256'], str(write_number), failure],capture_output=True,text=True)
    assert run.returncode == (23 if failure == 'hard_exit' else 24), run.stderr
    if write_number in (5,6):
        with pytest.raises(ValueError):
            store.read_pool_snapshot('20260918','a_d1_premarket_pool')
    fixed = PreselectionPoolStore(store.root).recover_v192_original(FIXTURES/'v192_original_trio',signal_date='20260917',target_date='20260918',expected_sha256=old['sha256'])
    snap = store.read_pool_snapshot('20260918','a_d1_premarket_pool')
    assert snap['artifact_sha256'] == fixed['sha256']
    assert len(snap['artifact']['rows']) == 91
    assert snap['artifact']['stage_selection_eligible'] is False


def test_corrupt_recovery_revision_fail_closed(tmp_path):
    store = PreselectionPoolStore(tmp_path / 'data')
    old = seed(store, 'a_d1_premarket_pool')
    real=store._write
    def stop(path,payload):
        real(path,payload)
        if path.endswith('/a_d1_premarket_pool.json'):
            raise OSError('after artifact')
    store._write=stop
    with pytest.raises(OSError):
        store.recover_v192_original(FIXTURES/'v192_original_trio',signal_date='20260917',target_date='20260918',expected_sha256=old['sha256'])
    revision=store.root/f"preselection_revisions/20260918/{old['sha256']}.json"
    revision.write_text('{}')
    with pytest.raises(ValueError,match='revision identity'):
        PreselectionPoolStore(store.root).recover_v192_original(FIXTURES/'v192_original_trio',signal_date='20260917',target_date='20260918',expected_sha256=old['sha256'])


def test_stage7_first_materialization_requires_explicit_absence(tmp_path):
    result = recover_stage(tmp_path/'data', 'ABSENT')
    assert len(result['pool_readback']['artifact']['rows']) == 185
    again = recover_stage(tmp_path/'data', 'ABSENT')
    assert again['pool_recovery']['idempotent'] is True


def test_stage7_untracked_dirty_artifact_is_not_overwritten(tmp_path):
    root = tmp_path/'data'
    path = root/'preselection_pools/20260918/a_d1_stage7_fenshi_review_pool.json'
    path.parent.mkdir(parents=True)
    path.write_text('{"dirty":true}')
    with pytest.raises(ValueError):
        recover_stage(root, 'ABSENT')
    assert path.read_text() == '{"dirty":true}'


@pytest.mark.parametrize('mode', ['ABSENT','PLACEHOLDER'])
def test_stage7_owner_write_failure_retry_keeps_same_input(tmp_path, monkeypatch, mode):
    store=PreselectionPoolStore(tmp_path/'data')
    expected = 'ABSENT' if mode == 'ABSENT' else seed(store,'a_d1_stage7_fenshi_review_pool')['sha256']
    real=PreselectionPoolStore._write
    fired=False
    def fail_after_artifact(self,path,payload):
        nonlocal fired
        real(self,path,payload)
        if not fired and path.endswith('/a_d1_stage7_fenshi_review_pool.json'):
            fired=True
            raise OSError('injected Stage7 artifact write failure')
    monkeypatch.setattr(PreselectionPoolStore,'_write',fail_after_artifact)
    with pytest.raises(OSError):
        recover_stage(store.root,expected)
    assert fired
    input_bytes=(store.root/'stage_inputs/20260917/STAGE_1445_1500.json').read_bytes()
    monkeypatch.setattr(PreselectionPoolStore,'_write',real)
    result=recover_stage(store.root,expected)
    assert len(result['pool_readback']['artifact']['rows']) == 185
    assert (store.root/'stage_inputs/20260917/STAGE_1445_1500.json').read_bytes()==input_bytes
