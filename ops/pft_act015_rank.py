"""ACT015 stage 2b: prospective ranked selection ledger, sealed before execution reads."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops.pft_act015_common import *
from ops.pft_act015_replay import POOLS, regimes, select_signals


def verified_predictions(fit_dir):
    m = read_manifest(fit_dir, 'fit_manifest.json')
    if m['mode'] != 'FULL' or m['actual_successful_fit_calls'] != 80:
        raise ValueError('EIGHTY_FIT_FULL_SEAL_REQUIRED')
    seal = old._read_json(fit_dir/'pre_replay_seal.json')
    if seal['fit_calls'] != 80 or seal['prediction_outcomes_read'] is not False:
        raise ValueError('INVALID_PRE_REPLAY_SEAL')
    frames = [pd.read_parquet(fit_dir/r) for r in sorted(m['outputs_sha256']) if r.startswith('predictions/')]
    predictions = pd.concat(frames, ignore_index=True)
    if predictions.episode_id.duplicated().any() or predictions.duplicated([*IDENTITY, 'lane']).any():
        raise ValueError('OOS_HALVES_OVERLAP')
    if not predictions.model_year.astype(str).eq(predictions.D.str[:4]).all() or not predictions.outer.eq(predictions.held_outer).all():
        raise ValueError('YEAR_OR_ISSUER_PREDICTION_JOIN_ERROR')
    return m, predictions


def rank(*, fit_dir, market_dir, output_dir):
    m, predictions = verified_predictions(fit_dir)
    market, sessions, market_manifest, calendar_info = calendar(market_dir, m['source'])
    if sessions != m['sessions']:
        raise ValueError('FIT_RANK_CALENDAR_DRIFT')
    selected, counts = [], []
    for pool in POOLS:
        picks = select_signals(predictions, pool)
        for day, rows in picks.items():
            for position, row in enumerate(rows, 1):
                selected.append({**row, 'pool': pool, 'rank_position': position})
        counts.append({'pool': pool, 'selected': sum(map(len, picks.values())), 'selected_days': len(picks),
                       'selected_by_year': dict(pd.Series([d[:4] for d, rows in picks.items() for _ in rows], dtype=str).value_counts())})
    columns = [*predictions.columns, 'pool', 'rank_position']
    ranked = pd.DataFrame(selected, columns=columns).sort_values(['pool', 'D', 'rank_position']).reset_index(drop=True)
    stage = new_stage(output_dir)
    ranked.to_parquet(stage/'ranked_signals.parquet', index=False, compression='zstd')
    regimes(market).to_csv(stage/'causal_regimes.csv', index=False, float_format='%.17g')
    outputs = {p.name: old._sha_file(p) for p in stage.iterdir() if p.is_file()}
    return finish_manifest(stage, output_dir, 'rank_manifest.json', {
        'schema': 'ACT015_PROSPECTIVE_RANK_V1', 'mode': 'FULL', 'source': m['source'], 'outputs_sha256': outputs,
        'fit_manifest_sha256': old._sha_file(fit_dir/'fit_manifest.json'),
        'pre_replay_seal_sha256': old._sha_file(fit_dir/'pre_replay_seal.json'),
        'market_manifest_sha256': old._sha_file(market_dir/'market_manifest.json'),
        'calendar': calendar_info, 'sessions': sessions, 'selection_counts': counts,
        'prediction_counts_by_model_year': predictions.groupby('model_year').size().to_dict(),
        'execution_market_read': False, 'fit_calls': 0, 'thresholds': {'S': .5, 'B': .5},
        'same_selected_signals_all_scenarios_and_horizons': True,
        'code_sha256': {str(p): old._sha_file(p) for p in [Path(__file__), ROOT/'ops/pft_act015_replay.py', ROOT/'ops/pft_act015_common.py']}})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['fit-dir', 'market-dir', 'output-dir']:
        p.add_argument('--'+name, type=Path, required=True)
    try:
        result = rank(**vars(p.parse_args(argv)))
    except Exception as exc:
        return cli_failure(exc)
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
