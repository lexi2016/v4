"""Pure Zhixing white/yellow lines & BBI indicators (zero external formula hacks)."""
from __future__ import annotations

from typing import Any


def _ema(values: list[float], period: int) -> list[float]:
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    out = [values[0]]
    for v in values[1:]:
        out.append(alpha * v + (1.0 - alpha) * out[-1])
    return out


def _sma(values: list[float], period: int) -> list[float | None]:
    out: list[float | None] = []
    running = 0.0
    for idx, v in enumerate(values):
        running += v
        if idx >= period:
            running -= values[idx - period]
        out.append(round(running / period, 4) if idx + 1 >= period else None)
    return out


def compute_zhixing_lines(bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Compute Zhixing White EMA(EMA(C,10),10), Yellow (MA14+MA28+MA57+MA114)/4, and BBI."""
    closes = [float(b["close"]) for b in bars]
    white = _ema(_ema(closes, 10), 10)
    m3, m6, m12, m24 = _sma(closes, 3), _sma(closes, 6), _sma(closes, 12), _sma(closes, 24)
    m14, m28, m57, m114 = _sma(closes, 14), _sma(closes, 28), _sma(closes, 57), _sma(closes, 114)

    enriched: list[dict[str, Any]] = []
    for i, b in enumerate(bars):
        yellow = None
        if None not in (m14[i], m28[i], m57[i], m114[i]):
            yellow = round((m14[i] + m28[i] + m57[i] + m114[i]) / 4.0, 4)
        bbi = None
        if None not in (m3[i], m6[i], m12[i], m24[i]):
            bbi = round((m3[i] + m6[i] + m12[i] + m24[i]) / 4.0, 4)
        enriched.append(
            {
                **b,
                "white_line": round(white[i], 4),
                "yellow_line": yellow,
                "bbi": bbi,
            }
        )
    return enriched
