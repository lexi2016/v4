"""D11 current candidate context, unchanged R3.1 proxies and transparent grouping; zero fit."""
import argparse, csv, gzip, hashlib, importlib.util, json, math, sys
from collections import Counter
from pathlib import Path
import pandas as pd
ASOF = 20261112
RUN = Path('/Users/lexi/Desktop/学习/agents调试/v4_close_selection_20261112')
SOURCE = RUN / 'data'
R3 = Path('/Users/lexi/Desktop/学习/Z哥方法论/PULLBACK_EVENT_R3_WORKTREE/05_EXPERIMENTS/PULLBACK_EVENT_R3/event_r3_v1_1.py')
CONFIG = Path('/Users/lexi/Desktop/学习/agents调试/Z哥方法论/top200_reversal_anchor_r3_20261112/R3_1_CONFIG.json')
GROUPS = ('nav_smallk', 'original', 'nav_pullback', 'nav_breakout')

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def read(p):
    return json.loads(Path(p).read_text())

def valid(x):
    try:
        return math.isfinite(float(x))
    except (ValueError, TypeError):
        return False

def ratio(a, b):
    return float(a) / float(b) if valid(a) and valid(b) and (float(a) > 0) and (float(b) > 0) else None

def val(x):
    return float(x) if valid(x) else None

def number(d):
    try:
        return int(str(d).replace('-', ''))
    except (ValueError, TypeError):
        return None

def text(x):
    return json.dumps(x, ensure_ascii=False, separators=(',', ':'), default=str)

def csvout(p, rows):
    if Path(p).exists():
        raise RuntimeError('output exists: ' + str(p))
    pd.DataFrame(rows).to_csv(p, index=False, float_format='%.17g')

def more_than(a, b):
    return valid(a) and valid(b) and (float(a) > float(b))

def at_most(a, b):
    return valid(a) and valid(b) and (float(a) <= float(b))

def make_one(c, ctx, g, scores, mod, cfg):
    symbol = c['symbol']
    e = ctx['evaluation']
    dates = g.trade_date.astype(int)
    if dates.duplicated().any() or not (dates <= ASOF).all() or dates.iloc[-1] != ASOF:
        raise RuntimeError('bad D11 prefix ' + symbol)
    g = g.sort_values('trade_date').reset_index(drop=True)
    d = g.iloc[-1]
    prev = g.iloc[-2] if len(g) >= 2 else None
    recent = g.tail(120).copy().rename(columns={'volume': 'vol', 'BBI': 'bbi'})
    recent['trade_date'] = recent.trade_date.astype(int)
    result = mod.evaluate(recent, ASOF, cfg)
    stock = result['stock']
    events = result['events']
    attacks = result['attacks']
    changes = result['management_changes']
    obs = result['observations']
    for collection in (events, attacks, changes, obs):
        for item in collection:
            item['security_code'] = symbol
    anchor = number(c.get('latest_new_anchor'))
    paths = [p for p in e.get('filter_anchor_paths', []) if number(p.get('anchor_date')) == anchor] if anchor else []
    arows = g[g.trade_date.astype(int) == anchor] if anchor else g.iloc[:0]
    path = paths[0] if len(paths) == 1 else None
    ar = arows.iloc[0] if len(arows) == 1 else None
    match = False
    if ar is not None and path is not None:
        o = path.get('ohlcv', {})
        match = all((valid(o.get(k)) and valid(ar[col]) and math.isclose(float(o[k]), float(ar[col]), rel_tol=1e-07, abs_tol=1e-07) for (k, col) in [('o', 'open'), ('h', 'high'), ('l', 'low'), ('c', 'close'), ('v', 'volume')]))
    identity = 'BOUND_OWNER_PROXY_NOT_CERTIFIED' if match else 'UNKNOWN_OWNER_ANCHOR_MISSING_OR_MISMATCH'
    matches = [x for x in events if number(x['origin_date']) == anchor] if match else []
    event = matches[0] if len(matches) == 1 else None
    relation = 'SAME_DATE_TWO_PROXIES_' + event['relation'] if event else 'OWNER_OUTSIDE_R3_120_LEFT_CENSORED' if anchor and anchor < int(recent.trade_date.iloc[0]) else 'UNKNOWN_NO_OWNER_R3_CONCORDANCE'
    if not match:
        relation = 'UNKNOWN_OWNER_ANCHOR_BINDING'
    a_low = val(ar['low']) if match else None
    a_high = val(ar['high']) if match else None
    post = g[g.trade_date.astype(int) > anchor] if match else g.iloc[:0]
    prior = post[post.trade_date.astype(int) < ASOF]
    invalid = not match or post[['open', 'high', 'low', 'close']].isna().any().any()
    broken = post[post.close < a_low] if match else g.iloc[:0]
    intra = post[(post.low < a_low) & (post.close >= a_low)] if match else g.iloc[:0]
    touches = prior[(prior.low <= a_high) & (prior.close >= a_low)] if match else g.iloc[:0]
    prior_touch = str(touches.trade_date.iloc[0]) if len(touches) else None
    last_touch = str(touches.trade_date.iloc[-1]) if len(touches) else None
    breached_date = str(broken.trade_date.iloc[0]) if len(broken) else None
    intra_date = str(intra.trade_date.iloc[0]) if len(intra) else None
    breach_state = 'UNKNOWN' if invalid else 'RECOVERED_AFTER_CLOSE_BREACH' if len(broken) and d.close >= a_low else 'CLOSE_BREACHED' if len(broken) else 'INTRADAY_BREACH_RECLAIM' if len(intra) else 'UNBROKEN_OBSERVED'
    clean = not invalid and (not len(broken))
    A = bool(clean and d.low <= a_high and (d.close >= a_low))
    B = bool(clean and len(touches) and (d.low > a_high) and (d.close > a_high))
    attacks_for = [x for x in attacks if event and x['origin_date'] == anchor and (x['attack_date'] < ASOF) and (not x['after_origin_close_breach'])]
    management = attacks_for[-1] if attacks_for else None
    attack_prior = g[(g.trade_date.astype(int) > management['attack_date']) & (g.trade_date.astype(int) < ASOF)] if management else g.iloc[:0]
    attack_touch = attack_prior[(attack_prior.low <= management['attack_high']) & (attack_prior.close >= management['attack_low'])] if management else g.iloc[:0]
    C = bool(clean and management and (d.low <= management['attack_high'] and d.close >= management['attack_low'] or (len(attack_touch) and d.low > management['attack_high'] and (d.close > management['attack_high']))))
    d_candle = bool(prev is not None and d.close > d.open and (prev.close < prev.open) and (d.close >= prev.open))
    d_r3 = any((x['origin_date'] == ASOF for x in events))
    D = d_candle or d_r3
    d_events = [x for x in events if x['origin_date'] == ASOF]
    recent5 = g.iloc[-6] if len(g) > 5 else None
    recent20 = g.iloc[-21] if len(g) > 20 else None
    recent60 = g.iloc[-61] if len(g) > 60 else None
    direction = bool(prev is not None and recent5 is not None and (d.close >= prev.close) and (d.close >= recent5.close))
    complete = all((valid(d[k]) for k in ('open', 'high', 'low', 'close', 'volume', 'BBI', 'zge_white_line', 'zge_yellow_line'))) and d.volume > 0 and (prev is not None) and (prev.volume > 0) and match and (ar.volume > 0)
    name = str(c['name'])
    is_st = 'ST' in name.upper()
    event_known = bool(event and event['relation'] != 'UNKNOWN_RELATIONSHIP')
    priority = bool((A or B or C) and event_known and clean and direction and complete and (not is_st))
    if is_st:
        disposition = 'EXCLUDED_ST_NAME'
        why = 'ST 名称依原交付口径不入优先；其余事实保留'
    elif breached_date and (not D):
        disposition = 'EXCLUDED_OWNER_CLOSE_BREACH'
        why = '该 owner 候选K曾收盘破低，非完整未破；未证新独立当前事件'
    elif priority:
        disposition = 'PRIORITY_REVIEW'
        why = '同日代理一致且当前支撑线索、方向代理和量价齐全；仅待人工逐日复核'
    elif not match:
        disposition = 'UNKNOWN_STRUCTURE'
        why = 'owner 候选K、原过滤锚与实际量价无法唯一绑定'
    elif not event_known and (A or B or C):
        disposition = 'UNKNOWN_CURRENT_EVENT_ATTRIBUTION'
        why = '当前有候选K支撑线索，但R3未在同日确认或事件关系未知；120根左截断'
    elif A or B or C or D:
        disposition = 'WAIT_CONFIRM'
        why = '存在支撑或局部转向线索，当前事件、方向或风险仍须确认'
    else:
        disposition = 'WAIT_NO_CURRENT_TRIGGER'
        why = '无本次可解释的当前支撑触及/恢复或局部转向，保留原引擎候选'
    risk = e.get('risk', {})
    group_info = e.get('groups', {})
    reasons = sorted(set((str(x) for xg in group_info.values() for x in xg.get('reasons', []))))
    row = {'security_code': symbol, 'name': name, 'trade_date': '2026-11-12', 'source_groups': c['groups'], 'source_pending_groups': c.get('pending_groups'), 'source_engine_risk_clear': c.get('risk_clear'), 'source_engine_group_status_json': text({k: group_info.get(k, {}).get('status', 'UNKNOWN') for k in GROUPS}), 'source_engine_reasons': '|'.join(reasons), 'owner_risk_status': risk.get('status'), 'owner_risk_events_json': text(risk.get('events', [])), 'owner_risk_proxy_json': text(risk.get('proxy_status', {})), 'D_open': val(d.open), 'D_high': val(d.high), 'D_low': val(d.low), 'D_close': val(d.close), 'D_volume': val(d.volume), 'prev_date': str(prev.trade_date) if prev is not None else None, 'prev_open': val(prev.open) if prev is not None else None, 'prev_high': val(prev.high) if prev is not None else None, 'prev_low': val(prev.low) if prev is not None else None, 'prev_close': val(prev.close) if prev is not None else None, 'prev_volume': val(prev.volume) if prev is not None else None, 'D_volume_div_prev_volume': ratio(d.volume, prev.volume) if prev is not None else None, 'prev20_volume_mean': val(g.volume.iloc[-21:-1].mean()) if len(g) > 20 else None, 'D_volume_div_prev20_mean': ratio(d.volume, g.volume.iloc[-21:-1].mean()) if len(g) > 20 else None, 'owner_candidate_anchor_date': anchor, 'owner_anchor_identity': identity, 'owner_anchor_relation_to_current_episode': relation, 'owner_anchor_open': val(ar.open) if match else None, 'owner_anchor_high': a_high, 'owner_anchor_low': a_low, 'owner_anchor_close': val(ar.close) if match else None, 'owner_anchor_volume': val(ar.volume) if match else None, 'owner_anchor_key_json': text(path.get('key', {})) if path else None, 'owner_preK_json': text(path.get('preK', {})) if path else None, 'D_volume_div_owner_volume': ratio(d.volume, ar.volume) if match else None, 'owner_first_prior_touch': prior_touch, 'owner_last_prior_touch': last_touch, 'owner_first_intraday_breach_reclaim': intra_date, 'owner_first_close_breach': breached_date, 'owner_support_state': breach_state, 'r3_window_rows': len(recent), 'r3_window_first': int(recent.trade_date.iloc[0]), 'r3_left_censored': True, 'r3_event_count': len(events), 'r3_any_origin_not_current_identity': stock.get('origin_any'), 'r3_any_attack_not_current_identity': stock.get('attack_any'), 'r3_owner_same_date_origin_retest': event.get('origin_retest_status') if event else 'UNKNOWN', 'r3_owner_same_date_origin_reason': event.get('origin_retest_reason') if event else 'UNKNOWN', 'r3_owner_same_date_management_status': event.get('management_status') if event else 'UNKNOWN', 'management_attack_date': management['attack_date'] if management else None, 'management_attack_open': management['attack_open'] if management else None, 'management_attack_high': management['attack_high'] if management else None, 'management_attack_low': management['attack_low'] if management else None, 'management_attack_close': management['attack_close'] if management else None, 'management_attack_volume': management['attack_volume'] if management else None, 'D_volume_div_management_volume': ratio(d.volume, management['attack_volume']) if management else None, 'attack_prior_first_touch': str(attack_touch.trade_date.iloc[0]) if len(attack_touch) else None, 'D_bbi': val(d.BBI), 'D_white': val(d.zge_white_line), 'D_yellow': val(d.zge_yellow_line), 'prev_bbi': val(prev.BBI) if prev is not None else None, 'prev_white': val(prev.zge_white_line) if prev is not None else None, 'prev_yellow': val(prev.zge_yellow_line) if prev is not None else None, 'D_formula_sell_signal': val(d.user_v1_sell_signal_daily), 'D_formula_break_prev_low': val(d.user_v1_break_prev_low), 'D_formula_under_yellow': val(d.user_v1_under_yellow), 'D_formula_white_yellow_death_cross': val(d.user_v1_white_yellow_death_cross), 'D_formula_keyline_break': val(d.user_v1_break_yesterday_keyline_daily), 'return_5_bars_pct': (d.close / recent5.close - 1) * 100 if recent5 is not None and recent5.close > 0 else None, 'return_20_bars_pct': (d.close / recent20.close - 1) * 100 if recent20 is not None and recent20.close > 0 else None, 'return_60_bars_pct': (d.close / recent60.close - 1) * 100 if recent60 is not None and recent60.close > 0 else None, 'prior20_high': val(g.high.iloc[-21:-1].max()) if len(g) > 20 else None, 'prior20_low': val(g.low.iloc[-21:-1].min()) if len(g) > 20 else None, 'prior60_high': val(g.high.iloc[-61:-1].max()) if len(g) > 60 else None, 'prior60_low': val(g.low.iloc[-61:-1].min()) if len(g) > 60 else None, 'A_candidate_key_retest': A, 'B_prior_touch_current_recovered': B, 'C_later_attack_retest': C, 'D_bull_reclaim_prior_bear_body': d_candle, 'D_r3_current_local_reversal_proxy': d_r3, 'D_any_turn_proxy': D, 'D_r3_origin_dates': '|'.join((str(x['origin_date']) for x in d_events)), 'engineering_direction_nonweak': direction, 'key_data_volume_complete': complete, 'is_ST_name': is_st, 'preliminary_disposition': disposition, 'preliminary_reason': why, 'owner_row_sha256': c['computation_row_sha256'], 'evidence_context_sha256': sha(SOURCE / 'STRUCTURE_CONTEXT.json.gz')}
    row.update(scores)
    return (row, events, attacks, changes, obs)
