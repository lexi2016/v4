"""Causal ACT-067D semantic research shadow."""

from __future__ import annotations

from dataclasses import dataclass
from math import fsum

from research.act067b.semantic_shadow import UNKNOWN, conjunction, disjunction, status


def comparison(test, *values):
    return None if None in values else test(*values)


def ratio(value, denominator):
    return value / denominator if denominator else None


def distance(value, reference):
    return 100 * (value / reference - 1) if reference else None


def at_least(value, threshold):
    return comparison(lambda item: item >= threshold, value)


def at_most(value, threshold):
    return comparison(lambda item: item <= threshold, value)


def within(value, bounds):
    return comparison(lambda item: bounds[0] <= item <= bounds[1], value)


def flag(value):
    return UNKNOWN if value is None else value


def certify(supported, risk_certified):
    return conjunction(supported, risk_certified)


def bar_metrics(bar):
    spread = bar.high - bar.low
    body = bar.close - bar.open
    return {
        'body_pct_open': 100 * body/bar.open,
        'abs_body_to_range': ratio(abs(body), spread),
        'close_location': ratio(bar.close - bar.low, spread),
        'lower_wick_fraction': ratio(min(bar.open, bar.close) - bar.low, spread),
    }


def candle_shape(bar, values, rules):
    body = values['body_pct_open']
    if bar.high == bar.low:
        return 'FLAT'
    if body >= rules['large_bull_body_pct_open']:
        return 'BULL_EXPANSION'
    if body <= -rules['large_bear_body_pct_open']:
        return 'BEAR_DISTRIBUTION'
    if values['lower_wick_fraction'] >= rules['lower_wick_min_fraction'] and values['close_location'] >= rules['recovery_close_min_fraction']:
        return 'LOWER_WICK_RECOVERY'
    if abs(body) <= rules['doji_max_body_pct_open']:
        return 'DOJI'
    return 'BULL_OTHER' if body > 0 else 'BEAR_OTHER'


def line_test(bar, line):
    if line is None:
        return UNKNOWN
    if bar.close < line:
        return 'CLOSE_BREAK'
    if bar.low < line:
        return 'PIERCE_RECOVER'
    return 'TOUCH_HOLD' if bar.low == line else 'NO_TOUCH'


@dataclass(frozen=True)
class Damage:
    index: int
    root: int | None
    swing: int | None
    prior: int | None


@dataclass(frozen=True)
class Test:
    index: int
    trough: int
    old_floor_breach: bool | None


class Shadow:
    def __init__(self, rules):
        self.rules = rules
        self.bars = []
        self.ma = []
        self.suspected_caps = []
        self.risk_flags = []
        self.base_sources = []
        self.formal = []
        self.tracks = []
        self.last_anchor = None
        self.last_key = None
        self.last_swing = None
        self.last_damage = None
        self.damage_history = []
        self.last_terminal = None
        self.damage_active = False
        self.pending = None
        self.test = None
        self.i = -1

    def _window(self, n, i):
        return self.bars[i-n:i] if i >= n else []

    def _date(self, index):
        return str(self.bars[index].day) if index is not None else ''

    def _ids(self, indices, label):
        return '|'.join(f'{label}@{self._date(index)}' for index in indices)

    def _mean(self, n, i):
        window = self._window(n, i)
        return fsum(bar.volume for bar in window)/n if window else None

    def _volume_evidence(self, index, n, name):
        source = self._window(n, index)
        ma = self._mean(n, index)
        return {
            f'{name}_denominator': flag(ma),
            f'{name}_ratio': flag(ratio(self.bars[index].volume, ma)),
            f'{name}_start': str(source[0].day) if source else UNKNOWN,
            f'{name}_end': str(source[-1].day) if source else UNKNOWN,
        }

    def _support(self):
        bar = self.bars[-1]
        b1 = self.rules['method_19']
        return conjunction(
            at_least(distance(bar.close, bar.y), b1['min_close_dist_y_pct']),
            at_least(distance(bar.close, bar.w), b1['min_close_dist_w_pct']),
            at_most(abs(bar.pct) if bar.pct is not None else None, b1['max_abs_pct_change']),
        )

    def _market_risk(self, bar, metrics):
        rules = self.rules['risk']
        pct_magnitude = abs(bar.pct) if bar.pct is not None else None
        close_at_extreme = (bar.high == bar.close and (bar.pct or 0) > 0) or (bar.low == bar.close and (bar.pct or 0) < 0)
        cap_like = self.i >= 5 and close_at_extreme and within(pct_magnitude, rules['suspected_st_cap_cluster_pct'])
        one_word = self.i >= 5 and bar.high == bar.low and within(pct_magnitude, rules['suspected_st_body_range_pct'])
        self.suspected_caps.append(bool(cap_like))
        caps = self.suspected_caps[-rules['suspected_st_cluster_window_td']:]
        suspected = bool(one_word or (cap_like and sum(caps) >= rules['suspected_st_cluster_count']))
        flags = {
            'DEEP_Y_CLOSE': comparison(lambda x: x < rules['deep_y_close_pct'], distance(bar.close, bar.y)),
            'LARGE_BEAR_DISTRIBUTION': conjunction(at_most(metrics['body_pct_open'], -rules['bearish_body_pct_open']),
                                                    at_least(ratio(bar.volume, self.ma[-1][5]), rules['bearish_volume_vs_preceding_ma5'])),
            'SUSPECTED_ST': suspected,
        }
        self.risk_flags.append(flags)
        window = rules['window_td_including_D']
        start = max(0, self.i-window+1)
        recent = self.risk_flags[start:]
        blockers = [f'{key}@{self._date(index)}' for index, daily in enumerate(recent, start) for key, value in daily.items() if value is True]
        all_known = len(recent) == window and all(value is not None for daily in recent for value in daily.values())
        shadow = False if blockers else True if all_known else None
        certified = False if blockers else None
        return shadow, certified, {
            'risk_clear_shadow': status(shadow), 'risk_clear_certified': status(certified),
            'risk_shadow_blockers': '|'.join(blockers), 'risk_suspected_ST_D': status(suspected),
            'risk_official_ST_coverage': 'CANNOT_CONFIRM', 'risk_official_delisting_coverage': 'CANNOT_CONFIRM',
        }

    def _b1(self, raw, risk_shadow, risk_certified):
        p = self.rules['method_19']
        d = self.bars[-1]
        anchor = self.last_anchor
        support = self._support()
        info = {'b1_raw': status(raw), 'b1_anchor_type': '', 'b1_anchor_date': '', 'b1_anchor_age_td': '',
                'b1_anchor_floor': '', 'b1_peak_date': '', 'b1_peak_high': '', 'b1_trough_date': '', 'b1_trough_low': '',
                'b1_pullback_td': '', 'b1_pullback_drawdown_pct': UNKNOWN, 'b1_attack_peak_volume': UNKNOWN,
                'b1_attack_peak_ratio': UNKNOWN, 'b1_pullback_real': 'FALSE', 'b1_pullback_shrink': UNKNOWN,
                'b1_anchor_floor_valid': UNKNOWN, 'b1_primary_support': status(support), 'b1_needle_rule': UNKNOWN,
                'b1_W_intraday': line_test(d, d.w), 'b1_Y_intraday': line_test(d, d.y)}
        for n in (5, 10):
            info.update({f'b1_trough_vol_ma{n}_{field}': UNKNOWN for field in ('denominator','ratio','start','end')})
        age = self.i - anchor[0] if anchor else None
        if age is None or not within(age, p['anchor_window_td']):
            phase = 'RAW_ONLY' if raw is True else 'NO_ACTIVE_ANCHOR'
            result = None if self.i < p['anchor_window_td'][1] else False
            return result, {**info, 'b1_phase': phase, 'b1_formal_shadow': status(result), 'b1_formal_certified': status(result)}
        a, label = anchor
        floor = self.bars[a].low
        peak = max(range(a, self.i), key=lambda index: self.bars[index].high)
        trough = min(range(peak+1, self.i+1), key=lambda index: self.bars[index].low)
        attack, pullback = self.bars[peak], self.bars[trough]
        actual_drawdown = 100 * (attack.high - pullback.low) / attack.high
        real = actual_drawdown > 0 and any(self.bars[index].close < self.bars[index-1].close for index in range(peak+1, self.i+1))
        depth = disjunction(within(actual_drawdown, p['drawdown_pct_range']), at_most(d.j, p['or_j_lte']))
        shrink = conjunction(*(at_most(ratio(pullback.volume, self.ma[trough][n]), p['volume_ratio_max']) for n in (5, 10)))
        floor_valid = all(bar.close >= floor for bar in self.bars[a+1:self.i+1])
        evidence = conjunction(real, depth, shrink, floor_valid, support)
        result = conjunction(evidence, risk_shadow)
        certified = certify(evidence, risk_certified)
        if not floor_valid or risk_shadow is False:
            phase = 'INVALIDATED'
        elif result is True:
            phase = 'FORMAL_B1_SHADOW'
        elif conjunction(real, depth, shrink, support) is True:
            phase = 'SUPPORT_CONFIRMED'
        elif real:
            phase = 'IN_PULLBACK'
        else:
            phase = 'WAIT_PULLBACK'
        info.update({'b1_phase': phase, 'b1_formal_shadow': status(result), 'b1_formal_certified': status(certified),
                     'b1_anchor_type': label, 'b1_anchor_date': self._date(a), 'b1_anchor_age_td': age, 'b1_anchor_floor': floor,
                     'b1_peak_date': self._date(peak), 'b1_peak_high': attack.high, 'b1_trough_date': self._date(trough),
                     'b1_trough_low': pullback.low, 'b1_pullback_td': trough-peak, 'b1_pullback_drawdown_pct': actual_drawdown,
                     'b1_attack_peak_volume': attack.volume, 'b1_attack_peak_ratio': flag(ratio(pullback.volume, attack.volume)),
                     'b1_pullback_real': status(real), 'b1_pullback_shrink': status(shrink), 'b1_anchor_floor_valid': status(floor_valid)})
        for n in (5, 10):
            info.update(self._volume_evidence(trough, n, f'b1_trough_vol_ma{n}'))
        return result, info

    def _b2(self, bar, metrics, risk_shadow, risk_certified):
        p = self.rules['method_20']
        previous = self.bars[self.i-1].volume if self.i else None
        close_chain = self._support()
        base_from = max(0, self.i-p['preceding_base_td'])
        prior_base = [index for index in range(base_from,self.i) if self.base_sources[index] is True or self.formal[index] is True]
        base = True if prior_base else (None if self.i < p['preceding_base_td'] or any(self.base_sources[index] is None or self.formal[index] is None for index in range(base_from,self.i)) else False)
        current_base = conjunction(
            len(self.bars) >= p['base_lookback_td'] and bar.low == min(b.low for b in self.bars[-p['base_lookback_td']:]),
            at_most(bar.j, p['base_max_j']), at_most(ratio(bar.volume, self.ma[-1][5]), p['base_max_volume_vs_prior_ma5']),
            at_least(distance(bar.close, bar.y), 0), at_most(distance(bar.close, bar.w), 0),
        )
        self.base_sources.append(current_base)
        past_j = ([None] * 3 + [item.j for item in self.bars[-3:]])[-3:]
        f03_conditions = {
            'J_LT_13_D_MINUS_2_TO_D': disjunction(*(comparison(lambda value: value < 13, j) for j in past_j)),
            'VOL_GT_1_25_PRIOR4': comparison(lambda v: bar.volume > 1.25*v, self.ma[-1][4]),
            'PCT_GT_4': comparison(lambda v: v > 4, bar.pct), 'J_LT_70': comparison(lambda v: v < 70, bar.j),
            'W_GT_Y': comparison(lambda w,y: w > y, bar.w, bar.y),
        }
        oral = conjunction(base, bar.close > bar.open,
                           at_least(metrics['body_pct_open'], p['oral_min_body_pct_open']),
                           at_least(metrics['abs_body_to_range'], p['oral_min_body_to_range']),
                           at_least(metrics['close_location'], p['oral_min_close_location']),
                           at_least(ratio(bar.volume, previous), p['oral_min_volume_vs_prev']),
                           at_least(ratio(bar.volume, self.ma[-1][5]), p['oral_min_volume_vs_ma5']))
        results = (oral, conjunction(at_least(bar.pct,4), comparison(lambda v:v<55,bar.j)),
                   comparison(lambda v:bar.volume > 1.20*v,previous), conjunction(*f03_conditions.values()), None)
        info = {'b2_oral_authentic': UNKNOWN, 'b2_oral_preceding_base': status(base),
                'b2_oral_preceding_base_dates': '|'.join(self._date(index) for index in prior_base),
                'b2_prev_volume': flag(previous), 'b2_oral_vol_vs_prev': flag(ratio(bar.volume, previous)), 'b2_f03_J_D_MINUS_2_TO_D': '|'.join(str(flag(j)) for j in past_j),
                'b2_f03_failed_clauses': '|'.join(key for key,value in f03_conditions.items() if value is False)}
        info.update(self._volume_evidence(self.i,4,'b2_f03_prior4'))
        info.update({f'b2_f03_vol_D_minus_{lag}': self.bars[self.i-lag].volume if self.i >= lag else UNKNOWN for lag in range(1,5)})
        info.update(self._volume_evidence(self.i,5,'b2_oral_prior5'))
        lo, hi = p['later_retest_td']
        for idx, (track, result) in enumerate(zip(p['tracks'], results)):
            history = [(i,self.tracks[i][idx]) for i in range(max(0,self.i-hi),self.i-lo+1)]
            anchor = next((i for i,state in reversed(history) if state is True), None)
            phase = 'UNKNOWN_PLACEHOLDER' if idx == 4 else 'D0_RAW' if result is True else 'UNKNOWN' if result is None else 'NO_EVENT'
            retest_phase = 'UNKNOWN_PLACEHOLDER' if idx == 4 else 'NO_EVENT'
            if anchor is None:
                prerequisites = None if len(history) < hi or any(value is None for _,value in history) else False
                dip = None
            else:
                dip = -distance(bar.low, self.bars[anchor].close)
                pullback = conjunction(at_least(dip,p['retest_low_vs_d0_close_min_depth_pct']),
                                       at_most(ratio(bar.volume,self.ma[-1][5]),p['retest_volume_max']))
                prerequisites = conjunction(pullback, close_chain)
                retest_phase = 'FORMAL_LOW_BUY_SHADOW' if conjunction(prerequisites,risk_shadow) is True else 'RETEST_SEEN' if pullback is True else 'WAIT_RETEST'
            info.update({f'{track}_raw': status(result), f'{track}_D0_state': phase,
                         f'{track}_retest_anchor': self._date(anchor), f'{track}_retest_drawdown_pct': flag(dip),
                         f'{track}_retest_state': retest_phase, f'{track}_formal_retest_shadow': UNKNOWN if idx == 4 else status(conjunction(prerequisites, risk_shadow)),
                         f'{track}_formal_retest_certified': UNKNOWN if idx == 4 else status(certify(prerequisites, risk_certified))})
        self.tracks.append(results)
        return info

    def _episode_record(self, chain, tested, event, observation):
        root_level = self.bars[chain.root].low if chain.root is not None else None
        return {'status':event,'observed_on':self._date(observation),'damage_id':self._ids([chain.index],'D_DAMAGE'),
                'previous_damage_id':self._ids([chain.prior],'D_DAMAGE') if chain.prior is not None else '',
                'D':self._date(chain.index),'T':self._date(tested.index) if tested else '',
                'C':self._date(observation) if event=='C_REBUILD_CONFIRM' else '',
                'root':self._date(chain.root),'root_floor':flag(root_level),'swing':self._date(chain.swing),
                'D_close_vs_root_pct':flag(distance(self.bars[chain.index].close,root_level)),
                'T_close_vs_root_pct':flag(distance(self.bars[tested.index].close,root_level)) if tested else UNKNOWN,
                'C_close_vs_root_pct':flag(distance(self.bars[observation].close,root_level)) if event=='C_REBUILD_CONFIRM' else UNKNOWN,
                'historical_breach':status(comparison(lambda level:any(b.close<level for b in self.bars[chain.index:observation+1]),root_level))}

    def _log_terminal(self, event, disposition=None):
        self.last_terminal = {**self._episode_record(self.pending,self.test,event,self.i), **(disposition or {})}
        self.damage_history.append(self.last_terminal)

    def _m25(self, bar, metrics, risk_shadow, risk_certified):
        p = self.rules['method_25']
        n = p['swing_side_bars']
        if self.i >= 2*n:
            middle = self.i - n
            if all(self.bars[middle].high > self.bars[i].high for i in range(self.i-2*n,self.i+1) if i != middle):
                self.last_swing = middle
        damage = conjunction(comparison(lambda w: bar.close < w, bar.w), comparison(lambda y: bar.low <= y, bar.y))
        first_damage = damage is True and not self.damage_active
        self.damage_active = damage is True
        phase = 'NO_DAMAGE' if damage is not None else UNKNOWN
        if self.pending:
            if self.test:
                expired = self.i - self.test.index > p['confirm_window_after_test_td'][1]
            else:
                expired = self.i - self.pending.index > p['test_window_after_damage_td'][1]
            phase = 'EXPIRED' if expired else 'WAIT_C' if self.test else 'WAIT_T'
        else:
            expired = False
        prior_terminal = self.last_terminal
        onset_disposition = 'NONE'
        if first_damage:
            onset = Damage(self.i,self.last_key,self.last_swing,self.last_damage)
            self.last_damage = self.i
            if not self.pending or expired:
                if expired:
                    self._log_terminal('EXPIRED')
                    prior_terminal = self.last_terminal
                self.pending,self.test = onset,None
                expired = False
                phase,onset_disposition = 'D_DAMAGE','ACTIVATED'
            else:
                onset_disposition = 'NOT_ACTIVATED_PENDING_CHAIN'
            self.damage_history.append(self._episode_record(onset,None,onset_disposition,self.i))
        chain, tested = self.pending, self.test
        test_status = confirm_status = False
        if chain and not expired:
            floor = self.bars[chain.root].low if chain.root is not None else None
            v_mean = self.ma[-1][5]
            if not tested and within(self.i-chain.index,p['test_window_after_damage_td']):
                test_status = conjunction(within(distance(bar.low,bar.y),p['test_low_dist_y_pct']), at_least(distance(bar.close,bar.y),0),
                                          at_least(bar.pct,p['test_min_pct_change']),at_most(ratio(bar.volume,v_mean),p['test_max_volume_ratio']))
                if test_status is True:
                    bottom = min(range(chain.index,self.i+1),key=lambda i:self.bars[i].low)
                    old_broken = comparison(lambda level:any(b.close < level for b in self.bars[chain.index:self.i+1]),floor)
                    self.test = tested = Test(self.i,bottom,old_broken)
                    phase = 'T_YELLOW_TEST'
                    self.damage_history.append(self._episode_record(chain,tested,phase,self.i))
            if tested and within(self.i-tested.index,p['confirm_window_after_test_td']):
                t_bar = self.bars[tested.index]
                confirm_status = conjunction(bar.close > bar.open,at_least(metrics['body_pct_open'],p['confirm_min_body_pct_open']),
                                             at_least(metrics['abs_body_to_range'],p['confirm_min_body_to_range']),
                                             at_least(metrics['close_location'],p['confirm_min_close_location']),
                                             at_least(ratio(bar.volume,v_mean),p['confirm_min_volume_vs_ma5']),
                                             at_least(ratio(bar.volume,t_bar.volume),p['confirm_min_volume_vs_test']),
                                             comparison(lambda w:bar.close>w,bar.w),bar.close > t_bar.high)
                if confirm_status is True:
                    phase = 'C_REBUILD_CONFIRM'
        root = chain.root if chain else None
        swing = chain.swing if chain else None
        swing_high = self.bars[swing].high if swing is not None else None
        root_low = self.bars[root].low if root is not None else None
        history = (True if root is not None else None) if chain else False
        root_clear = comparison(lambda level:bar.close >= level,root_low)
        m25_risk_shadow = conjunction(risk_shadow,root_clear)
        m25_risk_certified = conjunction(risk_certified,root_clear)
        total = conjunction(confirm_status,history,m25_risk_shadow)
        certified = conjunction(confirm_status,history,m25_risk_certified)
        fields = {'m25_phase':phase,'m25_price_damage_proxy_today':status(damage),'m25_d_damage_today':status(first_damage),
                  'm25_onset_disposition':onset_disposition,'m25_onset_id_today':self._ids([self.i],'D_DAMAGE') if first_damage else '',
                  'm25_previous_event_status':prior_terminal['status'] if prior_terminal else 'NONE',
                  'm25_previous_terminal_record': prior_terminal,
                  'm25_t_yellow_test_today':status(test_status),'m25_c_rebuild_price_today': status(confirm_status),
                  'm25_history_preserved':status(history),'m25_risk_clear_shadow':status(m25_risk_shadow),
                  'm25_risk_clear_certified':status(m25_risk_certified),'m25_original_root_clear_now':status(root_clear),
                  'm25_rebuild_shadow':status(total),'m25_rebuild_certified':status(certified),
                  'm25_damage_id':self._ids([chain.index],'D_DAMAGE') if chain else '',
                  'm25_previous_damage_id':self._ids([chain.prior],'D_DAMAGE') if chain and chain.prior is not None else '',
                  'm25_d_date':self._date(chain.index) if chain else '',
                  'm25_t_date':self._date(tested.index) if tested else '',
                  'm25_c_date':self._date(self.i) if confirm_status is True else '',
                  'm25_root_keyk_id':self._ids([root],'KEY_K') if root is not None else '',
                  'm25_root_keyk_date':self._date(root),'m25_original_root_floor':flag(root_low),
                  'm25_d_close_vs_old_floor_pct':flag(distance(self.bars[chain.index].close,root_low)) if chain else UNKNOWN,
                  'm25_t_close_vs_old_floor_pct':flag(distance(self.bars[tested.index].close,root_low)) if tested else UNKNOWN,
                  'm25_c_close_vs_old_floor_pct':flag(distance(bar.close,root_low)) if confirm_status is True else UNKNOWN,
                  'm25_old_floor_broken_at_damage':status(comparison(lambda level:self.bars[chain.index].close<level,root_low)) if chain else UNKNOWN,
                  'm25_old_floor_ever_broken_through_test':status(tested.old_floor_breach) if tested else UNKNOWN,
                  'm25_old_floor_ever_broken_through_observation':status(comparison(lambda level:any(b.close<level for b in self.bars[chain.index:self.i+1]),root_low)) if chain else UNKNOWN,
                  'm25_pre_damage_swing_date':self._date(swing),'m25_pre_damage_swing_high':flag(swing_high),
                  'm25_damage_to_test_trough_date':self._date(tested.trough) if tested else '',
                  'm25_damage_to_test_trough_low':self.bars[tested.trough].low if tested else UNKNOWN,
                  'm25_damage_drawdown_pct_reporting_only':flag(-distance(self.bars[tested.trough].low,swing_high)) if tested and swing_high else UNKNOWN,
                  'm25_t_intraday_y':line_test(self.bars[tested.index],self.bars[tested.index].y) if tested else UNKNOWN,
                  'm25_t_low_vs_y_pct':flag(distance(self.bars[tested.index].low,self.bars[tested.index].y)) if tested else UNKNOWN,
                  'm25_t_volume':self.bars[tested.index].volume if tested else UNKNOWN,
                  'm25_t_body_pct':bar_metrics(self.bars[tested.index])['body_pct_open'] if tested else UNKNOWN,
                  'm25_c_body_pct':metrics['body_pct_open'] if confirm_status is True else UNKNOWN,
                  'm25_c_body_to_range':metrics['abs_body_to_range'] if confirm_status is True else UNKNOWN,
                  'm25_c_close_location':metrics['close_location'] if confirm_status is True else UNKNOWN,
                  'm25_c_volume_vs_test':flag(ratio(bar.volume,self.bars[tested.index].volume)) if confirm_status is True else UNKNOWN,
                  'm25_c_reclaimed_W':status(comparison(lambda x:bar.close>x,bar.w)) if confirm_status is True else UNKNOWN}
        for name, idx in (('m25_t_vol_ma5',tested.index if tested else None),('m25_c_vol_ma5',self.i if confirm_status is True else None)):
            fields.update(self._volume_evidence(idx,5,name) if idx is not None else
                          {f'{name}_{suffix}':UNKNOWN for suffix in ('denominator','ratio','start','end')})
        if expired or confirm_status is True:
            disposition = None if expired else {
                'rebuild_shadow': status(total), 'rebuild_certified': status(certified),
                'original_root_clear': status(root_clear), 'market_risk_clear': status(risk_shadow),
                'independent_risk_clear_shadow': status(m25_risk_shadow),
                'independent_risk_clear_certified': status(m25_risk_certified),
            }
            self._log_terminal('EXPIRED' if expired else 'C_REBUILD_CONFIRM', disposition)
            self.pending = self.test = None
        return fields

    def advance(self, bar):
        if self.bars and bar.day <= self.bars[-1].day:
            raise ValueError('Sessions must be strictly ordered')
        self.i += 1
        self.bars.append(bar)
        self.ma.append({n:self._mean(n,self.i) for n in (4,5,10)})
        metrics = bar_metrics(bar)
        risk_shadow,risk_certified,risk = self._market_risk(bar,metrics)
        raw = conjunction(comparison(lambda b,w:b>w,bar.bbi,bar.w),comparison(lambda w,y:w>y,bar.w,bar.y),at_most(bar.j,13))
        p = self.rules['key_k_proxy']
        key = conjunction(bar.close > bar.open,at_least(bar.pct,p['min_pct_change']),
                          at_least(ratio(bar.volume,self.ma[-1][5]),p['min_volume_vs_previous_ma5']),
                          comparison(lambda w,y:bar.close>w>y,bar.w,bar.y))
        formal,b1 = self._b1(raw,risk_shadow,risk_certified)
        b2 = self._b2(bar,metrics,risk_shadow,risk_certified)
        m25 = self._m25(bar,metrics,risk_shadow,risk_certified)
        self.formal.append(formal)
        if key is True:
            self.last_key = self.i
        if raw is True or key is True:
            self.last_anchor = (self.i,'BOTH' if raw is True and key is True else 'USER_F02_RAW_B1' if raw is True else 'KEY_K_PROXY')
        return {**metrics,'candle_shape_proxy':candle_shape(bar,metrics,self.rules['shape_proxy']),
                'key_k_proxy':status(key),'close_dist_W_pct':flag(distance(bar.close,bar.w)),
                'close_dist_Y_pct':flag(distance(bar.close,bar.y)),**risk,**b1,**b2,**m25}
