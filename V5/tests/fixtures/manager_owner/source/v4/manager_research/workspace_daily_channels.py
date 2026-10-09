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
        'sha256','run_id','evidence_run_id','published_at','available_at','generated_at'}
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
    diagnostics = _object(value.get('selection_diagnostics'))
    membership = _object(diagnostics.get('membership'))
    focus_inputs = _object(_object(value.get('owner_chain')).get('focus_inputs'))
    connect = _base('HK_CONNECT', bindings, owner='EXISTING_WORKSPACE_FOCUS_AND_TARGET_HK_UNIVERSE_V2',
        dependencies=['TARGET_HK_UNIVERSE_V2','EXISTING_FOCUS_OWNERS'], **execution)
    connect['data_date']=_object(value.get('plan_context')).get('market_session')
    connect['input_identity']=membership.get('identity')
    from .connect_selection import _scope_error, filter_cards
    authority_error = _scope_error(membership, target)
    focus=set(value.get('focus_symbols', []))
    if authority_error is None:
        original_focus=[r for r in _rows(value.get('stocks')) if r.get('symbol') in focus
                        and r.get('connect_eligibility')=='VERIFIED_TARGET_UNIVERSE']
        verified_focus, rejected_focus=filter_cards(original_focus,membership,target_date=target)
        connect['rows']=[dict(symbol=r['symbol'],name=r.get('name') or r['symbol'],
            reason='；'.join(_texts(r.get('why_watch'))) or None, selection_status='SELECTED',
            data_date=connect['data_date'], target_trade_date=target, source_refs=_references(r.get('evidence',[])),
            run_id=execution['run_id'],generated_at=execution['generated_at'],product_sha256=execution['product_sha256'])
            for r in verified_focus]
        # General selection diagnostics also carry research-attention gaps.
        # Use the producer's channel-local dependency list here so a peripheral
        # US gap cannot change HK Connect readiness.
        connect['gaps']=sorted(set([*_texts(diagnostics.get('connect_gaps')),*_texts(focus_inputs.get('gaps')),
                                   *(r['reason'] for r in rejected_focus)]))
        if focus_inputs.get('status') != 'READY' and not focus_inputs.get('gaps'):
            connect['gaps'].append('FOCUS_OWNER_INPUT_STATUS_NOT_VERIFIED')
        incomplete=bool(connect['gaps'] or diagnostics.get('status') not in {'READY','READY_EMPTY'})
        connect['status']='PARTIAL' if incomplete else 'READY' if connect['rows'] else 'READY_EMPTY'
        if connect['rows'] or not incomplete:
            connect['candidate_count']=len(connect['rows'])
    else:
        connect['gaps']=sorted(set([*_texts(membership.get('gaps')),authority_error]))
    connect['authority']=deepcopy(membership)

    screen = _object(value.get('market_screen'))
    oversold = _base('OVERSOLD', bindings, owner='EXISTING_HK_02_REBOUND_TWO_GATE_SCREEN',
        dependencies=['COMPLETED_HK_02_PANEL','PRIOR_60_COMPLETE_SESSIONS','VERIFIED_VOLUME_PROVENANCE'], **execution)
    oversold.update(data_date=screen.get('verified_session'),input_identity=screen.get('input_identity'),
        gaps=_texts(screen.get('gaps')),data_context=deepcopy(screen.get('data_context')))
    if screen.get('status') in {'READY','READY_WITH_GAPS'} and screen.get('input_identity'):
        for key, classification in [('strict','SELECTED'),('near','NEAR_CONDITION')]:
            for row in _rows(screen.get(key)):
                symbol=canonical_symbol(row.get('code') or row.get('symbol'))
                if symbol is None:
                    continue
                oversold['rows'].append(dict(symbol=symbol,name=row.get('name') or symbol,
                    reason=row.get('reason_for_group') or row.get('reason_for_selection') or row.get('reason_for_near') or row.get('reason') or None,
                    selection_status=classification,data_date=screen.get('verified_session'),target_trade_date=target,
                    source_refs=_references(row.get('source_refs',[])),run_id=execution['run_id'],
                    generated_at=execution['generated_at'],product_sha256=execution['product_sha256']))
        oversold['pending_count']=len(_rows(screen.get('pending')))+len(_rows(screen.get('screen_unresolved')))
        incomplete=bool(oversold['pending_count'] or oversold['gaps'])
        oversold['status']='PARTIAL' if incomplete else 'READY' if oversold['rows'] else 'READY_EMPTY'
        selected=sum(r['selection_status']=='SELECTED' for r in oversold['rows'])
        oversold['candidate_count']=selected if selected or not incomplete else None
        oversold['watch_count']=sum(r['selection_status']=='NEAR_CONDITION' for r in oversold['rows'])
    if not oversold['gaps'] and oversold['status']=='CANNOT_CONFIRM':
        oversold['gaps']=['SCREEN_INPUT_OR_AUTHORITY_UNVERIFIED']
    oversold['authority']=deepcopy(screen.get('authority'))
    return dict(schema_version='v4.manager_research.daily_channels.v1',date_bindings=bindings,
        channels=[announcement,connect,oversold],selection_rules_unchanged=True,**FLAGS)
