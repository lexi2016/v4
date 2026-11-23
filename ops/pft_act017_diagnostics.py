"""ACT017 mechanical router and exact cash/NAV attribution; never persists marks."""
from __future__ import annotations
import bisect
import numpy as np
import pandas as pd
from ops import pft_act015_replay as base
from ops.pft_act016_inputs import hard_mask


def router_decomposition(predictions, thresholds, baseline, routed, sessions):
    """Same 940 signal dates and fixed K; q80-only keeps raw RF for every lane."""
    dates = [d for d in sessions if '20230101' <= d <= base.ASOF]
    hard = predictions.loc[predictions.D.isin(dates) & hard_mask(predictions)].copy()
    table = thresholds.set_index('year')
    hard['q80_threshold'] = [table.loc[int(d[:4]), lane+'_q80'] if lane in ('B1', 'B2') else np.nan
                             for d, lane in zip(hard.D, hard.lane)]
    passed = hard.loc[hard.lane.eq('B3') | hard.rank_score.ge(hard.q80_threshold)].copy()
    raw = base.select_signals(passed, 'ALL', 3)
    raw = pd.DataFrame([r for rows in raw.values() for r in rows], columns=passed.columns)
    modes = {'BASELINE_RAW': baseline, 'Q80_RAW_ALL_LANES': raw, 'Q80_B3_PRODUCT': routed}
    rows = []
    for period in [*sorted({d[:4] for d in dates}), 'ALL']:
        cut = lambda f: f if period == 'ALL' else f.loc[f.D.str[:4].eq(period)]
        for lane in ['B1', 'B2', 'B3']:
            h, p = cut(hard), cut(passed)
            h, p = h.loc[h.lane.eq(lane)], p.loc[p.lane.eq(lane)]
            low = p.loc[p.rank_score.lt(.25)] if lane in ('B1', 'B2') else p.iloc[:0]
            rec = dict(period=period, lane=lane, sessions=len(dates) if period == 'ALL' else sum(d.startswith(period) for d in dates),
                       hard_pool=len(h), pass_q80=len(p), pass_raw_RF_below_B3_min_025=len(low),
                       dates_pass_raw_RF_below_B3_min_025=low.D.nunique())
            for mode, selected in modes.items():
                s = cut(selected); s = s.loc[s.lane.eq(lane)]
                rec[mode+'_top3'] = len(s)
                rec[mode+'_selected_days'] = s.D.nunique()
                rec[mode+'_raw_RF_below_025'] = int(s.rank_score.lt(.25).sum()) if lane in ('B1', 'B2') else 0
            rows.append(rec)
    audit = pd.concat([f.assign(router_mode=mode) for mode, f in modes.items()], ignore_index=True)
    audit = audit[[x for x in ['router_mode', 'D', 'canonical_security_id', 'lane', 'episode_id', 'rank_score',
                               'rank_position', 'hybrid_score', 'q80_threshold', 'S_prob_gated', 'B_probability'] if x in audit]]
    return pd.DataFrame(rows), audit


def interval_specs(nav):
    """Annual/full cuts and deterministic earliest maximum-drawdown peak/trough."""
    f = nav.sort_values('D').reset_index(drop=True)
    periods = [*sorted(f.D.str[:4].unique()), 'FULL']
    result = []
    for period in periods:
        part = f if period == 'FULL' else f.loc[f.D.str[:4].eq(period)]
        first = int(part.index[0]); previous = f.iloc[first-1] if first else None
        start_day = str(previous.D) if previous is not None else ''
        start_nav = float(previous.NAV) if previous is not None else 1.
        result.append(dict(period=period, interval='PERIOD', start_D=start_day, end_D=str(part.D.iloc[-1]),
                           start_NAV=start_nav, end_NAV=float(part.NAV.iloc[-1])))
        values = np.r_[start_nav, part.NAV.to_numpy(float)]
        days = [start_day, *part.D.tolist()]
        dd = values/np.maximum.accumulate(values)-1
        trough = int(np.argmin(dd))
        peak = int(np.argmax(values[:trough+1]))
        result.append(dict(period=period, interval='MAX_DRAWDOWN', start_D=days[peak], end_D=days[trough],
                           start_NAV=float(values[peak]), end_NAV=float(values[trough]), MDD=float(dd[trough])))
    return result


class EndpointMarks:
    """One lazy bounded in-memory close cache per selected ticker; no raw files."""
    def __init__(self, bars, sessions):
        self.bars, self.sessions, self.cache = bars, sessions, {}

    def latest(self, code, entry_day, end_day, fallback):
        if code not in self.cache:
            history = self.bars.get(code, {})
            rows = [(d, base.number(row, 'close')) for d in self.sessions
                    if (row := history.get(d)) is not None and base.valid_mark(row)]
            self.cache[code] = ([r[0] for r in rows], [r[1] for r in rows])
        days, values = self.cache[code]
        i = bisect.bisect_right(days, end_day)-1
        return values[i] if i >= 0 and days[i] >= entry_day else fallback


def contribution_at(lot, day, marks):
    """Net mark already reserves exit fee, exactly as ACT015 daily NAV does."""
    if not day or lot.get('status') not in ('OPEN', 'CLOSED') or str(lot.get('entry_date', '')) > day:
        return 0.
    if lot.get('status') == 'CLOSED' and str(lot.get('exit_date', '')) <= day:
        return float(lot['realized_pnl'])
    price = marks.latest(lot['canonical_security_id'], str(lot['entry_date']), day, float(lot['entry_open']))
    return float(lot['quantity'])*price*(1-base.SELL_FEE)-float(lot['allocation'])


def portfolio_attribution(nav, ledger, bars, sessions, picked, risk_frame):
    marks = EndpointMarks(bars, [d for d in sessions if d <= base.ASOF])
    contributions, reconciliations, lanes, cases = [], [], [], []
    metadata = ['episode_id', 'D', 'canonical_security_id', 'lane', 'rank_score', 'entry_date', 'entry_open',
                'exit_date', 'exit_price', 'exit_reason', 'status', 'allocation', 'quantity', 'buy_fee', 'sell_fee']
    # Join by episode ID, never by a future execution date; retain other-config picks as context.
    context = {}
    for episode, group in picked.groupby('episode_id', sort=False):
        rec = {}
        for row in group.to_dict('records'):
            label = row['scenario']
            rec[label+'_selected_rank'] = row.get('rank_position')
            hybrid = row.get('hybrid_score', np.nan)
            rec[label+'_selected_score'] = hybrid if pd.notna(hybrid) else row.get('rank_score')
        context[episode] = rec
    risk_by_day = risk_frame.set_index('D').to_dict('index')
    for config_id, n in nav.groupby('config_id', sort=True):
        lots = ledger.loc[ledger.config_id.eq(config_id)].to_dict('records')
        scenario = str(n.scenario.iloc[0])
        for spec in interval_specs(n):
            atoms = []
            for lot in lots:
                before = contribution_at(lot, spec['start_D'], marks)
                after = contribution_at(lot, spec['end_D'], marks)
                delta = after-before
                # Keep all actual filled lots, including zero-delta and carryover rows.
                if lot.get('status') not in ('OPEN', 'CLOSED'):
                    continue
                row = {k: lot.get(k) for k in metadata}
                row.update(config_id=int(config_id), scenario=scenario, **spec,
                           contribution_start=before, contribution_end=after, contribution_delta=delta,
                           signed_NAV_atom=delta/spec['start_NAV'],
                           fraction_of_interval_NAV_change=delta/(spec['end_NAV']-spec['start_NAV'])
                               if spec['end_NAV'] != spec['start_NAV'] else np.nan)
                tier = risk_by_day.get(str(lot['D']), {})
                row.update(signal_D_tier=tier.get('graded_state', 'UNKNOWN'),
                           signal_D_timing_cap=tier.get('strict_cap', 0.),
                           **context.get(lot['episode_id'], {}))
                atoms.append(row)
            observed = sum(r['contribution_delta'] for r in atoms)
            expected = spec['end_NAV']-spec['start_NAV']
            error = observed-expected
            if not np.isclose(observed, expected, atol=1e-10, rtol=0):
                raise ValueError(f'ATTRIBUTION_NAV_RECONCILIATION:{config_id}:{spec}:{error}')
            reconciliations.append(dict(config_id=int(config_id), scenario=scenario, **spec,
                lot_delta_sum=observed, NAV_change=expected, reconciliation_error=error, status='PASS_ATOL_1E-10'))
            contributions.extend(atoms)
            a = pd.DataFrame(atoms)
            for lane in ['B1', 'B2', 'B3']:
                subset = a.loc[a.lane.eq(lane)] if not a.empty else a
                total = float(subset.contribution_delta.sum()) if len(subset) else 0.
                lanes.append(dict(config_id=int(config_id), scenario=scenario, **spec, lane=lane,
                                  contribution_delta=total, signed_NAV_atom=total/spec['start_NAV'],
                                  filled_lots=len(subset), nonzero_delta_lots=int(subset.contribution_delta.ne(0).sum()) if len(subset) else 0))
            if not a.empty:
                # Distinct ticker totals determine top names; retain every contributing lot for each name.
                totals = a.groupby('canonical_security_id').contribution_delta.sum().sort_values(kind='mergesort')
                names = totals.loc[totals.lt(0)].head(10).index
                selected = a.loc[a.canonical_security_id.isin(names) & a.contribution_delta.ne(0)].copy()
                selected['ticker_interval_contribution'] = selected.canonical_security_id.map(totals)
                cases.extend(selected.to_dict('records'))
    return {'lot_contributions.csv': pd.DataFrame(contributions),
            'attribution_reconciliation.csv': pd.DataFrame(reconciliations),
            'lane_attribution.csv': pd.DataFrame(lanes), 'top_negative_ticker_cases.csv': pd.DataFrame(cases)}
