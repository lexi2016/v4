import hashlib,json,struct
from pathlib import Path
import pytest
from ops import a_share_daily_sync as sync
from ops._a_share_daily_sync_parts.official_daily_package import OfficialDailyPackage,bind_cached_history
from test_a_share_daily_zip_source import input_ref,packet,bar,ref


def inputs(tmp_path):
    for day,previous in [(20261106,'20261105'),(20261109,'20261106'),(20261110,'20261109')]:
        def tweak(prefix,cod,md):
            if day==20261109 and prefix=='sh':
                struct.pack_into('<3d',md,12,0,0,0)
                struct.pack_into('<Q',md,56,0);struct.pack_into('<d',md,72,0)
            return cod,md
        value=input_ref(tmp_path/str(day),payload=packet(day,tweak=tweak),previous=previous,target=day)
    return bind_cached_history(value)


def witness():
    return [bar(d) for d in [20261104,20261105,20261106,20261110]]


def test_original_cli_entry_binds_cached_chain_and_resumes_existing_progress(tmp_path, monkeypatch):
    inp = inputs(tmp_path / 'official_daily')
    source = tmp_path / 'sh600025.day'
    source.write_bytes(sync.pack_hq_bar(bar(20261105)))
    monkeypatch.setattr(sync, 'RUN_DIR', tmp_path / 'run')
    monkeypatch.setattr(sync, 'discover_targets', lambda *a: [('sh', 1, '600025', source, 20261105)])
    requests = []
    class API:
        def __init__(self, **kw): pass
        def connect(self, *a, **kw): return True
        def get_security_bars(self, *a):
            requests.append(a)
            return witness()
        def disconnect(self): pass
    factory = lambda *a: API()
    monkeypatch.setattr(sync, '_runtime_api_factory', factory)
    import ops._a_share_daily_sync_parts.tdx_mac_adapter as transport
    monkeypatch.setattr(transport, 'MacDailyHqAPI', API)
    monkeypatch.setattr(sync, '_runtime_host_candidates', lambda *a: [('127.0.0.1', 7709)])
    args = sync.parse_args(['--tdx-root', str(tmp_path), '--target-date', '20261110',
                            '--official-daily-input', inp['path'],
                            '--official-daily-input-sha256', inp['sha256']])
    # The actual authority passes only path/SHA, never an expanded ref object.
    result = sync.run(args)
    assert result['accepted_count'] == 1
    assert [sync.day_int(b) for b in sync.read_hq_day_bars(source)] == [20261105, 20261106, 20261110]
    original = source.read_bytes()
    assert len(requests) == 1
    # A progress file created before history chaining binds the same input.json.
    progress = Path(result['progress_path'])
    old = json.loads(progress.read_text())
    old['official_daily_source']['input_ref'] = {k: inp[k] for k in ('path', 'sha256')}
    progress.write_text(json.dumps(old))
    again = sync.run(args)
    assert again['accepted_count'] == 1 and source.read_bytes() == original
    assert len(requests) == 1
    assert not list(tmp_path.glob('.*.tmp'))


def test_gap_uses_original_sdk_dates_but_only_official_values(tmp_path,monkeypatch):
    inp=inputs(tmp_path/'cache');p=tmp_path/'sh600025.day';p.write_bytes(sync.pack_hq_bar(bar(20261105)))
    monkeypatch.setattr(sync,'RUN_DIR',tmp_path/'run');calls=[]
    class API:
        def connect(self,*a,**kw):calls.append('connect');return True
        def get_security_bars(self,kline,market,code,start,count):
            assert (kline,market,code,start,count)==(9,1,'600025',0,32)
            values=witness()
            # These float values are not copied into the official native output.
            for value in values:value['amount']=129600.0
            calls.append('request');return values
        def disconnect(self):pass
    result=sync.run_sync([sync.DailyTarget('600025',1,p)],target_date='20261110',api_factory=lambda *a:API(),
                        host_candidates=[],official_daily_input=inp)
    assert result['accepted_count']==1 and calls==['connect','request']
    assert [sync.day_int(b) for b in sync.read_hq_day_bars(p)]==[20261105,20261106,20261110]
    assert p.read_bytes()[-32:]==sync.pack_hq_bar(bar(20261110))
    assert result['progress']['gap_witness_attempts']['600025'][0]['requests']==1
    snapshots=[json.loads(Path(r['path']).read_text()) for r in result['symbol_reconciliation'][0]['raw_response_snapshots']]
    proof=next(r['request']['date_witness'] for r in snapshots if r['request'].get('source_kind')=='TDX_OFFICIAL_G4DAY')
    assert proof['absent_dates']==[20261109]


@pytest.mark.parametrize('failure',['duplicate','future','truncated','market','missing_trade','unexpected_trade','zero_current','price_conflict'])
def test_witness_failures_never_authorize_omitted_or_invalid_days(tmp_path,failure):
    package=OfficialDailyPackage(inputs(tmp_path),20261110);rows=witness()
    if failure=='duplicate':rows.insert(1,dict(rows[0]))
    if failure=='future':rows.append(bar(20261111))
    if failure=='truncated':rows=rows[2:]
    if failure=='market':rows[0]['market']=0
    if failure=='missing_trade':rows=[r for r in rows if sync.day_int(r)!=20261106]
    if failure=='unexpected_trade':rows.insert(-1,bar(20261109))
    if failure=='zero_current':rows[-1]['vol']=0
    if failure=='price_conflict':rows[-1]['close']+=0.01
    bars,reason=package.witnessed_lookup(1,'600025',20261105,rows,{'path':'witness','sha256':'f'*64})
    assert not bars and reason!='OK'


def test_original_append_cas_preserves_prefix_and_cleans_temporary(tmp_path):
    p=tmp_path/'sh600025.day';original=sync.pack_hq_bar(bar(20261105));p.write_bytes(original)
    sha=lambda raw:hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError,match='CAS_MOVED'):
        sync.append_bars(p,[bar(20261106)],expected_source_sha256='0'*64)
    assert p.read_bytes()==original
    sync.append_bars(p,[bar(20261106)],expected_source_sha256=sha(original))
    assert p.read_bytes()==original+sync.pack_hq_bar(bar(20261106))
    with pytest.raises(ValueError,match='CAS_MOVED'):
        sync.append_bars(p,[bar(20261109)],expected_source_sha256=sha(original))
    assert p.read_bytes()==original+sync.pack_hq_bar(bar(20261106))
    assert not list(tmp_path.glob('.*.tmp'))
