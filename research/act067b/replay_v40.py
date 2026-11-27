"""Read-only replay of exactly the frozen ACT-065A source in an isolated process."""

from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path

import pandas as pd

from semantic_shadow import SYMBOL, as_date, read_cohort, sha256, through_sessions

SOURCE_SHA = 'd67612f90bb1b88b3262353e6329029a570caf994a950a45032c333091eb7ac9'
SOURCE_ID = '1iaEXGai1B0GxoyQ-0RAQwDdk0tWIYMZU'


def frozen_module(source):
    payload = source.read_bytes()
    if hashlib.sha256(payload).hexdigest() != SOURCE_SHA:
        raise ValueError('Frozen ACT-065A source hash mismatch')
    tree = ast.parse(payload, filename=str(source))
    imports = {alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    if imports != {'hashlib', 'os', 'pandas', 'numpy'} or any(isinstance(node, ast.ImportFrom) for node in ast.walk(tree)):
        raise ValueError('Unexpected frozen source imports')
    scope = {'__name__': 'act067b_frozen_readonly'}
    exec(compile(tree, str(source), 'exec'), scope)
    if (scope['ENGINE_VERSION'], scope['ACTION_ID']) != ('V4.0', 'ACT-065A'):
        raise ValueError('Unexpected frozen source version')
    return scope



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    timeline = args.inputs/'timeline_d_only.csv'
    timeline_provenance = json.loads((args.inputs/'timeline_provenance.json').read_bytes())
    cohort = read_cohort(sorted(args.inputs.glob('sheet_*.json')))
    if sha256(timeline) != timeline_provenance['projection_sha256'] or as_date(timeline_provenance['engine_ceiling']) != max(cohort):
        raise ValueError('Timeline projection identity/cutoff mismatch')
    sessions = list(through_sessions(timeline, max(cohort)))
    if len(sessions) != timeline_provenance['session_rows']:
        raise ValueError('Timeline projected session count mismatch')
    frame = pd.DataFrame([{'date': str(s.day), 'open': s.open, 'high': s.high, 'low': s.low,
                           'close': s.close, 'volume': s.volume} for s in sessions])
    if any(sessions[row['td_idx']].day != day for day, row in cohort.items()):
        raise ValueError('Stock trading-session index differs from historical cohort')
    frozen = frozen_module(args.inputs/'v40_source_readonly.py.txt')
    listing_date = '2017-04-25'
    if str(sessions[0].day) != listing_date:
        raise ValueError('Replay requires the complete listing-origin history')

    def compute_history(data):
        common = frozen['compute_indicators_d_only'](data, SYMBOL, listing_date)
        legacy, _ = frozen['run_v40_engine'](data, SYMBOL, '钧达股份', listing_date)
        return common, legacy

    common, legacy = compute_history(frame)
    ordered_days = list(cohort)
    checked = []
    for offset in (10, len(ordered_days)//2, len(ordered_days)-10):
        day = ordered_days[offset]
        count = cohort[day]['td_idx'] + 1
        common_prefix, legacy_prefix = compute_history(frame.iloc[:count])
        pd.testing.assert_frame_equal(common_prefix, common.iloc[:count], check_exact=True)
        pd.testing.assert_frame_equal(legacy_prefix, legacy.loc[legacy.date <= str(day)], check_exact=True)
        checked.append(str(day))
    common_columns = ['date', 'open', 'high', 'low', 'close', 'volume', 'pct_chg', 'W', 'Y', 'BBI', 'J']
    mapped = {str(day): row['td_idx'] for day, row in cohort.items()}
    legacy_rows = legacy.loc[legacy.date.isin(mapped)].to_dict(orient='records')
    target_columns = ('date', 'td_idx', 'formula_hit_tags', 'new_entry_qualified_tags', 'new_entry_status', 'new_entry_watch_tags',
                      'new_entry_rejected_tags', 'frozen_raw_only_tags', 'm25_chain_complete', 'm25_d_date', 'm25_t_date', 'm25_c_date')
    if any(row['td_idx'] != mapped[row['date']] for row in legacy_rows):
        raise ValueError('Replayed signal index differs from cohort')
    args.evidence.mkdir(parents=True, exist_ok=True)
    indicators_path = args.evidence/'common_indicators_d_only.csv'
    replay_path = args.evidence/'v40_same_input_replay.csv'
    common[common_columns].to_csv(indicators_path, index=False, na_rep='')
    with replay_path.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, target_columns, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(legacy_rows)
    receipt = {
        'RESEARCH_ONLY': True, 'S_FIT': 0, 'B_FIT': 0,
        'source_drive_file_id': SOURCE_ID, 'v40_source_sha256': SOURCE_SHA,
        'source_timeline_sha256': sha256(timeline), 'source_generation': timeline_provenance['generation'],
        'listing_date': listing_date, 'engine_ceiling': str(max(cohort)), 'session_rows': len(sessions),
        'pandas_version': pd.__version__, 'prefix_equivalence_dates': checked,
        'equivalence_assertion': 'exact full result frame prefix and all computed indicator columns',
        'same_input_replay_signal_rows': len(legacy_rows), 'cohort_rows': len(cohort),
        'common_indicators_sha256': sha256(indicators_path), 'v40_replay_sha256': sha256(replay_path),
    }
    (args.evidence/'v40_replay_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == '__main__':
    main()
