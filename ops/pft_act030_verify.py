"""Bounded ACT030 public-only Reader/parity/repair audit; no saved 140 scores.

Reads exactly the ZIP's manifest/cases_blind/bars public members. Emits aggregate
metrics and three canaries, never a whole raw panel or protected per-ID scores.
"""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import sys
from zipfile import ZipFile

import numpy as np
import pandas as pd

from ops import pft_act030_features as f
from ops import pft_act030_eval as evaluation
from ops import research_panel_logical as reader
from ops import research_panel_qfq as qfq

ZIP_NAME = 'PFT_V4_ACT022_BLIND_BATCH1_240EP_20261123.zip'
ZIP_SHA = '1b8baf28dfe666d9cdeb60e77e903fa26cd540750bf4d60dd3c6b520b9146f85'
CANARIES = (('601666.SH', '20200720'), ('002432.SZ', '20211216'), ('600221.SH', '20210624'))
RAW_COLUMNS = ('open', 'high', 'low', 'close', 'volume', 'amount_cny', 'white', 'yellow', 'bbi')



def need(ok, message):
    if not ok:
        raise ValueError(message)


def metadata(path):
    path = Path(path)
    return dict(path=str(path), bytes=path.stat().st_size, sha256=evaluation.sha(path))


def read_public(archive):
    need(evaluation.sha(archive) == ZIP_SHA, 'ACT022_ARCHIVE_SOURCE_TAMPER')
    with ZipFile(archive) as z:
        m = json.loads(z.read('manifest.json'))
        members = {}
        for name in ('cases_blind.csv', 'bars.csv'):
            payload = z.read(name)
            need(len(payload) == m['members'][name]['bytes'] and
                 hashlib.sha256(payload).hexdigest() == m['members'][name]['sha256'], 'PUBLIC_MEMBER_SOURCE_TAMPER:'+name)
            members[name] = list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'), newline='')))
    cases = evaluation.indexed(members['cases_blind.csv'])
    need(len(cases) == 240, 'EXACT_PUBLIC240_REQUIRED')
    bars = pd.DataFrame(members['bars.csv'])
    need(set(bars.episode_id) == set(cases), 'PUBLIC_BARS_IDS_DRIFT')
    bars['trade_date'] = bars.trade_date.map(f.day)
    bars['date_offset'] = pd.to_numeric(bars.date_offset)
    for name in RAW_COLUMNS:
        bars[name] = bars[name].map(float)
    need(not bars.duplicated(['episode_id', 'trade_date']).any() and bars.date_offset.le(0).all(), 'PUBLIC_BARS_FUTURE_OR_DUPLICATE')
    return cases, bars, m


def source_identity(census_path, archive_manifest):
    census = json.loads(census_path.read_text())
    need(evaluation.sha(census_path) == archive_manifest['source']['census_receipt_sha256'], 'FROZEN_CENSUS_SOURCE_TAMPER')
    source = census['source']
    b = source['backtest']
    panel = Path(b['path'])
    need(evaluation.sha(panel) == b['panel_sha256'] == archive_manifest['source']['backtest_sha256'], 'BACKTEST_SOURCE_TAMPER')
    need(evaluation.sha(b['generation_manifest_path']) == b['generation_manifest_sha256'] ==
         archive_manifest['source']['generation_manifest_sha256'], 'GENERATION_MANIFEST_SOURCE_TAMPER')
    # panel_contract is the owner API and resolves the logical anchor, not a copy.
    contract = qfq.panel_contract(panel)
    for key in ('generation_id', 'input_sha256', 'snapshot_file_sha256'):
        need(contract[key] == source['identity'][key], 'SOURCE_IDENTITY_DRIFT:'+key)
    need(contract['market_basis']['A']['amount_basis'] == 'RAW_TURNOVER' if 'A' in contract['market_basis'] else
         contract['amount_basis'] in ('RAW_TURNOVER', 'MIXED_BY_MARKET'), 'AMOUNT_BASIS_DRIFT')
    snap_ref = contract['adjustment_snapshot']
    need(evaluation.sha(snap_ref['path']) == snap_ref['sha256'] == contract['snapshot_file_sha256'], 'FACTOR_SNAPSHOT_SOURCE_TAMPER')
    snapshot = json.loads(Path(snap_ref['path']).read_text())
    need(snapshot['asof_date'] == contract['asof_date'] and snapshot['price_basis'] == 'QFQ_ASOF' and
         snapshot['volume_basis'] == 'QFQ_EVENT_VOLUME' and snapshot['amount_basis'] == 'RAW_TURNOVER', 'FACTOR_BASIS_DRIFT')
    return panel, contract, snapshot, dict(panel=metadata(panel), generation_manifest=metadata(b['generation_manifest_path']),
        adjustment_snapshot=metadata(snap_ref['path']), generation=contract['generation_id'],
        input_sha256=contract['input_sha256'], asof=contract['asof_date'], role='ACT022_FROZEN_BACKTEST',
        current_pointer_modified=False, historical_PIT='CANNOT_CONFIRM', factor_snapshot_historical_PIT=snapshot.get('historical_PIT'))


def reader_parity(panel, cases, bars, frozen_root):
    from ops import pft_s_full_ashare as existing
    frozen = existing._validate_inputs(frozen_root)
    observed, _ = existing._key_rows_universe(panel, reader, set(frozen['raw_to_canonical']))
    groups = {}
    for raw in observed:
        groups.setdefault(frozen['raw_to_canonical'][raw], []).append(raw)
    aliases = dict(volume='vol', amount_cny='amount', white='zge_white_line', yellow='zge_yellow_line')
    filters = []
    for eid, case in cases.items():
        h = bars.loc[bars.episode_id.eq(eid)]
        lo, hi = int(h.trade_date.min()), int(f.day(case['D']))
        filters.append([('ts_code', 'in', groups[case['security_id']]), ('trade_date', '>=', lo), ('trade_date', '<=', hi)])
    columns = ['ts_code', 'trade_date', 'exchange', 'market_type', *[aliases.get(c, c) for c in RAW_COLUMNS]]
    projected = reader.parquet.read_table(panel, columns=columns, filters=filters).to_pandas()
    projected = projected.rename(columns={v: k for k, v in aliases.items()})
    projected['trade_date'] = projected.trade_date.map(f.day)
    need(not projected.duplicated(['ts_code', 'trade_date']).any(), 'READER_DUPLICATE_KEY')
    venue = projected.exchange.fillna('').astype(str).str.upper().str.strip()
    market = projected.market_type.fillna('').astype(str).str.upper().str.strip()
    venue_ok = venue.eq('')
    for suffix, names in {'SH':('SH','SSE','XSHG','SHANGHAI'), 'SZ':('SZ','SZSE','XSHE','SHENZHEN'), 'BJ':('BJ','BSE','XBEI','BEIJING')}.items():
        venue_ok |= projected.ts_code.str.endswith('.'+suffix) & venue.isin(names)
    projected = projected.loc[venue_ok & market.isin(('', 'A_SHARE', 'BJ'))].copy()
    projected['canonical'] = projected.ts_code.map(frozen['raw_to_canonical'])
    need(projected.canonical.notna().all(), 'READER_OUTSIDE_FROZEN_UNIVERSE')
    by_code = {}
    for code, group in projected.groupby('canonical'):
        by_raw = {raw: h.to_dict('records') for raw, h in group.groupby('ts_code')}
        selected = existing._deduplicate_alias_history(by_raw, frozen['crosswalk_aliases'])
        by_code[code] = pd.DataFrame(selected).set_index('trade_date')
    errors = {c: [] for c in RAW_COLUMNS}
    serialized_errors = {c: [] for c in RAW_COLUMNS}
    mismatch_canaries = {}
    selected_aliases = {}
    for eid, case in cases.items():
        h = bars.loc[bars.episode_id.eq(eid)].sort_values('trade_date')
        f.checked_history(h, case['D'])
        source = by_code[case['security_id']].reindex(h.trade_date)
        need(not source[list(RAW_COLUMNS)].isna().any().any(), 'READER_PUBLIC_KEY_MISSING')
        selected_aliases[eid] = sorted(set(source.ts_code))
        for name in RAW_COLUMNS:
            raw_values = source[name].to_numpy(float)
            actual = np.array([float(format(x, '.16g')) for x in raw_values])
            err = np.abs(raw_values-h[name].to_numpy(float))
            errors[name].extend(err.tolist())
            serialized = actual
            serial_error = np.abs(serialized-h[name].to_numpy(float))
            serialized_errors[name].extend(serial_error.tolist())
            if np.any(serial_error > 0) and name not in mismatch_canaries:
                j = int(np.argmax(serial_error))
                mismatch_canaries[name] = dict(episode_id=eid, security_id=case['security_id'],
                    trade_date=h.trade_date.iloc[j], reader=float(raw_values[j]), serialized=float(serialized[j]), archive=float(h[name].iloc[j]))
    summary = {c: dict(n=len(v), exact=int(np.count_nonzero(np.array(v) == 0)), max_abs=float(max(v)),
                       serialized_exact=int(np.count_nonzero(np.array(serialized_errors[c]) == 0)),
                       serialized_max_abs=float(max(serialized_errors[c]))) for c, v in errors.items()}
    need(all(v['serialized_max_abs'] == 0 for v in summary.values()), 'READER_PUBLIC_VALUES_NOT_EXACT:'+
         json.dumps(dict(columns=summary, mismatch_canaries=mismatch_canaries)))
    result = dict(status='PASS_EXACT', episodes=len(cases), bars=len(bars), columns=summary,
                frozen_universe_input_sha256=frozen['input_sha256'], alias_resolution='ACT022 frozen universe, existing effective-date whole-row precedence',
                serialization_comparison='ACT022 .16g numeric canonicalization', projected_union_rows=len(projected), persisted_raw_rows=0, post_d_rows_used=0)
    return result, selected_aliases


def d_basis_eligibility(canonical_code, selected_aliases, snapshot):
    """Never cross-normalize old-code rows using a divergent canonical ledger."""
    canonical = snapshot['symbols'].get(canonical_code)
    if canonical is None or canonical.get('event_coverage_complete') is not True:
        return False, 'CANONICAL_FACTOR_COVERAGE_UNKNOWN'
    def timeline(item):
        return [(int(e['ex_date']), float(e['a']), float(e['b']), float(e['volume_a'])) for e in item['events']]
    expected = timeline(canonical)
    for alias in selected_aliases:
        item = snapshot['symbols'].get(alias)
        if item is None or item.get('event_coverage_complete') is not True:
            return False, 'RAW_ALIAS_FACTOR_COVERAGE_UNKNOWN'
        if timeline(item) != expected:
            return False, 'RAW_ALIAS_CANONICAL_EVENT_TIMELINE_DIVERGENCE'
    return True, 'MATCHED_ALL_CHOSEN_ALIAS_EVENT_TIMELINES'


def ref_value(row, name):
    return f.number(row.get(name))

def parity(actual, reference):
    result = {}
    for name in f.FEATURES:
        pairs = [(a[name], ref_value(reference[eid], name)) for eid, a in actual.items()]
        usable = [(a, b) for a, b in pairs if a is not None and b is not None]
        a, b = np.array(usable, float).T if usable else (np.array([]), np.array([]))
        delta = np.abs(a-b)
        correlation = float(np.corrcoef(a, b)[0, 1]) if len(a) > 1 and np.std(a) > 0 and np.std(b) > 0 else None
        result[name] = dict(n_total=len(pairs), n_finite=len(a), n_local_missing=sum(a is None for a, _ in pairs),
            n_reference_missing=sum(b is None for _, b in pairs), tolerance=f.TOLERANCE[name],
            within_rounding=int(np.count_nonzero(delta <= f.TOLERANCE[name]+1e-12)),
            mean_abs=float(delta.mean()) if len(a) else None, max_abs=float(delta.max()) if len(a) else None,
            pearson=correlation, direction_agreement=float(np.mean(np.sign(a) == np.sign(b))) if len(a) else None)
    return result


def raw_canary(case, archive_history, d_history, snapshot, driver, formula):
    code, endpoint = case['security_id'], f.day(case['D'])
    item = snapshot['symbols'][code]
    # Existing owner resolution performs source SHA checks and archive/native whole-row precedence.
    raw = qfq.resolved_raw_history(code, item, int(endpoint), driver)
    raw = raw.loc[raw.trade_date.le(int(endpoint)) & raw.trade_date.ge(item.get('compute_start_date', 0))].copy()
    adjusted = qfq.apply_adjustments(raw, [e for e in item['events'] if int(e['ex_date']) <= int(endpoint)], int(endpoint))
    calculated = driver.compute_formula_features(adjusted, 0, {}, driver._NoopLogger(), emit_all_rows=True, xdxr_events=None)
    canonical = driver._compute_canonical_v192_formula(adjusted)
    for name in canonical:
        calculated[name] = canonical[name].to_numpy()
    calculated['trade_date'] = calculated.trade_date.map(f.day)
    calculated = calculated.rename(columns=dict(vol='volume', amount='amount_cny', zge_white_line='white', zge_yellow_line='yellow', BBI='bbi'))
    calculated = calculated.loc[:, ~calculated.columns.duplicated()]
    selected = calculated.set_index('trade_date').reindex(d_history.trade_date)
    errors = {name: float(np.max(np.abs(selected[name].to_numpy(float)-d_history[name].to_numpy(float)))) for name in RAW_COLUMNS}
    need(all(np.isfinite(list(errors.values()))) and max(errors.values()) < 1e-5, 'RAW_REPLAY_CANARY_DRIFT:'+code)
    idx = int(np.argmin(archive_history.close.to_numpy()))
    return dict(security_id=code, D=endpoint, bars=len(d_history), raw_history_rows=len(raw),
        max_raw_date=str(raw.trade_date.max()), post_d_price_bars_used=0, raw_replay_max_abs=errors,
        source_refs=[dict(path=r['path'], sha256=r['sha256'], role=r.get('source_role')) for r in item['raw_files']],
        min_archive_close=float(archive_history.close.min()), min_d_basis_close=float(d_history.close.min()),
        min_archive_low=float(archive_history.low.min()), min_d_basis_low=float(d_history.low.min()),
        small_price_canary=dict(date=archive_history.trade_date.iloc[idx], archive_close=float(archive_history.close.iloc[idx]),
                               d_basis_close=float(d_history.close.iloc[idx])), status='PASS_RAW_REPLAY')


def run(artifact_root, output, driver_path=None, formula_path=None):
    started = datetime.now(timezone.utc).isoformat()
    target = artifact_root/'pft_act030_feature_parity_20261123'
    need(output.parent.resolve() == target.resolve(), 'OUTPUT_OUTSIDE_ACT030')
    source_dir = artifact_root/'pft_act022_blind_batch1_20261123'
    archive = source_dir/ZIP_NAME
    cases, bars, manifest = read_public(archive)
    panel, contract, snapshot, identity = source_identity(source_dir/'census_full.json', manifest)
    projection_path = target/'staging/gemini_numeric_projection.json'
    v0path = target/'staging/gemini_act023_numeric_controls.json'
    reference = evaluation.indexed(json.loads(projection_path.read_text()))
    v0 = evaluation.indexed(json.loads(v0path.read_text()))
    need(set(reference) == set(v0) == set(cases), 'NUMERIC_REFERENCE_IDS_DRIFT')
    need(all(reference[eid]['security_id'] == case['security_id'] and f.day(reference[eid]['D']) == f.day(case['D'])
             for eid, case in cases.items()), 'NUMERIC_REFERENCE_SECURITY_OR_D_DRIFT')
    source_seen = [metadata(p) for p in (archive, projection_path, v0path, source_dir/'census_full.json')]
    audit_reader, chosen_aliases = reader_parity(panel, cases, bars, artifact_root/'pft_s_full_ashare_scaleup_20261122')
    original, causal, diagnostic, v0diag, repairs, small = {}, {}, {}, {}, [], []
    canary_specs = set(CANARIES)
    # 601666 D is resolved from the actual public batch instead of invented.
    actual_601666 = [(c['security_id'], f.day(c['D'])) for c in cases.values() if c['security_id'] == '601666.SH']
    need(len(actual_601666) == 1, 'EXACT_601666_CASE_REQUIRED')
    canary_specs = {(c, d) for c, d in canary_specs if c != '601666.SH'} | set(actual_601666)
    driver = formula = None
    if driver_path is None and formula_path is None:
        producer_meta = Path(contract['generation_manifest_path']).with_name('meta.json')
        bound = json.loads(producer_meta.read_text())['formula_processing']['worker_context']
        driver_path, formula_path = Path(bound['driver_path']), Path(bound['canonical_formula_path'])
    if driver_path and formula_path:
        driver, formula = qfq.authorities(driver_path, formula_path)
    undo_counts, negative_before, negative_after = [], 0, 0
    near_low = []
    withheld, withheld_low_candidates = [], []
    for eid, case in sorted(cases.items()):
        h = bars.loc[bars.episode_id.eq(eid)].sort_values('trade_date').reset_index(drop=True)
        endpoint = f.day(case['D'])
        item = snapshot['symbols'].get(case['security_id'])
        need(item is not None and item['event_coverage_complete'] is True, 'SYMBOL_FACTOR_COVERAGE_UNKNOWN')
        events = item['events']
        eligible, basis_reason = d_basis_eligibility(case['security_id'], chosen_aliases[eid], snapshot)
        if eligible:
            dh, audit = f.to_d_basis(h, events, endpoint, snapshot['asof_date'])
            anchors = f.public_anchors(case, events, endpoint, snapshot['asof_date'])
            causal[eid] = f.features(dh, endpoint, anchors)
        else:
            dh = None
            audit = dict(status='WITHHELD', reason=basis_reason, events_undone=0)
            causal[eid] = dict.fromkeys(f.FEATURES)
            withheld.append(dict(market=case['board'], reason=basis_reason))
            if float(h.low.min()) < 1:
                withheld_low_candidates.append(dict(security_id=case['security_id'], D=endpoint, archive_min_low=float(h.low.min()),
                                                    d_basis_min_low=None, status='CANNOT_CONFIRM_ALIAS_BASIS'))
        # Diagnostic archive-basis series explain existing published calculations.
        raw_anchors = f.public_anchors(case, [], endpoint, snapshot['asof_date'])
        original[eid] = f.features(h, endpoint, raw_anchors)
        diagnostic[eid] = f.diagnostic_reference_features(h, endpoint, reference[eid])
        old_ref = {**reference[eid], **v0[eid]}
        # V0 does not publish active_anchor_low; its dated bar is the V0 control.
        old_ref.pop('active_anchor_low', None)
        v0diag[eid] = f.diagnostic_reference_features(h, endpoint, old_ref)
        archive_low = float(h.low.min())
        local_low = float(dh.low.min()) if dh is not None else None
        if archive_low <= .01 or (archive_low < 1 and local_low is not None and local_low > 0 and archive_low/local_low < .20):
            near_low.append(dict(security_id=case['security_id'], D=endpoint, archive_low=archive_low, d_basis_low=local_low))
        undo_counts.append(audit['events_undone'])
        negative_before += int(h[list(f.PRICE_COLUMNS)].le(0).any(axis=1).sum())
        if dh is not None:
            negative_after += int(dh[list(f.PRICE_COLUMNS)].le(0).any(axis=1).sum())
        if (case['security_id'], endpoint) in canary_specs:
            need(eligible, 'RAW_CANARY_BASIS_NOT_PROVED')
            info = dict(episode_id=eid, security_id=case['security_id'], D=endpoint, repair=audit,
                        archive_features=original[eid], d_basis_features=causal[eid],
                        close_slope15_archive=f._slope(h.close.iloc[-15:])/h.close.iloc[-15:].mean(),
                        close_slope15_d_basis=f._slope(dh.close.iloc[-15:])/dh.close.iloc[-15:].mean())
            small.append(info)
            if driver is not None:
                repairs.append(raw_canary(case, h, dh, snapshot, driver, formula))
    need(len(small) == 3, 'THREE_CANARIES_NOT_FOUND')
    calib_dir = artifact_root/'pft_act026_sfrozenv1_calib100_20261123'
    calib_path = calib_dir/'PFT_V4_ACT026_CODEX_CALIB100_ALIGNED_20261123.csv'
    assessment_path = calib_dir/'assessment_metrics.json'
    need(evaluation.sha(calib_path) == evaluation.CALIB100_SHA and evaluation.sha(assessment_path) == evaluation.ASSESSMENT_SHA,
         'APPROVED_ACT026_SOURCE_TAMPER')
    calibration = evaluation.read_csv(calib_path)
    ids = {eid for eid, c in cases.items() if c['calib_100'] == 'true'}
    scored = evaluation.same_exam(calibration, calibration, ids, (('raw_S_lr', 'gated_S_lr'), ('raw_S_rf', 'gated_S_rf')))
    regression = evaluation.compare_act026(scored, json.loads(assessment_path.read_text()))
    lineage_names = ('active_intact_margin_atr', 'active_close_vs_low_pct', 'active_close_vs_mid_pct', 'invalidation_dist_atr')
    lineage = dict(active_date_changed=sum(f.day(v0[eid].get('active_key_k_date')) != f.day(reference[eid].get('active_key_k_date')) for eid in cases),
                   unchanged_numeric={n: sum(v0[eid].get(n) == reference[eid].get(n) for eid in cases) for n in lineage_names})
    output_value = dict(schema='PFT_ACT030_LOCAL_VERIFICATION_V1', status='PASS_BOUNDED_AUDIT_WITH_PARITY_GAPS',
        started_utc=started, completed_utc=datetime.now(timezone.utc).isoformat(), source_identity=identity,
        sources=source_seen, numeric_identity_check=dict(episodes=240, fields=['episode_id','security_id','D'], status='PASS_EXACT'),
        code_sha256={name: evaluation.sha(Path(__file__).with_name(name)) for name in
                     ('pft_act030_features.py','pft_act030_eval.py','pft_act030_verify.py')}, executable=sys.executable, source_root=str(Path(__file__).resolve().parents[1]),
        resources=dict(cpu_count=os.cpu_count(), workers=1, projected_rows=len(bars)),
        flags=f.FLAGS, fit=0, model_load=0, predict=0, protected_data_reads=0,
        public_reader_parity=audit_reader, feature_schema=f.SCHEMA, feature_groups=f.GROUPS,
        parity_archive_basis=parity(original, reference), parity_public_D_basis=parity(causal, reference),
        parity_reference_diagnostic_archive_basis=parity(diagnostic, reference),
        parity_act023_reference_diagnostic_archive_basis=parity(v0diag, reference), publication_lineage=lineage,
        qfq_repair=dict(episodes=240, d_basis_eligible=240-len(withheld), d_basis_withheld=len(withheld),
                        withheld_by_reason={r: sum(x['reason']==r for x in withheld) for r in sorted({x['reason'] for x in withheld})},
                        withheld_by_board={b: sum(x['market']==b for x in withheld) for b in sorted({x['market'] for x in withheld})},
                        episodes_with_suffix=sum(n > 0 for n in undo_counts),
                        events_undone=sum(undo_counts), near_low_screen=dict(episodes=240,
                            rule='archive_min_low<=0.01 OR (archive_min_low<1 AND archive_min_low/d_basis_min_low<0.20)',
                            matched_n=len(near_low), matches=near_low, withheld_low_candidates=withheld_low_candidates), nonpositive_price_rows_before=negative_before,
                        nonpositive_price_rows_after=negative_after, clipping=False, amount_unchanged=True,
                        historical_PIT='CANNOT_CONFIRM', canaries=repairs, small_value_canaries=small),
        act026_saved_score_regression=regression,
        same_exam_baseline_only=dict(mode='BASELINE_ONLY_NO_CHALLENGER', primary=scored['consensus_primary'],
                                    secondary=scored['consensus_pos_neg_secondary'], hard_neg_adv_ge_3e8=scored['hard_neg_adv_ge_3e8']),
        CANNOT_CONFIRM=['ACT027 exact producer/anchor-version/volume conventions', 'Historical PIT from later factor snapshot',
                        *(['D-basis withheld for '+str(len(withheld))+' divergent/missing raw alias event ledgers'] if withheld else []),
                        'Challenger performance: no challenger predictions or training authorized',
                        *([] if driver else ['Original raw replay NOT_RUN: explicit owner driver/formula paths absent'])])
    # Abort rather than publish if any bound input changed while reading.
    for ref in source_seen + [identity['panel'], identity['generation_manifest'], identity['adjustment_snapshot']]:
        need(evaluation.sha(ref['path']) == ref['sha256'], 'SOURCE_CHANGED_DURING_AUDIT')
    with output.open('x', encoding='utf-8') as stream:
        json.dump(output_value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    return output_value


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifact-root', required=True, type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--driver', type=Path)
    p.add_argument('--formula', type=Path)
    args = p.parse_args(argv)
    output = args.output or args.artifact_root/'pft_act030_feature_parity_20261123/local_verification.json'
    result = run(args.artifact_root, output, args.driver, args.formula)
    print(json.dumps(dict(status=result['status'], output=str(output), raw_canaries=len(result['qfq_repair']['canaries']))))


if __name__ == '__main__':
    main()
