"""Bounded automatic increments of the existing announcement owner.

No network implementation or second producer lives here. Every response and
revision is owned by the original HKEX provider/MaterialStore/store validators.
All numeric policy values are PROPOSAL_ONLY and require explicit local opt-in.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, time
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
    if not time(7) <= local.time().replace(tzinfo=None) < time(23):
        return False
    # Do not start a 50s child which could cross into the 15:20 exclusion.
    if time(15, 19) <= local.time().replace(tzinfo=None) < time(15, 40):
        return False
    states = resolve_market_states(load_market_calendar(), local.strftime('%Y%m%d'))
    return states['hk_securities'] in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}


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
    runroot=service.store.root/'workspace_announcement_runs'/date
    with service.store._transaction(date,'workspace-announcements'):
        prior=service.store._read(runroot/'latest.json')
        if prior is not None:prior=validate_attempt(prior,date)
        started=owner._now()
        try:
            return _scheduled_refresh(service,date,schedule)
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


def _scheduled_refresh(service: Any, date: str, schedule: Mapping[str, Any]) -> dict:
    """Called only by explicit POST owner use or the opt-in bounded worker.

    Duplicate time buckets cause NO provider request. Cursor reservation occurs
    before I/O, so a repeatedly failing issuer cannot hold all higher codes.
    A selected-but-unqueried issuer is *not* counted as covered.
    """
    from .workspace import ATTEMPT_SCHEMA, seal_attempt, validate_attempt
    date = date_token(date)
    if not isinstance(schedule, Mapping) or set(schedule) - {'policy', 'now', 'priority_codes', 'execution_identity'}:
        raise ValueError('ANNOUNCEMENT_SCHEDULE_FIELDS_INVALID')
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
        context = plan_context(date, now=now)
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
        if last is not None and (now-last).total_seconds() < config['interval_seconds']:
            return owner.read(service, date, context)
        if len(state['runs']) >= MAX_RUNS:
            raise ValueError('ANNOUNCEMENT_RUN_RETENTION_BOUND_EXCEEDED')
        fair = [codes[(state['fair_cursor']+i) % len(codes)] for i in range(min(config['fair_count'],len(codes)))]
        priority = [priorities[(state['priority_cursor']+i) % len(priorities)]
                    for i in range(min(config['priority_count'], len(priorities)))] if priorities else []
        selected = priority + [c for c in fair if c not in priority]
        # Spare priority slots are NOT used to change the guaranteed fair stride.
        state.update(fair_cursor=(state['fair_cursor']+len(fair)) % len(codes),
                     priority_cursor=state['priority_cursor']+len(priority),
                     last_started_at=owner._now(), last_bucket=bucket, policy=policy)
        _save_state(service, date, state)
        manual = service.store._read(root / 'latest.json')
        if manual is not None and manual.get('run_id') not in state['runs']:
            retain_manual_product(service, date, owner.validate_product(manual,date))
            state = _valid_state(service.store._read(root/'autorun.json'),date)
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
            batch = service.source_provider.collect_announcement_batch(context=context,
                issuers=[dict(code=c,name=names[c]['name']) for c in selected],
                max_issuers=24, max_documents=0, budget=budget)
            product.update(queries=batch['queries'], pending_documents=batch['pending_documents'], next_index=len(batch['queries']))
            _commit(service, date, state, product)
            # Fair issuer search comes FIRST. Resume the oldest PDF queue with
            # its ORIGINAL cutoff and identity, never relabel it as the new run.
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
            attempt.update(state='PARTIAL', finished_at=owner._now(), last_success_at=owner._now(),
                provider_request_count=budget.requests, request_budget=budget.max_requests,
                input_identity=scope_id, input_coverage=dict(selected_issuer_count=len(selected),
                    queried_issuer_count=len(product['queries']), unqueried_selected_issuers=selected[len(product['queries']):],
                    failed_issuers=[dict(symbol=q['code'],reason=q['reason']) for q in product['queries'] if q['status']=='FAILED']),
                failure_reasons=['OFFICIAL_DIRECTORY_EXHAUSTION_UNVERIFIED'] +
                    (['ANNOUNCEMENT_BATCH_INCOMPLETE'] if len(product['queries']) < len(selected) else []))
            journal()
        except BaseException as exc:
            # SIGALRM cancellation raises a BaseException in the worker; persist
            # interruption without accepting an incomplete body as success.
            attempt.update(state='FAILED', finished_at=owner._now(), provider_request_count=budget.requests,
                           failure_reasons=[safe_reason(exc, 'ANNOUNCEMENT_AUTORUN_INTERRUPTED')])
            journal()
            raise
        return owner.read(service, date, plan_context(date, now=timestamp(owner._now())))


def read_automatic(service: Any, date: str, context: Mapping[str, Any] | None, value: Mapping[str, Any]) -> dict:
    state = _valid_state(value, date)
    if _markers(service, date) != state['runs']:
        raise ValueError('ANNOUNCEMENT_AUTORUN_COMMIT_SET_MISMATCH')
    context = context or plan_context(date, now=timestamp(owner._now()))
    names,witness=owner._master(service,context)
    if sorted(names)!=state.get('scope') or witness!=state.get('identity_witness') or state['scope_identity']!=digest([witness,sorted(names)]):
        raise ValueError('ANNOUNCEMENT_AUTORUN_SCOPE_IDENTITY_INVALID')
    grouped = {k:{} for k in ('positive_observations','risk_alerts','clarifications','pending_review','official_documents')}
    queries = {}; captures = []; rejections = []; gaps = {'OFFICIAL_DIRECTORY_SERVER_PAGINATION_EXHAUSTION_UNVERIFIED'}
    scope = set(state['scope']); pending_count = 0;validation_cache={}
    for product in _ordered_products(service, date, state):
        parsed = owner._check_sources(service, product, validation_cache=validation_cache)  # Every GET revalidates raw evidence.
        view = owner.project(service, product, context, parsed_documents=parsed)
        captures.append(view['product_identity']); scope.update(product['scope'])
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
                if key == 'official_documents' and old and old.get('body_status') == 'BODY_PARSED' and row.get('body_status') != 'BODY_PARSED':
                    old.setdefault('observed_in_runs', []).append(row['capture_run_id'])
                    continue
                row = deepcopy(row)
                if key == 'official_documents':
                    row['observed_in_runs'] = list(dict.fromkeys((old or {}).get('observed_in_runs', [])+[row['capture_run_id']]))
                grouped[key][identity] = row
        gaps.update(view['gaps']); rejections.extend(view['query_rejections'])
    failed = [v for v in queries.values() if v['status']=='FAILED']
    observed = [c for c,q in queries.items() if q['status']=='OBSERVED']
    return dict(status='PARTIAL' if captures else 'NOT_RUN', **{k:list(v.values()) for k,v in grouped.items()},
        product_identity=dict(sha256=state['sha256'], target_trade_date=date, consumed=bool(captures)),
        capture_runs=captures, query_rejections=rejections, gaps=sorted(gaps),
        coverage=dict(native_master_count=len(scope), queried_issuer_count=len(queries), queried_issuers=sorted(queries),
            successfully_observed_issuer_count=len(observed), pending_issuers=sorted(scope-set(queries)),
            failed_issuers=failed, issuer_queries=list(queries.values()), pending_document_count=pending_count,
            directory_exhaustion='UNVERIFIED', all_official_announcements_captured=False,
            natural_run_verified=False, can_resume=False, next_action='NEXT_FRESH_CUTOFF_AUTOMATIC_CYCLE',
            policy=state.get('policy'), policy_status='PROPOSAL_ONLY',
            source_revalidation=dict(raw_reference_reads=validation_cache.get('raw_revalidations',0),
                pdf_reparses=validation_cache.get('pdf_reparses',0),request_local_only=True),
            latest_cycle_started_at=state.get('last_started_at')))
