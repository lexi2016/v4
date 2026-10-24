"""Resolve existing owners into per-job immutable references, never produce data.

Every date/session is supplied by the market calendar. A pointer is an index,
not permission to substitute another date. Projections retain their raw sources.
"""
from __future__ import annotations
import json
from datetime import date, datetime
from pathlib import Path
from infrastructure.owned_io import SafeRoot
from ..engines.common import US_FACTOR_RULES_VERSION, valid_sha
from ..engines.us_mapping_consumption import (
    MANUAL_QUOTE_OWNER,
    MANUAL_QUOTE_SCOPE_SHA256,
    normalize_us_symbol,
)
from .validation import raw_sha, before, owner_digest, symbol

OWNER = 'v35_dispatcher.research_panel_daily_hk'
CONNECT_MEMBERSHIP_SOURCE = 'FUTU_HKCONNECT_PLATE_MEMBERSHIP'
_US_MAPPING_CATALOG_STORE = None
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


def _load_observed_hk_industry_pin(config, context, pin):
    """Load one explicitly pinned owner capture under the observed-use policy.

    The owner capture date and capture timestamp stay separate from the run's
    target date. This path is opt-in per target date and never scans for a newer
    file or infers an effective date from capture time.
    """
    day = context.target_date
    observed_day = _date_token(pin.get('observed_trade_date'))
    if (pin.get('policy') != 'LATEST_OBSERVED'
            or pin.get('target_date') != day
            or observed_day != pin.get('observed_trade_date')
            or observed_day is None
            or observed_day > day
            or pin.get('source_asof') is not None
            or pin.get('source_asof_status') != 'UNKNOWN'):
        raise ValueError('HK_INDUSTRY_OBSERVED_POLICY_BINDING_INVALID')
    root = Path(pin.get('source_local_path') or config.shared_root)
    artifact_relative = pin.get('artifact_relative')
    receipt_relative = pin.get('receipt_relative')
    manifest_relative = pin.get('manifest_relative')
    artifact_sha = pin.get('artifact_sha256')
    receipt_sha = pin.get('receipt_sha256')
    manifest_sha = pin.get('manifest_sha256')
    if (not artifact_relative or not receipt_relative or not manifest_relative
            or not valid_sha(artifact_sha) or not valid_sha(receipt_sha)
            or not valid_sha(manifest_sha)):
        raise ValueError('HK_INDUSTRY_OBSERVED_POLICY_PIN_INVALID')
    payload, actual_artifact_sha = read(root, artifact_relative, artifact_sha)
    receipt, actual_receipt_sha = read(root, receipt_relative, receipt_sha)
    manifest, actual_manifest_sha = read(root, manifest_relative, manifest_sha)
    captured_at = payload.get('captured_at')
    cutoff = context.cutoff
    if (manifest.get(artifact_relative) != actual_artifact_sha
            or payload.get('schema_version') != 'v3_5.research_peripheral.v1'
            or payload.get('source_id') != 'EASTMONEY_F10_RPT_HKF10_INFO_ORGPROFILE'
            or payload.get('trade_date') != observed_day
            or payload.get('source_asof') is not None
            or payload.get('source_asof_status') != 'UNKNOWN'
            or payload.get('source_date_semantics') != pin.get('source_date_semantics')
            or payload.get('captured_at') != pin.get('captured_at')
            or not before(captured_at, cutoff)
            or payload.get('status') != pin.get('expected_status')
            or payload.get('scope_count') != pin.get('expected_scope_count')
            or not isinstance(payload.get('items'), list)
            or len(payload['items']) != pin.get('expected_item_count')
            or not isinstance(payload.get('failures'), list)
            or len(payload['failures']) != pin.get('expected_failure_count')
            or receipt.get('schema_version') != 'v3_5.research_peripheral_receipt.v1'
            or receipt.get('trade_date') != observed_day
            or payload.get('source') != 'hk_industry_classification'
            or receipt.get('source') != payload.get('source')
            or receipt.get('payload_path') != artifact_relative
            or receipt.get('payload_sha256') != actual_artifact_sha
            or receipt.get('captured_at') != captured_at
            or receipt.get('item_count') != len(payload['items'])
            or receipt.get('failure_count') != pin.get('expected_failure_count')
            or receipt.get('batch_response_sha256') != payload.get('batch_response_sha256')):
        raise ValueError('HK_INDUSTRY_OBSERVED_POLICY_OWNER_EVIDENCE_INVALID')
    try:
        from ..engines.us_factor import HK_INDUSTRY_TO_PROXY
    except ImportError:
        HK_INDUSTRY_TO_PROXY = {}
    rows = []
    for item in payload['items']:
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
        market='HK_CONNECT', scope_type='HK_CONNECT_FULL_MARKET',
        target_date=day, observed_trade_date=observed_day,
        classification_policy='LATEST_OBSERVED',
        status=payload.get('status'), scope_count=payload.get('scope_count'),
        observed_scope_count=payload.get('scope_count'),
        source_membership_codes_sha256=payload.get('membership_codes_sha256'),
        source_membership_artifact_sha256=payload.get('membership_artifact_sha256'),
        batch_response_sha256=payload.get('batch_response_sha256'),
        source_url=payload.get('source_url'), source_asof=None,
        source_asof_status='UNKNOWN', captured_at=captured_at,
        source_date_semantics=payload.get('source_date_semantics'),
        requested_codes=payload.get('requested_codes'), failures=payload.get('failures'), rows=rows,
    )
    owner = pin.get('owner')
    if not isinstance(owner, str) or not owner:
        raise ValueError('HK_INDUSTRY_CLASSIFICATION_OWNER_UNKNOWN')
    root_text = str(root)
    return dict(status='READY', owner=owner, artifact=artifact,
        artifact_relative=artifact_relative, artifact_sha256=actual_artifact_sha,
        source_local_path=root_text, source_url=payload.get('source_url'),
        receipt_relative=receipt_relative, receipt_sha256=actual_receipt_sha,
        manifest_relative=manifest_relative, manifest_sha256=actual_manifest_sha,
        policy='LATEST_OBSERVED', observed_trade_date=observed_day,
        source_asof=None, source_asof_status='UNKNOWN',
        checked_files=[dict(source_local_path=root_text, relative=artifact_relative, sha256=actual_artifact_sha),
            dict(source_local_path=root_text, relative=receipt_relative, sha256=actual_receipt_sha),
            dict(source_local_path=root_text, relative=manifest_relative, sha256=actual_manifest_sha)])


def _date_token(value):
    """Parse an explicit calendar date without deriving one from capture time."""
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 8 and value.isascii() and value.isdigit():
            parsed = date.fromisoformat(f'{value[:4]}-{value[4:6]}-{value[6:]}')
            return parsed.strftime('%Y%m%d')
        parsed = date.fromisoformat(value)
        return parsed.strftime('%Y%m%d') if parsed.isoformat() == value else None
    except ValueError:
        return None


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
            # Preserve the captured Futu plate source and its exact source date.
            # An artifact effective_date is an observation date, not an interval.
            # Only explicit source interval fields can establish target eligibility.
            interval_fields = (
                ('membership_effective_from', 'membership_effective_through'),
                ('effective_from', 'effective_through'),
                ('effective_from', 'effective_to'),
            )
            effective_from = effective_through = None
            for source in (artifact, manifest, capture):
                if not isinstance(source, dict):
                    continue
                for start_field, end_field in interval_fields:
                    start = _date_token(source.get(start_field))
                    end = _date_token(source.get(end_field))
                    if start and end:
                        effective_from, effective_through = start, end
                        break
                if effective_from is not None:
                    break
            target_period_verified = bool(
                effective_from and effective_through
                and effective_from <= day <= effective_through
            )
            source_date = _date_token(artifact.get('source_date') or artifact.get('effective_date'))
            projection = dict(market='HK_CONNECT', codes=artifact['codes'],
                owner=CONNECT_MEMBERSHIP_SOURCE, producer_owner=OWNER,
                source_role=CONNECT_MEMBERSHIP_SOURCE, source_date=source_date,
                version=owner_digest(sources), effective_from=effective_from,
                effective_to=effective_through, target_period_verified=target_period_verified,
                available_at=available,
                # No HKEX URL is attached to a Futu plate capture.
                source_url=artifact.get('source_url') or capture.get('source_url'))
            source_codes = artifact.get('codes')
            normalized_codes = [symbol(value) for value in source_codes] if isinstance(source_codes, list) else []
            same_month_observation = bool(source_date and source_date[:6] == day[:6] and source_date <= day)
            source_codes_valid = bool(isinstance(source_codes, list) and source_codes
                and len(normalized_codes) == len(source_codes) and None not in normalized_codes
                and len(set(normalized_codes)) == len(normalized_codes))
            research_membership = dict(
                schema_version='v4.manager_workbench.hk_connect_monthly_research_universe.v1',
                status='VERIFIED' if (same_month_observation and source_codes_valid)
                    else 'CANNOT_CONFIRM',
                market='HK_CONNECT', owner=CONNECT_MEMBERSHIP_SOURCE, producer_owner=OWNER,
                source_role=CONNECT_MEMBERSHIP_SOURCE, target_month=day[:6], source_date=source_date,
                available_at=available, cutoff=context.cutoff,
                artifact_relative=artifact_rel, artifact_sha256=asha,
                manifest_relative=manifest_rel, manifest_sha256=msha,
                receipt_relative=rel, receipt_sha256=rsha,
                publication_relative=publication_rel, publication_sha256=psha,
                capture_relative=capture_rel, capture_sha256=csha,
                codes=sorted(normalized_codes) if source_codes_valid else [],
                code_count=len(normalized_codes) if source_codes_valid else 0,
                codes_sha256=owner_digest(dict(market='HK_CONNECT', codes=sorted(normalized_codes)))
                    if source_codes_valid else None,
                version=owner_digest(sources),
                target_period_verified=target_period_verified,
                formal_target_eligibility='VERIFIED' if target_period_verified else 'CANNOT_CONFIRM',
                formal_target_gap=None if target_period_verified else 'CONNECT_MEMBERSHIP_TARGET_EFFECTIVE_PERIOD_UNCONFIRMED',
                checked_files=[dict(source_local_path=str(root), relative=relative, sha256=source_sha)
                    for relative, source_sha in sources],
            )
            candidates.append((available, dict(source_local_path=str(root), owner=CONNECT_MEMBERSHIP_SOURCE,
                producer_owner=OWNER, artifact_relative=artifact_rel,
                artifact_sha256=asha,projection=projection,monthly_research=research_membership,
                checked_files=[dict(source_local_path=str(root),relative=r,sha256=s) for r,s in sources])))
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
    already materialized candidate artifacts. A fixed observed-policy template
    is an explicit fallback after date pins; no source discovery or network is used.
    """
    day = context.target_date
    owner_pins = context.scope_refs.get('owner_bindings', {}) if hasattr(context, 'scope_refs') else {}
    explicit_pin = isinstance(owner_pins, dict) and 'hk_industry_classification' in owner_pins
    pin = owner_pins.get('hk_industry_classification') if explicit_pin else None
    if not explicit_pin:
        date_pins = config.source_bindings.get('hk_industry_classification', {})
        explicit_pin = isinstance(date_pins, dict) and day in date_pins
        pin = date_pins.get(day) if explicit_pin else None
    if not explicit_pin:
        date_pins = config.source_bindings.get('us_mapping', {})
        us_pin = date_pins.get(day) if isinstance(date_pins, dict) else None
        explicit_pin = isinstance(us_pin, dict) and 'hk_industry_classification' in us_pin
        pin = us_pin.get('hk_industry_classification') if explicit_pin else None
    if explicit_pin and not isinstance(pin, dict):
        return dict(status='UNAVAILABLE', gap='HK_INDUSTRY_CLASSIFICATION_EXPLICIT_PIN_INVALID')
    if not explicit_pin:
        # An explicitly configured fixed capture can be reused across target
        # sessions. Only the projection target changes; source date/time and
        # all three owner hashes are still checked by the same pinned loader.
        date_pins = config.source_bindings.get('hk_industry_classification', {})
        template = date_pins.get('observed_policy_template') if isinstance(date_pins, dict) else None
        if template is not None:
            if (not isinstance(template, dict) or 'target_date' in template
                    or template.get('policy') != 'LATEST_OBSERVED'):
                return dict(status='UNAVAILABLE', gap='HK_INDUSTRY_OBSERVED_POLICY_TEMPLATE_INVALID')
            pin = dict(template, target_date=day)
    if isinstance(pin, dict) and pin.get('policy') == 'LATEST_OBSERVED':
        try:
            return _load_observed_hk_industry_pin(config, context, pin)
        except (OSError, ValueError, KeyError, TypeError) as error:
            gap = str(error) if isinstance(error, ValueError) else 'HK_INDUSTRY_CLASSIFICATION_OWNER_UNAVAILABLE'
            return dict(status='UNAVAILABLE', gap=gap)
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
    """Bind a date-paired review for daily modes; keep the 10/13 pair retrospective."""
    if context.rules_version != US_FACTOR_RULES_VERSION:
        return None, [], None
    root = config.relation_root
    if root is None:
        return dict(status='UNAVAILABLE', gap='US_FACTOR_RESEARCH_ROOT_MISSING'), [], 'US_FACTOR_RESEARCH_ROOT_MISSING'
    phase = getattr(context.phase, 'value', context.phase)
    if phase == 'RETROSPECTIVE':
        candidate_relative, candidate_expected = US_FACTOR_CANDIDATE_RELATIVE, US_FACTOR_CANDIDATE_SHA
        review_relative, review_expected = US_FACTOR_REVIEW_RELATIVE, US_FACTOR_REVIEW_SHA
    elif phase in ('MANUAL', 'NEXT_DAY'):
        day_pin = (config.source_bindings.get('us_mapping', {}) or {}).get(context.target_date, {})
        pair = day_pin.get('factor_exposure_pair') if isinstance(day_pin, dict) else None
        if not isinstance(pair, dict):
            gap = 'US_FACTOR_DAILY_PAIRED_REVIEW_NOT_BOUND'
            return dict(status='UNAVAILABLE', gap=gap), [], gap
        candidate_relative, candidate_expected = pair.get('candidate_relative'), pair.get('candidate_sha256')
        review_relative, review_expected = pair.get('review_relative'), pair.get('review_sha256')
        if (not isinstance(candidate_relative, str) or not candidate_relative
                or not isinstance(review_relative, str) or not review_relative
                or not valid_sha(candidate_expected) or not valid_sha(review_expected)):
            gap = 'US_FACTOR_DAILY_PAIRED_REVIEW_BINDING_INVALID'
            return dict(status='UNAVAILABLE', gap=gap), [], gap
    else:
        gap = 'US_FACTOR_PHASE_NOT_SUPPORTED'
        return dict(status='UNAVAILABLE', gap=gap), [], gap
    try:
        candidate, csha = read(root, candidate_relative, candidate_expected)
        review, rsha = read(root, review_relative, review_expected)
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
        files_checked = [dict(source_local_path=str(root), relative=candidate_relative,
                              sha256=csha),
                         dict(source_local_path=str(root), relative=review_relative,
                              sha256=rsha)]
        value = dict(status='READY', candidate=candidate, review=review,
            candidate_relative=candidate_relative, candidate_sha256=csha,
            review_relative=review_relative, review_sha256=rsha,
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


def _valid_sha256(value):
    return (isinstance(value, str) and len(value) == 64
            and all(char in '0123456789abcdef' for char in value))


_RECOVERY_STATE_PATHS = {
    "current_applicability_state": "CURRENT_APPLICABILITY",
    "fact_state": "FACT_VERIFIED_SCOPE",
    "identity_state": "IDENTITY_SCOPE",
}


def _adapt_effective_research_schema(effective_research):
    """Normalize the two observed recovery layouts without hiding conflicts."""
    if not isinstance(effective_research, dict):
        return {"state_conflicts": {}}
    adapted = dict(effective_research)
    conflicts = {}
    containers = [
        ("whitelist_scope", effective_research.get("whitelist_scope")),
        ("research_layers", effective_research.get("research_layers")),
        ("six_layers", effective_research.get("six_layers")),
    ]
    for field, section in _RECOVERY_STATE_PATHS.items():
        values = []
        top_level = effective_research.get(field)
        if isinstance(top_level, str) and top_level.strip():
            values.append((field, top_level.strip()))
        for container_name, container in containers:
            if not isinstance(container, dict):
                continue
            nested = container.get(section)
            if isinstance(nested, dict):
                nested = nested.get("state") or nested.get("status") or nested.get("finding")
            if isinstance(nested, str) and nested.strip():
                values.append((f"{container_name}.{section}", nested.strip()))
        distinct = {value.upper() for _, value in values}
        if len(distinct) > 1:
            conflicts[field] = [{"path": path, "value": value} for path, value in values]
            adapted[field] = None
        elif values:
            adapted[field] = values[0][1]
        else:
            adapted[field] = None
    adapted["use_scope"] = effective_research.get("whitelist_scope")
    adapted["research_layers"] = effective_research.get("research_layers")
    adapted["six_layers"] = effective_research.get("six_layers")
    adapted["state_conflicts"] = conflicts
    return adapted


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
    global _US_MAPPING_CATALOG_STORE
    if _US_MAPPING_CATALOG_STORE is None:
        from ..us_mapping_catalog import CatalogStore
        _US_MAPPING_CATALOG_STORE = CatalogStore()
    store = _US_MAPPING_CATALOG_STORE
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
    from .. import us_mapping_catalog as catalog_module
    recovery_raw = recovery_path.read_bytes()
    if raw_sha(recovery_raw) != catalog_module.RECOVERY_OVERLAY_SHA256:
        return {"state": "CANNOT_CONFIRM", "gap": "US_MAPPING_FULL_OVERLAY_VALIDATION_FAILED",
                "stock_count": len(stocks), "relation_count": None, "relations": []}
    try:
        recovery_payload = json.loads(recovery_raw)
        recovery_rows = recovery_payload.get("records")
        if not isinstance(recovery_rows, list):
            raise ValueError("RECOVERY_RECORDS_INVALID")
        recovery_by_id = {row.get("relation_id"): row for row in recovery_rows
                          if isinstance(row, dict) and isinstance(row.get("relation_id"), str)}
        if len(recovery_by_id) != len(recovery_rows):
            raise ValueError("RECOVERY_RELATION_ID_INVALID")
    except (ValueError, TypeError, AttributeError):
        return {"state": "CANNOT_CONFIRM", "gap": "US_MAPPING_FULL_OVERLAY_VALIDATION_FAILED",
                "stock_count": len(stocks), "relation_count": None, "relations": []}
    for stock in stocks:
        for relation in stock.get("relations", []):
            recovery = relation.get("recovery_v2r1") or {}
            recovery_record = recovery_by_id.get(relation.get("relation_id"))
            effective_research = recovery_record.get("effective_research") if isinstance(recovery_record, dict) else None
            field_assessments = recovery_record.get("field_assessments") if isinstance(recovery_record, dict) else None
            expected_research_sha = ((recovery_record.get("effective_summary") or {}).get("effective_research_sha256")
                                     if isinstance(recovery_record, dict) else None)
            if not isinstance(field_assessments, list) or not isinstance(effective_research, dict):
                return {"state": "CANNOT_CONFIRM", "gap": "US_MAPPING_FULL_OVERLAY_VALIDATION_FAILED",
                        "stock_count": len(stocks), "relation_count": None, "relations": []}
            field_sha256 = {}
            for assessment in field_assessments:
                field = assessment.get("source_field") if isinstance(assessment, dict) else None
                field_sha = assessment.get("effective_research_sha256") if isinstance(assessment, dict) else None
                if (not isinstance(field, str) or field in field_sha256
                        or not _valid_sha256(field_sha) or field_sha != expected_research_sha):
                    return {"state": "CANNOT_CONFIRM", "gap": "US_MAPPING_FULL_OVERLAY_VALIDATION_FAILED",
                            "stock_count": len(stocks), "relation_count": None, "relations": []}
                field_sha256[field] = field_sha
            if len(field_sha256) != 7:
                return {"state": "CANNOT_CONFIRM", "gap": "US_MAPPING_FULL_OVERLAY_VALIDATION_FAILED",
                        "stock_count": len(stocks), "relation_count": None, "relations": []}
            status = recovery.get("closure_status")
            if status:
                status_counts[status] = status_counts.get(status, 0) + 1
            adapted_research = _adapt_effective_research_schema(effective_research)
            recovery = dict(recovery, field_sha256=field_sha256,
                            use_scope=adapted_research.get("use_scope"),
                            current_applicability_state=adapted_research.get("current_applicability_state"),
                            fact_state=adapted_research.get("fact_state"),
                            identity_state=adapted_research.get("identity_state"),
                            research_layers=adapted_research.get("research_layers"),
                            six_layers=adapted_research.get("six_layers"),
                            state_conflicts=adapted_research.get("state_conflicts"),
                            remaining_gaps=effective_research.get("remaining_gaps"),
                            acceptance_closure_basis=(recovery_record.get("current_summary_csv_row") or {}).get("closure_basis"),
                            acceptance_closure_scope=(recovery_record.get("current_summary_csv_row") or {}).get("closure_scope"))
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
    relation_ids = [relation.get("relation_id") for relation in relations]
    valid = (len(stocks) == 667 and len(relations) == 1003
             and len(set(relation_ids)) == 1003
             and all(isinstance(relation_id, str) and relation_id for relation_id in relation_ids)
             and status_counts == expected_statuses)
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
        "stock_identities": [
            {"hk_code": stock.get("hk_code"), "name": stock.get("name")}
            for stock in stocks
        ],
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

def _manual_quote_scope_binding(root, manifest, manifest_sha, session, cutoff,
                                full_overlay, configured_symbols):
    """Validate the frozen expanded scope against its separate immutable owner artifact."""
    base_contract = build_us_universe_contract()
    base_symbols = set(base_contract["symbols"])
    catalog_symbols = set()
    invalid_symbols = set()
    for relation in full_overlay.get("relations", []):
        source = relation.get("source_record") if isinstance(relation, dict) else None
        raw = source.get("asset_code") if isinstance(source, dict) else None
        normalized = normalize_us_symbol(raw)
        if normalized:
            catalog_symbols.add(normalized)
        elif raw:
            invalid_symbols.add(str(raw))
    expected_symbols = sorted(base_symbols | catalog_symbols | {"XLU", "KIE"})

    def unavailable(reason):
        return dict(state="CANNOT_CONFIRM", gap=reason, owner=MANUAL_QUOTE_OWNER,
                    scope_sha256=MANUAL_QUOTE_SCOPE_SHA256, us_session_date=session,
                    requested_symbol_count=len(expected_symbols), available_symbol_count=0,
                    quotes={}, symbol_gaps={})

    if (full_overlay.get("state") != "READY"
            or full_overlay.get("catalog_file_sha256") != "3d7e1c3931a66a6844f4cb5c0d35030ed0e615e3e8246bc0b22caddc61dbb671"
            or len(catalog_symbols) != 517 or len(invalid_symbols) != 1
            or len(expected_symbols) != 547
            or set(configured_symbols) != base_symbols):
        return unavailable("US_MANUAL_QUOTE_SCOPE_EXPECTED_SYMBOLS_UNVERIFIED")
    expected_contract = build_us_universe_contract(sorted(set(expected_symbols) - base_symbols))
    exact = []
    for relative, expected_sha in sorted(manifest.items()):
        parts = Path(relative).parts
        if (len(parts) != 5 or parts[:3] != ("research", "peripherals", "history_backfill")
                or parts[4] != "external_finance.json" or len(parts[3]) != 8 or not parts[3].isdigit()):
            continue
        try:
            payload, payload_sha = read(root, relative, expected_sha)
            snapshot = payload.get("market_snapshot")
            if not isinstance(snapshot, dict) or snapshot.get("capture_session_date") != session:
                continue
            from infrastructure.research_peripheral_store import validate_research_peripheral
            validate_research_peripheral(payload, expected_trade_date=parts[3], expected_source="external_finance")
            receipt_relative = f"receipts/research/peripherals/history_backfill/{parts[3]}/external_finance.json"
            receipt, receipt_sha = read(root, receipt_relative)
            expected_receipt = dict(
                schema_version="v3_5.research_peripheral_backfill_receipt.v1",
                trade_date=parts[3], source="external_finance", payload_path=relative,
                payload_sha256=payload_sha, item_count=payload.get("item_count"),
                capture_origin="HISTORICAL_BACKFILL", original_time_capture=False,
                write_policy="read_only", recommendation_status="RESEARCH_ONLY",
                production_allowed=False, buy_gate_updated=False, orders_sent=False,
            )
            if (manifest.get(relative) != payload_sha or receipt != expected_receipt
                    or payload.get("capture_origin") != "HISTORICAL_BACKFILL"
                    or payload.get("original_time_capture") is not False
                    or payload.get("capture_mode") != "MANUAL_QUOTE_SCOPE_EXPANSION"
                    or payload.get("status") != "READY_EMPTY" or payload.get("item_count") != 0
                    or payload.get("market_snapshot_status") != snapshot.get("status")
                    or snapshot.get("capture_phase") != "HISTORICAL_BACKFILL"
                    or snapshot.get("capture_mode") != "MANUAL_QUOTE_SCOPE_EXPANSION"
                    or snapshot.get("status") not in {"READY", "PARTIAL"}
                    or not valid_sha(snapshot.get("source_response_sha256"))):
                raise ValueError("US_MANUAL_QUOTE_SCOPE_OWNER_IDENTITY_INVALID")
            scope_record = snapshot.get("manual_quote_scope")
            expected_symbols_sha = __import__("hashlib").sha256(
                json.dumps(expected_symbols, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
            if (not isinstance(scope_record, dict)
                    or scope_record.get("schema_version") != "v4.manual_us_quote_scope.v1"
                    or scope_record.get("scope_sha256") != MANUAL_QUOTE_SCOPE_SHA256
                    or scope_record.get("parent_scope_sha256") != MANUAL_QUOTE_SCOPE_SHA256
                    or scope_record.get("scope_mode") != "FULL"
                    or scope_record.get("symbols_sha256") != expected_symbols_sha
                    or scope_record.get("symbols") != expected_symbols
                    or scope_record.get("requested_symbol_count") != len(expected_symbols)
                    or scope_record.get("captured_at") != snapshot.get("captured_at")
                    or snapshot.get("universe_contract") != expected_contract
                    or snapshot.get("requested_symbol_count") != len(expected_symbols)):
                raise ValueError("US_MANUAL_QUOTE_SCOPE_UNIVERSE_OR_DIGEST_MISMATCH")
            captures = payload.get("us_session_captures") or []
            matching = [row for row in captures if isinstance(row, dict)
                        and row.get("us_session_date") == session
                        and row.get("capture_phase") == "HISTORICAL_BACKFILL"]
            if (len(matching) != 1
                    or matching[0].get("capture_origin") != "HISTORICAL_BACKFILL"
                    or matching[0].get("original_time_capture") is not False
                    or matching[0].get("capture_mode") != "MANUAL_QUOTE_SCOPE_EXPANSION"
                    or matching[0].get("captured_at") != snapshot.get("captured_at")):
                raise ValueError("US_MANUAL_QUOTE_SCOPE_CAPTURE_IDENTITY_INVALID")
            captured_at = snapshot.get("captured_at")
            checked_time(captured_at, cutoff)
            from datetime import datetime
            from zoneinfo import ZoneInfo
            from contracts.us_equity_calendar import latest_completed_session, session as us_session
            captured = datetime.fromisoformat(str(captured_at).replace("Z", "+00:00"))
            if latest_completed_session(captured).session_date != session:
                raise ValueError("US_MANUAL_QUOTE_SCOPE_NOT_LATEST_COMPLETED_SESSION")
            official = us_session(session)
            quotes = snapshot.get("quotes") or []
            if not isinstance(quotes, list):
                raise ValueError("US_MANUAL_QUOTE_SCOPE_QUOTES_INVALID")
            quote_map = {}
            symbol_gaps = dict(snapshot.get("quote_failures") or {})
            if not isinstance(snapshot.get("quote_failures") or {}, dict):
                raise ValueError("US_MANUAL_QUOTE_SCOPE_FAILURES_INVALID")
            for quote in quotes:
                symbol_value = quote.get("symbol") if isinstance(quote, dict) else None
                if symbol_value not in expected_symbols or symbol_value in quote_map:
                    raise ValueError("US_MANUAL_QUOTE_SCOPE_QUOTE_SYMBOL_INVALID")
                try:
                    observed = datetime.strptime(
                        session + " " + str(quote.get("session_time") or ""), "%Y%m%d %H:%M:%S"
                    ).replace(tzinfo=ZoneInfo("America/New_York"))
                except (TypeError, ValueError):
                    symbol_gaps[symbol_value] = "QUOTE_SESSION_TIMESTAMP_INVALID"
                    continue
                if observed < official.close_at:
                    symbol_gaps[symbol_value] = "QUOTE_PROVIDER_TIMESTAMP_BEFORE_OFFICIAL_CLOSE"
                    continue
                if observed > captured:
                    symbol_gaps[symbol_value] = "QUOTE_PROVIDER_TIMESTAMP_AFTER_CAPTURE"
                    continue
                quote_map[symbol_value] = dict(quote)
            for symbol_value in expected_symbols:
                if symbol_value not in quote_map:
                    symbol_gaps.setdefault(symbol_value, "QUOTE_SYMBOL_MISSING")
            if not quote_map:
                raise ValueError("US_MANUAL_QUOTE_SCOPE_NO_VALID_QUOTES")
            if (snapshot.get("available_symbol_count") != len(quotes)
                    or snapshot.get("status") != ("READY" if len(quotes) == len(expected_symbols) else "PARTIAL")):
                raise ValueError("US_MANUAL_QUOTE_SCOPE_COVERAGE_STATUS_INVALID")
            exact.append((relative, parts[3], payload_sha, receipt_relative, receipt_sha,
                          snapshot, quote_map, symbol_gaps))
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            continue
    if len(exact) != 1:
        return unavailable("US_MANUAL_QUOTE_SCOPE_ARTIFACT_NOT_UNIQUE" if exact
                           else "US_MANUAL_QUOTE_SCOPE_ARTIFACT_NOT_FOUND")
    relative, trade_date, payload_sha, receipt_relative, receipt_sha, snapshot, quote_map, symbol_gaps = exact[0]
    state = "READY" if len(quote_map) == len(expected_symbols) else "PARTIAL"
    return dict(
        state=state, gap=None if state == "READY" else "US_MANUAL_QUOTE_SCOPE_PARTIAL",
        owner=MANUAL_QUOTE_OWNER, scope_sha256=MANUAL_QUOTE_SCOPE_SHA256,
        us_session_date=session, trade_date=trade_date, available_at=snapshot.get("captured_at"),
        requested_symbol_count=len(expected_symbols), available_symbol_count=len(quote_map),
        coverage_fraction=len(quote_map) / len(expected_symbols), symbols=expected_symbols,
        quotes=quote_map, symbol_gaps=symbol_gaps, payload_relative=relative,
        payload_sha256=payload_sha, receipt_relative=receipt_relative, receipt_sha256=receipt_sha,
        manifest_relative="research/peripherals/manifest.json", manifest_sha256=manifest_sha,
        source_response_sha256=snapshot.get("source_response_sha256"),
        checked_files=[dict(source_local_path=str(root), relative=relative, sha256=payload_sha),
                       dict(source_local_path=str(root), relative=receipt_relative, sha256=receipt_sha),
                       dict(source_local_path=str(root), relative="research/peripherals/manifest.json", sha256=manifest_sha)],
    )


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
            if not _valid_sha256(expected_sha):
                raise ValueError('US_OWNER_MANIFEST_ENTRY_SHA_INVALID')
            payload,qsha=read(root,relative,expected_sha)
            from infrastructure.research_peripheral_store import validate_research_peripheral
            validate_research_peripheral(payload, expected_trade_date=parts[2],
                                         expected_source='external_finance')
            snapshot=payload.get('market_snapshot',{})
            if not isinstance(snapshot, dict):
                raise ValueError('US_OWNER_MARKET_SNAPSHOT_INVALID')
            if (snapshot.get('capture_session_date') != session
                    or snapshot.get('capture_phase') != 'POST_CLOSE'):
                continue
            receipt_rel=f"receipts/research/peripherals/{parts[2]}/external_finance.json"
            receipt,rsha=read(root,receipt_rel)
            checked_time(snapshot.get('captured_at'),context.cutoff)
            if (receipt.get('schema_version')!='v3_5.research_peripheral_receipt.v1'
                    or receipt.get('trade_date')!=parts[2]
                    or receipt.get('source')!='external_finance'
                    or receipt.get('payload_path')!=relative
                    or receipt.get('payload_sha256')!=qsha
                    or receipt.get('market_snapshot_sha256')!=owner_digest(snapshot)
                    or receipt.get('market_snapshot_schema_version')!=snapshot.get('schema_version')
                    or receipt.get('market_snapshot_status')!=payload.get('market_snapshot_status', snapshot.get('status'))
                    or ('us_session_date' in receipt and receipt.get('us_session_date')!=session)):
                raise ValueError('US_OWNER_RECEIPT_IDENTITY_INVALID')
            candidates.append((relative, payload, qsha, receipt_rel, receipt, rsha))
        except (OSError,ValueError,KeyError,TypeError):
            # Invalid candidates do not become a fallback. A separate exact
            # candidate may still be valid; if none is valid, fail closed below.
            continue
    if len(candidates)!=1:
        raise ValueError('US_OWNER_SESSION_ARTIFACT_NOT_UNIQUE' if candidates else 'US_OWNER_SESSION_ARTIFACT_NOT_FOUND')
    quote_rel,payload,qsha,receipt_rel,receipt,rsha=candidates[0]
    snapshot=payload.get('market_snapshot',{})
    artifact_date = Path(quote_rel).parts[2]

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
    full_overlay = _full_mapping_overlay()
    from .us_mapping_close_scope import bind_scheduled_scope
    manual_quote_scope = bind_scheduled_scope(
        snapshot, payload, source_session=session, cutoff=context.cutoff,
        payload_relative=quote_rel, payload_sha256=qsha,
        receipt_relative=receipt_rel, receipt_sha256=rsha, manifest_sha256=msha,
    )
    if manual_quote_scope is None:
        manual_quote_scope = _manual_quote_scope_binding(
            root, manifest, msha, session, context.cutoff,
            full_overlay, universe_contract["symbols"],
        )
    else:
        # Same owner artifact as the daily 48-symbol surface; no historical
        # fallback can disguise an invalid scheduled supplement.
        for checked in manual_quote_scope.get("checked_files", []):
            checked["source_local_path"] = str(root)
    return dict(quote_local_path=str(root),quote_relative=quote_rel,quote_sha256=qsha,
        quote_artifact_date=artifact_date,quote_source_session=session,
        quote_owner='research_peripheral.external_finance',
        capture_phase=snapshot.get('capture_phase'),capture_status=payload.get('status'),
        capture_session_date=snapshot.get('capture_session_date'),capture_run_id=payload.get('run_id'),
        capture_cutoff=snapshot.get('captured_at'),owner_receipt_relative=receipt_rel,owner_receipt_sha256=rsha,
        relation_local_path=str(registry_root),relation_relative=registry_relative,relation_sha256=registry_sha,
        relation_owner='US_MAPPING_BUSINESS_RELATION_PROPOSAL_REGISTRY',relation_projection=projection,
        configured_symbols=list(universe_contract["symbols"]),universe_contract=universe_contract,
        universe_version=universe_contract["version"],source_gaps_by_symbol=source_gaps_by_symbol,
        relation_registry_version=US_RELATION_REGISTRY_VERSION,
        factor_exposure=factor,factor_exposure_gap=factor_gap,hk_industry_classification=industry,
        full_overlay_projection=full_overlay.get('relations',[]),
        full_overlay_stock_identities=full_overlay.get('stock_identities',[]),
        full_overlay_summary={k:v for k,v in full_overlay.items()
            if k not in ('relations','stock_identities')},
        manual_quote_scope=manual_quote_scope,
        checked_files=[dict(source_local_path=str(root),relative=receipt_rel,sha256=rsha),
            dict(source_local_path=str(config.relation_root),relative=config.relation_evidence_relative,sha256=esha),
            dict(source_local_path=str(config.relation_root),relative=config.relation_review_relative,sha256=vsha),
            dict(source_local_path=str(registry_root),relative=registry_relative,sha256=registry_sha),
            *seed_sources,*inherited_sources,*factor_files,*industry.get('checked_files',[]),
            *full_overlay.get('checked_files',[]),
            *manual_quote_scope.get('checked_files',[])],
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


def read_us_universe_contract(config):
    return _load_us_universe_contract(config)


def load_us_universe_contract(config, extra_symbols=None):
    return _load_us_universe_contract(config, extra_symbols)


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

