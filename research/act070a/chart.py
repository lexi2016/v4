"""Render an SVG of an ordered D-only OHLCV window with no external dependencies."""

from __future__ import annotations

from decimal import Decimal
from xml.sax.saxutils import escape, quoteattr

from research.act070a.case_contract import OHLCV_FIELDS, require

CHART_SESSIONS = 35
WIDTH, HEIGHT = 1160, 560


def render_chart(rows: list[dict]) -> bytes:
    require(len(rows) == CHART_SESSIONS, "INVALID_CHART_MAPPING", "frozen window is 35 sessions")
    bars = [tuple(Decimal(row["fields"][key]) for key in OHLCV_FIELDS) for row in rows]
    floor = min(bar[2] for bar in bars)
    ceiling = max(bar[1] for bar in bars)
    padding = max((ceiling - floor) / 20, Decimal("0.01"))
    floor, ceiling = floor - padding, ceiling + padding
    max_volume = max(max(bar[4] for bar in bars), Decimal(1))

    def y(price):
        return 350 - round((price - floor) * 260 / (ceiling - floor))

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
        f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
        '<title id="title">D-only candles and volume</title>',
        '<desc id="desc">35 sessions through D. The last candle is D. '
        'The row IDs and exact OHLCV are supplied in the case input.</desc>',
        '<rect width="1160" height="560" fill="#fff"/>',
        '<g font-family="sans-serif" fill="#14263d">',
        '<text x="36" y="36" font-size="23">Trading sessions through D</text>',
        '<text x="36" y="60" font-size="14">QFQ prices and reference volume</text>',
        '<text x="36" y="400" font-size="13">Volume</text>',
    ]
    for index in range(5):
        price = floor + (ceiling - floor) * index / 4
        ordinate = y(price)
        svg.extend((
            f'<path d="M100 {ordinate} H1125" stroke="#dce6f0"/>',
            f'<text x="93" y="{ordinate + 4}" font-size="12" text-anchor="end">{price:.2f}</text>',
        ))
    for index, (row, bar) in enumerate(zip(rows, bars, strict=True)):
        opening, high, low, close, volume = bar
        x = 118 + 29 * index
        color = "#b82e43" if close > opening else "#177b70" if close < opening else "#6c7480"
        volume_height = round(104 * volume / max_volume)
        candle_top = min(y(opening), y(close))
        candle_height = max(abs(y(opening) - y(close)), 1)
        label = f"D{index + 1 - CHART_SESSIONS:+}" if index + 1 != CHART_SESSIONS else "D"
        item_id = row["row_id"]
        date_label = row["fields"]["date"]
        svg.extend((
            f'<g data-row-id={quoteattr(item_id)} fill="{color}" stroke="{color}">',
            f'<title>{escape(f"{label} · {date_label} · {item_id}")}</title>',
            f'<path d="M{x} {y(high)} V{y(low)}" stroke-width="2"/>',
            f'<rect x="{x - 7}" y="{candle_top}" width="14" height="{candle_height}"/>',
            f'<rect x="{x - 7}" y="{508 - volume_height}" width="14" height="{volume_height}"/>',
            '</g>',
        ))
        if index % 5 == 4 or index == 0:
            svg.append(f'<text x="{x}" y="535" font-size="12" text-anchor="middle">{label}</text>')
    svg.extend(("</g>", "</svg>"))
    return ("\n".join(svg) + "\n").encode("utf-8")
