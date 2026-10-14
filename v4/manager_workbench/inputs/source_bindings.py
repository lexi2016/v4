"""Resolve existing owners into per-job immutable references, never produce data.

Every date/session is supplied by the market calendar. A pointer is an index,
not permission to substitute another date. Projections retain their raw sources.
"""
from __future__ import annotations
import json
from pathlib import Path
from infrastructure.owned_io import SafeRoot
from ..engines.common import US_FACTOR_RULES_VERSION, valid_sha
from .validation import raw_sha, before, owner_digest

OWNER = 'v35_dispatcher.research_panel_daily_hk'
from .us_universe import (
    LEGACY_US_SYMBOLS,
    UNIVERSE_VERSION,
    build_legacy_us_universe_contract,
    build_us_universe_contract,
    load_us_universe_contract as _load_us_universe_contract,
    normalize_relation_registry,
    validate_us_universe_contract,
)


US_SYMBOLS = LEGACY_US_SYMBOLS
US_UNIVERSE_VERSION = UNIVERSE_VERSION
US_RELATION_REGISTRY_VERSION = "US_HK_RELATION_REGISTRY_V3"



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


def hk_industry_classification(config, context):
    """Read one exact-date issuer classification through its existing owner.

    ResearchPeripheralStore validates its payload, receipt, and manifest before
    projection. The existing explicit V4 pin remains a compatibility path for
    already materialized candidate artifacts; no latest or network fallback is
    introduced.
    """
    day = context.target_date
    owner_pins = context.scope_refs.get('owner_bindings', {}) if hasattr(context, 'scope_refs') else {}
    pin = owner_pins.get('hk_industry_classification') if isinstance(owner_pins, dict) else None
    if pin is None:
        date_pins = config.source_bindings.get('hk_industry_classification', {})
        pin = date_pins.get(day) if isinstance(date_pins, dict) else None
    if pin is None:
        date_pins = config.source_bindings.get('us_mapping', {})
        us_pin = date_pins.get(day) if isinstance(date_pins, dict) else None
        pin = us_pin.get('hk_industry_classification') if isinstance(us_pin, dict) else None
    if not isinstance(pin, dict):
        root = Path(config.shared_root) if getattr(config, 'shared_root', None) else None
        if root is None:
            return dict(status='UNAVAILABLE', gap='HK_INDUSTRY_CLASSIFICATION_SHARED_ROOT_MISSING')
        try:
            from infrastructure.research_peripheral_store import (
                HK_INDUSTRY_SOURCE,
                ResearchPeripheralStore,
            )

            source_store = ResearchPeripheralStore(root)
            payload = source_store.read_exact(day, HK_INDUSTRY_SOURCE)
            if payload is None:
                return dict(status='UNAVAILABLE', gap='HK_INDUSTRY_CLASSIFICATION_EXACT_DATE_BINDING_MISSING')
            relative = source_store._relative(day, HK_INDUSTRY_SOURCE)
            receipt_relative = source_store._receipt_relative(day, HK_INDUSTRY_SOURCE)
            manifest_relative = 'research/peripherals/manifest.json'
            manifest, manifest_sha = read(root, manifest_relative)
            expected_payload_sha = manifest.get(relative)
            owner_payload, artifact_sha = read(root, relative, expected_payload_sha)
            receipt, receipt_sha = read(root, receipt_relative)
            if (owner_payload != payload
                    or receipt.get('schema_version') != 'v3_5.research_peripheral_receipt.v1'
                    or receipt.get('trade_date') != day
                    or receipt.get('source') != HK_INDUSTRY_SOURCE
                    or receipt.get('payload_path') != relative
                    or receipt.get('payload_sha256') != artifact_sha
                    or manifest.get(relative) != artifact_sha):
                raise ValueError('HK_INDUSTRY_PERIPHERAL_OWNER_RECEIPT_MANIFEST_INVALID')
            owner_bindings = context.scope_refs.get('owner_bindings', {}) if hasattr(context, 'scope_refs') else {}
            member_pin = owner_bindings.get('membership') if isinstance(owner_bindings, dict) else None
            if not isinstance(member_pin, dict):
                member_pin = membership(config, context)
            projection = member_pin.get('projection')
            codes = sorted(projection.get('codes') or []) if isinstance(projection, dict) else []
            stored_refs = sorted(
                (ref.get('source_local_path'), ref.get('relative'), ref.get('sha256'))
                for ref in payload.get('membership_source_refs', [])
                if isinstance(ref, dict)
            )
            current_refs = sorted(
                (ref.get('source_local_path'), ref.get('relative'), ref.get('sha256'))
                for ref in member_pin.get('checked_files', [])
                if isinstance(ref, dict)
            )
            if (not codes or codes != payload.get('scope_codes')
                    or member_pin.get('artifact_sha256') != payload.get('membership_artifact_sha256')
                    or member_pin.get('artifact_relative') != payload.get('membership_relative')
                    or member_pin.get('owner') != payload.get('membership_owner')
                    or projection.get('available_at') != payload.get('membership_available_at')
                    or projection.get('effective_from') != payload.get('membership_effective_from')
                    or projection.get('effective_to') != payload.get('membership_effective_through')
                    or owner_digest(dict(market='HK_CONNECT', codes=codes)) != payload.get('membership_codes_sha256')
                    or not current_refs or stored_refs != current_refs):
                raise ValueError('HK_INDUSTRY_PERIPHERAL_MEMBERSHIP_BINDING_MISMATCH')
            checked_files = [
                dict(source_local_path=str(root), relative=relative, sha256=artifact_sha),
                dict(source_local_path=str(root), relative=receipt_relative, sha256=receipt_sha),
                dict(source_local_path=str(root), relative=manifest_relative, sha256=manifest_sha),
                *member_pin.get('checked_files', []),
            ]
            try:
                from ..engines.us_factor import HK_INDUSTRY_TO_PROXY
            except ImportError:
                HK_INDUSTRY_TO_PROXY = {}
            rows = []
            for item in payload.get('items', []):
                if not isinstance(item, dict):
                    continue
                row = dict(
                    symbol=item.get('symbol'),
                    issuer_name=item.get('issuer_name'),
                    source_industry=item.get('source_industry'),
                    source_row_sha256=item.get('source_row_sha256'),
                    source_response_sha256=item.get('source_response_sha256'),
                    source_response_ref=item.get('source_response_ref'),
                )
                mapped = HK_INDUSTRY_TO_PROXY.get(row.get('source_industry'))
                if isinstance(mapped, dict):
                    row['mapping_type'] = mapped.get('mapping_type')
                rows.append(row)
            artifact = dict(
                schema_version='v4.manager_workbench.hk_industry_classification.v1',
                source_id=payload.get('source_id'),
                source_owner='research_peripheral.hk_industry_classification',
                market='HK_CONNECT',
                scope_type='HK_CONNECT_FULL_MARKET',
                target_date=day,
                status=payload.get('status'),
                scope_count=payload.get('scope_count'),
                membership_codes_sha256=payload.get('membership_codes_sha256'),
                membership_artifact_sha256=payload.get('membership_artifact_sha256'),
                batch_response_sha256=payload.get('batch_response_sha256'),
                source_url=payload.get('source_url'),
                source_asof=payload.get('source_asof'),
                source_asof_status=payload.get('source_asof_status'),
                captured_at=payload.get('captured_at'),
                source_date_semantics=payload.get('source_date_semantics'),
                requested_codes=payload.get('requested_codes'),
                failures=payload.get('failures'),
                rows=rows,
            )
            return dict(status='READY', owner='research_peripheral.hk_industry_classification',
                artifact=artifact, artifact_relative=relative, artifact_sha256=artifact_sha,
                source_local_path=str(root), source_url=payload.get('source_url'),
                manifest_relative=manifest_relative, manifest_sha256=manifest_sha,
                receipt_relative=receipt_relative, receipt_sha256=receipt_sha,
                checked_files=checked_files)
        except (OSError, ValueError, KeyError, TypeError) as error:
            gap = str(error) if isinstance(error, ValueError) else 'HK_INDUSTRY_CLASSIFICATION_OWNER_UNAVAILABLE'
            return dict(status='UNAVAILABLE', gap=gap)
    try:
        root = Path(pin.get('source_local_path') or pin.get('root') or config.shared_root)
        relative = pin.get('artifact_relative') or pin.get('relative')
        expected = pin.get('artifact_sha256') or pin.get('sha256')
        if not relative or not valid_sha(expected):
            raise ValueError('HK_INDUSTRY_CLASSIFICATION_PIN_INVALID')
        artifact, sha = read(root, relative, expected)
        if (artifact.get('schema_version') != 'v4.manager_workbench.hk_industry_classification.v1'
                or artifact.get('market') != 'HK_CONNECT'
                or artifact.get('target_date') != day
                or not isinstance(artifact.get('rows'), list)):
            raise ValueError('HK_INDUSTRY_CLASSIFICATION_ARTIFACT_IDENTITY_INVALID')
        owner = pin.get('owner') or artifact.get('source_owner')
        if not isinstance(owner, str) or not owner:
            raise ValueError('HK_INDUSTRY_CLASSIFICATION_OWNER_UNKNOWN')
        return dict(status='READY', owner=owner, artifact=artifact,
            artifact_relative=relative, artifact_sha256=sha,
            source_local_path=str(root), source_url=artifact.get('source_url'),
            checked_files=[dict(source_local_path=str(root), relative=relative, sha256=sha)])
    except (OSError, ValueError, KeyError, TypeError) as error:
        gap = str(error) if isinstance(error, ValueError) else 'HK_INDUSTRY_CLASSIFICATION_ARTIFACT_UNAVAILABLE'
        return dict(status='UNAVAILABLE', gap=gap)



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


def us_mapping(config, context):
    session = context.source_sessions['us']
    root = config.us_root

    manifest, msha = read(root, 'research/peripherals/manifest.json')
    # The owner artifact is keyed by research trade date, while its quote rows
    # identify the preceding US session. Prefer the exact target-date artifact;
    # retain the old session-date layout only when the target artifact is absent.
    artifact_date = context.target_date
    quote_rel = f'research/peripherals/{artifact_date}/external_finance.json'
    try:
        SafeRoot(root).read_bytes(quote_rel)
    except FileNotFoundError:
        artifact_date = session
        quote_rel = f'research/peripherals/{artifact_date}/external_finance.json'
    expected_quote_sha = manifest.get(quote_rel)
    if not valid_sha(expected_quote_sha):
        raise ValueError('US_OWNER_ARTIFACT_MANIFEST_BINDING_INVALID')
    payload, qsha = read(root, quote_rel, expected_quote_sha)

    receipt_rel = f'receipts/research/peripherals/{artifact_date}/external_finance.json'
    receipt, rsha = read(root, receipt_rel)

    snapshot = payload.get('market_snapshot', {})
    checked_time(snapshot.get('captured_at'), context.cutoff)

    receipt_payload_sha = receipt.get('artifact_sha256') or receipt.get('payload_sha256')
    if (
        snapshot.get('capture_session_date') != session
        or receipt.get('trade_date') != artifact_date
        or receipt.get('source') != 'external_finance'
        or receipt.get('payload_path') != quote_rel
        or receipt_payload_sha != qsha
        or (artifact_date == context.target_date
            and receipt.get('us_session_date') != session)
    ):
        raise ValueError('US_OWNER_RECEIPT_ARTIFACT_SESSION_INVALID')

    snapshot_contract = snapshot.get("universe_contract")
    if isinstance(snapshot_contract, dict):
        universe_contract = validate_us_universe_contract(snapshot_contract)
    elif len(snapshot.get("quotes", [])) == len(LEGACY_US_SYMBOLS):
        universe_contract = build_legacy_us_universe_contract()
    else:
        raise ValueError("US_UNIVERSE_CONTRACT_MISSING")

    source_gaps_by_symbol = {symbol: [] for symbol in universe_contract["symbols"]}
    raw_quote_gaps = snapshot.get("cannot_confirm", [])
    if isinstance(raw_quote_gaps, list):
        for gap in raw_quote_gaps:
            if not isinstance(gap, str) or not gap.startswith("QUOTE_SYMBOL_MISSING:"):
                continue
            symbol = gap.split(":", 1)[1]
            if symbol in source_gaps_by_symbol:
                source_gaps_by_symbol[symbol].append(gap)

    # Keep the frozen reviewed evidence and its independent receipt intact.
    evidence, esha = read(config.relation_root, config.relation_evidence_relative)
    review, vsha = read(config.relation_root, config.relation_review_relative)
    # Candidate business links are a separate, versioned proposal registry.
    # Their source dates and PIT availability remain explicitly unknown.
    registry_root = Path(__file__).resolve().parents[1] / "data"
    registry_relative = "us_mapping_business_relations_20261014_v3.json"
    registry_source, registry_sha = read(registry_root, registry_relative)
    if (registry_source.get("status") != "PROPOSED"
            or registry_source.get("pit_status") != "PIT_UNCONFIRMED"
            or registry_source.get("strict_selection_eligible") is not False
            or registry_source.get("decision_use") != "OBSERVATION_ONLY"):
        raise ValueError("US_RELATION_PROPOSAL_SAFETY_INVALID")
    registry = normalize_relation_registry(registry_source)

    registry_contract_version = registry.get("contract_version")
    if (registry_contract_version not in {universe_contract["version"], UNIVERSE_VERSION}
            or (universe_contract["version"] == UNIVERSE_VERSION
                and registry_contract_version != UNIVERSE_VERSION)):
        raise ValueError("US_RELATION_UNIVERSE_CONTRACT_MISMATCH")

    if not isinstance(
        registry.get("relations"),
        list,
    ):
        raise ValueError(
            "US_RELATION_REGISTRY_INVALID"
        )

    registry_relations = registry["relations"]

    review_sha = vsha
    checked_time(review.get("reviewed_at"), context.cutoff)
    if (review.get('status')!='PASS' or review.get('evidence_file_sha256')!=esha
        or review.get('declared_artifact_sha256')!=evidence.get('artifact_sha256')
        or owner_digest({k:v for k,v in evidence.items() if k!='artifact_sha256'})!=evidence.get('artifact_sha256')
        or review.get('recomputed_artifact_sha256')!=evidence.get('artifact_sha256') or not review.get('reviewer_identity')
        or review.get('safety',{}).get('production_allowed') is not False):
        raise ValueError('US_RELATION_INDEPENDENT_REVIEW_INVALID')
    reviewed_pairs = (
        review.get("reviewed_pairs", [])
        if isinstance(review, dict)
        else []
    )

    pairs = {
        tuple(
            r.get(k)
            for k in (
                "us_symbol",
                "hk_symbol",
                "relationship_type",
                "direction",
            )
        )
        for r in reviewed_pairs
        if isinstance(r, dict)
    }
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
    proposal_cards = []
    registry_universe_symbols = set(build_us_universe_contract()["symbols"])
    for relation in registry_relations:
        us = relation.get("us_symbol")
        hk = relation.get("hk_symbol")
        if (us not in registry_universe_symbols or not isinstance(hk, str) or not hk.startswith("HK.")
                or relation.get("status") != "PROPOSED"
                or relation.get("pit_status") != "PIT_UNCONFIRMED"):
            raise ValueError("US_RELATION_PROPOSAL_IDENTITY_INVALID")
        sources = relation.get("sources") or []
        if not sources or any(
            not str(source.get("url", "")).startswith("https://")
            or not str(source.get("supports", "")).strip()
            for source in sources
        ):
            raise ValueError("US_RELATION_PROPOSAL_SOURCE_INVALID")
        if us not in universe_contract["symbols"]:
            continue
        proposal_cards.append({
            **relation,
            "relation_source_refs": [dict(
                title=source.get("title"), url=source.get("url"),
                reporting_period=source.get("reporting_period"), supports=source.get("supports"),
            ) for source in sources],
            "evidence_review_status": "PROPOSED",
            "strict_selection_supported": False,
        })
    unmapped_symbols = list(registry_source.get("unmapped_symbols", []))
    unmapped_by_symbol = {
        item.get("us_symbol"): item
        for item in unmapped_symbols
        if isinstance(item, dict) and item.get("us_symbol")
    }
    relation_symbols = {
        card.get("us_symbol")
        for card in [*joined.values(), *proposal_cards]
        if isinstance(card, dict)
    }
    for symbol in universe_contract.get("additional_symbols", []):
        if symbol not in relation_symbols and symbol not in unmapped_by_symbol:
            unmapped_symbols.append({
                "us_symbol": symbol,
                "status": "CANNOT_CONFIRM",
                "reason": "No HK target relationship is established for this configured US symbol.",
            })
    projection=dict(cards=[*joined.values(),*proposal_cards],symbol_assessments=assessments,
        available_at=registry.get('available_at'),limitations=review.get('limitations',[]),
        status=registry.get("status"),pit_status=registry.get("pit_status"),
        decision_use=registry_source.get("decision_use"),
        strict_selection_eligible=registry_source.get("strict_selection_eligible") is True,
        unmapped_symbols=unmapped_symbols,
        additional_relation_sources=[*seed_sources,*inherited_sources])
    factor, factor_files, factor_gap = us_factor_exposure(config, context)
    industry = hk_industry_classification(config, context)
    return dict(quote_local_path=str(root),quote_relative=quote_rel,quote_sha256=qsha,
        quote_artifact_date=artifact_date,quote_source_session=session,
        quote_owner='research_peripheral.external_finance',
        relation_local_path=str(registry_root),relation_relative=registry_relative,relation_sha256=registry_sha,
        relation_owner='US_MAPPING_BUSINESS_RELATION_PROPOSAL_REGISTRY',relation_projection=projection,
        configured_symbols=list(universe_contract["symbols"]),universe_contract=universe_contract,
        universe_version=universe_contract["version"],source_gaps_by_symbol=source_gaps_by_symbol,
        relation_registry_version=US_RELATION_REGISTRY_VERSION,
        factor_exposure=factor,factor_exposure_gap=factor_gap,hk_industry_classification=industry,
        checked_files=[dict(source_local_path=str(root),relative=receipt_rel,sha256=rsha),
            dict(source_local_path=str(config.relation_root),relative=config.relation_evidence_relative,sha256=esha),
            dict(source_local_path=str(config.relation_root),relative=config.relation_review_relative,sha256=vsha),
            dict(source_local_path=str(registry_root),relative=registry_relative,sha256=registry_sha),
            *seed_sources,*inherited_sources,*factor_files,*industry.get('checked_files',[])],
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

def read_us_universe_contract(config):
    return _load_us_universe_contract(config)


def load_us_universe_contract(config, extra_symbols=None):
    return _load_us_universe_contract(config, extra_symbols)
