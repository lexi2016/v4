"""ACT015 stage 3: sealed ranked signals, strict/graded risk and continuous cash/NAV.

Research fractional lots, directional ACT010 fills, next-open close-triggered
protection. No year-end liquidation and no opening-sale cash advanced to buys.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from ops.pft_act015_common import *
from ops.pft_act010_replay import fill_status, number, BUY_FEE, SELL_FEE
from ops.pft_act013_replay import open_sell_status, valid_mark

POOLS = ('ALL', 'B1_B3', 'B1', 'B2', 'B3')
BAR_FIELDS = ['open', 'high', 'low', 'close', 'vol', 'tradeable_basic',
              'limit_up_approx', 'limit_down_approx', 'zge_yellow_line']


def regimes(market):
    f = market.sort_values('D', kind='mergesort').reset_index(drop=True).copy()
    if f.D.duplicated().any():
        raise ValueError('DUPLICATE_REGIME_DATE')
    shares = f[['cw_share', 'cy_share', 'wy_share']]
    known = np.isfinite(shares).all(axis=1)
    f['score'] = shares.mean(axis=1).where(known)
    prior = f.score.shift(1).rolling(126, min_periods=126)
    f['q40'] = prior.quantile(.4)
    f['q70'] = prior.quantile(.7)
    grade_known = known & f.q40.notna() & f.q70.notna()
    # Weak equality wins when q40 == q70. No EOY or full-period lookup.
    weak = f.score.le(f.q40)
    strong = f.score.ge(f.q70) & ~weak
    f['graded_state'] = np.where(~grade_known, 'UNKNOWN', np.where(weak, 'WEAK', np.where(strong, 'STRONG', 'MID')))
    f['graded_cap'] = np.where(~grade_known | weak, 0., np.where(strong, 1., .5))
    f['strict_state'] = np.where(~known, 'UNKNOWN', np.where(shares.gt(.5).all(axis=1), 'RISK_ON', 'RISK_OFF'))
    f['strict_cap'] = f.strict_state.eq('RISK_ON').astype(float)
    return f


def select_signals(frame, pool, k=3):
    lane_ok = frame.lane.isin(('B1', 'B3')) if pool == 'B1_B3' else (frame.lane.eq(pool) if pool != 'ALL' else pd.Series(True, index=frame.index))
    f = frame.loc[lane_ok & frame.hard_eligible.eq(True) & np.isfinite(frame.rank_score)].copy()
    # Lane is an explicit stable final tiebreak. Highest eligible duplicate wins.
    f = f.sort_values(['D', 'rank_score', 'canonical_security_id', 'lane'], ascending=[True, False, True, True], kind='mergesort')
    f = f.drop_duplicates(['D', 'canonical_security_id'], keep='first')
    f = f.groupby('D', sort=True).head(k)
    return {str(d): rows.to_dict('records') for d, rows in f.groupby('D', sort=True)}


def protection(lot, row, day, scenario, regime):
    reasons = []
    if scenario in ('STRICT', 'STRICT_MATCHED') and regime.get('strict_state') == 'RISK_OFF':
        reasons.append('MACRO')
    if scenario == 'GRADED' and regime.get('graded_state') == 'WEAK':
        reasons.append('MACRO')
    if valid_mark(row):
        close = number(row, 'close')
        yellow = number(row, 'zge_yellow_line')
        lot['peak_close'] = max(lot['peak_close'], close)
        lot['trail_active'] = lot['trail_active'] or close >= lot['entry_open']*1.08
        if math.isfinite(yellow) and yellow > 0:
            if close < yellow:
                reasons.append('YELLOW')
        else:
            lot['missing_yellow_days'] += 1
        anchor = lot['anchor']
        if math.isfinite(anchor) and anchor > 0:
            if close < anchor:
                reasons.append('ANCHOR')
        else:
            lot['missing_anchor_days'] += 1
        if lot['trail_active'] and close <= lot['peak_close']*.95:
            reasons.append('TRAIL')
        if scenario in ('GRADED', 'STRICT_MATCHED') and close <= lot['entry_open']*.94:
            reasons.append('HARD_6PCT')
    else:
        lot['missing_yellow_days'] += 1
        lot['missing_anchor_days'] += int(not math.isfinite(lot['anchor']))
    if reasons and not lot['pending_reason']:
        lot.update(pending_reason=reasons[0], trigger_reasons='|'.join(reasons), trigger_date=day)
    return reasons


def opening_value(lot, row):
    price = number(row or {}, 'open')
    if not math.isfinite(price) or price <= 0:
        price = lot['last_close']
    return lot['quantity']*price*(1-SELL_FEE)


def close_lot(lot, row, day, at, reason):
    price = number(row, 'open' if at == 'OPEN' else 'close')
    notional = lot['quantity']*price
    fee = notional*SELL_FEE
    proceeds = notional-fee
    lot.update(status='CLOSED', exit_date=day, exit_price=price, exit_at=at,
               exit_reason=reason, sell_fee=fee, realized_pnl=proceeds-lot['allocation'],
               net_return_pct=(proceeds/lot['allocation']-1)*100)
    return proceeds, fee


def portfolio(picks, bars, sessions, risk, scenario, pool, horizon, asof=ASOF, *,
              protection_policy=None, tier_as_exposure_ceiling=True):
    days = [d for d in sessions if '20230101' <= d <= asof]
    index = {d: i for i, d in enumerate(sessions)}
    entries = {}
    after_asof = []
    for d, rows in picks.items():
        if d not in index:
            raise ValueError('SIGNAL_OUTSIDE_FROZEN_CALENDAR:' + d)
        next_i = index[d]+1
        if next_i < len(sessions) and sessions[next_i] <= asof:
            entries[sessions[next_i]] = rows
        else:
            after_asof.extend(rows)
    config = {'scenario': scenario, 'pool': pool, 'horizon': horizon, 'K': 3}
    cash, previous_nav = 1., 1.
    active, ledger, navs = [], [], []
    for day in days:
        prior_day = sessions[index[day]-1] if index[day] else ''
        observed_risk = risk.get(prior_day, {})
        cap_key = 'graded_cap' if scenario == 'GRADED' else 'strict_cap'
        state_key = 'graded_state' if scenario == 'GRADED' else 'strict_state'
        cap = float(observed_risk.get(cap_key, 0.))
        risk_known = observed_risk.get(state_key, 'UNKNOWN') != 'UNKNOWN'
        planned = entries.get(day, [])
        opening_cash_before_sales = max(0., cash)
        buy_fees = sell_fees = 0.
        exits = entered = failed = stale = constrained = trims = 0
        remaining = []
        # Only an earlier close may cause a protective opening exit.
        for lot in sorted(active, key=lambda l: (l['D'], l['canonical_security_id'], l['lane'])):
            row = bars.get(lot['canonical_security_id'], {}).get(day)
            if lot['pending_reason'] and lot['trigger_date'] < day:
                status = open_sell_status(row)
                lot['exit_status'] = status
                if status == 'FILLED':
                    proceeds, fee = close_lot(lot, row, day, 'OPEN', lot['pending_reason'])
                    cash += proceeds; sell_fees += fee; exits += 1
                    continue
                lot['open_exit_failed_attempts'] += 1
            remaining.append(lot)
        active = remaining
        exposure = sum(opening_value(l, bars.get(l['canonical_security_id'], {}).get(day)) for l in active)
        # UNKNOWN blocks new orders without forcing existing positions out.
        if scenario == 'GRADED' and risk_known and tier_as_exposure_ceiling:
            ceiling = previous_nav*cap
            remaining = []
            for lot in sorted(active, key=lambda l: (l['D'], l['canonical_security_id'], l['lane'])):
                row = bars.get(lot['canonical_security_id'], {}).get(day)
                if exposure > ceiling+1e-12:
                    status = open_sell_status(row)
                    lot['exit_status'] = status
                    if status == 'FILLED':
                        value = opening_value(lot, row)
                        proceeds, fee = close_lot(lot, row, day, 'OPEN', 'GRADED_WEAK' if cap == 0 else 'GRADED_TRIM')
                        cash += proceeds; sell_fees += fee; exits += 1; trims += 1; exposure -= value
                        continue
                    constrained += 1
                    if cap == 0 and not lot['pending_reason']:
                        lot.update(pending_reason='GRADED_WEAK', trigger_date=prior_day, trigger_reasons='GRADED_WEAK')
                remaining.append(lot)
            active = remaining
        room = max(0., previous_nav*cap-exposure) if tier_as_exposure_ceiling else opening_cash_before_sales
        budget = min(opening_cash_before_sales, room, previous_nav*cap/horizon) if planned else 0.
        allocation = budget/len(planned) if planned else 0.
        # Failed slots stay cash. Opening sells do not increase the fixed budget.
        for case in planned:
            code = case['canonical_security_id']
            row = bars.get(code, {}).get(day)
            status = fill_status(row, 'BUY')
            target_i = index[case['D']]+horizon
            target = sessions[target_i] if target_i < len(sessions) else ''
            if not risk_known or cap <= 0:
                status = 'MACRO_'+str(observed_risk.get(state_key, 'UNKNOWN'))
            lot = {**config, **{n: case[n] for n in ['episode_id', *IDENTITY, 'lane', 'model_year', 'held_outer']},
                   'rank_score': case['rank_score'], 'entry_date': day, 'planned_exit_date': target,
                   'entry_status': status, 'status': 'FAILED_ENTRY', 'allocation': allocation,
                   'quantity': 0., 'buy_fee': 0., 'sell_fee': 0., 'exit_date': '', 'exit_at': '', 'exit_reason': '',
                   'pending_reason': '', 'trigger_date': '', 'trigger_reasons': '',
                   'delayed_exit_days': 0, 'open_exit_failed_attempts': 0, 'stale_marks': 0,
                   'missing_anchor_days': 0, 'missing_yellow_days': 0, 'active_position_days': 0,
                   'realized_pnl': np.nan, 'net_return_pct': np.nan}
            if status == 'FILLED' and allocation > 1e-15:
                price = number(row, 'open')
                quantity = allocation/(price*(1+BUY_FEE))
                fee = quantity*price*BUY_FEE
                cash -= allocation; buy_fees += fee; entered += 1
                anchor_day = str(case.get('prior_anchor_date') or '')
                anchor = number(case, 'prior_anchor_low')
                if anchor_day and anchor_day >= case['D']:
                    raise ValueError('LOCKED_ANCHOR_NOT_PRE_D')
                if not anchor_day:
                    anchor = math.nan
                lot.update(status='OPEN', quantity=quantity, buy_fee=fee, entry_open=price, last_close=price,
                           anchor=anchor, anchor_date=anchor_day, peak_close=price, trail_active=False)
                active.append(lot)
            else:
                if status == 'FILLED':
                    lot['entry_status'] = 'NO_OPENING_BUDGET'
                failed += 1
            ledger.append(lot)
        remaining = []
        for lot in active:
            row = bars.get(lot['canonical_security_id'], {}).get(day)
            lot['active_position_days'] += 1
            if valid_mark(row):
                lot['last_close'] = number(row, 'close')
            else:
                lot['stale_marks'] += 1; stale += 1
            due = bool(lot['planned_exit_date'] and day >= lot['planned_exit_date'])
            if due:
                status = fill_status(row, 'SELL')
                lot['exit_status'] = status
                if status == 'FILLED':
                    proceeds, fee = close_lot(lot, row, day, 'CLOSE', 'SCHEDULED' if day == lot['planned_exit_date'] else 'DELAYED_SCHEDULED')
                    cash += proceeds; sell_fees += fee; exits += 1
                    continue
                lot['delayed_exit_days'] += 1
            (protection_policy or protection)(lot, row, day, scenario, risk.get(day, {}))
            remaining.append(lot)
        active = remaining
        value = sum(l['quantity']*l['last_close']*(1-SELL_FEE) for l in active)
        nav = cash+value
        if cash < -1e-10 or not math.isfinite(nav) or nav <= 0:
            raise ValueError('INVALID_CASH_NAV_LEDGER')
        navs.append({**config, 'D': day, 'NAV': nav, 'cash': cash, 'positions_value': value,
                     'daily_return': nav/previous_nav-1, 'open_lots': len(active), 'no_position': int(not active),
                     'entries': entered, 'exits': exits, 'failed_entries': failed, 'stale_marks': stale,
                     'buy_fees': buy_fees, 'sell_fees': sell_fees, 'opening_cap': cap, 'opening_risk_known': risk_known,
                     'opening_cash_before_sales': opening_cash_before_sales, 'opening_budget': budget,
                     'opening_exposure_after_sales': exposure, 'trimmed_lots': trims, 'constrained_trim_attempts': constrained,
                     'cap_excess_after_open_sales': max(0., exposure-previous_nav*cap) if risk_known else np.nan})
        previous_nav = nav
    for case in after_asof:
        ledger.append({**config, **{n: case[n] for n in ['episode_id', *IDENTITY, 'lane', 'model_year', 'held_outer']},
                       'status': 'ENTRY_AFTER_ASOF', 'entry_status': 'ENTRY_AFTER_ASOF', 'quantity': 0.,
                       'allocation': 0., 'buy_fee': 0., 'sell_fee': 0., 'exit_date': '', 'realized_pnl': np.nan, 'net_return_pct': np.nan})
    for lot in active:
        lot['residual_value_after_exit_cost'] = lot['quantity']*lot['last_close']*(1-SELL_FEE)
        lot['residual_exit_fee_reserve'] = lot['quantity']*lot['last_close']*SELL_FEE
    # Independent cash conservation check from actual realized and paid cash flows.
    expected_cash = 1.-sum(l['allocation'] for l in ledger if l['status'] in ('OPEN', 'CLOSED'))
    expected_cash += sum(l['allocation']+l['realized_pnl'] for l in ledger if l['status'] == 'CLOSED')
    if not math.isclose(expected_cash, cash, abs_tol=1e-10, rel_tol=1e-10):
        raise ValueError('CASH_CONSERVATION_FAILURE')
    ledger_frame = pd.DataFrame(ledger)
    if ledger_frame.empty:
        ledger_frame = pd.DataFrame(columns=[*config, 'status', 'exit_date', 'net_return_pct', 'realized_pnl'])
    return pd.DataFrame(navs), ledger_frame


def metrics(navs, ledger):
    results = []
    for config_values, f in navs.groupby(['scenario', 'pool', 'horizon'], sort=True):
        config = dict(zip(['scenario', 'pool', 'horizon'], config_values))
        trades = ledger
        for name, value in config.items():
            trades = trades.loc[trades[name].eq(value)]
        f = f.sort_values('D')
        prior_nav = 1.
        for period in [*sorted(f.D.str[:4].unique()), 'FULL']:
            part = f if period == 'FULL' else f.loc[f.D.str[:4].eq(period)]
            start_nav = 1. if period == 'FULL' else prior_nav
            final = float(part.NAV.iloc[-1]); returns = part.daily_return.to_numpy(dtype=float)
            dd = float(np.min(np.r_[start_nav, part.NAV] / np.maximum.accumulate(np.r_[start_nav, part.NAV]) - 1))
            cagr = (final/start_nav)**(252/len(part))-1
            vol = np.std(returns, ddof=1) if len(returns) > 1 else np.nan
            closed = trades.loc[trades.status.eq('CLOSED')]
            if period != 'FULL':
                closed = closed.loc[closed.exit_date.str[:4].eq(period)]
            r = closed.net_return_pct.to_numpy(dtype=float)
            winners, losers = r[r > 0], r[r < 0]
            count = len(r)
            results.append({**config, 'period': period, 'start': part.D.iloc[0], 'end': part.D.iloc[-1],
                'sessions': len(part), 'start_NAV': start_nav, 'final_NAV': final, 'net_return_pct': (final/start_nav-1)*100,
                'CAGR': cagr, 'MDD_pct': dd*100, 'Sharpe_252_RF0': float(np.mean(returns)/vol*np.sqrt(252)) if vol > 0 else np.nan,
                'Calmar': cagr/abs(dd) if dd < 0 else np.nan, 'closed_count': count,
                'annual_mean_closed_count': count/4 if period == 'FULL' else count,
                'win_rate': len(winners)/count if count else np.nan,
                'payoff_ratio': float(np.mean(winners)/abs(np.mean(losers))) if len(winners) and len(losers) else np.nan,
                'average_closed_net_pct': float(np.mean(r)) if count else np.nan,
                'realized_pnl': float(closed.realized_pnl.sum()), 'entries': int(part.entries.sum()),
                'exits': int(part.exits.sum()), 'residual_open_lots': int(part.open_lots.iloc[-1]),
                'no_position_fraction': float(part.no_position.mean()),
                'no_position_30_to_55_measured': bool(.3 <= part.no_position.mean() <= .55),
                'buy_fees': float(part.buy_fees.sum()), 'sell_fees': float(part.sell_fees.sum()),
                'stale_marks': int(part.stale_marks.sum()), 'constrained_trim_attempts': int(part.constrained_trim_attempts.sum())})
            if period != 'FULL':
                prior_nav = final
    return pd.DataFrame(results)


class CompactHistory:
    def __init__(self, frame):
        self.index = {d: i for i, d in enumerate(frame.trade_date)}
        self.values = frame[BAR_FIELDS].apply(pd.to_numeric, errors='coerce').to_numpy(dtype=float)
    def get(self, day, default=None):
        i = self.index.get(day)
        return default if i is None else dict(zip(BAR_FIELDS, self.values[i]))


def read_bars(*, data_root, act005_root, fit_manifest, codes, batch_size=128):
    from ops import pft_s_first_baseline as baseline
    from ops import research_panel_logical as reader
    frozen = old._validate_inputs(act005_root)
    result = {}
    counts = Counter()
    with baseline.bind_current_panels(data_root) as (path, source, recheck):
        assert_source(source, frozen)
        if source['identity'] != fit_manifest['source']['identity'] or source['backtest']['panel_sha256'] != fit_manifest['source']['backtest']['panel_sha256']:
            raise ValueError('REPLAY_FIT_SOURCE_DRIFT')
        aliases, groups, crosswalk = observed_universe(path, reader)
        if not set(codes) <= set(groups):
            raise ValueError('REPLAY_CANONICAL_MISSING')
        groups = {c: groups[c] for c in sorted(codes)}
        schema = reader.parquet.read_schema(path)
        actual = old._schema_names(schema)
        mapping = {n: actual[n] for n in ['ts_code', 'trade_date', *BAR_FIELDS] if n != 'vol'}
        mapping['vol'] = actual.get('vol', actual.get('volume'))
        for optional in ['exchange', 'market_type']:
            if optional in actual:
                mapping[optional] = actual[optional]
        for no, raw_codes in enumerate(cohorts(groups, batch_size)):
            f = read_cohort(path, schema, mapping, raw_codes, reader, lo='20230101')
            f['canonical_security_id'] = f.ts_code.map(aliases)
            for code, part in f.groupby('canonical_security_id', sort=True):
                h = canonical_history(part.drop(columns='canonical_security_id'), crosswalk)
                result[code] = CompactHistory(h)
                counts['projected_history_rows'] += len(h)
            print(json.dumps({'stage': 'READ_REPLAY_MARKS', 'cohort': no, 'codes': len(result), 'rows': counts['projected_history_rows']}), flush=True)
        recheck()
    counts['codes'] = len(result)
    return result, source, dict(counts)


def replay(*, fit_dir, rank_dir, data_root, act005_root, market_dir, output_dir):
    m = read_manifest(fit_dir, 'fit_manifest.json')
    if m['mode'] != 'FULL' or m['actual_successful_fit_calls'] != 80:
        raise ValueError('EIGHTY_FIT_FULL_SEAL_REQUIRED')
    seal = old._read_json(fit_dir/'pre_replay_seal.json')
    if seal['fit_calls'] != 80 or seal['prediction_outcomes_read'] is not False:
        raise ValueError('INVALID_PRE_REPLAY_SEAL')
    rm = read_manifest(rank_dir, 'rank_manifest.json')
    if (rm['fit_manifest_sha256'] != old._sha_file(fit_dir/'fit_manifest.json') or rm['execution_market_read'] is not False
        or rm['pre_replay_seal_sha256'] != old._sha_file(fit_dir/'pre_replay_seal.json')
        or rm['market_manifest_sha256'] != old._sha_file(market_dir/'market_manifest.json')):
        raise ValueError('PROSPECTIVE_RANK_SEAL_DRIFT')
    ranked = pd.read_parquet(rank_dir/'ranked_signals.parquet')
    if ranked.duplicated(['pool', *IDENTITY]).any() or not set(ranked.pool) <= set(POOLS):
        raise ValueError('INVALID_PROSPECTIVE_RANK_IDENTITY')
    market, sessions, market_manifest, calendar_info = calendar(market_dir, m['source'])
    if sessions != m['sessions']:
        raise ValueError('FIT_REPLAY_CALENDAR_DRIFT')
    if sessions != rm['sessions']:
        raise ValueError('RANK_REPLAY_CALENDAR_DRIFT')
    risk_frame = pd.read_csv(rank_dir/'causal_regimes.csv', dtype={'D': str})
    risk = risk_frame.set_index('D').to_dict('index')
    picks = {pool: {str(d): f.to_dict('records') for d, f in ranked.loc[ranked.pool.eq(pool)].sort_values(['D', 'rank_position']).groupby('D', sort=True)} for pool in POOLS}
    codes = {r['canonical_security_id'] for selected in picks.values() for rows in selected.values() for r in rows}
    # Only after immutable prediction+weight seal validation may execution bars be read.
    bars, source, read_counts = read_bars(data_root=data_root, act005_root=act005_root, fit_manifest=m, codes=codes)
    stage = new_stage(output_dir)
    navs, ledgers, configs = [], [], []
    specs = [(s, p, h) for s in ['STRICT', 'GRADED'] for p in POOLS for h in [3, 5]]
    specs += [('STRICT_MATCHED', 'ALL', h) for h in [3, 5]]
    for config_id, (scenario, pool, horizon) in enumerate(specs):
        n, l = portfolio(picks[pool], bars, sessions, risk, scenario, pool, horizon)
        n['config_id'] = config_id; l['config_id'] = config_id
        navs.append(n); ledgers.append(l)
        configs.append({'config_id': config_id, 'scenario': scenario, 'pool': pool, 'horizon': horizon, 'K': 3})
        print(json.dumps({'stage': 'PORTFOLIO', **configs[-1], 'daily_rows': len(n), 'ledger_rows': len(l)}), flush=True)
    nav = pd.concat(navs, ignore_index=True)
    ledger = pd.concat(ledgers, ignore_index=True)
    summary = metrics(nav, ledger)
    nav.to_parquet(stage/'daily_nav.parquet', index=False, compression='zstd')
    ledger.to_parquet(stage/'portfolio_ledger.parquet', index=False, compression='zstd')
    summary.to_csv(stage/'metrics.csv', index=False, float_format='%.12g')
    risk_frame.to_csv(stage/'causal_regimes.csv', index=False, float_format='%.12g')
    # Compact share artifact: exact dates and daily values, local rich details archived separately.
    daily = nav[['config_id', 'D', 'NAV', 'cash', 'entries', 'exits', 'open_lots']].rename(columns={'config_id': 'cfg', 'entries': 'en', 'exits': 'ex', 'open_lots': 'pos'})
    daily.to_csv(stage/'daily_evaluation.csv', index=False, float_format='%.7g')
    if (stage/'daily_evaluation.csv').stat().st_size >= 2_000_000:
        raise ValueError('SHARE_DAILY_CSV_NOT_UNDER_2MB')
    write_json(stage/'configs.json', configs)
    outputs = {p.name: old._sha_file(p) for p in stage.iterdir() if p.is_file()}
    return finish_manifest(stage, output_dir, 'replay_manifest.json', {
        'schema': 'ACT015_REPLAY_V1', 'mode': 'FULL', 'source': source, 'outputs_sha256': outputs,
        'fit_manifest_sha256': old._sha_file(fit_dir/'fit_manifest.json'),
        'pre_replay_seal_sha256': old._sha_file(fit_dir/'pre_replay_seal.json'),
        'rank_manifest_sha256': old._sha_file(rank_dir/'rank_manifest.json'),
        'market_manifest_sha256': old._sha_file(market_dir/'market_manifest.json'),
        'calendar': calendar_info, 'read_counts': read_counts, 'configs': configs,
        'prediction_counts_by_model_year': rm['prediction_counts_by_model_year'],
        'risk_known': risk_frame.graded_state.value_counts().to_dict(), 'range': ['20230101', ASOF],
        'oos_sessions_by_year': nav.loc[nav.config_id.eq(0)].D.str[:4].value_counts().sort_index().to_dict(),
        'share_file': 'daily_evaluation.csv', 'share_bytes': (stage/'daily_evaluation.csv').stat().st_size,
        'fees': {'buy': BUY_FEE, 'sell': SELL_FEE}, 'fits_this_stage': 0,
        'semantics': {'selection': 'same ranked eligible top3; pools dedup canonical+D highest score; code then lane tiebreak',
            'slots': 'budget/len(original selected slots <=3); failed fill slots stay cash',
            'opening_budget': 'pre-sale cash only; cap room after queued protection and graded oldest-lot trims; prior close NAV*cap/H',
            'UNKNOWN': 'blocks new entries; never forces unwind or trim',
            'grade': 'D score mean of 3 shares; quantiles of shifted prior126 actual sessions; q40 equality weak',
            'strict': 'original ACT013 protection, no -6%; STRICT_MATCHED and GRADED include -6% close trigger',
            'year_boundary': 'continuous cash/NAV and held lots; exits grouped by actual exit year; no artificial year end close',
            '2026': '213 actual market sessions through Nov20; later official calendar only planned future endpoint, no future prices',
            'source_PIT': 'CANNOT_CONFIRM frozen QFQ replay, no historical vintage claim'},
        'code_sha256': {str(p): old._sha_file(p) for p in [Path(__file__), ROOT/'ops/pft_act015_common.py']}})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    for name in ['fit-dir', 'rank-dir', 'data-root', 'act005-root', 'market-dir', 'output-dir']:
        p.add_argument('--'+name, type=Path, required=True)
    try:
        result = replay(**vars(p.parse_args(argv)))
    except Exception as exc:
        return cli_failure(exc)
    print(json.dumps(result, sort_keys=True)); return 0


if __name__ == '__main__':
    raise SystemExit(main())
