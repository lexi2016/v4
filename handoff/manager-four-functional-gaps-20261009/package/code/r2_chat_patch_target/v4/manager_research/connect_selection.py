"""Target-date HK Connect scope for the Manager's read-only candidate views.

Uses the EXISTING full-market universe reader, never a Stage list, native HK
name, ticker allowlist, or a new eligibility producer. Original Stage/screen
products are not rewritten. A present-time authority readback is explicitly
not a claim of historical PIT capture of the entire selection process.
"""
from __future__ import annotations
from copy import deepcopy
import os
import hashlib
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from .workspace_projection import FLAGS, canonical_symbol, date_token, digest, timestamp


def calendar_applicability(context: Mapping[str, Any]) -> dict:
    """Read the EXISTING calendar, bound to the plan's calendar bytes.

    Applicability is not membership. A Connect holiday does not prove or
    replace any target-date universe; both results remain independently visible.
    """
    date = date_token(context['plan_trade_date'])
    out = dict(status='CANNOT_CONFIRM', reason='HK_CONNECT_CALENDAR_UNVERIFIED',
        target_trade_date=date, calendar_owner='contracts.trading_calendar',
        calendar_sha256=None, hk_securities_state='UNKNOWN', hk_connect_state='UNKNOWN')
    expected = context.get('calendar_sha256')
    if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        return out
    try:
        from contracts.trading_calendar import (CALENDAR_PATH, load_market_calendar,
            resolve_market_states, TradingDayState)
        before = hashlib.sha256(CALENDAR_PATH.read_bytes()).hexdigest()
        if before != expected:
            out['reason'] = 'HK_CONNECT_CALENDAR_IDENTITY_MISMATCH'
            return out
        calendar = load_market_calendar()
        if hashlib.sha256(CALENDAR_PATH.read_bytes()).hexdigest() != before:
            out['reason'] = 'HK_CONNECT_CALENDAR_CHANGED_DURING_READ'
            return out
        states = resolve_market_states(calendar, date)
        state = states['hk_connect']
        out.update(calendar_sha256=before,
            hk_securities_state=states['hk_securities'].value, hk_connect_state=state.value)
        if state == TradingDayState.NON_TRADING_DAY:
            out.update(status='NOT_APPLICABLE', reason='HK_CONNECT_NON_TRADING_DAY')
        elif state in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
            out.update(status='APPLICABLE', reason='HK_CONNECT_TRADING_DAY')
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError):
        # Missing dependency is not evidence of a closed market.
        pass
    return out


def formal_selection(scope: Mapping[str, Any], date: str, count: int) -> dict:
    calendar = scope.get('calendar_applicability') or {}
    state = calendar.get('status') if calendar.get('target_trade_date') == date else None
    if state == 'NOT_APPLICABLE':
        status, reason = 'NOT_APPLICABLE', 'HK_CONNECT_NON_TRADING_DAY'
    elif state != 'APPLICABLE':
        status, reason = 'CANNOT_CONFIRM', 'HK_CONNECT_CALENDAR_UNVERIFIED'
    else:
        error = _scope_error(scope, date)
        status = 'CANNOT_CONFIRM' if error else 'READY' if count else 'READY_EMPTY'
        reason = error or 'TARGET_DATE_MEMBERSHIP_VERIFIED_NOT_BUY_ADMISSION'
    return dict(status=status, reason=reason, target_trade_date=date,
        candidate_count=count if status in {'READY','READY_EMPTY'} else 0 if status=='NOT_APPLICABLE' else None,
        membership_status=scope.get('status','CANNOT_CONFIRM'),
        calendar=deepcopy(calendar), qualified=False, buy_allowed=False, **FLAGS)


def read_scope(context: Mapping[str, Any]) -> dict:
    date=date_token(context['plan_trade_date'])
    result=dict(status='CANNOT_CONFIRM',target_trade_date=date,codes=[],source=None,
                identity=None,gaps=[],read_only=True,
                calendar_applicability=calendar_applicability(context),**FLAGS)
    configured=os.environ.get('V4_MANAGER_UNIVERSE_ROOT','').strip()
    if not configured:
        result['gaps']=['HK_CONNECT_TARGET_AUTHORITY_ROOT_NOT_BOUND'];return result
    root=Path(configured).expanduser()
    if not root.is_absolute() or '..' in root.parts or root.is_symlink():
        result['gaps']=['HK_CONNECT_TARGET_AUTHORITY_ROOT_INVALID'];return result
    # Only the exact target-date V2 authority can grant formal eligibility.
    # A prior-session capture is retained separately as source evidence.
    owner_text=os.environ.get('V4_MANAGER_UNIVERSE_OWNER_ROOT','').strip()
    owner_sha=os.environ.get('V4_MANAGER_UNIVERSE_OWNER_SHA256','').strip()
    owner_kwargs={}
    target_failure='HK_CONNECT_TARGET_AUTHORITY_OWNER_BINDING_REQUIRED'
    try:
        if not owner_text or not owner_sha:
            raise ValueError(target_failure)
        owner_root=Path(owner_text)
        valid=(owner_root.is_absolute() and '..' not in owner_root.parts
            and owner_root.resolve()==owner_root and not owner_root.is_symlink()
            and re.fullmatch(r'[0-9a-f]{64}',owner_sha) is not None)
        if not valid:
            raise ValueError('HK_CONNECT_TARGET_AUTHORITY_OWNER_BINDING_INVALID')
        owner_kwargs=dict(authority_owner_root=owner_root,authority_owner_sha256=owner_sha)
        result['authority_reader_binding']=dict(mode='EXPLICIT_SOURCE_PIN',
            owner_root=str(owner_root),source_code_ref='stage_center/hk_universe_preflight.py',
            source_code_sha256=owner_sha)
        from domains.manager_research_evidence import read_universe_evidence
        # Do not inject the plan cutoff as a fake clock into this reader.
        # This invokes native readback only, never ensure/capture/materialize.
        universe=read_universe_evidence(root,date,require_v2=True,**owner_kwargs)
        source=dict(universe.source)
        cutoff=timestamp(context.get('research_cutoff'))
        acquired=timestamp(source.get('acquired_at'))
        available=timestamp(source.get('available_at'))
        if (source.get('source_date')!=date or source.get('market')!='HK_CONNECT'
                or acquired is None or available is None or cutoff is None
                or acquired>cutoff or available>cutoff):
            raise ValueError('HK_CONNECT_TARGET_AUTHORITY_AFTER_CUTOFF_OR_WRONG_DATE')
        codes=sorted(set(universe.codes))
        if not codes or any(canonical_symbol(c)!=c for c in codes):
            raise ValueError('HK_CONNECT_TARGET_AUTHORITY_CODES_INVALID')
        result.update(status='OWNER_VERIFIED',codes=codes,source=source,
            identity=digest([date,codes,source['sha256']]),
            membership_semantics='TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2',
            availability_semantics='PERSISTED_ACQUIRED_AND_PUBLICATION_TIMES_MUST_PRECEDE_RESEARCH_CUTOFF')
        return result
    except (ImportError,OSError,ValueError,KeyError,TypeError,RuntimeError) as exc:
        reason=str(exc)
        if not re.fullmatch(r'[A-Z0-9_:. -]{1,180}',reason):reason=type(exc).__name__
        target_failure='HK_CONNECT_TARGET_AUTHORITY_UNVERIFIED:'+reason
        diagnostic=getattr(exc,'diagnostic',None)
        if isinstance(diagnostic,Mapping):
            result['authority_diagnostic']=deepcopy(dict(diagnostic))
    capture_root=os.environ.get('V4_MANAGER_HK_CAPTURE_RECEIPT_ROOT','').strip()
    dispatch_root=os.environ.get('V4_MANAGER_HK_DISPATCH_RECEIPT_ROOT','').strip()
    market_session=context.get('market_session')
    if capture_root and dispatch_root and market_session:
        from .connect_capture_adapter import read_d1_scope
        d1=read_d1_scope(context,security_master_root=root,
            capture_receipt_root=capture_root,dispatch_receipt_root=dispatch_root)
        result['previous_session_capture']=d1
        result['gaps']=[target_failure,*d1.get('gaps',[])]
    else:
        result['gaps']=[target_failure]
    return result


def _scope_error(scope: Mapping[str,Any], target_date: str) -> str | None:
    source=scope.get('source');codes=scope.get('codes')
    if (scope.get('status')!='OWNER_VERIFIED' or not isinstance(source,Mapping)
            or not isinstance(codes,list) or any(not isinstance(c,str) for c in codes)
            or codes!=sorted(set(codes))
            or any(canonical_symbol(c)!=c for c in codes)
            or not re.fullmatch(r'[0-9a-f]{64}',str(source.get('sha256','')))):
        return 'TARGET_HK_CONNECT_MEMBERSHIP_UNVERIFIED'
    if (scope.get('target_trade_date')!=target_date
            or source.get('market')!='HK_CONNECT' or source.get('role')!='HK_CONNECT_FULL_MARKET_AUTHORITY'):
        return 'TARGET_HK_CONNECT_MEMBERSHIP_DATE_OR_ROLE_MISMATCH'
    semantics=scope.get('membership_semantics')
    if semantics=='TARGET_DATE_CAPTURED_HK_CONNECT_AUTHORITY_V2':
        if source.get('source_date')!=target_date:
            return 'TARGET_HK_CONNECT_MEMBERSHIP_DATE_OR_ROLE_MISMATCH'
        expected_identity=digest([target_date,codes,source['sha256']])
    elif semantics=='EXACT_PREVIOUS_FULL_SESSION_CAPTURED_CONNECT_CODES':
        return 'TARGET_HK_CONNECT_AUTHORITY_V2_REQUIRED'
    else:
        return 'HK_CONNECT_MEMBERSHIP_SEMANTICS_UNVERIFIED'
    if scope.get('identity')!=expected_identity:
        return 'TARGET_HK_CONNECT_MEMBERSHIP_IDENTITY_MISMATCH'
    return None


def filter_cards(cards: Sequence[Mapping[str,Any]], scope: Mapping[str,Any], *, target_date: str | None=None) -> tuple[list[dict],list[dict]]:
    target_date=target_date or scope.get('target_trade_date')
    error=_scope_error(scope,target_date);allowed=set(scope.get('codes') or [])
    out=[];rejected=[]
    for raw in cards:
        if not isinstance(raw,Mapping):continue
        symbol=raw.get('symbol') or raw.get('code')
        reason=error
        if not reason and canonical_symbol(symbol,raw.get('market','HK'))!=symbol:
            reason='NON_HK_SECURITY_IDENTITY'
        if not reason and symbol not in allowed:reason='NOT_IN_TARGET_HK_CONNECT_UNIVERSE'
        if reason:
            rejected.append(dict(symbol=symbol,name=raw.get('name'),card_id=raw.get('card_id'),
                event_id=raw.get('event_id'),art_code=raw.get('art_code'),reason=reason,
                source_refs=deepcopy(raw.get('source_refs',[]))))
            continue
        row=deepcopy(dict(raw))
        # A witness clock is diagnostic only, not a source clock and not a
        # volatile component of input_identity/idempotency.
        row.update(connect_eligibility='VERIFIED_TARGET_UNIVERSE',
            membership_source={k:deepcopy(v) for k,v in scope['source'].items() if k!='available_at'},
            membership_input_identity=scope['identity'],
            membership_semantics='TARGET_DATE_AUTHORITY_AS_READ_NOT_HISTORICAL_SELECTION_CAPTURE')
        out.append(row)
    return out,rejected


def gate_workspace(value: Mapping[str,Any],scope: Mapping[str,Any]) -> dict:
    out=deepcopy(dict(value));date=out['target_trade_date']
    stocks,rejected=filter_cards(out.get('stocks',[]),scope,target_date=date)
    formal = formal_selection(scope, date, len(stocks))
    if formal['status'] not in {'READY', 'READY_EMPTY'}:
        rejected.extend(dict(symbol=r.get('symbol'), name=r.get('name'),
            reason=formal['reason'], source_refs=deepcopy(r.get('source_refs', []))) for r in stocks)
        stocks = []
    allowed={r['symbol'] for r in stocks}
    out['stocks']=stocks
    out['focus_symbols']=[s for s in out.get('focus_symbols',[]) if s in allowed]
    out['company_events']=[e for e in out.get('company_events',[]) if e.get('symbol') in allowed]
    for t in out.get('themes',[]):
        t['mappings']=[m for m in t.get('mappings',[]) if m.get('symbol') in allowed]
        t['mapped_symbols']=sorted({m['symbol'] for m in t['mappings']})
        t['mapped_stock_count']=len(t['mapped_symbols'])
    out.setdefault('summary',{}).update(stock_count=len(stocks),focus_count=len(out['focus_symbols']))
    out.setdefault('briefing',{})['focus_count']=len(out['focus_symbols'])
    out['connect_selection_rejections']=rejected
    out['gaps']=sorted(set([*out.get('gaps',[]),*scope.get('gaps',[])]))
    out['input_identity']=digest([out.get('input_identity'),scope.get('identity'),'HK_CONNECT_RESEARCH_SCOPE_V2',scope.get('calendar_applicability')])
    return out


def evidence_view(screen: Mapping[str,Any], lane: Mapping[str,Any], scope: Mapping[str,Any]) -> tuple[dict,dict]:
    """Private inputs for research attention; original screen/Stage stay intact."""
    screen=deepcopy(dict(screen));lane=deepcopy(dict(lane))
    for product, keys in ((screen, ('cards','strict','near','pending')),
                          (lane, ('official_documents','eastmoney_hk_documents','observations','pending_observations'))):
        counts = {}; reasons = {}
        for key in keys:
            if not isinstance(product.get(key),list):continue
            raw = product[key]
            product[key], rejected = filter_cards(raw,scope)
            counts[key] = dict(input=len(raw), admitted=len(product[key]), rejected=len(rejected))
            # Counts are per input list, not unique securities/documents.
            for row in rejected:
                reason = row['reason']; reasons[reason] = reasons.get(reason,0) + 1
        product['research_scope_diagnostics'] = dict(
            status='CANNOT_CONFIRM' if _scope_error(scope,scope.get('target_trade_date')) else 'OWNER_VERIFIED',
            target_trade_date=scope.get('target_trade_date'),
            membership_identity=scope.get('identity'), counts=counts, rejection_reasons=reasons,
            gaps=deepcopy(scope.get('gaps',[])), count_basis='PER_INPUT_LIST_NOT_UNIQUE_SECURITIES',
            formal_selection=formal_selection(scope,scope.get('target_trade_date'),0))
    # Preserve ONLY the original owner's already-classified positives in a
    # separate unscored observation lane; never send them to official_evidence.
    for row in lane.get('positive_observations',[]) or []:
        if not isinstance(row,dict):continue
        _, rejected = filter_cards([row],scope)
        row['target_connect_membership'] = dict(
            status='CANNOT_CONFIRM' if _scope_error(scope,scope.get('target_trade_date')) else
                   'NOT_IN_TARGET_UNIVERSE' if rejected else 'VERIFIED_TARGET_UNIVERSE',
            target_trade_date=scope.get('target_trade_date'), authority_identity=scope.get('identity'),
            reason=rejected[0]['reason'] if rejected else 'TARGET_DATE_MEMBERSHIP_VERIFIED')
        # Keep original safety flags intact for the downstream observation validator.
    return screen,lane


def selection_diagnostics(value: Mapping[str,Any],attention: Mapping[str,Any],sources: Mapping[str,Any],scope: Mapping[str,Any],material_rejections: Sequence[Mapping[str,Any]]) -> dict:
    focus=set(value.get('focus_symbols',[]));rows={}
    for stock in value.get('stocks',[]):
        if stock.get('symbol') not in focus:continue
        evidence=[deepcopy(e) for e in stock.get('evidence',[]) if e.get('semantic_status')=='ACCEPTED']
        rows[stock['symbol']]=dict(symbol=stock['symbol'],name=stock['name'],
            reason=deepcopy(stock.get('why_watch',[])),evidence=evidence,
            candidate_kind='COMPANY_RESEARCH_NOT_BUY',qualified=False,buy_allowed=False,**FLAGS)
    for card in attention.get('cards',[]):
        relations=[e for e in card.get('evidence',[]) if e.get('evidence_lane') in {'US_INDIVIDUAL_MAPPING','US_INDUSTRY_MAPPING'}]
        if not relations:continue
        row=rows.setdefault(card['symbol'],dict(symbol=card['symbol'],name=card['name'],reason=[],evidence=[],
            candidate_kind='BUSINESS_RELATION_RESEARCH_NOT_BUY',qualified=False,buy_allowed=False,**FLAGS))
        for e in relations:
            rel=e['hk_relation'];row['reason'].append(rel.get('issuer_quote',''))
            row['evidence'].append(deepcopy(e))
    rejected=[*sources.get('rejections',[]),*material_rejections,*value.get('connect_selection_rejections',[])]
    return dict(schema_version='v4.manager_research.selection_diagnostics.v1',
        target_trade_date=value['target_trade_date'],source_capture_dates=[c.get('target_trade_date') for c in sources.get('captures',[])],
        status='PARTIAL' if scope.get('gaps') or sources.get('gaps')
            or formal_selection(scope,value['target_trade_date'],len(focus))['status']=='CANNOT_CONFIRM' else 'READY',
        formal_selection=formal_selection(scope,value['target_trade_date'],len(focus)),
        research_attention_status=attention.get('status','CANNOT_CONFIRM'),
        candidate_scope='RESEARCH_RELATIONS_NOT_FORMAL_CONNECT_SELECTION',
        candidates=[rows[k] for k in sorted(rows)],candidate_count=len(rows),
        rejections=deepcopy(rejected),us_relation_audit=deepcopy(attention.get('us_mapping_diagnostics',{}).get('material_relation_audit',[])),
        raw_us_movers_retained=True,original_stage_unchanged=True,original_screen_unchanged=True,
        membership=deepcopy(dict(scope)),capture_input_identity=sources.get('input_identity'),
        # The general diagnostics also report peripheral research-attention
        # gaps. Preserve those for their own panel, but expose the dependencies
        # relevant to HK Connect independently for the daily-channel projection.
        connect_gaps=sorted(set([*sources.get('gaps',[]),*scope.get('gaps',[])])),
        gaps=sorted(set([*sources.get('gaps',[]),*scope.get('gaps',[]),*attention.get('gaps',[])])),**FLAGS)
