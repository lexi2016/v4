"""Build independently truncated, anonymously labeled chart and CSV views."""
from __future__ import annotations

from collections import Counter
import csv
from html import escape
from io import BytesIO, StringIO
import random
import re
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

import numpy as np
import pandas as pd

from dictionary062 import HOLD, RELAPSE, LOW_WICK_NAMES

SEED = 20261125
BAR_COLUMNS = ("bar", "open", "high", "low", "close", "volume", "white_line", "yellow_line")
SVG_NS = "{http://www.w3.org/2000/svg}"
SHORT_ID = re.compile(r"BLIND_(?:0[1-9]|1[0-6])")
DATE = re.compile(r"(?<![\w.])(?:19|20)\d{2}(?:[-/.年](?:0?[1-9]|1[0-2])[-/.月](?:0?[1-9]|[12][0-9]|3[01])|(?:0[1-9]|1[0-2])(?:0[1-9]|[12][0-9]|3[01]))(?!\w)")
MARKET_CODE = re.compile(r"\b\d{6}\.(?:SH|SZ|BJ)\b", re.IGNORECASE)
OUTCOME = re.compile(r"\b(?:peak|relapse|reveal|hold|retention|outcome|first_warn|archetype|cohort)\b|回吐|保持|峰日|峰涨|D\s*\+\s*20|T\s*\+\s*20", re.IGNORECASE)


def label(i):
    return f"t{i:+d}" if i else "t0"


def stage_bar(stock, anchor, ordinal):
    raw, adjusted, _ = stock.get(ordinal, anchor)
    if adjusted is None or raw is None or not np.isfinite(raw).all():
        return None
    return tuple(float(x) for x in raw)


def cases(inputs, stores):
    waves = inputs["waves"].loc[inputs["waves"].full20].copy()
    summary = inputs["stocks"]
    waves["low_wick"] = waves.name.isin(LOW_WICK_NAMES)
    waves["high_divergence"] = waves.security_id.map(summary.high_divergence)
    waves["frequent_n"] = waves.security_id.map(summary.complete_n)
    waves["old_pair"] = waves.svg_pair_id.notna()
    valid = []
    for row in waves.itertuples(index=False):
        stock = stores[row.security_id]
        assert int(stock.calendar[row.D_ordinal]) == row.D
        anchor = stock.available_rows[row.D_ordinal]
        observed_warning = row.warning_first_offset
        assert not np.isfinite(observed_warning) or observed_warning == int(observed_warning)
        b_cut = int(observed_warning) if np.isfinite(observed_warning) and observed_warning <= 5 else 3
        assert 1 <= b_cut <= 5
        bars = [stage_bar(stock, anchor, row.D_ordinal + i) for i in range(-15, b_cut + 1)]
        if all(x is not None for x in bars):
            valid.append((row, b_cut, bars))
    return valid


def select(valid):
    """Reserve all six observed low-wick stocks and all archetypes, then fill balanced quotas."""
    def priority(case):
        row = case[0]
        return (row.old_pair, not row.low_wick, not row.high_divergence, -row.frequent_n,
                row.security_id, row.D)
    ordered = sorted(valid, key=priority)
    selected, groups = {}, Counter()

    def eligible(case):
        return case[0].event_id not in selected and groups[case[0].cohort] < 8

    def add(case):
        row = case[0]
        assert eligible(case)
        groups[row.cohort] += 1
        selected[row.event_id] = case

    def reserve(test):
        matches = [case for case in ordered if eligible(case) and test(case[0])]
        assert matches, "Frozen representation/capacity constraint infeasible"
        add(min(matches, key=lambda case: (case[0].old_pair, groups[case[0].cohort], priority(case))))

    for archetype in "ABCD":
        reserve(lambda row: row.archetype == archetype)
    for name in sorted(LOW_WICK_NAMES - {x[0].name for x in selected.values()}):
        reserve(lambda row: row.name == name)
    for case in ordered:
        if eligible(case):
            add(case)
        if len(selected) == 16:
            break
    assert groups == {HOLD: 8, RELAPSE: 8}
    assert {case[0].archetype for case in selected.values()} == set("ABCD")
    assert LOW_WICK_NAMES <= {case[0].name for case in selected.values()}
    output = list(selected.values())
    random.Random(SEED).shuffle(output)
    return output


def csv_bytes(bars):
    stream = StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(BAR_COLUMNS)
    for i, bar in enumerate(bars, -15):
        writer.writerow((label(i), *(format(x, ".16e") for x in bar)))
    return stream.getvalue().encode("ascii")


def draw(case_id, stage, bars):
    points = tuple(enumerate(bars, -15))
    last = points[-1][0]
    low = min(min(b[2], b[5], b[6]) for _, b in points)
    high = max(max(b[1], b[5], b[6]) for _, b in points)
    gap = max((high - low) * .06, abs(high) * .002)
    low -= gap
    high += gap
    v_max = max(b[4] for _, b in points)
    spacing = 688 / len(points)
    x = lambda i: 72 + spacing * (i + 15.5)
    y = lambda price: 254 - 199 * (price - low) / (high - low)
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="790" height="374" viewBox="0 0 790 374">',
        '<rect width="790" height="374" fill="#101927"/>',
        f'<title>{escape(case_id)} Stage {stage} {label(last)}</title>',
        f'<text x="28" y="30" fill="#f0f3fa" font-size="18">{escape(case_id)} · Stage {stage} · {label(last)}</text>',
        '<path d="M28 330H760 M28 273H760" stroke="#637085"/>',
    ]
    for step in range(5):
        value = low + (high - low) * step / 4
        h = y(value)
        parts.extend((
            f'<path d="M72 {h:.2f}H760" stroke="#26364c"/>',
            f'<text x="66" y="{h+3:.2f}" text-anchor="end" fill="#bfccda" font-size="10">{value:.4g}</text>',
        ))
    candle_width = min(14, spacing * .55)
    for i, (open_, high_, low_, close, vol, _, _) in points:
        color = "#ff716b" if close >= open_ else "#45c5a1"
        vy = 328 - 45 * vol / v_max
        px = x(i)
        top = min(y(open_), y(close))
        body = max(.9, abs(y(close) - y(open_)))
        parts.extend((
            f'<g data-bar="{label(i)}">',
            f'<line x1="{px:.2f}" x2="{px:.2f}" y1="{y(high_):.2f}" y2="{y(low_):.2f}" stroke="{color}"/>',
            f'<rect x="{px-candle_width/2:.2f}" y="{top:.2f}" width="{candle_width:.2f}" height="{body:.2f}" fill="{color}"/>',
            f'<rect x="{px-candle_width/2:.2f}" y="{vy:.2f}" width="{candle_width:.2f}" height="{328-vy:.2f}" fill="{color}"/>',
            "</g>",
            f'<text x="{px:.2f}" y="348" text-anchor="middle" fill="#bfccda" font-size="11">{label(i)}</text>',
        ))
    for position, color in ((5,"#f1f4fa"),(6,"#f3c55b")):
        dimensions = " ".join(f"{x(i):.2f},{y(bar[position]):.2f}" for i, bar in points)
        parts.append(f'<polyline points="{dimensions}" fill="none" stroke="{color}" stroke-width="1.3"/>')
    parts.append('<text x="29" y="367" fill="#bfccda" font-size="11">OHLCV · white line · yellow line</text></svg>')
    return "".join(parts).encode("utf-8")


def member_info(name):
    info = ZipInfo(name)
    info.compress_type = ZIP_DEFLATED
    return info


def check(payload, reveal, roster):
    """Fail closed on member names, identity tokens, outcome terms and physical window boundaries."""
    expected = reveal.set_index("case_id",verify_integrity=True)
    denied_id = re.compile(r"(?<![\w.])(?:" + "|".join(c.split(".")[0] for c in sorted(roster.index)) + r")(?![\w.])")
    denied_names = tuple(roster.name.astype(str))
    counts = Counter()
    with ZipFile(BytesIO(payload)) as package:
        assert package.testzip() is None and not package.comment
        members = package.infolist()
        assert len(members) == len({x.filename for x in members}) == 64
        for info in members:
            stage, file = info.filename.split("/")
            case, ext = file.split(".")
            assert stage in "AB" and SHORT_ID.fullmatch(case) and ext in ("csv","svg")
            assert not info.is_dir() and not info.extra and not info.comment
            assert info.date_time == (1980,1,1,0,0,0)
            text = package.read(info).decode("utf-8")
            assert not MARKET_CODE.search(text) and not denied_id.search(text), "Blind security-code leak"
            assert not any(name in text for name in denied_names), "Blind security-name leak"
            assert not DATE.search(text), "Blind exact calendar date leak"
            assert not OUTCOME.search(text), "Blind outcome or reveal-marker leak"
            stop = 0 if stage == "A" else int(expected.loc[case,"stage_b_cutoff_bar"])
            labels = [label(i) for i in range(-15, stop + 1)]
            if ext == "csv":
                rows = list(csv.reader(StringIO(text)))
                assert tuple(rows[0]) == BAR_COLUMNS and [r[0] for r in rows[1:]] == labels
                assert all(len(r) == len(BAR_COLUMNS) and all(np.isfinite(float(x)) for x in r[1:]) for r in rows[1:])
            else:
                root = ET.fromstring(text)
                assert root.tag == SVG_NS + "svg"
                assert [e.attrib["data-bar"] for e in root.findall(SVG_NS + "g")] == labels
                assert set(re.findall(r"(?<!\w)t(?:[+-]\d+|0)(?!\w)",text)) == set(labels)
                assert root.find(SVG_NS + "title").text == f"{case} Stage {stage} {label(stop)}"
                assert all(len(e.get("points").split()) == len(labels) for e in root.findall(SVG_NS + "polyline"))
                assert len(root.findall(SVG_NS + "polyline")) == 2
            counts[f"{stage}_{ext}"] += 1
    assert counts == {"A_csv":16,"A_svg":16,"B_csv":16,"B_svg":16}
    return {"assertions_pass": True, "files_scanned": 64, "stage_files":dict(counts),
            "real_stock_codes":0,"stock_names":0,"real_calendar_dates":0,"outcome_tokens":0,
            "future_bars":0,"reveal_key_members":0,"xml_valid":32,"seed":SEED}


def build(inputs, stores, chosen=None, valid_n=None):
    if chosen is None:
        valid = cases(inputs, stores)
        valid_n = len(valid)
        chosen = select(valid)
    stream = BytesIO()
    key = []
    with ZipFile(stream,"w") as package:
        for rank, (row, stop, bars) in enumerate(chosen, 1):
            alias = f"BLIND_{rank:02}"
            for stage, view in (("A",bars[:16]),("B",bars)):
                package.writestr(member_info(f"{stage}/{alias}.csv"),csv_bytes(view))
                package.writestr(member_info(f"{stage}/{alias}.svg"),draw(alias,stage,view))
            key.append({
                "case_id":alias, "ts_code":row.security_id, "stock_name":row.name, "archetype":row.archetype,
                "D":f"{str(row.D)[:4]}-{str(row.D)[4:6]}-{str(row.D)[6:]}",
                "stage_b_cutoff_bar":stop, "stage_b_rule":"FIRST_OBSERVED_WARN_BY_D_PLUS_5" if
                np.isfinite(row.warning_first_offset) and row.warning_first_offset<=5 else "FIXED_D_PLUS_3",
                "warning_earlier_unavailable_n":row.warning_earlier_unavailable_n,
                "exit_path_class":row.exit_path_class, "peak_day":row.peak_day,
                "peak_rise_pct":row.raw_max_rise_pct_same_basis_exact,
                "peak_post5_max_drawdown_pct":row.peak_post5_max_dd_pct,
                "peak_post5_status":row.peak_post5_status, "D20_return_pct":row.close_ret_D20_pct,
                "true_cohort":"RELAPSE" if row.cohort == RELAPSE else "HOLD",
                "overlap_ACT061A_24_SVG":row.old_pair,"is_low_upper_wick_ACT061B":row.low_wick,
                "is_high_divergence_ACT061A":row.high_divergence,"complete_wave_n":int(row.frequent_n),
                "frozen_event_id":row.event_id, "first_warning_relative_bar":row.warning_first_offset,
                "first_warning_relation":row.warning_relation_to_peak,
            })
    reveal = pd.DataFrame(key)
    assert reveal.case_id.is_unique and reveal.frozen_event_id.is_unique
    payload = stream.getvalue()
    scan = check(payload,reveal,inputs["stocks"])
    return payload,reveal,scan | {
        "eligible_full_wave_window_n":valid_n,"cases":len(chosen),
        "new_cases":int((~reveal.overlap_ACT061A_24_SVG).sum()),
        "old_cases":int(reveal.overlap_ACT061A_24_SVG.sum()),
        "archetypes_n":reveal.archetype.value_counts().to_dict(),
        "cohorts_n":reveal.true_cohort.value_counts().to_dict(),
        "low_wick_stock_n":reveal.loc[reveal.is_low_upper_wick_ACT061B,"ts_code"].nunique(),
        "high_divergence_case_n":int(reveal.is_high_divergence_ACT061A.sum()),
        "flagged_warn_earlier_missing_case_n":int(reveal.warning_earlier_unavailable_n.gt(0).sum()),
    }
