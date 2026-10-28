"""Original manager-service integration: read existing owners; record real refreshes.

GET does not create receipts, collect data or run a producer. The existing
catalyst refresh is still the only catalyst producer. Journals below its store
record actual MANUAL_REFRESH attempts, never fabricated historical/natural runs.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Mapping
from uuid import uuid4
from .existing_materials import read_existing_materials
from .workspace_discovery import read_discovery, read_material_discovery
from .workspace_plan import plan_context, read_plan_quotes, read_rebound_screen
from .workspace_projection import FLAGS, HK, build_workspace, date_token, digest, timestamp
from .workspace_identity import (INPUT_IDENTITY_SCHEMA, semantic_digest, identity_component,
    input_identity_diagnostics)
from .workspace_read_control import (
    WorkspaceReadError,
    phase,
    count,
    checkpoint,
    project,
    READ_CONTRACT,
    contract_identity,
)

ATTEMPT_SCHEMA = 'v4.manager_research.workspace_attempt.v1'
_ERROR_TYPES = (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError, WorkspaceReadError)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def _attach_daily_channels(value: dict) -> dict:
    """Attach a read-only summary of existing owner products and bindings."""
    from .workspace_daily_channels import build_daily_channels
    value['daily_channels'] = build_daily_channels(value)
    return value


def _daily_mapping_plan_reference(service: Any, date: str,
                                  context: Mapping[str, Any], *,
                                  current_us_market: Mapping[str, Any] | None = None) -> tuple[dict, dict, list[str]]:
    """Bind a saved US mapping to this plan only when it precedes its cutoff."""
    from .us_mapping_research import read_workspace_mapping
    mapping_read = read_workspace_mapping(service, date)
    daily = mapping_read.get('daily_run') if isinstance(mapping_read, Mapping) else None
    if isinstance(daily, dict) and isinstance(current_us_market, Mapping):
        current_identity = current_us_market.get('source_identity')
        daily_identity = daily.get('source_identity')
        current_sha = current_identity.get('payload_sha256') if isinstance(current_identity, Mapping) else None
        daily_sha = daily_identity.get('payload_sha256') if isinstance(daily_identity, Mapping) else None
        current_session = current_us_market.get('expected_us_session')
        daily_session = daily.get('us_session_date')
        complete_daily = daily.get('status') in {'COMPLETED', 'VALID_EMPTY'}
        exact_current_identity = (
            isinstance(current_sha, str) and re.fullmatch(r'[0-9a-f]{64}', current_sha)
            and isinstance(daily_sha, str) and re.fullmatch(r'[0-9a-f]{64}', daily_sha)
            and isinstance(current_session, str) and isinstance(daily_session, str)
        )
        if not complete_daily:
            compatibility = 'NOT_APPLICABLE'
        elif not exact_current_identity:
            compatibility = 'CANNOT_CONFIRM'
        elif current_session != daily_session or current_sha != daily_sha:
            compatibility = 'STALE_INPUTS_CHANGED'
        else:
            compatibility = 'MATCHED'
        daily['current_context_compatibility'] = compatibility
        daily['current_context_us_session'] = current_session
        daily['current_context_source_payload_sha256'] = current_sha
        if compatibility in {'STALE_INPUTS_CHANGED', 'CANNOT_CONFIRM'}:
            saved_status = daily.get('status')
            saved_matches = daily.get('matches') if isinstance(daily.get('matches'), list) else []
            daily['saved_product_status'] = saved_status
            daily['saved_product_us_session_date'] = daily_session
            daily['saved_product_source_payload_sha256'] = daily_sha
            daily['saved_product_match_count'] = len(saved_matches)
            daily['matches'] = []
            daily['status'] = 'CANNOT_CONFIRM'
            # Preserve the saved product's known count separately, but do not
            # present its coverage counts as measurements of the stale current
            # context.
            coverage = daily.get('coverage')
            if isinstance(coverage, dict):
                coverage['matched_us_symbol_count'] = None
                coverage['matched_hk_relation_count'] = None
            reason = ('STALE_INPUTS_CHANGED' if compatibility == 'STALE_INPUTS_CHANGED'
                      else 'CURRENT_US_MARKET_IDENTITY_UNAVAILABLE')
            daily['gaps'] = sorted(set([*(daily.get('gaps') or []), reason]))
    cutoff = timestamp(context.get('research_cutoff'))
    available = timestamp(daily.get('generated_at')) if isinstance(daily, Mapping) else None
    reference = dict(status='NOT_CONSUMED', target_trade_date=date,
        artifact_sha256=daily.get('artifact_sha256') if isinstance(daily, Mapping) else None,
        run_id=daily.get('run_id') if isinstance(daily, Mapping) else None,
        available_at=daily.get('generated_at') if isinstance(daily, Mapping) else None,
        plan_cutoff=context.get('research_cutoff'),
        matches=deepcopy(daily.get('matches', [])) if isinstance(daily, Mapping) else [],
        reason='DAILY_MAPPING_NOT_MATERIALIZED', RESEARCH_ONLY=True, production_allowed=False,
        buy_gate_updated=False, orders_sent=False)
    identities: list[str] = []
    if isinstance(daily, Mapping) and daily.get('status') in {'COMPLETED', 'VALID_EMPTY'}:
        if cutoff is not None and available is not None and available <= cutoff:
            reference.update(status='CONSUMED', reason=None)
            artifact_sha = reference.get('artifact_sha256')
            if isinstance(artifact_sha, str) and re.fullmatch(r'[0-9a-f]{64}', artifact_sha):
                identities.append(artifact_sha)
        else:
            reference.update(status='NOT_CONSUMED_AFTER_CUTOFF',
                reason='DAILY_MAPPING_NOT_AVAILABLE_AT_PLAN_CUTOFF')
    elif isinstance(daily, Mapping):
        reference.update(status=daily.get('status') or 'CANNOT_CONFIRM',
            reason='DAILY_MAPPING_OWNER_STATUS_NOT_CONSUMABLE')
    return dict(mapping_read), reference, identities


def _announcement_owner_chain(review: Mapping[str, Any]) -> dict:
    """Keep the official HKEX owner and the Eastmoney mirror independently legible."""
    from copy import deepcopy
    official_documents=review.get('official_documents') or []
    east_documents=review.get('eastmoney_hk_documents') or []
    east_capture=review.get('eastmoney_hk_capture') or {}
    east_attempt=review.get('eastmoney_hk_attempt')
    east_readback=None
    if east_capture:
        east_readback=dict(
            status=east_capture.get('readback_status','CANNOT_CONFIRM'),
            owner='ManagerResearchJobService.refresh_announcements',
            source='EASTMONEY_HK',
            target_trade_date=review.get('target_trade_date'),
            run_id=east_capture.get('run_id'),
            product_sha256=east_capture.get('sha256'),
            generated_at=east_capture.get('generated_at'),
            query_cutoff=east_capture.get('query_cutoff'),
            verified_document_count=len(east_documents),
            verified_documents=[dict(event_id=doc.get('event_id'),symbol=doc.get('symbol'),
                art_code=doc.get('art_code'),body_sha256=doc.get('body_sha256'),
                content_page_count=doc.get('content_page_count'),document_sha256=doc.get('document_sha256'),
                available_at=doc.get('available_at'),source_refs=deepcopy(doc.get('source_refs',[])))
                for doc in east_documents])
    official_status=review.get('status','NOT_RUN')
    east_status=review.get('eastmoney_hk_status','NOT_RUN')
    return dict(
        owner='ManagerResearchJobService.refresh_announcements',
        status=official_status,
        status_by_source=dict(HKEX_OFFICIAL=official_status,EASTMONEY_HK=east_status),
        latest_attempt=deepcopy(review.get('attempt')),
        product_identity=deepcopy(review.get('product_identity')),
        coverage=deepcopy(review.get('coverage',{})),
        failure_reasons=deepcopy(review.get('gaps',[])),
        official_hkex=dict(source='HKEX_OFFICIAL',status=official_status,
            attempt=deepcopy(review.get('attempt')),
            product_identity=deepcopy(review.get('product_identity')),
            document_count=len(official_documents)),
        eastmoney_hk=dict(source='EASTMONEY_HK',
            source_identity='EASTMONEY_HK_MIRROR_NOT_HKEX_OFFICIAL',
            status=east_status,attempt=deepcopy(east_attempt),
            source_scope=east_capture.get('source_scope'),document_count=len(east_documents),
            readback_identity=east_readback,
            failure_reasons=deepcopy(review.get('eastmoney_hk_gaps',[]))))


def seal_attempt(row: Mapping[str, Any]) -> dict:
    result = {k: v for k, v in row.items() if k != 'sha256'}
    result['sha256'] = digest(result)
    return result


def validate_attempt(row: Mapping[str, Any], date: str) -> dict:
    if not isinstance(row, Mapping) or row.get('sha256') != digest({k:v for k,v in row.items() if k!='sha256'}):
        raise ValueError('WORKSPACE_ATTEMPT_HASH_INVALID')
    if (row.get('schema_version') != ATTEMPT_SCHEMA or row.get('target_trade_date') != date_token(date)
            or any(row.get(k) is not v for k,v in FLAGS.items())
            or not re.fullmatch(r'[0-9a-f]{32}',str(row.get('run_id','')))
            or row.get('state') not in {'RUNNING','FAILED','PARTIAL','SUCCEEDED','SUCCEEDED_EMPTY'}
            or (row.get('execution_kind') not in {'MANUAL_REFRESH','SCHEDULED_PREOPEN','SCHEDULED_MORNING'} and not (
                row.get('execution_kind') == 'SCHEDULED_REFRESH' and
                row.get('owner') == 'ManagerResearchJobService.refresh_announcements'))
            or (row.get('execution_kind') in {'SCHEDULED_PREOPEN','SCHEDULED_MORNING'} and
                row.get('owner') != 'ManagerResearchJobService.refresh_workspace_plan')
            or timestamp(row.get('started_at')) is None
            or not isinstance(row.get('failure_reasons'),list)):
        raise ValueError('WORKSPACE_ATTEMPT_CONTRACT_INVALID')
    if row['state'] != 'RUNNING':
        if timestamp(row.get('finished_at')) is None or timestamp(row['finished_at']) < timestamp(row['started_at']):
            raise ValueError('WORKSPACE_ATTEMPT_TERMINAL_TIME_INVALID')
    return dict(row)


def read_attempt(store: Any, date: str) -> dict | None:
    # Use the ORIGINAL store's bounded SafeRoot reads; no glob/latest-day fallback.
    row = store._read(store.root / 'workspace_runs' / date_token(date) / 'latest.json')
    return validate_attempt(row,date) if row is not None else None


def _save_attempt(store: Any, row: Mapping[str, Any]) -> dict:
    row = validate_attempt(seal_attempt(row),str(row['target_trade_date']))
    directory = store.root / 'workspace_runs' / row['target_trade_date']
    # Each run remains addressable; latest.json is a same-date pointer-document,
    # not a cross-day artifact fallback. Original SafeRoot writes are atomic.
    store._write_atomic(directory / (row['run_id']+'.json'),row)
    store._write_atomic(directory / 'latest.json',row)
    return row


def _vibe_binding() -> tuple[dict | None,list[str]]:
    path = os.environ.get('V4_MANAGER_VIBE_BINDING','').strip()
    if not path:
        return None,[]
    try:
        from infrastructure.owned_io import SafeRoot
        p = Path(path).expanduser()
        if not p.is_absolute() or '..' in p.parts:
            raise ValueError('absolute operator-owned binding path required')
        raw = SafeRoot(p.parent).read_bytes(p.name,max_bytes=1024*1024)
        value = json.loads(raw)
        if not isinstance(value,dict):
            raise ValueError('binding must be an object')
        return value,[]
    except _ERROR_TYPES as exc:
        return None,['VIBE_OPERATOR_BINDING_READ_FAILED:'+type(exc).__name__]


def _materials(service: Any,date: str,context: Mapping[str,Any] | None = None) -> dict:
    binding,errors = _vibe_binding()
    result = read_existing_materials(date,research_source=service._existing_research_source,vibe_binding=binding,context=context)
    result['gaps'] = sorted(set([*result['gaps'],*errors]))
    return result


def _discovery(service: Any,date: str,catalyst: Mapping[str,Any]) -> dict:
    configured=os.environ.get('V4_MANAGER_UNIVERSE_ROOT','').strip()
    root=Path(configured).expanduser() if configured else None
    if root is not None and (not root.is_absolute() or '..' in root.parts):
        return dict(cards=[],gaps=['DISCOVERY_UNIVERSE_ROOT_MUST_BE_EXPLICIT_ABSOLUTE'],coverage={})
    return read_discovery(date,catalyst=catalyst,universe_root=root,
                          data_root=service._catalyst_data_root,owner_root=service._catalyst_news_owner_root)


def _combined_catalyst(catalyst: Mapping[str,Any],discovery: Mapping[str,Any]) -> dict:
    # This is a read-only workspace input, NOT a rewritten signed v1 product.
    result={**catalyst,'cards':[*catalyst.get('cards',[]),*discovery.get('cards',[])]}
    result['original_catalyst_content_sha256']=result.pop('content_sha256',None)
    result['workspace_projection_only']=True
    if discovery.get('cards'):result['status']='READY'
    return result


def _previous_observation(service: Any,date: str) -> tuple[dict | None,str | None]:
    try:
        from domains.manager_condition_evidence import _prior_dates
        days,calendar_sha,_=_prior_dates(Path(__file__).resolve().parents[2],date)
        if not days:raise ValueError('prior session absent')
        prior_date=days[-1]
        catalyst=service.get_catalyst_observations(prior_date)
        stage=_reader_value(service.observation_reader,prior_date,'STAGE')
        close=_reader_value(service._close_observation_reader,prior_date,'CLOSE')
        prior=build_workspace(prior_date,catalyst=catalyst,stage=stage,close=close)
        prior['calendar_sha256']=calendar_sha
        return prior,None if prior['stocks'] else 'PRIOR_EXACT_OWNER_STOCK_OBSERVATION_NOT_AVAILABLE'
    except _ERROR_TYPES as exc:
        return None,'PRIOR_TRADING_SESSION_OR_EXACT_OWNER_ARTIFACT_UNVERIFIED:'+type(exc).__name__


def refresh_with_tracking(service: Any, target_trade_date: str) -> dict:
    """Called ONLY by the original service.refresh_catalyst_observations method.

    The old response schema/content checksum stay unchanged. Missing independent
    archives degrade the workspace receipt, not the already-verified catalyst
    material. A journal write failure must not be passed off as a successful run.
    """
    from .catalyst_observations import refresh
    date = date_token(target_trade_date)
    with service.store._transaction(date,'workspace-refresh'):
        prior = read_attempt(service.store,date)
        row = dict(schema_version=ATTEMPT_SCHEMA,target_trade_date=date,run_id=uuid4().hex,
                   owner='ManagerResearchJobService.refresh_catalyst_observations',
                   instance_id=service._instance_id,state='RUNNING',execution_kind='MANUAL_REFRESH',
                   started_at=_now(),last_success_at=(prior or {}).get('last_success_at'),
                   failure_reasons=[],**FLAGS)
        _save_attempt(service.store,row)
        try:
            product = refresh(service.store,service._material_store,date,
                              data_root=service._catalyst_data_root,owner_root=service._catalyst_news_owner_root,
                              archive_source=service._existing_research_source,security_master_root=service._workspace_security_master_root)
            existing = _materials(service,date)
            discovery = _discovery(service,date,product)
            projection = build_workspace(date,catalyst=_combined_catalyst(product,discovery),materials=existing['materials'],
                                         source_gaps=[*existing['gaps'],*discovery['gaps']])
            failures = sorted(set([*product.get('gaps',[]),*existing['gaps'],*discovery['gaps']]))
            finished = _now()
            row.update(state='PARTIAL' if failures else ('SUCCEEDED' if projection['stocks'] else 'SUCCEEDED_EMPTY'),
                       finished_at=finished,last_success_at=finished,failure_reasons=failures,
                       success_scope='CATALYST_PROJECTION_COMMITTED_NOT_FULL_MARKET_CAPTURE',
                       input_coverage=existing['coverage'],summary=projection['summary'],
                       material_bindings=existing['input_bindings'],input_identity=projection['input_identity'],
                       catalyst_content_sha256=product.get('content_sha256'))
            _save_attempt(service.store,row)
            return product
        except _ERROR_TYPES as exc:
            row.update(state='FAILED',finished_at=_now(),failure_reasons=['OWNER_REFRESH_FAILED:'+type(exc).__name__])
            _save_attempt(service.store,row)
            raise


def _reader_value(reader: Any,date: str,lane: str) -> dict:
    if reader is None:
        return dict(status='CANNOT_CONFIRM',target_trade_date=date,cannot_confirm=[lane+'_ORIGINAL_READER_NOT_BOUND'])
    try:
        value = reader.read(date) if hasattr(reader,'read') else reader(date)
        if not isinstance(value,Mapping):
            raise ValueError('owner did not return an envelope')
        return dict(value)
    except _ERROR_TYPES as exc:
        return dict(status='FAILED',target_trade_date=date,cannot_confirm=[lane+'_ORIGINAL_READER_FAILED:'+type(exc).__name__])


def _stage_attempt(service: Any,date: str) -> tuple[dict | None,list[str]]:
    root = service._workspace_ledger_root
    if root is None:
        return None,['STAGE_EXECUTION_LEDGER_NOT_EXPLICITLY_BOUND']
    try:
        from infrastructure.scheduling.execution_ledger import ExecutionLedger
        ledger=ExecutionLedger(root)
        rows=ledger.list_receipts(date,mode='LIVE')
        valid,_=ledger.verify_receipt_chain(date,mode='LIVE')
        if not valid:
            raise ValueError('receipt chain invalid')
        for receipt in reversed(rows):
            if receipt.get('target_date')!=date or receipt.get('scheduled_date')!=date:
                continue
            for result in receipt.get('workload_results',[]):
                if not isinstance(result,Mapping) or result.get('workload_id')!='stage_workbench':
                    continue
                # No scheduler slot -> real execution timestamp conversion.
                # Preserve absence where the supplied contract does not expose it.
                started=result.get('started_at') or receipt.get('started_at')
                status=str(result.get('status') or '').upper()
                attempt=dict(run_id=receipt.get('run_id'),started_at=started if timestamp(started) else None,
                             state={'FAILED':'FAILED','RUNNING':'RUNNING','SUCCEEDED':'SUCCEEDED','READY':'SUCCEEDED'}.get(status,'UNVERIFIED'),
                             execution_kind='LIVE_LEDGER_NOT_NATURAL_TIMING_VERIFIED',
                             verification='ORIGINAL_LEDGER_CHAIN_VERIFIED',failure_reasons=[])
                if status=='FAILED':attempt['failure_reasons']=['STAGE_EXECUTOR_REPORTED_FAILED']
                return attempt,[] if attempt['started_at'] else ['STAGE_LEDGER_ACTUAL_START_TIME_NOT_EXPOSED']
        return None,['STAGE_TARGET_EXECUTION_RECEIPT_NOT_FOUND']
    except _ERROR_TYPES as exc:
        return None,['STAGE_EXECUTION_LEDGER_READ_FAILED:'+type(exc).__name__]


def _research_relation_material_cards(
    cards: list[Mapping[str, Any]], connect_scope: Mapping[str, Any],
    connect_rejections: list[Mapping[str, Any]], target_date: str,
) -> list[dict[str, Any]]:
    """Copy pre-Connect cards for research audit with separate membership evidence.

    These copies are not selection/focus/BUY inputs. A missing or invalid
    target-date Connect authority remains visible on every research relation.
    """
    rejected_by_id = {
        str(row.get('card_id')): row for row in connect_rejections
        if isinstance(row, Mapping) and row.get('card_id')
    }
    scope_gaps = [str(gap) for gap in connect_scope.get('gaps', []) if isinstance(gap, str)]
    result: list[dict[str, Any]] = []
    for raw in cards:
        if not isinstance(raw, Mapping):
            continue
        card = deepcopy(dict(raw))
        rejection = rejected_by_id.get(str(card.get('card_id') or ''))
        reason = str(rejection.get('reason') or '') if rejection else ''
        if reason == 'NOT_IN_TARGET_HK_CONNECT_UNIVERSE':
            membership_state = 'NOT_IN_TARGET_HK_CONNECT_UNIVERSE'
        elif reason == 'NON_HK_SECURITY_IDENTITY':
            membership_state = 'IDENTITY_INVALID'
        elif rejection or connect_scope.get('status') != 'OWNER_VERIFIED':
            membership_state = 'CANNOT_CONFIRM'
            if not reason:
                reason = scope_gaps[0] if scope_gaps else 'TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED'
        else:
            membership_state = 'VERIFIED_TARGET_UNIVERSE'
        card['target_connect_membership'] = {
            'status': membership_state,
            'reason': reason or None,
            'target_trade_date': target_date,
            'authority_identity': connect_scope.get('identity'),
            'research_only': True,
            'RESEARCH_ONLY': True,
            'production_allowed': False,
            'buy_gate_updated': False,
            'orders_sent': False,
        }
        result.append(card)
    return result


def _research_relation_material_input(
    *, pre_connect_cards: list[Mapping[str, Any]], post_connect_cards: list[Mapping[str, Any]],
    relation_cards: list[Mapping[str, Any]], connect_scope: Mapping[str, Any],
    connect_rejections: list[Mapping[str, Any]], material_discovery: Mapping[str, Any],
    selection_materials: list[Mapping[str, Any]], existing: Mapping[str, Any],
    announcement_inputs: Mapping[str, Any],
) -> dict[str, Any]:
    source_gaps = sorted({
        str(gap)
        for gap in [
            *(existing.get('gaps') or []),
            *(announcement_inputs.get('gaps') or []),
            *(material_discovery.get('gaps') or []),
        ]
        if isinstance(gap, str) and not gap.startswith('TARGET_DATE_HK_CONNECT_')
    })
    discovery_status = material_discovery.get('status')
    if discovery_status not in {'READY', 'READY_EMPTY'}:
        status = 'CANNOT_CONFIRM'
    elif source_gaps:
        status = 'PARTIAL'
    else:
        status = 'READY'
    membership_counts: dict[str, int] = {}
    for card in relation_cards:
        membership = card.get('target_connect_membership') if isinstance(card, Mapping) else None
        key = str(membership.get('status') or 'CANNOT_CONFIRM') if isinstance(membership, Mapping) else 'CANNOT_CONFIRM'
        membership_counts[key] = membership_counts.get(key, 0) + 1
    rejection_counts: dict[str, int] = {}
    for row in connect_rejections:
        if not isinstance(row, Mapping):
            continue
        key = str(row.get('reason') or 'UNKNOWN')
        rejection_counts[key] = rejection_counts.get(key, 0) + 1
    input_identity = semantic_digest({
        'selection_materials': selection_materials,
        'relation_cards': relation_cards,
        'target_connect_membership': {
            'target_trade_date': connect_scope.get('target_trade_date'),
            'identity': connect_scope.get('identity'),
            'status': connect_scope.get('status'),
            'gaps': connect_scope.get('gaps'),
        },
        'source_gaps': source_gaps,
    })
    return {
        'status': status,
        'complete': status == 'READY',
        'source_material_record_count': len(selection_materials),
        'pre_connect_material_card_count': len(pre_connect_cards),
        'post_connect_material_card_count': len(post_connect_cards),
        'research_relation_material_card_count': len(relation_cards),
        'connect_rejection_count': len(connect_rejections),
        'target_connect_scope_status': connect_scope.get('status'),
        'target_connect_membership_counts': dict(sorted(membership_counts.items())),
        'connect_rejection_reasons': dict(sorted(rejection_counts.items())),
        'gaps': source_gaps,
        'input_identity': input_identity,
        'relation_use': 'RESEARCH_ONLY_NOT_FORMAL_SELECTION_FOCUS_OR_BUY',
        'RESEARCH_ONLY': True,
        'production_allowed': False,
        'buy_gate_updated': False,
        'orders_sent': False,
    }


def get_workspace(service: Any,target_trade_date: str, *, include_saved: bool = True,
                  view: str = 'dynamic', now: datetime | None = None,
                  selection_date: str | None = None, announcement_date: str | None = None) -> dict:
    date = date_token(target_trade_date)
    selection = date_token(selection_date) if selection_date is not None else date
    from .announcement_analysis import previous_hk_session
    publication = date_token(announcement_date.replace('-', '')) if announcement_date is not None else previous_hk_session(date)
    bindings = dict(plan_date=date, selection_date=selection, announcement_date=publication)
    clock = now if now is not None else datetime.now(timezone.utc)
    if clock.tzinfo is None or view not in {'auto','historical','dynamic'}:
        raise ValueError('WORKSPACE_VIEW_OR_CLOCK_INVALID')
    if include_saved and (view == 'historical' or
            (view == 'auto' and date < clock.astimezone(HK).strftime('%Y%m%d'))):
        if date >= clock.astimezone(HK).strftime('%Y%m%d'):
            raise ValueError('WORKSPACE_HISTORICAL_DATE_NOT_PAST')
        from .workspace_history import read_history
        result = read_history(service, date)
        if include_saved:
            from .us_mapping_research import read_workspace_mapping
            result['us_mapping_research'] = read_workspace_mapping(service, date)
        result['date_bindings'] = bindings
        return _attach_daily_channels(result)
    # An automatic page read is re-evaluated from the original owners. When the
    # complete date binding matches the sealed plan, use that plan's original
    # as-of context so a few seconds of wall-clock drift do not change the
    # semantic projection. This is not a cached-success shortcut: all sources
    # below are still re-read and _readback_plan compares their identities.
    # Explicit current review uses the current clock, including when there is
    # an older saved plan; the saved product keeps its own immutable cutoff.
    saved_context = (_saved_plan_context_for_bindings(service, date, bindings)
                     if include_saved and view == 'auto' else None)
    context = saved_context
    if context is None:
        context = plan_context(date, now=clock)
    if announcement_date is not None and saved_context is None:
        context['announcement_publication_date'] = datetime.strptime(publication, '%Y%m%d').strftime('%Y-%m-%d')
    # Bind before the saved-product comparison so the comparison can reject a
    # different selection/publication query and preserve exact page identity.
    result = _compute_workspace(service, date, include_saved=False, context=context)
    result['date_bindings'] = bindings
    if include_saved:
        result = _readback_plan(service.store, date, result, read_at=clock, current_review=view == 'dynamic')
    result['read_context'] = dict(mode='CURRENT_DYNAMIC_PREVIEW',
        status='VERIFIED_WITH_GAPS' if result['gaps'] else 'VERIFIED',
        as_of=result['plan_context']['research_cutoff'],
        candidate_count_known=bool(result['stocks']) or not result['gaps'], contract=READ_CONTRACT)
    return _attach_daily_channels(result)


def _read_close_recapture_inputs(reader: Any, requested_date: str, context: Mapping[str, Any]) -> tuple[dict, dict]:
    """Keep the prior-session planner read and requested-date display read separate."""
    from .workspace_projection import FLAGS

    plan_source_date=str(context.get('market_session') or '')
    if plan_source_date and hasattr(reader,'read_close_recapture'):
        try:
            planning=reader.read_close_recapture(plan_source_date)
        except _ERROR_TYPES as exc:
            planning=dict(status='FAILED',source_trade_date=plan_source_date,
                cannot_confirm=['CLOSE_RECAPTURE_ORIGINAL_READER_FAILED:'+type(exc).__name__])
    else:
        planning=dict(status='NOT_RUN',source_trade_date=plan_source_date or None,
            cannot_confirm=['CLOSE_RECAPTURE_ORIGINAL_READER_NOT_BOUND'])

    requested_reader=getattr(reader,'read_requested_day_hk_observation',None)
    if callable(requested_reader):
        try:
            requested=requested_reader(requested_date)
        except _ERROR_TYPES as exc:
            requested=dict(status='FAILED',source_trade_date=None,requested_trade_date=requested_date,
                observation_type='HK_SECURITIES_SESSION_MINUTE_OBSERVATION',
                candidate_overlay={'count':0,'rows':[]},
                cannot_confirm=['REQUESTED_DAY_HK_OBSERVATION_ORIGINAL_READER_FAILED:'+type(exc).__name__],
                **FLAGS)
    else:
        requested=dict(status='NOT_RUN',source_trade_date=None,requested_trade_date=requested_date,
            observation_type='HK_SECURITIES_SESSION_MINUTE_OBSERVATION',
            candidate_overlay={'count':0,'rows':[]},
            cannot_confirm=['REQUESTED_DAY_HK_OBSERVATION_READER_NOT_BOUND'],**FLAGS)
    return planning,requested


def _compute_workspace(service: Any, date: str, *, include_saved: bool = True, context: dict,
                       date_bindings: Mapping[str, str] | None = None) -> dict:
    from copy import deepcopy
    context = deepcopy(context)
    try:
        with phase('catalyst_owner'):
            catalyst=service.get_catalyst_observations(date)
    except _ERROR_TYPES as exc:
        catalyst=dict(status='FAILED',target_trade_date=date,cards=[],gaps=['CATALYST_ORIGINAL_READER_FAILED:'+type(exc).__name__],**FLAGS)
    with phase('stage_owner'):
        stage=_reader_value(service.observation_reader,date,'STAGE')
    with phase('close_owner'):
        close=_reader_value(service._close_observation_reader,date,'CLOSE')
    with phase('close_recapture_owner'):
        close_recapture,requested_day_close_recapture=_read_close_recapture_inputs(
            service._close_observation_reader,date,context)
    with phase('existing_material_owners'):
        existing=_materials(service,date,context)
    with phase('discovery_owner'):
        discovery=_discovery(service,date,catalyst)
    from .workspace_announcements import read as read_announcements, read_selection_inputs
    from .connect_selection import read_scope, filter_cards, gate_workspace, evidence_view, selection_diagnostics
    # The original owner revalidates existing stored bodies before the SAME
    # native issuer classifier runs. This GET still never fetches or writes.
    with phase('announcement_source_validation'):
        announcement_review = read_announcements(service, date, context)
    with phase('announcement_body_selection_inputs'):
        try:
            announcement_inputs=read_selection_inputs(service,context,current_review=announcement_review)
        except _ERROR_TYPES as exc:
            reason='ANNOUNCEMENT_SELECTION_ORIGINAL_READER_FAILED:'+type(exc).__name__
            announcement_inputs=dict(materials=[],rejections=[dict(reason=reason)],gaps=[reason],captures=[],
                status='CANNOT_CONFIRM',input_identity=digest([reason]),**FLAGS)
    with phase('target_connect_authority'):
        connect_scope=read_scope(context)
    selection_materials=[*existing['materials'],*announcement_inputs['materials']]
    with phase('material_discovery'):
        material_discovery=read_material_discovery(selection_materials,context,
            getattr(service,'_workspace_security_master_root',None),
            projection_memo=getattr(service,'_workspace_projection_memo',None))
    material_discovery=deepcopy(material_discovery)
    pre_connect_material_cards=deepcopy(material_discovery.get('cards',[]))
    post_connect_material_cards,connect_rejections=filter_cards(
        pre_connect_material_cards,connect_scope,target_date=date)
    research_relation_cards=_research_relation_material_cards(
        pre_connect_material_cards,connect_scope,connect_rejections,date)
    material_discovery['cards']=post_connect_material_cards
    material_discovery['rejected_relations']=[*material_discovery.get('rejected_relations',[]),*connect_rejections]
    material_discovery['coverage']['target_connect_card_count']=len(material_discovery['cards'])
    material_discovery['coverage']['pre_connect_card_count']=len(pre_connect_material_cards)
    material_discovery['coverage']['research_relation_card_count']=len(research_relation_cards)
    material_discovery['coverage']['target_connect_rejection_count']=len(connect_rejections)
    relation_material_input=_research_relation_material_input(
        pre_connect_cards=pre_connect_material_cards,post_connect_cards=post_connect_material_cards,
        relation_cards=research_relation_cards,connect_scope=connect_scope,
        connect_rejections=connect_rejections,material_discovery=material_discovery,
        selection_materials=selection_materials,existing=existing,announcement_inputs=announcement_inputs)
    with phase('exact_quote_owner'):
        quote_evidence=read_plan_quotes(service._catalyst_data_root,context,
            authority_root=getattr(service,'_workspace_security_master_root',None))
    screen_authority_root = (getattr(service, '_workspace_screen_authority_root', None)
                             or getattr(service, '_workspace_security_master_root', None))
    with phase('rebound_screen'):
        market_screen = read_rebound_screen(screen_authority_root, context)
    context['market_data_verified']=quote_evidence['verified']
    with phase('previous_observation'):
        previous,continuity_gap=_previous_observation(service,date)
    attempts={}
    runtime_gaps=[]
    try:
        attempt=read_attempt(service.store,date)
        if attempt:
            # Multi-worker ownership cannot be inferred from instance UUIDs;
            # never call a different live process a failed run without evidence.
            attempts['CATALYST']=attempt
    except _ERROR_TYPES as exc:
        runtime_gaps.append('WORKSPACE_JOURNAL_READ_FAILED:'+type(exc).__name__)
    with phase('stage_ledger'):
        attempt,missing=_stage_attempt(service,date)
    if attempt:attempts['STAGE']=attempt
    stage_ledger_verified_empty=(attempt is None and missing==['STAGE_TARGET_EXECUTION_RECEIPT_NOT_FOUND'])
    runtime_gaps.extend(missing)
    if close.get('generated_at'):
        state='RUNNING' if 'EXECUTION_STARTED' in close.get('cannot_confirm',[]) else close.get('status')
        attempts['CLOSE']=dict(run_id=close.get('run_id'),generated_at=close['generated_at'],state=state,
            execution_kind='ORIGINAL_CLOSE_RECEIPT_TIMING_NOT_CLASSIFIED',failure_reasons=close.get('cannot_confirm',[]))
    # No supplied current-plan reader/contract. This must remain a precise gap,
    # not a fixed 15:30 or top-of-hour promise. Local integration may add a
    # verified plan projection when runtime_router/dispatcher sources are supplied.
    runtime_gaps.append('NEXT_SCHEDULE_UNVERIFIED_ORIGINAL_RUNTIME_PLAN_READER_NOT_SUPPLIED')
    count('verified_material_count', len(existing['materials']))
    count('archive_attempted_count', int(existing['coverage'].get('attempted_artifact_count') or 0))
    committed_archive_ids={c.get('card_id') for c in catalyst.get('cards',[]) if isinstance(c,Mapping) and c.get('research_role')=='ARCHIVE_ISSUER_RESEARCH_OBSERVATION_ONLY'}
    discovery_cards=[c for c in [*discovery['cards'],*material_discovery['cards']] if c.get('card_id') not in committed_archive_ids]
    inputs = dict(catalyst=catalyst, stage=stage, close=close, close_recapture=close_recapture,
        requested_day_close_recapture=requested_day_close_recapture,
        materials=selection_materials,
        discovered_cards=discovery_cards, plan_context=context,
        price_quotes=quote_evidence['quotes'], discovery_rejections=material_discovery.get('rejected_relations',[]),
        attempts=attempts, source_gaps=[*existing['gaps'],*discovery['gaps'],*material_discovery['gaps'],
            *quote_evidence['gaps'],*market_screen.get('gaps',[]),*announcement_inputs['gaps'],
            *connect_scope.get('gaps',[])], previous=previous, market_screen=market_screen)
    with phase('pure_workspace_projection'):
        value = project(service, 'workspace_projection', [date, inputs], lambda: build_workspace(date, **inputs))
    value=gate_workspace(value,connect_scope)
    from .workspace_daily_channels import read_original_stage_selection
    # The STAGE observation DTO above remains owned by observation_reader.
    # Formal HK decisions are a distinct SelectionStore trio/read-only owner.
    value['stage_selection_readback'] = read_original_stage_selection(service, date)
    identity_components=value.get('input_identity_components')
    if not isinstance(identity_components, dict):
        raise ValueError('WORKSPACE_INPUT_IDENTITY_COMPONENTS_UNAVAILABLE')
    identity_components['connect_scope']=identity_component({
        'target_trade_date':connect_scope.get('target_trade_date'),
        'identity':connect_scope.get('identity'), 'status':connect_scope.get('status'),
        'gaps':connect_scope.get('gaps'),
        'calendar_applicability':connect_scope.get('calendar_applicability'),
        'source':deepcopy(dict(connect_scope.get('source') or {}))})
    from .stage_read_timing import project_stage_read_timing
    timing=project_stage_read_timing(stage,date,timestamp(context['research_cutoff']),
        attempt=attempts.get('STAGE'),ledger_verified_empty=stage_ledger_verified_empty)
    value['stage_read_timing']=timing
    for lane in value.get('lanes',[]):
        if lane.get('lane')=='STAGE':lane['execution_timing']=timing
    value['discovery_evidence']=discovery
    value['material_discovery_evidence']=material_discovery
    value['quote_evidence']={k:v for k,v in quote_evidence.items() if k!='quotes'}
    value['market_screen_evidence']={
        'status': market_screen.get('status'),
        'rule_version': market_screen.get('rule_version'),
        'coverage': market_screen.get('coverage'),
        'gaps': market_screen.get('gaps',[]),
        'input_identity': market_screen.get('input_identity'),
        'authority': market_screen.get('authority'),
    }
    value['previous_observation_identity']=previous.get('input_identity') if previous else None
    value['previous_calendar_sha256']=previous.get('calendar_sha256') if previous else None
    value['existing_material_coverage']=existing['coverage']
    value['existing_material_bindings']=existing['input_bindings']
    value['runtime_gaps']=runtime_gaps
    value['observation_mode']='READ_ONLY_EXISTING_OWNER_REPLAY'
    value['run_accounting']=dict(manual_refresh=attempts.get('CATALYST'),natural_run_verified=False,
                                 historic_exact_1530_recaptured=False)
    value['continuity_gap']=continuity_gap
    value['owner_chain']=dict(
        source_collection='NOT_INFERRED_FROM_ARCHIVE_ROW_COUNT',
        materials=dict(owner='ResearchArchiveStore / HourlyResearchStore / Vibe original readers',
            status='PARTIAL' if existing['gaps'] else 'READBACK_VERIFIED',
            input_bindings=existing['input_bindings'],coverage=existing['coverage']),
        issuer_projection=dict(status=material_discovery['status'],coverage=material_discovery['coverage']),
        semantic_projection=dict(status=value['briefing']['business_status'],
            semantic_version=value['semantic_version'],input_identity=value['input_identity']),
        api='PROJECTED_NOT_BROWSER_ACK',browser='LOCAL_REAL_UI_ACCEPTANCE_REQUIRED')
    value['announcement_review'] = announcement_review
    from .announcement_observation import event_lane
    value['announcement_observation'] = event_lane(announcement_review, market_screen, context)
    # US evidence is read from the existing exact-session peripheral store.
    # This GET never fetches or materializes US data.
    from .us_market_bridge import project_us_market
    with phase('us_market_exact_read'):
        us_market = project_us_market(
            getattr(service, '_workspace_us_market_reader', None), date, context
        )
        from .us_mapping_research import attach_current_relation_evidence
        us_market = attach_current_relation_evidence(us_market)
    us_market['research_material_input']=deepcopy(relation_material_input)
    value['us_market_attention'] = us_market
    from .research_attention import build_research_attention
    scoped_screen,scoped_announcement_lane=evidence_view(market_screen,value['announcement_observation'],connect_scope)
    # Research observation keeps the original owner screen before the formal
    # Connect gate. Its scope diagnostics remain attached, while stocks/focus
    # and the formal selection continue to use gate_workspace unchanged.
    research_screen=deepcopy(market_screen)
    research_screen['research_scope_diagnostics']=deepcopy(scoped_screen.get('research_scope_diagnostics'))
    with phase('research_attention_projection'):
        research_attention = build_research_attention(
        date, context=context, market_screen=research_screen, stocks=value.get('stocks', []),
        material_cards=research_relation_cards, themes=value.get('themes', []),
        announcement_observation=scoped_announcement_lane, us_market=us_market,
    )
    identity_components.update({
        'research_attention.projection':identity_component(research_attention['input_identity'],
            sources=identity_component(research_attention)['sources']),
        'research_attention.material_input':identity_component(relation_material_input['input_identity'],
            sources=identity_component(selection_materials)['sources']),
        'research_attention.material_cards':identity_component(research_relation_cards),
    })
    research_attention['input_identity']=digest([
        research_attention.get('input_identity'),relation_material_input['input_identity'],
        semantic_digest(research_relation_cards),
    ])
    value['repair_contract']='R9_ANNOUNCEMENT_BODY_CONNECT_CONSUMER_V1'
    value['research_attention'] = research_attention
    value['selection_diagnostics']=selection_diagnostics(value,research_attention,announcement_inputs,
        connect_scope,material_discovery.get('rejected_relations',[]))
    value['owner_chain']['announcement_selection']={
        'owner':'ManagerResearchJobService.refresh_announcements -> original stored body readers -> existing issuer classifier',
        'status':announcement_inputs['status'],'input_identity':announcement_inputs['input_identity'],
        'captures':deepcopy(announcement_inputs['captures']),
        'body_material_count':len(announcement_inputs['materials']),
        'rejections':deepcopy(announcement_inputs['rejections']),
        'gaps':deepcopy(announcement_inputs['gaps']),'read_only':True,
        'official_first_publication_claimed':False,
        'reviewed_analysis':deepcopy(announcement_inputs.get('reviewed_analysis', {})),
    }
    value['announcement_reviewed_analysis'] = deepcopy(announcement_inputs.get('reviewed_analysis', {}))
    # The bridge validates/raw-projects; only this completed relation stage
    # can publish mapping counts. Never reuse the bridge placeholder.
    from copy import deepcopy
    value['us_market_attention'] = {**us_market,
        'mapping_diagnostics': deepcopy(research_attention['us_mapping_diagnostics'])}
    # Source status/risks must be consumed, without changing the frozen Stage,
    # rebound or existing focus ranking. No automatic collection on this GET.
    value['owner_chain']['announcements'] = _announcement_owner_chain(announcement_review)
    value['owner_chain']['us_market'] = {
        'owner': 'ResearchPeripheralStore/external_finance',
        'status': us_market.get('status'),
        'expected_us_session': us_market.get('expected_us_session'),
        'coverage': us_market.get('coverage'),
        'source_identity': us_market.get('source_identity'),
        'failure_reasons': us_market.get('gaps', []),
        'read_only': True,
    }
    value['owner_chain']['research_attention'] = {
        'owner': 'v4.manager_research.research_attention',
        'status': research_attention.get('status'),
        'priority_name': research_attention.get('priority_name'),
        'input_identity': research_attention.get('input_identity'),
        'write_back_to_existing_rank': False,
    }
    identity_extensions = [value['input_identity'], research_attention['input_identity'],announcement_inputs['input_identity']]
    reviewed_analysis = announcement_inputs.get('reviewed_analysis')
    if isinstance(reviewed_analysis, Mapping):
        identity_extensions.append(reviewed_analysis.get('input_identity'))
    if announcement_review.get('product_identity'):
        identity_extensions.append(announcement_review['product_identity']['sha256'])
    us_identity = us_market.get('source_identity') if isinstance(us_market, Mapping) else None
    if isinstance(us_identity, Mapping) and isinstance(us_identity.get('payload_sha256'), str):
        identity_extensions.append(us_identity['payload_sha256'])
    relation_evidence = us_market.get('relation_evidence') if isinstance(us_market, Mapping) else None
    if isinstance(relation_evidence, Mapping) and isinstance(relation_evidence.get('assessment_identity'), str):
        identity_extensions.append(relation_evidence['assessment_identity'])
    # The saved daily US mapping is a separate research reference. It is
    # admitted into this plan identity only after the same exact plan cutoff.
    mapping_read, mapping_research, mapping_identities = _daily_mapping_plan_reference(
        service, date, context, current_us_market=us_market)
    identity_extensions.extend(mapping_identities)
    bindings=dict(date_bindings or {'plan_date':date,'selection_date':date,'announcement_date':date})
    value['date_bindings']=bindings
    identity_components['gated_projection']=identity_component(value['input_identity'])
    identity_components['announcement_inputs']=identity_component(announcement_inputs['input_identity'],
        sources=identity_component(announcement_inputs)['sources'])
    if isinstance(reviewed_analysis, Mapping):
        identity_components['announcement_reviewed_analysis']=identity_component(reviewed_analysis.get('input_identity'),
            sources=identity_component(reviewed_analysis)['sources'])
    if announcement_review.get('product_identity'):
        identity_components['announcement_product']=identity_component(
            announcement_review['product_identity']['sha256'],
            sources=[deepcopy(dict(announcement_review['product_identity']))])
    if isinstance(us_identity, Mapping) and isinstance(us_identity.get('payload_sha256'), str):
        identity_components['us_market_payload']=identity_component(us_identity['payload_sha256'],
            sources=[deepcopy(dict(us_identity))])
    if isinstance(relation_evidence, Mapping) and isinstance(relation_evidence.get('assessment_identity'), str):
        identity_components['us_relation_evidence'] = identity_component(
            relation_evidence['assessment_identity'],
            sources=[deepcopy(dict(relation_evidence))])
    identity_components['us_mapping_daily_reference']=identity_component(mapping_identities,
        sources=[deepcopy(mapping_research)] if mapping_identities else [])
    identity_components['date_bindings']=identity_component(bindings)
    identity_extensions.append(identity_components['date_bindings']['sha256'])
    value['input_identity_schema']=INPUT_IDENTITY_SCHEMA
    value['us_mapping_research'] = deepcopy(mapping_read)
    value['owner_chain']['us_mapping_daily_plan_reference'] = mapping_research
    value['input_identity'] = digest(identity_extensions)
    if include_saved:
        with phase('saved_plan_comparison'):
            return _readback_plan(service.store,date,value)
    return value


PLAN_SCHEMA = 'v4.manager_research.workspace_plan_product.v1'


def _read_plan(store: Any,date: str) -> dict | None:
    row=store._read(store.root/'workspace_plans'/date_token(date)/'latest.json')
    if row is None:return None
    expected=digest({k:v for k,v in row.items() if k!='sha256'})
    if (row.get('schema_version')!=PLAN_SCHEMA or row.get('target_trade_date')!=date
            or row.get('sha256')!=expected or any(row.get(k) is not v for k,v in FLAGS.items())
            or not re.fullmatch(r'[0-9a-f]{32}',str(row.get('run_id','')))
            or not isinstance(row.get('workspace'),dict)
            or row['workspace'].get('target_trade_date')!=date
            or row.get('input_identity')!=row['workspace'].get('input_identity')
            # R2 MANUAL_REFRESH products predate this optional discriminator.
            # Their existing v1 schema remains valid and must not become an
            # unreadable saved product merely because pre-open autorun adds a
            # new execution kind.  Missing means legacy manual refresh only;
            # an explicit unknown value still fails closed.
            or row.get('execution_kind','MANUAL_REFRESH') not in {'MANUAL_REFRESH','SCHEDULED_PREOPEN','SCHEDULED_MORNING'}
            or timestamp(row.get('generated_at')) is None):
        raise ValueError('WORKSPACE_STORED_PLAN_INVALID')
    return row


def _overlay_us_mapping_attempt(saved_workspace: Mapping[str, Any],
                                current_workspace: Mapping[str, Any],
                                plan_cutoff: Any) -> dict:
    """Expose fresh attempt status while keeping the saved plan's consumed run immutable."""
    saved_mapping = saved_workspace.get('us_mapping_research')
    current_mapping = current_workspace.get('us_mapping_research')
    base = deepcopy(dict(saved_mapping if isinstance(saved_mapping, Mapping)
                         else current_mapping if isinstance(current_mapping, Mapping) else {}))
    current_daily = current_mapping.get('daily_run') if isinstance(current_mapping, Mapping) else None
    saved_daily = base.get('daily_run')
    if not isinstance(saved_daily, Mapping):
        saved_daily = deepcopy(dict(current_daily)) if isinstance(current_daily, Mapping) else {}
        base['daily_run'] = saved_daily
    else:
        saved_daily = deepcopy(dict(saved_daily))
        base['daily_run'] = saved_daily
    latest_attempt = (current_daily.get('latest_attempt')
                      if isinstance(current_daily, Mapping) else None)
    if isinstance(latest_attempt, Mapping):
        cutoff = timestamp(plan_cutoff)
        attempt_finished = timestamp(latest_attempt.get('finished_at'))
        saved_daily['latest_attempt'] = deepcopy(dict(latest_attempt))
        saved_daily['latest_attempt_after_plan_cutoff'] = bool(
            cutoff is not None and attempt_finished is not None and attempt_finished > cutoff)
        saved_daily['latest_attempt_affects_saved_plan'] = False
        base['latest_attempt'] = deepcopy(dict(latest_attempt))
    else:
        saved_run = saved_daily.get('run_id') if isinstance(saved_daily, Mapping) else None
        saved_generated = timestamp(saved_daily.get('generated_at')) if isinstance(saved_daily, Mapping) else None
        cutoff = timestamp(plan_cutoff)
        if saved_run is None and isinstance(current_daily, Mapping):
            current_generated = timestamp(current_daily.get('generated_at'))
            if cutoff is not None and current_generated is not None and current_generated > cutoff:
                saved_daily.update({"status":"NOT_CONSUMED_AFTER_CUTOFF", "run_id":None,
                    "generated_at":None, "matches":[], "artifact_sha256":None,
                    "input_identity":None,
                    "gaps":sorted(set([*(saved_daily.get('gaps') or []),
                                         "US_MAPPING_DAILY_RUN_AFTER_PLAN_CUTOFF"]))})
    return base


def verified_plan_attempt(store: Any, saved: Mapping[str, Any]) -> dict | None:
    """Read the exact product's sealed journal, independently of latest.json."""
    from .workspace_plan_autorun import owner_plan_readback, morning_window, preopen_window
    date = date_token(saved['target_trade_date'])
    kind = saved.get('execution_kind', 'MANUAL_REFRESH')
    attempt = store._read(store.root/'workspace_plan_runs'/date/(saved['run_id']+'.json'))
    if attempt is None and kind == 'MANUAL_REFRESH':
        raise ValueError('WORKSPACE_PLAN_ATTEMPT_MISSING')
    product = dict(status='CURRENT', consumed=True, run_id=saved['run_id'],
        sha256=saved['sha256'], generated_at=saved['generated_at'],
        execution_kind=kind, original_owner=saved['owner'],
        execution_context=deepcopy(saved.get('execution_context')))
    owner_plan_readback(dict(target_trade_date=date,input_identity=saved['input_identity'],
        plan_product=product,workspace_plan_attempt=attempt),date,expected_kind=kind)
    if kind in {'SCHEDULED_MORNING','SCHEDULED_PREOPEN'}:
        _, deadline = morning_window(date) if kind == 'SCHEDULED_MORNING' else preopen_window(date,lead_seconds=1)
        if timestamp(saved['generated_at']) >= deadline or timestamp(attempt['finished_at']) >= deadline:
            raise ValueError('WORKSPACE_PLAN_SCHEDULED_TERMINAL_DEADLINE_EXCEEDED')
    return dict(attempt)


def _plan_run_readback(saved: Mapping[str, Any] | None, attempt: Mapping[str, Any] | None,
                       *, read_at: Any, verified: bool) -> dict:
    """Expose live verification without writing into the immutable plan product."""
    owner = 'ManagerResearchJobService.refresh_workspace_plan'
    attempt = attempt if isinstance(attempt, Mapping) else {}
    read_time = timestamp(read_at)
    saved = saved if isinstance(saved, Mapping) else {}
    return {
        'status': 'VERIFIED' if verified else 'CANNOT_CONFIRM',
        'target_trade_date': saved.get('target_trade_date'),
        'run_id': saved.get('run_id'),
        'artifact_sha256': saved.get('sha256'),
        'input_identity': saved.get('input_identity'),
        'owner': owner,
        'read_at': read_time.isoformat() if read_time is not None else _now(),
        'owner_attempt_run_id': attempt.get('run_id') if verified else None,
        'owner_attempt_sha256': attempt.get('sha256') if verified else None,
        'owner_attempt_state': attempt.get('state') if verified else None,
        'owner_finished_at': attempt.get('finished_at') if verified else None,
    }


def _readback_plan(store: Any,date: str,current: dict, *, read_at: Any = None, current_review: bool = False) -> dict:
    try:
        saved=_read_plan(store,date)
        attempt=store._read(store.root/'workspace_plan_runs'/date/'latest.json')
        if attempt is not None:attempt=validate_attempt(attempt,date)
    except _ERROR_TYPES as exc:
        current['plan_product']=dict(status='READBACK_FAILED',reason=type(exc).__name__,consumed=False,
            input_identity_diagnostics=dict(status='CANNOT_CONFIRM',
                reason='STORED_PLAN_VERIFICATION_FAILED',changed_components=[]),
            run_readback=_plan_run_readback(None,None,read_at=read_at or _now(),verified=False))
        return current
    read_time = (read_at.astimezone(HK) if isinstance(read_at, datetime)
                 and read_at.tzinfo is not None and read_at.utcoffset() is not None
                 else timestamp(read_at) if read_at is not None else timestamp(_now()))
    if read_time is None:
        read_time = timestamp(_now())
    saved_cutoff=timestamp(((saved or {}).get('workspace') or {}).get('plan_context',{}).get('research_cutoff'))
    current_cutoff=timestamp(current.get('plan_context',{}).get('research_cutoff'))
    after_cutoff=bool(saved is not None and (saved_cutoff is None or current_cutoff is None or saved_cutoff>current_cutoff))
    identity_diagnostics=input_identity_diagnostics((saved or {}).get('workspace'),current,
        after_cutoff=after_cutoff)
    saved_bindings=((saved or {}).get('workspace') or {}).get('date_bindings')
    current_bindings=current.get('date_bindings')
    bindings_match=(saved_bindings is None and current_bindings is None) or (
        isinstance(saved_bindings,Mapping) and isinstance(current_bindings,Mapping)
        and dict(saved_bindings)==dict(current_bindings))
    same=(saved is not None and identity_diagnostics['status']=='MATCH' and not after_cutoff
          and saved['input_identity']==current['input_identity']
          and saved['workspace'].get('semantic_version')==current.get('semantic_version')
          and bindings_match)
    plan_attempt_error = None
    verified_attempt = None
    if same:
        try:
            verified_attempt=verified_plan_attempt(store,saved)
        except _ERROR_TYPES as exc:
            plan_attempt_error = str(exc) if re.fullmatch(r'[A-Z][A-Z0-9_]{0,127}',str(exc)) else type(exc).__name__
            same = False
    value=deepcopy(saved['workspace']) if same and not current_review else current
    # Persisted stock plans do not freeze live owner execution status. An
    # unchanged material fingerprint must not conceal a later failed attempt.
    if same:
        # Eligibility diagnostics describe this read's owner binding, not the
        # saved plan's binding. Refresh them without changing its identity,
        # run_id or sealed bytes; the existing deep-copy overlay stays read-only.
        for key in ('lanes','runtime_gaps','run_accounting','continuity_gap','market_screen','market_screen_evidence','owner_chain','announcement_review','announcement_observation','announcement_reviewed_analysis','us_market_attention','research_attention','stage_read_timing','stage_selection_readback','repair_contract','selection_diagnostics','date_bindings'):
            if key in current:value[key]=deepcopy(current[key])
        value['runtime_status_read_at']=read_time.isoformat() if read_time is not None else _now()
    value['plan_product']=dict(status='CURRENT' if same else ('OWNER_ATTEMPT_UNVERIFIED' if plan_attempt_error else 'PLAN_AFTER_READ_CUTOFF' if after_cutoff else 'STALE_INPUTS_CHANGED' if saved else 'NOT_MATERIALIZED'),
        run_id=saved.get('run_id') if saved else None,generated_at=saved.get('generated_at') if saved else None,
        sha256=saved.get('sha256') if saved else None,
        execution_kind=saved.get('execution_kind','MANUAL_REFRESH') if saved else None,
        original_owner='ManagerResearchJobService.refresh_workspace_plan',
        last_checked_at=read_time.isoformat() if read_time is not None else _now(),consumed=same,
        input_identity_diagnostics=identity_diagnostics,
        run_readback=_plan_run_readback(saved,verified_attempt,
            read_at=read_time.isoformat() if read_time is not None else _now(),verified=same))
    if plan_attempt_error:
        value['plan_product']['reason'] = plan_attempt_error
    value['workspace_plan_attempt']=attempt
    value['workspace_plan_product_attempt']=deepcopy(verified_attempt) if same else None
    value['observation_mode']='EXACT_DATE_PLAN_READBACK' if same else 'READ_ONLY_EXISTING_OWNER_PREVIEW'
    return value


class _PlanCommitReadView:
    """Private read-only view of the exact product and sealed attempt to commit.

    The normal reader intentionally requires a terminal owner attempt before it
    exposes CURRENT. The owner verifies the full intended commit while the
    public latest pointer still names the previous product (or is absent).
    This view overlays only the candidate paths for one private read and is
    never written or returned to a caller.
    """
    def __init__(self, store: Any, date: str, product: Mapping[str, Any],
                 terminal_attempt: Mapping[str, Any]):
        self.root = Path(store.root)
        self._store = store
        token = date_token(date)
        run_id = str(product.get('run_id') or '')
        self._candidate_reads = {
            self.root/'workspace_plans'/token/'latest.json': deepcopy(dict(product)),
            self.root/'workspace_plan_runs'/token/'latest.json': deepcopy(dict(terminal_attempt)),
            self.root/'workspace_plan_runs'/token/(run_id+'.json'): deepcopy(dict(terminal_attempt)),
        }

    def _read(self, path: Any) -> Any:
        candidate = self._candidate_reads.get(Path(path))
        return deepcopy(candidate) if candidate is not None else self._store._read(path)


def _plan_readback_matches_commit(result: Any, product: Mapping[str, Any],
                                  terminal_attempt: Mapping[str, Any]) -> bool:
    if not isinstance(result, Mapping):
        return False
    reference = result.get('plan_product')
    diagnostics = reference.get('input_identity_diagnostics') if isinstance(reference, Mapping) else None
    run_readback = reference.get('run_readback') if isinstance(reference, Mapping) else None
    observed_attempt = result.get('workspace_plan_attempt')
    product_attempt = result.get('workspace_plan_product_attempt')
    owner = 'ManagerResearchJobService.refresh_workspace_plan'
    return bool(
        result.get('target_trade_date') == product.get('target_trade_date')
        and result.get('input_identity') == product.get('input_identity')
        and isinstance(reference, Mapping)
        and reference.get('status') == 'CURRENT'
        and reference.get('consumed') is True
        and reference.get('run_id') == product.get('run_id')
        and reference.get('sha256') == product.get('sha256')
        and reference.get('execution_kind', 'MANUAL_REFRESH') == product.get('execution_kind', 'MANUAL_REFRESH')
        and reference.get('original_owner') == owner
        and isinstance(diagnostics, Mapping) and diagnostics.get('status') == 'MATCH'
        and isinstance(run_readback, Mapping)
        and run_readback.get('status') == 'VERIFIED'
        and run_readback.get('target_trade_date') == product.get('target_trade_date')
        and run_readback.get('run_id') == product.get('run_id')
        and run_readback.get('artifact_sha256') == product.get('sha256')
        and run_readback.get('input_identity') == product.get('input_identity')
        and run_readback.get('owner') == owner
        and run_readback.get('owner_attempt_run_id') == terminal_attempt.get('run_id')
        and run_readback.get('owner_attempt_sha256') == terminal_attempt.get('sha256')
        and run_readback.get('owner_attempt_state') == terminal_attempt.get('state')
        and isinstance(observed_attempt, Mapping) and dict(observed_attempt) == dict(terminal_attempt)
        and isinstance(product_attempt, Mapping) and dict(product_attempt) == dict(terminal_attempt)
    )


def _verify_plan_commit_before_publication(store: Any, date: str, current: Mapping[str, Any],
                                           product: Mapping[str, Any],
                                           terminal_attempt: Mapping[str, Any]) -> dict:
    """Run the real full reader against an unpublished candidate commit."""
    view = _PlanCommitReadView(store, date, product, terminal_attempt)
    saved = _read_plan(view, date)
    if not isinstance(saved, Mapping) or dict(saved) != dict(product):
        raise ValueError('WORKSPACE_PLAN_SAVE_READBACK_FAILED')
    result = _readback_plan(view, date, deepcopy(dict(current)))
    if not _plan_readback_matches_commit(result, product, terminal_attempt):
        raise ValueError('WORKSPACE_PLAN_SAVE_READBACK_FAILED')
    return result


def refresh_workspace_plan(service: Any,target_trade_date: str, *, execution_kind: str = 'MANUAL_REFRESH',
                           now: datetime | None = None, deadline: datetime | None = None,
                           workspace_date_bindings: Mapping[str, Any] | None = None) -> dict:
    """Persist an exact-date plan from existing verified owners only.

    ``SCHEDULED_PREOPEN`` is reserved for the bounded pre-open autorun.  It
    uses its supplied aware clock for both the read cutoff and product timing;
    late/backfill eligibility is enforced by ``workspace_plan_autorun``.
    """
    if execution_kind not in {'MANUAL_REFRESH','SCHEDULED_PREOPEN','SCHEDULED_MORNING'}:
        raise ValueError('WORKSPACE_PLAN_EXECUTION_KIND_INVALID')
    scheduled = execution_kind in {'SCHEDULED_PREOPEN','SCHEDULED_MORNING'}
    if scheduled and (now is None or now.tzinfo is None):
        raise ValueError('WORKSPACE_PLAN_SCHEDULED_CLOCK_REQUIRED')
    if scheduled and deadline is None:
        raise ValueError('WORKSPACE_PLAN_SCHEDULED_DEADLINE_REQUIRED')
    if deadline is not None and deadline.tzinfo is None:
        raise ValueError('WORKSPACE_PLAN_DEADLINE_MUST_BE_AWARE')
    if not scheduled and deadline is not None:
        raise ValueError('WORKSPACE_PLAN_DEADLINE_ONLY_FOR_SCHEDULED_PREOPEN')
    if scheduled and now.astimezone(timezone.utc) >= deadline.astimezone(timezone.utc):
        raise ValueError('WORKSPACE_PLAN_SCHEDULED_DEADLINE_EXPIRED')
    date=date_token(target_trade_date)
    workspace_dates: dict[str, str] = {}
    if workspace_date_bindings is not None:
        if (not isinstance(workspace_date_bindings, Mapping)
                or set(workspace_date_bindings) - {'selection_date', 'announcement_date'}):
            raise ValueError('WORKSPACE_PLAN_DATE_BINDINGS_INVALID')
        if 'selection_date' in workspace_date_bindings:
            workspace_dates['selection_date'] = date_token(workspace_date_bindings['selection_date'])
        if 'announcement_date' in workspace_date_bindings:
            workspace_dates['announcement_date'] = date_token(
                str(workspace_date_bindings['announcement_date']).replace('-', ''))
        if not workspace_dates:
            raise ValueError('WORKSPACE_PLAN_DATE_BINDINGS_INVALID')
    if execution_kind == 'SCHEDULED_MORNING':
        from .workspace_plan_autorun import morning_window
        start, freeze = morning_window(date)
        if (now.astimezone(HK).strftime('%Y%m%d') != date or not start <= now < freeze
                or deadline != freeze):
            raise ValueError('MORNING_PLAN_OUTSIDE_FROZEN_WINDOW')
        if (getattr(service,'_existing_research_source',None) is None
                or getattr(service,'_workspace_us_market_reader',None) is None):
            raise ValueError('MORNING_PLAN_FULL_OWNER_READERS_REQUIRED')
    with service.store._transaction(date,'workspace-plan-refresh'):
        prepared=None;preparation_error=None
        previous_plan=_read_plan(service.store,date)
        # An exact-date, same-input manual owner call is a read, not a new run.
        # This is inside the existing cross-process store transaction.
        if (not scheduled and previous_plan is not None
                and previous_plan.get('execution_kind','MANUAL_REFRESH')==execution_kind):
            try:
                prepared=get_workspace(service,date,include_saved=False,now=now,**workspace_dates)
            except _ERROR_TYPES as exc:
                preparation_error=exc
            if prepared is not None:
                reusable=_readback_plan(service.store,date,deepcopy(prepared))
                product_ref=reusable.get('plan_product',{})
                if (product_ref.get('status')=='CURRENT'
                        and product_ref.get('consumed') is True
                        and product_ref.get('run_id')==previous_plan['run_id']
                        and product_ref.get('sha256')==previous_plan['sha256']):
                    owner_attempt=verified_plan_attempt(service.store,previous_plan)
                    reusable['plan_product']['status']='ALREADY_MATERIALIZED'
                    reusable['workspace_plan_attempt']=owner_attempt
                    reusable['workspace_plan_product_attempt']=deepcopy(owner_attempt)
                    return _attach_daily_channels(reusable)
        if scheduled:
            # The outer autorun check is only an optimization. A concurrent
            # caller may pass it before the first caller commits, so repeat
            # the exact-date check while holding the same store transaction
            # used for plan persistence.
            existing=_read_plan(service.store,date)
            if existing is not None:
                existing_workspace=existing['workspace']
                existing_context=existing_workspace.get('plan_context') if isinstance(existing_workspace.get('plan_context'),dict) else {}
                existing_generated=timestamp(existing.get('generated_at'))
                existing_cutoff=timestamp(existing_context.get('research_cutoff'))
                open_at=deadline.astimezone(timezone.utc)
                prior_product_attempt=service.store._read(service.store.root/
                    'workspace_plan_runs'/date/(existing['run_id']+'.json'))
                if prior_product_attempt is not None:
                    prior_product_attempt=validate_attempt(prior_product_attempt,date)
                same_owner_attempt=bool(prior_product_attempt is not None
                    and prior_product_attempt.get('run_id')==existing['run_id']
                    and prior_product_attempt.get('owner')=='ManagerResearchJobService.refresh_workspace_plan'
                    and prior_product_attempt.get('execution_kind')==existing.get('execution_kind')
                    and prior_product_attempt.get('state') in {'SUCCEEDED','SUCCEEDED_EMPTY','PARTIAL'}
                    and prior_product_attempt.get('input_identity')==existing.get('input_identity'))
                try:
                    prepared=get_workspace(service,date,include_saved=False,now=now,**workspace_dates)
                except _ERROR_TYPES as exc:
                    preparation_error=exc
                prepared_cutoff=timestamp((prepared or {}).get('plan_context',{}).get('research_cutoff'))
                reuse_diagnostics=input_identity_diagnostics(existing_workspace,prepared or {},
                    after_cutoff=bool(existing_cutoff is None or prepared_cutoff is None
                        or existing_cutoff>prepared_cutoff))
                compatible=(prepared is not None and same_owner_attempt
                        and reuse_diagnostics['status']=='MATCH'
                        and existing['input_identity']==prepared['input_identity']
                        and existing_workspace.get('semantic_version')==prepared.get('semantic_version')
                        and existing_workspace.get('date_bindings')==prepared.get('date_bindings')
                        and existing_cutoff is not None and existing_cutoff<=now
                        and existing_generated is not None and existing_cutoff is not None
                        and existing_generated<=now
                        and existing_generated.astimezone(timezone.utc)<open_at
                        and existing_cutoff.astimezone(timezone.utc)<=open_at)
                if (compatible and execution_kind=='SCHEDULED_MORNING'
                        and existing.get('execution_kind')=='SCHEDULED_PREOPEN'):
                    value=deepcopy(existing_workspace)
                    value['plan_product']=dict(status='PRESERVED_SCHEDULED_PREOPEN',run_id=existing.get('run_id'),
                        generated_at=existing.get('generated_at'),sha256=existing.get('sha256'),consumed=True,
                        input_identity_diagnostics=reuse_diagnostics,
                        original_owner='ManagerResearchJobService.refresh_workspace_plan')
                    value['workspace_plan_attempt']=deepcopy(prior_product_attempt)
                    return _attach_daily_channels(value)
                if (compatible and existing.get('execution_kind')==execution_kind):
                    value=deepcopy(prepared)
                    value['plan_product']=dict(status='ALREADY_MATERIALIZED',run_id=existing.get('run_id'),
                        generated_at=existing.get('generated_at'),sha256=existing.get('sha256'),
                        execution_kind=existing['execution_kind'],consumed=True,
                        input_identity_diagnostics=reuse_diagnostics,
                        original_owner='ManagerResearchJobService.refresh_workspace_plan')
                    value['workspace_plan_attempt']=deepcopy(prior_product_attempt)
                    return _attach_daily_channels(value)
        run_id=uuid4().hex
        run_root=service.store.root/'workspace_plan_runs'/date
        # Check before the first RUNNING journal write; a reused run ID must
        # not overwrite either an immutable plan or its existing audit record.
        if (service.store._read(run_root/(run_id+'.json')) is not None
                or service.store._read(service.store.root/'workspace_plans'/date/(run_id+'.json')) is not None):
            raise ValueError('WORKSPACE_PLAN_RUN_ALREADY_EXISTS')
        prior=service.store._read(run_root/'latest.json')
        if prior is not None:prior=validate_attempt(prior,date)
        attempt=dict(schema_version=ATTEMPT_SCHEMA,target_trade_date=date,run_id=run_id,
            owner='ManagerResearchJobService.refresh_workspace_plan',state='RUNNING',execution_kind=execution_kind,
            started_at=(now.astimezone(timezone.utc).isoformat(timespec='microseconds') if now is not None else _now()),last_success_at=(prior or {}).get('last_success_at'),failure_reasons=[],**FLAGS)
        def write_attempt() -> None:
            sealed=validate_attempt(seal_attempt(attempt),date)
            service.store._write_atomic(run_root/(run_id+'.json'),sealed)
            service.store._write_atomic(run_root/'latest.json',sealed)
        write_attempt()
        try:
            if preparation_error is not None:
                raise preparation_error
            value=prepared if prepared is not None else get_workspace(
                service,date,include_saved=False,now=now,**workspace_dates)
            completed_at=_now()
            if deadline is not None and timestamp(completed_at) >= deadline.astimezone(timezone.utc):
                raise TimeoutError('WORKSPACE_PLAN_SCHEDULED_COMPLETION_DEADLINE_EXCEEDED')
            failures=sorted(set(value['gaps']))
            state='PARTIAL' if failures else ('SUCCEEDED' if value['stocks'] else 'SUCCEEDED_EMPTY')
            checkpoint()
            product=dict(schema_version=PLAN_SCHEMA,target_trade_date=date,run_id=run_id,
                generated_at=completed_at,owner='ManagerResearchJobService.refresh_workspace_plan',
                execution_kind=execution_kind,input_identity=value['input_identity'],workspace=value,**FLAGS)
            product['read_contract_sha256'] = contract_identity()
            product['sha256']=digest(product)
            root=service.store.root/'workspace_plans'/date
            service.store._write_atomic(root/(run_id+'.json'),product)
            # Read back the immutable product before moving owner state.
            exact_product=service.store._read(root/(run_id+'.json'))
            if (not isinstance(exact_product,Mapping) or dict(exact_product)!=product):
                raise ValueError('WORKSPACE_PLAN_SAVE_READBACK_FAILED')
            # Bind the still-running owner attempt to the exact input before
            # preparing any terminal success state.
            attempt['input_identity']=product['input_identity']
            write_attempt()
            running_attempt=validate_attempt(
                service.store._read(run_root/(run_id+'.json')),date)
            running_latest=validate_attempt(service.store._read(run_root/'latest.json'),date)
            expected_running=validate_attempt(seal_attempt(attempt),date)
            if (running_attempt!=expected_running or running_latest!=expected_running
                    or expected_running.get('state')!='RUNNING'
                    or expected_running.get('run_id')!=product.get('run_id')
                    or expected_running.get('owner')!=product.get('owner')
                    or expected_running.get('execution_kind')!=execution_kind
                    or expected_running.get('input_identity')!=product.get('input_identity')
                    or 'finished_at' in expected_running or 'success_scope' in expected_running):
                raise ValueError('WORKSPACE_PLAN_ATTEMPT_READBACK_FAILED')
            finished_at=_now()
            if deadline is not None and timestamp(finished_at) >= deadline.astimezone(timezone.utc):
                raise TimeoutError('WORKSPACE_PLAN_SCHEDULED_TERMINAL_DEADLINE_EXCEEDED')
            attempt.update(state=state,finished_at=finished_at,last_success_at=product['generated_at'],
                input_identity=value['input_identity'],input_coverage=value['existing_material_coverage'],
                summary=value['summary'],failure_reasons=failures,
                success_scope='EXACT_DATE_RESEARCH_PLAN_NOT_FORMAL_RECOMMENDATION_OR_NATURAL_CAPTURE')
            planned_terminal=validate_attempt(seal_attempt(attempt),date)
            # The public reader needs a terminal owner attempt. Verify the
            # complete intended product/run/SHA/identity/owner contract via a
            # private read view before persisting terminal success.
            result=_verify_plan_commit_before_publication(service.store,date,value,
                product,planned_terminal)
            checkpoint()
            if deadline is not None and timestamp(_now()) >= deadline.astimezone(timezone.utc):
                raise TimeoutError('WORKSPACE_PLAN_SCHEDULED_TERMINAL_DEADLINE_EXCEEDED')
            write_attempt()
            terminal=validate_attempt(service.store._read(run_root/(run_id+'.json')),date)
            terminal_latest=validate_attempt(service.store._read(run_root/'latest.json'),date)
            if terminal!=planned_terminal or terminal_latest!=planned_terminal:
                raise ValueError('WORKSPACE_PLAN_ATTEMPT_READBACK_FAILED')
            # Only the exact commit already checked through the original reader
            # becomes public latest.
            service.store._write_atomic(root/'latest.json',product)
            published=_read_plan(service.store,date)
            if not isinstance(published,Mapping) or dict(published)!=product:
                raise ValueError('WORKSPACE_PLAN_SAVE_READBACK_FAILED')
            result['workspace_plan_attempt']=terminal
            result['workspace_plan_product_attempt']=deepcopy(terminal)
            return _attach_daily_channels(result)
        except _ERROR_TYPES as exc:
            attempt.pop('success_scope',None)
            attempt.update(state='FAILED',finished_at=_now(),last_success_at=(prior or {}).get('last_success_at'),
                failure_reasons=['WORKSPACE_PLAN_REFRESH_FAILED:'+type(exc).__name__])
            write_attempt()
            # Failed refreshes must not replace an older sealed success pointer.
            # The failed run and attempt remain separately addressable.
            if previous_plan is not None:
                latest_path=service.store.root/'workspace_plans'/date/'latest.json'
                latest=service.store._read(latest_path)
                if isinstance(latest,Mapping) and latest.get('run_id')==run_id:
                    service.store._write_atomic(latest_path,previous_plan)
            raise
