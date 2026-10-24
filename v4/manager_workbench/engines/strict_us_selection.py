"""Single frozen US-to-HK research selector and compatibility projections."""
from __future__ import annotations
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation, DecimalException
from datetime import datetime
from functools import lru_cache
from pathlib import Path
import hashlib
import json

from ..contracts import GateDecision, StrictSelectionDecision, MappingSelectionSummary, digest
from .common import current, valid_sha, membership as target_membership
from .us_mapping_policy import POLICY, POLICY_VERSION, POLICY_SHA256, RELATIONSHIP_A, US_SYMBOL_THEMES

RULES_VERSION = POLICY_VERSION
RULES_SHA256 = POLICY_SHA256
MAPPING_POLICY_VERSION = POLICY_VERSION
MAPPING_POLICY_SHA256 = POLICY_SHA256
SINGLE_DAY_MAPPING_VERSION = 'US_HK_SINGLE_DAY_MAPPING_V1_20261019'
BASIC_UNIT_CHECK_SHA256 = '6118718612b3be075d7757e37874564ca7fa09b35dddfca2f6c943aacbfc0d03'


def _decimal(value):
    if isinstance(value, bool) or value is None: return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError, TypeError): return None


def _text(value): return format(value, 'f') if value is not None else None


@lru_cache(maxsize=1)
def engine_identity():
    root = Path(__file__).resolve().parents[1]
    paths = ['engines/strict_us_selection.py','engines/us_mapping_consumption.py',
        'engines/us_mapping.py','engines/us_mapping_policy.py','inputs/strict_us_selection.py',
        'inputs/native.py','inputs/source_bindings.py','contracts.py']
    hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in paths}
    for rel in ['upstreams/v3_shared_data/shared_data/hk_panel_audit.py','contracts/market_calendar_2026.json']:
        source=root.parents[1]/rel
        hashes[rel]=hashlib.sha256(source.read_bytes()).hexdigest() if source.is_file() else 'UNAVAILABLE'
    return digest(hashes)


def _expected_sessions(context):
    from contracts.trading_calendar import load_market_calendar, previous_session
    calendar = load_market_calendar()
    end = previous_session(calendar, context['target_date'], market='hk_securities')
    sessions = [end]
    while len(sessions)<21:
        sessions.append(previous_session(calendar,sessions[-1],market='hk_securities'))
    return list(reversed(sessions))


def _metrics(history, close_sessions, amount_sessions):
    bars = history.get('bars') if isinstance(history,dict) else None
    if not isinstance(bars,list): return {}, ['HK_HISTORY_ROWS_MISSING']
    indexed = defaultdict(dict)
    malformed = False
    for bar in bars:
        if not isinstance(bar,dict): malformed=True; continue
        day = bar.get('date')
        if day not in close_sessions: continue
        # Compare only facts used by this frozen window, retaining duplicate refs upstream.
        fact = dict(date=day,close=bar.get('close'))
        if day in amount_sessions: fact['amount']=bar.get('amount')
        for key in ('suspended','open','high','low'):
            if key in bar: fact[key]=bar[key]
        try: indexed[day][digest(fact)]=bar
        except (ValueError,TypeError): malformed=True
    if any(len(rows)>1 for rows in indexed.values()): return {}, ['HK_HISTORY_CONFLICTING_DUPLICATE_SESSION']
    if malformed: return {}, ['HK_HISTORY_ROWS_INVALID']
    if any(day not in indexed for day in close_sessions): return {}, ['HK_CLOSE_21_SESSION_WINDOW_INCOMPLETE']
    by_date = {day:next(iter(rows.values())) for day,rows in indexed.items()}
    closes = [_decimal(by_date[day].get('close')) for day in close_sessions]
    amounts = [_decimal(by_date[day].get('amount')) for day in amount_sessions]
    gaps=[]
    if any(v is None or v<=0 for v in closes): gaps.append('HK_CLOSE_NONFINITE_OR_NONPOSITIVE')
    if any(v is None or v<0 for v in amounts): gaps.append('HK_AMOUNT_NONFINITE_OR_NEGATIVE')
    if history.get('history_holds'): gaps.append('HK_HISTORY_FIELD_QUARANTINED')
    if gaps: return {},gaps
    try:
        ma20=sum(closes[-20:])/20
        return dict(hk_previous_close=_text(closes[-1]),hk_close=_text(closes[-1]),hk_ma20=_text(ma20),
            hk_close_to_ma20=_text(closes[-1]/ma20),hk_return_5_sessions_pct=_text((closes[-1]/closes[-6]-1)*100),
            hk_mean_turnover20_hkd=_text(sum(amounts)/20)),[]
    except DecimalException: return {}, ['HK_HISTORY_ARITHMETIC_INVALID']


def evaluate_candidates(context, candidates, history_payload):
    """One strict judgment per normalized candidate; no data acquisition/writes."""
    history = history_payload if isinstance(history_payload,dict) else {}
    context = context if isinstance(context,dict) else {}
    source_sessions=context.get('source_sessions') or {}
    close_sessions=history.get('close_sessions') or []
    amount_sessions=history.get('amount_sessions') or []
    try: expected=_expected_sessions(context)
    except (ValueError,TypeError,KeyError): expected=[]
    window_ok=(bool(expected) and close_sessions==expected and amount_sessions==expected[-20:]
        and source_sessions.get('hk_price',source_sessions.get('HK_PRICE'))==expected[-1])
    identity_ok=(history.get('status')=='READY' and valid_sha(history.get('panel_sha256'))
        and valid_sha(history.get('panel_manifest_sha256')) and current(context,history.get('panel_available_at')))
    by_symbol=defaultdict(list)
    for row in history.get('rows') or []:
        if isinstance(row,dict): by_symbol[row.get('symbol')].append(row)
    decisions=[]
    for candidate in candidates:
        c=candidate.model_dump() if hasattr(candidate,'model_dump') else candidate
        paths=c.get('paths') or []
        primary=next((p for p in paths if p['path_id']==c.get('primary_path_id')),None)
        gates=[]
        def gate(name,state,actual=None,threshold=None,reasons=(),refs=()):
            gates.append(GateDecision(gate=name,state=state,actual=actual,threshold=threshold,
                reasons=list(dict.fromkeys(reasons)),source_refs=list(refs)))
        input_gaps=context.get('_selection_input_gaps') or []
        gate('source_contract','PENDING' if input_gaps else 'PASS',None,'VERIFIED_SOURCE_SCOPE',input_gaps)
        gate('window','PASS' if window_ok else 'PENDING',close_sessions,dict(close21=expected,amount20=expected[-20:]),[] if window_ok else ['HK_FROZEN_SESSION_WINDOW_INVALID'])
        gate('history_source','PASS' if identity_ok else 'PENDING',dict(panel_sha256=history.get('panel_sha256'),available_at=history.get('panel_available_at')),
            'HASH_BOUND_AND_AVAILABLE_BY_ORIGINAL_CUTOFF',[] if identity_ok else [history.get('gap') or 'HK_HISTORY_OWNER_IDENTITY_PENDING'])
        matching=by_symbol.get(c['symbol'],[])
        unique={digest(row):row for row in matching}
        h=next(iter(unique.values())) if len(unique)==1 else {}
        metrics,metric_gaps=_metrics(h,close_sessions,amount_sessions) if window_ok else ({},['HK_FROZEN_SESSION_WINDOW_INVALID'])
        if len(unique)>1: metrics={};metric_gaps=['HK_HISTORY_CONFLICTING_DUPLICATE_STOCK']
        ready=h.get('readiness') or {}
        readiness_ok=(isinstance(ready,dict) and ready.get('schema_version')=='hk_panel_strict_readiness.v1'
            and ready.get('code')==c['symbol'] and ready.get('target_date')==context.get('target_date')
            and ready.get('dependency_dates')==close_sessions and ready.get('cutoff')==context.get('cutoff')
            and ready.get('panel_sha256')==history.get('panel_sha256'))
        fields=ready.get('field_readiness',{}) if readiness_ok else {}
        for field in ['price','amount','currency','adjustment','pit','eligibility','suspension']:
            value=fields.get(field,'PENDING') if isinstance(fields,dict) else 'PENDING'
            if value not in {'PASS','PENDING','REJECT'}: value='PENDING'
            if not identity_ok or not window_ok: value='PENDING'
            refs=ready.get('evidence_refs') or []
            if value=='PASS' and not (refs and all(isinstance(r,dict) and valid_sha(r.get('sha256')) and r.get('reference') for r in refs)):
                value='PENDING'
            gate(field,value,dict(readiness_bound=readiness_ok),
                {'currency':'HKD','adjustment':'PIT_ADJUSTED','pit':'CORPORATE_ACTIONS_COMPLETE_AND_AVAILABLE','eligibility':'ELIGIBLE_ON_TARGET_DATE','suspension':'KNOWN_NOT_SUSPENDED_ON_TARGET_DATE'}.get(field,'CERTIFIED_WINDOW_FACTS'),
                [] if value=='PASS' else [field.upper()+'_PROOF_'+value,*ready.get('reasons',[])] if readiness_ok else ['HK_READINESS_BINDING_PENDING',field.upper()+'_PROOF_PENDING'],refs)
        primary_return=_decimal(primary.get('return_pct')) if primary else None
        evidence_ok=primary is not None and bool(primary.get('evidence_ids'))
        gate('source_evidence','PASS' if evidence_ok else 'PENDING',primary.get('evidence_ids') if primary else [],
            'BOUND_VERIFIED_SOURCE_EVIDENCE_IDS',[] if evidence_ok else ['SOURCE_EVIDENCE_IDS_PENDING'])
        theme=primary.get('primary_theme') if primary else None
        gate('primary_theme','PASS' if isinstance(theme,str) and bool(theme.strip()) else 'PENDING',theme,
            'KNOWN_PRIMARY_THEME_FOR_THEME3_CAP',[] if theme else ['PRIMARY_THEME_PENDING'])
        if primary is None:
            gate('individual_relation','PENDING',None,list(RELATIONSHIP_A),['INDIVIDUAL_POSITIVE_RELATION_NOT_PROVEN'])
        else:
            known_negative=(primary.get('status')=='PASS' and primary.get('scope')=='current_supported' and primary.get('direction')=='NEGATIVE')
            relation_ok=(primary.get('strict_supported') is True and primary.get('status')=='PASS'
                and primary.get('scope')=='current_supported' and primary.get('direction')=='POSITIVE')
            gate('individual_relation','REJECT' if known_negative else 'PASS' if relation_ok else 'PENDING',
                dict(path_id=primary['path_id'],scope=primary['scope'],direction=primary['direction']),
                'CURRENT_SUPPORTED_SPECIFIC_COMPANY_POSITIVE_TRANSMISSION',[] if relation_ok else ['INDIVIDUAL_RELATION_NOT_POSITIVE'] if known_negative else ['INDIVIDUAL_POSITIVE_RELATION_NOT_PROVEN',*primary.get('reasons',[])],primary.get('source_refs',[]))
        # Quote validity is orthogonal to missing history/relation material.
        quote_ok=primary is not None and primary_return is not None and not any(r.startswith(('QUOTE_','US_SOURCE_')) for r in primary.get('reasons',[]))
        gate('primary_return','PASS' if quote_ok and primary_return>=1 else 'REJECT' if quote_ok else 'PENDING',_text(primary_return),'1',
            [] if quote_ok and primary_return>=1 else ['PRIMARY_US_RETURN_BELOW_1_PERCENT'] if quote_ok else ['PRIMARY_US_QUOTE_PENDING'])
        secondary=[p for p in paths if p['role']=='INDIVIDUAL' and p['scope'] not in {'excluded','dated_weak'} and (primary is None or p['path_id']!=primary['path_id'])]
        conflicts=[];unknown=[]
        for p in secondary:
            value=_decimal(p.get('return_pct'))
            if p['status']!='PASS' or p['direction']=='UNKNOWN' or value is None: unknown.append(p['path_id'])
            elif value*(1 if p['direction']=='POSITIVE' else -1)<=-1: conflicts.append(p['path_id'])
        gate('secondary_paths','REJECT' if conflicts else 'PENDING' if unknown else 'PASS',dict(conflicts=conflicts,unknown=unknown),
            'NO_RELEVANT_INDIVIDUAL_OPPOSITE_OR_UNKNOWN', ['SECONDARY_INDIVIDUAL_CONFLICT'] if conflicts else ['SECONDARY_INDIVIDUAL_UNCERTAINTY'] if unknown else [])
        gate('numeric_facts','PASS' if metrics and not metric_gaps else 'PENDING',None,'COMPLETE_FINITE_NONCONFLICTING_WINDOW',metric_gaps)
        field_states={g.gate:g.state for g in gates}
        prices_ready=all(field_states.get(f)=='PASS' for f in ['price','currency','adjustment','pit'])
        amounts_ready=all(field_states.get(f)=='PASS' for f in ['amount','currency','pit'])
        tests=[('close_ma20_min','hk_close_to_ma20','1',lambda v:v>=1,prices_ready),
            ('close_ma20_max','hk_close_to_ma20','1.1',lambda v:v<=Decimal('1.1'),prices_ready),
            ('return5_max','hk_return_5_sessions_pct','15',lambda v:v<=15,prices_ready),
            ('turnover20_min','hk_mean_turnover20_hkd','20000000',lambda v:v>=20_000_000,amounts_ready)]
        for name,key,threshold,predicate,proven in tests:
            value=_decimal(metrics.get(key));known=proven and value is not None
            gate(name,'PASS' if known and predicate(value) else 'REJECT' if known else 'PENDING',_text(value),threshold,
                [] if known and predicate(value) else [name.upper()+'_FAILED'] if known else [name.upper()+'_PENDING'])
        states={g.state for g in gates};state='REJECT' if 'REJECT' in states else 'PENDING' if 'PENDING' in states else 'PASS'
        decisions.append(StrictSelectionDecision(symbol=c['symbol'],state=state,
            decision='QUALIFIED_NOT_SELECTED' if state=='PASS' else 'REJECTED' if state=='REJECT' else 'PENDING',qualified=state=='PASS',
            primary_path_id=c.get('primary_path_id'),primary_theme=primary.get('primary_theme') if primary else None,
            primary_return_pct=_text(primary_return),gates=gates,metrics=metrics,
            reasons=list(dict.fromkeys(r for g in gates for r in g.reasons)),
            evidence_ids=sorted({e for p in ([primary] if primary else [])+secondary for e in p.get('evidence_ids',[])})))
    qualified=sorted([d for d in decisions if d.qualified],key=lambda d:(-Decimal(d.primary_return_pct),-Decimal(d.metrics['hk_mean_turnover20_hkd']),d.symbol))
    themes=Counter();selected=0
    for rank,d in enumerate(qualified,1):
        d.rank=rank
        if selected>=10: d.reasons.append('TOP10_CAP')
        elif themes[d.primary_theme]>=3: d.reasons.append('PRIMARY_THEME3_CAP')
        else: d.decision='SELECTED';selected+=1;themes[d.primary_theme]+=1
    return decisions


def build_selection(context, candidates, history_payload):
    from .us_mapping_consumption import INDUSTRY_LISTING_VERSION, INDUSTRY_LISTING_POLICY
    decisions=evaluate_candidates(context,candidates,history_payload)
    counts=dict(candidate_count=len(candidates),current_supported=0,dated_weak=0,pending_research=0,
        selected=0,qualified_not_selected=0,rejected=0,pending=0,
        industry_match_count=sum(bool(c.industry_matches) for c in candidates))
    for c in candidates: counts[{'pending':'pending_research'}.get(c.research_state,c.research_state)]+=1
    for d in decisions: counts[{'SELECTED':'selected','QUALIFIED_NOT_SELECTED':'qualified_not_selected','REJECTED':'rejected','PENDING':'pending'}[d.decision]]+=1
    sessions=context.get('source_sessions') or {}
    complete=bool(candidates) and not context.get('_selection_input_gaps') and all(g.state!='PENDING' for d in decisions for g in d.gates)
    gaps=sorted({r for d in decisions for g in d.gates if g.state=='PENDING' for r in g.reasons})
    if not complete:gaps=sorted(set([*gaps,'STRICT_EVALUATION_INCOMPLETE',*(context.get('_selection_input_gaps') or [])]))
    return MappingSelectionSummary(policy_version=POLICY_VERSION,policy_sha256=POLICY_SHA256,engine_identity=engine_identity(),
        target_date=context['target_date'],source_session=sessions.get('us',sessions.get('US')),price_session=sessions.get('hk_price',sessions.get('HK_PRICE')),
        cutoff=context['cutoff'],candidates=candidates,strict_decisions=decisions,counts=counts,
        evaluation_complete=complete,gaps=gaps,listing_mode='INDUSTRY_MATCH',
        listing_policy_version=INDUSTRY_LISTING_VERSION,listing_policy_sha256=digest(INDUSTRY_LISTING_POLICY))


def single_day_mapping_context_ready(context):
    try:
        sessions=context.get('source_sessions') or {};target=context['target_date']
        return bool((sessions.get('us') or sessions.get('US'))<target and (sessions.get('hk_price') or sessions.get('HK_PRICE'))<target and current(context,context['cutoff']))
    except (TypeError,KeyError): return False


def legacy_mapping_projection(selection):
    value=selection.model_dump() if hasattr(selection,'model_dump') else selection
    rows=[]
    for c,d in zip(value['candidates'],value['strict_decisions']):
        primary=next((p for p in c['paths'] if p['path_id']==c['primary_path_id']),{})
        category={'POSITIVE':'BENEFIT','NEGATIVE':'RISK','CONFLICT':'CONFLICT','UNKNOWN':'UNASSESSED'}[c['direction']]
        primary_return=_decimal(primary.get('return_pct'))
        if category in {'BENEFIT','RISK'} and primary_return is not None and abs(primary_return)<1:category='OBSERVATION'
        rows.append(dict(c,decision=category,strict_decision=d['decision'],strict_state=d['state'],
            mapping_paths=c['paths'],mapping_grade='A' if primary.get('strict_supported') else 'C',
            primary_proxy=primary.get('us_symbol'),primary_us_symbol=primary.get('us_symbol'),primary_signed_return_pct=primary.get('return_pct'),
            primary_relation_type=primary.get('relation_type'),reason=(c['reasons'] or [None])[0],
            formal_target_eligibility='VERIFIED' if next((g['state'] for g in d['gates'] if g['gate']=='eligibility'),None)=='PASS' else 'CANNOT_CONFIRM'))
    counts={key:sum(r['decision']==key for r in rows) for key in ['BENEFIT','RISK','CONFLICT','OBSERVATION','SMALL_MOVE_WATCH','C_WATCH','UNMAPPED','UNASSESSED']}
    return dict(display_only=True,state='PARTIAL' if value['counts']['pending'] else 'READY',rows=rows,counts=counts,
        target_date=value['target_date'],source_session=value['source_session'],price_session=value['price_session'],
        rules_version=SINGLE_DAY_MAPPING_VERSION,mapping_policy_version=POLICY_VERSION,mapping_policy_sha256=POLICY_SHA256,
        strict_v1_status='EXECUTED',selected_count=value['counts']['selected'],strict_selection=value,
        outside_pool_observations=[],gaps=value['gaps'],historical_pit_verified=False,
        formal_target_eligibility='CANNOT_CONFIRM' if any(g['state']=='PENDING' for d in value['strict_decisions'] for g in d['gates'] if g['gate']=='eligibility') else 'PER_STOCK_TARGET_PROOF',
        RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)


def cannot_confirm_single_day_mapping(context, reason):
    return dict(state='CANNOT_CONFIRM',rows=[],counts={},gaps=[reason],strict_v1_status='PENDING',display_only=True)


def run_single_day_mapping(context, *, relation_rows, industry_rows, factor_summary, membership,
        catalog_rows=None,catalog_stock_identities=None,catalog_expected_stock_count=None,manual_quote_scope=None):
    from .us_mapping_consumption import normalize_mapping_candidates
    candidates=normalize_mapping_candidates(context,relation_rows=relation_rows,catalog_rows=catalog_rows or [],
        industry_rows=industry_rows,manual_quote_scope=manual_quote_scope,
        identities=catalog_stock_identities or (membership or {}).get('codes',[]))
    return legacy_mapping_projection(build_selection(context,candidates,{}))


def run_strict_us_selection(context, *, relation_rows, industry_rows, factor_summary,payload):
    from .us_mapping_consumption import normalize_mapping_candidates
    candidates=normalize_mapping_candidates(context,relation_rows=relation_rows,industry_rows=industry_rows,
        identities=(payload.get('monthly_membership') or {}).get('codes',[]))
    selection=build_selection(context,candidates,payload.get('hk_history') or {})
    return dict(selection.model_dump(),rows=[d.model_dump() for d in selection.strict_decisions],
        selected=[d.model_dump() for d in selection.strict_decisions if d.decision=='SELECTED'],selected_count=selection.counts['selected'],
        state='CANNOT_CONFIRM' if selection.counts['pending'] else 'READY',gaps=selection.gaps,
        historical_pit_verified=False,RESEARCH_ONLY=True,production_allowed=False,buy_gate_updated=False,orders_sent=False)
