"""Only Stage history capacity changes; original trust checks still execute."""
import ast
import importlib.util
import json
from pathlib import Path

import pytest

SOURCE = Path(__file__).parents[1] / 'docs/handoffs/stage_witness_owner_20261112/STAGE_manager_input_attestation.after.py'
spec = importlib.util.spec_from_file_location('stage_witness_capacity', SOURCE)
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')))


def seal(app, release, files):
    entries = []
    for rel, raw in sorted(files.items()):
        p = app / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(raw)
        entries.append(dict(path=rel, kind='file', size=len(raw), sha256=m.digest(raw)))
    manifest = dict(schema_version='v4.runtime_graph_repair_release.v1', app_root=str(app),
        release_id=release, RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False,
        orders_sent=False, application_inventory=dict(entries=entries, entry_count=len(entries),
        aggregate_sha256=m.digest(json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode())))
    path = app.parent / 'release-manifest.json'; write_json(path, manifest)
    return dict(app_root=str(app), release_id=release, manifest_sha256=m.digest(path.read_bytes()))


def fixture(tmp_path, monkeypatch, n):
    root = tmp_path / 'data'; root.mkdir(); ledger = tmp_path / 'ledger'; ledger.mkdir()
    current_files = {x: ('fixture source:' + x).encode() for x in m._MAIN_RESEARCH_FILES}
    current = seal(tmp_path / 'current/app', 'current', current_files)
    owners = [seal(tmp_path / f'history{i}/app', f'history{i}', current_files) for i in range(n)]
    transition = seal(tmp_path / 'transition/app', 'transition', current_files)
    config = dict(schema_version='stage_center.tick_config.v1', v4_research_data_root=str(root),
        research_owner_binding=current, research_scheduler_ledger_root=str(ledger),
        research_historical_owner_bindings=owners,
        research_transition_owner_binding=dict(transition, trade_date='20261106'))
    app = tmp_path / 'stage/app'
    stage_files = {x: ('stage fixture:' + x).encode() for x in m._STAGE_RESEARCH_FILES}
    def reseal():
        stage_files['stage_center_tick_config.json'] = json.dumps(config).encode()
        binding = seal(app, 'stage', stage_files)
        for key, value in dict(V4_APP_ROOT=str(app), V4_RELEASE_ID='stage',
            V4_RELEASE_MANIFEST_PATH=str(app.parent / 'release-manifest.json'),
            V4_RELEASE_MANIFEST_SHA256=binding['manifest_sha256'],
            STAGE_CENTER_CONFIG=str(app / 'stage_center_tick_config.json')).items():
            monkeypatch.setenv(key, value)
    reseal()
    write_json(root / 'research/hourly/publication/live/20261111/0900.json',
               dict(materializer_sha256=m.digest(current_files['ops/run_hourly_research.py'])))
    write_json(root / 'research/incoming/20261111/0900.json.publication.json',
               dict(owner_code=dict(publication_writer_sha256=m.digest(current_files['infrastructure/manager_input_attestation.py']))))
    calls = []
    def completion(**kwargs):
        calls.append(kwargs)
        return dict(completion_witness=dict(owner=str(kwargs['owner_root'])))
    monkeypatch.setattr(m, 'read_hourly_attestation', completion)
    return app, root, config, reseal, calls


def read(app, root, **kwargs):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    args = dict(stage_app=app, data_root=root, date='20261111', slot='0900', mode='LIVE',
                as_of=datetime(2026, 11, 11, 9, 45, tzinfo=ZoneInfo('Asia/Shanghai')))
    args.update(kwargs)
    return m.read_stage_hourly_attestation(**args)


@pytest.mark.parametrize('count', [9, 16])
def test_sealed_nine_and_sixteen_identities_pass_original_validation(tmp_path, monkeypatch, count):
    app, root, config, reseal, calls = fixture(tmp_path, monkeypatch, count)
    result, evidence = read(app, root)
    assert result['completion_witness']['owner'] == config['research_owner_binding']['app_root']
    assert len(calls) == 1


def test_original_eight_cap_reproduces_real_ninth_identity_block(tmp_path, monkeypatch):
    app, root, config, reseal, calls = fixture(tmp_path, monkeypatch, 9)
    source = SOURCE.read_text().replace('len(historical) > 16:', 'len(historical) > 8:')
    tree = ast.parse(source)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'read_stage_hourly_attestation')
    env = dict(m.__dict__); exec(compile(ast.Module(body=[fn], type_ignores=[]), str(SOURCE), 'exec'), env)
    with pytest.raises(m.PublicationError, match='HOURLY_PROVENANCE_ALLOWLIST_INVALID'):
        env['read_stage_hourly_attestation'](stage_app=app, data_root=root, date='20261111', slot='0900', mode='LIVE', as_of=None)
    assert calls == []


def test_seventeenth_identity_rejected_before_completion_lookup(tmp_path, monkeypatch):
    app, root, config, reseal, calls = fixture(tmp_path, monkeypatch, 17)
    with pytest.raises(m.PublicationError, match='HOURLY_PROVENANCE_ALLOWLIST_INVALID'):
        read(app, root)
    assert calls == []


@pytest.mark.parametrize('invalid,error', [
    ('duplicate', 'HOURLY_PROVENANCE_ALLOWLIST_INVALID'),
    ('current_duplicate', 'HOURLY_PROVENANCE_ALLOWLIST_INVALID'),
    ('extra_field', 'HOURLY_PROVENANCE_ALLOWLIST_INVALID'),
    ('manifest_sha', 'RESEARCH_RELEASE_MANIFEST_SHA_MISMATCH'),
    ('source_bytes', 'RESEARCH_RELEASE_CODE_OR_CONFIG_DRIFT'),
    ('release_id', 'RESEARCH_RELEASE_IDENTITY_MISMATCH'),
    ('transition_day', 'HOURLY_PROVENANCE_TRANSITION_INVALID'),
])
def test_invalid_identity_still_fails_closed(tmp_path, monkeypatch, invalid, error):
    app, root, config, reseal, calls = fixture(tmp_path, monkeypatch, 9)
    row = config['research_historical_owner_bindings'][-1]
    if invalid == 'duplicate': config['research_historical_owner_bindings'][-1] = config['research_historical_owner_bindings'][0]
    elif invalid == 'current_duplicate': config['research_historical_owner_bindings'][-1] = config['research_owner_binding']
    elif invalid == 'extra_field': row['unknown'] = 'not allowed'
    elif invalid == 'manifest_sha': row['manifest_sha256'] = 'f' * 64
    elif invalid == 'release_id': row['release_id'] = 'wrong'
    elif invalid == 'source_bytes': (Path(row['app_root']) / 'ops/run_hourly_research.py').write_text('changed')
    elif invalid == 'transition_day': config['research_transition_owner_binding']['trade_date'] = 'unknown'
    reseal()
    with pytest.raises(m.PublicationError, match=error): read(app, root)
    assert calls == []


@pytest.mark.parametrize('request_case', [dict(date='2026111'), dict(slot='09000'), dict(mode='REPLAY')])
def test_date_slot_mode_contract_unchanged(tmp_path, monkeypatch, request_case):
    app, root, config, reseal, calls = fixture(tmp_path, monkeypatch, 9)
    with pytest.raises(m.PublicationError, match='HOURLY_PROVENANCE_REQUEST_INVALID'): read(app, root, **request_case)
    assert calls == []


def test_same_code_bytes_do_not_substitute_original_release_completion(tmp_path, monkeypatch):
    app, root, config, reseal, calls = fixture(tmp_path, monkeypatch, 9)
    selected = config['research_historical_owner_bindings'][-1]['app_root']
    def actual_release_only(**kwargs):
        calls.append(kwargs)
        if str(kwargs['owner_root']) != selected:
            raise m.PublicationError('HOURLY_COMPLETION_WITNESS_MISSING')
        return dict(completion_witness=dict(owner=selected))
    monkeypatch.setattr(m, 'read_hourly_attestation', actual_release_only)
    result, evidence = read(app, root)
    assert len(calls) == 10 and result['completion_witness']['owner'] == selected
    assert any('historical_owner_release_id=history8' in item for item in evidence)


def test_pit_or_source_failure_is_not_hidden_by_trying_next_owner(tmp_path, monkeypatch):
    app, root, config, reseal, calls = fixture(tmp_path, monkeypatch, 9)
    def actual_failure(**kwargs):
        calls.append(kwargs); raise m.PublicationError('HOURLY_PUBLICATION_AFTER_AS_OF')
    monkeypatch.setattr(m, 'read_hourly_attestation', actual_failure)
    with pytest.raises(m.PublicationError, match='HOURLY_PUBLICATION_AFTER_AS_OF'): read(app, root)
    assert len(calls) == 1
