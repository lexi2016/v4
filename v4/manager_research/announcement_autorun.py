"""Bounded automatic increments of the existing announcement owner.

No network implementation or second producer lives here. Every response and
revision is owned by the original HKEX provider/MaterialStore/store validators.
All numeric policy values are PROPOSAL_ONLY and require explicit local opt-in.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time, timedelta
from typing import Any, Mapping
from uuid import uuid4
import re

from . import workspace_announcements as owner
from .announcement_source import CaptureBudget, PARSER_VERSION, safe_reason
from .workspace_projection import FLAGS, HK, date_token, digest, timestamp
from .workspace_plan import plan_context

SCHEMA = 'v4.manager_research.announcement_autorun.v1'
POLICIES = {
    'BALANCED_V1': dict(interval_seconds=60, fair_count=20, priority_count=4),
    'LOW_LOAD_V1': dict(interval_seconds=120, fair_count=10, priority_count=2),
}
MAX_RUNS = 2048  # Per day, fail closed; never silently evict adverse evidence.


def policy_due(now: datetime, policy: str) -> bool:
    """The proposal's HK calendar/window, including a hard tail exclusion zone."""
    from contracts.trading_calendar import load_market_calendar, resolve_market_states, TradingDayState
    if policy not in POLICIES or now.tzinfo is None:
        return False
    local = now.astimezone(HK)
    if not time(6) <= local.time().replace(tzinfo=None) < time(23):
        return False
    # Do not start a 50s child which could cross into the 15:20 exclusion.
    if time(15, 19) <= local.time().replace(tzinfo=None) < time(15, 40):
        return False
    states = resolve_market_states(load_market_calendar(), local.strftime('%Y%m%d'))
    return states['hk_securities'] in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}


def _calendar_day_market_window(date: str, context: Mapping[str, Any]) -> tuple[str, str, str]:
    """Capture the selected HK publication day from local midnight."""
    day = date_token(date)
    cutoff = timestamp(context.get('research_cutoff'))
    start = datetime.strptime(day, '%Y%m%d').replace(tzinfo=HK)
    if cutoff is None or cutoff.astimezone(HK).strftime('%Y%m%d') != day or start > cutoff:
        raise ValueError('HKEX_MARKET_CALENDAR_DAY_CUTOFF_INVALID')
    return start.isoformat(), 'HK_CALENDAR_DAY_V1', day


def _official_market_window(service: Any,date: str,context: Mapping[str,Any],state: Mapping[str,Any]) -> tuple[str,str,str]:
    """Resume from the latest verified full directory, or use prior HK close."""
    from .announcement_source import verify_official_market_directory
    cutoff=timestamp(context.get('research_cutoff'))
    if cutoff is None:raise ValueError('HKEX_MARKET_QUERY_CUTOFF_INVALID')
    products=_ordered_products(service,date,state) if state.get('runs') else []
    start=None;mode=None;from_date=None
    for product in reversed(products):
        market=product.get('market_directory')
        if (not isinstance(market,Mapping) or market.get('status')!='COMPLETE'
                or market.get('directory_exhaustion')!='VERIFIED'):
            continue
        try:
            owner._check_sources(service,product)
            valid=verify_official_market_directory(service._material_store,market,
                owner_generated_at=product['generated_at'])
        except (ValueError,RuntimeError,OSError,KeyError,TypeError):
            valid=False
        if not valid:continue
        cursor=timestamp(market.get('query_cutoff'))
        if cursor is None or cursor>cutoff:continue
        start=cursor-timedelta(minutes=1)
        if start>cutoff:continue
        mode='LAST_TRUSTED_COMPLETE_CURSOR_MINUS_1M';from_date=start.strftime('%Y%m%d')
        break
    if start is None:
        actual,_query=owner._targeted_hkex_context(date,now=cutoff)
        source_window=actual.get('targeted_source_window')
        start=timestamp(source_window.get('start')) if isinstance(source_window,Mapping) else None
        source_dates=source_window.get('source_dates') if isinstance(source_window,Mapping) else None
        if (start is None or start>cutoff or not isinstance(source_dates,list) or len(source_dates)!=2
                or source_dates[1]!=date):
            raise ValueError('HKEX_MARKET_FALLBACK_PREVIOUS_SESSION_WINDOW_INVALID')
        mode='FALLBACK_PREVIOUS_HK_SESSION_CLOSE';from_date=str(source_dates[0])
    queue=_market_body_retry_queue(service,products)
    if queue:
        oldest=min(timestamp(item['row']['published_at']) for item in queue)
        if oldest is not None:
            retry_start=oldest-timedelta(minutes=1)
            if retry_start<start:
                start=retry_start;from_date=min(from_date,start.strftime('%Y%m%d'))
            mode += '_WITH_BODY_QUEUE_RETRY'
    if start>cutoff:raise ValueError('HKEX_MARKET_FALLBACK_PREVIOUS_SESSION_WINDOW_INVALID')
    return start.isoformat(),mode,from_date


def _market_body_retry_queue(service: Any,products: list[Mapping[str,Any]]) -> list[dict]:
    """Return still-unresolved official PDF rows from verified owner products."""
    latest={};attempts={}
    for product in products:
        if not isinstance(product.get('market_directory'),Mapping):continue
        owner._check_sources(service,product)
        for doc in product.get('market_documents',[]):
            news_id=doc.get('news_id')
            if doc.get('body_status')=='BODY_CAPTURED_UNASSESSED':latest[news_id]=None
            elif doc.get('body_status')=='BODY_FETCH_FAILED':
                attempts[news_id]=attempts.get(news_id,0)+1
                latest[news_id]=deepcopy(doc)
        for doc in product.get('market_pending_documents',[]):
            if doc.get('body_status')=='BODY_NOT_CAPTURED':latest[doc.get('news_id')]=deepcopy(doc)
    unresolved=[doc for doc in latest.values() if isinstance(doc,dict)]
    order=lambda doc:(timestamp(doc.get('row',{}).get('published_at')) or datetime.max.replace(tzinfo=HK),
        doc.get('news_id',''))
    pending=sorted((doc for doc in unresolved if attempts.get(doc.get('news_id'),0)==0),key=order)
    failed=sorted((doc for doc in unresolved if attempts.get(doc.get('news_id'),0)>0),key=order)
    # Alternate fresh and failed work inside the fixed four-document budget:
    # repeated pending rows cannot starve retries, and retries cannot consume
    # every slot while new directory rows continue to arrive.
    queue=[]
    while pending or failed:
        if pending:queue.append(pending.pop(0))
        if failed:queue.append(failed.pop(0))
    return queue


def _market_coverage_summary(market: Mapping[str, Any], date: str) -> dict:
    start=timestamp(market.get('publication_window_start'))
    cutoff=timestamp(market.get('query_cutoff'))
    expected_start=datetime.strptime(date,'%Y%m%d').replace(tzinfo=HK)
    identity_valid=(re.fullmatch(r'[0-9a-f]{32}',str(market.get('product_run_id') or '')) is not None
        and re.fullmatch(r'[0-9a-f]{64}',str(market.get('product_sha256') or '')) is not None)
    verified=(market.get('status')=='COMPLETE' and market.get('directory_exhaustion')=='VERIFIED'
        and market.get('source_scope')=='HKEX_OFFICIAL_FULL_MARKET_DIRECTORY_V1'
        and market.get('from_date')==date and market.get('to_date')==date
        and market.get('window_mode')=='HK_CALENDAR_DAY_V1' and start==expected_start
        and cutoff is not None and cutoff.astimezone(HK).strftime('%Y%m%d')==date
        and type(market.get('record_count')) is int and market.get('record_count')>=0
        and market.get('loaded_record')==market.get('record_count')
        and market.get('captured_row_count')==market.get('record_count')
        and market.get('unique_news_id_count')==market.get('record_count')
        and market.get('captured_page_count')==market.get('expected_page_count')
        and identity_valid and not market.get('gaps'))
    return dict(status='VERIFIED' if verified else 'CANNOT_CONFIRM',
        target_trade_date=date,source_scope=market.get('source_scope'),
        from_date=market.get('from_date'),to_date=market.get('to_date'),
        window_mode=market.get('window_mode'),publication_window_start=market.get('publication_window_start'),
        query_cutoff=market.get('query_cutoff'),record_count=market.get('record_count'),
        loaded_record=market.get('loaded_record'),captured_page_count=market.get('captured_page_count'),
        expected_page_count=market.get('expected_page_count'),captured_row_count=market.get('captured_row_count'),
        unique_news_id_count=market.get('unique_news_id_count'),product_run_id=market.get('product_run_id'),
        product_revision=market.get('product_revision'),product_sha256=market.get('product_sha256'),
        gaps=list(market.get('gaps') or []),body_gaps=list(market.get('body_gaps') or []))


def _valid_state(value: Any, date: str) -> dict:
    if (not isinstance(value, dict) or value.get('schema_version') != SCHEMA
            or value.get('target_trade_date') != date or value.get('owner') != owner.OWNER
            or value.get('sha256') != owner._seal(value)['sha256']
            or any(value.get(k) is not v for k, v in FLAGS.items())
            or not isinstance(value.get('runs'), dict) or len(value['runs']) > MAX_RUNS
            or type(value.get('fair_cursor')) is not int or value['fair_cursor'] < 0
            or type(value.get('priority_cursor')) is not int or value['priority_cursor'] < 0):
        raise ValueError('ANNOUNCEMENT_AUTORUN_STATE_INVALID')
    for run, entry in value['runs'].items():
        if (not re.fullmatch('[0-9a-f]{32}', run) or not isinstance(entry, dict)
                or type(entry.get('revision')) is not int or entry['revision'] < 1
                or not re.fullmatch('[0-9a-f]{64}', str(entry.get('sha256', '')))):
            raise ValueError('ANNOUNCEMENT_AUTORUN_RUN_REFERENCE_INVALID')
    return deepcopy(value)


def _markers(service: Any, date: str) -> dict:
    directory = f'workspace_announcements/{date}/_auto_commits'
    result = {}
    for name in service.store._io.files(directory):
        if not re.fullmatch(r'[0-9a-f]{32}\.json', name):
            raise ValueError('ANNOUNCEMENT_COMMIT_NAME_INVALID')
        marker = service.store._read(service.store.root / directory / name)
        if (marker is None or marker.get('sha256') != owner._seal(marker)['sha256']
                or marker.get('target_trade_date') != date or marker.get('run_id') != name[:-5]
                or marker.get('owner') != owner.OWNER):
            raise ValueError('ANNOUNCEMENT_COMMIT_INVALID')
        result[name[:-5]] = marker['product']
    if len(result) > MAX_RUNS:
        raise ValueError('ANNOUNCEMENT_RUN_RETENTION_BOUND_EXCEEDED')
    return result


def _load_product(service: Any, date: str, run: str, reference: Mapping[str, Any]) -> dict:
    product = service.store._read(service.store.root / 'workspace_announcements' / date / run / (str(reference['revision'])+'.json'))
    product = owner.validate_product(product, date)
    if product['run_id'] != run or product['sha256'] != reference['sha256']:
        raise ValueError('ANNOUNCEMENT_AUTORUN_REFERENCE_MISMATCH')
    return product


def _save_state(service: Any, date: str, state: dict) -> None:
    state = owner._seal(state)
    _valid_state(state, date)
    service.store._write_atomic(service.store.root / 'workspace_announcements' / date / 'autorun.json', state)


def _commit(service: Any, date: str, state: dict, product: dict) -> None:
    product.update(generated_at=owner._now(), parser_revision=PARSER_VERSION,
                   execution_kind='SCHEDULED_REFRESH', natural_run_verified=False)
    product = owner._seal(product)
    owner.validate_product(product, date)
    owner._check_sources(service, product)
    root = service.store.root / 'workspace_announcements' / date
    service.store._write_atomic(root / product['run_id'] / (str(product['revision'])+'.json'), product)
    ref = dict(revision=product['revision'], sha256=product['sha256'])
    # Publish marker first. A crash between these two publications causes a
    # READBACK_FAILED, never a stale success; next explicit writer repairs it
    # only after revalidating ALL original products and source bytes.
    marker = owner._seal(dict(owner=owner.OWNER, target_trade_date=date, run_id=product['run_id'], product=ref, **FLAGS))
    service.store._write_atomic(root / '_auto_commits' / (product['run_id']+'.json'), marker)
    state['runs'][product['run_id']] = ref
    _save_state(service, date, state)


def retain_manual_product(service: Any, date: str, product: Mapping[str, Any]) -> None:
    """Keep explicit manual results visible once the automatic lane is active."""
    root = service.store.root / 'workspace_announcements' / date
    state = service.store._read(root / 'autorun.json')
    if state is None:
        return
    state = _valid_state(state, date)
    if _markers(service, date) != state['runs']:
        raise ValueError('ANNOUNCEMENT_AUTORUN_COMMIT_SET_MISMATCH')
    if product['run_id'] not in state['runs'] and len(state['runs']) >= MAX_RUNS:
        raise ValueError('ANNOUNCEMENT_RUN_RETENTION_BOUND_EXCEEDED')
    owner.validate_product(product, date)
    owner._check_sources(service, product)
    ref = dict(revision=product['revision'], sha256=product['sha256'])
    marker = owner._seal(dict(owner=owner.OWNER, target_trade_date=date,
                             run_id=product['run_id'], product=ref, **FLAGS))
    service.store._write_atomic(root / '_auto_commits' / (product['run_id']+'.json'), marker)
    state['runs'][product['run_id']] = ref
    _save_state(service, date, state)


def _ordered_products(service: Any, date: str, state: Mapping[str, Any]) -> list[dict]:
    products = [_load_product(service, date, run, ref) for run, ref in state['runs'].items()]
    return sorted(products, key=lambda p: (p['context']['research_cutoff'], p['run_id']))


def scheduled_refresh(service: Any, date: str, schedule: Mapping[str, Any]) -> dict:
    """Persist setup failures too, without forging source coverage or a cutoff."""
    from .workspace import ATTEMPT_SCHEMA, seal_attempt, validate_attempt
    date=date_token(date)
    now=timestamp(owner._now())
    # Off-window or malformed caller input is a rejected dispatch, not a run.
    if (not isinstance(schedule,Mapping) or now is None or
            not policy_due(now,schedule.get('policy')) or now.astimezone(HK).strftime('%Y%m%d')!=date):
        raise ValueError('ANNOUNCEMENT_SCHEDULE_OUTSIDE_APPROVED_PROPOSAL_WINDOW')
    capture_mode=schedule.get('capture_mode')
    if capture_mode not in {None,'HK_CALENDAR_DAY_V1'}:
        raise ValueError('ANNOUNCEMENT_SCHEDULE_CAPTURE_MODE_INVALID')
    catalog=None;catalog_error=None
    if capture_mode=='HK_CALENDAR_DAY_V1':
        # Every new calendar-day scheduled invocation must fetch fresh pages.
        # Explicit saved-ref resume remains available through its separate API;
        # reusing this date's latest product would make a later run look fresh.
        try:
            catalog=owner.refresh_eastmoney_date_catalog(service,date,date,
                resume=False,force_fresh=True)
        except Exception as exc:
            catalog_error=safe_reason(exc,'EASTMONEY_DAILY_CATALOG_CAPTURE_FAILED')
    runroot=service.store.root/'workspace_announcement_runs'/date
    with service.store._transaction(date,'workspace-announcements'):
        prior=service.store._read(runroot/'latest.json')
        if prior is not None:prior=validate_attempt(prior,date)
        started=owner._now()
        try:
            return _scheduled_refresh(service,date,schedule,catalog=catalog,catalog_error=catalog_error)
        except BaseException as exc:
            current=service.store._read(runroot/'latest.json')
            # The inner capture already records ordinary or cancellation errors.
            if current==prior:
                attempt=dict(schema_version=ATTEMPT_SCHEMA,owner=owner.OWNER,target_trade_date=date,
                    run_id=uuid4().hex,state='FAILED',execution_kind='SCHEDULED_REFRESH',
                    started_at=started,finished_at=owner._now(),last_success_at=(prior or {}).get('last_success_at'),
                    failure_reasons=[safe_reason(exc,'ANNOUNCEMENT_AUTORUN_ADMISSION_FAILED')],
                    input_coverage={'status':'UNVERIFIED','selected_issuer_count':None},
                    policy=schedule.get('policy'),policy_status='PROPOSAL_ONLY',**FLAGS)
                attempt=validate_attempt(seal_attempt(attempt),date)
                service.store._write_atomic(runroot/(attempt['run_id']+'.json'),attempt)
                service.store._write_atomic(runroot/'latest.json',attempt)
            raise


def _scheduled_refresh(service: Any, date: str, schedule: Mapping[str, Any], *,
                       catalog: Mapping[str, Any] | None = None,
                       catalog_error: str | None = None) -> dict:
    """Called only by explicit POST owner use or the opt-in bounded worker.

    Duplicate time buckets cause NO provider request. Cursor reservation occurs
    before I/O, so a repeatedly failing issuer cannot hold all higher codes.
    A selected-but-unqueried issuer is *not* counted as covered.
    """
    from .workspace import ATTEMPT_SCHEMA, seal_attempt, validate_attempt
    date = date_token(date)
    if not isinstance(schedule, Mapping) or set(schedule) - {
            'policy', 'now', 'priority_codes', 'execution_identity', 'capture_mode'}:
        raise ValueError('ANNOUNCEMENT_SCHEDULE_FIELDS_INVALID')
    calendar_day_capture=schedule.get('capture_mode')=='HK_CALENDAR_DAY_V1'
    if schedule.get('capture_mode') not in {None,'HK_CALENDAR_DAY_V1'}:
        raise ValueError('ANNOUNCEMENT_SCHEDULE_CAPTURE_MODE_INVALID')
    policy = schedule.get('policy')
    now = timestamp(owner._now())
    asserted = timestamp(schedule.get('now'))
    if (asserted is None or now is None or abs((asserted-now).total_seconds()) > 5
            or now.astimezone(HK).strftime('%Y%m%d') != date or not policy_due(now, policy)):
        raise ValueError('ANNOUNCEMENT_SCHEDULE_OUTSIDE_APPROVED_PROPOSAL_WINDOW')
    config = POLICIES[policy]
    bucket = int(now.timestamp()) // config['interval_seconds']
    root = service.store.root / 'workspace_announcements' / date
    runroot = service.store.root / 'workspace_announcement_runs' / date
    with service.store._transaction(date, 'workspace-announcements'):
        context = owner._daily_context(date, now=now) if calendar_day_capture else plan_context(date, now=now)
        names, witness = owner._master(service, context)
        codes = sorted(names)
        scope_id = digest([witness, codes])
        priorities = schedule.get('priority_codes', [])
        if (not isinstance(priorities, list) or len(priorities) > 20 or len(set(priorities)) != len(priorities)
                or any(c not in names for c in priorities)):
            raise ValueError('ANNOUNCEMENT_PRIORITY_SCOPE_INVALID')
        prior = service.store._read(runroot / 'latest.json')
        if prior is not None:
            prior = validate_attempt(prior, date)
        state = service.store._read(root / 'autorun.json')
        if state is None:
            if _markers(service, date):
                raise ValueError('ANNOUNCEMENT_AUTORUN_INDEX_MISSING_WITH_COMMITTED_RUNS')
            state = dict(schema_version=SCHEMA, owner=owner.OWNER, target_trade_date=date,
                         scope_identity=scope_id, scope=codes, identity_witness=witness, fair_cursor=0, priority_cursor=0, runs={}, **FLAGS)
        else:
            state = _valid_state(state, date)
            if state['scope_identity'] != scope_id:
                raise ValueError('ANNOUNCEMENT_AUTORUN_NATIVE_SCOPE_CHANGED')
            markers = _markers(service, date)
            if state['runs'] != markers:
                # Only a publish-ahead marker can be recovered, never a missing
                # marker or a retrograde revision (which could erase risk).
                if any(r not in markers or markers[r]['revision'] < ref['revision'] for r, ref in state['runs'].items()):
                    raise ValueError('ANNOUNCEMENT_AUTORUN_COMMIT_SET_MISMATCH')
                for run, ref in markers.items():
                    owner._check_sources(service, _load_product(service, date, run, ref))
                state['runs'] = markers
                _save_state(service, date, state)
        # Policy changes cannot reset duplicate admission in the same elapsed
        # interval, or reset the fair cursor.
        last = timestamp(state.get('last_started_at'))
        if (last is not None and (now-last).total_seconds() < config['interval_seconds']
                and not calendar_day_capture):
            return owner.read(service, date, context)
        if len(state['runs']) >= MAX_RUNS:
            raise ValueError('ANNOUNCEMENT_RUN_RETENTION_BOUND_EXCEEDED')
        fair = [] if calendar_day_capture else [codes[(state['fair_cursor']+i) % len(codes)]
            for i in range(min(config['fair_count'],len(codes)))]
        priority = ([] if calendar_day_capture else
                    [priorities[(state['priority_cursor']+i) % len(priorities)]
                     for i in range(min(config['priority_count'], len(priorities)))] if priorities else [])
        selected = priority + [c for c in fair if c not in priority]
        # A daily full-market pass does not reserve or advance bounded issuer
        # cursors; subsequent preopen cycles retain their fair stride.
        if not calendar_day_capture:
            state.update(fair_cursor=(state['fair_cursor']+len(fair)) % len(codes),
                         priority_cursor=state['priority_cursor']+len(priority))
        state.update(last_started_at=owner._now(), last_bucket=bucket, policy=policy)
        _save_state(service, date, state)
        manual = service.store._read(root / 'latest.json')
        if manual is not None and manual.get('run_id') not in state['runs']:
            retain_manual_product(service, date, owner.validate_product(manual,date))
            state = _valid_state(service.store._read(root/'autorun.json'),date)
        catalog_product=(catalog.get('catalog') if isinstance(catalog,Mapping)
                         and isinstance(catalog.get('catalog'),Mapping) else None)
        catalog_summary=(dict(publication_date=catalog.get('publication_date'),
            readback_status=catalog.get('readback_status'),status=(catalog_product or {}).get('status'),
            source_scope=(catalog_product or {}).get('source_scope'),run_id=(catalog_product or {}).get('run_id'),
            sha256=(catalog_product or {}).get('sha256'),captured_page_count=(catalog_product or {}).get('captured_page_count'),
            total_hits=(catalog_product or {}).get('total_hits')) if calendar_day_capture and isinstance(catalog,Mapping) else None)
        attempt = dict(schema_version=ATTEMPT_SCHEMA, target_trade_date=date, run_id=uuid4().hex,
            owner=owner.OWNER, state='RUNNING', execution_kind='SCHEDULED_REFRESH', started_at=owner._now(),
            last_success_at=(prior or {}).get('last_success_at'), failure_reasons=[], selected_issuers=selected,
            fair_issuers=fair, priority_issuers=priority, policy=policy, policy_status='PROPOSAL_ONLY',
            execution_identity=schedule.get('execution_identity',{'status':'CALLER_IDENTITY_UNVERIFIED'}),
            cutoff=context['research_cutoff'], previous_attempt_interrupted=bool(prior and prior['state']=='RUNNING'), **FLAGS)
        def journal() -> None:
            sealed = validate_attempt(seal_attempt(attempt), date)
            service.store._write_atomic(runroot / (attempt['run_id']+'.json'), sealed)
            service.store._write_atomic(runroot / 'latest.json', sealed)
        journal()
        budget = CaptureBudget()
        try:
            if service._material_store is None or getattr(service.source_provider, '_material_store', None) is not service._material_store:
                raise ValueError('ANNOUNCEMENT_ORIGINAL_SHARED_STORE_NOT_BOUND')
            order = selected + [c for c in codes if c not in selected]
            product = dict(schema_version=owner.SCHEMA, owner=owner.OWNER, target_trade_date=date, run_id=uuid4().hex,
                revision=1, context=context, identity_witness=witness, scope=codes, scan_order=order,
                scope_identity=scope_id, next_index=0, queries=[], documents=[], pending_documents=[], **FLAGS)
            if calendar_day_capture:
                # This daily-mode run captures the full-market directory only;
                # it must not advance the separate bounded issuer cursor.
                product.update(daily_cursor_start=0,daily_cursor_next=0,daily_cursor_advance=0,
                    daily_priority_codes=[],daily_parent_refs=[])
            market_history=_ordered_products(service,date,state) if state.get('runs') else []
            market_retry_queue=_market_body_retry_queue(service,market_history)
            if calendar_day_capture:
                market_retry_queue=[doc for doc in market_retry_queue
                    if doc.get('row',{}).get('publication_date')==date]
            market_retry_ids=[doc['news_id'] for doc in market_retry_queue[:4]]
            market_priority_codes=list(dict.fromkeys(
                [doc['code'] for doc in market_retry_queue[:4] if doc.get('code') in names]+selected))[:24]
            if calendar_day_capture:
                market_start,market_window_mode,market_from_date=_calendar_day_market_window(date,context)
                market_priority_codes=list(dict.fromkeys(
                    [doc['code'] for doc in market_retry_queue[:4] if doc.get('code') in names]))[:24]
            else:
                market_start,market_window_mode,market_from_date=_official_market_window(service,date,context,state)
            market_cutoff=timestamp(context.get('research_cutoff'))
            if market_cutoff is None:raise ValueError('HKEX_MARKET_QUERY_CUTOFF_INVALID')
            market_batch=service.source_provider.collect_official_market_batch(context=context,
                from_date=market_from_date,to_date=market_cutoff.strftime('%Y%m%d'),publication_window_start=market_start,
                window_mode=market_window_mode,priority_codes=market_priority_codes,
                priority_news_ids=market_retry_ids,max_documents=4,budget=budget)
            # Commit the full-market evidence before any bounded issuer batch.
            # This keeps a slow issuer pass from consuming the HKEX directory
            # request budget or erasing a successful directory capture.
            product.update(market_directory=market_batch['market_directory'],
                market_documents=market_batch['market_documents'],
                market_pending_documents=market_batch['market_pending_documents'])
            _commit(service, date, state, product)
            if not calendar_day_capture:
                batch = service.source_provider.collect_announcement_batch(context=context,
                    issuers=[dict(code=c,name=names[c]['name']) for c in selected],
                    max_issuers=24, max_documents=0, budget=budget)
                product.update(queries=batch['queries'],pending_documents=batch['pending_documents'],
                    next_index=len(batch['queries']),revision=product['revision']+1)
                _commit(service, date, state, product)
                # Resume the oldest PDF queue with its ORIGINAL cutoff and
                # identity, never relabel it as the new run.
                products = _ordered_products(service, date, state)
                pending = next((p for p in products if p['pending_documents']), None)
                if pending is not None:
                    owner._check_sources(service, pending)
                    more = service.source_provider.collect_announcement_batch(context=pending['context'], issuers=[],
                        pending_documents=pending['pending_documents'], max_issuers=24, max_documents=4, budget=budget)
                    pending['documents'].extend(more['documents'])
                    pending['pending_documents'] = more['pending_documents']
                    pending['revision'] += 1
                    _commit(service, date, state, pending)
            market=product['market_directory']
            market_failures=[]
            if market.get('directory_exhaustion')!='VERIFIED':market_failures.append('OFFICIAL_DIRECTORY_EXHAUSTION_UNVERIFIED')
            if market.get('status')!='COMPLETE':market_failures.append('HKEX_MARKET_DIRECTORY_PARTIAL')
            if market.get('body_gaps'):market_failures.append('HKEX_MARKET_BODY_CAPTURE_GAPS')
            catalog_failures=[]
            if calendar_day_capture:
                catalog_valid=(catalog_error is None and catalog_summary is not None
                    and catalog_summary.get('readback_status')=='VERIFIED'
                    and str(catalog_summary.get('publication_date') or '').replace('-','')==date
                    and catalog_summary.get('source_scope')=='EASTMONEY_HK_DATE_CATALOG'
                    and catalog_summary.get('status')=='COMPLETE')
                if not catalog_valid:
                    catalog_failures.append('EASTMONEY_DATE_CATALOG_NOT_COMPLETE')
                if catalog_error:
                    catalog_failures.append('EASTMONEY_DATE_CATALOG_CAPTURE_FAILED')
            batch_incomplete=(len(product['queries'])<len(selected)
                or any(query.get('status')=='FAILED' for query in product['queries']))
            failure_reasons=(['ANNOUNCEMENT_BATCH_INCOMPLETE'] if batch_incomplete else [])+market_failures+catalog_failures
            input_coverage=dict(selected_issuer_count=len(selected),
                queried_issuer_count=len(product['queries']),unqueried_selected_issuers=selected[len(product['queries']):],
                failed_issuers=[dict(symbol=q['code'],reason=q['reason']) for q in product['queries'] if q['status']=='FAILED'],
                source_order=(['EASTMONEY_HK_DATE_CATALOG','HKEX_OFFICIAL_FULL_MARKET_DIRECTORY']
                    if calendar_day_capture else ['HKEX_OFFICIAL_FULL_MARKET_DIRECTORY','HKEX_PER_ISSUER_BATCH']),
                eastmoney_date_catalog=catalog_summary if calendar_day_capture else None)
            input_coverage.update(market_directory=dict(status=market['status'],directory_exhaustion=market['directory_exhaustion'],
                from_date=market['from_date'],to_date=market['to_date'],window_mode=market['window_mode'],
                publication_window_start=market['publication_window_start'],query_cutoff=market['query_cutoff'],
                record_count=market['record_count'],loaded_record=market['loaded_record'],
                captured_page_count=market['captured_page_count'],captured_row_count=market['captured_row_count'],
                unique_news_id_count=market['unique_news_id_count'],body_documents_captured=len(product['market_documents']),
                pending_document_count=len(product['market_pending_documents']),gaps=market['gaps'],body_gaps=market['body_gaps'],
                product_run_id=product['run_id'],product_sha256=state['runs'][product['run_id']]['sha256']))
            attempt.update(state='PARTIAL' if failure_reasons else 'SUCCEEDED', finished_at=owner._now(), last_success_at=owner._now(),
                provider_request_count=budget.requests, request_budget=budget.max_requests,
                input_identity=scope_id,input_coverage=input_coverage,
                failure_reasons=failure_reasons)
            journal()
        except BaseException as exc:
            # SIGALRM cancellation raises a BaseException in the worker; persist
            # interruption without accepting an incomplete body as success.
            attempt.update(state='FAILED', finished_at=owner._now(), provider_request_count=budget.requests,
                           failure_reasons=[safe_reason(exc, 'ANNOUNCEMENT_AUTORUN_INTERRUPTED')])
            journal()
            raise
        return owner.read(service, date, context)


def read_automatic(service: Any, date: str, context: Mapping[str, Any] | None, value: Mapping[str, Any]) -> dict:
    state = _valid_state(value, date)
    if _markers(service, date) != state['runs']:
        raise ValueError('ANNOUNCEMENT_AUTORUN_COMMIT_SET_MISMATCH')
    context = context or plan_context(date, now=timestamp(owner._now()))
    names,witness=owner._master(service,context)
    if sorted(names)!=state.get('scope') or witness!=state.get('identity_witness') or state['scope_identity']!=digest([witness,sorted(names)]):
        raise ValueError('ANNOUNCEMENT_AUTORUN_SCOPE_IDENTITY_INVALID')
    grouped = {k:{} for k in ('positive_observations','risk_alerts','clarifications','pending_review','official_documents')}
    queries = {}; captures = []; rejections = []; market_captures=[]
    gaps = {'OFFICIAL_DIRECTORY_SERVER_PAGINATION_EXHAUSTION_UNVERIFIED'}
    scope = set(state['scope']); pending_count = 0;validation_cache={}
    for product in _ordered_products(service, date, state):
        parsed = owner._check_sources(service, product, validation_cache=validation_cache)  # Every GET revalidates raw evidence.
        view = owner.project(service, product, context, parsed_documents=parsed)
        captures.append(view['product_identity']); scope.update(product['scope'])
        if isinstance(view.get('market_directory_coverage'),Mapping):
            market_captures.append(_market_coverage_summary(view['market_directory_coverage'],date))
        pending_count += len(product['pending_documents'])
        for q in product['queries']:
            queries[q['code']] = dict(symbol=q['code'], status=q['status'], reason=q['reason'],
                query_cutoff=product['context']['research_cutoff'], capture_run_id=product['run_id'],
                retrieved_at=(q.get('directory_ref') or {}).get('retrieved_at'))
        for key in grouped:
            for row in view.get(key,[]):
                identity = row.get('proposition_id') or row.get('event_id') or digest(row)
                old = grouped[key].get(identity)
                # A later unparsed listing must not erase a parsed original.
                row = deepcopy(row)
                if key == 'official_documents':
                    row['observed_in_runs'] = list(dict.fromkeys((old or {}).get('observed_in_runs', [])+[row['capture_run_id']]))
                    if old:
                        old_success=(old.get('body_status') in {'BODY_CAPTURED_UNASSESSED','BODY_PARSED'}
                            and bool(old.get('document_sha256')))
                        row_success=(row.get('body_status') in {'BODY_CAPTURED_UNASSESSED','BODY_PARSED'}
                            and bool(row.get('document_sha256')))
                        if old_success and not row_success:
                            old['observed_in_runs']=row['observed_in_runs']
                            refs=list(old.get('source_refs',[]));seen={digest(ref) for ref in refs}
                            for ref in row.get('source_refs',[]):
                                if digest(ref) not in seen:refs.append(deepcopy(ref));seen.add(digest(ref))
                            old['source_refs']=refs
                            continue
                        row['first_directory_ref']=deepcopy(old.get('first_directory_ref') or row.get('first_directory_ref'))
                        first_ref=row.get('first_directory_ref')
                        first_seen=timestamp(first_ref.get('retrieved_at')) if isinstance(first_ref,Mapping) else None
                        body_seen=timestamp(row.get('body_observed_at'))
                        if first_seen is not None and body_seen is not None:
                            row['late_acquisition']=body_seen>first_seen
                        refs=list(old.get('source_refs',[]));seen={digest(ref) for ref in refs}
                        for ref in row.get('source_refs',[]):
                            if digest(ref) not in seen:refs.append(deepcopy(ref));seen.add(digest(ref))
                        row['source_refs']=refs
                grouped[key][identity] = row
        gaps.update(view['gaps']); rejections.extend(view['query_rejections'])
    failed = [v for v in queries.values() if v['status']=='FAILED']
    observed = [c for c,q in queries.items() if q['status']=='OBSERVED']
    full_day_market=any(item.get('status')=='VERIFIED' for item in market_captures)
    return dict(status='PARTIAL' if captures else 'NOT_RUN', **{k:list(v.values()) for k,v in grouped.items()},
        product_identity=dict(sha256=state['sha256'], target_trade_date=date, consumed=bool(captures)),
        capture_runs=captures, query_rejections=rejections, gaps=sorted(gaps),
        coverage=dict(native_master_count=len(scope), queried_issuer_count=len(queries), queried_issuers=sorted(queries),
            successfully_observed_issuer_count=len(observed), pending_issuers=sorted(scope-set(queries)),
            failed_issuers=failed, issuer_queries=list(queries.values()), pending_document_count=pending_count,
            directory_exhaustion='UNVERIFIED', all_official_announcements_captured=False,
            natural_run_verified=False, can_resume=False, next_action='NEXT_FRESH_CUTOFF_AUTOMATIC_CYCLE',
            policy=state.get('policy'), policy_status='PROPOSAL_ONLY',
            market_directory_captures=market_captures,
            full_market_directory_verified=full_day_market,
            source_revalidation=dict(raw_reference_reads=validation_cache.get('raw_revalidations',0),
                pdf_reparses=validation_cache.get('pdf_reparses',0),request_local_only=True),
            latest_cycle_started_at=state.get('last_started_at')))
