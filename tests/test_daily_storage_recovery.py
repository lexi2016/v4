"""Raw-sync serializer accounting: isolated files, no provider calls."""
import json
import types
from pathlib import Path

import pytest

from ops import a_share_daily_sync as source
from ops import research_storage_governance as g
from ops import research_storage_retention as r


@pytest.fixture
def policy(tmp_path, monkeypatch):
    outputs = tmp_path / 'outputs'
    outputs.mkdir()
    monkeypatch.setattr(g.shutil, 'disk_usage', lambda _: types.SimpleNamespace(
        free=400*g.GIB, total=1000*g.GIB))
    return dict(data_root=str(tmp_path), run_root=str(outputs), formal_roots={},
        governance=dict(enabled=True, registry_root=str(tmp_path/'registry'),
            pool_id='isolated', pool_identity_verified=True,
            ordinary_peak_budget_bytes=200*g.GIB))


def test_raw_json_actual_bytes_fit_reservation_and_match_source(policy, tmp_path, monkeypatch):
    payload = {'close': [1.5, None], 'evidence': 'x'*12000, 'name': '中文'}
    expected = tmp_path/'original.json'
    source.write_json(expected, payload)
    # The deployed estimate rejects this exact original serialization even
    # though its actual output plus the retained checkpoint fits the claim.
    assert len(json.dumps(payload, default=str).encode())*2 > 20_000
    checkpoint = Path(policy['run_root'])/'same'/'progress.json'
    checkpoint.parent.mkdir()
    checkpoint.write_bytes(b'original-checkpoint')
    before = r.digest(checkpoint)
    monkeypatch.setattr(source, 'run', lambda _: source.write_json(checkpoint.parent/'summary.json', payload))
    with g.admission(policy, key='same', directory=checkpoint.parent, predicted=20_000) as (claim, _):
        g.guarded_raw_run(source, None, claim)
        assert (checkpoint.parent/'summary.json').read_bytes() == expected.read_bytes()
        assert r.digest(checkpoint) == before
        claim.finish(error=RuntimeError('retain checkpoint'))


def test_raw_csv_actual_serializer_including_unicode_and_nested_rows(policy, tmp_path, monkeypatch):
    rows = [{'symbol': '000001.SZ', 'close': 2.5, 'nested': {'evidence': 'x'*12000}, 'name': '中文,\"值\"'}]
    expected = tmp_path/'original.csv'
    source.write_csv(expected, rows)
    assert len(json.dumps(rows, default=str).encode())*2 > 20_000
    output = Path(policy['run_root'])/'same'/'results.csv'
    monkeypatch.setattr(source, 'run', lambda _: source.write_csv(output, rows))
    with g.admission(policy, key='same', directory=output.parent, predicted=20_000) as (claim, _):
        g.guarded_raw_run(source, None, claim)
        assert output.read_bytes() == expected.read_bytes()
        claim.finish(error=RuntimeError('retain evidence'))


def test_raw_real_exhaustion_still_stops_before_write(policy, monkeypatch):
    output = Path(policy['run_root'])/'same'/'summary.json'
    monkeypatch.setattr(source, 'run', lambda _: source.write_json(output, {'x': 'x'*12000}))
    with pytest.raises(g.SpaceBlocked, match='PREDICTED_PEAK_EXCEEDED'):
        with g.admission(policy, key='same', directory=output.parent, predicted=10_000) as (claim, _):
            g.guarded_raw_run(source, None, claim)
    assert not output.exists()


def test_same_owner_resume_category_and_identity_safety(policy, monkeypatch):
    output = Path(policy['run_root'])/'same'/'summary.json'
    payload = {'close': [1., 2., None], 'evidence': 'x'*8000}
    monkeypatch.setattr(source, 'run', lambda _: source.write_json(output, payload))
    for attempt in (1, 2):
        with g.admission(policy, key='same', directory=output.parent, predicted=20_000) as (claim, _):
            g.guarded_raw_run(source, None, claim)
            claim.checkpoint()
            row = claim.registry.read()['tasks']['same']
            assert row['attempts'] == attempt
            assert row['logical_written_bytes'] == (output.stat().st_size if attempt == 1 else 0)
            claim.finish(error=RuntimeError('resume original'))
    with pytest.raises(r.RetentionError, match='ORIGINAL_DIRECTORY'):
        with g.admission(policy, key='same', directory=output.parent/'other', predicted=20_000):
            pytest.fail('identity drift allowed')
    policy['governance']['ordinary_peak_budget_bytes'] = 10_000
    with pytest.raises(g.SpaceBlocked, match='CATEGORY_BUDGET_BLOCKED'):
        with g.admission(policy, key='same', directory=output.parent, predicted=20_000):
            pytest.fail('genuine category exhaustion allowed')
