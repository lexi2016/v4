"""ACT016 causal annual calibration and pre-execution signal projection. No fits."""
from __future__ import annotations
from pathlib import Path
import numpy as np
import pandas as pd
from ops import pft_act015_common as c
from ops.pft_act015_rank import verified_predictions

STARTER_COLUMNS = ['episode_id', 'D', 'canonical_security_id', 'lane', 'S_prob_gated',
                   'B_probability', 'rank_score', 'hard_eligible']
SCENARIOS = [('BASELINE_STRICT', None, False), ('EXPANDING_HYBRID', None, False),
             ('EXPANDING_HYBRID_SL5', .05, False), ('EXPANDING_HYBRID_SL7', .07, False),
             ('EXPANDING_HYBRID_LIQ1E8', None, True),
             ('EXPANDING_HYBRID_SL5_LIQ1E8', .05, True),
             ('EXPANDING_HYBRID_SL7_LIQ1E8', .07, True)]


def hard_mask(f):
    return (f.hard_eligible.eq(True) & f.S_prob_gated.ge(.5) & f.B_probability.ge(.5)
            & np.isfinite(f.rank_score))


def annual_thresholds(market, predictions, starter):
    """Previous calendar years only; lane q80 uses pooled issuer-held-out RF scores."""
    m = market.sort_values('D').copy()
    if m.D.duplicated().any():
        raise ValueError('DUPLICATE_MARKET_DATE')
    shares = m[['cw_share', 'cy_share', 'wy_share']]
    m['B_comp'] = shares.mean(axis=1).where(np.isfinite(shares).all(axis=1))
    calibration = pd.concat([starter[STARTER_COLUMNS], predictions[STARTER_COLUMNS]], ignore_index=True)
    if calibration.episode_id.duplicated().any():
        raise ValueError('CALIBRATION_EPISODE_OVERLAP')
    result = []
    for year in range(2023, 2027):
        cutoff = f'{year}0101'
        prior = m.loc[m.D.ge('20220101') & m.D.lt(cutoff)]
        if prior.empty or prior.B_comp.isna().any():
            raise ValueError('ANNUAL_MACRO_CALIBRATION_MISSING:'+str(year))
        q33, q67 = np.quantile(prior.B_comp, [1/3, 2/3], method='linear')
        record = dict(year=year, calibration_max_D=str(prior.D.max()), calibration_days=len(prior),
                      q33=float(q33), q67=float(q67))
        for lane in ('B1', 'B2'):
            train = calibration.loc[calibration.D.ge('20220101') & calibration.D.lt(cutoff)
                                    & calibration.lane.eq(lane) & hard_mask(calibration)]
            if train.empty:
                raise ValueError('ANNUAL_Q80_CALIBRATION_MISSING:'+str(year)+':'+lane)
            record[lane+'_q80'] = float(np.quantile(train.rank_score, .8, method='linear'))
            record[lane+'_count'] = len(train)
            record[lane+'_max_D'] = str(train.D.max())
        result.append(record)
    thresholds = pd.DataFrame(result)
    by_year = thresholds.set_index('year').to_dict('index')
    m['graded_state'], m['graded_cap'], m['daily_K'] = 'UNKNOWN', 0., 0
    for i, row in m.iterrows():
        t = by_year.get(int(row.D[:4]))
        if t is None or not np.isfinite(row.B_comp):
            continue
        state, cap, k = ('WEAK', 0., 0) if row.B_comp < t['q33'] else (
            ('STRONG', 1., 3) if row.B_comp >= t['q67'] else ('NEUTRAL', .5, 2))
        m.loc[i, ['graded_state', 'graded_cap', 'daily_K']] = [state, cap, k]
    return thresholds, m


def hybrid_picks(predictions, thresholds, risk, amounts=None):
    """Amount and route eligibility precede TopK; entry failures never cause replacement."""
    f = predictions.loc[hard_mask(predictions) & predictions.D.ge('20230101')].copy()
    if not f.lane.isin(['B1', 'B2', 'B3']).all():
        raise ValueError('UNKNOWN_LANE')
    t = thresholds.set_index('year')
    f['q80_threshold'] = [t.loc[int(d[:4]), lane+'_q80'] if lane in ('B1', 'B2') else np.nan
                          for d, lane in zip(f.D, f.lane)]
    f = f.loc[f.lane.eq('B3') | f.rank_score.ge(f.q80_threshold)].copy()
    f['act015_rank_score'] = f.rank_score
    f['hybrid_score'] = np.where(f.lane.eq('B3'), f.S_prob_gated*f.B_probability, f.rank_score)
    if amounts is not None:
        if amounts.duplicated(c.IDENTITY).any():
            raise ValueError('DUPLICATE_AMOUNT_KEY')
        f = f.merge(amounts[c.IDENTITY+['amount_cny']], on=c.IDENTITY, how='left', validate='many_to_one')
        f = f.loc[np.isfinite(f.amount_cny) & f.amount_cny.ge(100_000_000)].copy()
    # Native score scales deliberately compared across lanes, as parameter card specifies.
    f = f.sort_values(['D', 'hybrid_score', 'canonical_security_id', 'lane'],
                      ascending=[True, False, True, True], kind='mergesort')
    f = f.drop_duplicates(c.IDENTITY, keep='first')
    f['rank_position'] = f.groupby('D').cumcount()+1
    k = risk.set_index('D').daily_K
    f = f.loc[f.rank_position.le(f.D.map(k).fillna(0))].copy()
    # Underlying portfolio consumes rank_score only for audit; preserve RF score as-is.
    return f.reset_index(drop=True)


def validate_seals(fit_dir, rank_dir, act015_replay_dir, market_dir, starter_path, starter_manifest_path):
    m, predictions = verified_predictions(fit_dir)
    rank = c.read_manifest(rank_dir, 'rank_manifest.json')
    replay = c.read_manifest(act015_replay_dir, 'replay_manifest.json')
    fit_sha = c.old._sha_file(fit_dir/'fit_manifest.json')
    rank_sha = c.old._sha_file(rank_dir/'rank_manifest.json')
    market_sha = c.old._sha_file(market_dir/'market_manifest.json')
    seal_sha = c.old._sha_file(fit_dir/'pre_replay_seal.json')
    if (rank['fit_manifest_sha256'] != fit_sha or rank['pre_replay_seal_sha256'] != seal_sha
        or rank['market_manifest_sha256'] != market_sha or rank['execution_market_read'] is not False
        or replay['rank_manifest_sha256'] != rank_sha or replay['fit_manifest_sha256'] != fit_sha
        or replay['market_manifest_sha256'] != market_sha or replay['pre_replay_seal_sha256'] != seal_sha
        or rank['sessions'] != m['sessions']):
        raise ValueError('ACT015_SEAL_CHAIN_DRIFT')
    for artifact in (rank, replay):
        if artifact['source']['identity'] != m['source']['identity'] or artifact['source']['backtest']['panel_sha256'] != m['source']['backtest']['panel_sha256']:
            raise ValueError('ACT015_SOURCE_DRIFT')
    market, sessions, mm, calendar_info = c.calendar(market_dir, m['source'])
    c.verified_file(c.old.CROSSWALK_FILE, mm['crosswalk_sha256'])
    if sessions != m['sessions']:
        raise ValueError('CALENDAR_DRIFT')
    starter_manifest = c.old._read_json(starter_manifest_path)
    if (starter_manifest['batch'] != 'ACT-016' or starter_manifest['fit_calls'] != 0
        or starter_manifest.get('mode') != 'FULL'
        or starter_manifest.get('calibration_model_year') != 2023
        or starter_manifest.get('issuer_held_excluded_from_all_scoring_weights') is not True
        or starter_manifest.get('chronological_2022_oos') is not False
        or starter_manifest.get('date_scope') != ['20220101', '20221231']
        or starter_manifest['fit_manifest_sha256'] != fit_sha
        or starter_manifest['source']['identity'] != m['source']['identity']
        or starter_manifest['source']['backtest']['panel_sha256'] != m['source']['backtest']['panel_sha256']):
        raise ValueError('STARTER_MANIFEST_DRIFT')
    model_hashes = {rel: sha for rel, sha in m['outputs_sha256'].items()
                    if rel.startswith('models/2023_held') and rel.endswith('.joblib') and '/S_INNER_' not in rel}
    if not model_hashes or starter_manifest.get('fit_models_sha256') != model_hashes:
        raise ValueError('STARTER_WEIGHT_IDENTITY_DRIFT')
    c.verified_file(starter_path, starter_manifest['sha256'])
    starter = pd.read_parquet(starter_path, columns=STARTER_COLUMNS)
    if (starter.empty or not starter.D.between('20220101', '20221231').all()
        or starter.episode_id.duplicated().any() or starter.duplicated([*c.IDENTITY, 'lane']).any()
        or len(starter) != starter_manifest['rows']
        or starter.D.min() != starter_manifest['date_min'] or starter.D.max() != starter_manifest['date_max']):
        raise ValueError('STARTER_RANGE_OR_IDENTITY_DRIFT')
    return m, predictions, market, sessions, calendar_info, starter


def read_amounts(*, data_root, act005_root, fit_manifest, predictions, turnover_unit):
    """Selected symbol/date/column projection through current canonical V4 Reader."""
    if turnover_unit != 'CNY_RAW':
        raise ValueError('VERIFIED_RAW_TURNOVER_CNY_REQUIRED')
    from ops import pft_s_first_baseline as baseline
    from ops import research_panel_logical as reader
    frozen = c.old._validate_inputs(act005_root)
    keys = predictions.loc[hard_mask(predictions), c.IDENTITY].drop_duplicates()
    codes = set(keys.canonical_security_id)
    result = []
    with baseline.bind_current_panels(data_root) as (path, source, recheck):
        c.assert_source(source, frozen)
        if (source['identity'] != fit_manifest['source']['identity']
            or source['backtest']['panel_sha256'] != fit_manifest['source']['backtest']['panel_sha256']
            or source['identity']['a_market_basis'].get('amount_basis') != 'RAW_TURNOVER'):
            raise ValueError('TURNOVER_SOURCE_DRIFT')
        aliases, groups, crosswalk = c.observed_universe(path, reader)
        if not codes <= set(groups):
            raise ValueError('TURNOVER_CANONICAL_MISSING')
        schema = reader.parquet.read_schema(path)
        actual = c.old._schema_names(schema)
        mapping = {n: actual[n] for n in ['ts_code', 'trade_date', 'amount', 'market_type', 'exchange']}
        for raw_codes in c.cohorts({k: groups[k] for k in sorted(codes)}, 128):
            f = c.read_cohort(path, schema, mapping, raw_codes, reader, lo='20230101')
            f['canonical_security_id'] = f.ts_code.map(aliases)
            for code, part in f.groupby('canonical_security_id', sort=True):
                h = c.canonical_history(part.drop(columns='canonical_security_id'), crosswalk)
                h['canonical_security_id'] = code
                result.append(h.rename(columns={'trade_date': 'D', 'amount': 'amount_cny'})[c.IDENTITY+['amount_cny']].merge(keys, on=c.IDENTITY, how='inner'))
        recheck()
    return pd.concat(result, ignore_index=True) if result else pd.DataFrame(columns=c.IDENTITY+['amount_cny'])
