"""Independent official-event observation, never a price-volume admission rule."""
from __future__ import annotations
from copy import deepcopy
import math
from typing import Mapping, Any
from .workspace_projection import FLAGS, HK, timestamp


def event_lane(review: Mapping[str, Any], screen: Mapping[str, Any], context: Mapping[str, Any]) -> dict:
    target = context['plan_trade_date']; prior = str(context['market_session'])
    cutoff = timestamp(context.get('research_cutoff'))
    rows = {}
    for key in ('cards','strict','near','pending'):
        for row in screen.get(key,[]) or []:
            rows.setdefault(row.get('code'), row)
    observations=[]; pending=[]
    documents=deepcopy(review.get('official_documents',[]) or [])
    for doc in documents:
        doc['body_claims']=[deepcopy(claim) for key in ('positive_observations','risk_alerts','clarifications')
            for claim in review.get(key,[]) if claim.get('document_sha256')==doc.get('document_sha256')
            and doc.get('document_sha256') and claim.get('symbol')==doc['symbol']]
    for doc in documents:
        published=timestamp(doc.get('published_at')); acquired=timestamp(doc.get('retrieved_at'))
        if (published is None or acquired is None or cutoff is None or published > cutoff or acquired > cutoff
                or published > acquired or published.astimezone(HK).strftime('%Y%m%d') != target):
            continue
        base=rows.get(doc['symbol']); known=False; oversold=False
        if base and str(base.get('verified_session')) == prior and str(screen.get('verified_session')) == prior:
            close=base.get('close'); high=base.get('prior60_session_high')
            if (type(close) in (int,float) and type(high) in (int,float) and math.isfinite(close)
                    and math.isfinite(high) and 0 < close and 0 < high
                    and base.get('prior60_session_count') == 60 and isinstance(base.get('oversold_flag'),bool)
                    and screen.get('input_identity')):
                oversold=close <= high*.8
                known=oversold is base['oversold_flag']
        # A known non-oversold name is not labelled oversold. Its announcement
        # remains in the independent full official-documents section.
        if known and not oversold:
            continue
        item=deepcopy(dict(doc))
        item.update(observation_status='PRIOR_OVERSOLD_OFFICIAL_OBSERVATION' if known else 'PRIOR_OVERSOLD_UNVERIFIED',
            prior_session=prior, prior_oversold_evidence=deepcopy(base) if base else None,
            screen_input_identity=screen.get('input_identity'), screen_authority=deepcopy(screen.get('authority')),
            intraday_price_volume=dict(status='UNKNOWN',reason='SEPARATE_INTRADAY_CONFIRMATION_NOT_COMPLETE_DAY_VOLUME'),
            focus_eligible=False, buy_allowed=False, causality='NOT_ESTABLISHED',
            assertion='OFFICIAL_DOCUMENT_OBSERVED_NOT_BULLISH_FACT_OR_BUY_RANK', **FLAGS)
        (observations if known else pending).append(item)
    eastmoney=[];eastmoney_gaps=[]
    east_since=timestamp(context.get('focus_window_start'))
    for raw in review.get('eastmoney_hk_documents',[]) or []:
        if not isinstance(raw,Mapping):
            eastmoney_gaps.append('EASTMONEY_HK_DOCUMENT_SHAPE_INVALID');continue
        doc=deepcopy(dict(raw));available=timestamp(doc.get('available_at'))
        displayed=timestamp(doc.get('display_time_iso'))
        if (doc.get('schema_version')!='v4.manager_research.eastmoney_hk_document.v2'
                or doc.get('target_trade_date')!=target or doc.get('source')!='EASTMONEY_HK'
                or doc.get('market_code')!='116' or doc.get('symbol')!='HK.'+str(doc.get('stock_code',''))
                or doc.get('hkex_first_publication_verified') is not False
                or doc.get('fresh_catalyst_eligible') is not False or doc.get('focus_eligible') is not False
                or doc.get('buy_allowed') is not False or displayed is None or available is None):
            eastmoney_gaps.append('EASTMONEY_HK_DOCUMENT_IDENTITY_OR_TIME_INVALID');continue
        if cutoff is None or displayed>cutoff or available>cutoff or east_since is None or displayed<=east_since:
            eastmoney_gaps.append('EASTMONEY_HK_DOCUMENT_OUTSIDE_CONSUMER_CUTOFF');continue
        eastmoney.append(doc)
    return dict(schema_version='v4.manager_research.announcement_observation.v1',
        target_trade_date=target, research_cutoff=context.get('research_cutoff'), prior_session=prior,
        status=review.get('status','NOT_RUN'), latest_attempt=deepcopy(review.get('attempt')),
        count_known=bool(review.get('product_identity',{}).get('consumed',False)) if isinstance(review.get('product_identity'),dict) else False,
        observations=observations, pending_observations=pending,
        official_documents=documents,
        eastmoney_hk_status=review.get('eastmoney_hk_status','NOT_RUN'),
        eastmoney_hk_documents=eastmoney,
        eastmoney_hk_capture=deepcopy(review.get('eastmoney_hk_capture')),
        eastmoney_hk_attempt=deepcopy(review.get('eastmoney_hk_attempt')),
        eastmoney_hk_gaps=sorted(set([*(review.get('eastmoney_hk_gaps',[]) or []),*eastmoney_gaps])),
        coverage=deepcopy(review.get('coverage',{})),gaps=deepcopy(review.get('gaps',[])),
        capture_runs=deepcopy(review.get('capture_runs',[])),independent_of_strict_near_focus=True, **FLAGS)
