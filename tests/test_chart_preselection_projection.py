"""The chart pool is an exact projection of one finished daily-panel identity."""
from copy import deepcopy
from pathlib import Path
import pytest

from ops.research_panel_daily_product import (
    FLAGS, GROUPS, chart_preselection_from_completion, publish_chart_preselection_from_completion,
    reference, save,
)
from infrastructure.preselection_pool_store import PreselectionPoolIntegrityError, PreselectionPoolStore
from infrastructure.stage_acquisition_universe_contracts import (
    build_strict_stage_acquisition_universe, read_strict_a_preselection_snapshot,
    validate_pool_rows, validate_strict_stage_acquisition_artifact,
)
from infrastructure.stage_acquisition_universe_commit import (
    EvidenceIdentity, StageAcquisitionUniverseCommit, StrictCommitError, _canonical_sha,
    _normalize_strict_artifact, _validate_artifact,
)

CALENDAR = Path(__file__).resolve().parents[1] / 'contracts/market_calendar_2026.json'
GEN = 'a' * 64
INPUT = 'b' * 64


def expected_identity(event_ref):
    import json
    event=json.loads(Path(event_ref['path']).read_bytes())
    return {key:event[key] for key in ('data_date','source_generation','input_sha256','manifest','artifact')}


def inputs(tmp_path, *, product_changes=None, manifest_changes=None, event_changes=None, index_changes=None):
    root = tmp_path / 'owner'
    rows = [
        {'symbol':'000035.SZ','display_name':'中国天楹','data_date':'20261030',
         'groups':'original|nav_smallk','pending_groups':'nav_pullback','reasons':'SOURCE_REASON'},
        {'symbol':'600000.SH','display_name':'浦发银行','data_date':'20261030',
         'groups':'nav_breakout','pending_groups':'','reasons':''},
    ]
    product = dict(schema_version='v4.a_share.daily_product.v1',data_date='20261030',
        source_generation=GEN,source_identity={'generation':GEN,'input_sha256':INPUT,'asof':20261030},sample_only=False,
        status='PARTIAL_WITH_ROWS',processed_count=4,source_universe_count=4,unique_count=2,
        group_counts={'original':1,'nav_smallk':1,'nav_pullback':0,'nav_breakout':1},
        unknown_count=1,rows=rows,**FLAGS)
    product.update(deepcopy(product_changes or {}))
    artifact = save(root/'versions/product.json', product)
    manifest = dict(schema_version='v4.a_share.daily_product_manifest.v1',data_date='20261030',
        source_generation=GEN,input_sha256=INPUT,sample_only=False,status='PARTIAL_WITH_ROWS',
        processed_count=4,source_universe_count=4,artifact=artifact,**FLAGS)
    manifest.update(deepcopy(manifest_changes or {}))
    manifest_ref = save(root/'versions/manifest.json', manifest)
    event = dict(schema_version='v4.a_share.daily_completion.v1',event_id='c'*64,data_date='20261030',
        source_generation=GEN,input_sha256=INPUT,status='PARTIAL_WITH_ROWS',processed_count=4,
        source_universe_count=4,unknown_count=1,manifest=manifest_ref,artifact=artifact,**FLAGS)
    event.update(deepcopy(event_changes or {}))
    event_ref = save(root/'events/latest.json', event)
    index = dict(schema_version='v4.a_share.daily_product_index.v1',dates={'20261030':manifest_ref},
                 latest_date='20261030',latest=manifest_ref)
    index.update(deepcopy(index_changes or {}))
    index_ref = save(root/'index.json', index)
    return root, {'index_ref':index_ref,'event_ref':event_ref,'calendar_ref':reference(CALENDAR)}


def test_four_groups_are_one_deduplicated_pool_with_separate_dates_and_unknown(tmp_path):
    _, refs = inputs(tmp_path)
    pool = chart_preselection_from_completion(**refs)
    assert pool['signal_date'] == '20261030'
    assert pool['trade_date'] == pool['target_date'] == '20261102'
    assert pool['source_run_id'] == GEN
    assert len(pool['rows']) == 2
    first = pool['rows'][0]
    assert first['symbol'] == 'A.000035'
    assert first['chart_groups'] == ['original','nav_smallk']
    assert first['chart_pending_groups'] == ['nav_pullback']
    assert first['chart_group_states'] == dict(zip(GROUPS,['TRUE','TRUE','UNKNOWN','FALSE']))
    assert first['source_date'] == '20261030'
    assert first['production_allowed'] is first['buy_gate_updated'] is first['orders_sent'] is False
    assert pool['coverage_evidence']['source_unknown_count'] == 1
    assert pool['coverage_evidence']['source_product_status'] == 'PARTIAL_WITH_ROWS'
    assert 'SOURCE_PANEL_PARTIAL_WITH_ROWS' in pool['cannot_confirm']
    assert pool['source_archive']['completion'] == refs['event_ref']
    assert all('pool_score' not in row for row in pool['rows'])


@pytest.mark.parametrize('kind', ['generation','input','date','sample','duplicate','normalized_duplicate','overlap','count','index','flag'])
def test_wrong_identity_or_invalid_membership_is_never_published(tmp_path, kind):
    kwargs = {}
    if kind == 'generation': kwargs['event_changes'] = {'source_generation':'d'*64}
    elif kind == 'input': kwargs['manifest_changes'] = {'input_sha256':'d'*64}
    elif kind == 'date': kwargs['event_changes'] = {'data_date':'20261102'}
    elif kind == 'sample': kwargs['product_changes'] = {'sample_only':True}
    elif kind == 'duplicate':
        row={'symbol':'000035.SZ','display_name':'甲','data_date':'20261030','groups':'original','pending_groups':'','reasons':''}
        kwargs['product_changes']={'rows':[row,row]}
    elif kind == 'normalized_duplicate':
        row={'symbol':'920196.BJ','display_name':'甲','data_date':'20261030','groups':'original','pending_groups':'','reasons':''}
        kwargs['product_changes']={'rows':[row,{**row,'symbol':'920196.SZ'}]}
    elif kind == 'overlap':
        row={'symbol':'000035.SZ','display_name':'甲','data_date':'20261030','groups':'original','pending_groups':'original','reasons':''}
        kwargs['product_changes']={'rows':[row], 'unique_count':1}
    elif kind == 'count': kwargs['product_changes']={'group_counts':{'original':999,'nav_smallk':1,'nav_pullback':0,'nav_breakout':1}}
    elif kind == 'index': kwargs['index_changes']={'dates':{}}
    elif kind == 'flag': kwargs['event_changes']={'production_allowed':True}
    _, refs = inputs(tmp_path, **kwargs)
    with pytest.raises(ValueError): chart_preselection_from_completion(**refs)


def test_tampered_bytes_and_same_hash_refs_with_optional_size(tmp_path):
    root, refs = inputs(tmp_path)
    extended = {key:{**ref,'bytes':Path(ref['path']).stat().st_size} for key,ref in refs.items()}
    assert len(chart_preselection_from_completion(**extended)['rows']) == 2
    (root/'versions/product.json').write_text('{}')
    with pytest.raises(ValueError,match='DAILY_SOURCE_PIN_DRIFT'):
        chart_preselection_from_completion(**refs)


def test_pool_store_writes_only_verified_projection_and_requires_exact_revision_cas(tmp_path):
    _, refs = inputs(tmp_path)
    refs['archive_refs'] = {'index':refs['index_ref'], 'completion':refs['event_ref']}
    data_root = tmp_path / 'preselection'
    data_root.mkdir()
    store = PreselectionPoolStore(data_root)
    original = chart_preselection_from_completion(**refs)
    stored = store.materialize_chart_selection(original, **refs)
    snapshot = store.read_pool_snapshot('20261102', 'a_share_chart_selection')
    assert snapshot['artifact'] == original
    assert stored['sha256'] == snapshot['artifact_sha256']
    assert store.materialize_chart_selection(original, **refs)['sha256'] == stored['sha256']
    altered = deepcopy(original)
    altered['rows'][0]['stock_name'] = 'unverified'
    with pytest.raises(ValueError, match='CHART_POOL_PROJECTION_MISMATCH'):
        store.materialize_chart_selection(altered, **refs)

    # A new, fully-bound event can replace only its exact stored predecessor.
    _, new_refs = inputs(tmp_path, product_changes={'rows':[
        {'symbol':'000035.SZ','display_name':'中国天楹','data_date':'20261030',
         'groups':'original|nav_smallk','pending_groups':'nav_pullback','reasons':'UPDATED'},
        {'symbol':'600000.SH','display_name':'浦发银行','data_date':'20261030',
         'groups':'nav_breakout','pending_groups':'','reasons':''},
    ]})
    new_refs['archive_refs'] = {'index':new_refs['index_ref'], 'completion':new_refs['event_ref']}
    updated = chart_preselection_from_completion(**new_refs)
    with pytest.raises(ValueError, match='CHART_POOL_PREIMAGE_MISMATCH'):
        store.materialize_chart_selection(updated, **new_refs)
    cas_keys = ('artifact_raw_sha256','receipt_raw_sha256','manifest_raw_sha256')
    cas = {key:snapshot[key] for key in cas_keys}
    wrong_cas = {**cas, 'receipt_raw_sha256':'d'*64}
    with pytest.raises(ValueError, match='CHART_POOL_PREIMAGE_MISMATCH'):
        store.materialize_chart_selection(updated, **new_refs, expected_previous=wrong_cas)
    result = store.materialize_chart_selection(updated, **new_refs, expected_previous=cas)
    assert result['previous_sha256'] == stored['sha256']
    assert store.read_pool_snapshot('20261102','a_share_chart_selection')['artifact'] == updated


def test_chart_rows_join_existing_strict_a_snapshot_without_unknown_blocking(tmp_path):
    _, refs = inputs(tmp_path)
    refs['archive_refs'] = {'index':refs['index_ref'], 'completion':refs['event_ref']}
    data_root = tmp_path / 'preselection'
    data_root.mkdir()
    store = PreselectionPoolStore(data_root)
    pool = chart_preselection_from_completion(**refs)
    store.materialize_chart_selection(pool, **refs)
    snapshot = read_strict_a_preselection_snapshot(store, '20261102')
    assert snapshot.ready
    assert set(snapshot.codes) == {'A.000035','A.600000'}
    assert all(snapshot.code_sources[code] == ('a_share_chart_selection',) for code in snapshot.codes)
    proposed = build_strict_stage_acquisition_universe(snapshot)
    assert validate_strict_stage_acquisition_artifact(proposed) == '20261102'
    identity = EvidenceIdentity('V3_5_STAGE_CENTER','ops.materialize_stage_acquisition_universe',
                                'test_release','A_SHARE_STAGE_ACQUISITION')
    strict = _normalize_strict_artifact(proposed,snapshot,identity)
    _validate_artifact(strict,'20261102',identity)
    assert len(strict['source_pool_provenance']) == 7


def test_daily_completion_publishes_once_and_stale_source_is_isolated(tmp_path):
    root, refs = inputs(tmp_path)
    data_root = tmp_path / 'preselection'
    data_root.mkdir()
    first = publish_chart_preselection_from_completion(root=root, pool_root=data_root,
                                                        calendar_ref=refs['calendar_ref'],expected_index_ref=refs['index_ref'],expected_event_ref=refs['event_ref'],
                                                        expected_identity=expected_identity(refs['event_ref']))
    store = PreselectionPoolStore(data_root)
    first_event = (root/'events/latest.json').read_bytes()
    assert first['row_count'] == 2 and first['source_date'] == '20261030'
    assert first['target_date'] == '20261102'
    assert store.read_pool('20261102','a_share_chart_selection')['rows'][0]['chart_pending_groups'] == ['nav_pullback']
    again = publish_chart_preselection_from_completion(root=root, pool_root=data_root,
                                                        calendar_ref=refs['calendar_ref'],expected_index_ref=reference(root/'index.json'),
                                                        expected_event_ref=reference(root/'events/latest.json'),
                                                        expected_identity=expected_identity(reference(root/'events/latest.json')))
    assert again['reused'] is True and again['artifact_sha256'] == first['artifact_sha256']
    assert (root/'events/latest.json').read_bytes() == first_event
    old_index = __import__('json').loads((root/'index.json').read_bytes())
    old_index['dates']['20261030'] = {'path':str(root/'versions/manifest.json'),'sha256':'d'*64}
    save(root/'index.json',old_index)
    with pytest.raises(PreselectionPoolIntegrityError, match='SOURCE_CANNOT_CONFIRM'):
        store.read_pool_snapshot('20261102','a_share_chart_selection')
    quarantine = store.read_all('20261102')
    assert quarantine[0]['status'] == 'CANNOT_CONFIRM' and quarantine[0]['rows'] == []


def test_manifest_continuation_reuses_only_identical_four_group_data(tmp_path):
    root, refs = inputs(tmp_path)
    data_root = tmp_path / 'preselection'
    data_root.mkdir()
    publish_chart_preselection_from_completion(root=root,pool_root=data_root,calendar_ref=refs['calendar_ref'],
        expected_index_ref=refs['index_ref'],expected_event_ref=refs['event_ref'],expected_identity=expected_identity(refs['event_ref']))
    store=PreselectionPoolStore(data_root)
    import json
    event=json.loads((root/'events/latest.json').read_bytes())
    previous=json.loads(Path(event['artifact']['path']).read_bytes())
    current=deepcopy(previous)
    current['row_refs']={'history_only':'unchanged group fields'}
    artifact_ref=save(root/'versions/continued-product.json',current)
    manifest=json.loads(Path(event['manifest']['path']).read_bytes())
    manifest['artifact']=artifact_ref
    new_manifest=save(root/'versions/continued-manifest.json',manifest)
    index=json.loads((root/'index.json').read_bytes())
    index['dates']['20261030']=index['latest']=new_manifest
    save(root/'index.json',index)
    assert len(store.read_pool('20261102','a_share_chart_selection')['rows'])==2
    current['rows'][0]['groups']='nav_pullback'
    changed_ref=save(root/'versions/changed-product.json',current)
    manifest['artifact']=changed_ref
    changed_manifest=save(root/'versions/changed-manifest.json',manifest)
    index['dates']['20261030']=index['latest']=changed_manifest
    save(root/'index.json',index)
    with pytest.raises(PreselectionPoolIntegrityError,match='CURRENT_SOURCE_CHANGED'):
        store.read_pool_snapshot('20261102','a_share_chart_selection')


def test_legacy_six_lane_stage_evidence_remains_readable_and_chart_appends(tmp_path):
    _, refs = inputs(tmp_path)
    refs['archive_refs'] = {'index':refs['index_ref'], 'completion':refs['event_ref']}
    data_root = tmp_path / 'preselection'
    data_root.mkdir()
    store = PreselectionPoolStore(data_root)
    base = dict(schema_version='v3_5.preselection_pool.v1',trade_date='20261102',
        pool_id='a_d1_premarket_pool',display_name='主池',market='A',status='V192_CANDIDATE_READY',
        producer_id='v3_shared_v192_consumer_v1',source_role='SHARED_VERIFIED_V192',source_path='source',
        source_sha256='e'*64,signal_date='20261030',target_date='20261102',stage_selection_eligible=True,
        rows=[dict(symbol='A.000001',market='A',pool_id='a_d1_premarket_pool',signal_date='20261030')],
        cannot_confirm=[],production_allowed=False,buy_gate_updated=False,orders_sent=False)
    store.materialize(base)
    chart = chart_preselection_from_completion(**refs)
    store.materialize_chart_selection(chart, **refs)
    snapshot = read_strict_a_preselection_snapshot(store, '20261102')
    identity = EvidenceIdentity('V3_5_STAGE_CENTER','ops.materialize_stage_acquisition_universe',
                                'test_release','A_SHARE_STAGE_ACQUISITION')
    extended = _normalize_strict_artifact(build_strict_stage_acquisition_universe(snapshot),snapshot,identity)
    _validate_artifact(extended,'20261102',identity)
    legacy = deepcopy(extended)
    legacy['source_pool_provenance'] = legacy['source_pool_provenance'][:-1]
    legacy['source_pool_provenance_sha256'] = _canonical_sha(legacy['source_pool_provenance'])
    legacy['known_pool_ids'] = legacy['known_pool_ids'][:-1]
    legacy['available_pool_ids'] = [x for x in legacy['available_pool_ids'] if x != 'a_share_chart_selection']
    legacy['pool_diagnostics'].pop('a_share_chart_selection',None)
    legacy['cannot_confirm'] = [f'{item["pool_id"]}:{reason}' for item in legacy['source_pool_provenance']
                                for reason in legacy['pool_diagnostics'].get(item['pool_id'],[])]
    legacy['codes'] = ['A.000001']
    legacy['codes_sha256'] = _canonical_sha(legacy['codes'])
    legacy['row_count'] = legacy['source_projection_row_count'] = 1
    legacy['code_sources'] = {'A.000001':['a_d1_premarket_pool']}
    legacy['pool_contribution_counts'].pop('a_share_chart_selection',None)
    _validate_artifact(legacy,'20261102',identity)
    assert len(legacy['source_pool_provenance']) == 6
    previous = {'current':{'trade_date':'20261102',**identity.as_dict()},'artifact':legacy}
    StageAcquisitionUniverseCommit._assert_successor_evolution(previous,extended)
    tampered = deepcopy(extended)
    tampered['codes'] = ['A.600000']
    with pytest.raises(StrictCommitError,match='retain all prior candidates'):
        StageAcquisitionUniverseCommit._assert_successor_evolution(previous,tampered)
    previous_seven = {'current':previous['current'],'artifact':extended}
    successor = deepcopy(extended)
    successor['codes'].append('A.600001')
    successor['code_sources']['A.600001'] = ['a_share_chart_selection']
    chart_evidence = successor['source_pool_provenance'][-1]
    chart_evidence['row_count'] += 1
    chart_evidence['artifact_raw_sha256'] = 'f'*64
    StageAcquisitionUniverseCommit._assert_successor_evolution(previous_seven,successor)
    successor['codes'].remove('A.600000')
    with pytest.raises(StrictCommitError,match='retain all prior candidates'):
        StageAcquisitionUniverseCommit._assert_successor_evolution(previous_seven,successor)


def test_stage_keeps_valid_rows_and_does_not_treat_date_tokens_as_a_share_codes():
    source={'rows':[{'symbol':'A.261029','market':'A','pool_id':'a_share_research_recommendation_pool'},
                    {'symbol':'A.000001','market':'A','pool_id':'a_share_research_recommendation_pool'}]}
    original=deepcopy(source)
    accepted=validate_pool_rows(source,'a_share_research_recommendation_pool','20261102')
    assert [row['symbol'] for row in accepted]==['A.000001']
    assert source==original


@pytest.mark.parametrize('lock_busy',[False,True])
def test_existing_daily_product_emits_bound_chart_completion_without_recomputing_history(tmp_path,monkeypatch,lock_busy):
    import json
    import ops.research_panel_daily_product as owner
    daily_root=tmp_path/'daily';pool_root=tmp_path/'pools';pool_root.mkdir()
    monkeypatch.setenv('V4_DATA_ROOT',str(pool_root))
    monkeypatch.delenv('V4_PRESELECTION_SOURCE_ROOT',raising=False)
    monkeypatch.delenv('V35_PRESELECTION_SOURCE_ROOT',raising=False)
    class FakeContext:
        def __init__(self,data_root,target):
            self.target=target;self.root=daily_root;self.scope=['000035.SZ'];self.generation=GEN
            self.identity={'generation':GEN,'input_sha256':INPUT,'asof':target}
            self.config={};self.config_ref={'path':'fixture','sha256':'d'*64}
            self.snapshot_ref={'path':'fixture','sha256':'e'*64}
        def unchanged(self):pass
    def fake_stock(context,symbol,**kwargs):
        groups={g:{'status':'TRUE' if g=='original' else 'UNKNOWN' if g=='nav_pullback' else 'FALSE','reasons':[]} for g in GROUPS}
        row={'symbol':symbol,'display_name':'中国天楹','data_date':'20261030','groups':'original',
             'pending_groups':'nav_pullback','reasons':'','risk_clear':'UNKNOWN','evaluation':{'groups':groups}}
        return row,{},daily_root/'checkpoints/test-cache.json'
    monkeypatch.setattr(owner,'SourceContext',FakeContext)
    monkeypatch.setattr(owner,'compute_stock',fake_stock)
    if lock_busy:
        def busy(**kwargs): raise BlockingIOError('OWNER_COMPLETION_LOCK_BUSY')
        monkeypatch.setattr(owner,'publish_chart_preselection_from_completion',busy)
    result=owner.materialize_daily_product(data_root=tmp_path,target=20261030,original_charts=False)
    event=json.loads((daily_root/'events/latest.json').read_bytes())
    assert result['chart_preselection']['status']==event['chart_preselection']['status']==('CANNOT_CONFIRM' if lock_busy else 'READY')
    assert event['chart_preselection']['target_date']=='20261102'
    assert event['chart_preselection']['source_date']=='20261030'
    assert event['chart_preselection']['source_generation']==event['source_generation']==GEN
    if lock_busy:
        assert result['chart_preselection']['reason']=='OWNER_COMPLETION_LOCK_BUSY'
        assert not (pool_root/'preselection_pools/20261102/a_share_chart_selection.json').exists()
    else:
        assert PreselectionPoolStore(pool_root).read_pool('20261102','a_share_chart_selection')['rows'][0]['chart_pending_groups']==['nav_pullback']


def test_shared_manifest_cas_conflict_gets_one_bounded_retry(tmp_path,monkeypatch):
    root,refs=inputs(tmp_path);pool_root=tmp_path/'pools';pool_root.mkdir()
    original=PreselectionPoolStore.materialize_chart_selection
    calls=[]
    def race_once(self,*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise ValueError('CHART_POOL_PREIMAGE_MISMATCH')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(PreselectionPoolStore,'materialize_chart_selection',race_once)
    result=publish_chart_preselection_from_completion(root=root,pool_root=pool_root,calendar_ref=refs['calendar_ref'],
        expected_index_ref=refs['index_ref'],expected_event_ref=refs['event_ref'],expected_identity=expected_identity(refs['event_ref']))
    assert len(calls)==2 and result['status']=='READY'


@pytest.mark.parametrize('changed',['event','index'])
def test_competing_completion_is_not_overwritten_or_published(tmp_path,changed):
    import json
    root,refs=inputs(tmp_path);pool_root=tmp_path/'pools';pool_root.mkdir()
    expected=expected_identity(refs['event_ref'])
    path=root/('events/latest.json' if changed=='event' else 'index.json')
    competing=json.loads(path.read_bytes())
    if changed=='event':competing.update(event_id='d'*64,source_generation='e'*64,data_date='20261029')
    else:competing['competing_revision']='different owner'
    save(path,competing);other_bytes=path.read_bytes()
    with pytest.raises(ValueError,match='CHART_POOL_EXPECTED_COMPLETION_CHANGED'):
        publish_chart_preselection_from_completion(root=root,pool_root=pool_root,calendar_ref=refs['calendar_ref'],
            expected_index_ref=refs['index_ref'],expected_event_ref=refs['event_ref'],expected_identity=expected)
    assert path.read_bytes()==other_bytes
    assert not (pool_root/'preselection_pools/20261102/a_share_chart_selection.json').exists()


def test_completion_lock_contention_never_overwrites_current_event(tmp_path):
    import fcntl,json
    root,refs=inputs(tmp_path);pool_root=tmp_path/'pools';pool_root.mkdir()
    expected=expected_identity(refs['event_ref'])
    with (root/'.stock-history-completion.lock').open('a+b') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        rival=json.loads((root/'events/latest.json').read_bytes());rival['event_id']='e'*64
        save(root/'events/latest.json',rival);other_bytes=(root/'events/latest.json').read_bytes()
        with pytest.raises(BlockingIOError):
            publish_chart_preselection_from_completion(root=root,pool_root=pool_root,calendar_ref=refs['calendar_ref'],
                expected_index_ref=refs['index_ref'],expected_event_ref=refs['event_ref'],expected_identity=expected)
        assert (root/'events/latest.json').read_bytes()==other_bytes
    assert not (pool_root/'preselection_pools/20261102/a_share_chart_selection.json').exists()


def test_locked_publisher_also_checks_the_owners_in_memory_identity(tmp_path):
    root,refs=inputs(tmp_path);pool_root=tmp_path/'pools';pool_root.mkdir()
    expected=expected_identity(refs['event_ref']);expected['source_generation']='e'*64
    with pytest.raises(ValueError,match='CHART_POOL_EXPECTED_IDENTITY_CHANGED'):
        publish_chart_preselection_from_completion(root=root,pool_root=pool_root,calendar_ref=refs['calendar_ref'],
            expected_index_ref=refs['index_ref'],expected_event_ref=refs['event_ref'],expected_identity=expected)
    assert not (pool_root/'preselection_pools/20261102/a_share_chart_selection.json').exists()


def test_index_and_event_rename_reference_interleaving_cannot_publish_other_run(tmp_path,monkeypatch):
    import os
    import ops.research_panel_daily_product as owner
    daily_root=tmp_path/'daily';pool_root=tmp_path/'pools';pool_root.mkdir()
    monkeypatch.setenv('V4_DATA_ROOT',str(pool_root))
    monkeypatch.delenv('V4_PRESELECTION_SOURCE_ROOT',raising=False)
    monkeypatch.delenv('V35_PRESELECTION_SOURCE_ROOT',raising=False)
    rival_generation='e'*64;rival_input='f'*64;rival_date='20261029'
    rival_product=dict(schema_version='v4.a_share.daily_product.v1',data_date=rival_date,
        source_generation=rival_generation,source_identity={'generation':rival_generation,'input_sha256':rival_input,'asof':20261029},
        sample_only=False,status='READY',processed_count=1,source_universe_count=1,unique_count=1,
        group_counts={'original':1,'nav_smallk':0,'nav_pullback':0,'nav_breakout':0},unknown_count=0,
        rows=[{'symbol':'600000.SH','display_name':'浦发银行','data_date':rival_date,'groups':'original','pending_groups':'','reasons':''}],**FLAGS)
    rival_artifact=owner.save(daily_root/'versions/rival/product.json',rival_product)
    rival_manifest=owner.save(daily_root/'versions/rival/manifest.json',dict(schema_version='v4.a_share.daily_product_manifest.v1',
        data_date=rival_date,source_generation=rival_generation,input_sha256=rival_input,sample_only=False,status='READY',
        processed_count=1,source_universe_count=1,artifact=rival_artifact,**FLAGS))
    rival_event=dict(schema_version='v4.a_share.daily_completion.v1',event_id='d'*64,data_date=rival_date,
        source_generation=rival_generation,input_sha256=rival_input,status='READY',processed_count=1,source_universe_count=1,
        unknown_count=0,manifest=rival_manifest,artifact=rival_artifact,**FLAGS)
    rival_index=dict(schema_version='v4.a_share.daily_product_index.v1',dates={rival_date:rival_manifest},latest_date=rival_date,latest=rival_manifest)
    rival_bytes={daily_root/'index.json':owner.canonical(rival_index)+b'\n',
                 daily_root/'events/latest.json':owner.canonical(rival_event)+b'\n'}
    original_reference=owner.reference;injected=[]
    def racing_reference(path):
        path=Path(path)
        if path in rival_bytes and path not in injected:
            replacement=path.with_name('.competing-test-write');replacement.write_bytes(rival_bytes[path]);os.replace(replacement,path);injected.append(path)
        return original_reference(path)
    class FakeContext:
        def __init__(self,data_root,target):
            self.target=target;self.root=daily_root;self.scope=['000035.SZ'];self.generation=GEN
            self.identity={'generation':GEN,'input_sha256':INPUT,'asof':target}
            self.config={};self.config_ref={'path':'fixture','sha256':'d'*64};self.snapshot_ref={'path':'fixture','sha256':'e'*64}
        def unchanged(self):pass
    def fake_stock(context,symbol,**kwargs):
        groups={g:{'status':'TRUE' if g=='original' else 'FALSE','reasons':[]} for g in GROUPS}
        return {'symbol':symbol,'display_name':'中国天楹','data_date':'20261030','groups':'original',
                'pending_groups':'','reasons':'','risk_clear':'UNKNOWN','evaluation':{'groups':groups}}, {}, daily_root/'checkpoints/test-cache.json'
    monkeypatch.setattr(owner,'reference',racing_reference);monkeypatch.setattr(owner,'SourceContext',FakeContext);monkeypatch.setattr(owner,'compute_stock',fake_stock)
    result=owner.materialize_daily_product(data_root=tmp_path,target=20261030,original_charts=False)
    assert set(injected)==set(rival_bytes)
    assert result['data_date']=='20261030' and result['source_generation']==GEN
    assert result['chart_preselection']['status']=='CANNOT_CONFIRM'
    assert result['chart_preselection']['reason']=='CHART_POOL_EXPECTED_COMPLETION_CHANGED'
    assert all(path.read_bytes()==raw for path,raw in rival_bytes.items())
    assert not (pool_root/'preselection_pools').exists()
