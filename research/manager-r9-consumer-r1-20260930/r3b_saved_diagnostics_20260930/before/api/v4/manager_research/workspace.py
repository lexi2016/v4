"""Original manager-service integration: read existing owners; record real refreshes.

GET does not create receipts, collect data or run a producer. The existing
catalyst refresh is still the only catalyst producer. Journals below its store
record actual MANUAL_REFRESH attempts, never fabricated historical/natural runs.
"""
from __future__ import annotations
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
from .workspace_read_control import phase, count, checkpoint, project, READ_CONTRACT, contract_identity

ATTEMPT_SCHEMA = 'v4.manager_research.workspace_attempt.v1'
_ERROR_TYPES = (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


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
            or (row.get('execution_kind') not in {'MANUAL_REFRESH','SCHEDULED_PREOPEN'} and not (
                row.get('execution_kind') == 'SCHEDULED_REFRESH' and
                row.get('owner') == 'ManagerResearchJobService.refresh_announcements'))
            or (row.get('execution_kind') == 'SCHEDULED_PREOPEN' and
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


def get_workspace(service: Any,target_trade_date: str, *, include_saved: bool = True,
                  view: str = 'dynamic', now: datetime | None = None) -> dict:
    date = date_token(target_trade_date)
    clock = now if now is not None else datetime.now(timezone.utc)
    if clock.tzinfo is None or view not in {'auto','historical','dynamic'}:
        raise ValueError('WORKSPACE_VIEW_OR_CLOCK_INVALID')
    if include_saved and (view == 'historical' or
            (view == 'auto' and date < clock.astimezone(HK).strftime('%Y%m%d'))):
        if date >= clock.astimezone(HK).strftime('%Y%m%d'):
            raise ValueError('WORKSPACE_HISTORICAL_DATE_NOT_PAST')
        from .workspace_history import read_history
        return read_history(service, date)
    result = _compute_workspace(service, date, include_saved=include_saved,
                                context=plan_context(date, now=clock))
    result['read_context'] = dict(mode='CURRENT_DYNAMIC_PREVIEW',
        status='VERIFIED_WITH_GAPS' if result['gaps'] else 'VERIFIED',
        as_of=result['plan_context']['research_cutoff'],
        candidate_count_known=bool(result['stocks']) or not result['gaps'], contract=READ_CONTRACT)
    return result


def _compute_workspace(service: Any, date: str, *, include_saved: bool = True, context: dict) -> dict:
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
        recapture_date=str(context.get('market_session') or '')
        reader=service._close_observation_reader
        if recapture_date and hasattr(reader,'read_close_recapture'):
            try:
                close_recapture=reader.read_close_recapture(recapture_date)
            except _ERROR_TYPES as exc:
                close_recapture=dict(status='FAILED',source_trade_date=recapture_date,
                    cannot_confirm=['CLOSE_RECAPTURE_ORIGINAL_READER_FAILED:'+type(exc).__name__])
        else:
            close_recapture=dict(status='NOT_RUN',source_trade_date=recapture_date or None,
                cannot_confirm=['CLOSE_RECAPTURE_ORIGINAL_READER_NOT_BOUND'])
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
    material_discovery['cards'],connect_rejections=filter_cards(material_discovery['cards'],connect_scope,target_date=date)
    material_discovery['rejected_relations']=[*material_discovery.get('rejected_relations',[]),*connect_rejections]
    material_discovery['coverage']['target_connect_card_count']=len(material_discovery['cards'])
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
        materials=selection_materials,
        discovered_cards=discovery_cards, plan_context=context,
        price_quotes=quote_evidence['quotes'], discovery_rejections=material_discovery.get('rejected_relations',[]),
        attempts=attempts, source_gaps=[*existing['gaps'],*discovery['gaps'],*material_discovery['gaps'],
            *quote_evidence['gaps'],*market_screen.get('gaps',[]),*announcement_inputs['gaps'],
            *connect_scope.get('gaps',[])], previous=previous, market_screen=market_screen)
    with phase('pure_workspace_projection'):
        value = project(service, 'workspace_projection', [date, inputs], lambda: build_workspace(date, **inputs))
    value=gate_workspace(value,connect_scope)
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
    value['us_market_attention'] = us_market
    from .research_attention import build_research_attention
    scoped_screen,scoped_announcement_lane=evidence_view(market_screen,value['announcement_observation'],connect_scope)
    with phase('research_attention_projection'):
        research_attention = build_research_attention(
            date, context=context, market_screen=scoped_screen, stocks=value.get('stocks', []),
            material_cards=material_discovery.get('cards', []), themes=value.get('themes', []),
            announcement_observation=scoped_announcement_lane, us_market=us_market,
        )
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
    }
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
    if announcement_review.get('product_identity'):
        identity_extensions.append(announcement_review['product_identity']['sha256'])
    us_identity = us_market.get('source_identity') if isinstance(us_market, Mapping) else None
    if isinstance(us_identity, Mapping) and isinstance(us_identity.get('payload_sha256'), str):
        identity_extensions.append(us_identity['payload_sha256'])
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
            or row.get('execution_kind','MANUAL_REFRESH') not in {'MANUAL_REFRESH','SCHEDULED_PREOPEN'}
            or timestamp(row.get('generated_at')) is None):
        raise ValueError('WORKSPACE_STORED_PLAN_INVALID')
    return row


def _readback_plan(store: Any,date: str,current: dict) -> dict:
    from copy import deepcopy
    try:
        saved=_read_plan(store,date)
        attempt=store._read(store.root/'workspace_plan_runs'/date/'latest.json')
        if attempt is not None:attempt=validate_attempt(attempt,date)
    except _ERROR_TYPES as exc:
        # Tampered/stale stored results never hide a freshly verified read-only
        # projection, and are NOT presented as successfully read back.
        current['plan_product']=dict(status='READBACK_FAILED',reason=type(exc).__name__)
        return current
    saved_cutoff=timestamp(((saved or {}).get('workspace') or {}).get('plan_context',{}).get('research_cutoff'))
    current_cutoff=timestamp(current.get('plan_context',{}).get('research_cutoff'))
    after_cutoff=bool(saved is not None and (saved_cutoff is None or current_cutoff is None or saved_cutoff>current_cutoff))
    same=(saved is not None and not after_cutoff and saved['input_identity']==current['input_identity']
          and saved['workspace'].get('semantic_version')==current.get('semantic_version'))
    value=deepcopy(saved['workspace']) if same else current
    # Persisted stock plans do not freeze live owner execution status. An
    # unchanged material fingerprint must not conceal a later failed attempt.
    if same:
        for key in ('lanes','runtime_gaps','run_accounting','continuity_gap','market_screen','market_screen_evidence','owner_chain','announcement_review','announcement_observation','us_market_attention','research_attention','stage_read_timing','repair_contract'):
            if key in current:value[key]=deepcopy(current[key])
        value['runtime_status_read_at']=current['plan_context']['research_cutoff']
    value['plan_product']=dict(status='CURRENT' if same else ('PLAN_AFTER_READ_CUTOFF' if after_cutoff else 'STALE_INPUTS_CHANGED' if saved else 'NOT_MATERIALIZED'),
        run_id=saved.get('run_id') if saved else None,generated_at=saved.get('generated_at') if saved else None,
        sha256=saved.get('sha256') if saved else None,original_owner='ManagerResearchJobService.refresh_workspace_plan',
        last_checked_at=current['plan_context']['research_cutoff'],consumed=same)
    value['workspace_plan_attempt']=attempt
    value['observation_mode']='EXACT_DATE_PLAN_READBACK' if same else 'READ_ONLY_EXISTING_OWNER_PREVIEW'
    return value


def refresh_workspace_plan(service: Any,target_trade_date: str, *, execution_kind: str = 'MANUAL_REFRESH',
                           now: datetime | None = None, deadline: datetime | None = None) -> dict:
    """Persist an exact-date plan from existing verified owners only.

    ``SCHEDULED_PREOPEN`` is reserved for the bounded pre-open autorun.  It
    uses its supplied aware clock for both the read cutoff and product timing;
    late/backfill eligibility is enforced by ``workspace_plan_autorun``.
    """
    if execution_kind not in {'MANUAL_REFRESH','SCHEDULED_PREOPEN'}:
        raise ValueError('WORKSPACE_PLAN_EXECUTION_KIND_INVALID')
    if execution_kind == 'SCHEDULED_PREOPEN' and (now is None or now.tzinfo is None):
        raise ValueError('WORKSPACE_PLAN_SCHEDULED_CLOCK_REQUIRED')
    if execution_kind == 'SCHEDULED_PREOPEN' and deadline is None:
        raise ValueError('WORKSPACE_PLAN_SCHEDULED_DEADLINE_REQUIRED')
    if deadline is not None and deadline.tzinfo is None:
        raise ValueError('WORKSPACE_PLAN_DEADLINE_MUST_BE_AWARE')
    if execution_kind != 'SCHEDULED_PREOPEN' and deadline is not None:
        raise ValueError('WORKSPACE_PLAN_DEADLINE_ONLY_FOR_SCHEDULED_PREOPEN')
    if execution_kind == 'SCHEDULED_PREOPEN' and now.astimezone(timezone.utc) >= deadline.astimezone(timezone.utc):
        raise ValueError('WORKSPACE_PLAN_SCHEDULED_DEADLINE_EXPIRED')
    date=date_token(target_trade_date)
    with service.store._transaction(date,'workspace-plan-refresh'):
        prepared=None
        if execution_kind == 'SCHEDULED_PREOPEN':
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
                prepared=get_workspace(service,date,include_saved=False,now=now)
                if (existing['input_identity']==prepared['input_identity']
                        and existing_workspace.get('semantic_version')==prepared.get('semantic_version')
                        and existing_cutoff is not None and existing_cutoff<=now
                        and existing_generated is not None and existing_cutoff is not None
                        and existing_generated.astimezone(timezone.utc)<open_at
                        and existing_cutoff.astimezone(timezone.utc)<=open_at):
                    from copy import deepcopy
                    value=deepcopy(existing_workspace)
                    value['plan_product']=dict(status='ALREADY_MATERIALIZED',run_id=existing.get('run_id'),
                        generated_at=existing.get('generated_at'),sha256=existing.get('sha256'),
                        original_owner='ManagerResearchJobService.refresh_workspace_plan')
                    return value
        run_id=uuid4().hex
        run_root=service.store.root/'workspace_plan_runs'/date
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
            value=prepared if prepared is not None else get_workspace(service,date,include_saved=False,now=now)
            failures=sorted(set(value['gaps']))
            state='PARTIAL' if failures else ('SUCCEEDED' if value['stocks'] else 'SUCCEEDED_EMPTY')
            completed_at=_now()
            if deadline is not None and timestamp(completed_at) >= deadline.astimezone(timezone.utc):
                raise TimeoutError('WORKSPACE_PLAN_SCHEDULED_COMPLETION_DEADLINE_EXCEEDED')
            product=dict(schema_version=PLAN_SCHEMA,target_trade_date=date,run_id=run_id,
                generated_at=completed_at,owner='ManagerResearchJobService.refresh_workspace_plan',
                execution_kind=execution_kind,input_identity=value['input_identity'],workspace=value,**FLAGS)
            product['read_contract_sha256'] = contract_identity()
            product['sha256']=digest(product)
            root=service.store.root/'workspace_plans'/date
            service.store._write_atomic(root/(run_id+'.json'),product)
            service.store._write_atomic(root/'latest.json',product)
            attempt.update(state=state,finished_at=_now(),last_success_at=product['generated_at'],
                input_identity=value['input_identity'],input_coverage=value['existing_material_coverage'],
                summary=value['summary'],failure_reasons=failures,
                success_scope='EXACT_DATE_RESEARCH_PLAN_NOT_FORMAL_RECOMMENDATION_OR_NATURAL_CAPTURE')
            write_attempt()
            return _readback_plan(service.store,date,value)
        except _ERROR_TYPES as exc:
            attempt.update(state='FAILED',finished_at=_now(),failure_reasons=['WORKSPACE_PLAN_REFRESH_FAILED:'+type(exc).__name__])
            write_attempt()
            raise
