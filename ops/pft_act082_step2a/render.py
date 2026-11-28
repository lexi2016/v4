"""Fixed, metadata-free rendering of independent D-only panels."""

from binascii import crc32
from hashlib import file_digest
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from struct import unpack

FONT = Path("/System/Library/Fonts/Hiragino Sans GB.ttc")
WIDTH, HEIGHT = 1440, 720
BG, PANEL, GRID = "#101721", "#182334", "#324259"
WHITE, YELLOW, TEXT = "#eaf0f8", "#f5cf70", "#b6c5d8"
RED, GREEN, AUX = "#fd777b", "#63d6aa", "#89b5f5"
PNG_SIGNATURE = bytes.fromhex("89504e470d0a1a0a")
PANELS = ("day_wide", "day_focus", "week")


@lru_cache(maxsize=2)
def _font(size):
    from PIL import ImageFont

    return ImageFont.truetype(str(FONT), size)


def environment():
    import PIL

    with FONT.open("rb") as font:
        font_sha = file_digest(font, "sha256").hexdigest()
    return {
        "renderer": "PIL_CANONICAL_RGB_PNG", "pillow": PIL.__version__, "font_sha256": font_sha,
        "geometry": [WIDTH, HEIGHT], "dpi": "RASTER_FIXED_NO_DPI_METADATA", "presence_of_timestamps": False,
    }


def png_chunks(encoded):
    if not encoded.startswith(PNG_SIGNATURE):
        raise ValueError("missing PNG signature")
    pos = len(PNG_SIGNATURE)
    chunks = []
    while pos < len(encoded):
        if pos + 12 > len(encoded):
            raise ValueError("truncated PNG")
        length, kind = unpack(">I4s", encoded[pos:pos + 8])
        following = pos + 12 + length
        if following > len(encoded) or kind not in (b"IHDR", b"IDAT", b"IEND"):
            raise ValueError("PNG contains auxiliary metadata or invalid chunk")
        body = encoded[pos + 8:following - 4]
        if crc32(kind + body) != unpack(">I", encoded[following - 4:following])[0]:
            raise ValueError("invalid PNG checksum")
        if kind == b"IHDR" and body != bytes.fromhex(f"{WIDTH:08x}{HEIGHT:08x}0802000000"):
            raise ValueError("unexpected PNG geometry or color mode")
        if kind == b"IEND" and (length or following != len(encoded)):
            raise ValueError("invalid PNG terminal chunk")
        pos = following
        chunks.append(kind)
    if not chunks or chunks[0] != b"IHDR" or chunks[-1] != b"IEND" or set(chunks[1:-1]) != {b"IDAT"}:
        raise ValueError("noncanonical PNG structure")
    return chunks


def _dash(draw, x0, y0, x1, y1, color):
    length = max(abs(x1 - x0), abs(y1 - y0))
    if not length:
        return
    for start in range(0, round(length), 9):
        a, b = start / length, min(1.0, (start + 5) / length)
        draw.line((x0 + a * (x1 - x0), y0 + a * (y1 - y0),
                   x0 + b * (x1 - x0), y0 + b * (y1 - y0)), fill=color, width=2)


def _limits(values):
    lo, hi = min(values), max(values)
    margin = max((hi - lo) * 0.055, abs(lo) * 0.001, 1e-7)
    return lo - margin, hi + margin


def _ohlc(draw, rows, *, weekly):
    left, top, right, bottom = 34, 125, WIDTH - 34, 510
    draw.rounded_rectangle((left, top, right, bottom), 11, fill=PANEL)
    for y in range(top + 60, bottom, 69):
        draw.line((left + 14, y, right - 14, y), fill=GRID)
    visible = [v for row in rows for k in ("h", "l", "W", "Y") if (v := row.get(k)) is not None]
    if not visible:
        draw.text((left + 30, top + 38), "证据不足", font=_font(26), fill=TEXT)
        return
    low, high = _limits(visible)
    def y_of(value):
        return bottom - (bottom - top) * (value - low) / (high - low)
    step = (right - left - 35) / max(1, len(rows))
    half = max(1, min(9, int(step * 0.27)))
    columns = [left + 17 + step * (i + .5) for i in range(len(rows))]
    for x, row in zip(columns, rows, strict=True):
        if row["o"] is None:
            continue
        x = round(x)
        color = RED if row["c"] >= row["o"] else GREEN
        incomplete = weekly and row["partial"]
        wick = (x, y_of(row["h"]), x, y_of(row["l"]), color)
        if incomplete:
            _dash(draw, *wick)
        else:
            draw.line(wick[:-1], fill=color, width=1)
        opened, closed = y_of(row["o"]), y_of(row["c"])
        body = (x - half, min(opened, closed), x + half, max(min(opened, closed) + 1, opened, closed))
        draw.rectangle(body, fill=None if incomplete else color, outline=color, width=2 if incomplete else 1)
    for key, color in (("W", WHITE), ("Y", YELLOW)):
        for i, row in enumerate(rows[1:], 1):
            prev = rows[i - 1][key]
            value = row[key]
            if prev is None or value is None:
                continue
            coords = (columns[i - 1], y_of(prev), columns[i], y_of(value))
            if weekly and row["partial"]:
                _dash(draw, *coords, color)
                x, y = coords[-2:]
                draw.ellipse((x - 4, y - 4, x + 4, y + 4), outline=color, width=2)
            else:
                draw.line(coords, fill=color, width=2)
    _volume(draw, rows, columns, left, right, half, weekly)


def _volume(draw, rows, columns, left, right, half, weekly):
    specs = [("v", "累计实际量" if weekly else "成交量", 525, 604, None)]
    if weekly:
        specs.append(("mean_v_per_elapsed_exchange_day", "同单位 日均量 / 已过交易日", 613, 694, AUX))
    for key, name, top, bottom, override in specs:
        draw.rounded_rectangle((left, top, right, bottom), 11, fill=PANEL)
        draw.text((left + 13, top + 6), name, fill=TEXT, font=_font(17))
        max_v = max((row[key] for row in rows), default=0.0) or 1.0
        for x, row in zip(columns, rows, strict=True):
            if not row[key]:
                continue
            x = round(x)
            color = override or (RED if row["c"] >= row["o"] else GREEN)
            y = bottom - 3 - (bottom - top - 28) * row[key] / max_v
            draw.rectangle((x - half, y, x + half, bottom - 3),
                           fill=None if weekly and row["partial"] else color, outline=color)


def draw_panel(payload, panel):
    from PIL import Image, ImageDraw

    if panel not in PANELS:
        raise ValueError("unrecognized panel")
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    weekly = panel == "week"
    if weekly:
        rows = payload["weekly"]
        title = "周线背景"
        detail = "白线 W / 黄线 Y · 已收实线 · 临时周虚线，非已收周确认"
        state = rows[-1] if rows else None
        if state:
            prefix = "未完结" if state["partial"] else "已收周"
            note = (f"{prefix}，已过 {state['elapsed']}/{state['scheduled']} 个交易日"
                    f"   停牌 {state['suspended']}   数据缺失 {state['missing']}   无效观测 {state['invalid']}")
        else:
            note = "周线证据不足"
    else:
        focus = panel == "day_focus"
        rows = payload["daily_focus"] if focus else payload["daily_wide"]
        title = "日线聚焦" if focus else "日线结构"
        detail = "白线 W / 黄线 Y · 横轴为截至 D 的相对交易日"
        first = rows[0]["i"]
        note = f"D{first:+d} 至 D" if first != 0 else "D"
    draw.text((35, 16), title, fill=WHITE, font=_font(31))
    draw.text((37, 58), detail, fill=TEXT, font=_font(20))
    draw.text((37, 90), note, fill=YELLOW, font=_font(18))
    _ohlc(draw, rows, weekly=weekly)
    buf = BytesIO()
    img.save(buf, format="PNG", compress_level=7)
    result = buf.getvalue()
    png_chunks(result)
    return result

