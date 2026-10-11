"""Read-only presentation of existing selections; no new producer or rules."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Mapping

from .workspace_projection import FLAGS, canonical_symbol, digest, timestamp


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
        'receipt_path','receipt_sha256','raw_capture_path','raw_capture_sha256',
        'pointer_path','pointer_sha256','source_root','provider'}
    return [{key:item for key,item in row.items() if key in keys
             and (item is None or isinstance(item,(str,int,float,bool)))} for row in _rows(value)]


def _checks(products: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [{key:deepcopy(item) for key,item in product.items() if key!='research_references'}
            for product in products]


def _execution(value: Mapping[str, Any]) -> dict[str, Any]:
    product = _object(value.get('plan_product'))
    # The latest attempt is runtime status. The immutable product's own
    # verified attempt remains authoritative if a later refresh failed.
    attempt = value.get('workspace_plan_product_attempt', value.get('workspace_plan_attempt'))
    try:
        from .workspace_plan_autorun import owner_plan_readback
        proof = owner_plan_readback(dict(value, workspace_plan_attempt=attempt),
            value.get('target_trade_date'), expected_kind=product.get('execution_kind'),
            allow_preserved_preopen=True)
    except (ValueError,TypeError,KeyError):
        proof = {}
    return dict(run_id=proof.get('run_id'), product_sha256=proof.get('product_sha256'),
        generated_at=proof.get('generated_at'),
        execution_kind=proof.get('execution_kind', 'READ_ONLY_EXISTING_OWNER_REPLAY'),
        attempt_status=proof.get('owner_attempt_state', 'NOT_VERIFIED'),
        owner_attempt_sha256=proof.get('owner_attempt_sha256'),
        # Scheduler trigger + process/API/page readback is a separate acceptance
        # record. Even a valid SCHEDULED_PREOPEN plan alone does not prove it.
        natural_run_verified=False)


def _oversold(value: Mapping[str, Any], bindings: Mapping[str, Any]) -> dict[str, Any]:
    """Project the original complete decision ledger, not its strict bucket."""
    screen = _object(value.get('market_screen'))
    attention = _object(value.get('research_attention'))
    ledger = _object(attention.get('research_selection'))
    execution = _execution(value)
    result = _base('OVERSOLD', bindings,
        owner='v4.manager_research.research_attention.build_research_selection_ledger',
        dependencies=['COMPLETED_HK_02_PANEL', 'PRIOR_60_COMPLETE_SESSIONS',
                      'VERIFIED_VOLUME_PROVENANCE', 'ORIGINAL_RESEARCH_SELECTION_LEDGER', 'SAVED_OWNER_PLAN'],
        **execution)
    result.update(data_date=screen.get('verified_session'), input_identity=screen.get('input_identity'),
        data_context=deepcopy(screen.get('data_context')), authority=deepcopy(screen.get('authority')),
        decision_identity=None, coverage=None, formal_selection_input=False)
    if not ledger:
        result['gaps'] = sorted(set([*_texts(screen.get('gaps')), 'ORIGINAL_RESEARCH_SELECTION_LEDGER_MISSING']))
        return result
    # Recheck with the existing ledger function and actual priority cards; no
    # duplicate decision rules, new ranking, or new selection producer.
    from .research_attention import build_research_selection_ledger
    verified = build_research_selection_ledger(screen, _rows(attention.get('cards')), bindings.get('plan_date'))
    if dict(ledger) != verified:
        result['gaps'] = ['ORIGINAL_RESEARCH_SELECTION_LEDGER_MISMATCH']
        return result
    result.update(decision_identity=ledger.get('decision_identity'),
        coverage=deepcopy(ledger.get('coverage')), gaps=_texts(ledger.get('gaps')))
    if ledger.get('status') not in {'READY', 'READY_WITH_GAPS'}:
        result['gaps'] = sorted(set([*result['gaps'], 'ORIGINAL_RESEARCH_SELECTION_LEDGER_NOT_READY']))
        return result
    for decision in _rows(ledger.get('decisions')):
        status = decision.get('decision_status')
        if status not in {'SELECTED', 'NEAR_WATCH'}:
            continue
        result['rows'].append(dict(symbol=decision['symbol'], name=decision['name'],
            reason=decision.get('decision_reason'), decision_reason_code=decision.get('decision_reason_code'),
            selection_status='SELECTED' if status == 'SELECTED' else 'NEAR_CONDITION',
            research_priority=deepcopy(decision.get('research_priority')),
            source_metrics=deepcopy(decision.get('source_metrics')),
            source_refs=_references(decision.get('source_refs')), data_date=ledger['source_date'],
            target_trade_date=ledger['target_trade_date'], run_id=result['run_id'],
            generated_at=result['generated_at'], product_sha256=result['product_sha256']))
    coverage = ledger['coverage']
    result.update(pending_count=coverage['unresolved_count'], watch_count=coverage['near_watch_count'])
    if execution['attempt_status'] == 'NOT_VERIFIED':
        result['gaps'].append('RESEARCH_SELECTION_OWNER_PLAN_NOT_VERIFIED')
    incomplete = bool(result['gaps'] or result['pending_count'] or ledger['status'] != 'READY')
    result['status'] = 'PARTIAL' if incomplete else 'READY' if result['rows'] else 'READY_EMPTY'
    selected = coverage['selected_count']
    result['candidate_count'] = selected if selected or not incomplete else None
    return result


def _base(channel: str, bindings: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    return dict(channel=channel, target_trade_date=bindings.get('plan_date'),
        selection_date=bindings.get('selection_date'),
        announcement_date=bindings.get('announcement_date'),
        rows=[], candidate_count=None, pending_count=None, gaps=[],
        dependencies=[], status='CANNOT_CONFIRM', run_id=None, generated_at=None,
        product_sha256=None, input_identity=None, data_date=None,
        execution_kind='READ_ONLY_EXISTING_OWNER_REPLAY', natural_run_verified=False,
        **FLAGS) | extra


def stage_selection_readback(stage: Mapping[str, Any]) -> dict[str, Any]:
    """Preserve the existing canonical market, never the capped UI alias."""
    markets = stage.get('selection_markets') if 'selection_markets' in stage else stage.get('markets')
    return {key: deepcopy(stage[key]) for key in (
        'schema_version', 'response_source', 'trade_date', 'stage_id',
        'execution_evidence', 'write_performed', *FLAGS) if key in stage} | {
        'markets': {'HK_CONNECT': deepcopy(_object(markets).get('HK_CONNECT'))}}


def _hk_connect(value: Mapping[str, Any], bindings: Mapping[str, Any]) -> dict[str, Any]:
    """Show the saved native Stage selection without inventing execution proof.

    The supplied execution-declaration contract cannot establish availability
    or natural execution. Its reference binding remains a diagnostic, separate
    from the original SelectionStore trio. Missing time cannot qualify PIT.
    """
    original = _object(value.get('stage_selection_readback'))
    native = _object(_object(original.get('markets')).get('HK_CONNECT'))
    membership = _object(_object(value.get('selection_diagnostics')).get('membership'))
    result = _base('HK_CONNECT', bindings, owner='StageSelectionConsumer/SelectionStore',
        dependencies=['TARGET_HK_UNIVERSE_V2', 'ORIGINAL_STAGE_SELECTION_TRIO', 'ORIGINAL_STAGE_EXECUTION_EVIDENCE'])
    result.update(authority=deepcopy(membership), stage_id=original.get('stage_id'),
        source_result=deepcopy(native), execution_evidence=deepcopy(original.get('execution_evidence')))
    if not native:
        result['gaps'] = ['HK_ORIGINAL_STAGE_SELECTION_NOT_AVAILABLE']
        return result
    target = bindings.get('plan_date')
    if (original.get('schema_version') != 'stage_center.selection_consumer.v1'
            or original.get('response_source') != 'SHARED_STAGE_CENTER'
            or any(original.get(key) is not expected for key, expected in FLAGS.items())
            or original.get('trade_date') != target or native.get('trade_date') != target
            or native.get('stage_id') != original.get('stage_id') or native.get('market') != 'HK_CONNECT'):
        result['gaps'] = ['HK_ORIGINAL_STAGE_DATE_OR_MARKET_MISMATCH']
        return result
    evidence = _texts(native.get('source_evidence'))
    if (native.get('selection_mode') == 'BACKFILL' or native.get('backfill_run_id')
            or any(marker in evidence for marker in ('selection_mode=BACKFILL',
                'recovery_mode=HISTORICAL_BACKFILL', 'HISTORICAL_BACKFILL',
                'substitute_kind=HK_0930_0935_FOR_HK_0925'))):
        result['gaps'] = ['HK_BACKFILL_NOT_DAILY_SELECTION']
        return result
    if (native.get('selection_manifest_receipt_verified') is not True
            or not native.get('run_id') or native.get('run_id') != native.get('selection_run_id')
            or not all(re.fullmatch(r'[0-9a-f]{64}', str(native.get(key, ''))) for key in (
                'selection_manifest_sha256', 'selection_receipt_sha256', 'selection_artifact_sha256',
                'algorithm_sha256', 'raw_artifact_sha256'))):
        result['gaps'] = ['HK_SELECTION_TRIO_NOT_VERIFIED']
        return result
    rows = _rows(native.get('rows'))
    codes = [canonical_symbol(row.get('code')) for row in rows]
    ranks = [row.get('rank') for row in rows]
    if (not isinstance(native.get('rows'), list) or len(rows) != len(native['rows'])
            or type(native.get('selected_rows')) is not int or native['selected_rows'] != len(rows)
            or any(code is None for code in codes) or len(set(codes)) != len(codes)
            or any(type(rank) is not int or rank <= 0 for rank in ranks) or len(set(ranks)) != len(ranks)):
        result['gaps'] = ['HK_ORIGINAL_STAGE_ROW_CONTRACT_INVALID']
        return result
    if _object(value.get('read_context')).get('mode') == 'HISTORICAL_AS_OF':
        result['gaps'] = ['HK_STAGE_AVAILABILITY_AT_CUTOFF_NOT_VERIFIED']
        return result
    from .connect_selection import _scope_error
    authority_error = _scope_error(membership, target)
    if authority_error:
        result['gaps'] = sorted(set([*_texts(membership.get('gaps')), authority_error]))
        return result
    if native.get('selection_status') not in {'READY', 'READY_EMPTY', 'PARTIAL_WITH_ROWS'}:
        result['gaps'] = sorted(set([*_texts(native.get('cannot_confirm')), 'HK_ORIGINAL_STAGE_SELECTION_NOT_READY']))
        return result
    result.update(data_date=native['trade_date'], input_identity=native['raw_artifact_sha256'],
        input_identity_basis='ORIGINAL_RAW_ARTIFACT_SHA256', run_id=native['run_id'],
        product_sha256=native['selection_manifest_sha256'], product_sha256_basis='ORIGINAL_SELECTION_MANIFEST_SHA256',
        selection_artifact_sha256=native['selection_artifact_sha256'],
        selection_receipt_sha256=native['selection_receipt_sha256'],
        execution_kind='EXISTING_STAGE_SELECTION_READBACK', status='PARTIAL',
        gaps=[*_texts(native.get('cannot_confirm')), 'HK_SELECTION_EXECUTION_AND_AVAILABILITY_NOT_VERIFIED'])
    allowed = set(membership.get('codes') or [])
    for row, symbol in zip(rows, codes):
        if symbol not in allowed:
            result['gaps'].append('NOT_IN_TARGET_HK_CONNECT_UNIVERSE:' + symbol)
            continue
        result['rows'].append({key: deepcopy(row.get(key)) for key in (
            'rank', 'order', 'source_mode', 'formal_eligible', 'action_level', 'trade_status', 'lane_evidence')} | dict(
            symbol=symbol, name=row.get('name') or row.get('stock_name') or symbol,
            reason='；'.join(_texts(row.get('lane_evidence'))) or None,
            selection_status='SELECTED', data_date=native['trade_date'], target_trade_date=target,
            run_id=result['run_id'], generated_at=None, product_sha256=result['product_sha256'],
            source_refs=[dict(owner='SelectionStore', run_id=result['run_id'],
                manifest_sha256=result['product_sha256'], artifact_sha256=native['selection_artifact_sha256'],
                receipt_sha256=native['selection_receipt_sha256'], source_sha256=native['raw_artifact_sha256'])]))
    # A positive saved row count is known. Zero completion requires the missing
    # execution/availability contract, so never convert an empty read into 0.
    result['candidate_count'] = len(result['rows']) or None
    result['gaps'] = sorted(set(result['gaps']))
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

    connect = _hk_connect(value, bindings)

    oversold = _oversold(value, bindings)
    return dict(schema_version='v4.manager_research.daily_channels.v1',date_bindings=bindings,
        channels=[announcement,connect,oversold],selection_rules_unchanged=True,**FLAGS)
