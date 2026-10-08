"""Read-only, stock-keyed manager workspace projection.

Inputs must have passed their ORIGINAL owner readers. This module is not an
archive validator, security master, scanner or recommendation producer. It has
no I/O or third-party imports; original Stage/close rows remain unchanged.
"""
from __future__ import annotations
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, time
import hashlib
import json
import re
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
SCHEMA = 'v4.manager_research.workspace.v1'
HK = ZoneInfo('Asia/Hong_Kong')
HK_MARKETS = {'HK', 'HK_LISTED', 'HK_CONNECT'}
THEME_ALIASES = {'AI医疗':'AI_HEALTHCARE','AI制药':'AI_HEALTHCARE','AI药物研发':'AI_HEALTHCARE',
                 'AIDD':'AI_HEALTHCARE','机器人':'ROBOTICS','具身智能':'ROBOTICS','大模型':'AI_APPLICATION'}
_DATA = {'READY', 'READY_EMPTY', 'EMPTY', 'PARTIAL', 'PARTIAL_WITH_ROWS', 'SUCCEEDED', 'STALE'}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def date_token(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'\d{8}', value):
        raise ValueError('WORKSPACE_DATE_INVALID')
    return datetime.strptime(value, '%Y%m%d').strftime('%Y%m%d')


def timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return dt.astimezone(HK) if dt.tzinfo else None
    except ValueError:
        return None


def canonical_symbol(value: Any, market: Any = 'HK') -> str | None:
    if market not in HK_MARKETS or not isinstance(value, str):
        return None
    match = re.fullmatch(r'(?:HK\.)?(\d{1,5})(?:\.HK)?', value.upper().strip())
    if not match or int(match[1]) == 0:
        return None
    return 'HK.' + match[1].zfill(5)


def themes_of(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return sorted({THEME_ALIASES.get(v.strip(), v.strip()) for v in value if isinstance(v, str) and v.strip()})


def canonical_url(value: Any) -> str:
    if not isinstance(value, str):
        return ''
    try:
        u = urlsplit(value)
        if u.scheme not in {'https', 'http'} or not u.hostname or u.username or u.password:
            return ''
        query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True)
                 if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid'}]
        return urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip('/'), urlencode(sorted(query)), ''))
    except ValueError:
        return ''


def event_groups(evidence: Sequence[Mapping[str, Any]]) -> list[list[dict[str, Any]]]:
    """Conservative transitive merge. Preserve every relationship, not just one row.

    Different URLs are not automatically independent sources. Unresolved copies
    have NO confirmed-independent count, even when their titles differ.
    """
    parents = list(range(len(evidence)))
    keys: dict[tuple, int] = {}
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]; i = parents[i]
        return i
    for i, row in enumerate(evidence):
        tokens = []
        url = canonical_url(row.get('original_url') or row.get('source_url'))
        if url:
            tokens.append(('url', url))
        for key in ('origin_event_id', 'event_id'):
            if row.get(key):
                tokens.append((key, str(row[key])))
        title = ' '.join(str(row.get('title') or '').casefold().split())
        day = row.get('published_date') or str(row.get('published_at') or '')[:10]
        if title and day:
            tokens.append(('title_date', title, day))
        for token in tokens:
            if token in keys:
                parents[root(i)] = root(keys[token])
            else:
                keys[token] = i
    grouped = defaultdict(list)
    for i, row in enumerate(evidence):
        grouped[root(i)].append(deepcopy(dict(row)))
    return list(grouped.values())


def _is_new(row: Mapping[str, Any], date: str) -> bool:
    """Only explicit owner-captured target-session publications are new signals."""
    pub, available = timestamp(row.get('published_at')), timestamp(row.get('available_at'))
    cutoff = datetime.combine(datetime.strptime(date, '%Y%m%d').date(), time(16, 10), HK)
    return bool(row.get('captured_at_target') is True and row.get('temporal_classification') == 'CAPTURED_AT_TARGET'
                and pub and available and pub.strftime('%Y%m%d') == date and pub <= available <= cutoff)


def lane_status(lane: str, owner: str, date: str, *, status: str = 'NOT_RUN', count: int | None = None,
                gaps: Sequence[str] = (), artifact: Mapping[str, Any] | None = None,
                attempt: Mapping[str, Any] | None = None, next_plan: Mapping[str, Any] | None = None) -> dict:
    status = str(status).upper()
    if count is not None and (type(count) is not int or count < 0):
        raise ValueError('WORKSPACE_STOCK_COUNT_INVALID')
    state = {'NOT_MATERIALIZED':'NOT_RUN','NOT_RUN':'NOT_RUN','PENDING_SLOT':'NOT_RUN','RUNNING':'RUNNING',
             'QUEUED':'RUNNING','FAILED':'FAILED','CANCELLED':'FAILED','CANNOT_CONFIRM':'UNVERIFIED',
             'PARTIAL':'PARTIAL','PARTIAL_WITH_ROWS':'PARTIAL','STALE':'PARTIAL'}.get(status, 'UNVERIFIED')
    if status in {'READY','READY_EMPTY','EMPTY','SUCCEEDED'}:
        state = 'PARTIAL' if gaps else ('SUCCEEDED_EMPTY' if count == 0 else ('SUCCEEDED' if count is not None else 'UNVERIFIED'))
    artifact, attempt = dict(artifact or {}), dict(attempt or {})
    # A later failed/running attempt must not be painted green by an older product.
    attempt_at = timestamp(attempt.get('finished_at') or attempt.get('started_at') or attempt.get('generated_at'))
    product_at = timestamp(artifact.get('generated_at'))
    if attempt_at and (product_at is None or attempt_at >= product_at
                       or (attempt.get('state') == 'RUNNING' and attempt.get('execution_kind') == 'MANUAL_REFRESH')):
        if attempt.get('state') in {'RUNNING','FAILED','PARTIAL'}:
            state = attempt['state']
    plan = None
    if (isinstance(next_plan, Mapping) and next_plan.get('verification') == 'OWNER_VERIFIED'
            and next_plan.get('owner') and next_plan.get('run_id') and timestamp(next_plan.get('next_at'))):
        plan = deepcopy(dict(next_plan))
    return dict(lane=lane, owner=owner, state=state, target_date=date, stock_count=count,
                last_attempt_at=attempt.get('started_at') or attempt.get('generated_at'),
                last_success_at=attempt.get('last_success_at') or (artifact.get('generated_at') if status in _DATA else None),
                run_id=attempt.get('run_id') or artifact.get('run_id'),
                execution_kind=attempt.get('execution_kind', 'UNVERIFIED'),
                liveness='START_RECEIPT_ONLY_PROCESS_LIVENESS_NOT_VERIFIED' if state == 'RUNNING' else 'NOT_APPLICABLE',
                input_coverage=deepcopy(artifact.get('coverage') or artifact.get('input_coverage') or {}),
                failure_reasons=list(dict.fromkeys([*gaps, *attempt.get('failure_reasons', [])])),
                next_plan=plan, schedule_status='VERIFIED' if plan else 'SCHEDULER_PLAN_NOT_BOUND',
                artifact_consumption='API_PROJECTED' if artifact.get('consumed') else 'NO_VERIFIED_PRODUCT',
                previous_product_retained=bool(state in {'FAILED','RUNNING'} and artifact.get('consumed')))


def _rows(payload: Mapping[str, Any] | None, lane: str, date: str, gaps: list[str]) -> tuple[dict, list]:
    if not isinstance(payload, Mapping):
        return {}, []
    payload = deepcopy(dict(payload))
    target = payload.get('target_trade_date') or payload.get('trade_date')
    if target != date:
        gaps.append(lane + '_TARGET_DATE_MISMATCH')
        return {'status':'CANNOT_CONFIRM','cannot_confirm':[lane + '_TARGET_DATE_MISMATCH']}, []
    source = payload
    if lane == 'STAGE' and isinstance(payload.get('markets'), dict):
        source = payload['markets'].get('HK_CONNECT') or payload['markets'].get('HK') or {}
        # Retain exact envelope identity while using only the HK sub-payload.
        source = {**payload, **source}
    rows = source.get('rows' if lane == 'STAGE' else 'candidates', [])
    if not isinstance(rows, list):
        gaps.append(lane + '_ROWS_INVALID'); return {'status':'CANNOT_CONFIRM'}, []
    if source.get('status') not in _DATA:
        return source, []
    return source, rows


def _market_screen_summary_counts(screen: Mapping[str, Any] | None) -> tuple[int | None, int | None, int | None]:
    """Project counts only when the existing screen marks its result ready."""
    if (not isinstance(screen, Mapping)
            or screen.get('status') not in {'READY', 'READY_WITH_GAPS'}
            or screen.get('main_screen_ready') is not True):
        return None, None, None
    coverage = screen.get('coverage')
    coverage = coverage if isinstance(coverage, Mapping) else {}

    def count(key: str) -> int | None:
        value = coverage.get(key)
        return value if type(value) is int and value >= 0 else None

    cards = screen.get('cards')
    return count('strict_count'), count('near_count'), len(cards) if isinstance(cards, list) else None


def build_workspace(date: str, *, catalyst: Mapping[str, Any], materials: Sequence[Mapping[str, Any]] = (),
                    stage: Mapping[str, Any] | None = None, close: Mapping[str, Any] | None = None,
                    close_recapture: Mapping[str, Any] | None = None,
                    requested_day_close_recapture: Mapping[str, Any] | None = None,
                    attempts: Mapping[str, Any] | None = None, plans: Mapping[str, Any] | None = None,
                    source_gaps: Sequence[str] = (), previous: Mapping[str, Any] | None = None,
                    discovered_cards: Sequence[Mapping[str, Any]] = (),
                    plan_context: Mapping[str, Any] | None = None,
                    price_quotes: Mapping[str, Mapping[str, Any]] | None = None,
                    market_screen: Mapping[str, Any] | None = None,
                    discovery_rejections: Sequence[Mapping[str,Any]] = ()) -> dict:
    date = date_token(date)
    gaps = list(source_gaps)
    if plan_context is not None and plan_context.get('plan_trade_date') != date:
        raise ValueError('WORKSPACE_PLAN_TARGET_MISMATCH')
    from .workspace_plan import stock_plan, temporal_role
    from .workspace_semantics import sanitize_cards, SEMANTIC_VERSION
    context = dict(plan_context or {'plan_trade_date':date,'market_session':None,'research_cutoff':None})
    close_recapture_projection = deepcopy(dict(close_recapture or {}))
    close_recapture_projection.setdefault('status', 'NOT_RUN')
    close_recapture_projection.setdefault('candidate_overlay', {'count': 0, 'rows': []})
    close_recapture_projection.setdefault('cannot_confirm', ['CLOSE_RECAPTURE_NOT_MATERIALIZED'])
    close_recapture_projection.setdefault('planner_availability', 'SOURCE_NOT_AVAILABLE')
    close_recapture_projection['planner_eligible_context'] = False
    requested_day_projection = deepcopy(dict(requested_day_close_recapture or {}))
    requested_day_projection.setdefault('status', 'NOT_RUN')
    requested_day_projection.setdefault('source_trade_date', None)
    requested_day_projection.setdefault('requested_trade_date', date)
    requested_day_projection.setdefault('target_trade_date', None)
    requested_day_projection.setdefault('plan_trade_date', None)
    requested_day_projection.setdefault('observation_type', 'HK_SECURITIES_SESSION_MINUTE_OBSERVATION')
    requested_day_projection.setdefault('candidate_overlay', {'count': 0, 'rows': []})
    requested_day_projection.setdefault('cannot_confirm', ['REQUESTED_DAY_HK_OBSERVATION_NOT_MATERIALIZED'])
    requested_day_projection['planner_availability'] = 'DISPLAY_ONLY_NOT_PLANNER_INPUT'
    requested_day_projection['planner_eligible_context'] = False
    requested_day_projection['formal_recommendation_effect'] = 'NONE'
    requested_day_projection['buy_gate_effect'] = 'NONE'
    cutoff = timestamp(context.get('research_cutoff'))
    requested_overlay = requested_day_projection.get('candidate_overlay')
    requested_overlay = requested_overlay if isinstance(requested_overlay, Mapping) else {}
    requested_rows = requested_overlay.get('rows')
    requested_rows = requested_rows if isinstance(requested_rows, list) else []
    requested_request = requested_day_projection.get('request')
    requested_request = requested_request if isinstance(requested_request, Mapping) else {}
    requested_available = timestamp(requested_request.get('available_at'))
    if requested_day_projection.get('status') in {'READY', 'PARTIAL'}:
        cutoff_reason = None
        if cutoff is None:
            cutoff_status = 'CANNOT_CONFIRM'
            cutoff_reason = 'REQUESTED_DAY_OBSERVATION_RESEARCH_CUTOFF_UNAVAILABLE'
        elif requested_available is None:
            cutoff_status = 'CANNOT_CONFIRM'
            cutoff_reason = 'REQUESTED_DAY_OBSERVATION_AVAILABLE_AT_UNVERIFIED'
        elif requested_available > cutoff:
            cutoff_status = 'AFTER_CUTOFF'
            cutoff_reason = 'REQUESTED_DAY_OBSERVATION_AFTER_RESEARCH_CUTOFF'
        else:
            cutoff_status = 'AVAILABLE_AT_CUTOFF'
        requested_day_projection['availability_gate'] = {
            'status': cutoff_status,
            'source_status': requested_day_projection.get('status'),
            'research_cutoff': context.get('research_cutoff'),
            'available_at': requested_request.get('available_at'),
            'verified_source_row_count': len(requested_rows),
            'artifact_ref': requested_overlay.get('artifact_ref'),
            'artifact_sha256': requested_overlay.get('sha256'),
            'reason': cutoff_reason,
        }
        if cutoff_reason:
            requested_day_projection['status'] = 'CANNOT_CONFIRM'
            reasons = requested_day_projection.get('cannot_confirm')
            reasons = list(reasons) if isinstance(reasons, list) else []
            if cutoff_reason not in reasons:
                reasons.append(cutoff_reason)
            requested_day_projection['cannot_confirm'] = reasons
            requested_day_projection['candidate_overlay'] = {
                **dict(requested_overlay), 'count': 0, 'rows': [],
            }
    request = close_recapture_projection.get('request')
    request = request if isinstance(request, Mapping) else {}
    available = timestamp(request.get('available_at'))
    source_date = close_recapture_projection.get('source_trade_date')
    if (close_recapture_projection.get('status') in {'READY', 'PARTIAL'}
            and source_date == context.get('market_session')
            and close_recapture_projection.get('plan_trade_date') == date and cutoff and available):
        close_recapture_projection['planner_availability'] = (
            'AVAILABLE_BEFORE_CUTOFF' if available <= cutoff else 'AFTER_CUTOFF'
        )
        close_recapture_projection['planner_eligible_context'] = available <= cutoff
    elif close_recapture_projection.get('status') in {'READY', 'PARTIAL'}:
        close_recapture_projection['planner_availability'] = 'SOURCE_SESSION_NOT_IN_PLAN_CONTEXT'
    close_recapture_projection['formal_recommendation_effect'] = 'NONE'
    close_recapture_projection['buy_gate_effect'] = 'NONE'
    late_tail_plan_rows: dict[str, dict] = {}
    if close_recapture_projection.get('planner_eligible_context') is True:
        overlay = close_recapture_projection.get('candidate_overlay')
        overlay = overlay if isinstance(overlay, Mapping) else {}
        request = close_recapture_projection.get('request')
        request = request if isinstance(request, Mapping) else {}
        receipt = close_recapture_projection.get('receipt')
        receipt = receipt if isinstance(receipt, Mapping) else {}
        source = close_recapture_projection.get('source')
        source = source if isinstance(source, Mapping) else {}
        window = close_recapture_projection.get('bar_window')
        window = window if isinstance(window, Mapping) else {}
        pool = close_recapture_projection.get('pool')
        pool = pool if isinstance(pool, Mapping) else {}
        rows = overlay.get('rows')
        if (source_date == context.get('market_session') and date == context.get('plan_trade_date')
                and close_recapture_projection.get('observation_type') == 'PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION'
                and source.get('provider') == 'pytdx_exhq' and window.get('stage_id') == 'STAGE_1545_1555'
                and timestamp(request.get('available_at')) and timestamp(request.get('available_at')) <= cutoff
                and isinstance(rows, list)):
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                symbol = canonical_symbol(row.get('symbol'), 'HK_CONNECT')
                observed = timestamp(row.get('observed_at'))
                available = timestamp(row.get('available_at'))
                if (not symbol or symbol != row.get('symbol') or row.get('candidate_status') != 'OBSERVATION_ONLY'
                        or row.get('source_trade_date') != source_date or observed is None or available is None
                        or observed > available or available > cutoff or observed.strftime('%Y%m%d') != source_date):
                    continue
                late_tail_plan_rows[symbol] = {
                    'status': 'AVAILABLE_BEFORE_CUTOFF',
                    'symbol': symbol,
                    'observation_type': close_recapture_projection.get('observation_type'),
                    'provider': source.get('provider'),
                    'stage_id': window.get('stage_id'),
                    'source_trade_date': source_date,
                    'plan_trade_date': date,
                    'capture_artifact_ref': f'workbench_research/{source_date}/close_recapture.json',
                    'capture_artifact_sha256': receipt.get('artifact_sha256'),
                    'request_started_at': request.get('started_at'),
                    'captured_at': request.get('captured_at'),
                    'observed_at': row.get('observed_at'),
                    'available_at': row.get('available_at'),
                    'capture_available_at': request.get('available_at'),
                    'candidate_overlay_ref': overlay.get('artifact_ref'),
                    'candidate_overlay_sha256': overlay.get('sha256'),
                    'snapshot_ref': (close_recapture_projection.get('snapshot') or {}).get('artifact_ref'),
                    'snapshot_sha256': (close_recapture_projection.get('snapshot') or {}).get('sha256'),
                    'pool': deepcopy(dict(pool)),
                    'observation': deepcopy(dict(row)),
                    'price_semantics': 'LATE_TAIL_MINUTE_OBSERVATION_NOT_FULL_DAY_CLOSE',
                    'turnover_currency': 'UNKNOWN',
                    'turnover_unit': 'UNKNOWN',
                }
    attempts, plans = attempts or {}, plans or {}
    stocks: dict[str, dict] = {}
    def stock(symbol, name, market='HK'):
        symbol = canonical_symbol(symbol, market)
        if not symbol:
            gaps.append('NON_HK_OR_UNVERIFIED_SECURITY'); return None
        key = f'HK|{symbol}|{date}'
        if key not in stocks:
            stocks[key] = dict(stock_key=key, market='HK', symbol=symbol, target_date=date, name=name or symbol,
                               connect_eligibility='NOT_CHECKED', lanes=[], evidence=[], material_relations=[],
                               stage_observation=None, close_observation=None, close_recapture_observation=None, **FLAGS)
        return stocks[key]
    raw_cards = catalyst.get('cards', []) if catalyst.get('status') in _DATA else []
    if catalyst.get('target_trade_date', date) != date:
        raw_cards = []; gaps.append('CATALYST_TARGET_DATE_MISMATCH')
    if not isinstance(raw_cards, list):
        raise ValueError('WORKSPACE_CATALYST_CARDS_INVALID')
    original_candidate_cards = [*raw_cards, *discovered_cards]
    candidate_cards, rejected_relations = sanitize_cards(original_candidate_cards)
    rejected_relations=[*deepcopy(list(discovery_rejections)),*rejected_relations]
    for raw in candidate_cards:
        row = deepcopy(dict(raw))
        if row.get('symbol') is None:
            continue
        s = stock(row.get('symbol'), row.get('name'), row.get('market','HK'))
        if s is None:
            continue
        s['evidence'].append(row)
        if row.get('connect_eligibility')=='VERIFIED_TARGET_UNIVERSE' and row.get('membership_source',{}).get('source_date')==date:
            s['connect_eligibility']='VERIFIED_TARGET_UNIVERSE'
            s['membership_source']=deepcopy(row['membership_source'])
        source_lane = 'MATERIAL' if row.get('relationship_type')=='NATIVE_HK_ISSUER_EXPLICIT_MENTION' else 'CATALYST'
        if source_lane not in s['lanes']:
            s['lanes'].append(source_lane)
    stage_value, stage_rows = _rows(stage, 'STAGE', date, gaps)
    close_value, close_rows = _rows(close, 'CLOSE', date, gaps)
    for lane, rows in (('STAGE', stage_rows), ('CLOSE', close_rows)):
        for row in rows:
            if not isinstance(row, Mapping):
                gaps.append(lane + '_ROW_INVALID'); continue
            s = stock(row.get('symbol') or row.get('code'), row.get('name'), row.get('market','HK_CONNECT'))
            if s is not None:
                s[lane.lower() + '_observation'] = deepcopy(dict(row))
                if lane not in s['lanes']:
                    s['lanes'].append(lane)
    for symbol, observation in late_tail_plan_rows.items():
        s = stock(symbol, observation.get('observation', {}).get('name'), 'HK_CONNECT')
        if s is not None:
            s['close_recapture_observation'] = observation
            if 'CLOSE_RECAPTURE' not in s['lanes']:
                s['lanes'].append('CLOSE_RECAPTURE')
    accepted_materials = []
    for original in materials:
        if original.get('verification') != 'OWNER_VERIFIED':
            gaps.append('EXISTING_MATERIAL_NOT_OWNER_VERIFIED'); continue
        if plan_context and temporal_role(original,context)=='AFTER_CUTOFF_EXCLUDED':
            gaps.append('MATERIAL_AFTER_CUTOFF_EXCLUDED'); continue
        accepted_materials.append(deepcopy(dict(original)))
    previous_stocks = {}
    if previous and previous.get('target_trade_date','') < date and previous.get('schema_version') == SCHEMA and previous.get('semantic_version') == SEMANTIC_VERSION:
        previous_stocks = {s['symbol']:s for s in previous.get('stocks',[])}
    for s in stocks.values():
        groups = event_groups(s['evidence'])
        new_groups = [g for g in groups if any(_is_new(e,date) for e in g)]
        s['event_group_count'] = len(groups)
        s['new_catalyst_count'] = len(new_groups)
        s['new_plan_publication_count'] = sum(any(e.get('temporal_role')=='NEW_PLAN_PUBLICATION' for e in g) for g in groups)
        s['publication_unknown_group_count'] = sum(all(not timestamp(e.get('published_at')) for e in g) for g in groups)
        s['confirmed_independent_event_count'] = len({e['origin_event_id'] for g in groups for e in g
            if e.get('origin_event_id') and e.get('origin_verification') == 'OWNER_VERIFIED'})
        s['themes'] = sorted({t for e in s['evidence'] for t in themes_of(e.get('themes'))})
        s['why_watch'] = list(dict.fromkeys(e.get('mapping_reason') for e in s['evidence'] if e.get('mapping_reason')))
        if s['stage_observation'] is not None:
            s['why_watch'].insert(0,'进入原Stage固定池；原始排名和分数保持不变。')
        if s['close_observation'] is not None:
            s['why_watch'].append('原尾盘owner产物中的量价研究观察；未知催化不作确认。')
        if s['close_recapture_observation'] is not None:
            s['why_watch'].append('PyTDX尾盘分钟观测已在研究cutoff前可用；这是分钟观察，不代表完整日收盘价或正式推荐。')
        old = previous_stocks.get(s['symbol'])
        s['change'] = dict(status='NO_PRIOR_VERIFIED_OBSERVATION', previous_date=None, reasons=[])
        # New record/event IDs alone do not make a new business proposition.
        # Nor does an attention-review change assert price/volume confirmation.
        if old is not None:
            signatures={(p.get('event_type'),p.get('quote'),p.get('event_date_claim'))
                for e in old.get('evidence',[]) for p in e.get('propositions',[])}
            added=[p for g in new_groups for e in g for p in e.get('propositions',[])
                if (p.get('event_type'),p.get('quote'),p.get('event_date_claim')) not in signatures]
            reasons=(['新增目标日已捕获的本股命题，进入证据复核；未确认行情转强或交易条件。'] if added else
                     ['未新增已核目标日本股命题；不因更换记录ID或转载旧内容自动升档。'])
            s['change']=dict(status='NEW_SUBJECT_EVIDENCE' if added else 'UNCHANGED',
                previous_date=previous['target_trade_date'],reasons=reasons,
                evidence_ids=sorted({p['evidence_id'] for p in added}))
        s['attention_priority']='RESEARCH_WATCH'  # final role/time explanation below
        missing = [] if s['connect_eligibility']=='VERIFIED_TARGET_UNIVERSE' else ['港股通资格须按目标日单独核验']
        if s['close_observation'] is None:
            missing.append('同时间段成交基线和价格位置尚未验证')
        if old is None:
            missing.append('无前一交易日同股验证产物，连续走强未判定')
        if not new_groups:
            missing.append('现有材料不证明目标日实时捕获新催化')
        s['plan'] = stock_plan(s,context,quote=(price_quotes or {}).get(s['symbol']),
                               late_tail_observation=s['close_recapture_observation'])
        s['plan']['missing'] = list(dict.fromkeys([*s['plan']['missing'],*missing]))
    from .workspace_briefing import build_briefing
    ordered_stocks=list(stocks.values())
    briefing=build_briefing(accepted_materials,ordered_stocks,context)
    theme_rows=briefing['themes']
    gaps.extend(briefing['briefing']['gaps'])
    lane_values=[('STAGE','shared_data.stage_selection → StageSelectionConsumer',stage_value,stage_rows),
                 ('CATALYST','ManagerResearchJobService / catalyst_observations.refresh',dict(catalyst),raw_cards),
                 ('CLOSE','ops.materialize_manager_close_discovery',close_value,close_rows)]
    lanes=[]
    for lane,owner,value,rows in lane_values:
        lane_gaps=list(value.get('cannot_confirm') or value.get('gaps') or [])
        if lane=='CATALYST':
            lane_gaps.extend(source_gaps)
            bindings=value.get('input_bindings',[])
            news=[b for b in bindings if isinstance(b,Mapping) and b.get('kind')=='HOURLY_NEWS']
            value['input_coverage']={**(value.get('input_coverage') or {}),
                'hourly_news_artifact_count':len(news),
                'missing_publication_sidecar_count':sum(b.get('publication_sha256') is None for b in news),
                'material_admission_count':sum(isinstance(b,Mapping) and b.get('kind')=='MATERIAL_ADMISSION' for b in bindings),
                'archive_materials':deepcopy((value.get('archive_projection') or {}).get('coverage') or {}),
                'global_market_coverage':'NOT_ESTABLISHED'}
        elif lane=='STAGE':
            value['input_coverage']={k:value.get(k) for k in ('requested_rows','source_rows','selected_rows','coverage_ratio','missing_symbols')}

        count=len({canonical_symbol(r.get('symbol') or r.get('code'),r.get('market','HK')) for r in rows
                   if isinstance(r,Mapping) and canonical_symbol(r.get('symbol') or r.get('code'),r.get('market','HK'))}) if value.get('status') in _DATA else None
        lanes.append(lane_status(lane,owner,date,status=value.get('status','NOT_RUN'),count=count,gaps=lane_gaps,
            artifact={**value,'consumed':bool(value and value.get('status') in _DATA)},
            attempt=attempts.get(lane),next_plan=plans.get(lane)))
    screen = deepcopy(dict(market_screen)) if isinstance(market_screen, Mapping) else None
    screen_summary_counts = _market_screen_summary_counts(screen)
    result= dict(schema_version=SCHEMA,semantic_version=SEMANTIC_VERSION,rejected_relations=rejected_relations,
        decision_projection_version='20260921.manager-decision-ux.a1',
        target_trade_date=date,stocks=ordered_stocks,themes=theme_rows,lanes=lanes,
        briefing=briefing['briefing'],company_events=briefing['company_events'],focus_symbols=briefing['focus_symbols'],
        materials=accepted_materials, gaps=sorted(set(gaps)),
        close_recapture_evidence=requested_day_projection,
        planning_close_recapture_evidence=close_recapture_projection,
        summary=dict(stock_count=len(stocks),relation_count=len(candidate_cards),theme_count=len(theme_rows),
                     reused_material_count=len(accepted_materials),formal_recommendation_count=0,
                     focus_count=len(briefing['focus_symbols']),input_relation_count=len(original_candidate_cards),
                     rejected_fragment_count=len(rejected_relations),
                     market_screen_strict_count=screen_summary_counts[0],
                     market_screen_near_count=screen_summary_counts[1],
                     market_screen_card_count=screen_summary_counts[2]),
        replacement_context='COMPARISON_ONLY_NO_POSITION_READ',
        input_identity=digest(dict(decision_projection_version='20260921.manager-decision-ux.a1',semantic_version=SEMANTIC_VERSION,catalyst=catalyst,materials=materials,stage=stage,close=close,
            discovered_cards=discovered_cards,discovery_rejections=discovery_rejections,price_quotes=price_quotes,
            market_screen=screen,
            plan_context={k:v for k,v in context.items() if k!='research_cutoff'} if plan_context else None)),
        plan_context=context,
        browser_consumption='NOT_ACKNOWLEDGED_BY_SERVER',**FLAGS)
    if screen is not None:
        result['market_screen'] = screen
    return result
