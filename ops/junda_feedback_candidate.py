"""Rebind one already accepted QFQ stock with the requested research fields.

This does not fetch data, select candidates, alter an authority pointer or
recompute old formula/KB labels. The score projection consumes its old QFQ
prefix and its output is bound to both role files and the displayed view.
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ops import research_panel_qfq as q
from ops import render_original_formula_projection as renderer
from ops.kb_hold_score import SUPPLEMENTAL_REASONS

REPO = Path(__file__).resolve().parents[1]
OLD_SHA = '9f328df9a6c2649036cc5ccbe0f7bda0a7e69b7ceb0416bc97059c1de73a66b8'
EXPECTED = '310e64e55bd17d85a3c4afc26d637788029a3af28e251f88afe48051e5602a66'
SYMBOL = '002865.SZ'


def immutable(path, data):
    path = Path(path)
    if path.exists():
        if path.read_bytes() != data:
            raise ValueError('IMMUTABLE_OUTPUT_CONFLICT:' + str(path))
    else:
        path.write_bytes(data)
    return dict(path=str(path), sha256=q.sha(path), bytes=len(data))


def write_json(path, value):
    return immutable(path, (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode())


def same(left, right):
    if left.type != right.type or len(left) != len(right):
        return False
    for a, b in zip(left.to_pylist(), right.to_pylist()):
        if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
            continue
        if a != b:
            return False
    return True


def build(previous, root, source_gate_path, feedback_reuse_path, feedback_reuse_sha256):
    root = Path(root).resolve(strict=True)
    previous = Path(previous).resolve(strict=True)
    if q.sha(previous) != OLD_SHA:
        raise ValueError('OLD_CANDIDATE_SHA_MISMATCH')
    old = json.loads(previous.read_text())
    if old['candidate_generation'] != EXPECTED:
        raise ValueError('OLD_CANDIDATE_IDENTITY_MISMATCH')
    for ref in [*old['outputs'].values(), *old['assets'].values(), old['binding'], old['source_gate'], old['admission']]:
        q._source(ref, owner='prior accepted single-stock candidate')
    old_binding = json.loads(Path(old['binding']['path']).read_text())
    if old_binding['symbol'] != SYMBOL or old_binding['candidate_generation'] != EXPECTED:
        raise ValueError('OLD_BINDING_IDENTITY_MISMATCH')
    gate_path = Path(source_gate_path).resolve(strict=True)
    gate_ref = {'path': str(gate_path), 'sha256': q.sha(gate_path)}
    gate = json.loads(gate_path.read_text())
    if (gate.get('status') != 'PASS_RELOCATED_SOURCE_GATE' or not gate.get('matches_frozen_input_sha256')
            or gate.get('canonical_input_sha256') != old['source_input_sha256']
            or gate.get('relocation_ref') != old_binding['source_relocation']):
        raise ValueError('SOURCE_GATE_NOT_PASSED')
    for ref in gate['source_code_refs'].values():
        q._source(ref, owner='accepted source gate code')
    # The full relocation gate must bind this exact QFQ/KB/score code set.
    for name in ('ops/research_panel_qfq.py', 'ops/research_panel_factor_cache.py', 'ops/kb_signal_authority.py',
                 'contracts/a_share_kb_fields_v1.json', 'ops/kb_hold_score.py', 'contracts/a_share_kb_hold_score_v1.json',
                 'contracts/a_share_kb_supplemental_signals_v1.json'):
        if gate['source_code_refs'].get(name, {}).get('sha256') != q.sha(REPO / name):
            raise ValueError('SOURCE_GATE_CODE_DRIFT:' + name)

    tables = {role: pq.read_table(item['path']) for role, item in old['outputs'].items()}
    if set(tables) != {'selector', 'backtest'} or any(len(t) != 2311 for t in tables.values()):
        raise ValueError('ROLE_SET_OR_LENGTH_MISMATCH')
    role_aliases = {'trade_date': 'trade_date', 'ts_code': 'ts_code', 'open': 'open', 'high': 'high',
                    'low': 'low', 'close': 'close', 'volume': 'vol', 'kb_b1_j': 'kb_b1_j'}
    for name, other in role_aliases.items():
        left, right = tables['selector'][name].to_pylist(), tables['backtest'][other].to_pylist()
        if name == 'trade_date':
            left, right = [int(v) for v in left], [int(v) for v in right]
        for a, b in zip(left, right):
            both_nan = isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b)
            if a != b and not both_nan:
                raise ValueError('ROLE_INPUT_MISMATCH:' + name + ':' + other)
    source = tables['selector'].select(['trade_date', 'ts_code', 'open', 'high', 'low', 'close', 'volume', 'kb_b1_j']).to_pylist()
    if any(r['ts_code'] != SYMBOL for r in source) or source[-1]['trade_date'] != '20261030':
        raise ValueError('SINGLE_PREFIX_IDENTITY_MISMATCH')
    supplement_names = list(SUPPLEMENTAL_REASONS)
    hold_names = sorted(q.SINGLE_FEEDBACK_FIELDS - set(supplement_names))
    if len(hold_names) != 17 or len(supplement_names) != 4:
        raise ValueError('NEW_FIELD_INVENTORY_MISMATCH')
    if any(name in t.column_names for t in tables.values() for name in hold_names + supplement_names):
        raise ValueError('NEW_FIELD_ALREADY_PRESENT')
    inventory = dict(base_kb_fields=old_binding['fields_count'],
                     hold_score_fields=hold_names, supplemental_fields=supplement_names,
                     total_new_fields=len(hold_names) + len(supplement_names),
                     total_derived_fields=old_binding['fields_count'] + len(hold_names) + len(supplement_names),
                     display_only_metadata=['volume_vs_previous', 'volume_vs_previous_5_mean'])
    score_ref = immutable(root / 'a_share_kb_hold_score_v1.json', (REPO / 'contracts/a_share_kb_hold_score_v1.json').read_bytes())
    supplemental_ref = immutable(root / 'a_share_kb_supplemental_signals_v1.json', (REPO / 'contracts/a_share_kb_supplemental_signals_v1.json').read_bytes())
    reuse_path = Path(feedback_reuse_path).resolve(strict=True)
    reuse_ref = {'path': str(reuse_path), 'sha256': feedback_reuse_sha256}
    reuse = json.loads(q._source(reuse_ref, owner='prior feedback candidate').read_text())
    reuse_identity = reuse['candidate_identity']
    if (reuse_identity.get('prior_single_candidate_sha256') != OLD_SHA
            or reuse_identity.get('score_engine_sha256') != q.sha(REPO / 'ops/kb_hold_score.py')
            or reuse_identity.get('score_contract_sha256') != score_ref['sha256']
            or reuse_identity.get('supplemental_contract_sha256') != supplemental_ref['sha256']
            or reuse.get('field_inventory') != inventory):
        raise ValueError('FEEDBACK_REUSE_IDENTITY_CONFLICT')
    cached = {role: pq.read_table(q._source(ref, owner='prior feedback role ' + role))
              for role, ref in reuse['outputs'].items()}
    if set(cached) != {'selector', 'backtest'}:
        raise ValueError('FEEDBACK_REUSE_ROLE_SET_CONFLICT')
    for role, table in tables.items():
        if not all(name in cached[role].column_names and same(table[name], cached[role][name]) for name in table.column_names):
            raise ValueError('FEEDBACK_REUSE_PREFIX_CONFLICT:' + role)
    for name in hold_names + supplement_names:
        if not same(cached['selector'][name], cached['backtest'][name]):
            raise ValueError('FEEDBACK_REUSE_ROLE_VALUES_CONFLICT:' + name)
    projected = cached['selector'].select(hold_names + supplement_names).to_pylist()
    identity = dict(old['candidate_identity'])
    sources = set(identity['source_sha256']) | {'ops/kb_hold_score.py', 'ops/junda_feedback_candidate.py',
        'ops/render_original_formula_projection.py', 'contracts/a_share_kb_hold_score_v1.json',
        'contracts/a_share_kb_supplemental_signals_v1.json', 'research-panel/workbench-host/kb-chart-overlay.mjs',
        'research-panel/workbench-host/kb-signal-view.mjs', 'research-panel/workbench-host/dot/shell/workbench.local.mjs'}
    identity.update(source_sha256={name: q.sha(REPO / name) for name in sorted(sources)},
                    prior_single_candidate_sha256=OLD_SHA, score_contract_sha256=score_ref['sha256'],
                    score_engine_sha256=q.sha(REPO / 'ops/kb_hold_score.py'),
                    supplemental_contract_sha256=supplemental_ref['sha256'], field_inventory=inventory, single_feedback_enabled=True,
                    feedback_reused_candidate_sha256=feedback_reuse_sha256,
                    source_gate_sha256=gate_ref['sha256'])
    generation = q.canonical_sha(identity)
    short = generation[:16]
    outputs = {}
    for role, before in tables.items():
        after = before
        for name in hold_names + supplement_names:
            values = [row[name] for row in projected]
            if name.endswith('_reason') or name == 'kb_hold_score_status':
                typ = pa.string()
            elif name in ('kb_hold_score', 'kb_hold_score_min', 'kb_hold_score_max'):
                typ = pa.int8()
            elif name in ('kb_hold_bbi', 'kb_hold_k', 'kb_hold_d'):
                typ = pa.float64()
            else:
                typ = pa.bool_()
            after = after.append_column(pa.field(name, typ, nullable=True), pa.array(values, type=typ))
        metadata = dict(after.schema.metadata or {})
        provenance = json.loads(metadata[b'kb_single_candidate_v1'])
        provenance.update(candidate_generation=generation, hold_score_contract=score_ref,
                          score_engine_sha256=identity['score_engine_sha256'], supplemental_contract=supplemental_ref,
                          field_inventory=inventory, source_gate_receipt=gate_ref, single_feedback_enabled=True)
        metadata[b'kb_single_candidate_v1'] = json.dumps(provenance, ensure_ascii=False, sort_keys=True).encode()
        after = after.replace_schema_metadata(metadata)
        target = root / f'JUNDA_{role.upper()}_FEEDBACK_{short}.parquet'
        temporary = target.with_suffix('.pending')
        pq.write_table(after, temporary, compression='zstd')
        if target.exists():
            if q.sha(target) != q.sha(temporary):
                raise ValueError('IMMUTABLE_OUTPUT_CONFLICT:' + str(target))
            temporary.unlink()
        else:
            temporary.replace(target)
        reread = pq.read_table(target)
        if not all(same(before[name], reread[name]) for name in before.column_names):
            raise ValueError('OLD_COLUMN_CHANGED:' + role)
        if not all(reread[name].to_pylist() == [row[name] for row in projected] for name in hold_names + supplement_names):
            raise ValueError('NEW_COLUMN_READBACK_MISMATCH:' + role)
        outputs[role] = dict(path=str(target), sha256=q.sha(target), rows=len(reread),
                             old_column_count=len(before.column_names), old_columns_equal=True,
                             added_column_count=len(hold_names) + len(supplement_names))
    view = json.loads(gzip.decompress(Path(old['assets']['kb']['path']).read_bytes()))
    projection = json.loads(gzip.decompress(Path(old['assets']['projection']['path']).read_bytes()))
    original_rows = projection['formula_result']['rows']
    if len(view['rows']) != len(source) or len(original_rows) != len(source):
        raise ValueError('VIEW_PREFIX_LENGTH_MISMATCH')
    for i, (view_row, src, scores, chart_row) in enumerate(zip(view['rows'], source, projected, original_rows)):
        if int(src['trade_date']) != view_row['trade_date'] or int(src['trade_date']) != int(chart_row['trade_date']):
            raise ValueError('VIEW_PREFIX_DATE_MISMATCH')
        for name in ('open', 'high', 'low', 'close'):
            if float(src[name]) != float(chart_row['ohlcv'][name]):
                raise ValueError('CHART_OHLC_MISMATCH:' + name)
        view_row['hold_score'] = {name: scores[name] for name in hold_names}
        view_row['supplemental'] = {name: scores[name] for name in supplement_names}
        vol, previous_vol = src['volume'], source[i-1]['volume'] if i else None
        ratio = float(vol / previous_vol) if vol is not None and previous_vol and previous_vol > 0 else None
        prior_volumes = [r['volume'] for r in source[max(0, i-5):i]]
        previous_mean = sum(prior_volumes) / 5 if len(prior_volumes) == 5 and all(v is not None and v > 0 for v in prior_volumes) else None
        ratio5 = float(vol / previous_mean) if vol is not None and previous_mean else None
        view_row['diagnostics'] = {'volume_vs_previous': ratio if ratio is not None and math.isfinite(ratio) else None,
                                   'volume_vs_previous_5_mean': ratio5 if ratio5 is not None and math.isfinite(ratio5) else None}
    view.update(candidate_generation=generation, candidate_identity_sha256=generation,
                selector_candidate_sha256=outputs['selector']['sha256'], hold_score_contract_sha256=score_ref['sha256'],
                hold_score_engine_sha256=identity['score_engine_sha256'], supplemental_contract_sha256=supplemental_ref['sha256'],
                field_inventory=inventory, source_gate_receipt=gate_ref)
    raw = json.dumps(view, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    kb_ref = immutable(root / f'JUNDA_FEEDBACK_VIEW_{short}.json.gz', gzip.compress(raw, mtime=0))
    kb_ref.update(encoding='gzip', decoded_bytes=len(raw))
    projection['candidate_generation'] = generation
    projection['lineage']['candidate_generation'] = generation
    projection['lineage']['source_gate'] = gate_ref
    projection['lineage']['selector_candidate'].update(path=outputs['selector']['path'], sha256=outputs['selector']['sha256'],
                                                        added_feedback_columns=len(hold_names) + len(supplement_names))
    raw = (json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    proj_ref = immutable(root / f'JUNDA_FEEDBACK_PROJECTION_{short}.json.gz', gzip.compress(raw, mtime=0))
    proj_ref.update(encoding='gzip', decoded_bytes=len(raw), row_count=len(source), formula_sha256=renderer.FORMULA_SHA)
    renderer_path = Path(renderer.OWNER_RENDERER['path'])
    if q.sha(renderer_path) != renderer.RENDERER_SHA:
        raise ValueError('ORIGINAL_RENDERER_SHA_DRIFT')
    html = renderer.chart_html(renderer_path.read_bytes(), projection, projection['lineage'], compress_payload=True)
    html = html.replace('候选派生投影', '单股研究投影').replace('候选原式派生投影', '单股原式研究投影')
    html_ref = immutable(root / f'JUNDA_FEEDBACK_CHART_{short}.html', html.encode())
    binding = dict(old_binding)
    binding.update(candidate_identity=identity, candidate_generation=generation, assets={'kb': kb_ref, 'projection': proj_ref, 'html': html_ref},
                   hold_score_contract=score_ref, hold_score_engine_sha256=identity['score_engine_sha256'],
                   supplemental_contract=supplemental_ref, field_inventory=inventory, source_gate_receipt=gate_ref)
    binding_ref = write_json(root / f'JUNDA_FEEDBACK_BINDING_{short}.json', binding)
    result = dict(old)
    result.update(status='PREPARED_PENDING_UI_AND_INDEPENDENT_REVIEW', candidate_generation=generation,
                  candidate_identity=identity, binding=binding_ref, outputs=outputs, assets=binding['assets'],
                  field_inventory=inventory, hold_score_contract=score_ref, supplemental_contract=supplemental_ref,
                  superseded_candidate={'path': str(previous), 'sha256': OLD_SHA},
                  last_hold_score=projected[-1], source_gate=gate_ref, source_gate_reverified_for_current_code=True,
                  feedback_reused_from=reuse_ref, feedback_values_unchanged=True,
                  role_input_aliases=role_aliases, role_input_values_equal=True,
                  readback_note='All old role columns compared after disk readback; only named fields were appended.')
    result_ref = write_json(root / f'JUNDA_FEEDBACK_CANDIDATE_{short}.json', result)
    return dict(status=result['status'], generation=generation, receipt=result_ref, binding=binding_ref,
                field_inventory=inventory, last_hold_score=projected[-1], outputs=outputs)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prior', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--source-gate', required=True)
    parser.add_argument('--feedback-reuse', required=True)
    parser.add_argument('--feedback-reuse-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.prior, args.output_dir, args.source_gate, args.feedback_reuse, args.feedback_reuse_sha256),
                     ensure_ascii=False, sort_keys=True, indent=2))
