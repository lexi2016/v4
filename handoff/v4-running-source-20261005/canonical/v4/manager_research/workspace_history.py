"""Historical pre-session readback, not a retrospective producer or raw cache.

Legacy v1 plans have no independent read-set attestation. They are NEVER
trusted for their self-checksum alone: their saved cutoff is replayed through
the original owners, then frozen business fields are compared in full. Cold
source verification may be expensive; timings report that cost rather than
claiming a disk JSON cache is an admitted historical plan.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
import re
from typing import Any, Mapping
from .workspace_projection import FLAGS, HK, SCHEMA, build_workspace, date_token, timestamp, digest
from .workspace_plan import plan_context, _screen_empty
from .workspace_read_control import phase, count, checkpoint, contract_identity, READ_CONTRACT
from .safety import assert_manager_safe_tree

_MAX_PLAN_BYTES = 32*1024*1024
_MAX_SCAN_BYTES = 64*1024*1024
_MAX_RUNS = 64
_BUSINESS_FIELDS = ('schema_version', 'semantic_version', 'decision_projection_version',
    'target_trade_date', 'stocks', 'themes', 'materials', 'company_events', 'focus_symbols',
    'rejected_relations', 'briefing', 'summary', 'market_screen', 'announcement_review')


def boundary_context(date: str) -> dict:
    """Use the existing first continuous Manager Stage boundary (09:30 contract).

    HK's 09:00 auction session is not the cutoff used by the saved 09:27
    manager plan.  The boundary is derived from the frozen Stage contract,
    while each admitted saved plan is still revalidated at its own exact
    research_cutoff.
    """
    from .workspace_plan_autorun import preopen_window
    _, opening = preopen_window(date_token(date), lead_seconds=1)
    return plan_context(date, now=opening)


def _read_candidate(store: Any, date: str, name: str) -> tuple[dict | None, int]:
    from .workspace import PLAN_SCHEMA
    path = f'workspace_plans/{date}/{name}'
    try:
        raw = store._io.read_bytes(path, max_bytes=_MAX_PLAN_BYTES)
    except FileNotFoundError:
        return None, 0
    count('saved_plan_bytes', len(raw))
    row = json.loads(raw)
    assert_manager_safe_tree(row)
    if not isinstance(row, dict):
        raise ValueError('HISTORY_PLAN_OBJECT_INVALID')
    body = row.get('workspace')
    if (row.get('schema_version') != PLAN_SCHEMA or row.get('target_trade_date') != date
        or row.get('owner') != 'ManagerResearchJobService.refresh_workspace_plan'
        or row.get('execution_kind', 'MANUAL_REFRESH') not in {'MANUAL_REFRESH','SCHEDULED_PREOPEN'}
        or row.get('sha256') != digest({k:v for k,v in row.items() if k!='sha256'})
        or any(row.get(k) is not v for k,v in FLAGS.items())
        or not re.fullmatch(r'[0-9a-f]{32}', str(row.get('run_id','')))
        or not isinstance(body, dict) or body.get('target_trade_date') != date
        or row.get('input_identity') != body.get('input_identity')
        or not timestamp(row.get('generated_at'))
        or name not in {'latest.json', str(row.get('run_id'))+'.json'}):
        raise ValueError('HISTORY_PLAN_IDENTITY_INVALID')
    if (body.get('schema_version') != SCHEMA
        or not re.fullmatch(r'[0-9a-f]{64}', str(body.get('input_identity','')))
        or any(not isinstance(body.get(k), dict) for k in ('summary','briefing','plan_context'))
        or any(not isinstance(body.get(k), list) for k in
            ('stocks','materials','themes','company_events','rejected_relations','focus_symbols'))
        or any(not isinstance(item, dict) for k in ('stocks','materials','themes','company_events','rejected_relations') for item in body[k])
        or any(not isinstance(item, str) for item in body['focus_symbols'])):
        raise ValueError('HISTORY_WORKSPACE_SCHEMA_INVALID')
    for stock in body['stocks']:
        if (not isinstance(stock.get('evidence'), list)
            or any(not isinstance(item, dict) for item in stock['evidence'])
            or any(stock.get(k) is not None and not isinstance(stock[k], dict)
                for k in ('stage_observation','close_observation'))):
            raise ValueError('HISTORY_WORKSPACE_SCHEMA_INVALID')
    ctx = body.get('plan_context')
    cutoff = timestamp(ctx.get('research_cutoff')) if isinstance(ctx, Mapping) else None
    if (not cutoff or ctx.get('plan_trade_date') != date or cutoff > timestamp(row['generated_at'])
        or any(body.get(k) is not v for k,v in FLAGS.items())):
        raise ValueError('HISTORY_SAVED_CUTOFF_INVALID')
    # The entire native window, not merely the target string, must match.
    expected = plan_context(date, now=cutoff)
    if any(ctx.get(k) != v for k,v in expected.items() if k != 'market_data_verified'):
        raise ValueError('HISTORY_SAVED_WINDOW_INVALID')
    return row, len(raw)


def select_plan(store: Any, date: str, boundary: Mapping[str, Any]) -> dict | None:
    limit = timestamp(boundary['research_cutoff'])
    def eligible(row: dict | None) -> bool:
        return bool(row and timestamp(row['generated_at']) <= limit
            and timestamp(row['workspace']['plan_context']['research_cutoff']) <= limit)
    latest, total = _read_candidate(store, date, 'latest.json')
    if eligible(latest):
        return latest
    # A later dynamic refresh must not mask an earlier exact-date pre-session
    # run. Bound both directory traversal and total bytes; no date fallback.
    names = []
    try:
        with store._io.directory(f'workspace_plans/{date}') as fd:
            with os.scandir(fd) as entries:
                for index, entry in enumerate(entries):
                    if index >= 256:
                        raise ValueError('HISTORY_RUN_DIRECTORY_BOUND_EXCEEDED')
                    if entry.name == 'latest.json':
                        continue
                    if re.fullmatch(r'[0-9a-f]{32}\.json', entry.name):
                        if not entry.is_file(follow_symlinks=False):
                            raise ValueError('HISTORY_RUN_FILE_UNSAFE')
                        names.append(entry.name)
                        if len(names) > _MAX_RUNS:
                            raise ValueError('HISTORY_RUN_COUNT_BOUND_EXCEEDED')
    except FileNotFoundError:
        return None
    candidates = []
    for name in sorted(names):
        checkpoint()
        row, size = _read_candidate(store, date, name)
        total += size
        if total > _MAX_SCAN_BYTES:
            raise ValueError('HISTORY_RUN_BYTES_BOUND_EXCEEDED')
        if eligible(row):
            candidates.append(row)
    if not candidates:
        return None
    candidates.sort(key=lambda r: (timestamp(r['workspace']['plan_context']['research_cutoff']),
                                   timestamp(r['generated_at'])), reverse=True)
    if len(candidates)>1:
        left, right = candidates[:2]
        if (left['workspace']['plan_context']['research_cutoff']==right['workspace']['plan_context']['research_cutoff']
            and left['generated_at']==right['generated_at'] and left['sha256']!=right['sha256']):
            raise ValueError('HISTORY_SAVED_PLAN_AMBIGUOUS')
    return candidates[0]


def _pit(row: Mapping[str, Any], cutoff: datetime) -> None:
    """Do not accept an undated acquisition as proof it was known at cutoff."""
    for material in row.get('materials', []):
        if not isinstance(material, Mapping):
            raise ValueError('HISTORY_MATERIAL_INVALID')
        for key in ('published_at', 'available_at', 'retrieved_at'):
            value = timestamp(material.get(key))
            if value is None or value > cutoff:
                raise ValueError('HISTORY_MATERIAL_PIT_UNVERIFIED')
        for key in ('collected_at', 'first_seen_at', 'archive_recorded_at'):
            if material.get(key) is not None and (timestamp(material[key]) is None or timestamp(material[key])>cutoff):
                raise ValueError('HISTORY_MATERIAL_AFTER_CUTOFF')
    for stock in row.get('stocks', []):
        if stock.get('market') != 'HK':
            raise ValueError('HISTORY_MARKET_NOT_HK')
        for evidence in stock.get('evidence', []):
            for key in ('published_at','retrieved_at'):
                value = timestamp(evidence.get(key))
                if value is None or value > cutoff:
                    raise ValueError('HISTORY_STOCK_EVIDENCE_PIT_UNVERIFIED')
            if evidence.get('available_at') is not None:
                available = timestamp(evidence['available_at'])
                if available is None or available>cutoff:
                    raise ValueError('HISTORY_STOCK_EVIDENCE_PIT_UNVERIFIED')
        # Intraday rows need actual owner capture evidence, not a guessed time
        # from the bar label. This does not change the original Stage ranking.
        for lane in ('stage_observation', 'close_observation'):
            observation = stock.get(lane)
            if observation:
                capture = timestamp(observation.get('available_at') or observation.get('captured_at'))
                if capture is None or capture > cutoff:
                    raise ValueError('HISTORY_OBSERVATION_AVAILABILITY_UNVERIFIED')


def unavailable(date: str, context: dict, status: str, reason: str, *, saved: dict | None = None) -> dict:
    screen = _screen_empty(context, ['HISTORY_EXACT_DATE_MARKET_NOT_VERIFIED'])
    result = build_workspace(date, catalyst=dict(status='NOT_MATERIALIZED', target_trade_date=date, cards=[], gaps=[reason]),
        plan_context=context, market_screen=screen, source_gaps=[reason, 'HISTORY_COVERAGE_UNKNOWN'])
    result['plan_product'] = dict(status=status, consumed=False, reason=reason,
        run_id=(saved or {}).get('run_id'), sha256=(saved or {}).get('sha256'),
        original_owner='ManagerResearchJobService.refresh_workspace_plan')
    result['observation_mode'] = 'HISTORICAL_PLAN_UNAVAILABLE'
    result['read_context'] = dict(mode='HISTORICAL_AS_OF', status=status,
        as_of=context['research_cutoff'], boundary_basis='NATIVE_MANAGER_FIRST_CONTINUOUS_STAGE_MAXIMUM',
        candidate_count_known=False, reason=reason, contract=READ_CONTRACT)
    result['announcement_review'] = dict(schema_version='v4.manager_research.announcement_review.v1',
        target_trade_date=date, status='NOT_RUN', positive_observations=[], risk_alerts=[],
        clarifications=[], pending_review=[], coverage={}, gaps=['HISTORY_ANNOUNCEMENT_COVERAGE_UNKNOWN'],
        attempt=None, product_identity=None, query_rejections=[], **FLAGS)
    return result


def _mark_historical_us_recheck(us_market: dict, context: Mapping[str, Any],
                                saved: Mapping[str, Any]) -> dict:
    checked_at = datetime.now(timezone.utc).isoformat()
    recheck = dict(
        state='COMPLETED_READ_ONLY_RECHECK',
        source_status=us_market.get('status'),
        saved_plan_run_id=saved.get('run_id'),
        saved_plan_sha256=saved.get('sha256'),
        research_cutoff=context.get('research_cutoff'),
        checked_at=checked_at,
        saved_plan_modified=False,
        selected_stock_verdict_modified=False,
    )
    us_market['historical_source_recheck'] = recheck
    return recheck


def _attach_historical_us_recheck(result: dict, service: Any, date: str,
                                  context: Mapping[str, Any], saved: Mapping[str, Any]) -> None:
    """Expose the exact-cutoff US owner read even when another history owner fails.

    This read is an observation attached to the failed history response. It
    never admits the saved plan, recomputes selected stocks, or writes a plan.
    """
    from .us_market_bridge import project_us_market

    try:
        us_market = project_us_market(
            getattr(service, '_workspace_us_market_reader', None), date, context
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, TimeoutError) as exc:
        us_market = project_us_market(None, date, context)
        us_market['status'] = 'CANNOT_CONFIRM'
        us_market['gaps'] = sorted(set(us_market.get('gaps', [])) |
                                   {f'US_HISTORICAL_RECHECK_FAILED:{type(exc).__name__}'})
        us_market['mapping_eligible'] = False
        us_market['mapping_ineligible_reasons'] = sorted(set(
            us_market.get('mapping_ineligible_reasons', [])
        ) | {'US_HISTORICAL_RECHECK_FAILED'})
    recheck = _mark_historical_us_recheck(us_market, context, saved)
    result['us_market_attention'] = us_market
    result['historical_source_rechecks'] = dict(us_market=recheck)
    result.setdefault('owner_chain', {})['us_market'] = dict(
        owner='ResearchPeripheralStore/external_finance',
        status=us_market.get('status'),
        expected_us_session=us_market.get('expected_us_session'),
        coverage=us_market.get('coverage'),
        source_identity=us_market.get('source_identity'),
        failure_reasons=us_market.get('gaps', []),
        read_only=True,
        selected_stock_verdict_modified=False,
    )


def read_history(service: Any, date: str) -> dict:
    from .workspace import _compute_workspace, _ERROR_TYPES
    boundary = boundary_context(date)
    saved = None
    ctx = None
    try:
        with phase('saved_plan_gate'):
            saved = select_plan(service.store, date, boundary)
        if saved is None:
            return unavailable(date, boundary, 'NOT_MATERIALIZED', 'HISTORY_QUALIFIED_SAVED_PLAN_MISSING')
        ctx = deepcopy(saved['workspace']['plan_context'])
        with phase('saved_plan_version_and_pit'):
            from .workspace_semantics import SEMANTIC_VERSION
            if saved['workspace'].get('semantic_version') != SEMANTIC_VERSION:
                raise ValueError('HISTORY_SEMANTIC_VERSION_CHANGED')
            reader = saved.get('read_contract_sha256')
            if reader is not None and reader != contract_identity():
                raise ValueError('HISTORY_READER_VERSION_CHANGED')
            _pit(saved['workspace'], timestamp(ctx['research_cutoff']))
        # Mandatory original schema/SHA/safety/source validation. The memo
        # below _compute_workspace caches ONLY pure projections of these
        # revalidated full inputs, never the source-reader output itself.
        with phase('historical_owner_revalidation'):
            verified = _compute_workspace(service, date, include_saved=False, context=ctx)
        with phase('frozen_business_comparison'):
            if saved['input_identity'] != verified['input_identity']:
                raise ValueError('HISTORY_SOURCE_INPUTS_CHANGED')
            if any(saved['workspace'].get(k) != verified.get(k) for k in _BUSINESS_FIELDS):
                raise ValueError('HISTORY_FROZEN_PROJECTION_CHANGED')
            _pit(verified, timestamp(ctx['research_cutoff']))
        # Return the verified projection, never unchecked saved stock/actions.
        verified['plan_product'] = dict(status='CURRENT', consumed=True, run_id=saved['run_id'],
            sha256=saved['sha256'], generated_at=saved['generated_at'],
            original_owner=saved['owner'], last_checked_at=datetime.now(timezone.utc).isoformat())
        verified['observation_mode'] = 'EXACT_DATE_HISTORICAL_PLAN_READBACK'
        verified['read_context'] = dict(mode='HISTORICAL_AS_OF',
            status='VERIFIED_WITH_GAPS' if verified['gaps'] else 'VERIFIED',
            as_of=ctx['research_cutoff'], boundary_basis='SAVED_CUTOFF_NOT_LATER_THAN_MANAGER_FIRST_CONTINUOUS_STAGE',
            candidate_count_known=bool(verified['stocks']) or not verified['gaps'],
            contract=READ_CONTRACT, legacy_full_revalidation=reader is None)
        us_market = verified.get('us_market_attention')
        if isinstance(us_market, dict):
            recheck = _mark_historical_us_recheck(us_market, ctx, saved)
            verified['historical_source_rechecks'] = dict(us_market=recheck)
            verified['owner_chain']['us_market']['historical_source_recheck'] = recheck
            verified['read_context']['source_recheck_status'] = us_market.get('status')
            verified['read_context']['source_recheck_saved_run_id'] = saved.get('run_id')
        return verified
    except _ERROR_TYPES as exc:
        reason = str(exc) if re.fullmatch(r'HISTORY_[A-Z0-9_]+', str(exc)) else 'HISTORY_SOURCE_VALIDATION_FAILED'
        # Once a qualified plan is selected, any attached owner recheck is
        # evaluated at its immutable saved cutoff, never at the later 09:30
        # boundary or at the current page time.
        failed_context = ctx if isinstance(ctx, Mapping) else boundary
        result = unavailable(date, dict(failed_context), 'SOURCE_FAILED', reason, saved=saved)
        if saved is not None and ctx is not None:
            _attach_historical_us_recheck(result, service, date, ctx, saved)
            result['read_context']['as_of'] = ctx['research_cutoff']
            result['read_context']['source_recheck_status'] = result['us_market_attention'].get('status')
            result['read_context']['source_recheck_saved_run_id'] = saved.get('run_id')
        return result
