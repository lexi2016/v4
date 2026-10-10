"""Explain the exact reviewed scope; no new relation, time or eligibility claims."""
import copy
from v5_shadow.contracts import aware


def describe_scope(daily,market,reviewed):
    cards=reviewed['cards'];index={}
    for card in cards:
        for symbol in card.get('daily_match_symbols',[]):
            index.setdefault(symbol,[]).append(card)
    reasons=['BROADER_US_HK_RELATIONS_NOT_ASSESSED','TARGET_DATE_ELIGIBILITY_CANNOT_CONFIRM']
    source=market.get('source_identity') or {};saved=daily.get('source_identity') or {}
    hashes=('payload_sha256','manifest_sha256','receipt_sha256')
    same_source=(source.get('status')=='VERIFIED' and saved.get('status')=='VERIFIED'
        and all(isinstance(source.get(key),str) and len(source[key])==64 and source[key]==saved.get(key) for key in hashes))
    try:
        timely=(aware(daily.get('research_cutoff'))<=aware(market.get('research_cutoff'))
                and aware(daily.get('generated_at'))<=aware(market.get('research_cutoff')))
    except (ValueError,TypeError,AttributeError):timely=False
    ready=(timely and market.get('status')=='READY' and daily.get('source_status')=='READY'
        and daily.get('us_session_date')==market.get('expected_us_session')
        and same_source
        and daily.get('relation_artifact_sha256')==reviewed.get('artifact_sha256'))
    if not ready:reasons.append('CURRENT_US_SOURCE_OR_REVIEWED_RELATION_IDENTITY_NOT_MATCHED')
    rows=[]
    if ready:
        for raw in market.get('raw_individual_up',[]):
            symbol=raw['symbol'];matches=[copy.deepcopy(m) for m in daily.get('matches',[]) if m.get('us_symbol')==symbol]
            rows.append(dict(us_symbol=symbol,source_row=copy.deepcopy(raw),
                relation_assessment='REVIEWED_REGISTRY_MATCHED' if matches else 'NOT_IN_REVIEWED_REGISTRY_NOT_ASSESSED' if symbol not in index else 'REVIEWED_REGISTRY_NO_MATCH',
                reviewed_relation_count=len(index.get(symbol,[])) if symbol in index else None,
                matched_relation_count=len(matches) if symbol in index else None))
    assessed=sum(row['us_symbol'] in index for row in rows) if ready else None
    return dict(schema_version='v5.us_mapping_scope.v1',status='PARTIAL' if ready else 'CANNOT_CONFIRM',
        scope='PINNED_REVIEWED_RELATIONS_WITHIN_CONFIGURED_US_SAMPLE',
        reviewed_us_symbols=sorted(index),reviewed_us_symbol_count=len(index),
        reviewed_relation_artifact_sha256=reviewed['artifact_sha256'],
        registry_readback=dict(scope='ORIGINAL_REVIEWED_RETROSPECTIVE_RESEARCH_NOT_CURRENT_SELECTION',
            seed_target_date=reviewed.get('target_trade_date'),report=copy.deepcopy(reviewed.get('report')),
            cards=copy.deepcopy(cards),
            non_matching_theme_cards=[copy.deepcopy(card) for card in cards if not card.get('daily_match_symbols')],
            original_source_scope=copy.deepcopy(reviewed.get('source_scope')),
            formal_eligible=False,natural_verified=False),
        us_session_date=market.get('expected_us_session'),daily_run_id=daily.get('run_id'),
        daily_artifact_sha256=daily.get('artifact_sha256'),
        rising_individual_count=len(rows) if ready else None,assessed_rising_symbol_count=assessed,
        unassessed_rising_symbol_count=len(rows)-assessed if ready else None,
        configured_sample_count=copy.deepcopy(daily.get('coverage',{}).get('configured_us_universe_count')) if ready else None,
        full_market_coverage=False,broader_relation_result=None,
        rows=rows if ready else None,reason_codes=reasons,formal_eligible=False,natural_verified=False)
