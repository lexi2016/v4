"""Resolve existing owners into per-job immutable references, never produce data.

Every date/session is supplied by the market calendar. A pointer is an index,
not permission to substitute another date. Projections retain their raw sources.
"""
from __future__ import annotations
import json
from datetime import datetime
from pathlib import Path
from infrastructure.owned_io import SafeRoot
from ..engines.common import US_FACTOR_RULES_VERSION
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
    from upstreams.v3_shared_data.shared_data.hk_history_resolution import policy_for_shared
    resolution = policy_for_shared(config.shared_root)
    selected, _ = read(config.shared_root, pin['manifest_relative'], pin['manifest_sha256'])
    resolution.check_panel(selected['panel_sha256'])
    pin['history_resolution_proof'] = resolution.encode_proof(resolution.proof(
        required_fields=('close','high','trade'), start='19000101', end=day,
        consumer='HK_SOURCE_BINDING_IDENTITY_V1'))
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


def _tdxpy_history_for_exact_parents(config, context, panel_pin, master_pin, configured_pin=None):
    """Discover only a complete TDX61 run bound to this exact panel/master pair."""
    if config.shared_root is None or not panel_pin or not master_pin:
        return None
    day=context.source_sessions['hk_price']
    from upstreams.v3_shared_data.shared_data.hk_daily_supplement import (
        _read_master_identity, _read_panel_identity, read_tdxpy_window_supplement,
    )
    panel, _=read(config.shared_root,panel_pin['manifest_relative'],panel_pin['manifest_sha256'])
    panel_identity=_read_panel_identity(config.shared_root,day,
        manifest_relative=panel_pin['manifest_relative'],manifest_sha256=panel_pin['manifest_sha256'])
    master_identity,codes=_read_master_identity(config.shared_root,day)
    master_doc,_=read(config.shared_root,master_pin['manifest_relative'],master_pin['manifest_sha256'])
    if (master_identity['manifest_relative']!=master_pin['manifest_relative']
            or master_identity['manifest_sha256']!=master_pin['manifest_sha256']
            or master_doc.get('trade_date')!=day
            or master_doc.get('artifact_sha256')!=master_identity['artifact_sha256']):
        raise ValueError('TDXPY_MASTER_PARENT_BINDING_MISMATCH')
    output=Path(config.shared_root)/'assets/hk_0_2/daily_supplements/tdxpy61'
    candidates=[]
    seen=set()
    if isinstance(configured_pin,dict):
        candidates.append(configured_pin)
    for relative in files(output,f'runs/{day}/*/manifest.json'):
        try:
            _,manifest_sha=read(output,relative)
            candidates.append(dict(source_local_path=str(output),manifest_relative=relative,
                manifest_sha256=manifest_sha))
        except (OSError,ValueError,KeyError,TypeError):
            continue
    verified=[]
    for candidate in candidates:
        try:
            source=Path(candidate['source_local_path']).resolve()
            relative=candidate['manifest_relative']
            marker=(str(source),relative,candidate.get('manifest_sha256'))
            if marker in seen:continue
            seen.add(marker)
            if source!=output.resolve():continue
            manifest,msha=read(source,relative,candidate.get('manifest_sha256'))
            raw_rel=manifest['raw_relative'];raw_sha=manifest['raw_sha256']
            pin=dict(source_local_path=str(source),manifest_relative=relative,manifest_sha256=msha,
                raw_relative=raw_rel,raw_sha256=raw_sha,target_date=day,
                run_id=manifest.get('run_id'),available_at=manifest.get('available_at'),
                capture_scope=manifest.get('capture_scope'))
            if pin['capture_scope']!='PANEL_GAPS':continue
            checked,_=read_tdxpy_window_supplement(pin,target_date=day,cutoff=context.cutoff,
                expected_panel_sha=panel['panel_sha256'],expected_master_sha=master_identity['artifact_sha256'],
                expected_codes=codes,expected_panel_manifest_sha=panel_identity['panel_manifest_sha256'],
                expected_master_manifest_sha=master_identity['manifest_sha256'])
            if (checked.get('panel_identity')!=panel_identity
                    or checked.get('master_identity')!=master_identity
                    or not before(checked.get('available_at'),context.cutoff)):
                continue
            available=datetime.fromisoformat(checked['available_at'].replace('Z','+00:00'))
            verified.append((available,pin))
        except (OSError,ValueError,KeyError,TypeError):
            continue
    return max(verified,key=lambda item:item[0])[1] if verified else None


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
US_FACTOR_CANDIDATE_RELATIVE = 'v4/manager_workbench/research_data/us_factor_exposure_candidate_20261013.json'
US_FACTOR_CANDIDATE_SHA = '7e184c5aaad1b8a9ce2e37bfddf0600bf7e20f86dba512054823ffd971d31d7e'
US_FACTOR_REVIEW_RELATIVE = 'v4/manager_workbench/research_data/us_factor_exposure_review_20261013.json'
US_FACTOR_REVIEW_SHA = '390dcca7f7941f3999b6ef3f890f3a8fa2d08de7057342e7f9cba0be51c45948'


def us_factor_exposure(config, context):
    """Bind only the independently paired retrospective exposure registry."""
    if context.rules_version != US_FACTOR_RULES_VERSION:
        return None, [], None
    root = config.relation_root
    if root is None:
        return dict(status='UNAVAILABLE', gap='US_FACTOR_RESEARCH_ROOT_MISSING'), [], 'US_FACTOR_RESEARCH_ROOT_MISSING'
    try:
        candidate, csha = read(root, US_FACTOR_CANDIDATE_RELATIVE, US_FACTOR_CANDIDATE_SHA)
        review, rsha = read(root, US_FACTOR_REVIEW_RELATIVE, US_FACTOR_REVIEW_SHA)
        if (candidate.get('schema_version') != 'v4.manager_workbench.us_factor_exposure_candidate.v1'
                or candidate.get('target_date') != context.target_date
                or candidate.get('RESEARCH_ONLY') is not True or candidate.get('production_allowed') is not False
                or candidate.get('orders_sent') is not False or candidate.get('buy_gate_updated') is not False
                or review.get('schema') != 'v4.manager_workbench.us_factor_exposure_review.v1'
                or review.get('artifact_sha256') != csha
                or not isinstance(review.get('review_owner'), str) or not review.get('review_owner')):
            raise ValueError('US_FACTOR_PAIRED_ARTIFACT_IDENTITY_INVALID')
        checked_time(candidate.get('created_at'), context.cutoff)
        checked_time(review.get('reviewed_at'), context.cutoff)
        facts, rows = candidate.get('rows'), review.get('rows')
        if not isinstance(facts, list) or not isinstance(rows, list):
            raise ValueError('US_FACTOR_PAIRED_ROWS_INVALID')
        fact_ids = [fact.get('id') for fact in facts if isinstance(fact, dict)]
        review_ids = [row.get('id') for row in rows if isinstance(row, dict)]
        if (len(fact_ids) != len(facts) or len(review_ids) != len(rows)
                or len(set(fact_ids)) != len(fact_ids) or len(set(review_ids)) != len(review_ids)
                or set(fact_ids) != set(review_ids)
                or any(row.get('decision') not in ('ACCEPT', 'REJECT') or not isinstance(row.get('reasons'), list)
                       for row in rows)):
            raise ValueError('US_FACTOR_PAIRED_ROW_COVERAGE_INVALID')
        files_checked = [dict(source_local_path=str(root), relative=US_FACTOR_CANDIDATE_RELATIVE,
                              sha256=csha),
                         dict(source_local_path=str(root), relative=US_FACTOR_REVIEW_RELATIVE,
                              sha256=rsha)]
        value = dict(status='READY', candidate=candidate, review=review,
            candidate_relative=US_FACTOR_CANDIDATE_RELATIVE, candidate_sha256=csha,
            review_relative=US_FACTOR_REVIEW_RELATIVE, review_sha256=rsha,
            local_path=str(root), checked_files=files_checked)
        return value, files_checked, None
    except (OSError, ValueError, KeyError, TypeError) as error:
        gap = str(error) if isinstance(error, ValueError) else 'US_FACTOR_PAIRED_ARTIFACT_UNAVAILABLE'
        return dict(status='UNAVAILABLE', gap=gap), [], gap


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


def priority_review(config, evidence, review):
    """New classifications require their own exact review, never a quote rank."""
    if evidence.get('schema_version') != 'v4.manager_workbench.us_mapping_relation_evidence.v3':
        if any('priority_assessment' in c for c in evidence.get('relations', [])):
            raise ValueError('US_PRIORITY_REVIEW_SCHEMA_INVALID')
        return []
    inherited=evidence.get('inherited_evidence',{})
    if (evidence.get('classification_version')!='US_RESEARCH_PRIORITY_REVIEW_V1_20261013'
            or inherited.get('relative')!='v4/manager_research/us_mapping_relation_evidence_20261011.json'
            or inherited.get('review_relative')!='v4/manager_research/us_mapping_relation_evidence_review_20261011.json'):
        raise ValueError('US_PRIORITY_ORIGINAL_IDENTITY_INVALID')
    original,osha=read(config.relation_root,inherited['relative'],inherited.get('raw_sha256'))
    old_review,rsha=read(config.relation_root,inherited['review_relative'],inherited.get('review_raw_sha256'))
    if (old_review.get('status')!='PASS' or old_review.get('evidence_file_sha256')!=osha
            or original.get('artifact_sha256')!=inherited.get('artifact_sha256')
            or owner_digest({k:v for k,v in original.items() if k!='artifact_sha256'})!=original.get('artifact_sha256')
            or old_review.get('recomputed_artifact_sha256')!=original.get('artifact_sha256')):
        raise ValueError('US_PRIORITY_ORIGINAL_IDENTITY_INVALID')
    keys=('us_symbol','hk_symbol','relationship_type','direction')
    identity=lambda c:tuple(c.get(k) for k in keys)
    originals={identity(c):c for c in original.get('relations',[])}
    cards=evidence.get('relations',[])
    audits=review.get('reviewed_priority_assessments',[])
    reviewed={identity(a):a for a in audits}
    old_pairs={identity(c) for c in old_review.get('reviewed_pairs',[])}
    if (len(originals)!=len(original.get('relations',[])) or set(originals)!=old_pairs
            or len(reviewed)!=len(audits) or len(cards)!=len(originals)
            or {identity(c) for c in cards}!=set(originals) or set(reviewed)!=set(originals)
            or {identity(c) for c in review.get('reviewed_pairs',[])}!=set(originals)):
        raise ValueError('US_PRIORITY_TUPLE_REVIEW_INVALID')
    for card in cards:
        key=identity(card);old=originals[key];a=card.get('priority_assessment',{});audit=reviewed[key]
        unchanged={k:v for k,v in card.items() if k not in {'research_priority','research_priority_reason',
            'priority_assessment','original_available_at','new_capture_checks'}}
        unchanged['available_at']=old.get('available_at')
        if ('research_priority' in old):unchanged['research_priority']=old['research_priority']
        if (unchanged!=old or a.get('original_relation_sha256')!=owner_digest(old)
                or a.get('original_evidence_raw_sha256')!=osha or a.get('original_review_raw_sha256')!=rsha
                or a.get('original_tuple')!={k:card.get(k) for k in keys}
                or a.get('classification_version')!=evidence.get('classification_version')
                or a.get('classification_kind')!='NEW_RESEARCH_CLASSIFICATION_NOT_RECOVERED_OLD_FIELD'
                or not a.get('analyst_identity') or a['analyst_identity']==review.get('reviewer_identity')
                or a.get('not_a_quote_based_rank') is not True or a.get('strict_selection_supported') is not False
                or a.get('research_priority') not in ('PRIORITY','WATCH','NONE')
                or a.get('research_priority')!=card.get('research_priority')
                or not a.get('reason') or a['reason']!=card.get('research_priority_reason')
                or owner_digest(a)!=audit.get('assessment_sha256')
                or any(a.get(k)!=audit.get(k) for k in ('research_priority','reason','counter_evidence'))):
            raise ValueError('US_PRIORITY_ASSESSMENT_REVIEW_INVALID')
        checked_time(old.get('available_at'),a.get('classified_at'))
        checked_time(old_review.get('reviewed_at'),a.get('classified_at'))
        checked_time(a.get('classified_at'),review['reviewed_at'])
        if card.get('available_at')!=a.get('classified_at') or evidence.get('classified_at')!=a.get('classified_at'):
            raise ValueError('US_PRIORITY_AVAILABILITY_INVALID')
    return [dict(source_local_path=str(config.relation_root),relative=rel,sha256=sha,
                 owner=old_review.get('reviewer_identity'),available_at=old_review['reviewed_at'])
            for rel,sha in [(inherited['relative'],osha),(inherited['review_relative'],rsha)]]


def _full_mapping_overlay():
    """Read the same pinned full overlay used by the existing catalog API.

    This is a consumer-side read only. Missing owner files are reported as
    CANNOT_CONFIRM; the derived fixture is never substituted for the owner.
    """
    root = Path(__file__).resolve().parents[1] / "research_data"
    catalog_path = root / "us_hk_667_catalog_20261015.json"
    overlay_path = root / "us_hk_667_review_overlay_20261015.json"
    recovery_path = root / "us_hk_667_recovery_overlay_20261016.json"
    if not catalog_path.is_file() or not overlay_path.is_file() or not recovery_path.is_file():
        return {"state": "CANNOT_CONFIRM", "gap": "US_MAPPING_FULL_OVERLAY_OWNER_UNAVAILABLE",
                "stock_count": None, "relation_count": None, "relations": []}
    from ..us_mapping_catalog import CatalogStore
    store = CatalogStore()
    stocks = []
    offset = 0
    total = None
    while total is None or offset < total:
        try:
            page = store.search(catalog_path, overlay_path, offset=offset, limit=200)
        except (OSError, ValueError):
            return {"state": "CANNOT_CONFIRM", "gap": "US_MAPPING_FULL_OVERLAY_VALIDATION_FAILED",
                    "stock_count": None, "relation_count": None, "relations": []}
        total = page.get("total")
        items = page.get("items")
        if not isinstance(total, int) or not isinstance(items, list):
            raise ValueError("US_MAPPING_FULL_OVERLAY_PAGE_INVALID")
        stocks.extend(items)
        if not items or len(items) < 200:
            break
        offset += len(items)
    relations = []
    status_counts = {}
    for stock in stocks:
        for relation in stock.get("relations", []):
            recovery = relation.get("recovery_v2r1") or {}
            status = recovery.get("closure_status")
            if status:
                status_counts[status] = status_counts.get(status, 0) + 1
            relations.append({
                "hk_code": stock.get("hk_code"),
                "hk_name": stock.get("name"),
                "relation_id": relation.get("relation_id"),
                "source_row": relation.get("source_row"),
                "source_record": relation.get("source_record"),
                "source_review_status": relation.get("source_review_status"),
                "independent_verification": relation.get("independent_verification"),
                "research_use": relation.get("research_use"),
                "recovery_v2r1": recovery,
            })
    expected_statuses = {"CLOSED_RESEARCH_SCOPE": 757, "OPEN": 221, "CLOSED_EXCLUDED_SCOPE": 25}
    valid = len(stocks) == 667 and len(relations) == 1003 and status_counts == expected_statuses
    if not valid:
        return {"state": "CANNOT_CONFIRM", "gap": "US_MAPPING_FULL_OVERLAY_CONTRACT_MISMATCH",
                "stock_count": len(stocks), "relation_count": len(relations),
                "status_counts": status_counts, "relations": []}
    recovery_meta = page.get("recovery_v2r1") or {}
    return {
        "state": "READY",
        "stock_count": len(stocks),
        "relation_count": len(relations),
        "status_counts": status_counts,
        "catalog_integrity_sha256": page.get("catalog_integrity_sha256"),
        "recovery_overlay_integrity_sha256": recovery_meta.get("overlay_integrity_sha256"),
        "catalog_file_sha256": raw_sha(catalog_path.read_bytes()),
        "review_overlay_file_sha256": raw_sha(overlay_path.read_bytes()),
        "checked_files": [
            {"source_local_path": str(root), "relative": catalog_path.relative_to(root).as_posix(),
             "sha256": raw_sha(catalog_path.read_bytes())},
            {"source_local_path": str(root), "relative": overlay_path.relative_to(root).as_posix(),
             "sha256": raw_sha(overlay_path.read_bytes())},
            {"source_local_path": str(root), "relative": recovery_path.relative_to(root).as_posix(),
             "sha256": raw_sha(recovery_path.read_bytes())},
        ],
        "relations": relations,
    }


def us_mapping(config, context):
    session=context.source_sessions['us']; root=config.us_root
    manifest,msha=read(root,'research/peripherals/manifest.json')
    # The artifact directory is keyed by the Shanghai trade/scheduled date,
    # while the capture identifies the US exchange session inside its payload.
    # Resolve by the exact session identity, never by assuming those dates match.
    if not isinstance(manifest,dict):
        raise ValueError('US_OWNER_MANIFEST_SHAPE_INVALID')
    candidates=[]
    for relative, expected_sha in sorted(manifest.items()):
        parts=Path(relative).parts
        if (len(parts)!=4 or parts[0]!='research' or parts[1]!='peripherals'
                or parts[3]!='external_finance.json' or len(parts[2])!=8 or not parts[2].isdigit()):
            continue
        try:
            payload,qsha=read(root,relative,expected_sha)
            snapshot=payload.get('market_snapshot',{})
            if snapshot.get('capture_session_date')!=session:
                continue
            receipt_rel=f"receipts/research/peripherals/{parts[2]}/external_finance.json"
            receipt,rsha=read(root,receipt_rel)
            checked_time(snapshot.get('captured_at'),context.cutoff)
            if (receipt.get('artifact_sha256',receipt.get('payload_sha256'))!=qsha
                    or receipt.get('trade_date',parts[2])!=parts[2]
                    or receipt.get('us_session_date',session)!=session):
                raise ValueError('US_OWNER_RECEIPT_SESSION_INVALID')
            candidates.append((relative, payload, qsha, receipt_rel, receipt, rsha))
        except (OSError,ValueError,KeyError,TypeError):
            # Invalid candidates do not become a fallback. A separate exact
            # candidate may still be valid; if none is valid, fail closed below.
            continue
    if len(candidates)!=1:
        raise ValueError('US_OWNER_SESSION_ARTIFACT_NOT_UNIQUE' if candidates else 'US_OWNER_SESSION_ARTIFACT_NOT_FOUND')
    quote_rel,payload,qsha,receipt_rel,receipt,rsha=candidates[0]
    snapshot=payload.get('market_snapshot',{})
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
    inherited_sources=priority_review(config,evidence,review)
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
    projection=dict(cards=list(joined.values()),symbol_assessments=assessments,available_at=review['reviewed_at'],limitations=review.get('limitations',[]),additional_relation_sources=[*seed_sources,*inherited_sources])
    factor, factor_files, factor_gap = us_factor_exposure(config, context)
    full_overlay = _full_mapping_overlay()
    return dict(quote_local_path=str(root),quote_relative=quote_rel,quote_sha256=qsha,quote_owner='research_peripheral.external_finance',
        capture_phase=snapshot.get('capture_phase'),capture_status=payload.get('status'),
        capture_session_date=snapshot.get('capture_session_date'),capture_run_id=payload.get('run_id'),
        capture_cutoff=snapshot.get('captured_at'),owner_receipt_relative=receipt_rel,owner_receipt_sha256=rsha,
        relation_local_path=str(config.relation_root),relation_relative=config.relation_evidence_relative,relation_sha256=esha,
        relation_owner=review['reviewer_identity'],relation_projection=projection,configured_symbols=list(US_SYMBOLS),
        factor_exposure=factor,factor_exposure_gap=factor_gap,
        full_overlay_projection=full_overlay.get("relations",[]),
        full_overlay_summary={k:v for k,v in full_overlay.items() if k!="relations"},
        checked_files=[dict(source_local_path=str(root),relative=receipt_rel,sha256=rsha),dict(source_local_path=str(config.relation_root),relative=config.relation_review_relative,sha256=vsha),*seed_sources,*inherited_sources,*factor_files,*full_overlay.get("checked_files",[])],
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
    if result.get('hk_panel') and result.get('security_master'):
        panel_pin=result['hk_panel']
        configured_pin=panel_pin.pop('tdxpy_history',None)
        try:
            tdx_pin=_tdxpy_history_for_exact_parents(config,context,panel_pin,result['security_master'],configured_pin)
            if tdx_pin:panel_pin['tdxpy_history']=tdx_pin
            gaps.pop('tdxpy_history',None)
        except (OSError,ValueError,KeyError,TypeError) as error:
            gaps['tdxpy_history']=str(error) if isinstance(error,ValueError) else 'TDXPY_HISTORY_PARENT_UNAVAILABLE'
    # No alternative close producer is configured. Exact-date explicit pins are
    # allowed for an original complete ranking owner, otherwise the lane is unknown.
    return result,gaps
