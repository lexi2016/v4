"""Generate isolated D-only shadow deliverables and the separate user-review atlas."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, deque
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from charts import render_panel
from semantic_shadow import (
    SYMBOL, TRACKS, UNKNOWN, Session, Shadow, as_date, read_baseline, read_cohort,
    read_json, sha256, status, tags, through_sessions, truth, validate_contract,
)

CSV_NAME = 'ACT067B_JUNDA_002865_V40_VS_V41_SHADOW_DONLY_20261127.csv'
ZIP_NAME = 'ACT067B_JUNDA_002865_D_ONLY_BLIND_PACKAGE_20261127.zip'
PDF_NAME = 'ACT067B_JUNDA_002865_USER_REVIEW_ATLAS_DPLUS15_20261127.pdf'
SUMMARY_NAME = 'ACT067B_JUNDA_SHADOW_SUMMARY_20261127.md'
BASELINE_SHA = 'e608234c44eedeed8fb39d452e05ffa20066c855b7290e82b2af5613bedbcdc9'
CHART_BARS = 35
BLIND_COUNT = 12


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def set_date_fields(row):
    return {key: str(as_date(row[key])) if row and row.get(key) else '' for key in ('m25_d_date', 'm25_t_date', 'm25_c_date')}


def method_fields(prefix, row, *, covered=True):
    row = row or {}
    fields = {}
    for method, identifier in (('b1', '#19'), ('b2', '#20'), ('m25', '#25')):
        for level, source in (('raw', 'formula_hit_tags'), ('qualified', 'new_entry_qualified_tags')):
            fields[f'{prefix}_{method}_{level}'] = status(identifier in tags(row.get(source, '')) if covered else None)
    fields[f'{prefix}_entry_status'] = row.get('new_entry_status', 'NO_FORMULA_HIT' if covered else UNKNOWN)
    for key in ('formula_hit_tags', 'new_entry_qualified_tags', 'new_entry_watch_tags', 'new_entry_rejected_tags', 'frozen_raw_only_tags'):
        fields[f'{prefix}_{key}'] = row.get(key, '' if covered else UNKNOWN)
    fields[f'{prefix}_m25_chain_complete'] = status(truth(row.get('m25_chain_complete')) if row else (False if covered else None))
    fields.update({f'{prefix}_{key}': value for key, value in set_date_fields(row).items()})
    return fields


def collect_rows(cohort, history, replay, common, contract, provenance):
    engine = Shadow(contract, continuous_sessions=True)
    cohort_last_idx = next(reversed(cohort.values()))['td_idx']
    rows = []
    for idx, session in enumerate(through_sessions(common, max(cohort))):
        outcomes = engine.advance(session)
        d = session.day
        if d not in cohort:
            continue
        legacy_context = cohort[d]
        if legacy_context['td_idx'] != idx:
            raise ValueError(f'Historical stock index mismatch {d}')
        legacy = history.get(d)
        if legacy and int(legacy['td_idx']) != idx:
            raise ValueError(f'Frozen V4.0 stock index mismatch {d}')
        matched = replay.get(d)
        if matched and int(matched['td_idx']) != idx:
            raise ValueError(f'Replay stock index mismatch {d}')
        replay_fields = method_fields('v40_replay', matched)
        if replay_fields['v40_replay_b1_raw'] != outcomes['b1_raw']:
            raise ValueError(f'Identical #19 RAW expressions disagree on {d}')
        rows.append({
            'ts_code': SYMBOL, 'date': str(d), 'stock_session_index': idx,
            'source_generation': provenance['generation'],
            'price_basis': provenance['market_basis']['price_basis'],
            'volume_basis': provenance['market_basis']['volume_basis'],
            'historical_pit': provenance['historical_pit'],
            'v31_3_formula_tags': legacy_context['formula_hit_tags'],
            'v31_3_structure_status': legacy_context['structure_status'],
            'v31_3_qualified_tags': legacy_context['qualified_tags'],
            'v31_3_watch_tags': legacy_context['watch_tags'], 'v31_3_rejected_tags': legacy_context['rejected_tags'],
            **{f'v31_3_proxy_{key}': value for key, value in set_date_fields(legacy_context).items()},
            'v31_3_proxy_m25_chain_complete': status(truth(legacy_context.get('m25_chain_complete'))),
            'v41_m25_D_DAMAGE_proxy_context_only': set_date_fields(legacy_context)['m25_d_date'],
            'v41_m25_T_YELLOW_TEST_proxy_context_only': set_date_fields(legacy_context)['m25_t_date'],
            'v41_m25_C_REBUILD_CONFIRM_proxy_context_only': set_date_fields(legacy_context)['m25_c_date'],
            'v41_m25_C_REBUILD_CONFIRM_D_candle_body_pct_open': 100*(session.close-session.open)/session.open,
            'v41_m25_C_REBUILD_CONFIRM_D_candle_body_to_range_ratio': abs(session.close-session.open)/(session.high-session.low)
                                                                        if session.high > session.low else '',
            'v41_m25_C_REBUILD_CONFIRM_D_close_location_in_range': (session.close-session.low)/(session.high-session.low)
                                                                  if session.high > session.low else '',
            'v41_m25_HISTORY_PRESERVED_proxy_context_only': legacy_context['m25_repair_id'],
            'v41_m25_RISK_CLEAR_legacy_anchor_broken_context_only': status(truth(legacy_context['anchor_broken_flag'])),
            'v40_frozen_date_present': status(legacy is not None),
            **method_fields('v40_frozen', legacy, covered=legacy is not None),
            'v40_frozen_source_parity': provenance['parity_status'],
            **replay_fields,
            'open_D': session.open, 'high_D': session.high, 'low_D': session.low, 'close_D': session.close,
            'volume_D': session.volume, 'pct_D': session.pct, 'W_D': session.w, 'Y_D': session.y, 'BBI_D': session.bbi, 'J_D': session.j,
            **{f'v41_{key}': value for key, value in outcomes.items()},
            'b2_f03_raw_diff': status(outcomes['USER_FORMULA_B2_F03'] != replay_fields['v40_replay_b2_raw'])
                               if outcomes['USER_FORMULA_B2_F03'] != UNKNOWN else UNKNOWN,
            'blind_possible': idx >= CHART_BARS - 1 and cohort_last_idx - idx >= 15,
        })
    if len(rows) != len(cohort):
        raise ValueError('Output did not cover the full historical cohort')
    return rows


def select_cases(rows):
    pool = [row for row in rows if row['blind_possible']]
    chosen = {}

    def hit(row, field):
        return row[field] == 'TRUE'

    strata = [
        ('V40_B2_RAW_WITHOUT_V41_F03', lambda r: hit(r, 'v40_replay_b2_raw') and not hit(r, 'v41_USER_FORMULA_B2_F03')),
        ('V41_F03_WITHOUT_V40_B2_RAW', lambda r: hit(r, 'v41_USER_FORMULA_B2_F03') and not hit(r, 'v40_replay_b2_raw')),
        ('V40_B2_RAW_AND_V41_F03', lambda r: hit(r, 'v41_USER_FORMULA_B2_F03') and hit(r, 'v40_replay_b2_raw')),
        ('V41_1006_WITHOUT_F03', lambda r: hit(r, 'v41_B2_1006_SCREEN') and not hit(r, 'v41_USER_FORMULA_B2_F03')),
        ('V41_VOLUME_WITHOUT_1006_OR_F03', lambda r: hit(r, 'v41_B2_151_PREV_VOL_X1_20') and not hit(r, 'v41_B2_1006_SCREEN') and not hit(r, 'v41_USER_FORMULA_B2_F03')),
        ('V40_B1_QUALIFIED_V41_FORMAL_UNRESOLVED', lambda r: hit(r, 'v40_replay_b1_qualified') and r['v41_b1_formal'] == UNKNOWN),
        ('V41_B1_RAW_WITH_NO_PRIOR_RAW', lambda r: hit(r, 'v41_b1_raw') and not r['v41_b1_prior_raw_dates']),
        ('V41_B1_PRIOR_RAW_ON_NON_RAW_D', lambda r: not hit(r, 'v41_b1_raw') and bool(r['v41_b1_prior_raw_dates'])),
        ('V40_M25_CHAIN_V41_UNRESOLVED', lambda r: hit(r, 'v40_replay_m25_chain_complete') and r['v41_m25'] == UNKNOWN),
        ('V40_B2_AND_M25_QUALIFIED', lambda r: hit(r, 'v40_replay_b2_qualified') and hit(r, 'v40_replay_m25_qualified')),
        ('HISTORICAL_M25_PROXY_NO_REPLAY_M25', lambda r: hit(r, 'v31_3_proxy_m25_chain_complete') and not hit(r, 'v40_replay_m25_raw')),
        ('HISTORICAL_FROZEN_B2_RAW_DRIFT', lambda r: hit(r, 'v40_frozen_date_present') and r['v40_frozen_b2_raw'] != r['v40_replay_b2_raw']),
    ]

    def add(candidates, reason):
        unused = [r for r in candidates if r['date'] not in chosen]
        if unused:
            def spread(row):
                distance = min((abs(row['stock_session_index'] - i) for i, _ in chosen.values()), default=0)
                return distance, row['stock_session_index']
            pick = max(unused, key=spread)
            chosen[pick['date']] = (pick['stock_session_index'], reason)

    for name, predicate in strata:
        add([row for row in pool if predicate(row)], name)
    while len(chosen) < BLIND_COUNT and len(chosen) < len(pool):
        add(pool, 'D_ONLY_DATE_SPREAD_FILL')
    if len(chosen) != BLIND_COUNT:
        raise ValueError('Insufficient D-only dates for blind package')
    return [{ 'chart_id': f'A{idx:02d}', 'date': day, 'td_idx': td_idx, 'stratum': reason}
            for idx, (day, (td_idx, reason)) in enumerate(sorted(chosen.items()), start=1)]


def render_left_panels(common_path, selected):
    waiting = {as_date(case['date']): case['chart_id'] for case in selected}
    history = deque(maxlen=CHART_BARS)
    panels = {}
    for bar in through_sessions(common_path, max(waiting)):
        history.append(bar)
        if bar.day in waiting:
            if len(history) != CHART_BARS:
                raise ValueError('Insufficient lookback for blind chart')
            panels[waiting[bar.day]] = render_panel(list(history))
    if len(panels) != len(selected):
        raise ValueError('Blind cohort dates are absent from common projection')
    return panels


def blind_zip(path, panels):
    manifest = {'review_mode': 'D_ONLY', 'anonymous': True, 'x_axis_max': 'D',
                'lookback_trading_sessions_including_D': CHART_BARS, 'chart_count': len(panels), 'charts': []}
    with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
        for identifier, png in sorted(panels.items()):
            name = f'{identifier}.png'
            archive.writestr(ZipInfo(name), png, compress_type=ZIP_DEFLATED)
            manifest['charts'].append({'chart_id': identifier, 'file': name, 'sha256': hashlib.sha256(png).hexdigest()})
        archive.writestr(ZipInfo('manifest.json'), json.dumps(manifest, indent=2) + '\n', compress_type=ZIP_DEFLATED)
    return manifest


def summarize(rows, path):
    paired = [r for r in rows if r['v40_frozen_date_present'] == 'TRUE']
    true = lambda cohort, key: sum(row[key] == 'TRUE' for row in cohort)
    distribution = lambda key: '/'.join(str(sum(row[key] == v for row in rows)) for v in ('TRUE', 'FALSE', UNKNOWN))
    body = ['# ACT-067B｜钧达股份 002865.SZ · V4.1 语义影子', '',
            f'三层历史表覆盖 {rows[0]["date"]} 至 {rows[-1]["date"]}，共 {len(rows)} 个原始信号日。'
            f'原 ACT-065A V4.0 快照与本批同日 {len(paired)} 个，另 {len(rows)-len(paired)} 个原榜日期缺原快照。'
            '同源回放与影子共用 2316 个交易日的 Reader 价格及成交量、同一套冻结回放指标。'
            '原快照使用不同代次和预处理，保留用于观测历史漂移。历史 PIT 为 CANNOT_CONFIRM。', '',
            '| 规则 | 原 V4.0 命中/合格（同日） | 同源 V4.0 命中/合格 | V4.1 TRUE/FALSE/UNKNOWN |',
            '|---|---:|---:|---:|']
    for label, method, v41 in (('#19 RAW', 'b1', 'b1_raw'), ('#19 Formal', 'b1', 'b1_formal'),
                               ('#20 传统 RAW / V4.1 F03', 'b2', 'USER_FORMULA_B2_F03'), ('#25 独立重建', 'm25', 'm25')):
        historic = f'{true(paired, f"v40_frozen_{method}_raw")}/{true(paired, f"v40_frozen_{method}_qualified")}'
        replay = f'{true(rows, f"v40_replay_{method}_raw")}/{true(rows, f"v40_replay_{method}_qualified")}'
        body.append(f'| {label} | {historic} | {replay} | {distribution(f"v41_{v41}")} |')
    body += ['', f'V4.1 #20 分轨（TRUE/FALSE/UNKNOWN） 口述核心 {distribution("v41_B2_ORAL_CORE")}，'
                  f'1006 {distribution("v41_B2_1006_SCREEN")}，151 昨量 {distribution("v41_B2_151_PREV_VOL_X1_20")}，'
                  f'趋势确认 {distribution("v41_B2_TREND_CONFIRMATION")}。V4.0 合格与 V4.1 正式事件的口径各自保留。', '']
    for predicate, label in (
        (lambda r: r['v40_replay_b2_raw'] == 'TRUE' and r['v41_USER_FORMULA_B2_F03'] == 'FALSE', '同源 V4.0 #20 RAW 为 TRUE，V4.1 F03 为 FALSE'),
        (lambda r: r['v40_replay_b2_raw'] == 'FALSE' and r['v41_USER_FORMULA_B2_F03'] == 'TRUE', '同源 V4.0 #20 RAW 为 FALSE，V4.1 F03 为 TRUE'),
        (lambda r: r['v40_replay_b1_qualified'] == 'TRUE' and r['v41_b1_formal'] == UNKNOWN, '同源 V4.0 #19 合格，V4.1 Formal 缺锚定回踩、缩量或风控证据'),
        (lambda r: r['v40_replay_m25_chain_complete'] == 'TRUE', '同源 V4.0 #25 代理链完成，V4.1 缺原始破坏、黄线测试、重建、历史保留及风控证据'),
    ):
        examples = [row['date'] for row in rows if predicate(row)]
        if examples:
            body.append(f'- {examples[len(examples)//2]}（共 {len(examples)} 日）{label}。')
    removed = Counter(row['v41_b2_f03_failed_clauses'] for row in rows
                      if row['v40_replay_b2_raw'] == 'TRUE' and row['v41_USER_FORMULA_B2_F03'] == 'FALSE')
    clause_labels = {'J_LT_13_WITHIN_D_MINUS_2_TO_D': '3 根 J 窗口', 'W_GT_Y': 'W > Y'}
    failure_summary = '，'.join(f'{"和".join(clause_labels.get(clause, clause) for clause in group.split("|"))} {count} 日'
                               for group, count in removed.most_common())
    body += ['', f'同源 #20 RAW 中 F03 移出的日期按未满足条件计数：{failure_summary}。', '', 'V4.1 F03 取截至 D 的 3 根 J 值，要求 W > Y，量均值取 D 前 4 根。口述核心、趋势确认、正式回踩和针形替代路径缺原规则。#25 的 15%–20% 为描述。盲审为 12 张匿名 D 截止 K 线，用户 PDF 另附逐例后 15 个交易日。仅供研究，S_FIT=0，B_FIT=0。', '']
    path.write_text('\n'.join(body), encoding='utf-8')


def shadow(args):
    inputs, output, evidence = args.inputs, args.output, args.evidence
    pages = sorted(inputs.glob('sheet_*.json'))
    cohort = read_cohort(pages)
    contract_path = inputs/'contract.json'
    contract = validate_contract(read_json(contract_path))
    provenance = read_json(inputs/'timeline_provenance.json')
    receipt = read_json(evidence/'v40_replay_receipt.json')
    baseline = inputs/'v40.csv'
    common = evidence/'common_indicators_d_only.csv'
    replay_path = evidence/'v40_same_input_replay.csv'
    if (sha256(baseline) != BASELINE_SHA or receipt['source_generation'] != provenance['generation']
        or receipt['source_timeline_sha256'] != provenance['projection_sha256']
        or sha256(common) != receipt['common_indicators_sha256'] or sha256(replay_path) != receipt['v40_replay_sha256']):
        raise ValueError('Baseline, common indicator or replay input identity mismatch')
    history = read_baseline(baseline, cohort)
    with replay_path.open(encoding='utf-8', newline='') as handle:
        replay = {as_date(row['date']): row for row in csv.DictReader(handle)}
    rows = collect_rows(cohort, history, replay, common, contract, provenance)
    selected = select_cases(rows)
    output.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True)
    date_to_id = {case['date']: case['chart_id'] for case in selected}
    fields = [key for key in rows[0] if key != 'blind_possible'] + ['blind_chart_id']
    csv_path = output/CSV_NAME
    with csv_path.open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows({**row, 'blind_chart_id': date_to_id.get(row['date'], '')} for row in rows)
    archive_path = output/ZIP_NAME
    zip_manifest = blind_zip(archive_path, render_left_panels(common, selected))
    summary_path = output/SUMMARY_NAME
    summarize(rows, summary_path)
    lock = {'selection_mode': 'D_ONLY', 'source_generation': provenance['generation'], 'cases': selected,
            'csv_sha256': sha256(csv_path), 'blind_zip_sha256': sha256(archive_path), 'charts': zip_manifest['charts']}
    write_json(evidence/'blind_case_lock.json', lock)
    write_json(evidence/'shadow_receipt.json', {
        'RESEARCH_ONLY': True, 'S_FIT': 0, 'B_FIT': 0, 'production_allowed': False, 'orders_sent': False,
        'source_generation': provenance['generation'], 'contract_sha256': sha256(contract_path),
        'sheet_page_sha256': {file.name: sha256(file) for file in pages}, 'baseline_sha256': BASELINE_SHA,
        'engine_ceiling': str(max(cohort)), 'cohort_rows': len(rows), 'frozen_v40_shared_rows': len(history),
        'first_date': rows[0]['date'], 'last_date': rows[-1]['date'], 'v40_v41_b1_raw_immutable_matches': len(rows),
        'counts': {field: dict(Counter(row[field] for row in rows)) for field in fields
                   if field.startswith(('v41_', 'v40_replay_', 'v40_frozen_'))
                   and all(row.get(field) in ('TRUE', 'FALSE', UNKNOWN) for row in rows)},
        'unknowns': ['historical_PIT', 'B1_anchored_pullback_volume_and_risk', 'B1_needle_alternative',
                     'B2_oral_and_trend', 'B2_formal_retest_thresholds', 'M25_original_chain_and_independent_risk'],
        'same_basis_attribution_scope': 'frozen replay versus V4.1 common inputs, archived production tags excluded',
        'files': {file.name: sha256(file) for file in (csv_path, archive_path, summary_path)},
    })
    print(json.dumps({'rows': len(rows), 'shared': len(history), 'blind': selected}, ensure_ascii=False))


def read_forward_cases(path, selected):
    """Read only the pre-projected, exact offsets for locked pages."""
    by_day = {case['date']: case for case in selected}
    forward = {day: [] for day in by_day}
    with path.open(encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            day = row['anchor_D']
            if day not in by_day:
                raise ValueError('Forward-only input contains an unlocked anchor')
            segment = forward[day]
            offset = int(row['offset'])
            if offset != len(segment) + 1 or offset > 15:
                raise ValueError(f'Forward offsets outside consecutive D+1..D+15 at {day}')
            if 'td_idx' in row and int(row['td_idx']) != by_day[day]['td_idx'] + offset:
                raise ValueError(f'Forward stock-session index mismatch at {day} offset {offset}')
            session = Session.from_row(row)
            if session.day <= (segment[-1].day if segment else as_date(day)):
                raise ValueError(f'Forward date crosses page cutoff or is unordered at {day} offset {offset}')
            segment.append(session)
    if any(len(segment) != 15 for segment in forward.values()):
        raise ValueError('Future data required for each locked D+15')
    return forward


def atlas(args):
    """The user atlas reads the locked artifacts and a separate forward-only projection."""
    from reportlab.lib.colors import HexColor
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.pdfgen.canvas import Canvas

    lock_path = args.evidence/'blind_case_lock.json'
    lock = read_json(lock_path)
    selected = lock['cases']
    future_provenance = read_json(args.forward_provenance)
    timeline_provenance = read_json(args.inputs/'timeline_provenance.json')
    if (lock['source_generation'] != future_provenance['generation']
        or future_provenance['blind_case_lock_sha256'] != sha256(lock_path)
        or future_provenance['rows'] != len(selected)*15
        or future_provenance['complete_Dplus15_pages'] != len(selected)
        or future_provenance['allowed_in_engine'] is not False
        or future_provenance['allowed_in_redteam'] is not False
        or future_provenance['market_basis'] != timeline_provenance['market_basis']
        or sha256(args.forward) != future_provenance['projection_sha256']):
        raise ValueError('Review-only data differs from locked generation, basis or projection hash')
    csv_path = args.output/CSV_NAME
    archive_path = args.output/ZIP_NAME
    if sha256(csv_path) != lock['csv_sha256'] or sha256(archive_path) != lock['blind_zip_sha256']:
        raise ValueError('D-only deliverables changed after blind locking')
    with csv_path.open(encoding='utf-8-sig', newline='') as handle:
        rows = {r['date']: r for r in csv.DictReader(handle) if r['blind_chart_id']}
    future = read_forward_cases(args.forward, selected)
    geometry = {day: [str(segment[0].day), str(segment[-1].day)] for day, segment in future.items()}
    if geometry != future_provenance['window_start_end']:
        raise ValueError('Forward-only data dates disagree with the reviewed window geometry')
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    page_width, page_height = 1136, 568
    pdf_path = args.output/PDF_NAME
    canvas = Canvas(str(pdf_path), pagesize=(page_width, page_height), invariant=True, pageCompression=1)
    canvas.setTitle('ACT-067B 钧达股份 002865.SZ 用户复核图册')
    canvas.setSubject('D-only locked blind chart and independent 15-session user-only review')
    canvas.setAuthor('ACT-067B')

    def line(x, y, text, *, size=14, color='#14263d'):
        canvas.setFont('STSong-Light', size)
        canvas.setFillColor(HexColor(color))
        canvas.drawString(x, y, text)

    def rule_at(label, row, field):
        return f'{label} {row[field]}'

    page_records = []
    with ZipFile(archive_path) as archive:
        for case in selected:
            day, identifier = case['date'], case['chart_id']
            row = rows[day]
            if row['blind_chart_id'] != identifier:
                raise ValueError(f'Case ID disagrees with CSV at {day}')
            left_png = archive.read(f'{identifier}.png')
            left_hash = hashlib.sha256(left_png).hexdigest()
            if left_hash != next(item['sha256'] for item in lock['charts'] if item['chart_id'] == identifier):
                raise ValueError(f'Left panel changed after lock at {day}')
            anchor = Session.from_row({'date': day, **{key: row[f'{key}_D'] for key in ('open', 'high', 'low', 'close', 'volume')},
                                       **{key: row[f'{key}_D'] for key in ('W', 'Y', 'BBI', 'J')}, 'pct_change': row['pct_D']})
            forward_bars = future[day]
            right_png = render_panel(forward_bars, forward_reference_close=anchor.close)
            last_day = str(forward_bars[-1].day)
            move = 100 * (forward_bars[-1].close / anchor.close - 1)
            canvas.setFillColor(HexColor('#f5f8fc'))
            canvas.rect(0, 0, page_width, page_height, stroke=0, fill=1)
            line(29, 531, f'{identifier}  钧达股份（002865.SZ）', size=24)
            line(31, 504, f'信号日 {day}    |    三层历史表 {row["v31_3_structure_status"]} / {row["v31_3_formula_tags"]}', color='#405572')
            line(31, 467, '左图 / D-only 盲审原图', size=16)
            line(580, 467, '右图 / 用户复核 D+1 至 D+15', size=16)
            canvas.drawImage(ImageReader(BytesIO(left_png)), 25, 145, width=531, height=314)
            canvas.drawImage(ImageReader(BytesIO(right_png)), 574, 145, width=531, height=314)
            line(31, 121, f'V4.0 同源 RAW {row["v40_replay_formula_hit_tags"] or "NONE"}    合格 {row["v40_replay_new_entry_qualified_tags"] or "NONE"}', size=13)
            line(31, 97, '    |    '.join(rule_at(label, row, key) for label, key in (
                ('V4.1 #19 RAW', 'v41_b1_raw'), ('Formal', 'v41_b1_formal'), ('#25', 'v41_m25'))), size=13)
            line(31, 73, '    |    '.join(rule_at(label, row, key) for label, key in (
                ('#20 1006', 'v41_B2_1006_SCREEN'), ('151', 'v41_B2_151_PREV_VOL_X1_20'), ('F03', 'v41_USER_FORMULA_B2_F03'))), size=13)
            line(580, 121, f'D+15 {last_day}    |    15 个交易日    |    收盘较 D {move:+.2f}%', size=13)
            line(580, 97, '两图各自定纵轴，D 日收盘统一为 100。', size=13)
            line(580, 73, '右图仅供用户复核，历史 PIT 为 CANNOT_CONFIRM。', size=13)
            line(31, 34, 'ACT-067B    |    RESEARCH_ONLY    |    S_FIT=0    B_FIT=0', size=12, color='#405572')
            canvas.showPage()
            page_records.append({'chart_id': identifier, 'D': day, 'D_plus_15': last_day, 'future_sessions': 15,
                                 'left_png_sha256': left_hash, 'right_png_sha256': hashlib.sha256(right_png).hexdigest()})
    canvas.save()
    write_json(args.evidence/'atlas_receipt.json', {
        'atlas_sha256': sha256(pdf_path), 'forward_projection_sha256': future_provenance['projection_sha256'],
        'source_generation': lock['source_generation'], 'locked_zip_sha256': lock['blind_zip_sha256'],
        'page_count': len(page_records), 'pages': page_records,
    })
    print(json.dumps({'pdf': pdf_path.name, 'sha256': sha256(pdf_path), 'pages': len(page_records)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for action in ('shadow', 'atlas'):
        command = commands.add_parser(action)
        for name in ('inputs', 'output', 'evidence'):
            command.add_argument(f'--{name}', type=Path, required=True)
        if action == 'atlas':
            command.add_argument('--forward', type=Path, required=True)
            command.add_argument('--forward-provenance', type=Path, required=True)
    args = parser.parse_args()
    (shadow if args.command == 'shadow' else atlas)(args)


if __name__ == '__main__':
    main()
