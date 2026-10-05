"""Bounded transport fixtures; no live quote/selector or injected selection builders."""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from infrastructure.preselection_pool_store import PreselectionPoolStore
from ops import run_stage_center_nodes as nodes
from ops.materialize_stage_acquisition_universe import materialize_stage_acquisition_universe
from stage_center.runner import RunnerConfig, StageCenterRunner, _validate_exact_selection_inputs
from test_strict_stage_acquisition_v4 import _write_pool_set

DATE = '20260915'
SH = ZoneInfo('Asia/Shanghai')
ROOT = Path(__file__).resolve().parents[1]
FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)


@pytest.fixture(autouse=True)
def release_identity(monkeypatch):
    monkeypatch.setenv("V35_RELEASE_ID", "synthetic-core-recovery")


def bound_config(tmp_path: Path, *, materialize: bool = True) -> dict:
    config = {key: str(tmp_path / key) for key in nodes.REQUIRED_CONFIG_KEYS}
    config.update(python_path=sys.executable,
                  shared_data_root=str(ROOT / 'upstreams/v3_shared_data'),
                  node_max_attempts=1, node_retry_backoff_seconds=0)
    for key, value in config.items():
        if key.endswith('_root'):
            Path(value).mkdir(parents=True, exist_ok=True)
    _write_pool_set(Path(config['candidate_acquisition_root']), DATE)
    if materialize:
        materialize_stage_acquisition_universe(Path(config['candidate_acquisition_root']), DATE)
    codes = [f'HK.{n:05d}' for n in range(1, 101)]
    pool = dict(schema_version='v3_5.preselection_pool.v1', trade_date=DATE,
                pool_id='hkconnect_d1_top100', display_name='synthetic exact D-1',
                market='HK', status='STRICT_0_2_READY',
                producer_id='v3_shared_hk_0_2_consumer_v1',
                source_role='SHARED_VERIFIED_HK_0_2',
                source_path='synthetic/exact-d1.csv',
                source_sha256=hashlib.sha256(b'synthetic D-1').hexdigest(),
                rows=[dict(symbol=c, code=c, name='fixture', market='HK',
                           pool_id='hkconnect_d1_top100', signal_date='20260914',
                           trade_date=DATE, target_date=DATE, selected_strategy='prob_active',
                           prob_active=0.5, data_cutoff='20260914 close', **FLAGS)
                      for c in codes], cannot_confirm=[], **FLAGS)
    PreselectionPoolStore(Path(config['hk_d1_root'])).materialize(pool)
    return config


def runner_for(config: dict) -> StageCenterRunner:
    return nodes._build_runner(config)


def test_public_prep_serializes_actual_materializer_paths(tmp_path, capsys):
    config = bound_config(tmp_path, materialize=False)
    # The public prep contract now requires an explicit source root. Seed its
    # source pool there and leave the target empty so the test exercises the
    # cross-root materialization path instead of relying on target-side rows.
    _write_pool_set(Path(config['preselection_source_root']), DATE)
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    rc = nodes.main(['--config', str(path), '--node', 'PREP_0915', '--trade-date', DATE,
                     '--evaluated-at', '2026-09-15T09:15:00+08:00', '--historical-backfill'])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0, payload
    from stage_center.candidate_input import read_candidate_input
    assert len(read_candidate_input(Path(config['candidate_acquisition_root']), DATE).codes) == 6
    assert payload['nodes'][0]['status'] == 'READY'
    assert all(payload[k] is False for k in FLAGS)


def test_public_deadline_checks_missing_chain_without_provider_or_writes(tmp_path, capsys):
    config = bound_config(tmp_path)
    path = tmp_path / 'config.json'
    path.write_text(json.dumps(config))
    before = {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    rc = nodes.main(['--config', str(path), '--deadline-only', '--trade-date', DATE,
                     '--evaluated-at', '2026-09-15T09:37:00+08:00'])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 3
    assert payload['status'] == 'DEADLINE_CHAIN_ALERT'
    assert payload['first_failed_layer'] == 'RAW_LATEST'
    assert set(payload['lanes']) == {'A_SHARE', 'HK_CONNECT'}
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}


def test_fixed_universe_gate_needs_no_optional_overlay_or_full_market(tmp_path):
    from test_stage_research_context_v4 import _write_morning

    config = bound_config(tmp_path)
    morning_root = Path(config['v4_research_data_root']).parent / 'v4_morning_news_root'
    morning_root.mkdir(parents=True, exist_ok=True)
    config['v4_morning_news_root'] = str(morning_root)
    _write_morning(morning_root, DATE)
    runner = runner_for(config)
    assert runner.config.injected_test_mode is False
    a = _validate_exact_selection_inputs(runner.config, DATE, 'STAGE_0930_0935', market='A_SHARE')
    hk = _validate_exact_selection_inputs(runner.config, DATE, 'STAGE_0930_0935', market='HK_CONNECT')
    assert any('a_name_overlay_unavailable' in item for item in a)
    assert any('hk_d1_sha256=' in item for item in hk)
    assert not any('full_universe_json=' in item for item in hk)


def test_zero_row_receipt_preserves_each_market_input_failure(tmp_path):
    config = bound_config(tmp_path)
    # Corrupt an already-published exact pool, without rewriting its evidence.
    artifact = Path(config['hk_d1_root']) / f'preselection_pools/{DATE}/hkconnect_d1_top100.json'
    payload = json.loads(artifact.read_text()); payload['trade_date'] = '20260914'
    artifact.write_text(json.dumps(payload))
    # The A core pointer is independently invalid; no transport may be used.
    root = Path(config['candidate_acquisition_root'])
    for current in root.glob(f'current/{DATE}/*/current.json'):
        current.write_text('{}')
    result = runner_for(config).tick(DATE, datetime(2026,9,15,9,35,5,tzinfo=SH), stage_id='STAGE_0930_0935')
    assert result['status'] == 'CANNOT_CONFIRM'
    assert set(result['markets']) == {'A_SHARE', 'HK_CONNECT'}
    assert result['markets']['A_SHARE']['cannot_confirm']
    assert result['markets']['HK_CONNECT']['cannot_confirm']
    assert result['first_failed_layer'] == 'EXACT_SELECTION_INPUT_BINDING'


def test_hk_pool_byte_mutation_is_refused(tmp_path):
    config = bound_config(tmp_path)
    artifact = Path(config['hk_d1_root']) / f'preselection_pools/{DATE}/hkconnect_d1_top100.json'
    payload = json.loads(artifact.read_text()); payload['rows'][0]['name'] = 'tampered'
    artifact.write_text(json.dumps(payload))
    with pytest.raises(ValueError, match='(?i)(integrity|sha|canonical|snapshot)'):
        _validate_exact_selection_inputs(runner_for(config).config, DATE, 'STAGE_0930_0935', market='HK_CONNECT')


def stage_transport(monkeypatch, *, bad_snapshot_date=False, after_snapshot=None):
    """Only replace subprocess I/O used by the unchanged shared transports."""
    import functools
    import subprocess
    import stage_center.live_collectors as live

    calls = []
    def process(command, **kwargs):
        request = json.loads(kwargs['input'])
        codes = request['codes']
        if 'stage_id' not in request:
            kind, marker = 'FUTU_FIXED_CODES', '__FUTU_HK_AUCTION_JSON__'
            stamp = '2026-09-14' if bad_snapshot_date else '2026-09-15'
            response = {'rows': [dict(code=c, name='fixture', prev_close_price=10,
                          last_price=11, turnover=30_000_000, volume_ratio=2,
                          update_time=f'{stamp} 09:35:00') for c in codes], 'errors': []}
        else:
            kind = 'EXHQ' if 'scripts.live_acquisition.pytdx_exhq_probe' in command else 'HQ'
            marker = '__PYTDX_EXHQ_MINUTE_JSON__' if kind == 'EXHQ' else '__PYTDX_HQ_MINUTE_JSON__'
            response = dict(raw_rows=[dict(code=c, name='fixture',
                           time_key=f'2026-09-15 09:{minute:02d}:00', open=10,
                           close=10+minute/100, high=11, low=9.8, volume=10000,
                           turnover=10_000_000, last_close=10)
                           for c in codes for minute in range(30,36)],
                           errors=[], no_data_codes=[], requested_code_count=len(codes),
                           completed_code_count=len(codes), source_host='TRANSPORT_FIXTURE')
        calls.append({'kind': kind, 'request': request})
        if kind == 'FUTU_FIXED_CODES' and after_snapshot is not None:
            after_snapshot()
        return subprocess.CompletedProcess(command, 0, marker+json.dumps(response), '')
    monkeypatch.setattr(live, 'collect_a_share_hq_minute', functools.partial(live.collect_a_share_hq_minute, process_runner=process))
    monkeypatch.setattr(live, 'collect_hk_minute', functools.partial(live.collect_hk_minute, process_runner=process))
    return calls


def publish_research_fixture(config):
    from test_stage_research_context_v4 import _publish_slot, _write_morning
    root = Path(config['v4_research_data_root'])
    morning_root = root.parent / 'v4_morning_news_root'
    morning_root.mkdir(parents=True, exist_ok=True)
    config['v4_morning_news_root'] = str(morning_root)
    _write_morning(morning_root, DATE)
    _publish_slot(root, DATE, '0900', with_stage_evidence=True)


def test_actual_node_collects_only_fixed_codes_and_publishes_verified_chains(tmp_path, monkeypatch, capsys):
    from stage_center.raw_store import RawStore
    from stage_center.selection import SelectionStore
    config = bound_config(tmp_path)
    # Supply the explicit source binding independently from the target chain.
    # The source fixture is synthetic; publication and runner reads still use
    # the public node path and the target remains the only current pointer.
    _write_pool_set(Path(config['preselection_source_root']), DATE)
    publish_research_fixture(config)
    calls = stage_transport(monkeypatch)
    path = tmp_path / 'config.json'; path.write_text(json.dumps(config))
    rc = nodes.main(['--config', str(path), '--node', 'STAGE_0930_0935', '--trade-date', DATE,
                     '--evaluated-at', '2026-09-15T09:35:05+08:00', '--historical-backfill'])
    output = json.loads(capsys.readouterr().out)
    receipt_path = Path(config['receipt_root']) / DATE / 'STAGE_0930_0935/receipt.json'
    receipt = json.loads(receipt_path.read_text())
    assert rc == 0, (output, receipt, calls)
    assert receipt['status'] in {'READY', 'PARTIAL_WITH_ROWS'}, receipt
    assert len(calls) == 4, calls
    assert [c['kind'] for c in calls] == ['HQ', 'EXHQ', 'EXHQ', 'FUTU_FIXED_CODES']
    assert calls[0]['request']['codes'] == [f'SZ.{n:06d}' for n in range(1,7)]
    assert calls[1]['request']['codes'] + calls[2]['request']['codes'] == calls[3]['request']['codes'] == [f'HK.{n:05d}' for n in range(1,101)]
    for market in ('A_SHARE', 'HK_CONNECT'):
        raw = RawStore(Path(config['raw_root'])).verify_latest(DATE, 'STAGE_0930_0935', market)
        selected = SelectionStore(Path(config['selection_root'])).read_verified(DATE,'STAGE_0930_0935',market)
        assert raw['verified']['row_count'] == (6 if market == 'A_SHARE' else 100)
        assert len(selected['rows']) > 0
        assert all(selected[k] is False for k in FLAGS)
        if market == 'HK_CONNECT':
            assert 'route=shared_pytdx_exhq_hk_exact_d1_top100' in raw['verified']['source_evidence']
    before = len(calls)
    again = runner_for(config).tick(DATE, datetime(2026,9,15,9,35,5,tzinfo=SH),stage_id='STAGE_0930_0935')
    assert again['status'] == 'NOOP_ALREADY_VERIFIED', again
    assert len(calls) == before
    rc = nodes.main(['--config', str(path), '--deadline-only', '--trade-date',DATE,
                    '--evaluated-at','2026-09-15T09:37:00+08:00'])
    checked = json.loads(capsys.readouterr().out)
    assert rc == 0 and checked['status'] == 'DEADLINE_CHAIN_READY', checked


def test_bad_hk_quote_date_keeps_a_lane_and_rejects_hk(tmp_path, monkeypatch):
    config = bound_config(tmp_path); publish_research_fixture(config)
    calls = stage_transport(monkeypatch, bad_snapshot_date=True)
    result = runner_for(config).tick(DATE,datetime(2026,9,15,9,35,5,tzinfo=SH),stage_id='STAGE_0930_0935')
    assert result['markets']['A_SHARE']['selection_status'] in {'READY','PARTIAL_WITH_ROWS'}, result
    assert result['markets']['HK_CONNECT']['status'] == 'CANNOT_CONFIRM', result
    assert any('TEMPORAL' in reason for reason in result['markets']['HK_CONNECT']['cannot_confirm'])
    assert len(calls) == 4


@pytest.mark.parametrize('mutation', ['signal_date','mixed_code','missing_receipt','duplicate'])
def test_hk_authority_bad_identity_never_starts_its_collector(tmp_path,monkeypatch,mutation):
    from infrastructure.data_store import _canonical_bytes, _sha256
    config=bound_config(tmp_path); publish_research_fixture(config)
    store=PreselectionPoolStore(Path(config['hk_d1_root']))
    payload=store.read_pool(DATE,'hkconnect_d1_top100')
    artifact_rel,receipt_rel=store._relative(DATE,'hkconnect_d1_top100')
    if mutation=='missing_receipt':
        (store.root/receipt_rel).unlink()
    else:
        if mutation=='signal_date': payload['rows'][0]['signal_date']='20260911'
        elif mutation=='mixed_code': payload['rows'][0]['code']='A.000001'
        else: payload['rows'][0]['symbol']=payload['rows'][1]['symbol']; payload['rows'][0]['code']=payload['rows'][1]['code']
        # A self-consistent trio is not enough to make a wrong role/date valid.
        receipt=store._receipt(trade_date=DATE,pool_id='hkconnect_d1_top100',
                              artifact_path=artifact_rel,artifact_sha256=_sha256(payload),payload=payload)
        (store.root/artifact_rel).write_bytes(_canonical_bytes(payload))
        (store.root/receipt_rel).write_bytes(_canonical_bytes(receipt))
        (store.root/f'preselection_pools/{DATE}/manifest.json').write_bytes(_canonical_bytes({'hkconnect_d1_top100':_sha256(payload)}))
    calls=stage_transport(monkeypatch)
    result=runner_for(config).tick(DATE,datetime(2026,9,15,9,35,5,tzinfo=SH),stage_id='STAGE_0930_0935')
    assert result['markets']['A_SHARE']['selection_status'] in {'READY','PARTIAL_WITH_ROWS'},result
    assert result['markets']['HK_CONNECT']['status']=='CANNOT_CONFIRM',result
    assert [c['kind'] for c in calls]==['HQ'],calls


def test_bad_a_pointer_does_not_expand_or_block_exact_hk(tmp_path,monkeypatch):
    config=bound_config(tmp_path)
    for current in Path(config['candidate_acquisition_root']).glob(f'current/{DATE}/*/current.json'):
        value=json.loads(current.read_text()); value['artifact_sha256']='0'*64
        current.write_text(json.dumps(value))
    calls=stage_transport(monkeypatch)
    result=runner_for(config).tick(DATE,datetime(2026,9,15,9,35,5,tzinfo=SH),stage_id='STAGE_0930_0935')
    assert result['markets']['A_SHARE']['status']=='CANNOT_CONFIRM',result
    assert result['markets']['HK_CONNECT']['selection_status'] in {'READY','PARTIAL_WITH_ROWS'},result
    assert [c['kind'] for c in calls]==['EXHQ','EXHQ','FUTU_FIXED_CODES']
    assert len(calls[0]['request']['codes'])+len(calls[1]['request']['codes'])==100


def test_candidate_authority_is_lane_local_across_a_loss_and_restore(tmp_path, monkeypatch):
    """A/HK slot reuse must survive an A pointer outage and recovery."""
    config = bound_config(tmp_path / "existing-slot")
    publish_research_fixture(config)
    calls = stage_transport(monkeypatch)
    runner = runner_for(config)
    first = runner.tick(
        DATE,
        datetime(2026, 9, 15, 9, 35, 5, tzinfo=SH),
        stage_id="STAGE_0930_0935",
    )
    assert first["status"] in {"READY", "PARTIAL_WITH_ROWS"}, first
    assert len(calls) == 4
    current_paths = tuple(
        Path(config["candidate_acquisition_root"]).glob(
            f"current/{DATE}/*/current.json"
        )
    )
    saved_current = {path: path.read_bytes() for path in current_paths}
    assert current_paths
    for path in current_paths:
        path.write_text("{}", encoding="utf-8")
    damaged = runner.tick(
        DATE,
        datetime(2026, 9, 15, 9, 35, 5, tzinfo=SH),
        stage_id="STAGE_0930_0935",
    )
    assert damaged["status"] == "PARTIAL_WITH_ROWS", damaged
    assert damaged["markets"]["A_SHARE"]["status"] == "CANNOT_CONFIRM", damaged
    assert damaged["markets"]["HK_CONNECT"]["selection_status"] in {
        "READY",
        "PARTIAL_WITH_ROWS",
    }, damaged
    # The verified HK lane is reused; an unavailable A authority cannot cause
    # a fresh A/HK transport attempt.
    assert len(calls) == 4
    for path, payload in saved_current.items():
        path.write_bytes(payload)
    restored = runner.tick(
        DATE,
        datetime(2026, 9, 15, 9, 35, 5, tzinfo=SH),
        stage_id="STAGE_0930_0935",
    )
    assert restored["status"] == "NOOP_ALREADY_VERIFIED", restored
    assert len(calls) == 4

    # A missing before the first run publishes an HK-only partial slot with
    # the HK D-1 SHA.  Restoring A must complete that slot without treating the
    # synthetic HK plan carrier SHA as an HK mismatch.
    config = bound_config(tmp_path / "hk-first")
    publish_research_fixture(config)
    calls = stage_transport(monkeypatch)
    runner = runner_for(config)
    current_paths = tuple(
        Path(config["candidate_acquisition_root"]).glob(
            f"current/{DATE}/*/current.json"
        )
    )
    saved_current = {path: path.read_bytes() for path in current_paths}
    for path in current_paths:
        path.write_text("{}", encoding="utf-8")
    hk_first = runner.tick(
        DATE,
        datetime(2026, 9, 15, 9, 35, 5, tzinfo=SH),
        stage_id="STAGE_0930_0935",
    )
    assert hk_first["markets"]["A_SHARE"]["status"] == "CANNOT_CONFIRM", hk_first
    assert hk_first["markets"]["HK_CONNECT"]["selection_status"] in {
        "READY",
        "PARTIAL_WITH_ROWS",
    }, hk_first
    assert [call["kind"] for call in calls] == [
        "EXHQ",
        "EXHQ",
        "FUTU_FIXED_CODES",
    ], calls
    for path, payload in saved_current.items():
        path.write_bytes(payload)
    a_restored = runner.tick(
        DATE,
        datetime(2026, 9, 15, 9, 35, 5, tzinfo=SH),
        stage_id="STAGE_0930_0935",
    )
    assert a_restored["status"] in {"READY", "PARTIAL_WITH_ROWS"}, a_restored
    assert a_restored["markets"]["A_SHARE"]["selection_status"] in {
        "READY",
        "PARTIAL_WITH_ROWS",
    }, a_restored
    assert a_restored["markets"]["HK_CONNECT"]["selection_status"] in {
        "READY",
        "PARTIAL_WITH_ROWS",
    }, a_restored
    assert [call["kind"] for call in calls] == [
        "EXHQ",
        "EXHQ",
        "FUTU_FIXED_CODES",
        "HQ",
    ], calls


def test_deadline_rejects_same_root_noncanonical_bundle_receipt_without_writes(
    tmp_path, monkeypatch, capsys
):
    config = bound_config(tmp_path)
    publish_research_fixture(config)
    calls = stage_transport(monkeypatch)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config), encoding="utf-8")
    assert (
        nodes.main(
            [
                "--config",
                str(path),
                "--node",
                "STAGE_0930_0935",
                "--trade-date",
                DATE,
                "--evaluated-at",
                "2026-09-15T09:35:05+08:00",
                "--historical-backfill",
            ]
        )
        == 0
    )
    capsys.readouterr()
    raw_root = Path(config["raw_root"])
    bundle_latest = raw_root / "bundle_latest.json"
    bundle = json.loads(bundle_latest.read_text(encoding="utf-8"))
    key = f"{DATE}/STAGE_0930_0935"
    entry = bundle["entries"][key]
    wrong_receipt = next(
        raw_root.glob(f"runs/{DATE}/*/*/receipt.json")
    )
    entry["receipt_relative"] = wrong_receipt.relative_to(raw_root).as_posix()
    bundle_latest.write_text(json.dumps(bundle), encoding="utf-8")
    before = {
        str(file.relative_to(tmp_path)): file.read_bytes()
        for file in tmp_path.rglob("*")
        if file.is_file()
    }
    rc = nodes.main(
        [
            "--config",
            str(path),
            "--deadline-only",
            "--trade-date",
            DATE,
            "--evaluated-at",
            "2026-09-15T09:37:00+08:00",
        ]
    )
    result = json.loads(capsys.readouterr().out)
    after = {
        str(file.relative_to(tmp_path)): file.read_bytes()
        for file in tmp_path.rglob("*")
        if file.is_file()
    }
    assert rc == 3, result
    assert result["status"] == "DEADLINE_CHAIN_ALERT", result
    assert result["first_failed_layer"] == "RAW_BUNDLE_RECEIPT", result
    assert result["observed_status"] == "NON_CANONICAL_RECEIPT_PATH", result
    assert before == after
    assert len(calls) == 4


def test_tick_public_entry_never_invokes_legacy_full_market_preflight(tmp_path,monkeypatch,capsys):
    from ops import run_stage_center_tick as tick
    config=bound_config(tmp_path)
    config['hk_auction_root']=config['hk_second_filter_root']
    publish_research_fixture(config)
    calls=stage_transport(monkeypatch)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):
            return cls(2026,9,15,9,35,5,tzinfo=SH).astimezone(tz) if tz else cls(2026,9,15,9,35,5)
    monkeypatch.setattr(tick,'datetime',Clock)
    def forbidden(*args,**kwargs):
        raise AssertionError('second producer/full universe must not run')
    monkeypatch.setattr(tick,'_run_universe_preflight',forbidden)
    path=tmp_path/'config.json';path.write_text(json.dumps(config))
    rc=tick.main(['--config',str(path),'--stage-id','STAGE_0930_0935'])
    result=json.loads(capsys.readouterr().out)
    assert rc==0,result
    assert result['markets']['HK_CONNECT']['selection_status'] in {'READY','PARTIAL_WITH_ROWS'},result
    assert len(calls)==4


def test_verified_slot_does_not_hide_changed_hk_source_sha(tmp_path,monkeypatch):
    config=bound_config(tmp_path);publish_research_fixture(config)
    calls=stage_transport(monkeypatch)
    runner=runner_for(config)
    first=runner.tick(DATE,datetime(2026,9,15,9,35,5,tzinfo=SH),stage_id='STAGE_0930_0935')
    assert first['status'] in {'READY','PARTIAL_WITH_ROWS'}
    artifact=Path(config['hk_d1_root'])/f'preselection_pools/{DATE}/hkconnect_d1_top100.json'
    raw=json.loads(artifact.read_text());raw['rows'][0]['name']='tampered after publication'
    artifact.write_text(json.dumps(raw))
    repeated=runner.tick(DATE,datetime(2026,9,15,9,35,5,tzinfo=SH),stage_id='STAGE_0930_0935')
    assert repeated['status']=='PARTIAL_WITH_ROWS',repeated
    assert repeated['markets']['HK_CONNECT']['status']=='CANNOT_CONFIRM',repeated
    assert repeated['markets']['A_SHARE']['selection_status'] in {'READY','PARTIAL_WITH_ROWS'}
    assert len(calls)==4


def test_cli_large_output_prioritizes_market_first_errors_within_byte_budget(capsys):
    healthy=[{'stage_id':f'STAGE_{n}', 'status':'READY', 'padding':'x'*6000} for n in range(5)]
    failed={'stage_id':'STAGE_0930_0935', 'status':'CANNOT_CONFIRM',
            'error':'源证据错误'*200,
            'markets':{'A_SHARE':{'status':'CANNOT_CONFIRM','first_error':'A_SHA_MISMATCH:'+'来源异常'*200},
                       'HK_CONNECT':{'status':'CANNOT_CONFIRM','cannot_confirm':['HK_D1_MISSING:'+'证据缺失'*200]}}}
    nodes._print_json({'trade_date':DATE,'status':'NODES_PARTIAL','nodes':[*healthy,failed],**FLAGS})
    output=capsys.readouterr().out.strip()
    assert len(output.encode())<=4095
    value=json.loads(output)
    assert value['output_truncated'] is True
    assert 'A_SHA_MISMATCH' in output and 'HK_D1_MISSING' in output


def test_hk_source_changes_during_transport_remains_lane_local(tmp_path,monkeypatch):
    config=bound_config(tmp_path);publish_research_fixture(config)
    artifact=Path(config['hk_d1_root'])/f'preselection_pools/{DATE}/hkconnect_d1_top100.json'
    def mutate():
        raw=json.loads(artifact.read_text());raw['rows'][0]['name']='changed during collection'
        artifact.write_text(json.dumps(raw))
    calls=stage_transport(monkeypatch,after_snapshot=mutate)
    result=runner_for(config).tick(DATE,datetime(2026,9,15,9,35,5,tzinfo=SH),stage_id='STAGE_0930_0935')
    assert result['status']=='PARTIAL_WITH_ROWS',result
    assert result['markets']['A_SHARE']['selection_status'] in {'READY','PARTIAL_WITH_ROWS'},result
    assert result['markets']['HK_CONNECT']['status']=='CANNOT_CONFIRM'
    assert len(calls)==4
