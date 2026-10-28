"""Read-only discovery from the original full HK universe and attested news.

Unlike reader_source.py this accepts no preselected stock list. Membership is
read from the actual existing authority; only explicit HK code mentions map.
No quote snapshot, Stage selection, crawler or second producer is required.
"""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Any, Mapping, Sequence
from .workspace_projection import FLAGS, canonical_symbol, canonical_url, date_token, digest, timestamp
from .workspace_read_control import checkpoint, phase


def project_discovery(events: Sequence[Mapping[str,Any]], codes: Sequence[str], membership: Mapping[str,Any], date: str) -> list[dict]:
    """Projection only. The caller must use read_discovery for real admission."""
    date=date_token(date)
    if membership.get('source_date')!=date:
        raise ValueError('DISCOVERY_UNIVERSE_TARGET_MISMATCH')
    allowed=set(codes); cards=[]
    for event in events:
        if event.get('mapping_basis')!='EXPLICIT_HK_CODE':
            continue
        for symbol in event.get('mapped_symbols',[]):
            if canonical_symbol(symbol)!=symbol or symbol not in allowed:
                continue
            if not canonical_url(event.get('source_url')) or not timestamp(event.get('published_at')) or not timestamp(event.get('source_available_at')):
                continue
            # Witnessing the membership chain NOW cannot prove that this whole
            # discovery was running on the historical target date.
            stable_member={k:v for k,v in membership.items() if k!='available_at'}
            source=dict(source_id=event['source_ref'],url=event['source_url'],sha256=event['source_sha256'],
                        retrieved_at=event.get('first_seen_at'),representation='ATTESTED_HOURLY_ARTIFACT',
                        retrieval_method=event['source_owner'],verification_reference=event.get('publication_ref'))
            cards.append(dict(card_id=digest([date,symbol,event['event_id'],membership.get('sha256')]),
                event_id=event['event_id'],market='HK_CONNECT',symbol=symbol,name=symbol,title=event['title'],
                connect_eligibility='VERIFIED_TARGET_UNIVERSE',membership_source=stable_member,
                identity_mapping_basis='EXPLICIT_HK_CODE',themes=list(event.get('themes',[])),
                published_at=event['published_at'],published_date=timestamp(event['published_at']).date().isoformat(),
                time_precision='UNSPECIFIED_BY_ORIGINAL_EVENT_CONTRACT',retrieved_at=event.get('first_seen_at'),available_at=event['source_available_at'],
                source_url=event['source_url'],source_refs=[source],evidence_quote=event['title'],
                relationship_type='EXPLICIT_MENTION',relation_quote=None,
                mapping_reason='原归档以明确港股代码提及本股：'+event['title']+'；目标日资格由全市场authority核验，不来自Stage固定池。',
                temporal_classification='POST_HOC_RESEARCH',captured_at_target=False,
                projection_scope='EXISTING_ARCHIVE_CODE_MENTION_REVIEW_NOT_HISTORICAL_CAPTURE',
                volume_condition='UNKNOWN',price_position='UNKNOWN',qualified=False,research_role='CATALYST_OBSERVATION_ONLY',**FLAGS))
    return cards


def read_discovery(date: str, *, catalyst: Mapping[str,Any], universe_root: Path | None,
                   data_root: Path | None, owner_root: Path | None) -> dict:
    date=date_token(date)
    result=dict(cards=[],gaps=[],coverage=dict(universe_code_count=None,attested_news_artifact_count=0,
                mapped_stock_count=0),membership_witness=None)
    if universe_root is None:
        result['gaps']=['DISCOVERY_NATIVE_HK_UNIVERSE_ROOT_NOT_BOUND']; return result
    if data_root is None or owner_root is None:
        result['gaps']=['DISCOVERY_ORIGINAL_NEWS_ROOT_OR_OWNER_NOT_BOUND']; return result
    if catalyst.get('status') not in {'READY','EMPTY'} or catalyst.get('target_trade_date')!=date:
        result['gaps']=['DISCOVERY_REQUIRES_CURRENT_VERIFIED_CATALYST_INPUT_INVENTORY']; return result
    try:
        from domains.manager_research_evidence import read_universe_evidence
        from domains.manager_catalyst_tracking import read_catalyst_events
        from infrastructure.manager_input_attestation import resolve, digest as raw_digest
        from .catalyst_observations import _hourly_cards
        universe=read_universe_evidence(Path(universe_root),date)
        bindings=[b for b in catalyst.get('input_bindings',[]) if b.get('kind')=='HOURLY_NEWS']
        # Original replay checks both positive and missing publication SHA. A
        # new sidecar cannot silently change the old input inventory on GET.
        _hourly_cards(data_root,owner_root,date,datetime.now(timezone.utc),bindings=bindings)
        paths=[resolve(Path(data_root),b['artifact_ref']) for b in bindings if b.get('publication_sha256')]
        result['coverage'].update(universe_code_count=len(universe.codes),attested_news_artifact_count=len(paths))
        if not paths:
            result['gaps']=['DISCOVERY_NO_ATTESTED_NEWS_PUBLICATION_IN_INVENTORY']; return result
        events,gaps=read_catalyst_events(paths,as_of=datetime.now(timezone.utc),
            universe_names={code:code for code in universe.codes},reference_root=Path(data_root),
            owner_root=Path(owner_root),include_extended_themes=True)
        # Avoid attaching post-replacement events to a previously verified SHA.
        for b in bindings:
            if not b.get('publication_sha256'):continue
            p=resolve(Path(data_root),b['artifact_ref'])
            if raw_digest(p.read_bytes())!=b['artifact_sha256'] or raw_digest(Path(str(p)+'.publication.json').read_bytes())!=b['publication_sha256']:
                raise ValueError('DISCOVERY_NEWS_CHANGED_DURING_READ')
        values=[{**event.to_dict(),'source_url':event.source_url} for event in events]
        result['cards']=project_discovery(values,universe.codes,universe.source,date)
        result['gaps']=gaps
        result['membership_witness']=dict(universe.source)
        result['coverage']['mapped_stock_count']=len({c['symbol'] for c in result['cards']})
        return result
    except (ImportError,OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
        result['gaps']=['DISCOVERY_ORIGINAL_AUTHORITY_OR_NEWS_READ_FAILED:'+type(exc).__name__]
        return result


def _issuer_alias(name: str) -> str:
    # Only documented exchange name suffixes; no fuzzy/reverse A-to-H mapping.
    import re
    return re.sub(r'-(?:SW|SS|W|B|P|R)$','',name.strip(),flags=re.I)


def _mentions(text: str, alias: str) -> bool:
    return bool(_mention_spans(text,alias))


def _mention_spans(text: str, alias: str) -> list[tuple[int,int]]:
    """Return every source interval matching one native issuer alias."""
    if len(alias)<2:
        return []
    if len(alias)==2 and re.fullmatch(r'[\u3400-\u9fff]{2}',alias):
        pattern=r'(?<![\u3400-\u9fff])'+re.escape(alias)+r'(?![\u3400-\u9fff])'
        return [match.span() for match in re.finditer(pattern,text)]
    if re.fullmatch(r'[\x00-\x7f]+',alias):
        pattern=r'(?<![A-Za-z0-9])'+re.escape(alias)+r'(?![A-Za-z0-9])'
        return [match.span() for match in re.finditer(pattern,text,re.I)]
    spans=[];start=0
    while True:
        found=text.find(alias,start)
        if found<0:
            return spans
        spans.append((found,found+len(alias)))
        start=found+1


def _select_alias_matches(text: str, aliases: Mapping[str,set[str]]) -> list[tuple[int,int,str,str]]:
    """Choose non-overlapping native aliases without hiding separate mentions.

    A longer alias may contain a shorter native alias (for example ``周大福``
    inside ``周大福创建``). That one source interval is assigned to the
    longest alias. Overlapping intervals that are not a containment pair are
    ambiguous and are rejected together. Separate source intervals remain
    eligible, so a sentence can still mention both issuers explicitly.
    """
    candidates=[]
    for alias,codes in aliases.items():
        if len(codes)!=1:
            continue
        code=next(iter(codes))
        candidates.extend((start,end,alias,code) for start,end in _mention_spans(text,alias))
    if not candidates:
        return []
    candidates.sort(key=lambda row:(row[0],row[1],row[2],row[3]))
    groups=[]
    for candidate in candidates:
        overlaps=[]
        for index,group in enumerate(groups):
            if any(candidate[0]<other[1] and other[0]<candidate[1] for other in group):
                overlaps.append(index)
        if not overlaps:
            groups.append([candidate])
            continue
        merged=[candidate]
        for index in reversed(overlaps):
            merged.extend(groups.pop(index))
        groups.append(merged)
    selected=[]
    for group in groups:
        longest=max(end-start for start,end,_,_ in group)
        winners=[row for row in group if row[1]-row[0]==longest]
        if len(winners)!=1:
            continue
        winner=winners[0]
        if all(winner[0]<=row[0] and row[1]<=winner[1] for row in group):
            selected.append(winner)
    return sorted(selected,key=lambda row:(row[0],row[1],row[2],row[3]))


def _discovery_alias_probes(aliases: Mapping[str,set[str]]) -> list[tuple[str,set[str],Any]]:
    """Prepare only necessary literal tests; preserve _mention_spans as arbiter."""
    return [(alias,codes,re.compile(re.escape(alias),re.I) if alias.isascii() else None)
            for alias,codes in aliases.items() if len(alias)>=2 and len(codes)==1]


def _possible_discovery_aliases(text: str, probes: Sequence[tuple[str,set[str],Any]]) -> dict[str,set[str]]:
    # Discovery uses case-sensitive literal CJK/mixed names, but re.I for
    # ASCII aliases. A bare re.I probe preserves Unicode case variants too.
    return {alias:codes for alias,codes,pattern in probes
            if (pattern.search(text) if pattern is not None else alias in text)}


def _subject_name_patterns(names: Mapping[str,str]) -> list[tuple[str,str,re.Pattern[str]]]:
    """Request-local necessary-match tests, NOT an issuer/grammar decision.

    The existing semantic scanner requires alias_of(name) literally, with
    re.I. Omit its boundary checks here: splitting a body into units/clauses
    may CREATE a boundary. Keep every duplicate and contained alias so the
    original scanner can still reject ambiguity and assign subject roles.
    No source verdict, prose or result is kept across projection calls.
    """
    from .workspace_semantics import alias_of
    patterns=[]
    for code,name in names.items():
        alias=alias_of(name)
        if len(alias)>=2:
            patterns.append((code,name,re.compile(re.escape(alias),re.I)))
    return patterns


def _body_subject_names(body: str, patterns: Sequence[tuple[str,str,re.Pattern[str]]]) -> dict[str,str]:
    # Do not use discovery's casefold/unique-alias winners here. The semantic
    # scanner has its own re.I, duplicate, overlap and clause-boundary rules.
    return {code:name for code,name,pattern in patterns if pattern.search(body)}


def project_material_discovery(materials: Sequence[Mapping[str,Any]], master: Mapping[str,Mapping[str,Any]],
                               identity: Mapping[str,Any], context: Mapping[str,Any], *,
                               rejection_audit: list[dict] | None = None) -> list[dict]:
    """Pure projection after the ORIGINAL exact-date native identity reader.

    A broker-extracted A-share stock_code is retained as provenance, NEVER
    converted to HK. We match a unique native HK issuer name against the actual
    article title/evidence sentence and retain that specific sentence. Broad
    themes alone do not create issuers. No fixed list is accepted by the API.
    """
    import re
    from .workspace_plan import temporal_role
    from copy import deepcopy
    if (identity.get('status')!='OWNER_VERIFIED' or identity.get('source_date')!=context.get('market_session')
            or not re.fullmatch(r'[0-9a-f]{64}',str(identity.get('artifact_sha256','')))):
        raise ValueError('MATERIAL_DISCOVERY_NATIVE_IDENTITY_NOT_VERIFIED')
    aliases: dict[str,set[str]]={}
    for code,row in master.items():
        if canonical_symbol(code)!=code or not isinstance(row,Mapping):
            continue
        name=str(row.get('name') or '').strip()
        for alias in {name,_issuer_alias(name)}:
            if len(alias)>=2 and alias!=code:
                aliases.setdefault(alias.casefold(),set()).add(code)
    from .workspace_semantics import prose_sources, assess, SEMANTIC_VERSION, _spans
    from .announcement_materials import is_mirror, mirror_binding_valid, CARD_FIELDS
    cards=[]
    audit = rejection_audit if rejection_audit is not None else []
    names = {code: str(row.get('name') or '') for code,row in master.items()}
    subject_patterns = None
    alias_probes = _discovery_alias_probes(aliases)
    for material in materials:
        checkpoint()
        if material.get('verification')!='OWNER_VERIFIED' or not material.get('source_refs'):
            continue
        role=temporal_role(material,context)
        if role in {'AFTER_CUTOFF_EXCLUDED','TIME_CONTEXT_UNVERIFIED','SOURCE_TIME_OR_BODY_UNVERIFIED'}:
            if is_mirror(material):
                audit.append(dict(symbol=material.get('document_issuer_symbol'),art_code=material.get('art_code'),
                    body_sha256=material.get('body_sha256'),reason=role,source_refs=deepcopy(material.get('source_refs',[]))))
            continue
        row=material.get('source_row') if isinstance(material.get('source_row'),Mapping) else {}
        # Not the pooled stock name; use the original prose about the issuer.
        title=str(material.get('title') or '')
        sources=prose_sources(material)
        body='\n'.join(text for _,text in sources)
        # Title is a discovery locator only; assess requires actual body prose.
        text=title+'\n'+body
        matched={}
        folded=text.casefold()
        possible_aliases=_possible_discovery_aliases(folded,alias_probes)
        for _,_,alias,code in _select_alias_matches(folded,possible_aliases):
            matched.setdefault(code,alias)
        if is_mirror(material):
            issuer=material.get('document_issuer_symbol')
            if not mirror_binding_valid(material) or issuer not in master:
                audit.append(dict(symbol=issuer,art_code=material.get('art_code'),reason='ANNOUNCEMENT_ISSUER_NOT_IN_NATIVE_MASTER'))
                continue
            # A filing belongs to its owner-bound issuer, not every named customer/peer.
            matched={issuer:_issuer_alias(str(master[issuer]['name']))}
        if not matched:
            continue
        if subject_patterns is None:
            subject_patterns = _subject_name_patterns(names)
        # assess scans only substrings of these original prose bodies and
        # reinserts its target issuer even when the name occurs only in title.
        # A no-boundary literal hit is a superset of every possible clause hit.
        body_names = _body_subject_names(body,subject_patterns)
        subject_scope = None
        for code,alias in sorted(matched.items()):
            name=str(master[code]['name'])
            assessed=assess(material,name,code,names=body_names,identity_row=master[code])
            if is_mirror(material):
                for rejected in assessed['rejected']:
                    rejected.update(art_code=material['art_code'],body_sha256=material['body_sha256'],
                        capture_trade_date=material['capture_trade_date'],
                        time_basis=material['time_basis'],mirror_observed_at=material['mirror_observed_at'],
                        available_at=material['available_at'],retrieved_at=material['retrieved_at'])
            audit.extend(assessed['rejected'])
            if not assessed['propositions']:
                continue
            if subject_scope is None:
                # Keep the original full-catalogue scope and separate per-card
                # dicts; only eliminate identical repeated body scans.
                subject_scope = {s:names[s] for _,_,s in _spans(body,names)}
            quote='。'.join(p['quote'] for p in assessed['propositions'])
            material_id=str(material.get('material_id') or digest(material))
            cards.append(dict(card_id=digest(['MATERIAL',context['plan_trade_date'],code,material_id]),
                event_id='material:'+str(material.get('original_article_id') or material_id),
                material_id=material_id,market='HK',symbol=code,name=name,title=title,
                themes=sorted({p['theme'] for p in assessed['propositions'] if p.get('theme')}),source_url=material.get('source_url'),
                semantic_version=SEMANTIC_VERSION,semantic_status='ACCEPTED',propositions=assessed['propositions'],
                subject_role=assessed['propositions'][0]['subject_role'],
                subject_scope=dict(subject_scope),
                identity_pair_basis={k:master[code][k] for k in ('a_share_code',) if k in master[code]},
                source_refs=deepcopy(material['source_refs']),claim_type=material.get('claim_type','RESEARCH_OPINION'),
                published_at=material.get('published_at'),published_date=material.get('published_date'),
                retrieved_at=material.get('retrieved_at'),available_at=material.get('available_at'),
                collected_at=material.get('collected_at'),first_seen_at=material.get('first_seen_at'),
                archive_recorded_at=material.get('archive_recorded_at'),archive_date=material.get('archive_date'),
                original_source_row=deepcopy(dict(row)),relation_quote=quote,evidence_quote=quote,
                relationship_type='NATIVE_HK_ISSUER_EXPLICIT_MENTION',identity_mapping_basis='UNIQUE_NATIVE_HK_NAME_IN_SOURCE_TEXT',
                identity_source=deepcopy(dict(identity)),connect_eligibility='TARGET_DATE_NOT_CHECKED',
                mapping_reason=f'原研究材料直接提及{name}：{quote}。仅研究观点/待核事实，不把原A股标签转换成港股或推定港股通资格。',
                temporal_role=role,temporal_classification='PREOPEN_PLAN_RESEARCH_NOT_HISTORICAL_CAPTURE',
                captured_at_target=False,qualified=False,volume_condition='UNKNOWN',price_position='UNKNOWN',
                research_role='MATERIAL_RESEARCH_OBSERVATION_ONLY',**FLAGS))
            if is_mirror(material):
                cards[-1].update({k:deepcopy(material[k]) for k in CARD_FIELDS})
                cards[-1]['mapping_reason']=f'镜像公告原文中的本公司事件：{quote}；镜像可见时间不是HKEX首次发布时间，仅研究候选。'
    from .issuer_us_relations import extract_issuer_business_relations
    for card in cards:
        card['issuer_business_relations']=extract_issuer_business_relations(card)
    return cards


def read_material_discovery(materials: Sequence[Mapping[str,Any]], context: Mapping[str,Any],
                            security_master_root: Path | None, *, projection_memo: Any = None) -> dict:
    """Read existing reference-day native master, not a future manual whitelist."""
    result=dict(cards=[],rejected_relations=[],gaps=[],coverage=dict(material_record_count=len(materials),identity_row_count=None,
        mapped_stock_count=0),identity_witness=None,status='CANNOT_CONFIRM')
    if security_master_root is None:
        result['gaps']=['MATERIAL_DISCOVERY_NATIVE_SECURITY_MASTER_ROOT_NOT_BOUND'];return result
    try:
        from upstreams.v3_shared_data.shared_data.store import StoreError as NativeStoreError
    except ImportError:
        result['gaps']=['MATERIAL_DISCOVERY_NATIVE_IDENTITY_DEPENDENCY_MISSING']; return result
    try:
        from upstreams.v3_shared_data.shared_data.hk_security_master import load_verified_hk_security_master
        from upstreams.v3_shared_data.shared_data.hashing import sha256_json
        from .workspace_projection import timestamp
        root=Path(security_master_root).expanduser()
        if not root.is_absolute() or '..' in root.parts:
            raise ValueError('native security master root must be explicit absolute')
        day=str(context['market_session'])
        with phase('native_security_master_validation'):
            master,manifest=load_verified_hk_security_master(root,day)
        cutoff=timestamp(context['research_cutoff'])
        for code,row in master.items():
            captured=timestamp(row.get('captured_at'))
            if captured is None or cutoff is None or captured>cutoff:
                raise ValueError('native identity acquisition time missing or after cutoff')
            # load_verified supplies a date-indexed manifest; name and HK code
            # remain mandatory even if an older native validator was permissive.
            if canonical_symbol(code)!=code or not str(row.get('name') or '').strip():
                raise ValueError('native HK identity row invalid')
        witness=dict(status='OWNER_VERIFIED',source_date=day,
            owner='upstreams.v3_shared_data.shared_data.hk_security_master.load_verified_hk_security_master',
            artifact_sha256=manifest['artifact_sha256'],manifest_sha256=sha256_json(manifest),
            artifact_relative=manifest.get('artifact_relative'),run_id=manifest.get('run_id'),
            role='REFERENCE_SESSION_IDENTITY_NOT_TARGET_CONNECT_MEMBERSHIP')
        def project_verified() -> dict:
            rejected: list[dict] = []
            cards = project_material_discovery(materials, master, witness, context, rejection_audit=rejected)
            return dict(cards=cards, rejected_relations=rejected)
        # The original owner has just validated the master and the caller has
        # just validated all materials. Full input content, not a claimed SHA
        # alone, keys this bounded pure-calculation cache. Rejections are kept.
        with phase('pure_material_discovery'):
            projected = (projection_memo.compute('material_discovery',
                [materials, master, witness, context], project_verified)
                if projection_memo is not None else project_verified())
        result.update(projected)
        result['identity_witness']=witness
        result['coverage'].update(identity_row_count=len(master),mapped_stock_count=len({c['symbol'] for c in result['cards']}))
        result['status']='READY' if result['cards'] else 'READY_EMPTY'
        # Membership may be obtained only from the separate target authority.
        result['gaps']=['TARGET_DATE_HK_CONNECT_ELIGIBILITY_NOT_CHECKED'] if result['cards'] else []
    except (ImportError,OSError,ValueError,TypeError,KeyError,RuntimeError,NativeStoreError) as exc:
        result['gaps']=['MATERIAL_DISCOVERY_NATIVE_IDENTITY_READ_FAILED:'+str(context.get('market_session'))+':'+type(exc).__name__]
    return result
