"""ACT-059A Task C only: package fixed, staged charts from the frozen Reader."""
from __future__ import annotations

from collections import Counter
import csv
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
from io import BytesIO, StringIO
import importlib.util
import json
from math import isclose, isfinite
from pathlib import Path
import sys
from time import perf_counter
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parent
ACT058A = ROOT.parent / 'act058a_hidden_kb42_20261125'
MASTER = '04_ACT058B_14_CASES.csv'
PACK = ROOT / 'delivery/ACT059A_14CASE_LIGHT_PACK.zip'
RECEIPT = ROOT / 'evidence/case_receipt.json'
STAGES = (
    ('stage1_Dminus1', -1, 'stage1_bars.csv', '阶段 1 · 截至 D−1'),
    ('stage2_D0', 0, 'stage2_bars.csv', '阶段 2 · 加看 D 日'),
    ('stage3_followup', 25, 'case_bars.csv', '阶段 3 · 后续路径'),
)
FAMILIES = ('S-Pullback', 'S-ReAdvance', 'S-Rebuild', 'E-Reversal')
FAMILY_COLORS = ('#68ddd3', '#a8adff', '#ff9fbd', '#f5c583')
FIELDS = ('open', 'high', 'low', 'close', 'volume', 'white', 'yellow')
BAR_FIELDS = ('case_id', 'offset', 'date', 'bar_status',
              *(f'original_{field}' for field in FIELDS),
              *(f'd_basis_{field}' for field in FIELDS), *FAMILIES)
REASONS = ('maximum_peak_gain', 'most_negative_post_peak_5_session_drawdown')
CASES = {
    '000547.SZ': ('20251110', '20251211'), '002865.SZ': ('20251224', '20261023'),
    '605198.SH': ('20260521', '20250612'), '601899.SH': ('20260701', '20251229'),
    '002715.SZ': ('20250814', '20251111'), '301076.SZ': ('20250407', '20241203'),
    '300454.SZ': ('20250123', '20260105'),
}
OUTCOME_FIELDS = (
    'observed_sessions', 'scheduled_sessions', 'path_status', 'right_censored_rows',
    'd_close_basis', 'peak_day', 'peak_D', 'raw_max_rise_pct', 'peak_high_d_basis', 'peak_status',
    'peak_post5_observed_sessions', 'peak_post5_status', 'peak_post5_max_dd_pct',
    'peak_post5_sessions_to_trough', 'peak_post5_dd_speed_pp_per_session',
)
NS = '{http://www.w3.org/2000/svg}'


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'


def csv_text(rows):
    output = StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=tuple(rows[0]), lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()


def load_sources():
    stamps = json.loads((ROOT / 'inputs/source_manifest.json').read_text())
    required = {MASTER, '01_ACT058B_KB42_MANUAL_V1.md', '05_ACT059A_CODEX_MAC_PROMPT.md'}
    input_ids = {item['name']: item for item in stamps if item['name'] in required}
    assert set(input_ids) == required
    for file, identity in input_ids.items():
        data = (ROOT / 'inputs' / file).read_bytes()
        assert (len(data), sha256(data).hexdigest()) == (identity['bytes'], identity['sha256'])
    with (ROOT / 'inputs' / MASTER).open(encoding='utf-8-sig', newline='') as handle:
        master = list(csv.DictReader(handle))
    expected = {(code, d, reason) for code, dates in CASES.items() for d, reason in zip(dates, REASONS)}
    assert len(master) == 14
    assert {(r['security_id'], r['D'], r['selection_reason']) for r in master} == expected
    assert all(r['event_id'] == f"{r['security_id']}/{r['D']}" for r in master)
    spec = importlib.util.spec_from_file_location('act058a_compute', ACT058A / 'compute.py')
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    assert previous.FAMILIES == FAMILIES
    _, events, signals, fingers, r56, r50, identities = previous.frozen_inputs()
    cfg, frame, calendar, binding = previous.bind_projection(r56, r50)
    frame = frame.loc[frame.canonical.isin(CASES)]
    stocks = {code: previous.Stock(code, daily, cfg['events'][code], calendar)
              for code, daily in frame.groupby('canonical', sort=True)}
    assert set(stocks) == set(CASES)
    # Hash event keys to obtain a stable opaque order without using outcomes or reasons.
    opaque = [(sha256(f"ACT059A-cases-v1|{r['event_id']}".encode()).hexdigest(), r) for r in master]
    order = [(f'K-{digest[:8].upper()}', r) for digest, r in sorted(opaque)]
    assert len({case_id for case_id, _ in order}) == 14
    return previous, stocks, events, signals, fingers, order, {
        'master_inputs': input_ids, 'inherited_inputs': identities,
        'frozen_reader': cfg['provenance']['bound'], 'reader_projection': binding,
        'case_reader_rows': len(frame),
        'act058a_compute_sha256': sha256((ACT058A / 'compute.py').read_bytes()).hexdigest(),
    }


def numeric_fields(values, prefix):
    return {f'{prefix}_{field}': float(v) if isfinite(v) else None
            for field, v in zip(FIELDS, values if values is not None else (float('nan'),)*7)}


def compile_cases(previous, stocks, events, signals, fingers, order):
    bars, outcomes, mappings = {}, {}, []
    for case_id, master in order:
        code, d = master['security_id'], master['D']
        stock = stocks[code]
        at = int(master['D_ordinal'])
        source = events.loc[events.security_id.eq(code) & events.D.eq(int(d))].iloc[0]
        assert int(source.exchange_session_ordinal) == at
        assert str(stock.calendar[at]) == d and stock.available_rows[at] == stock.lookup[d]
        frozen = signals.loc[signals.security_id.eq(code)].set_index('exchange_session_ordinal')
        assert bool(frozen.at[at, 'reverse_independent'])
        anchor = stock.lookup[d]
        assert anchor == int(frozen.at[at, 'event_slice_end_bar'])
        fingerprint = fingers.loc[fingers.security_id.eq(code) & fingers.D.eq(int(d))]
        assert len(fingerprint) == 1
        finger = fingerprint.iloc[0]
        for field in OUTCOME_FIELDS:
            if isinstance(finger[field], str):
                assert finger[field] == master[field], (case_id, field)
            else:
                assert isclose(float(finger[field]), float(master[field]), rel_tol=5e-11, abs_tol=1e-12), (case_id, field)
        assert finger.peak_status == 'FULL_WINDOW' and finger.peak_post5_status == 'COMPLETE'
        rows = []
        for off in range(-25, 26):
            slot = at + off
            date = str(stock.calendar[slot]) if 0 <= slot < len(stock.calendar) else None
            original, converted, status = stock.get(slot, anchor)
            row = {'case_id': case_id, 'offset': off, 'date': date, 'bar_status': status}
            row.update(numeric_fields(original, 'original'))
            row.update(numeric_fields(converted, 'd_basis'))
            availability = previous.signal_status(stock, slot)
            if slot in frozen.index:
                assert int(frozen.at[slot, 'D']) == int(date)
            for family in FAMILIES:
                hit = slot in frozen.index and bool(frozen.at[slot, family])
                row[family] = 'FROZEN_HIT' if hit else availability
                if -5 <= off <= 0:
                    group = row[family] if not row[family].startswith('UNAVAILABLE') else 'UNAVAILABLE'
                    assert group == master[f'{family}_D{off:+d}'], (case_id, off, family)
            rows.append(row)
        assert tuple(rows[0]) == BAR_FIELDS
        assert isclose(rows[25]['d_basis_close'], float(finger.d_close_basis), rel_tol=5e-11)
        peak = rows[25 + int(finger.peak_day)]
        assert int(peak['date']) == int(finger.peak_D)
        assert isclose(peak['d_basis_high'], float(finger.peak_high_d_basis), rel_tol=5e-11)
        outcomes[case_id] = {'case_id': case_id, **{field: master[field] for field in OUTCOME_FIELDS}}
        mappings.append({'case_id': case_id, **master, 'd_affine_price_scale': float(stock.a[anchor]),
                         'd_affine_price_offset': float(stock.b[anchor]), 'd_affine_volume_scale': float(stock.v[anchor])})
        bars[case_id] = rows
    return bars, outcomes, mappings


def display_date(date):
    return f'{date[:4]}-{date[4:6]}-{date[6:8]}' if date else 'NA'


def label(x, y, value, **attributes):
    attrs = ' '.join(f'{key.replace("_", "-")}="{escape(str(val), quote=True)}"' for key, val in attributes.items())
    return f'<text x="{x:.2f}" y="{y:.2f}" {attrs}>{escape(str(value))}</text>'


def line(x1, y1, x2, y2, color, width=1):
    return f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="{width}"/>'


def rect(x, y, w, h, color, **attributes):
    attrs = ' '.join(f'{key.replace("_", "-")}="{val}"' for key, val in attributes.items())
    return f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" fill="{color}" {attrs}/>'


def render(rows, phase, outcome=None):
    case_id = rows[0]['case_id']
    num = len(rows)
    width, height = 1280, 710 if outcome else 680
    x0, x1, price_top, price_end, volume_top, volume_end = 112, 1252, 82, 351, 393, 465
    step = (x1-x0) / num

    def x(i):
        return x0 + (i+.5)*step

    values = [r[f'd_basis_{k}'] for r in rows for k in ('high', 'low', 'white', 'yellow')
              if r[f'd_basis_{k}'] is not None]
    assert values
    span = max(max(values)-min(values), max(values)*0.015)
    vmin, vmax = min(values)-.06*span, max(values)+.11*span
    volume_max = max(r['d_basis_volume'] or 0 for r in rows)
    assert volume_max > 0

    def yp(value):
        return price_end - (price_end-price_top)*(value-vmin)/(vmax-vmin)

    def yv(value):
        return volume_end - (volume_end-volume_top)*value/volume_max

    guide, muted, text = '#30445a', '#b1c1d3', '#edf4ff'
    white, yellow, up, down = '#f3f6fb', '#f4cb5a', '#ff817e', '#66d9ab'
    valid_dates = [r['date'] for r in rows if r['date']]
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">',
           f'<title id="title">{case_id} · {phase}</title>',
           '<desc id="desc">交易所日栏 K 线，事件 D 冻结等价价格和量，W 白线、Y 黄线及四族冻结信号轨道。</desc>',
           '<style>text{font-family:system-ui,PingFang SC,Noto Sans CJK SC,sans-serif;font-size:12px} .title{font-size:23px;font-weight:700} .sub{font-size:13px} .axis{font-size:11px;font-variant-numeric:tabular-nums} .note{font-size:12px} .family{font-size:12px;font-weight:650}</style>',
           rect(0, 0, width, height, '#101d2d'),
           label(24, 34, f'{case_id}  /  {phase}', fill=text, **{'class': 'title'}),
           label(25, 57, f'{display_date(valid_dates[0])} 至 {display_date(valid_dates[-1])}  ·  交易所日历  ·  K 线、W/Y 与成交量统一到事件 D 冻结基准', fill=muted, **{'class': 'sub'}),
           label(692, 34, '红＝收高于开盘   绿＝收低于开盘   灰＝开收相等', fill=muted, **{'class': 'sub'}),
           line(1056, 30, 1081, 30, white, 2), label(1086, 34, 'W 白线', fill=white),
           line(1152, 30, 1177, 30, yellow, 2), label(1182, 34, 'Y 黄线', fill=yellow),
           rect(x0, price_top, x1-x0, price_end-price_top, '#16263a'),
           rect(x0, volume_top, x1-x0, volume_end-volume_top, '#16263a'),
           label(24, 80, '等价价格', fill=muted), label(24, 386, '等价成交量', fill=muted),
           label(24, 498, '原冻结四族', fill=muted),
           label(882, 498, '◆ 冻结命中      · 未见冻结命中      × 不可判定', fill=muted),
           label(24, 609, '交易日偏移', fill=muted), label(24, 630, '日期 月/日', fill=muted)]
    for i in range(6):
        tick = vmin + (vmax-vmin)*i/5
        ytick = yp(tick)
        out.extend([line(x0, ytick, x1, ytick, guide), label(x0-9, ytick+4, f'{tick:.2f}', fill=muted, text_anchor='end', **{'class': 'axis'})])
    for tick in (0, volume_max/2, volume_max):
        ytick = yv(tick)
        out.extend([line(x0, ytick, x1, ytick, guide), label(x0-9, ytick+4, f'{tick:.3g}', fill=muted, text_anchor='end', **{'class': 'axis'})])
    for i, (fam, color) in enumerate(zip(FAMILIES, FAMILY_COLORS)):
        y = 519+20*i
        out.extend([rect(x0, y-9, x1-x0, 17, '#16263a'), label(24, y+4, fam, fill=color, **{'class': 'family'})])
    for i, row in enumerate(rows):
        off, day = row['offset'], row['date']
        center = x(i)
        out.append(f'<g data-slot="{off}" data-date="{day or ""}" data-status="{row["bar_status"]}">')
        if off == 0:
            out.append(rect(center-step/2, price_top, step, 514, '#6596bf', opacity='.19'))
        if off == 0 or off % 5 == 0:
            out.append(line(center, price_top, center, volume_end, '#566c82' if off == 0 else guide))
        fmt = str if day else lambda _: 'NA'
        vals = ' · '.join(f"{short} {fmt(row[f'd_basis_{key}']) if row[f'd_basis_{key}'] is not None else 'NA'}"
                          for key, short in zip(FIELDS, ('O', 'H', 'L', 'C', 'V', 'W', 'Y')))
        out.append(f'<title>{day or "NA"} / D{off:+d} · {row["bar_status"]} · {escape(vals)}</title>')
        if row['bar_status'] == 'OBSERVED':
            o, h, low, c, v = (row[f'd_basis_{key}'] for key in FIELDS[:5])
            color = up if c > o else down if c < o else '#bacddd'
            body = min(step*.52, 16)
            out.extend(['<g class="candle">', line(center, yp(h), center, yp(low), color, 1.45),
                        rect(center-body/2, min(yp(o), yp(c)), body, max(abs(yp(o)-yp(c)), 1.4), color), '</g>',
                        rect(center-body/2, yv(v), body, volume_end-yv(v), color, opacity='.79', **{'class': 'volume'})])
        else:
            out.extend([rect(center-step/2, price_top, step, price_end-price_top, '#33435b', opacity='.48'),
                        label(center, (price_top+price_end)/2, '×', fill=muted, text_anchor='middle', **{'class': 'gap'})])
        for j, (fam, color) in enumerate(zip(FAMILIES, FAMILY_COLORS)):
            status = row[fam]
            y = 519+20*j
            glyph = '◆' if status == 'FROZEN_HIT' else '·' if status == 'NO_FROZEN_HIT' else '×'
            out.append(f'<g data-family="{fam}" data-signal="{status}"><title>{fam} · {status}</title>'
                       + label(center, y+4, glyph, fill=color if glyph == '◆' else muted, text_anchor='middle') + '</g>')
        off_text = 'D' if not off else f'{off:+d}' if off > 0 else f'−{abs(off)}'
        day_text = day[4:6]+'/'+day[6:] if day else 'NA'
        out.extend([label(center, 609, off_text, fill=text if off == 0 else muted, text_anchor='middle', **{'class': 'axis'}),
                    label(center, 630, day_text, fill=text if off == 0 else muted, text_anchor='middle',
                          transform=f'rotate(-61 {center:.2f} 630)' if num > 30 else 'rotate(0)', **{'class': 'axis'}), '</g>'])
    for key, color in (('white', white), ('yellow', yellow)):
        points = []
        pen_down = False
        for i, row in enumerate(rows):
            value = row[f'd_basis_{key}']
            if value is None:
                pen_down = False
                continue
            points.append(f'{"L" if pen_down else "M"}{x(i):.2f} {yp(value):.2f}')
            pen_down = True
        if points:
            out.append(f'<path data-series="{key}" d="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.55" pointer-events="none"/>')
        for i, row in enumerate(rows):
            if row[f'd_basis_{key}'] is not None and all(
                not 0 <= adjacent < num or rows[adjacent][f'd_basis_{key}'] is None for adjacent in (i-1, i+1)
            ):
                out.append(f'<circle data-single="{key}" cx="{x(i):.2f}" cy="{yp(row[f"d_basis_{key}"]):.2f}" r="2.0" fill="{color}"/>')
    if outcome:
        peak_idx = 25 + int(outcome['peak_day'])
        at = x(peak_idx)
        out.extend([line(at, price_top+14, at, yp(rows[peak_idx]['d_basis_high']), '#f4cb5a', 1.5),
                    label(at, price_top+10, '窗口峰', fill=yellow, text_anchor='middle'),
                    label(25, 669, f"冻结结果  ·  窗口峰 {display_date(outcome['peak_D'])} / D+{outcome['peak_day']}  ·  对 D 收盘峰涨 {float(outcome['raw_max_rise_pct']):.2f}%  ·  峰后 5 栏回撤 {float(outcome['peak_post5_max_dd_pct']):.2f}%", fill=yellow, **{'class': 'note'})])
    out.extend([label(25, height-15, '× 价格区表示未画 K 线的排程栏。悬停读当栏细值，完整原值与状态见本阶段 CSV。', fill=muted, **{'class': 'note'}), '</svg>'])
    return '\n'.join(out)


COMMON_DEFINITIONS = '''# 图与 CSV 读法

- `case_id` 是这一包内的随机样式固定案号。`offset` 是交易所交易日相对 D 的排程位置。`date` 是冻结交易所日历键，空白为 NA。
- `original_open/high/low/close/volume/white/yellow` 直接来自冻结 V4 Reader 的 QFQ（前复权）日栏，始终保留同源原值。`white` 是原 W 白线，`yellow` 是原 Y 黄线。
- `d_basis_*` 是画图用的固定换算。OHLC、W、Y 使用 `(原值−b_D)/a_D`，量使用 `原量/v_D`。指定事件 D 基准来自 ACT-056A 使用的冻结 affine 链，三个参数在这个案例的三个阶段中相同。ACT-058A 的前兆指标使用 D−1 基准，案例图与前兆指标的换算各沿用其各自口径。D 日或后续日栏不参与各阶段价格轴和量轴范围计算，除非该阶段包含相应日栏。各阶段轴范围可随可见数据变化。
- `bar_status=OBSERVED` 表示有原日栏且能用统一基准换算。`NO_READER_BAR_ON_SESSION` 是有交易日但缺股栏，`D_BASIS_ALIAS_DISCONTINUITY` 是基准链未连通，`READER_BAR_WITHOUT_VALID_ACTIVITY_OR_BASIS` 是活动或基准无效，`D_BASIS_NONPOSITIVE_OHLCV` 是换算后 OHLCV 无效。`LEFT_CENSORED_BY_CALENDAR` 和 `RIGHT_CENSORED_AT_20261120` 表示超出冻结日历边界。缺位的价格、线或量留空，K 线留白，W/Y 分别在各自缺点断开。
- 四族列沿用原冻结 S-Pullback、S-ReAdvance、S-Rebuild、E-Reversal 的稀疏命中。`FROZEN_HIT` 表示原表同日同族有命中，`NO_FROZEN_HIT` 表示日栏可判定且原稀疏表无该族命中。`UNAVAILABLE_BAR`／`UNAVAILABLE_PRE_WARMUP` 表示缺有效栏／原预热未完成，图上均为 ×。未重新扫描信号。
- 红色实体表示收盘高于开盘，绿色表示收盘低于开盘，灰色表示开收相等。量栏与 K 线同色。SVG 日栏悬停展示等价 O、H、L、C、V、W、Y，并保留完整日期和状态。
'''
START = '''# ACT-059A · 14 案分阶段独立复核

按包内案号顺序走完当前阶段 14 案并另存当期评语，再打开下一阶段。各阶段均可离线查看。入口 `index.html` 提供图卡和本阶段 CSV。

1. 打开 `stage1_Dminus1/`，只看 D−25 到 D−1。记录准备结构、观察判断及一条失效条件，保存 14 案全部评语。
2. 打开 `stage2_D0/`，补看 D 日。另存 14 案当日确认及未确认项，保留第一阶段原始评语。
3. 打开 `stage3_followup/`，先读逐日路径与首次失效，再看冻结窗口结果和预判断差异。

阶段 1 和 2 评语均已另存后，才进入 stage3 或读取配套 108 路径补表。`MASTER_ONLY/` 是供 CHAT 对账的独立目录，Gemini 阶段复核不读。阶段隔离依赖阅读顺序，目录可访问。候选案号只在本轮稳定，图卡用于研究复核。
'''
MASTER_START = '''# 仅供 CHAT 对账

`case_mapping.csv` 保留 04 号原始行的证券、日期、事件键、选择理由、已有评语状态、前兆字段、信号时点和结果，另含本包各案 D 冻结换算参数。`case_id` 与三个阶段的图、日栏及结果一一对应。
'''
STAGE3_DEFINITIONS = '''
## 冻结结果字段

`stage3_outcomes.csv` 继承 ACT-056A 指纹和 04 号表。`peak_D` 与 `peak_day` 是 D+1～D+20 中最高 H 的日期与相对位置，同值取早。`peak_high_d_basis` 对 `d_close_basis` 计算 `raw_max_rise_pct`。`peak_post5_max_dd_pct` 取峰后五个连续交易日中的最低 L 对峰高的百分比，最大值限制为 0，`peak_post5_sessions_to_trough` 记录峰后至最低 L 的排程交易日数。`peak_post5_dd_speed_pp_per_session` 为该回撤百分比除以到达低点的交易日数。`observed_sessions` 和 `scheduled_sessions` 属于原 20 栏峰值窗口，`right_censored_rows` 也只统计该原窗口。`case_bars.csv` 展示完整 51 个排程位置，其中 D+21～D+25 对应是否有日栏另以逐行状态为准。窗口峰是完整路径的回看结果。
'''


def stage_home(title, csv_name, case_ids, final):
    cards = '\n'.join(f'<li><a href="{case_id}.svg">{case_id}</a></li>' for case_id in case_ids)
    outcomes = '<a href="stage3_outcomes.csv">冻结结果 CSV</a>' if final else ''
    return f'''<!doctype html>
<html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title}</title><style>body{{font:16px/1.65 system-ui,sans-serif;margin:48px auto;padding:0 24px;max-width:760px;background:#101d2d;color:#edf4ff}}a{{color:#93d9ff}}ul{{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:10px;list-style:none;padding:0}}li{{padding:12px;background:#16263a;border-radius:5px}}nav a{{margin-right:18px}}</style>
<h1>{title}</h1><nav><a href="{csv_name}">本阶段日栏 CSV</a><a href="FIELDS.md">字段口径</a>{outcomes}</nav>
<ul>{cards}</ul></html>'''


def assemble(bars, outcomes, mappings):
    members = {'START_HERE.md': START, 'MASTER_ONLY/README.md': MASTER_START,
               'MASTER_ONLY/case_mapping.csv': csv_text(mappings)}
    manifest = {'work': 'ACT-059A Task C', 'review_mode': '分阶段独立复核',
                'frozen_reader_asof': '20261120', 'case_count': len(bars),
                'case_ids_in_review_order': list(bars), 'stages': {}}
    for sub, last, csv_name, title in STAGES:
        visible = {case_id: rows[:last+26] for case_id, rows in bars.items()}
        members[f'{sub}/{csv_name}'] = csv_text([r for rows in visible.values() for r in rows])
        members[f'{sub}/index.html'] = stage_home(title, csv_name, bars, last == 25)
        members[f'{sub}/FIELDS.md'] = COMMON_DEFINITIONS + (STAGE3_DEFINITIONS if last == 25 else '')
        for case_id, rows in visible.items():
            members[f'{sub}/{case_id}.svg'] = render(rows, title, outcomes[case_id] if last == 25 else None)
        if last == 25:
            members[f'{sub}/stage3_outcomes.csv'] = csv_text(list(outcomes.values()))
        manifest['stages'][sub] = {'first_offset': -25, 'last_offset': last,
                                   'rows_per_case': last+26, 'index': f'{sub}/index.html',
                                   'bar_csv': f'{sub}/{csv_name}'}
    members['case_manifest.json'] = json_text(manifest)
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED, compresslevel=9) as handle:
        for name, contents in members.items():
            item = ZipInfo(name, date_time=(2026, 11, 25, 0, 0, 0))
            item.external_attr = 0o100644 << 16
            handle.writestr(item, contents.encode(), compress_type=ZIP_DEFLATED, compresslevel=9)
    return output.getvalue(), set(members)


def compare_plot(handle, bars, stage, key, last):
    root = ET.fromstring(handle.read(f'{stage}/{key}.svg'))
    assert all(e.tag not in {NS+'script', NS+'image', NS+'use', NS+'a', NS+'foreignObject'} for e in root.iter())
    groups = [g for g in root.findall(NS+'g') if 'data-slot' in g.attrib]
    assert list(range(-25, last+1)) == [int(g.attrib['data-slot']) for g in groups]
    for row, group in zip(bars, groups, strict=True):
        assert group.attrib['data-date'] == (row['date'] or '')
        assert group.attrib['data-status'] == row['bar_status']
        values = group.find(NS+'title').text
        assert values.startswith(f"{row['date'] or 'NA'} / D{row['offset']:+d} · {row['bar_status']} · ")
        for field, short in zip(FIELDS, ('O', 'H', 'L', 'C', 'V', 'W', 'Y')):
            value = row[f'd_basis_{field}']
            expected = 'NA' if value is None else str(value)
            assert f'{short} {expected}' in values.split(' · '), (key, row['offset'], field)
        candle = group.findall(f'{NS}g[@class="candle"]')
        volume = group.findall(f'{NS}rect[@class="volume"]')
        assert len(candle) == len(volume) == (row['bar_status'] == 'OBSERVED')
        assert [(s.attrib['data-family'], s.attrib['data-signal']) for s in group.findall(f'{NS}g[@data-family]')] == [(f, row[f]) for f in FAMILIES]
    for line_name in ('white', 'yellow'):
        line_element = root.find(f'{NS}path[@data-series="{line_name}"]')
        line_exists = [r[f'd_basis_{line_name}'] is not None for r in bars]
        commands = [p[0] for p in line_element.attrib['d'].split(' ') if p[:1] in ('M', 'L')] if line_element is not None else []
        assert commands == [('L' if i and line_exists[i-1] else 'M') for i, x in enumerate(line_exists) if x]
        singles = root.findall(f'{NS}circle[@data-single="{line_name}"]')
        assert len(singles) == sum(active and not (i > 0 and line_exists[i-1]) and not (i+1 < len(line_exists) and line_exists[i+1])
                                   for i, active in enumerate(line_exists))
    svg_text = ''.join(root.itertext())
    assert ('冻结结果' in svg_text) == (last == 25)
    assert ('窗口峰' in svg_text) == (last == 25)


def verify(package, expected, bars, outcomes, mappings):
    identities = [r['security_id'] for r in mappings] + [r['name'] for r in mappings]
    blocked_early = (*REASONS, *OUTCOME_FIELDS, *identities, '冻结结果', '窗口峰', '峰后回撤', '峰后 5 栏回撤')
    rows_by_stage = {}
    with ZipFile(BytesIO(package)) as handle:
        assert handle.testzip() is None
        names = handle.namelist()
        assert len(names) == len(set(names)) == 56 and set(names) == expected
        manifest = json.loads(handle.read('case_manifest.json'))
        assert manifest['case_ids_in_review_order'] == list(bars)
        for name in names:
            if name.startswith(('stage1_Dminus1/', 'stage2_D0/')):
                contents = handle.read(name).decode()
                assert not any(forbidden in contents for forbidden in blocked_early), name
                assert 'stage3_followup' not in contents and 'MASTER_ONLY' not in contents
        for sub, last, csv_name, _ in STAGES:
            reader = csv.DictReader(StringIO(handle.read(f'{sub}/{csv_name}').decode()))
            assert tuple(reader.fieldnames) == BAR_FIELDS
            count = 0
            for key, rows in bars.items():
                current = rows[:last+26]
                for expected_row in current:
                    assert next(reader) == {k: '' if v is None else str(v) for k, v in expected_row.items()}
                    count += 1
                compare_plot(handle, current, sub, key, last)
            assert next(reader, None) is None
            assert count == 14*(last+26)
            rows_by_stage[sub] = count
        for name, expected_rows in (('stage3_followup/stage3_outcomes.csv', list(outcomes.values())),
                                    ('MASTER_ONLY/case_mapping.csv', mappings)):
            read = list(csv.DictReader(StringIO(handle.read(name).decode())))
            assert read == [{k: str(v) for k, v in row.items()} for row in expected_rows]
    assert len(package) <= 9_500_000
    return {'archive_members': len(names), 'svg_charts_verified_from_zip': 42, 'rows_by_stage': rows_by_stage,
            'exact_source_rows_and_prefixes_passed': 42, 'all_svg_candle_volume_signal_and_wy_gap_checks_passed': True,
            'all_early_members_identity_outcome_scan_passed': True, 'zip_crc_passed': True,
            'preferred_size_met': len(package) <= 2_000_000}


def atomic_bytes(path, data):
    staged = ROOT / 'evidence' / f'case_{path.name}.part'
    with staged.open('xb') as handle:
        handle.write(data)
    staged.replace(path)


def main():
    start = perf_counter()
    previous, stocks, events, signals, fingers, order, inputs = load_sources()
    read_at = perf_counter()
    bars, outcomes, mappings = compile_cases(previous, stocks, events, signals, fingers, order)
    package, expected = assemble(bars, outcomes, mappings)
    compute_at = perf_counter()
    checks = verify(package, expected, bars, outcomes, mappings)
    atomic_bytes(PACK, package)
    assert sha256(PACK.read_bytes()).digest() == sha256(package).digest()
    verify_at = perf_counter()
    status = Counter(r['bar_status'] for rows in bars.values() for r in rows)
    witnesses = []
    sample_keys = {'000547.SZ/20251211', '002865.SZ/20261023', '300454.SZ/20260105'}
    for item in mappings:
        key = item['case_id']
        if item['event_id'] not in sample_keys:
            continue
        series = bars[key]
        witnesses.append({'case_id': key, 'event_id': item['event_id'],
                          'full_calendar_status_counts': dict(Counter(r['bar_status'] for r in series)),
                          'Dminus1': series[24], 'D0': series[25], 'final_slot': series[-1],
                          'peak_date': item['peak_D'], 'peak_gain_pct': item['raw_max_rise_pct'],
                          'postpeak_5_dd_pct': item['peak_post5_max_dd_pct'],
                          'sample_chart_paths': [f'{stage}/{key}.svg' for stage, _, _, _ in STAGES]})
    clean_at = perf_counter()
    receipt = {
        'status': 'PASS_TASK_C_FROZEN_14_STAGED_CASES', 'utc': datetime.now(timezone.utc).isoformat(),
        'output': {'path': str(PACK), 'bytes': len(package), 'sha256': sha256(package).hexdigest()},
        'inputs': inputs, 'case_count': 14, 'scheduled_slots': 714, 'bar_status_counts': dict(status),
        'missing_plot_w': sum(r['d_basis_white'] is None for rows in bars.values() for r in rows),
        'missing_plot_y': sum(r['d_basis_yellow'] is None for rows in bars.values() for r in rows),
        'checks': checks, 'witnesses': witnesses,
        'runtime': {'interpreter': sys.executable, 'psutil_import_path': sys.modules['psutil'].__file__},
        'accounting': {'fit': 0, 'model_load': 0, 'predict': 0, 'tune': 0, 'simulate': 0, 'orders': 0},
        'research_only': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False,
        'seconds': {'read': read_at-start, 'compute': compute_at-read_at, 'verify_and_seal': verify_at-compute_at,
                    'upload': None, 'cleanup_check': clean_at-verify_at},
        'temporary_material': {'reader_files_written': 0, 'chart_render_cache_created': False,
                               'atomic_package_staging_renamed_to_delivery': True},
    }
    atomic_bytes(RECEIPT, json_text(receipt).encode())
    print(json_text({'status': receipt['status'], 'output': receipt['output'], 'bar_status_counts': dict(status),
                     'checks': checks, 'witnesses': [{k: w[k] for k in ('case_id','event_id','sample_chart_paths')} for w in witnesses]}))


if __name__ == '__main__':
    main()
