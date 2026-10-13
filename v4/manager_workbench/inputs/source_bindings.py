"""Resolve existing owners into per-job immutable references, never produce data.

Every date/session is supplied by the market calendar. A pointer is an index,
not permission to substitute another date. Projections retain their raw sources.
"""
from __future__ import annotations
import json
from pathlib import Path
from infrastructure.owned_io import SafeRoot
from .validation import raw_sha, before, owner_digest

OWNER = 'v35_dispatcher.research_panel_daily_hk'
US_SYMBOLS = ('AMD','ARKX','AVGO','BOTZ','CIEN','CLOU','COHR','COPX','DLR','DRIV','EQIX','FCG','GLD','GRID','ICLN','ITA','KBE','LIT','LITE','MU','NLR','NVDA','REMX','SOXX','STX','TAN','UFO','VRT','WDC','XBI','XLE','XLP','XLY')


def read(root, relative, expected=None):
    raw = SafeRoot(root).read_bytes(relative)
    sha = raw_sha(raw)
    if expected is not None and sha != expected:
        raise ValueError('OWNER_SHA_MISMATCH')
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError('OWNER_OBJECT_REQUIRED')
    return value, sha


def files(root, pattern):
    if root is None: return []
    root = Path(root)
    return sorted(p.relative_to(root).as_posix() for p in root.glob(pattern) if not p.is_symlink())


def checked_time(value, cutoff):
    if not before(value, cutoff): raise ValueError('OWNER_AFTER_CUTOFF_OR_UNKNOWN')


def membership(config, context):
    root, day = config.shared_root, context.target_date
    candidates = []
    failures = []
    # Original publication receipts, including immutable runs within this month.
    for rel in files(root, f'universes/{day[:6]}*/HK_CONNECT_FULL_MARKET.authority/*/receipt.json'):
        try:
            receipt, rsha = read(root, rel)
            directory = str(Path(rel).parent)
            manifest_rel = directory + '/manifest.json'
            manifest, msha = read(root, manifest_rel, receipt.get('manifest_sha256'))
            effective = manifest.get('effective_date')
            if not isinstance(effective,str) or effective[:6] != day[:6] or effective > day: continue
            if manifest.get('authority_role') != 'HK_CONNECT_FULL_MARKET_AUTHORITY' or manifest.get('status') != 'READY': continue
            producer = manifest.get('producer_owner', {})
            if producer.get('workload_id') != OWNER: continue
            artifact_rel, capture_rel = manifest['artifact_relative'], manifest['capture_relative']
            artifact, asha = read(root, artifact_rel, manifest['artifact_sha256'])
            capture, csha = read(root, capture_rel)
            capture_identity = owner_digest({k:v for k,v in capture.items() if k!='capture_sha256'})
            if capture_identity != manifest['capture_sha256'] or capture_identity != capture.get('capture_sha256'):
                raise ValueError('MEMBERSHIP_CAPTURE_CONTENT_IDENTITY_INVALID')
            if capture.get('codes') != artifact.get('codes') or owner_digest(capture.get('membership_source_payload')) != capture.get('membership_source_sha256'):
                raise ValueError('MEMBERSHIP_CAPTURE_UNION_INVALID')
            publication_rel = manifest.get('publication_relative', directory + '/publication.json')
            publication, psha = read(root, publication_rel)
            current_rel = publication['current_relative']
            _, current_sha = read(root, current_rel, publication['current_sha256'])
            available = publication.get('available_at')
            if not before(available,context.cutoff): continue
            if artifact.get('market') != 'HK_CONNECT' or artifact.get('code_count') != len(artifact.get('codes', [])):
                raise ValueError('MEMBERSHIP_SCOPE_INVALID')
            if any(v.get('production_allowed') is not False or v.get('orders_sent',False) is not False for v in (artifact,manifest,receipt)):
                raise ValueError('MEMBERSHIP_SAFETY_INVALID')
            if receipt.get('artifact_sha256') != asha or receipt.get('capture_sha256') != capture_identity:
                raise ValueError('MEMBERSHIP_RECEIPT_INVALID')
            sources = [(artifact_rel,asha),(capture_rel,csha),(current_rel,current_sha),(manifest_rel,msha),(publication_rel,psha),(rel,rsha)]
            projection = dict(market='HK_CONNECT',codes=artifact['codes'],owner=OWNER,version=owner_digest(sources),
                effective_from=day[:6]+'01',effective_to=day[:6]+'31',available_at=available,
                source_url='https://www.hkex.com.hk/Mutual-Market/Stock-Connect')
            candidates.append((available, dict(source_local_path=str(root),owner=OWNER,artifact_relative=artifact_rel,
                artifact_sha256=asha,projection=projection,checked_files=[dict(source_local_path=str(root),relative=r,sha256=s) for r,s in sources])))
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append(str(error) if isinstance(error,ValueError) else 'MEMBERSHIP_CANDIDATE_INVALID')
    if not candidates:
        reason = 'MONTHLY_AUTHORITY_UNAVAILABLE_BEFORE_CUTOFF'
        if failures: reason += ':' + ','.join(sorted(set(failures)))
        raise ValueError(reason)
    return max(candidates,key=lambda item:item[0])[1]


def announcements(config, context):
    if config.capture_root:
        from .capture_binding import resolve
        # New owner configured means no fallback to an old live capture owner.
        return context.scope_refs.get('capture_binding_pin') or resolve(config,context)
    candidates=[]
    for rel in files(config.manager_root,'announcement_agent_runs/*/evidence/body_corpus_manifest.json'):
        manifest,msha=read(config.manager_root,rel)
        if manifest.get('target_trade_date') != context.target_date: continue
        directory=str(Path(rel).parent)
        corpus_rel=directory+'/body_corpus.json'; receipt_rel=directory+'/capture_receipt.json'
        receipt,rsha=read(config.manager_root,receipt_rel)
        available=receipt.get('finished_at',receipt.get('generated_at',manifest.get('generated_at')))
        if not before(available,context.cutoff): continue
        corpus,csha=read(config.manager_root,corpus_rel,receipt['body_corpus_file_sha256'])
        if corpus.get('target_trade_date')!=context.target_date:
            continue  # Older owner formats are not this full-body corpus contract.
        if receipt.get('body_corpus_manifest_file_sha256')!=msha:
            raise ValueError('CORPUS_DATE_SHA_MISMATCH')
        candidates.append((available,dict(corpus_relative=corpus_rel,
            corpus_sha256=csha,manifest_relative=rel,manifest_sha256=msha,receipt_relative=receipt_rel,receipt_sha256=rsha)))
    if candidates:return max(candidates,key=lambda x:x[0])[1]
    scans=[]
    for rel in files(config.manager_root, f'workspace_announcements/{context.target_date}/**/*.json'):
        scan,sha=read(config.manager_root,rel)
        if scan.get('target_trade_date')==context.target_date and scan.get('owner')=='ManagerResearchJobService.refresh_announcements' and before(scan.get('generated_at'),context.cutoff):
            scans.append(dict(relative=rel,sha256=sha))
    if not scans: raise ValueError('EXACT_DATE_ANNOUNCEMENT_OWNER_UNAVAILABLE')
    return dict(scans=scans)


def hk_panel(config, context):
    day=context.source_sessions['hk_price']; candidates=[]
    for rel in files(config.shared_root,'assets/hk_0_2/panels/*/manifest.json'):
        manifest,sha=read(config.shared_root,rel)
        available=manifest.get('manifest_prepared_at',manifest.get('prepared_at'))
        if manifest.get('panel_max_date')!=day or not before(available,context.cutoff):continue
        candidates.append((available,dict(manifest_relative=rel,manifest_sha256=sha,available_at=available)))
    pin=max(candidates,key=lambda x:x[0])[1] if candidates else None
    # A retrospective projection retains the actual latest panel identity and
    # observation time; it never relabels a newer manifest as the D-1 day.
    if context.phase.value == 'RETROSPECTIVE':
        try:
            pointer, psha = read(config.shared_root, 'assets/hk_0_2/panel_latest.json')
            relative = 'assets/hk_0_2/' + pointer['manifest_relative']
            manifest, sha = read(config.shared_root, relative)
            maximum = manifest.get('panel_max_date')
            available = manifest.get('manifest_prepared_at', manifest.get('prepared_at'))
            if isinstance(maximum,str) and day <= maximum <= context.target_date and before(available,context.cutoff):
                pin = dict(manifest_relative=relative,manifest_sha256=sha,available_at=available,
                    actual_panel_max_date=maximum,projection_price_date=day,
                    checked_files=[dict(source_local_path=str(config.shared_root),relative='assets/hk_0_2/panel_latest.json',sha256=psha)])
        except FileNotFoundError:
            pass
    if pin is None:raise ValueError('EXACT_DATE_HK_PANEL_UNAVAILABLE')
    # Supplements are existing owner bytes only, and remain optional.
    relative=f'assets/hk_0_2/daily_supplements/pointers/{day}.json'
    try:
        pointer,_=read(config.shared_root,relative)
        rel='assets/hk_0_2/'+pointer['manifest_relative']
        manifest,sha=read(config.shared_root,rel,pointer.get('manifest_sha256'))
        checked_time(manifest.get('available_at',manifest.get('prepared_at')),context.cutoff)
        if manifest.get('target_date')!=day:raise ValueError('SUPPLEMENT_DATE_MISMATCH')
        pin['supplement']=dict(manifest_relative=rel,manifest_sha256=sha)
    except FileNotFoundError:pass
    except (OSError,ValueError,KeyError,TypeError) as error:
        # An optional retired six-day sidecar cannot invalidate a complete panel.
        pin['supplement_gap']=str(error) if isinstance(error,ValueError) else 'LEGACY_SUPPLEMENT_OWNER_UNAVAILABLE'
    # Explicit existing owner response only; no acquisition or alternative producer.
    original=config.source_bindings.get('hk_panel',{}).get(day,{})
    if original.get('futu_history'):pin['futu_history']=original['futu_history']
    if original.get('tdxpy_history'):pin['tdxpy_history']=original['tdxpy_history']
    return pin


def security_master(config, context):
    day=context.source_sessions['hk_price']; base='assets/hk_security_master/'
    pointer,_=read(config.shared_root,base+'latest.json')
    entry=pointer['entries'][day]; rel=base+entry['manifest_relative']
    manifest,sha=read(config.shared_root,rel)
    receipt_rel=base+entry['receipt_relative']; receipt,rsha=read(config.shared_root,receipt_rel)
    if receipt.get('manifest_sha256')!=sha or manifest.get('run_id')!=entry['run_id']:
        raise ValueError('MASTER_RUN_RECEIPT_INVALID')
    checked_time(manifest.get('captured_at'),context.cutoff)
    return dict(manifest_relative=rel,manifest_sha256=sha,checked_files=[dict(source_local_path=str(config.shared_root),relative=receipt_rel,sha256=rsha)])



SEED_RELATIVE = 'v4/manager_research/us_mapping_reviewed_20260930.json'
SEED_SHA = 'e6108eca9f30a44a96674941ffc7b44557d44a4f3cbe17983d96d1de23ca956a'
REGISTRY_RELATIVE = 'v4/manager_research/us_mapping_relation_registry.json'
REGISTRY_SHA = 'ffd6ff853eb69a8329c18cf5ac77745ac08f14905279036e494c34eb0b55b3fe'


def reviewed_seed(config, context):
    # Existing reviewed data only; no legacy business module is imported.
    root = config.relation_root
    if root is None or not (Path(root)/SEED_RELATIVE).exists() and not (Path(root)/REGISTRY_RELATIVE).exists():
        return [], []
    seed, ssha = read(root, SEED_RELATIVE, SEED_SHA)
    registry, rsha = read(root, REGISTRY_RELATIVE, REGISTRY_SHA)
    if (seed.get('schema_version') != 'v4.manager_research.us_mapping_reviewed.v1'
            or seed.get('status') != 'REVIEWED_RETROSPECTIVE_RESEARCH'
            or registry.get('schema_version') != 'v4.manager_research.us_mapping_relation_registry.v1'
            or owner_digest({k:v for k,v in seed.items() if k!='artifact_sha256'}) != seed.get('artifact_sha256')
            or owner_digest({k:v for k,v in registry.items() if k!='artifact_sha256'}) != registry.get('artifact_sha256')
            or registry.get('source_seed_sha256') != ssha
            or registry.get('source_report_sha256') != seed.get('report',{}).get('sha256')
            or registry.get('availability_basis') != 'V4_RELEASE_PUBLICATION'
            or registry.get('availability_scope') != 'APPLICATION_SYSTEM_ONLY_NOT_HISTORICAL_PIT_OR_TARGET_DATE_ELIGIBILITY'
            or seed.get('RESEARCH_ONLY') is not True or seed.get('production_allowed') is not False):
        raise ValueError('US_REVIEWED_SEED_REGISTRY_INVALID')
    checked_time(registry.get('available_at'), context.cutoff)
    sources = [dict(source_local_path=str(root),relative=rel,sha256=sha,owner='V4_REVIEWED_US_MAPPING_SEED',available_at=registry['available_at'])
        for rel,sha in [(SEED_RELATIVE,ssha),(REGISTRY_RELATIVE,rsha)]]
    cards=[]
    for original in seed['cards']:
        for us in original.get('daily_match_symbols',[]):
            if us not in US_SYMBOLS:raise ValueError('US_SEED_SYMBOL_OUTSIDE_FIXED_33')
            cards.append({**original,'us_symbol':us,'evidence_review_status':'REVIEWED',
                'reviewer_identity':'V4_REVIEWED_US_MAPPING_SEED', 'available_at':registry['available_at'],
                'relation_identity_sha256':owner_digest(dict(card=original,us_symbol=us,seed_sha256=ssha,registry_sha256=rsha)),
                'publication_evidence':[dict(role='RELATION',published_at=original.get('published_at'),precision='DATE',
                    evidence_basis='REVIEWED_CARD_ORIGINAL_DATE',source_file_sha256=ssha)],
                'relation_source_refs':sources})
    return cards, sources


def us_mapping(config, context):
    session=context.source_sessions['us']; root=config.us_root
    quote_rel=f'research/peripherals/{session}/external_finance.json'
    manifest,msha=read(root,'research/peripherals/manifest.json')
    payload,qsha=read(root,quote_rel,manifest[quote_rel])
    receipt_rel=f'receipts/research/peripherals/{session}/external_finance.json'
    receipt,rsha=read(root,receipt_rel)
    snapshot=payload.get('market_snapshot',{})
    checked_time(snapshot.get('captured_at'),context.cutoff)
    if snapshot.get('capture_session_date')!=session or receipt.get('artifact_sha256',receipt.get('payload_sha256'))!=qsha:
        raise ValueError('US_OWNER_RECEIPT_SESSION_INVALID')
    evidence,esha=read(config.relation_root,config.relation_evidence_relative)
    review,vsha=read(config.relation_root,config.relation_review_relative)
    checked_time(review.get('reviewed_at'),context.cutoff)
    if (review.get('status')!='PASS' or review.get('evidence_file_sha256')!=esha
        or review.get('declared_artifact_sha256')!=evidence.get('artifact_sha256')
        or owner_digest({k:v for k,v in evidence.items() if k!='artifact_sha256'})!=evidence.get('artifact_sha256')
        or review.get('recomputed_artifact_sha256')!=evidence.get('artifact_sha256') or not review.get('reviewer_identity')
        or review.get('safety',{}).get('production_allowed') is not False):
        raise ValueError('US_RELATION_INDEPENDENT_REVIEW_INVALID')
    pairs={tuple(r.get(k) for k in ('us_symbol','hk_symbol','relationship_type','direction')) for r in review['reviewed_pairs']}
    assessments=[]
    reviewed_assessments={a['us_symbol']:a for a in review.get('reviewed_symbol_assessments',[])}
    if len(reviewed_assessments)!=len(review.get('reviewed_symbol_assessments',[])):
        raise ValueError('US_ASSESSMENT_REVIEW_IDENTITY_INVALID')
    seen_assessments=set()
    for assessment in evidence.get('symbol_assessments',[]):
        us=assessment.get('us_symbol');audited=reviewed_assessments.get(us)
        if (us not in US_SYMBOLS or us in seen_assessments or not audited
                or owner_digest(assessment)!=audited.get('assessment_sha256')
                or any(assessment.get(k)!=audited.get(k) for k in ('status','conclusion','candidate_hk_code'))
                or assessment.get('status')!='ASSESSED_WITH_GAPS' or assessment.get('conclusion')!='CANNOT_CONFIRM'
                or assessment.get('candidate_hk_symbol')!='HK.'+str(assessment.get('candidate_hk_code'))):
            raise ValueError('US_ASSESSMENT_REVIEW_IDENTITY_INVALID')
        checked_time(assessment.get('available_at'),review['reviewed_at'])
        seen_assessments.add(us)
        assessments.append(dict(original=assessment,assessment_sha256=audited['assessment_sha256'],
            verification='REVIEWED',review_owner=review['reviewer_identity'],available_at=review['reviewed_at'],
            source_refs=[dict(relative=rel,sha256=sha,owner=review['reviewer_identity'],available_at=review['reviewed_at'])
                for rel,sha in [(config.relation_evidence_relative,esha),(config.relation_review_relative,vsha)]]))
    if seen_assessments!=set(reviewed_assessments):raise ValueError('US_ASSESSMENT_REVIEW_IDENTITY_INVALID')
    cards=[]
    for card in evidence.get('relations',evidence.get('cards',[])):
        if tuple(card.get(k) for k in ('us_symbol','hk_symbol','relationship_type','direction')) not in pairs:
            raise ValueError('US_RELATION_PAIR_NOT_REVIEWED')
        checked_time(card.get('available_at'),review['reviewed_at'])
        cards.append({**card,'relation_source_refs':[dict(relative=config.relation_evidence_relative,sha256=esha,owner=review['reviewer_identity'],available_at=review['reviewed_at'])],'evidence_review_status':'REVIEWED','reviewer_identity':review['reviewer_identity'],
            'available_at':review['reviewed_at'],'review_receipt_sha256':vsha})
    seed_cards, seed_sources = reviewed_seed(config,context)
    joined={}
    for card in [*cards,*seed_cards]:
        key=tuple(card.get(k) for k in ('us_symbol','hk_symbol','relationship_type','direction'))
        if key not in joined:joined[key]=card
        else:
            # Retain both independently bound sources without duplicate decisions.
            original=joined[key]
            original['relation_source_refs']=[*original.get('relation_source_refs',[]),*card.get('relation_source_refs',[])]
            original['reviewed_variants']=[*original.get('reviewed_variants',[]),card]
    projection=dict(cards=list(joined.values()),symbol_assessments=assessments,available_at=review['reviewed_at'],limitations=review.get('limitations',[]),additional_relation_sources=seed_sources)
    return dict(quote_local_path=str(root),quote_relative=quote_rel,quote_sha256=qsha,quote_owner='research_peripheral.external_finance',
        relation_local_path=str(config.relation_root),relation_relative=config.relation_evidence_relative,relation_sha256=esha,
        relation_owner=review['reviewer_identity'],relation_projection=projection,configured_symbols=list(US_SYMBOLS),
        checked_files=[dict(source_local_path=str(root),relative=receipt_rel,sha256=rsha),dict(source_local_path=str(config.relation_root),relative=config.relation_review_relative,sha256=vsha),*seed_sources],
        owner_manifest_ref='research/peripherals/manifest.json',owner_manifest_sha256=msha)


def stage(config,context):
    pointer,sha=read(config.stage_root,'selection_latest.json')
    entries={k:v for k,v in pointer.get('entries',{}).items() if v.get('trade_date')==context.target_date and v.get('market')=='HK_CONNECT'}
    return dict(pointer_sha256=sha,entries=entries)


def resolve_bindings(config,context):
    result={}; gaps={}
    for name, resolver in [('membership',membership),('announcements',announcements),('hk_panel',hk_panel),('security_master',security_master),('us_mapping',us_mapping),('stage',stage)]:
        try: result[name]=resolver(config,context)
        except (OSError,ValueError,KeyError,TypeError) as error:gaps[name]=str(error) if isinstance(error,ValueError) else name.upper()+'_OWNER_UNAVAILABLE'
    # No alternative close producer is configured. Exact-date explicit pins are
    # allowed for an original complete ranking owner, otherwise the lane is unknown.
    return result,gaps
