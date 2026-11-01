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
import sys
import hashlib
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from ops import research_panel_qfq as q
from ops import render_original_formula_projection as renderer
from ops.kb_hold_score import SUPPLEMENTAL_REASONS, project_single_history
from ops.kb_action_authority import FIELDS as ACTION_FIELDS, INPUT_FIELDS as ACTION_INPUT_FIELDS, project_action
from ops.kb_yidong_authority import FIELDS as YIDONG_FIELD_TYPES, INPUT_FIELDS as YIDONG_INPUT_FIELDS, project_yidong_history
from infrastructure.research_workbench_host import checked_relocated_parquet

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


def build(previous, root, source_gate_path, feedback_reuse_path, feedback_reuse_sha256,
          history_ref, company_ref, facts_ref, history_relocation_ref):
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
    score_path = REPO / 'contracts/a_share_kb_hold_score_v1.json'
    score_ref = immutable(root / ('a_share_kb_hold_score_v1_' + q.sha(score_path)[:16] + '.json'), score_path.read_bytes())
    supplemental_ref = immutable(root / 'a_share_kb_supplemental_signals_v1.json', (REPO / 'contracts/a_share_kb_supplemental_signals_v1.json').read_bytes())
    reuse_path = Path(feedback_reuse_path).resolve(strict=True)
    reuse_ref = {'path': str(reuse_path), 'sha256': feedback_reuse_sha256}
    reuse = json.loads(q._source(reuse_ref, owner='prior feedback candidate').read_text())
    reuse_identity = reuse['candidate_identity']
    if (reuse_identity.get('prior_single_candidate_sha256') != OLD_SHA
            or reuse_identity.get('supplemental_contract_sha256') != supplemental_ref['sha256']
            or reuse.get('field_inventory') != inventory):
        raise ValueError('FEEDBACK_REUSE_IDENTITY_CONFLICT')
    cached = {role: pq.read_table(pa.BufferReader(checked_relocated_parquet(ref, history_relocation_ref)))
              if role == 'selector' else pq.read_table(q._source(ref, owner='prior feedback role ' + role))
              for role, ref in reuse['outputs'].items()}
    if set(cached) != {'selector', 'backtest'}:
        raise ValueError('FEEDBACK_REUSE_ROLE_SET_CONFLICT')
    for role, table in tables.items():
        if not all(name in cached[role].column_names and same(table[name], cached[role][name]) for name in table.column_names):
            raise ValueError('FEEDBACK_REUSE_PREFIX_CONFLICT:' + role)
    for name in hold_names + supplement_names:
        if not same(cached['selector'][name], cached['backtest'][name]):
            raise ValueError('FEEDBACK_REUSE_ROLE_VALUES_CONFLICT:' + name)
    projected = project_single_history(SYMBOL, source)
    old_projected = cached['selector'].select(hold_names + supplement_names).to_pylist()
    changed = {'kb_hold_volume_ok', 'kb_hold_volume_ok_reason', 'kb_hold_score',
               'kb_hold_score_min', 'kb_hold_score_max', 'kb_hold_score_status'}
    for old_row, new_row in zip(old_projected, projected):
        if any(old_row[name] != new_row[name] for name in set(hold_names + supplement_names) - changed):
            raise ValueError('UNRELATED_FEEDBACK_FIELD_CHANGED')
    if (projected[-1]['kb_hold_score'],projected[-1]['kb_hold_score_min'],projected[-1]['kb_hold_score_max']) != (None,4,5):
        raise ValueError('LAST_SCORE_COMPONENT_CONFLICT')
    artifacts = {}
    for kind, ref in [('history', history_ref), ('company', company_ref)]:
        path = q._source(ref, owner='single research ' + kind)
        value = json.loads(path.read_text())
        if (value.get('symbol') != SYMBOL or value.get('data_date') != '20261030'
                or value.get('source_generation') != old_binding['source_generation']
                or value.get('input_sha256') != old_binding['source_input_sha256']
                or value.get('numeric_manifest') != old_binding['numeric_manifest']
                or value.get('source_candidate_generation') != reuse['candidate_generation']
                or value.get('historical_PIT') is not False
                or any(value.get(k) != expected for k, expected in q.FLAGS.items())):
            raise ValueError('SINGLE_RESEARCH_ASSET_IDENTITY_CONFLICT:' + kind)
        producer = 'ops/bootstrap_stock_event_history.py' if kind == 'history' else 'ops/research_panel_daily_product.py'
        if value.get('producer_sha256') != q.sha(REPO / producer):
            raise ValueError('SINGLE_RESEARCH_PRODUCER_DRIFT:' + kind)
        raw = path.read_bytes()
        asset = immutable(root / ('JUNDA_' + kind.upper() + '_' + ref['sha256'][:16] + '.json.gz'), gzip.compress(raw, mtime=0))
        asset.update(encoding='gzip', decoded_bytes=len(raw))
        artifacts[kind] = asset
    facts = json.loads(q._source(facts_ref, owner='bound signal components').read_text())
    if (facts.get('symbol') != SYMBOL or facts.get('data_asof') != 20261030
            or facts.get('source',{}).get('sha256') != reuse_identity['baseline_panel_sha256']['selector']):
        raise ValueError('SIGNAL_COMPONENT_SOURCE_CONFLICT')
    identity = dict(old['candidate_identity'])
    sources = set(identity['source_sha256']) | {'ops/kb_hold_score.py', 'ops/junda_feedback_candidate.py',
        'ops/render_original_formula_projection.py', 'contracts/a_share_kb_hold_score_v1.json',
        'contracts/a_share_kb_supplemental_signals_v1.json', 'research-panel/workbench-host/kb-chart-overlay.mjs',
        'research-panel/workbench-host/kb-signal-view.mjs', 'research-panel/workbench-host/dot/shell/workbench.local.mjs',
        'ops/bootstrap_stock_event_history.py', 'ops/research_panel_daily_product.py'}
    identity.update(source_sha256={name: q.sha(REPO / name) for name in sorted(sources)},
                    prior_single_candidate_sha256=OLD_SHA, score_contract_sha256=score_ref['sha256'],
                    score_engine_sha256=q.sha(REPO / 'ops/kb_hold_score.py'),
                    supplemental_contract_sha256=supplemental_ref['sha256'], field_inventory=inventory, single_feedback_enabled=True,
                    feedback_reused_candidate_sha256=feedback_reuse_sha256,
                    history_asset_sha256=artifacts['history']['sha256'], company_asset_sha256=artifacts['company']['sha256'],
                    signal_component_facts_sha256=facts_ref['sha256'], history_source_relocation_sha256=history_relocation_ref['sha256'],
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
                signal_component_facts=facts['facts'], signal_component_facts_sha256=facts_ref['sha256'],
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
    binding.update(candidate_identity=identity, candidate_generation=generation, assets={'kb': kb_ref, 'projection': proj_ref, 'html': html_ref, **artifacts},
                   hold_score_contract=score_ref, hold_score_engine_sha256=identity['score_engine_sha256'],
                   supplemental_contract=supplemental_ref, field_inventory=inventory, source_gate_receipt=gate_ref,
                   history_source_relocation=history_relocation_ref)
    binding_ref = write_json(root / f'JUNDA_FEEDBACK_BINDING_{short}.json', binding)
    result = dict(old)
    result.update(status='PREPARED_PENDING_UI_AND_INDEPENDENT_REVIEW', candidate_generation=generation,
                  candidate_identity=identity, binding=binding_ref, outputs=outputs, assets=binding['assets'],
                  field_inventory=inventory, hold_score_contract=score_ref, supplemental_contract=supplemental_ref,
                  superseded_candidate={'path': str(previous), 'sha256': OLD_SHA},
                  last_hold_score=projected[-1], source_gate=gate_ref, source_gate_reverified_for_current_code=True,
                  feedback_reused_from=reuse_ref, feedback_values_unchanged=False,
                  feedback_changed_fields=sorted(changed), signal_component_facts=facts_ref,
                  role_input_aliases=role_aliases, role_input_values_equal=True,
                  readback_note='All old role columns compared after disk readback; only named fields were appended.')
    result_ref = write_json(root / f'JUNDA_FEEDBACK_CANDIDATE_{short}.json', result)
    return dict(status=result['status'], generation=generation, receipt=result_ref, binding=binding_ref,
                field_inventory=inventory, last_hold_score=projected[-1], outputs=outputs)


def rebind_action_candidate(previous, expected_sha, root, source_gate_ref):
    """Rebind an accepted stock to the action projection without recalculating labels."""
    root = Path(root).resolve(strict=True)
    previous_ref = {'path': str(Path(previous).resolve(strict=True)), 'sha256': expected_sha}
    old = json.loads(q._source(previous_ref, owner='accepted action source candidate').read_text())
    binding = json.loads(q._source(old['binding'], owner='accepted action source binding').read_text())
    if (binding.get('symbol') not in {'002865.SZ', '301048.SZ'}
            or binding.get('candidate_generation') != old.get('candidate_generation')
            or q.canonical_sha(binding.get('candidate_identity')) != old.get('candidate_generation')
            or old.get('candidate_identity') != binding.get('candidate_identity')
            or set(old['outputs']) != {'selector', 'backtest'}):
        raise ValueError('ACTION_SOURCE_IDENTITY_CONFLICT')
    for ref in [*old['outputs'].values(), *binding['assets'].values(), binding['source_gate_receipt'],
                binding['source_relocation'], binding['admission'], binding['numeric_manifest'],
                binding['hold_score_contract'], binding['supplemental_contract']]:
        q._source(ref, owner='accepted action source dependency')
    gate = json.loads(q._source(source_gate_ref, owner='current action source gate').read_text())
    if (gate.get('status') != 'PASS_RELOCATED_SOURCE_GATE'
            or gate.get('canonical_input_sha256') != binding['source_input_sha256']
            or gate.get('relocation_ref') != binding['source_relocation']):
        raise ValueError('ACTION_SOURCE_GATE_CONFLICT')
    for ref in gate['source_code_refs'].values():
        q._source(ref, owner='accepted source gate code')
    for name in ('ops/research_panel_qfq.py', 'ops/kb_action_authority.py', 'contracts/a_share_kb_action_v1.json',
                 'ops/kb_yidong_authority.py', 'contracts/a_share_kb_yidong_v1.json'):
        if gate['source_code_refs'].get(name, {}).get('sha256') != q.sha(REPO / name):
            raise ValueError('ACTION_GATE_CODE_DRIFT:' + name)
    identity = dict(binding['candidate_identity'])
    sources = dict(identity['source_sha256'])
    changed = {'ops/junda_feedback_candidate.py', 'ops/research_panel_qfq.py', 'infrastructure/research_workbench_host.py',
               'research-panel/workbench.html', 'research-panel/workbench-host/kb-single-stock.mjs',
               'research-panel/workbench-host/kb-signal-view.mjs', 'research-panel/workbench-host/bootstrap.mjs'}
    for name, digest in sources.items():
        if name not in changed and q.sha(REPO / name) != digest:
            raise ValueError('ACTION_UNRELATED_SOURCE_DRIFT:' + name)
    if not changed.issubset(sources):
        raise ValueError('ACTION_SOURCE_INVENTORY_INCOMPLETE')
    for name in changed | {'contracts/a_share_kb_action_v1.json', 'ops/kb_action_authority.py',
                           'contracts/a_share_kb_yidong_v1.json', 'ops/kb_yidong_authority.py'}:
        sources[name] = q.sha(REPO / name)
    action_path = REPO / 'contracts/a_share_kb_action_v1.json'
    action_ref = immutable(root / ('a_share_kb_action_v1_' + q.sha(action_path)[:16] + '.json'), action_path.read_bytes())
    yidong_path = REPO / 'contracts/a_share_kb_yidong_v1.json'
    yidong_ref = immutable(root / ('a_share_kb_yidong_v1_' + q.sha(yidong_path)[:16] + '.json'), yidong_path.read_bytes())
    inventory = dict(binding['field_inventory'])
    inventory.update(action_fields=sorted(ACTION_FIELDS), total_action_fields=len(ACTION_FIELDS),
                     yidong_fields=sorted(YIDONG_FIELD_TYPES), total_yidong_fields=len(YIDONG_FIELD_TYPES),
                     total_new_fields=len(inventory['hold_score_fields'])+len(inventory['supplemental_fields'])+len(ACTION_FIELDS)+len(YIDONG_FIELD_TYPES),
                     total_derived_fields=binding['fields_count']+len(inventory['hold_score_fields'])+len(inventory['supplemental_fields'])+len(ACTION_FIELDS)+len(YIDONG_FIELD_TYPES))
    identity.update(source_sha256=sources, action_contract_sha256=action_ref['sha256'],
                    action_authority_sha256=sources['ops/kb_action_authority.py'], source_gate_sha256=source_gate_ref['sha256'],
                    yidong_contract_sha256=yidong_ref['sha256'], yidong_authority_sha256=sources['ops/kb_yidong_authority.py'],
                    field_inventory=inventory, single_action_enabled=True, single_yidong_enabled=True, action_prior_candidate_sha256=expected_sha)
    generation = q.canonical_sha(identity)
    short = generation[:16]

    def data_sha(table):
        canonical = table.replace_schema_metadata(None).combine_chunks()
        sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, canonical.schema) as stream:
            stream.write_table(canonical)
        return __import__('hashlib').sha256(sink.getvalue().to_pybytes()).hexdigest()

    inputs = {role:pq.read_table(q._source(ref, owner='accepted action role ' + role)) for role,ref in old['outputs'].items()}
    selector, backtest = inputs['selector'], inputs['backtest']
    if any(name not in selector.column_names or name not in backtest.column_names or not same(selector[name], backtest[name])
           for name in ACTION_INPUT_FIELDS):
        raise ValueError('ACTION_ROLE_INPUTS_CONFLICT')
    for name in YIDONG_INPUT_FIELDS:
        other = 'vol' if name == 'volume' else name
        if name not in selector.column_names or other not in backtest.column_names:
            raise ValueError('YIDONG_ROLE_INPUT_MISSING:' + name)
        if name == 'trade_date':
            if [int(v) for v in selector[name].to_pylist()] != [int(v) for v in backtest[other].to_pylist()]:
                raise ValueError('YIDONG_ROLE_DATES_CONFLICT')
        elif not same(selector[name], backtest[other]):
            raise ValueError('YIDONG_ROLE_INPUTS_CONFLICT:' + name)
    action_rows = [project_action(row, rule_sha256=action_ref['sha256']) for row in selector.select(sorted(ACTION_INPUT_FIELDS)).to_pylist()]
    yidong_rows = project_yidong_history(selector.select(sorted(YIDONG_INPUT_FIELDS)).to_pylist(), digest=yidong_ref['sha256'])
    field_types = {'string': pa.string(), 'bool': pa.bool_(), 'double': pa.float64(), 'int8': pa.int8(), 'int32': pa.int32()}
    outputs = {}
    for role, ref in old['outputs'].items():
        before = inputs[role]
        if (ACTION_FIELDS | set(YIDONG_FIELD_TYPES)) & set(before.column_names):
            raise ValueError('ACTION_SOURCE_ALREADY_PRESENT:' + role)
        metadata = dict(before.schema.metadata or {})
        provenance = json.loads(metadata[b'kb_single_candidate_v1'])
        if provenance.get('candidate_generation') != old['candidate_generation']:
            raise ValueError('ACTION_SOURCE_ROLE_GENERATION_CONFLICT:' + role)
        provenance.update(candidate_generation=generation, action_contract_sha256=action_ref['sha256'],
                          action_authority_sha256=identity['action_authority_sha256'], single_action_enabled=True,
                          yidong_contract_sha256=yidong_ref['sha256'], yidong_authority_sha256=identity['yidong_authority_sha256'],
                          single_yidong_enabled=True, source_gate_receipt=source_gate_ref, field_inventory=inventory)
        metadata[b'kb_single_candidate_v1'] = json.dumps(provenance, ensure_ascii=False, sort_keys=True).encode()
        table = before.replace_schema_metadata(metadata)
        for name in sorted(ACTION_FIELDS):
            table = table.append_column(pa.field(name, pa.string(), nullable=True),
                                        pa.array([row[name] for row in action_rows], type=pa.string()))
        for name in sorted(YIDONG_FIELD_TYPES):
            typ = field_types[YIDONG_FIELD_TYPES[name]]
            table = table.append_column(pa.field(name, typ, nullable=True), pa.array([row[name] for row in yidong_rows], type=typ))
        sink = pa.BufferOutputStream()
        pq.write_table(table, sink, compression='zstd')
        target = root / f"{binding['symbol'].replace('.', '_')}_{role.upper()}_ACTION_{short}.parquet"
        new_ref = immutable(target, sink.getvalue().to_pybytes())
        reread = pq.read_table(q._source(new_ref, owner='action role readback'))
        if (data_sha(before) != data_sha(reread.select(before.column_names))
                or any(reread[name].to_pylist() != [row[name] for row in action_rows] for name in ACTION_FIELDS)
                or any(reread[name].to_pylist() != [row[name] for row in yidong_rows] for name in YIDONG_FIELD_TYPES)):
            raise ValueError('ACTION_ROLE_VALUES_CHANGED:' + role)
        outputs[role] = {**ref, **new_ref, 'rows': len(reread), 'old_columns_equal': True,
                         'arrow_data_sha256': data_sha(before)}

    def read_gzip(ref):
        return json.loads(gzip.decompress(q._source(ref, owner='accepted action asset').read_bytes()))

    view = read_gzip(binding['assets']['kb'])
    projection = read_gzip(binding['assets']['projection'])
    if (view.get('symbol') != binding['symbol'] or view.get('candidate_generation') != old['candidate_generation']
            or projection.get('symbol') != binding['symbol'] or projection.get('candidate_generation') != old['candidate_generation']):
        raise ValueError('ACTION_SOURCE_ASSET_CONFLICT')
    if len(view.get('rows', [])) != len(action_rows):
        raise ValueError('ACTION_VIEW_LENGTH_CONFLICT')
    for row, action, yidong in zip(view['rows'], action_rows, yidong_rows):
        if project_action({**row['kb'], **row['hold_score'], **row['original']}, rule_sha256=action_ref['sha256']) != action:
            raise ValueError('ACTION_VIEW_SOURCE_CONFLICT:' + str(row.get('trade_date')))
        row['action'] = action
        row['yidong'] = yidong
    view.update(candidate_generation=generation, candidate_identity_sha256=generation, field_inventory=inventory,
                source_gate_receipt=source_gate_ref, selector_candidate_sha256=outputs['selector']['sha256'], action_contract_sha256=action_ref['sha256'],
                yidong_contract_sha256=yidong_ref['sha256'])
    raw = json.dumps(view, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    kb = immutable(root / f"{binding['symbol'].replace('.', '_')}_ACTION_VIEW_{short}.json.gz", gzip.compress(raw, mtime=0))
    kb.update(encoding='gzip', decoded_bytes=len(raw))
    projection.update(candidate_generation=generation)
    projection['lineage']['candidate_generation'] = generation
    projection['lineage']['selector_candidate'] = outputs['selector']
    projection['lineage']['source_gate'] = source_gate_ref
    raw = (json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    proj = immutable(root / f"{binding['symbol'].replace('.', '_')}_ACTION_PROJECTION_{short}.json.gz", gzip.compress(raw, mtime=0))
    proj.update(encoding='gzip', decoded_bytes=len(raw), row_count=len(view['rows']), formula_sha256=renderer.FORMULA_SHA)
    html = renderer.chart_html(Path(renderer.OWNER_RENDERER['path']).read_bytes(), projection, projection['lineage'], compress_payload=True)
    html = html.replace('候选派生投影', '单股研究投影').replace('候选原式派生投影', '单股原式研究投影')
    chart = immutable(root / f"{binding['symbol'].replace('.', '_')}_ACTION_CHART_{short}.html", html.encode())
    assets = {**binding['assets'], 'kb': kb, 'projection': proj, 'html': chart}
    binding.update(candidate_identity=identity, candidate_generation=generation, action_contract=action_ref, yidong_contract=yidong_ref,
                   source_gate_receipt=source_gate_ref, field_inventory=inventory, assets=assets)
    binding_ref = write_json(root / f"{binding['symbol'].replace('.', '_')}_ACTION_BINDING_{short}.json", binding)
    result = dict(old)
    result.update(candidate_generation=generation, candidate_identity=identity, outputs=outputs, assets=assets,
                  binding=binding_ref, action_contract=action_ref, yidong_contract=yidong_ref, action_rebound_from=previous_ref,
                  source_gate=source_gate_ref, field_inventory=inventory,
                  status='PREPARED_PENDING_UI_AND_INDEPENDENT_REVIEW')
    result_ref = write_json(root / f"{binding['symbol'].replace('.', '_')}_ACTION_CANDIDATE_{short}.json", result)
    return {'candidate_generation': generation, 'candidate': result_ref, 'binding': binding_ref,
            'symbol': binding['symbol'], 'role_values': 'EXACT_ARROW_IPC_SHA_MATCH', 'action_contract': action_ref}


def rebind_display_candidate(previous, expected_sha, root):
    """Add a same-generation display-only projection of an accepted paired candidate."""
    root = Path(root).resolve(strict=True)
    prior = {'path': str(Path(previous).resolve(strict=True)), 'sha256': expected_sha}
    old = json.loads(q._source(prior, owner='accepted display source candidate').read_text())
    binding = json.loads(q._source(old['binding'], owner='accepted display source binding').read_text())
    if (binding.get('symbol') not in {'002865.SZ', '301048.SZ'} or old.get('candidate_identity') != binding.get('candidate_identity')
            or binding.get('candidate_generation') != old.get('candidate_generation')
            or q.canonical_sha(binding.get('candidate_identity')) != old.get('candidate_generation')
            or set(old['outputs']) != {'selector', 'backtest'}):
        raise ValueError('DISPLAY_SOURCE_IDENTITY_CONFLICT')
    for ref in [*old['outputs'].values(), *binding['assets'].values(), binding['source_gate_receipt'],
                binding['source_relocation'], binding['admission'], binding['numeric_manifest'],
                binding['hold_score_contract'], binding['supplemental_contract'], binding['action_contract'], binding['yidong_contract']]:
        q._source(ref, owner='accepted display dependency')
    gate = json.loads(q._source(binding['source_gate_receipt'], owner='display source gate').read_text())
    if (gate.get('status') != 'PASS_RELOCATED_SOURCE_GATE' or gate.get('canonical_input_sha256') != binding['source_input_sha256']
            or gate.get('relocation_ref') != binding['source_relocation']):
        raise ValueError('DISPLAY_SOURCE_GATE_CONFLICT')
    for ref in gate['source_code_refs'].values():
        q._source(ref, owner='display source gate code')
    policy_path = REPO / 'contracts/a_share_single_display_projection_v1.json'
    policy = json.loads(policy_path.read_text())
    excluded = policy['excluded_from_display_projection']
    if (policy.get('schema') != 'a_share_single_display_projection_v1' or len(excluded) != 25 or len(set(excluded)) != 25
            or binding['symbol'] not in policy.get('authorized_symbols', []) or any(policy.get(k) != v for k, v in q.FLAGS.items())):
        raise ValueError('DISPLAY_POLICY_INVALID')
    policy_ref = immutable(root / ('a_share_single_display_projection_v1_' + q.sha(policy_path)[:16] + '.json'), policy_path.read_bytes())
    company = json.loads(gzip.decompress(q._source(binding['assets']['company'], owner='bound company asset').read_bytes()))
    f10_ref = company['source_refs']['tdx_f10']['file']
    f10 = json.loads(q._source(f10_ref, owner='bound F10 concept snapshot').read_text())
    concepts = f10.get('concepts')
    if (f10.get('symbol') != binding['symbol'] or f10.get('status') != 'OBSERVED'
            or f10.get('concept_status') != 'OBSERVED' or not isinstance(concepts, list)
            or not 0 < len(concepts) <= 127 or not all(isinstance(x, dict) and isinstance(x.get('name'), str) and x['name'] for x in concepts)
            or len({x['name'] for x in concepts}) != len(concepts)
            or not isinstance(f10.get('captured_at'), str)
            or hashlib.sha256(f10.get('source_text', '').encode()).hexdigest() != f10.get('source_text_sha256')
            or company.get('f10', {}).get('concepts') != concepts
            or company.get('f10', {}).get('captured_at') != f10['captured_at']):
        raise ValueError('DISPLAY_F10_IDENTITY_CONFLICT')
    concept_text = '、'.join(item['name'] for item in concepts)
    identity = dict(binding['candidate_identity'])
    sources = dict(identity['source_sha256'])
    changed = {'ops/junda_feedback_candidate.py', 'infrastructure/research_workbench_host.py',
               'research-panel/workbench-host/kb-single-stock.mjs', 'research-panel/workbench-host/bootstrap.mjs'}
    for name, digest in sources.items():
        if name not in changed and q.sha(REPO / name) != digest:
            raise ValueError('DISPLAY_UNRELATED_SOURCE_DRIFT:' + name)
    if not changed.issubset(sources):
        raise ValueError('DISPLAY_SOURCE_INVENTORY_INCOMPLETE')
    for name in changed | {'contracts/a_share_single_display_projection_v1.json'}:
        sources[name] = q.sha(REPO / name)
    identity.update(source_sha256=sources, display_policy_sha256=policy_ref['sha256'],
                    display_f10_sha256=f10_ref['sha256'], display_prior_candidate_sha256=expected_sha)
    generation = q.canonical_sha(identity);short = generation[:16]

    def data_sha(table):
        canonical = table.replace_schema_metadata(None).combine_chunks();sink = pa.BufferOutputStream()
        with pa.ipc.new_stream(sink, canonical.schema) as stream:
            stream.write_table(canonical)
        return hashlib.sha256(sink.getvalue().to_pybytes()).hexdigest()

    outputs, display_roles = {}, {}
    for role, source_ref in old['outputs'].items():
        before = pq.read_table(q._source(source_ref, owner='accepted display input role ' + role))
        if any(name in before.column_names for name in ('kb_concepts','kb_concept_count')) or 'kb_hold_volume_ok_reason' not in before.column_names:
            raise ValueError('DISPLAY_SOURCE_SCHEMA_CONFLICT:' + role)
        if not len(before) or int(before['trade_date'][-1].as_py()) != 20261030:
            raise ValueError('DISPLAY_ASOF_ROW_CONFLICT:' + role)
        metadata = dict(before.schema.metadata or {});provenance = json.loads(metadata[b'kb_single_candidate_v1'])
        if provenance.get('candidate_generation') != old['candidate_generation']:
            raise ValueError('DISPLAY_SOURCE_ROLE_GENERATION_CONFLICT:' + role)
        provenance.update(candidate_generation=generation, display_policy_sha256=policy_ref['sha256'], display_f10_sha256=f10_ref['sha256'])
        metadata[b'kb_single_candidate_v1'] = json.dumps(provenance, ensure_ascii=False, sort_keys=True).encode()
        full = before.replace_schema_metadata(metadata);sink = pa.BufferOutputStream();pq.write_table(full, sink, compression='zstd')
        full_ref = immutable(root / f"{binding['symbol'].replace('.', '_')}_{role.upper()}_FULL_{short}.parquet", sink.getvalue().to_pybytes())
        reread = pq.read_table(q._source(full_ref, owner='display full role readback'))
        if data_sha(before) != data_sha(reread):
            raise ValueError('DISPLAY_FULL_SOURCE_VALUES_CHANGED:' + role)
        outputs[role] = {**source_ref, **full_ref, 'rows': len(reread), 'old_columns_equal': True,
                         'arrow_data_sha256': data_sha(before)}
        kept = [name for name in reread.column_names if name not in excluded]
        projected = reread.select(kept)
        projected = projected.append_column(pa.field('kb_concepts', pa.string(), nullable=True),
            pa.array([None] * (len(projected)-1) + [concept_text], type=pa.string()))
        projected = projected.append_column(pa.field('kb_concept_count', pa.int8(), nullable=True),
            pa.array([None] * (len(projected)-1) + [len(concepts)], type=pa.int8()))
        context = dict(schema='a_share_single_display_projection_v1', candidate_generation=generation,
            symbol=binding['symbol'], role=role, source_full_sha256=full_ref['sha256'], policy_sha256=policy_ref['sha256'],
            f10_sha256=f10_ref['sha256'], captured_at=f10['captured_at'], source_date=binding['source_date'],
            concept_scope='CURRENT_OBSERVATION_ONLY', historical_PIT=False, **q.FLAGS)
        projected = projected.replace_schema_metadata({b'a_share_single_display_projection_v1':json.dumps(context, ensure_ascii=False, sort_keys=True).encode()})
        sink = pa.BufferOutputStream();pq.write_table(projected, sink, compression='zstd')
        ref = immutable(root / f"{binding['symbol'].replace('.', '_')}_{role.upper()}_DISPLAY_{short}.parquet", sink.getvalue().to_pybytes())
        read = pq.read_table(q._source(ref, owner='display projection readback'))
        if (data_sha(reread.select(kept)) != data_sha(read.select(kept))
                or read['kb_concepts'].to_pylist() != [None]*(len(read)-1)+[concept_text]
                or read['kb_concept_count'].to_pylist() != [None]*(len(read)-1)+[len(concepts)]):
            raise ValueError('DISPLAY_PROJECTION_VALUES_CHANGED:' + role)
        display_roles[role] = {'artifact':ref, 'source_full':full_ref, 'rows':len(read), 'columns':len(read.column_names),
                               'removed_fields':sorted(set(excluded)&set(before.column_names))}
    display = dict(policy=policy_ref, f10_source=f10_ref, captured_at=f10['captured_at'], roles=display_roles,
                   kb_concepts=concept_text, kb_concept_count=len(concepts), historical_PIT=False)
    view = json.loads(gzip.decompress(q._source(binding['assets']['kb'], owner='accepted display view').read_bytes()))
    projection = json.loads(gzip.decompress(q._source(binding['assets']['projection'], owner='accepted chart projection').read_bytes()))
    if view.get('candidate_generation') != old['candidate_generation'] or projection.get('candidate_generation') != old['candidate_generation']:
        raise ValueError('DISPLAY_SOURCE_VIEW_GENERATION_CONFLICT')
    view.update(candidate_generation=generation, candidate_identity_sha256=generation,
                selector_candidate_sha256=outputs['selector']['sha256'],
                concept_snapshot=dict(kb_concepts=concept_text, kb_concept_count=len(concepts),
                    captured_at=f10['captured_at'], source_sha256=f10_ref['sha256'], historical_PIT=False))
    raw = json.dumps(view, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()
    kb = immutable(root / f"{binding['symbol'].replace('.', '_')}_DISPLAY_VIEW_{short}.json.gz", gzip.compress(raw, mtime=0))
    kb.update(encoding='gzip', decoded_bytes=len(raw))
    projection.update(candidate_generation=generation);projection['lineage']['candidate_generation'] = generation
    projection['lineage']['selector_candidate'] = outputs['selector']
    raw = (json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()
    proj = immutable(root / f"{binding['symbol'].replace('.', '_')}_DISPLAY_CHART_PROJECTION_{short}.json.gz", gzip.compress(raw, mtime=0))
    proj.update(encoding='gzip', decoded_bytes=len(raw), row_count=len(view['rows']), formula_sha256=renderer.FORMULA_SHA)
    html = renderer.chart_html(Path(renderer.OWNER_RENDERER['path']).read_bytes(), projection, projection['lineage'], compress_payload=True)
    html = html.replace('候选派生投影', '单股研究投影').replace('候选原式派生投影', '单股原式研究投影')
    chart = immutable(root / f"{binding['symbol'].replace('.', '_')}_DISPLAY_CHART_{short}.html", html.encode())
    assets = {**binding['assets'], 'kb':kb, 'projection':proj, 'html':chart}
    binding.update(candidate_identity=identity, candidate_generation=generation, display_projection=display, assets=assets)
    binding_ref = write_json(root / f"{binding['symbol'].replace('.', '_')}_DISPLAY_BINDING_{short}.json", binding)
    result = dict(old);result.update(candidate_generation=generation, candidate_identity=identity, outputs=outputs,
        assets=assets, binding=binding_ref, display_projection=display, display_rebound_from=prior,
        status='PREPARED_PENDING_UI_AND_INDEPENDENT_REVIEW')
    result_ref = write_json(root / f"{binding['symbol'].replace('.', '_')}_DISPLAY_CANDIDATE_{short}.json", result)
    return {'candidate_generation':generation, 'candidate':result_ref, 'binding':binding_ref, 'symbol':binding['symbol'],
            'full_columns':{role:len(pq.read_schema(ref['path'])) for role,ref in outputs.items()},
            'display_columns':{role:item['columns'] for role,item in display_roles.items()}, 'concept_count':len(concepts)}


if __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'rebind-display':
    parser = argparse.ArgumentParser()
    parser.add_argument('rebind-display')
    parser.add_argument('--prior', required=True)
    parser.add_argument('--prior-sha256', required=True)
    parser.add_argument('--output-dir', required=True)
    args = parser.parse_args()
    print(json.dumps(rebind_display_candidate(args.prior, args.prior_sha256, args.output_dir), ensure_ascii=False))
elif __name__ == '__main__' and len(sys.argv) > 1 and sys.argv[1] == 'rebind-action':
    parser = argparse.ArgumentParser()
    parser.add_argument('rebind-action')
    parser.add_argument('--prior', required=True)
    parser.add_argument('--prior-sha256', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--source-gate', required=True)
    parser.add_argument('--source-gate-sha256', required=True)
    args = parser.parse_args()
    gate_ref = {'path': str(Path(args.source_gate).resolve(strict=True)), 'sha256': args.source_gate_sha256}
    print(json.dumps(rebind_action_candidate(args.prior, args.prior_sha256, args.output_dir, gate_ref), ensure_ascii=False))
elif __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--prior', required=True)
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--source-gate', required=True)
    parser.add_argument('--feedback-reuse', required=True)
    parser.add_argument('--feedback-reuse-sha256', required=True)
    for name in ('history', 'company', 'facts', 'history_relocation'):
        parser.add_argument('--' + name.replace('_','-'), required=True)
        parser.add_argument('--' + name.replace('_','-') + '-sha256', required=True)
    args = parser.parse_args()
    refs = [{"path": str(Path(getattr(args,name)).resolve(strict=True)), "sha256": getattr(args,name+'_sha256')}
            for name in ('history','company','facts','history_relocation')]
    print(json.dumps(build(args.prior, args.output_dir, args.source_gate, args.feedback_reuse, args.feedback_reuse_sha256,*refs),
                     ensure_ascii=False, sort_keys=True, indent=2))
