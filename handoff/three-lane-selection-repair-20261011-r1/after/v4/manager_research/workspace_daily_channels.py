"""Read-only presentation of existing selections; no new producer or rules."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import re
from typing import Any, Mapping

from .workspace_projection import FLAGS, HK, canonical_symbol, digest, timestamp


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _rows(value: Any) -> list[Mapping[str, Any]]:
    return [v for v in value if isinstance(v, Mapping)] if isinstance(value, list) else []


def _texts(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    return [v for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _references(value: Any) -> list[dict[str, Any]]:
    # Keep source pointers in the first-screen projection. Original bodies and
    # nested evidence remain in their existing owner fields, not duplicated.
    keys = {'card_id','art_code','title','owner','source','source_ref','source_date',
        'product_sha256','source_sha256','source_manifest_sha256','artifact_sha256',
        'sha256','run_id','evidence_run_id','published_at','available_at','generated_at',
        'payload_path','payload_sha256','manifest_path','manifest_sha256',
        'receipt_path','receipt_sha256','artifact_path','path','pointer'}
    return [{key:item for key,item in row.items() if key in keys
             and (item is None or isinstance(item,(str,int,float,bool)))} for row in _rows(value)]


def _checks(products: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{key:deepcopy(item) for key,item in product.items() if key!='research_references'}
            for product in products]


def _execution(value: Mapping[str, Any]) -> dict[str, Any]:
    product, attempt = _object(value.get('plan_product')), _object(value.get('workspace_plan_attempt'))
    try:
        from .workspace import validate_attempt
        attempt = validate_attempt(attempt, value.get('target_trade_date'))
    except (ValueError,TypeError,KeyError):
        attempt = {}
    matches = bool(product.get('status') in {'CURRENT','ALREADY_MATERIALIZED','PRESERVED_SCHEDULED_PREOPEN'}
        and product.get('consumed') is True
        and product.get('original_owner') == 'ManagerResearchJobService.refresh_workspace_plan'
        and re.fullmatch(r'[0-9a-f]{64}',str(product.get('sha256','')))
        and timestamp(product.get('generated_at')) is not None
        and product.get('run_id') and product.get('run_id') == attempt.get('run_id')
        and product.get('execution_kind') == attempt.get('execution_kind')
        and attempt.get('target_trade_date') == value.get('target_trade_date')
        and attempt.get('input_identity') == value.get('input_identity')
        and attempt.get('owner') == 'ManagerResearchJobService.refresh_workspace_plan'
        and attempt.get('state') in {'SUCCEEDED','SUCCEEDED_EMPTY','PARTIAL'})
    return dict(run_id=product.get('run_id') if matches else None,
        product_sha256=product.get('sha256') if matches else None,
        generated_at=product.get('generated_at') if matches else None,
        execution_kind=attempt.get('execution_kind') if matches else 'READ_ONLY_EXISTING_OWNER_REPLAY',
        attempt_status=attempt.get('state') if matches else 'NOT_VERIFIED',
        # Scheduler trigger + process/API/page readback is a separate acceptance
        # record. Even a valid SCHEDULED_PREOPEN plan alone does not prove it.
        natural_run_verified=False)


def _base(channel: str, bindings: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    return dict(channel=channel, target_trade_date=bindings.get('plan_date'),
        selection_date=bindings.get('selection_date'),
        announcement_date=bindings.get('announcement_date'),
        rows=[], candidate_count=None, pending_count=None, gaps=[],
        dependencies=[], status='CANNOT_CONFIRM', run_id=None, generated_at=None,
        product_sha256=None, input_identity=None, data_date=None,
        execution_kind='READ_ONLY_EXISTING_OWNER_REPLAY', natural_run_verified=False,
        **FLAGS) | extra


def _oversold_channel(value: Mapping[str, Any], bindings: Mapping[str, Any],
                      execution: Mapping[str, Any]) -> dict[str, Any]:
    screen = _object(value.get('market_screen'))
    ledger = _object(_object(value.get('research_attention')).get('research_selection'))
    result = _base('OVERSOLD', bindings, owner='build_research_selection_ledger',
        dependencies=['COMPLETED_HK_02_PANEL','PRIOR_60_COMPLETE_SESSIONS',
                      'VERIFIED_VOLUME_PROVENANCE','ORIGINAL_RESEARCH_SELECTION_LEDGER'], **execution)
    result.update(data_date=screen.get('verified_session'), source_status=ledger.get('source_status', screen.get('status')),
        source_input_identity=screen.get('input_identity'),
        decision_ledger_ref='research_attention.research_selection',
        input_diagnostics_ref='rebound_input_diagnostics',
        formal_selection_input=False, as_of_claim='NONE_RETROSPECTIVE_RESEARCH',
        data_context=deepcopy(screen.get('data_context')), authority=deepcopy(screen.get('authority')),
        gaps=sorted(set([*_texts(screen.get('gaps')), *_texts(ledger.get('gaps'))])))
    # Consume the original complete decision ledger. Its strict/near rows may
    # still be UNRESOLVED (missing priority, duplicate, bad source, or date).
    # Raw screen groups cannot substitute for this owner verdict.
    identity_fields = ('target_trade_date','source_date','source_input_identity',
                       'source_rule_version','decisions','coverage','gaps')
    bound = bool(ledger.get('schema_version') == 'v4.manager_research.selection_ledger.v1'
        and ledger.get('target_trade_date') == bindings.get('plan_date')
        and ledger.get('source_date') == screen.get('verified_session')
        and ledger.get('source_input_identity') == screen.get('input_identity')
        and ledger.get('source_rule_version') == screen.get('rule_version')
        and ledger.get('formal_selection_input') is False
        and ledger.get('as_of_claim') == 'NONE_RETROSPECTIVE_RESEARCH'
        and isinstance(ledger.get('decision_identity'), str)
        and ledger['decision_identity'] == digest({key:ledger.get(key) for key in identity_fields}))
    if not bound or ledger.get('status') not in {'READY','READY_WITH_GAPS'}:
        result['gaps'] = sorted(set([*result['gaps'], 'ORIGINAL_RESEARCH_SELECTION_LEDGER_UNVERIFIED']))
        return result
    coverage = _object(ledger.get('coverage'))
    decisions = _rows(ledger.get('decisions'))
    selected = [row for row in decisions if row.get('decision_status') in {'SELECTED','NEAR_WATCH'}]
    source_rows = [(group,row) for group in ('strict','near','pending','excluded','screen_unresolved')
                   for row in _rows(screen.get(group))]
    result.update(input_identity=ledger['decision_identity'], coverage=deepcopy(coverage),
        pending_count=coverage.get('unresolved_count'))
    for row in selected:
        indexes = row.get('source_row_indexes')
        group, original = (source_rows[indexes[0]-1] if isinstance(indexes,list) and len(indexes)==1
            and type(indexes[0]) is int and 0 < indexes[0] <= len(source_rows) else (None,{}))
        source_diagnostics = ({key:deepcopy(original[key]) for key in (
            'history_numeric_status','history_raw_status','history_raw_error','volume_source',
            'volume_unit_status','volume_scale_applied','volume_relative_comparability_status','volume_provenance')
            if key in original} if original.get('code') == row['symbol'] and group == row.get('source_group')
                and str(original.get('target_monday')) == bindings.get('plan_date')
                and str(original.get('verified_session')) == ledger.get('source_date') else {})
        result['rows'].append(dict(symbol=row['symbol'],name=row['name'],reason=row['decision_reason'],
            selection_status='SELECTED' if row['decision_status']=='SELECTED' else 'NEAR_CONDITION',
            data_date=ledger['source_date'],target_trade_date=bindings.get('plan_date'),
            source_refs=_references(row.get('source_refs')),source_group=row.get('source_group'),
            source_row_indexes=deepcopy(row.get('source_row_indexes')),
            source_input_identity=row.get('source_input_identity'),
            decision_reason_code=row.get('decision_reason_code'),
            research_priority=deepcopy(row.get('research_priority')),
            source_metrics=deepcopy(row.get('source_metrics')),
            source_diagnostics=source_diagnostics,
            formal_selection_input=False,as_of_claim='NONE_RETROSPECTIVE_RESEARCH',
            run_id=execution['run_id'],generated_at=execution['generated_at'],
            product_sha256=execution['product_sha256']))
    incomplete = ledger['status'] != 'READY' or bool(result['gaps'] or result['pending_count'])
    count_selected = coverage.get('selected_count')
    result.update(status='PARTIAL' if incomplete else 'READY' if selected else 'READY_EMPTY',
        candidate_count=count_selected if count_selected or not incomplete else None,
        watch_count=coverage.get('near_watch_count'))
    return result


def _hk_stage_channel(value: Mapping[str, Any], bindings: Mapping[str, Any],
                       execution: Mapping[str, Any]) -> dict[str, Any]:
    """Read an already verified HK Stage selection; never execute or re-rank."""
    from contracts.stages import STAGE_DEFINITIONS
    from .connect_selection import _scope_error, filter_cards
    target, stage_id = bindings.get('plan_date'), 'STAGE_0935_0940'
    stage = _object(value.get('stage_selection'))
    # The existing API retains canonical, untruncated rows under this key.
    markets = _object(stage.get('selection_markets', stage.get('markets')))
    market = _object(markets.get('HK_CONNECT'))
    membership = _object(_object(value.get('selection_diagnostics')).get('membership'))
    result = _base('HK_CONNECT', bindings, owner='StageSelectionConsumer/SelectionStore',
        dependencies=['TARGET_HK_UNIVERSE_V2','EXACT_DATE_D1_TOP100','ORIGINAL_STAGE_SELECTION_TRIO',
                      'ORIGINAL_STAGE_EXECUTION_RECEIPT'], **execution)
    result.update(authority=deepcopy(membership), stage_selection_ref='stage_selection',
        source_status=market.get('source_status'), formal_selection_input=False,
        source_selection={key:deepcopy(market.get(key)) for key in (
            'trade_date','stage_id','market','status','selection_status','run_id','artifact_id',
            'selection_run_id','algorithm_id','algorithm_sha256','raw_artifact_sha256',
            'selection_artifact_sha256','selection_manifest_sha256','selection_receipt_sha256',
            'selection_manifest_receipt_verified','source_status','source_evidence',
            'requested_rows','source_rows','selected_rows','missing_symbols','cannot_confirm')})
    gaps = result['gaps']
    scope_error = _scope_error(membership, target)
    if scope_error:
        gaps.extend([scope_error, *_texts(membership.get('gaps'))])
    calendar = _object(membership.get('calendar_applicability'))
    if calendar.get('status') != 'APPLICABLE' or calendar.get('target_trade_date') != target:
        gaps.append('HK_STAGE_TARGET_CONNECT_CALENDAR_NOT_APPLICABLE_OR_UNVERIFIED')
    if (stage.get('schema_version') != 'stage_center.selection_consumer.v1'
            or stage.get('response_source') != 'SHARED_STAGE_CENTER'
            or any(stage.get(key) is not expected for key, expected in FLAGS.items())
            or stage.get('write_performed') is not False
            or stage.get('trade_date') != target or market.get('trade_date') != target
            or stage.get('stage_id') != stage_id or market.get('stage_id') != stage_id
            or market.get('market') != 'HK_CONNECT'):
        gaps.append('HK_ORIGINAL_STAGE_SELECTION_IDENTITY_UNVERIFIED')
    sha = lambda raw: isinstance(raw, str) and re.fullmatch(r'[0-9a-f]{64}', raw) is not None
    run = market.get('run_id')
    if (not isinstance(run, str) or not re.fullmatch(r'run-[0-9a-f]{24}', run)
            or market.get('artifact_id') != 'selection-'+str(run)[4:]
            or market.get('selection_run_id') != run
            or market.get('selection_manifest_receipt_verified') is not True
            or not all(sha(market.get(key)) for key in ('algorithm_sha256','raw_artifact_sha256',
                'selection_artifact_sha256','selection_manifest_sha256','selection_receipt_sha256'))):
        gaps.append('HK_STAGE_SELECTION_TRIO_UNVERIFIED')
    evidence = _texts(market.get('source_evidence'))
    d1_shas = [item.partition('=')[2] for item in evidence
               if item.partition('=')[0] in {'hk_d1_sha256','hk_d1_json_sha256','hk_d1_binding_sha256'}]
    if ('hk_d1_membership=exact_date_top100' not in evidence
            or 'hk_d1_status=STRICT_0_2_READY' not in evidence
            or not d1_shas or not all(sha(item) for item in d1_shas) or len(set(d1_shas)) != 1):
        gaps.append('HK_STAGE_EXACT_D1_TOP100_IDENTITY_UNVERIFIED')
    original_rows = market.get('rows')
    rows = _rows(original_rows)
    if (not isinstance(original_rows, list) or len(rows) != len(original_rows)
            or type(market.get('selected_rows')) is not int or market['selected_rows'] != len(rows)
            or type(market.get('requested_rows')) is not int or market['requested_rows'] != 100
            or type(market.get('source_rows')) is not int or not 0 < market['source_rows'] <= 100
            or market.get('selected_rows',0) > market.get('source_rows',0)
            or market.get('status') != market.get('selection_status')
            or market.get('status') not in {'READY','READY_EMPTY','PARTIAL_WITH_ROWS'}
            or market.get('source_status') not in {'READY','READY_EMPTY','PARTIAL_WITH_ROWS'}
            or market.get('status') == 'READY_EMPTY' and bool(rows)
            or market.get('status') == 'READY' and not rows
            or not isinstance(market.get('missing_symbols'), list)
            or not isinstance(market.get('cannot_confirm'), list)):
        gaps.append('HK_STAGE_ORIGINAL_INPUT_OR_SELECTION_COUNT_UNVERIFIED')
    codes, ranks = set(), set()
    for order, row in enumerate(rows, 1):
        code, rank = row.get('code'), row.get('rank')
        if (canonical_symbol(code) != code or code is None or code in codes
                or 'symbol' in row and row['symbol'] != code
                or type(rank) is not int or rank <= 0 or str(rank) in ranks
                or type(row.get('order')) is not int or row['order'] != order
                or row.get('formal_eligible') is not False or row.get('action_level') != 'NO_BUY'
                or any(key in row and row[key] is not expected for key, expected in FLAGS.items())
                or any(key in row and row[key] != expected for key, expected in
                       (('trade_date',target),('stage_id',stage_id),('market','HK_CONNECT')))):
            gaps.append('HK_STAGE_ORIGINAL_ROW_IDENTITY_OR_SAFETY_UNVERIFIED')
        codes.add(str(code)); ranks.add(str(rank))
    # Recovery artifacts can live at the ordinary key. Keep the original
    # evidence visible, but do not substitute them for this ordinary lane.
    source_execution = _object(stage.get('execution_evidence'))
    source_nodes = (stage, market, source_execution, *rows)
    markers = [*evidence, *_texts(market.get('cannot_confirm')),
        *[str(node.get(key) or '') for node in source_nodes
          for key in ('selection_mode','due_status','attempt_mode','mode','recovery_mode',
                      'source_mode','status','second_filter_status')],
        *[item for row in rows for key in ('lane_evidence','candidate_lanes')
          for item in _texts(row.get(key))]]
    recovery_markers = ('BACKFILL','LATE_CATCHUP_REPLAY','PRIOR_CONNECT_DATE_FALLBACK',
        'HK_SECURITIES_OPEN_HK_CONNECT_CLOSED','D1_PRESELECT_REFERENCE','WAITING_0920_SECOND_FILTER',
        'historical_observation_contract=', 'hk_afterfact_contract=', 'substitute_kind=',
        'temporal_cutoff_safe=false', 'temporal_cutoff_safe=False')
    if (any(any(marker in item for marker in recovery_markers) for item in markers)
            or any(node.get('backfill_run_id') or node.get('backfill_run_ids') or node.get('recovery_provenance')
                   or node.get('temporal_cutoff_safe') is False for node in source_nodes)):
        gaps.append('HK_STAGE_RECOVERY_OR_PRIOR_OBSERVATION_NOT_ORDINARY_SELECTION')
    cutoff = timestamp(_object(value.get('plan_context')).get('research_cutoff'))
    try:
        end = datetime.strptime(str(target)+' '+STAGE_DEFINITIONS[stage_id]['cutoff'], '%Y%m%d %H:%M:%S').replace(tzinfo=HK)
        if cutoff is None or cutoff < end:
            gaps.append('HK_STAGE_AFTER_RESEARCH_CUTOFF_OR_CUTOFF_UNVERIFIED')
    except (ValueError, KeyError):
        gaps.append('HK_STAGE_READ_WINDOW_UNVERIFIED')
    if gaps:
        result['gaps'] = sorted(set(gaps))
        return result
    result['data_date'] = target
    result['input_identity'] = digest([membership['identity'],result['source_selection']])
    execution_market = _object(_object(source_execution.get('markets')).get('HK_CONNECT'))
    declared = _object(execution_market.get('declared_identity'))
    execution_bound = (source_execution.get('trade_date') == target and source_execution.get('stage_id') == stage_id
        and sha(source_execution.get('observed_sha256'))
        and execution_market.get('selection_binding') == 'BOUND_TO_VERIFIED_SELECTION'
        and all(declared.get(key) == market.get(key) for key in ('run_id','artifact_id','algorithm_sha256','raw_artifact_sha256'))
        and type(execution_market.get('selected_rows')) is int
        and execution_market['selected_rows'] == market['selected_rows'])
    result['execution_selection_reference'] = 'BOUND' if execution_bound else 'CANNOT_CONFIRM'
    result['source_execution_evidence_ref'] = 'stage_selection.execution_evidence'
    if not execution_bound:
        gaps.append('HK_STAGE_EXECUTION_SELECTION_BINDING_UNVERIFIED')
    admitted, rejected = filter_cards(rows, membership, target_date=target)
    gaps.extend(row['reason'] for row in rejected)
    gaps.extend(_texts(market.get('cannot_confirm')))
    if market['source_rows'] != 100 or market.get('missing_symbols'):
        gaps.append('HK_STAGE_D1_INPUT_COVERAGE_INCOMPLETE')
    source_ref = dict(owner='stage_center.SelectionStore',run_id=run,
        payload_sha256=market['selection_artifact_sha256'],manifest_sha256=market['selection_manifest_sha256'],
        receipt_sha256=market['selection_receipt_sha256'],raw_artifact_sha256=market['raw_artifact_sha256'],
        algorithm_sha256=market['algorithm_sha256'])
    for row in admitted:
        reasons = _texts(row.get('reason')) or _texts(row.get('lane_evidence'))
        result['rows'].append(dict(symbol=row['code'],name=row.get('name') or row.get('stock_name') or row['code'],
            reason='；'.join(reasons) or None,selection_status='SELECTED',rank=row['rank'],order=row.get('order'),
            formal_eligible=row['formal_eligible'],action_level=row['action_level'],trade_status=row.get('trade_status'),
            data_date=target,target_trade_date=target,source_refs=[deepcopy(source_ref)],
            source_row_ref='stage_selection.selection_markets.HK_CONNECT.rows',
            run_id=execution['run_id'],generated_at=execution['generated_at'],product_sha256=execution['product_sha256']))
    incomplete = bool(gaps) or market['status'] == 'PARTIAL_WITH_ROWS' or market['source_status'] == 'PARTIAL_WITH_ROWS'
    result.update(status='PARTIAL' if incomplete else 'READY' if admitted else 'READY_EMPTY',
        candidate_count=len(admitted) if admitted or not incomplete else None,
        pending_count=None if incomplete else 0,selection_rejections=rejected,gaps=sorted(set(gaps)))
    return result


def build_daily_channels(value: Mapping[str, Any]) -> dict[str, Any]:
    """Expose stock/reason/date/run without changing owners' rows or ranking."""
    bindings = dict(_object(value.get('date_bindings')))
    target = bindings.get('plan_date') or value.get('target_trade_date')
    bindings.setdefault('plan_date', target)
    bindings.setdefault('selection_date', target)
    publication = str(bindings.get('announcement_date') or '').replace('-', '')
    reviewed = _object(value.get('announcement_reviewed_analysis'))
    products = _rows(reviewed.get('products'))
    exact = [p for p in products if p.get('target_trade_date') == target
        and str(p.get('publication_date') or '').replace('-', '') == publication]
    consumed = {p.get('product_sha256'):p for p in exact if p.get('status') == 'CONSUMED'}
    announcement = _base('ANNOUNCEMENT', bindings, owner='ManagerResearchJobService.import_announcement_analysis',
        data_date=publication or None, dependencies=['REGISTERED_REVIEWED_HANDOFF','OWNER_IMPORT_RECEIPT'])
    announcement_rows = []
    for reference in _rows(reviewed.get('research_references')):
        source = consumed.get(reference.get('product_sha256'))
        if source is None or reference.get('target_trade_date') != target or str(reference.get('publication_date') or '').replace('-', '') != publication:
            continue
        symbol = canonical_symbol(reference.get('stock_code'))
        if symbol is None or reference.get('research_status') not in {'SELECTED','CONDITIONAL_WATCH'}:
            continue
        reasons = _texts(reference.get('selection_reasons'))
        if not reasons:
            reasons = [reason for article in _rows(reference.get('article_refs')) for reason in _texts(article.get('reason'))]
        announcement_rows.append(dict(symbol=symbol, name=reference.get('stock_name') or symbol,
            reason='；'.join(dict.fromkeys(reasons)) or None, selection_status=reference['research_status'],
            data_date=publication, target_trade_date=target,
            product_sha256=reference.get('product_sha256'), source_manifest_sha256=reference.get('source_manifest_sha256'),
            run_id=source.get('evidence_run_id'), generated_at=source.get('owner_available_at') or source.get('reviewed_at'),
            source_refs=_references(reference.get('article_refs', []))))
    if consumed:
        assessed=all(p.get('selection_status')=='VERIFIED'
            and type(p.get('not_assessed_stock_count')) is int for p in consumed.values())
        pending=sum(p['not_assessed_stock_count'] for p in consumed.values()) if assessed else None
        incomplete=len(consumed)!=len(exact) or not assessed or bool(pending)
        selected=sum(r['selection_status']=='SELECTED' for r in announcement_rows)
        announcement.update(status='PARTIAL' if incomplete else 'READY',
            rows=announcement_rows, candidate_count=selected if selected or not incomplete else None,
            pending_count=pending,
            watch_count=sum(r['selection_status']=='CONDITIONAL_WATCH' for r in announcement_rows),
            execution_kind='OWNER_IMPORT_TIMING_NOT_CLASSIFIED',
            input_identity=digest(sorted(consumed)),
            product_sha256=next(iter(consumed)) if len(consumed)==1 else None)
        dates=[r['generated_at'] for r in announcement_rows if r['generated_at']]
        announcement['generated_at']=max(dates) if dates else next(iter(consumed.values())).get('owner_available_at')
        announcement['run_id']=next(iter(consumed.values())).get('evidence_run_id') if len(consumed)==1 else None
        if not announcement_rows and announcement['status']=='READY':
            announcement['status']='READY_EMPTY'
    announcement['gaps'] = sorted({gap for p in exact for gap in _texts(p.get('gaps'))})
    if consumed and (not assessed or pending):
        announcement['gaps'].append('ANNOUNCEMENT_SELECTION_NOT_ASSESSED')
    if not exact:
        announcement['gaps']=['ANNOUNCEMENT_EXACT_DATE_PRODUCT_NOT_CONSUMED']
    announcement['product_checks']=_checks(exact)
    announcement['other_product_checks']=_checks([p for p in products if p not in exact])

    execution = _execution(value)
    connect = _hk_stage_channel(value, bindings, execution)

    oversold = _oversold_channel(value, bindings, execution)
    return dict(schema_version='v4.manager_research.daily_channels.v1',date_bindings=bindings,
        channels=[announcement,connect,oversold],selection_rules_unchanged=True,**FLAGS)
