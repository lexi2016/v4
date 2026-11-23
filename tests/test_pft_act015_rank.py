import pandas as pd
from ops.pft_act015_common import old
from ops import pft_act015_rank as rank


def test_rank_seals_same_selected_signals_before_execution_access(tmp_path, monkeypatch):
    fit_dir = tmp_path/'fit'; fit_dir.mkdir()
    market_dir = tmp_path/'market'; market_dir.mkdir()
    for p in [fit_dir/'fit_manifest.json', fit_dir/'pre_replay_seal.json', market_dir/'market_manifest.json']:
        p.write_text('{}')
    f = pd.DataFrame([{'episode_id': f'{d}|{lane}', 'canonical_security_id': '000001.SZ', 'D': d,
        'lane': lane, 'rank_score': score, 'hard_eligible': True, 'model_year': int(d[:4]),
        'outer': 0, 'held_outer': 0} for d in ['20230103', '20240103', '20250103', '20260105']
        for lane, score in [('B1', 1.), ('B2', 2.), ('B3', 3.)]])
    sessions = sorted(f.D.unique())
    manifest = {'source': {}, 'sessions': sessions}
    monkeypatch.setattr(rank, 'verified_predictions', lambda _: (manifest, f))
    market = pd.DataFrame({'D': sessions, 'cw_share': .6, 'cy_share': .6, 'wy_share': .6})
    monkeypatch.setattr(rank, 'calendar', lambda *args: (market, sessions, {}, {}))
    out = tmp_path/'ranked'
    receipt = rank.rank(fit_dir=fit_dir, market_dir=market_dir, output_dir=out)
    assert receipt['status'] == 'SEALED'
    m = old._read_json(out/'rank_manifest.json')
    assert m['execution_market_read'] is False
    assert m['same_selected_signals_all_scenarios_and_horizons'] is True
    ranked = pd.read_parquet(out/'ranked_signals.parquet')
    assert len(ranked) == 20  # 5 pools x 4 model years, dedup each issuer+D.
    assert ranked.loc[ranked.pool.eq('ALL'), 'lane'].eq('B3').all()
    for rel, sha in m['outputs_sha256'].items():
        assert old._sha_file(out/rel) == sha
