"""Strict opt-in identity and change classification for the original QFQ owner.

This module does not publish, calculate labels, or change a panel.  The caller
must first validate its normal source snapshot and keep the candidate isolated.
"""
from __future__ import annotations

import ast
import json
import math
import os
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq


_CONTROL_ONLY = frozenset({'run_daily_rebuild', '_revalidate_build_identity', 'run_action_correction_candidate'})
_KERNEL_KEYS = (
    'driver_sha256', 'formula_sha256', 'field_contract_sha256', 'user_formula_sha256',
    'input_adapter_sha256', 'factor_cache_sha256', 'tdx_adapter_sha256',
    'kb_authority_sha256', 'kb_field_contract_sha256',
    'single_score_authority_sha256', 'single_score_contract_sha256',
    'single_supplemental_contract_sha256', 'single_action_authority_sha256',
    'single_action_contract_sha256', 'single_yidong_authority_sha256',
    'single_yidong_contract_sha256', 'confirmed_gap_contract_sha256',
    'confirmed_gap_helper_sha256', 'confirmed_gap_rebuild_contract_sha256',
    'confirmed_gap_components_contract_sha256', 'n_structure_helper_sha256',
    'n_structure_contract_sha256', 'full_research_contract_sha256',
)
_ASOF_FIELDS = ('user_v1_hold_yesterday_keyline_display_asof',
                'user_v1_break_yesterday_keyline_display_asof',
                'user_v1_sell_signal_display_asof')


def _same_scalar(left,right):
    if left is None or right is None:return left is None and right is None
    if isinstance(left,float) and isinstance(right,float):
        if math.isnan(left) or math.isnan(right):return math.isnan(left) and math.isnan(right)
        if left==0.0 and right==0.0:return math.copysign(1.0,left)==math.copysign(1.0,right)
    return left==right


def reconcile_panel(old, fresh, *, code, previous, target, q):
    """Keep old Arrow rows until the first new/revised source-dependent bar."""
    if not old.schema.equals(fresh.schema,check_metadata=False):
        raise q.QfqGateError('FULL_DAILY_OUTPUT_SCHEMA_CHANGED:'+code)
    required={'ts_code','trade_date','open','high','low','close','amount','pre_close','pct_chg',*_ASOF_FIELDS}
    if not required<=set(old.column_names):raise q.QfqGateError('FULL_DAILY_OUTPUT_COMPONENT_MISSING:'+code)
    volume='volume' if 'volume' in old.column_names else 'vol'
    if volume not in old.column_names:raise q.QfqGateError('FULL_DAILY_OUTPUT_VOLUME_MISSING:'+code)
    if set(old['ts_code'].to_pylist())!={code} or set(fresh['ts_code'].to_pylist())!={code}:
        raise q.QfqGateError('FULL_DAILY_OUTPUT_SYMBOL_CONFLICT:'+code)
    old_dates=[int(x) for x in old['trade_date'].to_pylist()]
    new_dates=[int(x) for x in fresh['trade_date'].to_pylist()]
    if (old_dates!=sorted(set(old_dates)) or new_dates!=sorted(set(new_dates))
            or not set(old_dates)<=set(new_dates) or not old_dates or max(old_dates)>previous
            or not new_dates or max(new_dates)>target):
        raise q.QfqGateError('FULL_DAILY_OUTPUT_KEYS_CONFLICT:'+code)
    positions={day:i for i,day in enumerate(new_dates)}
    compare=('open','high','low','close',volume,'amount','pre_close','pct_chg')
    old_values={name:old[name].to_pylist() for name in compare}
    new_values={name:fresh[name].to_pylist() for name in compare}
    revised=[day for i,day in enumerate(old_dates)
             if any(not _same_scalar(old_values[name][i],new_values[name][positions[day]]) for name in compare)]
    added=sorted(set(new_dates)-set(old_dates))
    boundaries=revised+added;first=min(boundaries) if boundaries else None
    old_keep=[i for i,day in enumerate(old_dates) if first is None or day<first]
    new_keep=[i for i,day in enumerate(new_dates) if first is not None and day>=first]
    prefix=old.take(pa.array(old_keep,type=pa.int64())).combine_chunks()
    if target>previous and previous in old_dates and previous in [old_dates[i] for i in old_keep]:
        mask=pc.equal(prefix['trade_date'],pa.scalar(str(previous) if pa.types.is_string(prefix['trade_date'].type)
                                                      else previous,type=prefix['trade_date'].type))
        for name in _ASOF_FIELDS:
            pos=prefix.schema.get_field_index(name)
            prefix=prefix.set_column(pos,prefix.schema.field(pos),pc.if_else(mask,fresh[name][positions[previous]],prefix[name]))
    suffix=fresh.take(pa.array(new_keep,type=pa.int64()))
    output=pa.concat_tables([prefix.replace_schema_metadata(None),suffix.replace_schema_metadata(None)])
    output=output.replace_schema_metadata(fresh.schema.metadata)
    dates=[int(x) for x in output['trade_date'].to_pylist()]
    if dates!=new_dates:raise q.QfqGateError('FULL_DAILY_RECONCILED_KEYS_CONFLICT:'+code)
    return output,{'symbol':code,'first_affected_date':first,'preserved_rows':len(old_keep),
                   'recomputed_rows':len(new_keep),'revised_dates':revised,'added_dates':added,
                   'asof_display_updated':target>previous and previous in old_dates}


def reconcile_sidecar(old_ref, fresh_ref, *, code, first_affected_date, destination, q):
    """Preserve an old diagnostic prefix only when its causal input hash matches."""
    old_path=q._source(old_ref,owner='full daily prior diagnostic sidecar '+code)
    fresh_path=q._source(fresh_ref,owner='full daily new diagnostic sidecar '+code)
    old=pq.read_table(old_path);fresh=pq.read_table(fresh_path)
    columns=['ts_code','trade_date','diagnostics_json','prefix_input_sha256']
    if old.column_names!=columns or fresh.column_names!=columns or not old.schema.equals(fresh.schema,check_metadata=False):
        raise q.QfqGateError('FULL_DAILY_SIDECAR_SCHEMA_CHANGED:'+code)
    old_dates=[int(x) for x in old['trade_date'].to_pylist()]
    new_dates=[int(x) for x in fresh['trade_date'].to_pylist()]
    if (set(old['ts_code'].to_pylist())!={code} or set(fresh['ts_code'].to_pylist())!={code}
            or old_dates!=sorted(set(old_dates)) or new_dates!=sorted(set(new_dates))
            or not set(old_dates)<=set(new_dates)):
        raise q.QfqGateError('FULL_DAILY_SIDECAR_KEYS_CONFLICT:'+code)
    before=[i for i,d in enumerate(old_dates) if first_affected_date is None or d<first_affected_date]
    after=[i for i,d in enumerate(new_dates) if first_affected_date is not None and d>=first_affected_date]
    prefix_day=old_dates[before[-1]] if before else None
    old_hash=None
    if prefix_day is not None:
        new_index=new_dates.index(prefix_day)
        old_hash=old['prefix_input_sha256'][before[-1]].as_py()
        if not isinstance(old_hash,str) or old_hash!=fresh['prefix_input_sha256'][new_index].as_py():
            raise q.QfqGateError('FULL_DAILY_SIDECAR_PREFIX_INPUT_CHANGED:'+code)
    metadata=dict(fresh.schema.metadata or {})
    try:payload=json.loads(metadata[b'v4.a_share.kb_gap_diagnostics.v1'])
    except (KeyError,ValueError,TypeError) as exc:raise q.QfqGateError('FULL_DAILY_SIDECAR_METADATA_INVALID:'+code) from exc
    payload['inherited_prefix']={'source':old_ref,'rows':len(before),'through_date':prefix_day,
        'identity_policy':'ORIGINAL_SOURCE_IDENTITY_RETAINED_IN_DIAGNOSTICS',
        'cross_generation_n_checkpoint_reused':False}
    payload['continuation']={'fresh_source':fresh_ref,'first_affected_date':first_affected_date,
        'prefix_input_sha256':old_hash,'prefix_through_date':prefix_day}
    metadata[b'v4.a_share.kb_gap_diagnostics.v1']=json.dumps(payload,sort_keys=True).encode()
    result=pa.concat_tables([old.take(pa.array(before,type=pa.int64())).replace_schema_metadata(None),
                             fresh.take(pa.array(after,type=pa.int64())).replace_schema_metadata(None)])
    result=result.replace_schema_metadata(metadata)
    if [int(x) for x in result['trade_date'].to_pylist()]!=new_dates:
        raise q.QfqGateError('FULL_DAILY_SIDECAR_OUTPUT_KEYS_CONFLICT:'+code)
    destination=Path(destination);temporary=destination.with_suffix('.pending')
    pq.write_table(result,temporary,compression='zstd')
    if destination.exists():
        if q.sha(destination)!=q.sha(temporary):raise q.QfqGateError('FULL_DAILY_SIDECAR_IMMUTABLE_CONFLICT:'+code)
        temporary.unlink()
    else:os.replace(temporary,destination)
    return {'path':str(destination),'sha256':q.sha(destination),'rows':len(result),
            'checkpoint_id':fresh_ref.get('checkpoint_id'),
            'inherited_prefix':payload['inherited_prefix'],'continuation':payload['continuation']}


def advance_unchanged_asof(table, *, previous, target, unchanged_codes, q):
    """Only the three original as-of display columns change on an idle stock."""
    if target<=previous or not unchanged_codes or not len(table):return table
    required={'ts_code','trade_date',*_ASOF_FIELDS,'user_v1_white_yellow_death_cross','user_v1_break_prev_low'}
    if not required<=set(table.column_names):raise q.QfqGateError('FULL_DAILY_ASOF_SOURCE_FIELDS_MISSING')
    mask=[code in unchanged_codes and int(day)==previous for code,day in
          zip(table['ts_code'].to_pylist(),table['trade_date'].to_pylist())]
    if not any(mask):return table
    cross=table['user_v1_white_yellow_death_cross'].to_pylist()
    didi=table['user_v1_break_prev_low'].to_pylist()
    result=table
    for name in _ASOF_FIELDS:
        values=table[name].to_pylist()
        for i,selected in enumerate(mask):
            if not selected:continue
            if name!=_ASOF_FIELDS[2]:values[i]=0;continue
            left,right=cross[i],didi[i]
            values[i]=1 if left==1 or right==1 else 0 if left==0 and right==0 else None
        position=result.schema.get_field_index(name)
        result=result.set_column(position,result.schema.field(position),pa.array(values,type=result.schema.field(position).type))
    return result


def computation_semantics_sha(path: Path, q) -> str:
    """Bind all QFQ module syntax except the two release-control functions."""
    nodes = [node for node in ast.parse(Path(path).read_text()).body
             if not (isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in _CONTROL_ONLY)]
    return q.canonical_sha([ast.dump(node, include_attributes=False) for node in nodes])


def bind(ref, *, q, snapshot, target, identity, currents, baseline_hashes, driver):
    """Return affected symbols only after exact inputs, rules and calendars bind."""
    value=json.loads(q._source(ref, owner='full research daily continuation').read_text())
    if (value.get('schema')!='a_share_kb_daily_continuation_v1'
            or value.get('status')!='PREPARED_NOT_CONSUMED'
            or value.get('target_date')!=target or value.get('historical_PIT') is not False
            or any(value.get(k)!=v for k,v in q.FLAGS.items())):
        raise q.QfqGateError('FULL_DAILY_CONTINUATION_DESCRIPTOR_INVALID')
    old_receipt_ref=value.get('baseline_receipt')
    old_receipt=json.loads(q._source(old_receipt_ref, owner='full daily baseline receipt').read_text())
    old_snapshot_ref=value.get('baseline_snapshot')
    old=json.loads(q._source(old_snapshot_ref, owner='full daily baseline snapshot').read_text())
    old_source=q._source(value.get('baseline_adapter'), owner='full daily baseline QFQ source')
    previous=old_receipt.get('target_date')
    if (type(previous) is not int or previous>target or old.get('asof_date')!=previous
            or old_receipt.get('status') not in {'CANDIDATE_READY','READY'}
            or old_receipt.get('research_scope')!='ADMITTED_A_SHARE'
            or old_receipt.get('adjustment_snapshot')!=old_snapshot_ref
            or old_receipt.get('snapshot_file_sha256')!=old_snapshot_ref['sha256']
            or old_receipt.get('input_sha256')!=q.canonical_sha(old)
            or old_receipt.get('adapter_sha256')!=value['baseline_adapter']['sha256']
            or old_receipt.get('full_research_contract_sha256')!=identity.get('full_research_contract_sha256')):
        raise q.QfqGateError('FULL_DAILY_BASELINE_RECEIPT_CONFLICT')
    for role,path in currents.items():
        role_ref=value.get('baseline_roles',{}).get(role,{})
        meta=q.panel_contract(path)
        if (role_ref.get('path')!=str(path) or role_ref.get('sha256')!=baseline_hashes[role]
                or old_receipt.get('candidates',{}).get(role)!=str(path)
                or old_receipt.get('candidate_sha256',{}).get(role)!=baseline_hashes[role]
                or meta.get('generation_id')!=old_receipt.get('generation_id')
                or meta.get('input_sha256')!=old_receipt.get('input_sha256')
                or meta.get('generation_manifest_path')!=old_receipt_ref['path']
                or meta.get('snapshot_file_sha256')!=old_snapshot_ref['sha256']
                or meta.get('research_scope')!='ADMITTED_A_SHARE'):
            raise q.QfqGateError('FULL_DAILY_BASELINE_ROLE_CONFLICT:'+role)
        if any(key not in meta or key not in identity or meta[key] is None or identity[key] is None
               or meta[key]!=identity[key] for key in _KERNEL_KEYS):
            raise q.QfqGateError('FULL_DAILY_CALCULATION_IDENTITY_CHANGED:'+role)
    if (computation_semantics_sha(old_source,q)!=computation_semantics_sha(Path(q.__file__),q)):
        raise q.QfqGateError('FULL_DAILY_QFQ_COMPUTATION_CHANGED')
    for key in ('convention','price_basis','volume_basis','amount_basis'):
        if old.get(key)!=snapshot.get(key):raise q.QfqGateError('FULL_DAILY_BASIS_CHANGED:'+key)
    # Membership changes require the original, separately bound lifecycle
    # authority.  This continuation cannot admit, remove or unquarantine codes.
    for key in ('original_target_codes','effective_target_codes','lifecycle_addition_codes',
                'retained_history_codes','legacy_preservation_codes','quarantine_symbols'):
        if old.get(key)!=snapshot.get(key):raise q.QfqGateError('FULL_DAILY_MEMBERSHIP_CHANGED:'+key)
    if set(old['symbols'])!=set(snapshot['symbols']):
        raise q.QfqGateError('FULL_DAILY_SOURCE_SYMBOL_SET_CHANGED')
    config=json.loads(q._source(snapshot.get('research_cache_configuration'),
                               owner='full daily current source configuration').read_text())
    sync=json.loads(q._source(config.get('prequery_sync_ref'),owner='full daily current sync receipt').read_text())
    official_ref=sync.get('official_daily_source',{}).get('input_ref')
    official=json.loads(q._source(official_ref,owner='full daily official input').read_text())
    if (str(sync.get('target_date'))!=str(target) or str(official.get('target_date'))!=str(target)
            or official.get('calendar')!=value.get('calendar')
            or official.get('calendar_adapter')!=value.get('calendar_adapter')):
        raise q.QfqGateError('FULL_DAILY_CALENDAR_NOT_BOUND_TO_SOURCE')
    calendar=q._source(value.get('calendar'),owner='full daily trading calendar')
    calendar_adapter=q._source(value.get('calendar_adapter'),owner='full daily trading calendar adapter')
    module=q._load(calendar_adapter,value['calendar_adapter']['sha256'],'qfq_full_daily_calendar')
    current_calendar=module.load_market_calendar(calendar)
    states=module.resolve_market_states(current_calendar,str(target))
    if states.get('a_share') not in {module.TradingDayState.FULL_TRADING_DAY,module.TradingDayState.HALF_TRADING_DAY_AM}:
        raise q.QfqGateError('FULL_DAILY_TARGET_NOT_A_TRADING_DAY')
    if target>previous and module.previous_session(current_calendar,str(target),market='a_share')!=str(previous):
        raise q.QfqGateError('FULL_DAILY_SKIPPED_SESSION_UNBOUND')
    changed={};unchanged=[]
    for code,item in sorted(snapshot['symbols'].items()):
        old_item=old['symbols'][code]
        if q._same_asof_stock_dependencies(old_item)!=q._same_asof_stock_dependencies(item):
            changed[code]={'reason':'SOURCE_OR_ADJUSTMENT_DEPENDENCIES_CHANGED'}
            continue
        if target>previous:
            raw=q.resolved_raw_history(code,item,target,driver)
            if bool(raw.trade_date.le(target).any()) and int(raw.loc[raw.trade_date.le(target),'trade_date'].max())>previous:
                changed[code]={'reason':'NEW_OBSERVED_BAR_AFTER_BASELINE'}
                continue
        unchanged.append(code)
    return {'schema':'a_share_kb_daily_continuation_v1','binding_ref':ref,
        'baseline_generation_id':old_receipt['generation_id'],'baseline_input_sha256':old_receipt['input_sha256'],
        'baseline_snapshot':old_snapshot_ref,'baseline_receipt':old_receipt_ref,
        'baseline_roles':value['baseline_roles'],'baseline_target':previous,'codes':changed,
        'unchanged_codes':unchanged,'calendar':value['calendar'],'calendar_adapter':value['calendar_adapter'],
        'kernel_sha256':computation_semantics_sha(old_source,q),
        'sidecar_policy':'PRESERVE_BOUND_PRIOR_IDENTITY_NO_CROSS_GENERATION_N_RESUME',
        'historical_PIT':False,**q.FLAGS}
