"""Read-only adapter for original-owner-validated mirror announcement bodies.

No source fetch/store, timestamp synthesis, issuer map, or official-publication
attestation. Call mirror_material only AFTER the existing owner reopens and
validates its stored responses. Rechecking these bindings is not that I/O proof.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime
import hashlib
import re
from typing import Any, Mapping, Sequence
from .workspace_projection import FLAGS, canonical_symbol, digest, timestamp

SOURCE_KIND = 'EASTMONEY_HK_ANNOUNCEMENT_BODY'
SOURCE_IDENTITY = 'EASTMONEY_HK_MIRROR_NOT_HKEX_OFFICIAL'
CURRENT_ROLE = 'CURRENT_WINDOW_MIRROR_OBSERVATION'
TIME_BASIS = 'MIRROR_DISPLAY_TIME_NOT_HKEX_FIRST_PUBLICATION'
_SHA = re.compile(r'[0-9a-f]{64}')


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def is_mirror(value: Mapping[str, Any]) -> bool:
    return value.get('source_kind') == SOURCE_KIND


def _document_error(doc: Mapping[str, Any]) -> str | None:
    symbol=doc.get('symbol')
    if (doc.get('schema_version')!='v4.manager_research.eastmoney_hk_document.v2'
            or not isinstance(symbol,str) or canonical_symbol(symbol)!=symbol or doc.get('source')!='EASTMONEY_HK'
            or doc.get('source_identity')!=SOURCE_IDENTITY or doc.get('market_code')!='116'
            or doc.get('stock_code')!=symbol[3:] or doc.get('ann_type')!='H'
            or not str(doc.get('name') or '').strip() or not re.fullmatch(r'AN\d{18}',str(doc.get('art_code','')))):
        return 'ANNOUNCEMENT_MATERIAL_IDENTITY_INVALID'
    if (doc.get('published_at') not in (None,'') or doc.get('hkex_first_publication_verified') is not False
            or doc.get('publication_status')!='CANNOT_CONFIRM_FIRST_PUBLICATION'):
        return 'ANNOUNCEMENT_MATERIAL_PUBLICATION_UPGRADE_REJECTED'
    if (any(doc.get(k) is not v for k,v in FLAGS.items()) or doc.get('buy_allowed') is not False
            or doc.get('fresh_catalyst_eligible') is not False):
        return 'ANNOUNCEMENT_MATERIAL_SAFETY_INVALID'
    body=doc.get('body_text')
    if not isinstance(body,str) or not body.strip():return 'ANNOUNCEMENT_MATERIAL_BODY_MISSING'
    if (doc.get('body_status')!='FULL_CONTENT_API_TEXT_VERIFIED'
            or doc.get('body_source')!='EASTMONEY_CONTENT_API_PAGES'
            or _hash(body)!=doc.get('body_sha256') or not _SHA.fullmatch(str(doc.get('document_sha256','')))):
        return 'ANNOUNCEMENT_MATERIAL_BODY_SHA_OR_CONTRACT_INVALID'
    pages=doc.get('body_pages')
    if (not isinstance(pages,list) or not pages or len(pages)!=doc.get('content_page_count')
            or any(not isinstance(p,Mapping) or p.get('page_index')!=i+1 or not isinstance(p.get('text'),str)
                   or _hash(p['text'])!=p.get('text_sha256') for i,p in enumerate(pages))
            or '\n\n'.join(p['text'] for p in pages)!=body):
        return 'ANNOUNCEMENT_MATERIAL_BODY_PAGES_INVALID'
    refs=doc.get('source_refs')
    if (not isinstance(refs,list) or len(refs)!=len(pages)+2 or any(not isinstance(r,Mapping)
            or not _SHA.fullmatch(str(r.get('blob_sha256',''))) or not _SHA.fullmatch(str(r.get('body_sha256','')))
            or timestamp(r.get('retrieved_at')) is None or not isinstance(r.get('request'),Mapping)
            or r['request'].get('source')!='EASTMONEY_HK' or r['request'].get('method')!='GET'
            or r.get('http_status')!=200 or not r.get('source_key') for r in refs)
            or any(p.get('source_ref')!=refs[i+1] for i,p in enumerate(pages))):
        return 'ANNOUNCEMENT_MATERIAL_SOURCE_REFS_INVALID'
    available=timestamp(doc.get('available_at'));retrieved=timestamp(doc.get('retrieved_at'))
    displayed=timestamp(doc.get('display_time_iso'))
    if (available is None or retrieved is None or displayed is None
            or displayed>available or retrieved!=available
            or available!=max(timestamp(r['retrieved_at']) for r in refs)):
        return 'ANNOUNCEMENT_MATERIAL_CLOCK_INVALID'
    return None


def mirror_material(doc: Mapping[str, Any], capture: Mapping[str, Any]) -> dict:
    """Adapt bytes already checked by workspace_announcements' ORIGINAL reader."""
    if (not isinstance(capture,Mapping) or capture.get('source')!='EASTMONEY_HK'
            or capture.get('readback_status')!='VERIFIED'
            or not _SHA.fullmatch(str(capture.get('sha256','')))
            or not re.fullmatch(r'[0-9a-f]{32}',str(capture.get('run_id','')))):
        raise ValueError('ANNOUNCEMENT_MATERIAL_OWNER_READBACK_UNVERIFIED')
    error=_document_error(doc)
    if error:raise ValueError(error)
    capture_date=str(doc.get('capture_trade_date') or capture.get('target_trade_date') or '')
    if not re.fullmatch(r'20\d{6}',capture_date):
        raise ValueError('ANNOUNCEMENT_MATERIAL_CAPTURE_IDENTITY_INVALID')
    # payload_sha256 denotes the existing MaterialStore HTTP ENVELOPE blob,
    # not a new payload, not the PDF hash, and not an invented source receipt.
    refs=[dict(status='VERIFIED',payload_sha256=r['blob_sha256'],
        representation='MATERIALSTORE_HTTP_RESPONSE_ENVELOPE',
        verification_owner='workspace_announcements._check_eastmoney_sources',
        source_id=r['source_key'],source_url=r['request']['url'],
        retrieved_at=r['retrieved_at'],response_body_sha256=r['body_sha256'],
        raw_source_ref=deepcopy(dict(r))) for r in doc['source_refs']]
    return dict(material_id=digest(['ANNOUNCEMENT_BODY',doc['symbol'],doc['art_code'],doc['body_sha256']]),
        original_article_id=doc['event_id'],title=doc['title'],source_kind=SOURCE_KIND,
        source='EASTMONEY_HK',source_identity=SOURCE_IDENTITY,source_market='HK',
        source_url=doc['source_url'],source_refs=refs,verification='OWNER_VERIFIED',
        source_row={'body_text':doc['body_text']},claim_type='SOURCE_STATEMENT',
        issuer_code=doc['symbol'],document_issuer_symbol=doc['symbol'],
        body_sha256=doc['body_sha256'],document_sha256=doc['document_sha256'],
        art_code=doc['art_code'],owner_document=deepcopy(dict(doc)),
        owner_capture=deepcopy(dict(capture)),capture_trade_date=capture_date,
        published_at=None,published_date=None,mirror_observed_at=doc['display_time_iso'],
        display_time_iso=doc['display_time_iso'],time_basis=TIME_BASIS,
        available_at=doc['available_at'],retrieved_at=doc['retrieved_at'],
        publication_status='CANNOT_CONFIRM_FIRST_PUBLICATION',hkex_first_publication_verified=False,
        fresh_catalyst_eligible=False,buy_allowed=False,**FLAGS)


def mirror_binding_valid(value: Mapping[str, Any]) -> bool:
    if not is_mirror(value):return False
    doc=value.get('owner_document');capture=value.get('owner_capture')
    if not isinstance(doc,Mapping) or _document_error(doc):return False
    try:expected=mirror_material(doc,capture)
    except (TypeError,ValueError,KeyError):return False
    # original_source_row is the existing card projection of source_row.
    row=value.get('source_row') or value.get('original_source_row') or {}
    if row.get('body_text')!=doc['body_text']:return False
    keys=('source','source_identity','source_kind','source_refs','issuer_code','document_issuer_symbol',
          'body_sha256','document_sha256','art_code','published_at','published_date','mirror_observed_at',
          'display_time_iso','time_basis','available_at','retrieved_at','publication_status',
          'hkex_first_publication_verified','fresh_catalyst_eligible','buy_allowed')
    return all(value.get(k)==expected.get(k) for k in keys) and all(value.get(k) is v for k,v in FLAGS.items())


def mirror_role(value: Mapping[str, Any], start: datetime | None, cutoff: datetime | None) -> str:
    if cutoff is None:return 'TIME_CONTEXT_UNVERIFIED'
    if not mirror_binding_valid(value):return 'SOURCE_TIME_OR_BODY_UNVERIFIED'
    seen=timestamp(value['mirror_observed_at']);available=timestamp(value['available_at'])
    if seen>cutoff or available>cutoff:return 'AFTER_CUTOFF_EXCLUDED'
    return CURRENT_ROLE if start is not None and start<seen<=cutoff else 'BACKGROUND'


def current_company_claim(value: Mapping[str, Any], start: datetime | None, cutoff: datetime | None) -> bool:
    if is_mirror(value):return mirror_role(value,start,cutoff)==CURRENT_ROLE
    if start is None or cutoff is None:return False
    pub=timestamp(value.get('published_at'));available=timestamp(value.get('available_at'));retrieved=timestamp(value.get('retrieved_at'))
    if pub is None or available is None or retrieved is None or not start<=pub<=retrieved<=available<=cutoff:
        return False
    from .evidence_identity import acquisition_is_within_window
    return acquisition_is_within_window(value,start,cutoff)


def substantive_propositions(value: Mapping[str, Any], propositions: Sequence[Mapping[str,Any]]) -> tuple[list[dict],list[dict]]:
    """Selection filter AFTER, not instead of, the existing subject classifier."""
    if not is_mirror(value):return list(propositions),[]
    kept=[];rejected=[];binding_valid=mirror_binding_valid(value)
    for p in propositions:
        kind=p.get('event_type');action=str(p.get('action_quote') or '')
        reason=None
        if not binding_valid:reason='ANNOUNCEMENT_MATERIAL_BINDING_INVALID'
        elif p.get('symbol')!=value.get('document_issuer_symbol'):reason='ANNOUNCEMENT_NOT_BOUND_ISSUER'
        elif p.get('claim_status')!='SOURCE_STATEMENT' or p.get('polarity')!='AFFIRMED':reason='ANNOUNCEMENT_NOT_AFFIRMED_SOURCE_EVENT'
        elif re.search(r'回购|回購|購回|购回|repurchas|buyback',action,re.I):reason='ROUTINE_CAPITAL_ACTION_NOT_SUBSTANTIVE_CATALYST'
        elif kind in {'ISSUER_RESEARCH','VALUATION_OPINION','OWNERSHIP_CHANGE'}:reason='NO_SUBSTANTIVE_COMPANY_EVENT'
        elif not re.search(r'已|完成|新增|取得|获得|獲得|获批|獲批|批准|签署|簽署|达成|達成|增长|增長|下降|增加|减少|減少|\d|announced|completed|signed|approved',action,re.I):
            reason='NO_CONFIRMED_EVENT_ACTION'
        if reason:rejected.append({**deepcopy(dict(p)),'reason':reason,'art_code':value.get('art_code'),
            'body_sha256':value.get('body_sha256'),'source_refs':deepcopy(value.get('source_refs',[]))})
        else:kept.append(dict(p))
    return kept,rejected


CARD_FIELDS=('source','source_identity','source_kind','issuer_code','document_issuer_symbol','body_sha256',
             'document_sha256','art_code','owner_document','owner_capture','capture_trade_date',
             'mirror_observed_at','display_time_iso','time_basis','publication_status',
             'hkex_first_publication_verified','fresh_catalyst_eligible','buy_allowed')
