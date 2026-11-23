"""ACT015 stage 1: bounded full-A natural features, D-only S labels and mature H5 rank labels.

No fitting. No 2026 outcome labels. Raw V4 histories stay in memory only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import shutil
import time
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops.pft_act015_common import *
from ops.pft_act008_b_features import b_frame, frozen_s_gate
from ops.pft_s_full_ashare_features import feature_frame, weak_label_strata
from ops.pft_act010_scan import natural_masks
from ops.pft_act010_replay import fill_status, BUY_FEE, SELL_FEE


def gates(s):
    names = ['wy_spread_pct', 'c_vs_yellow_pct', 'd_upper_shadow_pct', 'd_vr5', 'dd_from_pk30_pct', 'd_amp_pct']
    known = np.isfinite(s[names]).all(axis=1)
    g1 = s.wy_spread_pct.gt(0)
    g2 = (s.c_vs_yellow_pct.ge(25) & s.d_upper_shadow_pct.ge(4) & s.d_vr5.ge(1.5)) | (s.dd_from_pk30_pct.le(-22) & s.d_amp_pct.ge(8))
    # weak_label_strata sees the same revised G2 as actual frozen gate.
    out = s.copy()
    out['g1_wy_pass'] = g1.astype(float).where(known)
    out['g2_s26_reject'] = g2.astype(float).where(known)
    out['gate_pass'] = (g1 & ~g2).astype(float).where(known)
    return out


def rank_labels(h, dates, sessions):
    """Exact D+5 and D+1, with no missing/halted path silently carried for training."""
    lookup = h.set_index('trade_date').to_dict('index')
    index = {d: i for i, d in enumerate(sessions)}
    result = []
    for day in dates:
        item = {'D': day, 'target_end': '', 'rank_status': 'D_NOT_IN_CALENDAR',
                'rank_net_return_pct': np.nan, 'rank_mdd_pct': np.nan, 'rank_target': np.nan}
        if day not in index:
            raise ValueError('SIGNAL_D_ABSENT_FROZEN_CALENDAR:' + day)
        i = index[day]
        target = sessions[i+5] if i+5 < len(sessions) else ''
        item['target_end'] = target
        if day >= '20260101':
            raise ValueError('2026_OUTCOME_LABEL_FORBIDDEN')
        if not target or target > '20251231':
            item['rank_status'] = 'TARGET_AFTER_TRAIN_ALLOWED_RANGE'
        else:
            path = sessions[i+1:i+6]
            entry = lookup.get(path[0])
            buy = fill_status(entry, 'BUY')
            sell = fill_status(lookup.get(target), 'SELL')
            known = all(d in lookup and np.isfinite(float(lookup[d]['close'])) and float(lookup[d]['close']) > 0
                        and float(lookup[d]['tradeable_basic']) == 1 and float(lookup[d]['vol']) > 0 for d in path)
            if buy != 'FILLED':
                item['rank_status'] = 'ENTRY_' + buy
            elif sell != 'FILLED':
                item['rank_status'] = 'EXIT_' + sell
            elif not known:
                item['rank_status'] = 'PATH_UNKNOWN'
            else:
                entry_price = float(entry['open'])
                equity = np.array([float(lookup[d]['close']) * (1-SELL_FEE) / (entry_price*(1+BUY_FEE)) for d in path])
                peak = np.maximum.accumulate(np.r_[1., equity])[1:]
                mdd = min(0., float(np.min(equity / peak - 1))) * 100
                ret = (equity[-1] - 1) * 100
                item.update(rank_status='VALID', rank_net_return_pct=ret, rank_mdd_pct=mdd, rank_target=ret+.5*mdd)
        result.append(item)
    return pd.DataFrame(result, columns=['D', 'target_end', 'rank_status', 'rank_net_return_pct', 'rank_mdd_pct', 'rank_target'])


def project_security(task):
    canonical, frame, crosswalk, sessions = task
    h = canonical_history(frame, crosswalk)
    if h.empty:
        return pd.DataFrame(), pd.DataFrame(), {'canonical_security_id': canonical, 'history_rows': 0}
    b, s = b_frame(h), gates(feature_frame(h))
    # Actual early and late prefix parity for each issuer, without recomputing every D.
    checks = sorted({min(len(h), 80), max(1, len(h)-20)})
    for cut in checks:
        ps = gates(feature_frame(h.iloc[:cut]))
        pb = b_frame(h.iloc[:cut])
        pd.testing.assert_frame_equal(ps, s.iloc[:cut].reset_index(drop=True), check_exact=False, rtol=1e-11, atol=1e-11)
        pd.testing.assert_frame_equal(pb, b.iloc[:cut].reset_index(drop=True), check_exact=False, rtol=1e-11, atol=1e-11)
    if (s.prior_anchor_date.ne('') & s.prior_anchor_date.ge(s.trade_date)).any():
        raise ValueError('ANCHOR_NOT_PRIOR_D')
    base = pd.concat([b[list(BASE_FEATURES)], s[list(BRANCH_FEATURES)].add_prefix('S_'),
                      s[list(S_FEATURES)].add_prefix('pure_s_')], axis=1)
    base.insert(0, 'D', b.trade_date.astype(str))
    base.insert(0, 'canonical_security_id', canonical)
    base['gate'] = s.gate_pass
    base['prior_anchor_date'] = s.prior_anchor_date
    base['prior_anchor_low'] = s.prior_anchor_low
    base['eligible'] = b.eligible
    base['outer'] = bucket(canonical)
    base['inner'] = bucket(canonical, 'INNER')
    masks = natural_masks(h, b)
    natural = []
    for lane in LANES:
        raw, near = masks[lane]
        selected = raw | near
        out = base.loc[selected].copy()
        out['lane'] = lane
        out['raw_trigger'] = raw.loc[selected]
        out['near_trigger'] = near.loc[selected]
        for name in ['label', 'stratum', 'reason', 'formula_mismatch', 'original', 'recomputed']:
            out[name] = b.loc[selected, f'{lane}_{name}']
        out['episode_id'] = [digest(f'ACT015|{canonical}|{day}|{lane}')[:24] for day in out.D]
        natural.append(out)
    natural = pd.concat(natural, ignore_index=True)
    label_dates = sorted(set(natural.loc[natural.D.lt('20260101'), 'D']))
    labels = rank_labels(h, label_dates, sessions)
    natural = natural.merge(labels, on='D', how='left', validate='many_to_one')
    natural['rank_status'] = natural.rank_status.fillna('OOS_2026_NOT_READ')
    # Sample D BEFORE weak truth; 64 dates per code/year, no outcome conditioning.
    sample = base.loc[base.D.lt('20260101') & base.eligible].copy()
    sample['_sample'] = [digest(f'ACT015|S_D|{canonical}|{d}') for d in sample.D]
    sample['_year'] = sample.D.str[:4]
    sample = sample.sort_values('_sample').groupby('_year', sort=True).head(S_PRESAMPLE_PER_CODE_YEAR).copy()
    strata = [weak_label_strata(s.loc[i].to_dict()) for i in sample.index]
    sample['S_label'] = [int(v[0][0] == 'TRUE') if v else np.nan for v in strata]
    sample['S_stratum'] = [v[0][1] if v else 'UNKNOWN' for v in strata]
    sample = sample.drop(columns=['_sample', '_year'])
    stats = {'canonical_security_id': canonical, 'outer': bucket(canonical), 'inner': bucket(canonical, 'INNER'),
             'history_rows': len(h), 'natural_rows': len(natural), 'S_presampled_D': len(sample),
             'S_known': int(sample.S_label.notna().sum()), 'prefix_parity_checks': len(checks)}
    for lane in LANES:
        sub = natural[natural.lane.eq(lane)]
        stats[lane+'_natural'] = len(sub)
        stats[lane+'_unknown'] = int(sub.label.isna().sum())
        stats[lane+'_formula_mismatch'] = int(sub.formula_mismatch.sum())
        stats[lane+'_raw_short_history'] = int((sub.raw_trigger & ~sub.eligible).sum())
    return natural, sample, stats


def worker_init():
    for name in ['OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'VECLIB_MAXIMUM_THREADS']:
        os.environ[name] = '1'
    from threadpoolctl import threadpool_limits
    threadpool_limits(1)


def project(*, act005_root, data_root, market_dir, output_dir, workers=16, batch_size=128, canary_codes=None):
    from ops import pft_s_first_baseline as baseline
    from ops import research_panel_logical as reader
    if not 1 <= workers <= 18:
        raise ValueError('WORKERS_1_TO_18')
    if shutil.disk_usage(output_dir.parent).free < 12*1024**3:
        raise ValueError('PROJECTION_SPACE_BUDGET_UNAVAILABLE')
    frozen = old._validate_inputs(act005_root)
    stage = new_stage(output_dir)
    (stage/'shards').mkdir()
    outputs, stats, counts = {}, [], Counter()
    started = time.monotonic()
    worker_init()
    with baseline.bind_current_panels(data_root) as (path, source, recheck):
        assert_source(source, frozen)
        aliases, groups, crosswalk = observed_universe(path, reader)
        full_count = len(groups)
        if canary_codes:
            if not set(canary_codes) <= set(groups):
                raise ValueError('CANARY_UNKNOWN_CANONICAL')
            groups = {c: groups[c] for c in sorted(set(canary_codes))}
        market, sessions, market_manifest, calendar_info = calendar(market_dir, source)
        schema = reader.parquet.read_schema(path)
        mapping, _ = panel_columns(schema)
        names = old._schema_names(schema)
        for field in ['limit_up_approx', 'limit_down_approx']:
            if field not in names:
                raise ValueError('FILL_FIELD_MISSING:' + field)
            mapping[field] = names[field]
        executor = ProcessPoolExecutor(max_workers=workers, initializer=worker_init) if workers > 1 else None
        try:
            for cohort_no, raw_codes in enumerate(cohorts(groups, batch_size)):
                frame = read_cohort(path, schema, mapping, raw_codes, reader)
                frame['canonical_security_id'] = frame.ts_code.map(aliases)
                tasks = ((code, chunk.drop(columns='canonical_security_id'), crosswalk, sessions)
                         for code, chunk in frame.groupby('canonical_security_id', sort=True))
                iterator = executor.map(project_security, tasks, chunksize=1) if executor else map(project_security, tasks)
                natural, s_train = [], []
                for n, s, stat in iterator:
                    natural.append(n); s_train.append(s); stats.append(stat)
                for suffix, parts in [('natural', natural), ('s_train', s_train)]:
                    combined = pd.concat(parts, ignore_index=True).replace([np.inf, -np.inf], np.nan) if parts else pd.DataFrame()
                    name = f'shards/{cohort_no:04d}_{suffix}.parquet'
                    combined.to_parquet(stage/name, index=False, compression='zstd')
                    outputs[name] = old._sha_file(stage/name)
                    counts[suffix+'_rows'] += len(combined)
                counts['history_rows_read'] += len(frame)
                total_bytes = sum((stage/p).stat().st_size for p in outputs)
                if total_bytes > 6*1024**3:
                    raise ValueError('PROJECTION_DISK_BUDGET_EXCEEDED')
                progress = {'stage': 'PROJECT', 'codes': len(stats), 'total_codes': len(groups), 'cohort': cohort_no,
                            'elapsed_seconds': time.monotonic()-started, 'bytes': total_bytes, 'counts': dict(counts)}
                write_json(stage/'progress.json', progress)
                print(json.dumps(progress, sort_keys=True), flush=True)
        finally:
            if executor:
                executor.shutdown(wait=True)
        recheck()
    universe = pd.DataFrame(stats).sort_values('canonical_security_id')
    if len(universe) != len(groups):
        raise ValueError('CANONICAL_COVERAGE_MISMATCH')
    universe.to_csv(stage/'universe.csv', index=False)
    outputs['universe.csv'] = old._sha_file(stage/'universe.csv')
    return finish_manifest(stage, output_dir, 'projection_manifest.json', {
        'schema': 'ACT015_PROJECT_V1', 'mode': 'CANARY' if canary_codes else 'FULL', 'source': source,
        'range': [START, ASOF], 'full_observed_canonical_count': full_count, 'projected_canonical_count': len(groups),
        'counts': dict(counts), 'outputs_sha256': outputs, 'sessions': sessions,
        'market_dir': str(market_dir), 'market_manifest_sha256': old._sha_file(market_dir/'market_manifest.json'),
        'calendar': calendar_info, 'folds': FOLDS, 'caps': CAPS, 'S_D_presample_per_code_year': S_PRESAMPLE_PER_CODE_YEAR,
        'code_sha256': {str(p): old._sha_file(p) for p in [Path(__file__), ROOT/'ops/pft_act015_common.py',
            ROOT/'ops/pft_act008_b_features.py', ROOT/'ops/pft_s_full_ashare_features.py', ROOT/'ops/pft_act010_scan.py']},
        'crosswalk_sha256': old._sha_file(old.CROSSWALK_FILE), 'workers': workers, 'batch_size': batch_size,
        'actual_fit_calls': 0, '2026_outcome_labels_read': False, 'S_weak_G2': 'REVISED_FROZEN_G2_WITHOUT_GE35',
        'source_PIT': 'CANNOT_CONFIRM; current frozen QFQ generation, no historical vintage claim',
        'scratch_lifecycle': 'derived-only shards; retain until model/replay/archive validated, controller cleanup only'})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['act005-root', 'data-root', 'market-dir', 'output-dir']:
        p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--workers', type=int, default=16)
    p.add_argument('--batch-size', type=int, default=128)
    p.add_argument('--canary-codes')
    a = vars(p.parse_args(argv))
    a['canary_codes'] = a['canary_codes'].split(',') if a['canary_codes'] else None
    try:
        result = project(**a)
    except Exception as exc:
        return cli_failure(exc)
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
