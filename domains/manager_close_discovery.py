"""Existing-owner 15:30 research observations, NOT formal stock selection.

Complete rule: verified >100m HKD AND verified volume expansion AND
(verified oversold recovery OR verified breakout) AND new direct PIT catalyst.
The supplied owners contain no approved same-time volume/position authority or
rule. Those two legs are explicitly incomplete; raw ratios/rule strings/daily
returns cannot stand in for them. Other verified observations are still useful
and remain visible, without promotion to a complete candidate.
"""
from __future__ import annotations
from collections import Counter
from datetime import datetime
import hashlib
import math
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo
from infrastructure.manager_input_attestation import encoded, digest, aware
from domains.manager_research_evidence import VerifiedUniverse, VerifiedSnapshot, admitted
from domains.manager_catalyst_tracking import CatalystEvent, candidate_catalyst, theme_summary

HK_TZ=ZoneInfo('Asia/Hong_Kong')
SCHEMA_VERSION='v4.manager_workbench.research.v1'
MARKET='HK_CONNECT'; SLOT='1530'
RULE_VERSION='manager-close-rework-r2-v1'
TURNOVER_THRESHOLD_HKD=100_000_000.0
FOUR_FLAGS={'RESEARCH_ONLY':True,'production_allowed':False,'buy_gate_updated':False,'orders_sent':False}
REQUIRED_PREDICATES=('turnover_gt_100m_hkd','verified_volume_expansion','verified_oversold_or_breakout','new_direct_pit_catalyst')
RULE_DEFINITION={
    'rule_version':RULE_VERSION,'operator':'ALL',
    'required_predicates':list(REQUIRED_PREDICATES),
    'position_operator':'ANY_VERIFIED','position_legs':['OVERSOLD_RECOVERY','BREAKOUT'],
    'turnover_currency':'HKD','turnover_unit':'HKD','turnover_operator':'>','turnover_threshold':100_000_000,
    'volume_authority':'INPUT_AND_APPROVED_RULE_MISSING',
    'position_authority':'INPUT_AND_APPROVED_RULE_MISSING',
    'rule_authorization':'USER_FOUR_LEG_CONJUNCTION_ONLY_NO_NEW_NUMERIC_VOLUME_POSITION_RULE',
}


def iso_seconds(value: datetime) -> str:
    if value.tzinfo is None: raise ValueError('AS_OF_MUST_BE_AWARE')
    return value.astimezone(HK_TZ).isoformat(timespec='microseconds')


def finite_number(value: Any) -> float | None:
    if isinstance(value,bool) or value is None: return None
    try: number=float(value)
    except (ValueError,TypeError): return None
    return number if math.isfinite(number) else None


def normalize_hk_code(value: Any) -> str | None:
    import re
    if isinstance(value,str) and re.fullmatch(r'HK\.\d{5}',value): return value
    return None


def _quote_time(value: Any, trade_date: str, as_of: datetime) -> datetime | None:
    if not isinstance(value,str): return None
    try: observed=datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError: return None
    # The existing shared bridge carries Futu's HK market update_time. This
    # conversion applies only to that field, never to a baseline/availability.
    if observed.tzinfo is None: observed=observed.replace(tzinfo=HK_TZ)
    observed=observed.astimezone(HK_TZ)
    if observed.strftime('%Y%m%d')!=trade_date or observed>as_of: return None
    return observed


def _text(value: Any) -> str | None:
    return value.strip() if isinstance(value,str) and value.strip() else None


def _predicate(key: str,value: bool | str,reason: str,refs: Sequence[str]) -> dict:
    return {'predicate_id':key,'value':value,'reason':reason,'input_refs':list(refs),'rule_version':RULE_VERSION}


def _and(values: Sequence[bool | str]) -> bool | None:
    if any(v is False for v in values): return False
    if len(values)==4 and all(v is True for v in values): return True
    return None


def build_workbench_payload(*, trade_date: str, as_of: datetime, generated_at: datetime,
    universe_source: Mapping[str,Any], eligible_symbols: Sequence[str],
    snapshot_rows: Sequence[Mapping[str,Any]], snapshot_source: Mapping[str,Any],
    snapshot_errors: Sequence[str]=(), catalyst_events: Sequence[CatalystEvent]=(),
    catalyst_gaps: Sequence[str]=(), prior_candidates: Mapping[str,Any] | None=None,
    prior_source: Mapping[str,Any] | None=None, universe_evidence: VerifiedUniverse | None=None,
    snapshot_evidence: VerifiedSnapshot | None=None, prior_evidence: Any=None,
    condition_evidence: Any=None) -> dict:
    if as_of.tzinfo is None or generated_at.tzinfo is None or generated_at<as_of:
        raise ValueError('WORKBENCH_CLOCK_INVALID')
    as_of=as_of.astimezone(HK_TZ)
    if as_of.strftime('%Y%m%d')!=trade_date: raise ValueError('WORKBENCH_AS_OF_DATE_MISMATCH')
    verified=admitted(universe_evidence,snapshot_evidence,snapshot_rows)
    if verified:
        if (dict(universe_source)!=dict(universe_evidence.source)
            or dict(snapshot_source)!=dict(snapshot_evidence.source)
            or tuple(eligible_symbols)!=universe_evidence.codes):
            raise ValueError('WORKBENCH_EVIDENCE_ARGUMENT_MISMATCH')
    condition_audit=None
    if condition_evidence is not None:
        from domains.manager_condition_evidence import condition_details
        condition_audit=condition_details(condition_evidence,universe=universe_evidence,
                                          snapshot=snapshot_evidence,as_of=as_of)
    eligible=set(eligible_symbols)
    if len(eligible)!=len(eligible_symbols) or any(normalize_hk_code(c) is None for c in eligible):
        raise ValueError('WORKBENCH_UNIVERSE_CODES_INVALID')
    from domains.manager_catalyst_tracking import verified_prior_rows
    prior,prior_lineage=verified_prior_rows(prior_evidence)
    # The old loose prior_candidates/source arguments deliberately convey no
    # authority. Kept only for compatibility with supplied adversarial probes.
    counts=Counter(x.get('code') for x in snapshot_rows if isinstance(x,Mapping))
    quote_gaps=[]; candidates=[]; covered=0
    for raw in snapshot_rows:
        if not isinstance(raw,Mapping): quote_gaps.append('QUOTE_OBJECT_INVALID'); continue
        symbol=normalize_hk_code(raw.get('code'))
        if symbol not in eligible: quote_gaps.append('QUOTE_NOT_IN_EXACT_UNIVERSE'); continue
        if counts[symbol]!=1: quote_gaps.append('DUPLICATE_QUOTE_EXCLUDED:'+symbol); continue
        observed=_quote_time(raw.get('update_time'),trade_date,as_of)
        amount=finite_number(raw.get('turnover'))
        price=finite_number(raw.get('last_price',raw.get('price')))
        prev=finite_number(raw.get('prev_close_price',raw.get('last_close')))
        if observed is None or amount is None or amount<0 or price is None or price<=0 or prev is None or prev<=0:
            quote_gaps.append('QUOTE_TIME_OR_VALUE_INVALID:'+symbol); continue
        covered+=1
        currency=(_text(raw.get('turnover_currency')) or _text(raw.get('currency')) or 'UNKNOWN').upper()
        unit=(_text(raw.get('turnover_unit')) or _text(raw.get('unit')) or 'UNKNOWN').upper()
        # Conflicting explicit aliases invalidate the unit contract too.
        aliases_ok=all(not raw.get(a) or not raw.get(b) or str(raw[a]).upper()==str(raw[b]).upper()
                       for a,b in [('turnover_currency','currency'),('turnover_unit','unit')])
        hkd=verified and aliases_ok and currency=='HKD' and unit=='HKD'
        turnover=(amount>TURNOVER_THRESHOLD_HKD) if hkd else 'unknown'
        amount_reason=(f'已核港元成交额{amount/1e8:.4f}亿；严格大于1亿' if turnover is True
                       else '已核港元成交额未超过1亿' if turnover is False
                       else '原始金额已记录；币种、单位或来源未核实')
        # Missing authorities are explicit incomplete implementations, not a
        # permissive parser accepting a self-declared rule/source/boolean.
        volume='unknown'; position='unknown'
        volume_reason='缺少同时间成交量基线及获授权放量规则'
        position_reason='缺少历史价格位置底板及获授权超跌或突破规则'
        condition_row=(condition_audit or {}).get('symbols',{}).get(symbol)
        if condition_row is not None:
            n=condition_row['volume']['valid_sample_count']
            volume_reason=f'同期成交量诊断可比样本{n}个；元数据权威、有效样本门槛及放量规则尚未获准入'
            n=condition_row['price']['valid_sample_count']
            position_reason=f'同期价格诊断可比样本{n}个（非日线高低点）；历史底板及超跌或突破规则仍待核'
        catalyst=candidate_catalyst(symbol,catalyst_events,as_of=as_of) if verified else candidate_catalyst(symbol,[],as_of=as_of)
        new_catalyst=True if catalyst['status']=='CONFIRMED_PIT' else 'unknown'
        refs=[str(snapshot_source.get('artifact_ref') or '')]
        predicates=[_predicate(REQUIRED_PREDICATES[0],turnover,amount_reason,refs),
                    _predicate(REQUIRED_PREDICATES[1],volume,volume_reason,[]),
                    _predicate(REQUIRED_PREDICATES[2],position,position_reason,[]),
                    _predicate(REQUIRED_PREDICATES[3],new_catalyst,'已核新直接催化' if new_catalyst is True else '新直接催化或可用时间待核',
                               [e['artifact_ref'] for e in catalyst.get('evidence',[])])]
        qualified=_and([p['value'] for p in predicates])
        lanes=['CLOSE_DISCOVERY']; sources=[]
        for source in (universe_source,snapshot_source):
            sources.append({**source,'lane':'CLOSE_DISCOVERY'})
        for event in catalyst.get('evidence',[]):
            sources.append({'owner':event['owner'],'role':event['role'],'artifact_ref':event['artifact_ref'],
                            'receipt_ref':event['publication_ref'],'run_id':event['run_id'],'sha256':event['sha256'],
                            'source_date':event['source_date'],'market':MARKET,'lane':'CLOSE_DISCOVERY',
                            'reason':event['reason'],'observed_at':event['published_at'],'available_at':event['available_at']})
        previous=prior.get(symbol)
        first_seen=iso_seconds(observed)
        previous_level=None
        if previous is not None and prior_lineage is not None:
            lanes.append('CONTINUOUS_TRACKING'); sources.append(dict(prior_lineage))
            first_seen=previous['first_seen_at']
            previous_level=(previous.get('research_priority') or {}).get('level')
        prior_events=(previous.get('catalyst') or {}).get('event_ids',[]) if previous else []
        prior_event_ids={x for x in prior_events if isinstance(x,str)} if isinstance(prior_events,list) else set()
        upgrade=previous is not None and new_catalyst is True and bool(set(catalyst['event_ids'])-prior_event_ids)
        level='UPGRADED_WATCH' if upgrade else 'FOLLOW_UP' if previous else 'WATCH'
        reason='新增直接催化，继续核对交易条件' if upgrade else '持续跟踪，交易条件仍待核' if previous else '成交额观察待核；尚非完整条件候选'
        missing=[p['reason'] for p in predicates if p['value']=='unknown']
        if not hkd: missing[0]='成交额币种、单位或原始来源'
        cid='mcd-'+digest(f'{trade_date}|{symbol}'.encode())[:24]
        candidates.append({'candidate_id':cid,'symbol':symbol,'name':_text(raw.get('name')) or symbol,
            'trade_date':trade_date,'source_lanes':lanes,'first_seen_at':first_seen,
            'last_seen_at':iso_seconds(observed),'observed_at':iso_seconds(observed),
            'available_at':snapshot_source.get('available_at') or iso_seconds(as_of),
            'turnover_amount':{'value':amount,'currency':currency,'unit':unit,'as_of':iso_seconds(observed),
                               'status':'OBSERVED' if hkd else 'UNKNOWN_CONTRACT','contract_state':'VERIFIED_HKD' if hkd else 'UNKNOWN_CURRENCY_UNIT_OR_SOURCE'},
            'volume_comparison':{'state':'unknown','ratio':None,'raw_provider_ratio':finite_number(raw.get('volume_ratio')),
                                 'baseline_as_of':None,'baseline_period':None,'rule_version':None,'source_ref':None,'reason':volume_reason},
            'position':{'state':'DAILY_RETURN_OBSERVATION_ONLY','pct_chg':round((price/prev-1)*100,6),
                        'last_price':price,'prev_close':prev,'historical_position_state':'UNKNOWN',
                        'historical_baseline_as_of':None,'historical_rule_version':None,'historical_source_ref':None,'reason':position_reason},
            'catalyst':catalyst,'research_priority':{'level':level,'previous_level':previous_level,'change_reason':reason,
                'formal_rank_changed':False,'buy_gate_changed':False,'rule_version':RULE_VERSION},
            'data_status':'CLOSE_CONDITION_CANDIDATE' if qualified is True else 'TURNOVER_OBSERVATION_PENDING',
            'attention_reason':reason,'predicates':predicates,'qualified':qualified,'sources':sources,
            'risks':[{'risk_type':'FREE_FLOAT_EVIDENCE_GAP','severity':'unknown','explanation':'自由流通分母缺失，不能判断真实自由流通换手风险'}],
            'observation_plan':{'triggers':['补齐放量及历史位置证据后再判断完整条件'],
                'invalidation_conditions':['资格或来源校验失效时撤下观察；不触发BUY'],
                'missing_evidence':missing+['自由流通换手分母']}})
    if condition_audit is not None:
        # Audit arithmetic is never substituted into ratio/state/predicates.
        # Bind every projected diagnostic to its bytes, window and exact quote.
        for candidate in candidates:
            row=condition_audit['symbols'].get(candidate['symbol'])
            if row is None: continue
            common={'contract_version':condition_audit['contract_version'],
                    'audit_sha256':condition_audit['audit_sha256'],
                    'validator_sha256':condition_audit['validator_sha256'],
                    'current_snapshot':condition_audit['current_snapshot'],
                    'window':condition_audit['window'],
                    'rules':condition_audit['rules'],'archive_gaps':condition_audit['archive_gaps']}
            for key,kind in (('volume_comparison','volume'),('position','price')):
                diagnostic={**common,**row[kind]}
                diagnostic['diagnostic_content_sha256']=digest(encoded(diagnostic))
                candidate[key]['evidence_audit']=diagnostic
    # A research display queue only. Never rank incomparable currencies/units
    # against HKD; keep stable code ordering within each evidence class.
    candidates.sort(key=lambda c:(0 if c['predicates'][0]['value'] is True else 1,c['symbol']))
    missing_count=max(0,len(eligible)-covered)
    gaps=list(quote_gaps)+[str(x)[:160] for x in snapshot_errors]
    cannot=list(catalyst_gaps)+['COMPARABLE_VOLUME_AUTHORITY_AND_RULE_MISSING','HISTORICAL_POSITION_AUTHORITY_AND_RULE_MISSING','FREE_FLOAT_DENOMINATOR_MISSING']
    if any(c['predicates'][0]['value']=='unknown' for c in candidates): cannot.append('TURNOVER_CURRENCY_UNIT_OR_SOURCE_UNVERIFIED')
    if not verified: cannot.append('SNAPSHOT_OR_UNIVERSE_EVIDENCE_UNVERIFIED')
    if missing_count: cannot.append('QUOTE_COVERAGE_INCOMPLETE')
    summary=lambda c:{'item_id':'focus-'+c['candidate_id'],'candidate_id':c['candidate_id'],'name':c['name'],
                      'occurred_at':c['observed_at'],'reason':c['attention_reason'],'evidence_status':c['data_status'],'kind':'FOCUS'}
    themes=[{'item_id':'theme-'+digest(x['theme'].encode())[:16],'candidate_id':None,'name':x['theme'],
             'occurred_at':x['occurred_at'],'reason':x['reason'],'evidence_status':'PIT_AGGREGATED','kind':'THEME_CHANGE'}
             for x in theme_summary(catalyst_events)] if verified else []
    run='mcd-'+digest(encoded({'date':trade_date,'rule':RULE_VERSION,'universe':universe_source.get('sha256'),
                              'snapshot':snapshot_source.get('sha256')}))[:24]
    if condition_audit is not None:
        run='mcd-'+digest(encoded({'prior_run_id':run,'condition_audit_sha256':condition_audit['audit_sha256']}))[:24]
    return {'schema_version':SCHEMA_VERSION,'market':MARKET,'trade_date':trade_date,'slot':SLOT,
            'as_of':iso_seconds(as_of),'generated_at':iso_seconds(generated_at),'run_id':run,
            # Complete scan != complete conditions. An empty PARTIAL observation
            # queue must never be presented as a verified zero-candidate scan.
            'status':'PARTIAL' if cannot or gaps else ('READY' if candidates else 'READY_EMPTY'),
            'rule_version':RULE_VERSION,'cache_key':f'{trade_date}|{MARKET}|{SLOT}|{RULE_VERSION}',
            'universe':dict(universe_source),'coverage':{'eligible_count':len(eligible),'covered_count':covered,
                'missing_count':missing_count,'missing_reasons':sorted(set(gaps))},
            'cannot_confirm':sorted(set(cannot)),'priority_summary':{'focus':[summary(x) for x in candidates[:20]],
                'theme_changes':themes,'risk_upgrades':[]},'candidates':candidates,**FOUR_FLAGS}
