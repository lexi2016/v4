"""Render the two ACT-078A review atlases from the sealed chart manifests."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path

from pypdf import PdfReader
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

FONT = "ACT078A-CJK"
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"
INK = HexColor("#18232b")
MUTED = HexColor("#465662")
GRID = HexColor("#dce5ec")
DOWN = HexColor("#19845c")
UP = HexColor("#ba3c37")
YELLOW = HexColor("#a97709")
WHITE_OUTLINE = HexColor("#486375")
BLUE = HexColor("#21689c")
DEFAULT_NAME = {"blind": "D_ONLY_BLIND", "post": "POST_VALIDATION"}
OUTCOME_FIELDS = ("t2_net", "t5_net", "t10_net", "mae5_net", "tail_std")
COMMON_KEYS = {"chart_id", "security_id", "name", "D", "candidate_tier", "score", "metrics_d", "bars"}
BAR_KEYS = {"D", "offset", "open", "high", "low", "close", "volume", "W", "Y"}


def text(doc, x, y, value, size=8, color=INK):
    doc.setFillColor(color)
    doc.setFont(FONT, size)
    doc.drawString(x, y, value)


def fmt(value, unit=""):
    if value is None or not math.isfinite(float(value)):
        return "NA"
    if unit == "%":
        return f"{float(value):+.2%}"
    return f"{float(value):.2f}{unit}"


def build_pages(doc, samples, mode):
    width, height = landscape(A4)
    margin, gap, top = 25, 11, 63
    card_w = (width - 2 * margin - 2 * gap) / 3
    card_h = (height - top - margin - gap) / 2
    per_page = 6
    group_title = "D-only 盲审图册" if mode == "blind" else "事后验证图册"
    window = "D-20 至 D" if mode == "blind" else "D-10 至 D+10"
    for page in range(0, len(samples), per_page):
        text(doc, margin, height - 28, f"PFT V4   ACT-078A   {group_title}", 18)
        text(doc, margin, height - 48, f"V2.2 候选   |   {window}   |   按独立波段取样", 9, MUTED)
        text(doc, width - 231, height - 48, "白线 W   金线 Y   蓝色虚线 D", 9, MUTED)
        for index, sample in enumerate(samples[page:page + per_page]):
            x = margin + (index % 3) * (card_w + gap)
            y = height - top - card_h - (index // 3) * (card_h + gap)
            render_card(doc, sample, mode, x, y, card_w, card_h)
        text(doc, margin, 12, "GEMINI_MASTER  |  研究候选", 7, MUTED)
        text(doc, width - 59, 12, f"{page // per_page + 1} / {math.ceil(len(samples) / per_page)}", 7, MUTED)
        doc.showPage()


def render_card(doc, sample, mode, x, y, width, height):
    doc.setFillColor(white)
    doc.setStrokeColor(GRID)
    doc.setLineWidth(0.6)
    doc.roundRect(x, y, width, height, 5, fill=1, stroke=1)
    title = f"{sample['security_id']}   {sample['name']}"
    text(doc, x + 9, y + height - 16, title, 10)
    text(doc, x + 9, y + height - 30, f"{sample['chart_id']}   |   D {sample['D']}", 8, MUTED)

    chart_left, chart_right = x + 12, x + width - 37
    chart_low, chart_high = y + 89, y + height - 40
    v_low, v_high = y + 62, y + 84
    first, last = (-20, 0) if mode == "blind" else (-10, 10)
    step = (chart_right - chart_left) / (last - first + 1)
    bars = sample["bars"]

    def xpos(offset):
        return chart_left + step * (offset - first + 0.5)

    price = [bar[key] for bar in bars for key in ("low", "high", "W", "Y") if bar[key] is not None]
    price_lo, price_hi = min(price), max(price)
    pad = max((price_hi - price_lo) * 0.09, abs(price_hi) * 0.002, 0.001)
    price_lo, price_hi = price_lo - pad, price_hi + pad

    def ypos(value):
        return chart_low + (value - price_lo) / (price_hi - price_lo) * (chart_high - chart_low)

    doc.setStrokeColor(GRID)
    for fraction in (0, 0.5, 1):
        price_level = price_lo + fraction * (price_hi - price_lo)
        yy = ypos(price_level)
        doc.setLineWidth(0.35)
        doc.line(chart_left, yy, chart_right, yy)
        text(doc, chart_right + 3, yy - 2, f"{price_level:.2f}", 6.5, MUTED)

    doc.setStrokeColor(BLUE)
    doc.setLineWidth(0.55)
    doc.setDash(2.2, 1.6)
    doc.line(xpos(0), v_low, xpos(0), chart_high)
    doc.setDash()

    max_volume = max(max(float(bar["volume"]) for bar in bars), 1)
    for bar in bars:
        xx = xpos(bar["offset"])
        shade = UP if bar["close"] >= bar["open"] else DOWN
        doc.setStrokeColor(shade)
        doc.setFillColor(shade)
        doc.setLineWidth(0.6)
        doc.line(xx, ypos(bar["low"]), xx, ypos(bar["high"]))
        body = min(ypos(bar["open"]), ypos(bar["close"]))
        body_h = max(abs(ypos(bar["close"]) - ypos(bar["open"])), 0.65)
        doc.rect(xx - step * 0.28, body, step * 0.56, body_h, fill=1, stroke=0)
        vol_height = float(bar["volume"]) / max_volume * (v_high - v_low)
        doc.rect(xx - step * 0.25, v_low, step * 0.5, vol_height, fill=1, stroke=0)

    for col, shade, line_w in (("W", WHITE_OUTLINE, 1.65), ("W", white, 0.75), ("Y", YELLOW, 1.0)):
        doc.setStrokeColor(shade)
        doc.setLineWidth(line_w)
        prev = None
        for bar in bars:
            val = bar[col]
            if val is None:
                prev = None
                continue
            new = (xpos(bar["offset"]), ypos(val))
            if prev is not None:
                doc.line(*prev, *new)
            prev = new

    for offset in sorted({first, 0, last}):
        label = "D" if offset == 0 else f"D{offset:+d}"
        doc.setFillColor(MUTED)
        doc.setFont(FONT, 7)
        doc.drawCentredString(xpos(offset), v_low - 9, label)

    m = sample["metrics_d"]
    text(doc, x + 9, y + 35, f"J {fmt(m.get('kdj_j'))}   日涨 {fmt(m.get('ret_1d'), '%')}   五日 {fmt(m.get('ret_5d'), '%')}   VR5 {fmt(m.get('vol_ratio_5d'), '×')}", 7.4)
    text(doc, x + 9, y + 23, f"白线距 {fmt(m.get('dist_w_atr'))} ATR   LOW60 {fmt(m.get('low60_gain'), '%')}   广度 {fmt(m.get('breadth_41_above_w'), '%')}", 7.4)
    if mode == "post":
        o = sample["outcomes"]
        text(doc, x + 9, y + 10, f"T+2 {fmt(o.get('t2_net'), '%')}   T+5 {fmt(o.get('t5_net'), '%')}   T+10 {fmt(o.get('t10_net'), '%')}   MAE5 {fmt(o.get('mae5_net'), '%')}", 7.4, BLUE)


def ensure_pair(blind, post):
    assert 0 < len(blind) == len(post) <= 36
    assert len({r["chart_id"] for r in blind}) == len(blind)
    windows = {"blind_truncated": 0, "post_truncated": 0}
    for left, right in zip(blind, post, strict=True):
        assert not set(left) - COMMON_KEYS, set(left) - COMMON_KEYS
        assert all(left[key] == right[key] for key in ("chart_id", "security_id", "name", "D"))
        for mode, sample, lo, hi in (("blind", left, -20, 0), ("post", right, -10, 10)):
            offsets = [bar["offset"] for bar in sample["bars"]]
            dates = [bar["D"] for bar in sample["bars"]]
            assert dates == sorted(set(dates))
            assert offsets == list(range(offsets[0], offsets[-1] + 1))
            assert lo <= offsets[0] <= 0 <= offsets[-1] <= hi
            assert dates[offsets.index(0)] == sample["D"]
            assert all(set(bar) == BAR_KEYS for bar in sample["bars"])
            windows[f"{mode}_truncated"] += int(offsets[0] != lo or offsets[-1] != hi)
        assert set(right["outcomes"]) >= set(OUTCOME_FIELDS)
        left_overlap = {b["offset"]: b for b in left["bars"] if b["offset"] >= -10}
        right_overlap = {b["offset"]: b for b in right["bars"] if b["offset"] <= 0}
        assert left_overlap == right_overlap, sample["chart_id"]
    assert windows["blind_truncated"] == 0, windows
    return windows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("day")
    args = parser.parse_args()
    pdfmetrics.registerFont(TTFont(FONT, os.environ.get("ACT078A_CJK_FONT", FONT_PATH)))
    blind, post = [json.loads((args.run / name).read_text()) for name in ("chart_d_only.json", "chart_post.json")]
    windows = ensure_pair(blind, post)
    args.output.mkdir(parents=True, exist_ok=True)
    receipt = {"samples": len(blind), **windows, "files": []}
    for mode, samples in (("blind", blind), ("post", post)):
        filename = f"PFT_V4_ACT078A_CODEX_{DEFAULT_NAME[mode]}_{args.day}.pdf"
        path = args.output / filename
        assert not path.exists(), path
        tmp = path.with_suffix(".pdf.incoming")
        doc = canvas.Canvas(str(tmp), pagesize=landscape(A4), pageCompression=1, invariant=1)
        doc.setTitle(f"PFT V4 ACT-078A {DEFAULT_NAME[mode]}")
        doc.setAuthor("CODEX_MAC")
        build_pages(doc, samples, mode)
        doc.save()
        with tmp.open("rb") as source:
            pdf = PdfReader(source)
            expected_pages = math.ceil(len(samples) / 6)
            assert len(pdf.pages) == expected_pages
            pages = [p.extract_text() for p in pdf.pages]
            for index, sample in enumerate(samples):
                assert str(sample["chart_id"]) in pages[index // 6]
            for label in ("T+2", "T+5", "T+10", "MAE5"):
                assert all((label in p) == (mode == "post") for p in pages), label
        data = tmp.read_bytes()
        assert len(data) < 8_500_000
        tmp.rename(path)
        receipt["files"].append({"name": filename, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "pages": expected_pages})
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
