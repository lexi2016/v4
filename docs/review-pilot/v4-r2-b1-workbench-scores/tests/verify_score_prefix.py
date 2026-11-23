"""Replay the actual score authorities in a composed, isolated Main app."""
import argparse
from datetime import date, timedelta
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory

from ops import materialize_workbench_score_action as candidate


def run_verification(legacy_writer, scratch):
    spec = importlib.util.spec_from_file_location('pre_b1_score_writer', legacy_writer)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    rules = candidate.authority_identity()
    old_rules = legacy.authority_identity()
    assert old_rules in candidate.legacy_rule_maps(rules)
    assert rules[candidate.CALCULATION_MODULE] == candidate.LEGACY_EQUIVALENT_CALCULATION_SHA256

    symbol = '000001.SZ'
    days = [date(2025, 1, 2) + timedelta(days=i) for i in range(230)]
    days = [d.strftime('%Y%m%d') for d in days if d.weekday() < 5][:139]
    rows = []
    for i, day in enumerate(days):
        close = 10. + i / 60 + ((i % 13) - 6) * .03
        rows.append(dict(ts_code=symbol, trade_date=day, open=close * .99, high=close * 1.01,
                         low=close * .98, close=close, volume=(i % 18 + 20) * 100_000.,
                         pre_close=rows[-1]['close'] if rows else close,
                         pct_chg=1., user_v1_sell_signal_daily=False))

    basis = {'price_basis': 'QFQ_ASOF'}
    qualification = {'status': 'CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH'}
    prior_writer = dict(module=candidate.WRITER_MODULE, sha256='a' * 64)
    next_writer = dict(module=candidate.WRITER_MODULE, sha256='b' * 64)

    def project(bars, root, provenance):
        return candidate.project_symbol((symbol, bars, bars[-1]['trade_date'], basis,
                                         str(scratch / root), rules, provenance, qualification))

    initial = project(rows[:138], 'current', prior_writer)
    same = project(rows[:138], 'current', next_writer)
    assert same['reused'] and same['record'] == initial['record']
    assert same['record']['writer_provenance'] == prior_writer
    continued = project(rows, 'current', next_writer)['record']

    legacy.project_symbol((symbol, rows[:138], days[137], basis, str(scratch / 'legacy'),
                           old_rules, qualification))
    migrated = project(rows, 'legacy', next_writer)['record']
    fresh = project(rows, 'fresh', next_writer)['record']
    assert (continued['incremental_prefix_rows'], continued['new_observation_rows']) == (138, 1)
    assert (migrated['incremental_prefix_rows'], migrated['new_observation_rows']) == (138, 1)
    assert (fresh['incremental_prefix_rows'], fresh['new_observation_rows']) == (0, 139)
    for field in ('hold_score', 'action', 'kb', 'input_rows'):
        assert continued[field] == migrated[field] == fresh[field], field

    # These two provenance fields deliberately refer to the actual starting
    # checkpoint when warmed, which the previous calculation already did.
    checkpoint_fields = {'generation_id', 'input_sha256'}
    def n_values(record):
        return {key: value for key, value in record['n_structure'].items()
                if key not in checkpoint_fields}
    assert n_values(continued) == n_values(migrated) == n_values(fresh)
    for record in (continued, migrated, fresh):
        identity = record['recurrence']['n']['identity']
        assert all(record['n_structure'][key] == identity[key] for key in checkpoint_fields)

    changed = [dict(row) for row in rows]
    changed[70]['close'] += 0.001
    invalidated = project(changed, 'current', next_writer)['record']
    assert (invalidated['incremental_prefix_rows'], invalidated['new_observation_rows']) == (0, 139)
    print('PASS: unchanged writer-only cache; new and audited old prefixes 138+1; business parity; changed prefix cold.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-writer', type=Path, required=True)
    args = parser.parse_args()
    with TemporaryDirectory(prefix='v4-b1-score-replay-') as temporary:
        run_verification(args.legacy_writer.resolve(strict=True), Path(temporary))
