"""The confirmed daily anomaly fields and explicitly descriptive components."""
from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[1] / 'contracts/a_share_kb_yidong_v1.json'
SPEC = json.loads(CONTRACT.read_text())
FIELDS = {name: item['type'] for name, item in SPEC['materialized_fields'].items()}
INPUT_FIELDS = frozenset({'trade_date', 'open', 'close', 'volume', 'pct_chg', 'ma60', 'zge_yellow_line'})


def rule_sha256():
    return hashlib.sha256(CONTRACT.read_bytes()).hexdigest()


def _number(value, *, positive=False, nonnegative=False):
    if hasattr(value, 'item'):
        value = value.item()
    if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(value):
        return None
    value = float(value)
    if positive and value <= 0 or nonnegative and value < 0:
        return None
    return value


def project_yidong_history(rows, *, digest=None):
    """Calculate the source's two confirmed thresholds; leave phase anchors UNKNOWN."""
    digest = digest or rule_sha256()
    result, dates = [], []
    for i, row in enumerate(rows):
        try:
            date = int(row['trade_date'])
        except (KeyError, ValueError, TypeError) as exc:
            raise ValueError('YIDONG_TRADE_DATE_INVALID') from exc
        if dates and date <= dates[-1]:
            raise ValueError('YIDONG_DATES_NOT_STRICTLY_INCREASING')
        dates.append(date)
        n = i + 1
        current_volume = _number(row.get('volume'), positive=True)
        prior = rows[max(0, i - 5):i]
        prior_volumes = [_number(item.get('volume'), nonnegative=True) for item in prior]
        previous_volume = prior_volumes[-1] if prior_volumes else None
        average = sum(prior_volumes) / 5 if len(prior_volumes) == 5 and all(v is not None for v in prior_volumes) else None
        ratio = current_volume / average if current_volume is not None and average and average > 0 and previous_volume and previous_volume > 0 else None
        latest = rows[max(0, n - 5):n]
        candles = [(_number(item.get('open'), positive=True), _number(item.get('close'), positive=True)) for item in latest]
        red = sum(close > opening for opening, close in candles) if len(candles) == 5 and all(a is not None and b is not None for a, b in candles) else None
        pct = _number(row.get('pct_chg'))
        status = 'INSUFFICIENT_65_BARS' if n < 65 else 'INVALID_PRICE_OR_VOLUME' if ratio is None or pct is None else 'COMPLETE' if red is not None else 'PARTIAL_CANDLE_INPUT'
        basic = ratio >= 2 and pct >= 2 if n >= 65 and ratio is not None and pct is not None else None
        james = (False if ratio < 3 or pct < 5 else red >= 3 if red is not None else None) if n >= 65 and ratio is not None and pct is not None else None
        kind = ('詹姆斯级' if james else '徐杰级') if basic is True and james is not None else None
        close = _number(row.get('close'), positive=True)
        ma60, yellow = _number(row.get('ma60'), positive=True), _number(row.get('zge_yellow_line'), positive=True)
        ma_dist = (close / ma60 - 1) * 100 if n >= 60 and close is not None and ma60 is not None else None
        yellow_dist = (close / yellow - 1) * 100 if n >= 114 and close is not None and yellow is not None else None
        latest_volumes = [_number(item.get('volume'), nonnegative=True) for item in latest]
        recent_peak = max(latest_volumes) if len(latest_volumes) == 5 and all(v is not None for v in latest_volumes) else None
        preceding = rows[max(0, n - 25):max(0, n - 5)]
        preceding_volumes = [_number(item.get('volume'), nonnegative=True) for item in preceding]
        prior_peak = max(preceding_volumes) if len(preceding_volumes) == 20 and all(v is not None for v in preceding_volumes) else None
        peak_ratio = recent_peak / prior_peak if recent_peak is not None and prior_peak and prior_peak > 0 else None
        six = rows[max(0, n - 6):n]
        points = [(_number(item.get('close'), positive=True), _number(item.get('volume'), positive=True)) for item in six]
        count = sum(points[j][0] > points[j - 1][0] and points[j][1] > points[j - 1][1] for j in range(1, 6)) if len(points) == 6 and all(a is not None and b is not None for a, b in points) else None
        result.append(dict(kb_yidong_is=basic, kb_yidong_james=james, kb_yidong_type=kind,
                           kb_yidong_status=status, kb_yidong_vol_ratio_5=ratio, kb_yidong_bullish_count_5=red,
                           kb_yidong_ma60_distance_pct=ma_dist, kb_yidong_yellow_distance_pct=yellow_dist,
                           kb_yidong_vol_peak_5=recent_peak, kb_yidong_vol_peak_prior20=prior_peak,
                           kb_yidong_peak_ratio_5_20=peak_ratio, kb_yidong_price_volume_up_days_5=count,
                           kb_yidong_phase_anchor_date=None, kb_yidong_phase_status='ANCHOR_RULE_NOT_QUANTIFIED',
                           kb_yidong_rule_sha256=digest))
    return result
