"""Separate anonymized left-panel and user-only forward-panel rendering."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 880, 520
FONT_PATH = Path('/System/Library/Fonts/Supplemental/Arial.ttf')
INK = '#14263d'
MUTED = '#405572'
GRID = '#dce6f0'
UP = '#b82e43'
DOWN = '#177b70'
LINES = {'w': '#929dab', 'y': '#c18410', 'bbi': '#7951b5'}


def font(size):
    return ImageFont.truetype(str(FONT_PATH), size) if FONT_PATH.is_file() else ImageFont.load_default(size)


def render_panel(bars, *, forward_reference_close=None):
    forward = forward_reference_close is not None
    if not bars:
        raise ValueError('Empty chart data')
    if forward and len(bars) > 15:
        raise ValueError('Forward chart crosses D+15')
    base = forward_reference_close if forward else bars[-1].close
    indices = range(1, len(bars)+1) if forward else range(1-len(bars), 1)
    image = Image.new('RGB', (WIDTH, HEIGHT), '#f0f1f2' if forward else '#ffffff')
    draw = ImageDraw.Draw(image)
    draw.text((30, 21), 'D+1 to D+15' if forward else 'Trading sessions through D', fill=INK, font=font(24))
    draw.text((31, 56), 'Indexed prices  |  D close = 100', fill=MUTED, font=font(15))
    legend = [(key, color) for key, color in LINES.items() if any(getattr(bar, key) is not None for bar in bars)]
    for index, (key, color) in enumerate(legend):
        x = 640 + index * 68
        draw.line((x, 64, x+18, 64), fill=color, width=3)
        draw.text((x+24, 56), key.upper(), fill=MUTED, font=font(15))

    left, right, top, bottom, vtop, vbottom = 73, 839, 91, 354, 392, 474
    price_values = [price / base * 100 for bar in bars for price in (bar.high, bar.low)]
    price_values += [value / base * 100 for bar in bars for key in LINES if (value := getattr(bar, key)) is not None]
    if forward:
        price_values.append(100.0)
    lo, hi = min(price_values), max(price_values)
    pad = max((hi - lo) * 0.06, 0.5)
    lo, hi = lo - pad, hi + pad
    max_vol = max(max(bar.volume for bar in bars), 1)
    sessions_on_axis = 15 if forward else len(bars)
    step = (right-left) / max(sessions_on_axis, 1)
    half = max(2, min(7, round(step * 0.28)))

    def y_price(value):
        return round(bottom-(value / base * 100 - lo) / (hi-lo) * (bottom-top))

    for tick in range(5):
        y = round(top + tick * (bottom-top) / 4)
        tick_value = hi - tick * (hi-lo) / 4
        draw.line((left, y, right, y), fill=GRID)
        draw.text((left-10, y), f'{tick_value:.1f}', anchor='rm', fill=MUTED, font=font(13))
    draw.line((left, y_price(base), right, y_price(base)), fill='#9dacc0', width=1)
    draw.line((left, vbottom, right, vbottom), fill=GRID)
    draw.text((left-10, vtop+7), 'Vol.', anchor='rm', fill=MUTED, font=font(13))
    xs = [round(left+(offset+0.5)*step) for offset in range(len(bars))]
    for key, color in LINES.items():
        for first, second, x1, x2 in zip(bars, bars[1:], xs, xs[1:]):
            first_value, second_value = getattr(first, key), getattr(second, key)
            if first_value is not None and second_value is not None:
                draw.line((x1, y_price(first_value), x2, y_price(second_value)), fill=color, width=2)
    for bar, x in zip(bars, xs):
        color = UP if bar.close > bar.open else DOWN if bar.close < bar.open else MUTED
        o, h, lo_y, c = (y_price(value) for value in (bar.open, bar.high, bar.low, bar.close))
        draw.line((x, h, x, lo_y), fill=color, width=2)
        draw.rectangle((x-half, min(o, c), x+half, max(min(o, c)+1, max(o, c))), fill=color)
        volume_top = round(vbottom - bar.volume / max_vol * (vbottom-vtop))
        draw.rectangle((x-half, volume_top, x+half, vbottom), fill=color)
    for offset, index in enumerate(indices):
        if index in (0, 1) or index % 5 == 0:
            label = 'D' if index == 0 else f'D{index:+d}'
            draw.text((xs[offset], 491), label, fill=INK if index == 0 else MUTED, font=font(14), anchor='mt')
    if forward and len(bars) < 15:
        draw.text((right-8, 109), f'Observed {len(bars)}/15 forward sessions', fill=MUTED, font=font(14), anchor='rt')
    buffer = BytesIO()
    image.save(buffer, format='PNG', optimize=False)
    return buffer.getvalue()
