"""Persist conditional, research-only interpretations of the bound KB fields."""
from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[1] / 'contracts/a_share_kb_action_v1.json'
FIELDS = frozenset({'kb_action_no_position', 'kb_action_no_position_status',
                    'kb_action_with_position', 'kb_action_with_position_status',
                    'kb_action_reasons', 'kb_action_rule_sha256'})
INPUT_FIELDS = frozenset({'kb_b1', 'kb_b2', 'kb_b3', 'kb_b1_j', 'kb_white_cross_down',
    'kb_bull_rope_status', 'kb_macd_veto', 'kb_brick_action', 'kb_brick_flip_green',
    'kb_hold_score', 'kb_hold_score_min', 'kb_hold_score_max', 'user_v1_sell_signal_daily'})


def _value(value):
    if hasattr(value, 'item'):
        value = value.item()
    return None if isinstance(value, Real) and not math.isfinite(value) else value


def _score(value):
    value = _value(value)
    return int(value) if isinstance(value, Real) and not isinstance(value, bool) and value == int(value) else None


def action_rule_sha256():
    return hashlib.sha256(CONTRACT.read_bytes()).hexdigest()


def project_action(row, *, rule_sha256=None):
    """Return six persisted string fields for one day; unknown is never false."""
    row = {key: _value(row.get(key)) for key in INPUT_FIELDS}
    digest = rule_sha256 or action_rule_sha256()
    raw_total = row['kb_hold_score']
    low, high, total = (_score(row[key]) for key in ('kb_hold_score_min', 'kb_hold_score_max', 'kb_hold_score'))
    valid = (low is not None and high is not None and 0 <= low <= high <= 5
             and (raw_total is None or total is not None and total == low == high))
    interval = (f'{low}/5' if low == high else f'{low}～{high}/5') if valid else '待核'
    rope, brick, macd, cross = (row[key] for key in ('kb_bull_rope_status', 'kb_brick_action', 'kb_macd_veto', 'kb_white_cross_down'))
    sell_value = row['user_v1_sell_signal_daily']
    sell = sell_value is True or (isinstance(sell_value, Real) and not isinstance(sell_value, bool) and sell_value == 1)
    blockers = []
    if brick in ('禁止抄底', '止损'):
        blockers.append('砖型源状态为' + brick)
    if macd is True:
        blockers.append('MACD日线风险条件触发')
    if rope in ('牛绳断', '死叉'):
        blockers.append('牛绳状态为' + rope)
    missing = []
    if rope not in ('牵牛', '金叉', '死叉', '牛绳断'):
        missing.append('牛绳状态')
    if brick not in ('持有', '减仓', '止损', '禁止抄底', '观望'):
        missing.append('砖型状态')
    if macd is not True and macd is not False:
        missing.append('MACD日线风险条件')
    if cross is not True and cross is not False:
        missing.append('白黄线当日交叉')
    buys = [(name, row['kb_' + name.lower()]) for name in ('B1', 'B2', 'B3')]
    hits = [name for name, value in buys if value is True]
    unknown_buy = any(value is not True and value is not False for _, value in buys)
    if blockers:
        flat, flat_status = '等回调', 'OBSERVED_BLOCKER_CONDITIONAL'
        flat_reasons = ['；'.join(blockers) + '。']
        if hits:
            flat_reasons.append('KB ' + '、'.join(hits) + '为独立买点信号，须同时核对择时和风险。')
    elif hits:
        flat, flat_status = '等回调', 'UNKNOWN_BUY_FILTERS'
        flat_reasons = ['KB ' + '、'.join(hits) + '命中；大盘择时及完整买入过滤条件未绑定，不能确认买入。']
    elif unknown_buy:
        flat, flat_status = None, 'UNKNOWN_SIGNAL_INPUTS'
        flat_reasons = ['B1/B2/B3至少一项未知，不能当作未命中。']
    else:
        flat, flat_status = '等回调', 'OBSERVED_NO_BUY_SIGNAL'
        flat_reasons = ['当日KB B1/B2/B3均未命中；大盘择时未绑定。']
    if cross is True:
        held, held_status = '卖出', 'OBSERVED_CROSS_CONDITIONAL'
        held_reasons = ['白线当日下穿黄线；这是交叉事件，区别于持续的牛绳状态。']
    elif brick == '止损' and row['kb_brick_flip_green'] is True:
        held, held_status = '卖出', 'OBSERVED_BRICK_FLIP_CONDITIONAL'
        held_reasons = ['固定砖型实现确认红砖翻绿，源状态为止损。']
    elif valid and high < 3:
        held, held_status = '卖出', 'OBSERVED_SCORE_RANGE_CONDITIONAL'
        held_reasons = [f'持股评分范围 {interval}，上界仍低于3分；五分制对应离场观察。']
    elif brick == '减仓':
        held, held_status = '放飞', 'OBSERVED_BRICK_REDUCE_CONDITIONAL'
        held_reasons = ['固定砖型实现的红砖已达减仓状态；持仓和实际盈亏未绑定。']
    elif valid and low == high == 3:
        held, held_status = '放飞', 'OBSERVED_SCORE_THREE_CONDITIONAL'
        held_reasons = ['持股评分已确定为3分；五分制对应减半观察，实际持仓与盈亏未绑定。']
    elif valid and low >= 4 and (blockers or sell):
        held, held_status = '持有', 'CONFLICTING_OBSERVATIONS'
        risk = blockers + (['原式独立卖点命中'] if sell else [])
        held_reasons = [f'评分范围 {interval}，五分制有持仓分支偏持有；' + '；'.join(risk) + '，应并列核对。',
                        '半仓放飞所需形态、真实持仓及盈亏待核，不能仅凭J值确认。']
    elif valid and low >= 4 and not missing:
        held, held_status = '持有', 'OBSERVED_SCORE_HOLD_CONDITIONAL'
        held_reasons = [f'持股评分范围 {interval}；五分制持有规则以已有仓位及盈亏情境为前提，本面板未绑定实际仓位。']
    else:
        held, held_status = None, 'UNKNOWN_SCORE_OR_RISK'
        held_reasons = [f'持股评分范围 {interval}；不能把未确认的分项或风险状态当作0或否。']
    reasons = flat_reasons + held_reasons
    if rope == '牛绳断':
        reasons.append('牛绳断表示白线处于黄线下方，不表示今日刚发生下穿。')
    j = row['kb_b1_j']
    if isinstance(j, Real) and not isinstance(j, bool) and math.isfinite(j) and j > 80:
        reasons.append(f'J={j}，知识库将J高于80视为超买观察，不以J>90单独认定放飞。')
    if sell:
        reasons.append('原式卖点独立展示，不等同于尚未统一定义的KB S1。')
    if missing:
        reasons.append('状态待核：' + '、'.join(missing) + '。')
    reasons.append('S1/S2/S3的来源冲突或前置锚点尚待核；未绑定实际持仓、大盘择时和盈亏，本判断仅供研究。')
    return dict(kb_action_no_position=flat, kb_action_no_position_status=flat_status,
                kb_action_with_position=held, kb_action_with_position_status=held_status,
                kb_action_reasons=json.dumps(reasons, ensure_ascii=False, separators=(',', ':')),
                kb_action_rule_sha256=digest)
