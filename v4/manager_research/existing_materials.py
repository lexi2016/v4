"""Consume existing owner-verified archives/snapshots, without HTTP or fetching.

The original ResearchArchiveStore / HourlyResearchStore / Vibe validators remain
mandatory. They are intentionally NOT reimplemented here. No unvalidated JSON,
latest-pointer fallback, archive mtime, free-text security code or A-share pool
is admitted as a HK candidate.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from .workspace_projection import date_token, digest, themes_of, timestamp
from .workspace_read_control import checkpoint, count, phase

MAX_ARTIFACTS = 775  # bounded 31-day native-calendar window; daily + up to 24 slots
MAX_ARTICLES = 2000


def project_archive(payload: Mapping[str, Any], binding: Mapping[str, Any], date: str) -> tuple[list[dict], list[str]]:
    """Projection only, called after the existing store's exact read/validation."""
    if binding.get('status') != 'VERIFIED' or not binding.get('payload_path') or not re.fullmatch(r'[0-9a-f]{64}',str(binding.get('payload_sha256',''))):
        raise ValueError('ARCHIVE_OWNER_VERIFICATION_REQUIRED')
    if payload.get('archive_date') != date_token(date):
        raise ValueError('ARCHIVE_EXACT_DATE_MISMATCH')
    articles = payload.get('articles')
    if not isinstance(articles,list):
        raise ValueError('ARCHIVE_ARTICLES_CONTRACT_MISSING')
    out, gaps = [], []
    if len(articles)>MAX_ARTICLES:
        raise ValueError('ARCHIVE_ARTICLE_BOUND_EXCEEDED')
    for article in articles:
        if not isinstance(article,Mapping):
            gaps.append('ARCHIVE_ARTICLE_ID_OR_TITLE_MISSING'); continue
        # The V3.5 archive contract names the human-readable headline
        # ``source_title``.  Accept the generic ``title`` used by newer
        # producers as well, while preserving the original row unchanged.
        article_title = article.get('title') or article.get('source_title')
        if not article.get('article_id') or not isinstance(article_title,str) or not article_title:
            gaps.append('ARCHIVE_ARTICLE_ID_OR_TITLE_MISSING'); continue
        article_id = str(article['article_id'])
        published = article.get('published_at') if timestamp(article.get('published_at')) else None
        retrieved = article.get('retrieved_at') if timestamp(article.get('retrieved_at')) else None
        available = article.get('available_at') if timestamp(article.get('available_at')) else None
        if published is None: gaps.append('ARCHIVE_ARTICLE_PUBLICATION_TIME_MISSING:'+article_id)
        if retrieved is None or available is None: gaps.append('ARCHIVE_ARTICLE_ACQUISITION_TIME_MISSING:'+article_id)
        themes=themes_of(article.get('themes') or article.get('theme'))
        if not themes: gaps.append('ARCHIVE_ARTICLE_STRUCTURED_THEME_MISSING:'+article_id)
        # An archive's research statement is not independently verified raw fact.
        # The full original row remains inspectable; source_kind is not a truth gate.
        out.append(dict(material_id=digest([binding['payload_path'],binding['payload_sha256'],article_id]),
            original_article_id=article_id,title=article_title,themes=themes,claim_type='RESEARCH_OPINION',
            source_kind=article.get('source_type','UNKNOWN'),source_market=article.get('market','UNKNOWN'),
            source_url=article.get('source_url') or article.get('url'),
            published_at=published,published_date=timestamp(published).date().isoformat() if published else None,
            retrieved_at=retrieved,available_at=available,
            collected_at=article.get('collected_at') if timestamp(article.get('collected_at')) else None,
            first_seen_at=article.get('first_seen_at') if timestamp(article.get('first_seen_at')) else None,
            archive_recorded_at=payload.get('source_generated_at'),
            archive_date=date,verification='OWNER_VERIFIED',source_refs=[deepcopy(dict(binding))],
            source_row=deepcopy(dict(article)),fresh_catalyst_eligible=False,
            identity_status='HK_IDENTITY_AND_CONNECT_NOT_VERIFIED'))
    return out,gaps


def project_vibe_snapshot(payload: Mapping[str, Any], binding: Mapping[str, Any]) -> list[dict]:
    """Read the actual theme_tree shape; A-share members remain context only.

    Vibe's news.text is an aggregate search response, not a publication sidecar.
    Never split it into fabricated articles or infer publication times from it.
    """
    if binding.get('status')!='VERIFIED':
        raise ValueError('VIBE_OWNER_VERIFICATION_REQUIRED')
    sources=payload.get('sources',{})
    values=payload.get('functions',{}).get('get_market_facts')
    if (not isinstance(values,(list,tuple)) or len(values)!=2 or not isinstance(values[1],Mapping)
            or sources.get('market_facts.theme_tree',{}).get('status')!='READY'):
        return []
    tree=values[1].get('theme_tree',{})
    if tree.get('available') is not True:
        return []
    out=[]
    for row in tree.get('themes',[]):
        if not isinstance(row,Mapping) or not row.get('tag'):
            continue
        tag=str(row['tag'])
        out.append(dict(material_id=digest([binding.get('payload_sha256'),tag]),
            title=f"Vibe题材复盘：{tag}（{row.get('state','状态未提供')}）",themes=themes_of([tag]),
            claim_type='AGGREGATED_REVIEW_CONTEXT',source_kind='VIBE_VERIFIED_INPUT',source_market='A_SHARE',
            published_at=None,published_date=None,retrieved_at=None,available_at=None,
            archive_date=str(payload['trade_date']).replace('-',''),archive_recorded_at=payload.get('data_as_of'),
            verification='OWNER_VERIFIED',source_refs=[deepcopy(dict(binding))],source_row=deepcopy(dict(row)),
            fresh_catalyst_eligible=False,identity_status='A_SHARE_CONTEXT_ONLY_NOT_HK_CANDIDATES'))
    return out


def _read_archive(source: Any, date: str, slot: str) -> tuple[list[dict],list[str],dict | None]:
    # Use the very same existing store and manifest/receipt validation as the
    # research lane; no per-symbol filter and no latest fallback.
    if slot:
        payload=source.hourly_store.read_exact(date,slot,mode='LIVE')
    else:
        payload=source.store.read_exact(date)
    if payload is None:
        return [],[],None
    binding=source.artifact_binding(date,slot=slot,mode='LIVE')
    from infrastructure.data_store import _sha256
    if _sha256(payload)!=binding.get('payload_sha256'):
        raise ValueError('ARCHIVE_CHANGED_DURING_READ')
    count('archive_payload_serialized_bytes', len(json.dumps(payload, ensure_ascii=False).encode()))
    count('archive_article_rows', len(payload.get('articles', [])))
    materials,gaps=project_archive(payload,binding,date)
    return materials,gaps,binding


def _read_vibe(config: Mapping[str, Any], date: str) -> tuple[list[dict],dict]:
    from infrastructure.owned_io import SafeRoot
    from domains.research_review_generation._snapshot import ReviewSnapshot
    from domains.research_review_generation._evidence import verify_evidence, read_bound
    from domains.research_review_generation.owned_runtime import verify_owned_sources
    from domains.research_review_generation.generation import _assert_research_flags
    if config.get('schema_version')!='v4.manager_existing_vibe_binding.v1':
        raise ValueError('VIBE_EXPLICIT_BINDING_SCHEMA_INVALID')
    root=Path(str(config.get('state_root',''))).expanduser()
    if not root.is_absolute() or '..' in root.parts:
        raise ValueError('VIBE_ABSOLUTE_OWNED_STATE_ROOT_REQUIRED')
    implementation=config.get('implementation_manifest_sha256')
    expected=config.get('input_sha256_by_date',{}).get(date)
    if not re.fullmatch(r'[0-9a-f]{64}',str(expected or '')):
        raise ValueError('VIBE_EXACT_INPUT_SHA_NOT_BOUND:'+date)
    verify_owned_sources(implementation)
    iso=datetime.strptime(date,'%Y%m%d').date().isoformat()
    path=f'inputs/{iso}.json'
    io=SafeRoot(root)
    raw=io.read_bytes(path,max_bytes=64*1024*1024)
    if hashlib.sha256(raw).hexdigest()!=expected:
        raise ValueError('VIBE_INPUT_SHA_CHANGED')
    payload=json.loads(raw); _assert_research_flags(payload)
    ReviewSnapshot(payload,iso)
    receipt,_=read_bound(io,payload.get('authority_receipt'),prefixes=('receipts/',))
    verification=verify_evidence(state_root=root,payload=payload,implementation_sha256=implementation,
                                 reflection_manifest=receipt.get('reflection_manifest',[]))
    binding=dict(status='VERIFIED',owner=payload['authority_id'],payload_path=path,payload_sha256=expected,
                 receipt_sha256=payload['authority_receipt_sha256'],verification=verification)
    return project_vibe_snapshot(payload,binding),binding


def _read_vibe_radar_snapshot(config: Mapping[str, Any], date: str) -> tuple[list[dict], dict]:
    """Read one explicitly bound response from Vibe's existing RSS producer.

    This is a read-only adapter for the saved POST response. It never calls
    Vibe, never derives article publication time from display fields, and is
    independently optional alongside the legacy aggregated-review input.
    """
    # New captures are indexed by their exact plan trade date. Keep the legacy
    # single entry readable only while no dated map exists; once the map is
    # present, a missing date is explicitly NOT_APPLICABLE and never falls
    # back to yesterday's material.
    snapshots = config.get('radar_snapshots_by_plan_date')
    if snapshots is not None and not isinstance(snapshots, Mapping):
        raise ValueError('VIBE_RADAR_SNAPSHOT_DATE_MAP_INVALID')
    if isinstance(snapshots, Mapping):
        binding = snapshots.get(date)
        if binding is None:
            return [], dict(status='NOT_APPLICABLE', material_count=0, plan_trade_date=date)
    else:
        binding = config.get('radar_snapshot')
    if not isinstance(binding, Mapping):
        return [], dict(status='NOT_CONFIGURED', material_count=0)
    if binding.get('schema_version') != 'v4.manager_vibe_radar_snapshot_binding.v1':
        raise ValueError('VIBE_RADAR_SNAPSHOT_SCHEMA_INVALID')
    if binding.get('plan_trade_date') != date:
        return [], dict(status='NOT_APPLICABLE', material_count=0,
                         plan_trade_date=date)

    evidence_root = Path(str(binding.get('evidence_root', ''))).expanduser()
    provider_root = Path(str(binding.get('provider_root', ''))).expanduser()
    if not evidence_root.is_absolute() or not provider_root.is_absolute() or '..' in evidence_root.parts or '..' in provider_root.parts:
        raise ValueError('VIBE_RADAR_ABSOLUTE_ROOTS_REQUIRED')

    def read_bounded(root: Path, relative: Any, limit: int, code: str) -> tuple[bytes, Path]:
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise ValueError(code + '_PATH_INVALID')
        base = root.resolve(strict=True)
        path = (base / relative).resolve(strict=True)
        if base not in path.parents or not path.is_file():
            raise ValueError(code + '_PATH_OUTSIDE_ROOT')
        raw = path.read_bytes()
        if len(raw) > limit:
            raise ValueError(code + '_SIZE_BOUND_EXCEEDED')
        return raw, path

    response_raw, response_path = read_bounded(evidence_root, binding.get('response_path'), 16 * 1024 * 1024,
                                                'VIBE_RADAR_RESPONSE')
    response_sha = hashlib.sha256(response_raw).hexdigest()
    expected_response_sha = str(binding.get('response_sha256', ''))
    if (not re.fullmatch(r'[0-9a-f]{64}', expected_response_sha)
            or response_sha != expected_response_sha
            or len(response_raw) != binding.get('response_bytes')):
        raise ValueError('VIBE_RADAR_RESPONSE_IDENTITY_MISMATCH')

    receipt_raw, receipt_path = read_bounded(evidence_root, binding.get('capture_receipt_path'), 1024 * 1024,
                                              'VIBE_RADAR_CAPTURE_RECEIPT')
    receipt_sha = hashlib.sha256(receipt_raw).hexdigest()
    expected_receipt_sha = str(binding.get('capture_receipt_sha256', ''))
    if not re.fullmatch(r'[0-9a-f]{64}', expected_receipt_sha) or receipt_sha != expected_receipt_sha:
        raise ValueError('VIBE_RADAR_CAPTURE_RECEIPT_SHA_MISMATCH')

    receipt = json.loads(receipt_raw)
    payload = json.loads(response_raw)
    if not isinstance(receipt, Mapping) or not isinstance(payload, Mapping):
        raise ValueError('VIBE_RADAR_RESPONSE_OR_RECEIPT_INVALID')
    if (receipt.get('url') != 'http://127.0.0.1:8910/api/radar/refresh'
            or receipt.get('method') != 'POST'
            or receipt.get('producer') != 'existing Vibe newsradar.fetch_radar'
            or receipt.get('status') != 'RESPONSE_SAVED'
            or receipt.get('http_status') != 200):
        raise ValueError('VIBE_RADAR_REFRESH_RECEIPT_NOT_SUCCESSFUL')
    if (receipt.get('sha256') != response_sha or receipt.get('bytes') != len(response_raw)
            or receipt.get('article_count') != binding.get('raw_article_count')):
        raise ValueError('VIBE_RADAR_RECEIPT_RESPONSE_IDENTITY_MISMATCH')

    available_at = receipt.get('finished_at')
    available = timestamp(available_at)
    if available is None or available.utcoffset() is None:
        raise ValueError('VIBE_RADAR_CAPTURE_FINISH_TIME_INVALID')
    snapshot_date = available.strftime('%Y%m%d')
    if (snapshot_date != binding.get('snapshot_date')
            or available_at != binding.get('available_at')
            or receipt.get('generated_at') != binding.get('generated_at')
            or str(receipt.get('generated_at', '')).replace('-', '')[:8] != snapshot_date):
        raise ValueError('VIBE_RADAR_CAPTURE_DATE_MISMATCH')

    provider_files = binding.get('provider_source_sha256')
    if not isinstance(provider_files, Mapping) or not provider_files:
        raise ValueError('VIBE_RADAR_PROVIDER_IDENTITY_MISSING')
    provider_refs = []
    for relative, expected_sha in sorted(provider_files.items()):
        if not re.fullmatch(r'[0-9a-f]{64}', str(expected_sha or '')):
            raise ValueError('VIBE_RADAR_PROVIDER_SHA_INVALID')
        source_raw, source_path = read_bounded(provider_root, relative, 2 * 1024 * 1024,
                                                'VIBE_RADAR_PROVIDER_SOURCE')
        actual_sha = hashlib.sha256(source_raw).hexdigest()
        if actual_sha != expected_sha:
            raise ValueError('VIBE_RADAR_PROVIDER_SOURCE_SHA_MISMATCH')
        provider_refs.append(dict(path=relative, sha256=actual_sha))

    data = payload.get('data')
    if not isinstance(data, Mapping) or not isinstance(data.get('industries'), list):
        raise ValueError('VIBE_RADAR_RESPONSE_SHAPE_INVALID')
    if data.get('generated_at') != receipt.get('generated_at'):
        raise ValueError('VIBE_RADAR_GENERATED_AT_MISMATCH')
    raw_article_count = 0
    out: list[dict] = []
    seen: dict[str, tuple[str, str, str]] = {}
    for industry in data['industries']:
        if not isinstance(industry, Mapping) or not isinstance(industry.get('items'), list):
            raise ValueError('VIBE_RADAR_INDUSTRY_SHAPE_INVALID')
        industry_key = str(industry.get('key') or '')
        industry_name = str(industry.get('name') or '')
        for item in industry['items']:
            raw_article_count += 1
            if not isinstance(item, Mapping):
                continue
            item_id = item.get('item_id')
            title = item.get('original_title') or item.get('title')
            url = item.get('url')
            source = item.get('source')
            if (not isinstance(item_id, str) or not item_id.strip()
                    or not isinstance(title, str) or not title.strip()
                    or not isinstance(url, str) or not url.startswith(('http://', 'https://'))
                    or not isinstance(source, str) or not source.strip()):
                continue
            identity = (title, url, source)
            prior = seen.get(item_id)
            if prior is not None:
                if prior != identity:
                    raise ValueError('VIBE_RADAR_ITEM_ID_COLLISION')
                continue
            seen[item_id] = identity
            ref = dict(schema_version=binding['schema_version'], response_path=str(response_path),
                       response_sha256=response_sha, response_bytes=len(response_raw),
                       capture_receipt_path=str(receipt_path), capture_receipt_sha256=receipt_sha,
                       capture_finished_at=available_at, producer=receipt['producer'],
                       provider_sources=provider_refs, item_id=item_id, industry_key=industry_key)
            out.append(dict(
                material_id=digest(['vibe_radar', response_sha, item_id]),
                original_article_id=item_id,
                title=title.strip(), summary=item.get('summary') if isinstance(item.get('summary'), str) else None,
                themes=[], claim_type='NEWS_ARTICLE_OBSERVATION', source_kind='VIBE_EXISTING_RSS_SNAPSHOT',
                source_market='MULTI_MARKET_NEWS', source_url=url, source_name=source,
                published_at=None, published_date=None, publication_status='PUBLICATION_UNKNOWN',
                retrieved_at=available_at, available_at=available_at, collected_at=None,
                first_seen_at=None, snapshot_generated_at=data.get('generated_at'), snapshot_date=snapshot_date,
                industry_key=industry_key, industry_name=industry_name,
                verification='OWNER_VERIFIED', verification_basis='BOUND_RESPONSE_AND_CAPTURE_RECEIPT',
                source_refs=[ref],
                source_row=deepcopy(dict(item)), fresh_catalyst_eligible=False,
                identity_status='ISSUER_UNMAPPED_HK_MAPPING_UNVERIFIED'))
    if raw_article_count != binding.get('raw_article_count') or raw_article_count != receipt.get('article_count'):
        raise ValueError('VIBE_RADAR_ARTICLE_COUNT_MISMATCH')
    stats = data.get('stats')
    if not isinstance(stats, Mapping) or stats.get('industries') != len(data['industries']):
        raise ValueError('VIBE_RADAR_STATS_MISMATCH')
    if receipt.get('stats') != stats:
        raise ValueError('VIBE_RADAR_RECEIPT_STATS_MISMATCH')
    result_binding = dict(status='VERIFIED', source_contract='EXISTING_VIBE_RSS_RESPONSE_READ_ONLY',
                          plan_trade_date=date, snapshot_date=snapshot_date, response_path=str(response_path),
                          response_sha256=response_sha, response_bytes=len(response_raw),
                          capture_receipt_path=str(receipt_path), capture_receipt_sha256=receipt_sha,
                          available_at=available_at, raw_article_count=raw_article_count,
                          deduplicated_article_count=len(out), provider_sources=provider_refs)
    return out, result_binding


def _vibe_a_share_session_scope(source_dates: list[str]) -> dict[str, Any]:
    """Limit the A-share-only Vibe binding to dates known by its calendar."""
    dates = [str(day) for day in source_dates]
    try:
        from contracts.trading_calendar import (
            CALENDAR_PATH,
            TradingDayState,
            load_market_calendar,
            resolve_market_states,
        )

        calendar = load_market_calendar()
        calendar_sha256 = hashlib.sha256(CALENDAR_PATH.read_bytes()).hexdigest()
    except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError):
        return dict(
            session_dates=[],
            excluded_dates=[],
            unknown_calendar_dates=dates,
            calendar_status='CANNOT_CONFIRM',
            calendar_sha256=None,
        )

    sessions, excluded, unknown = [], [], []
    for day in dates:
        try:
            state = resolve_market_states(calendar, day)['a_share']
        except (ValueError, TypeError, KeyError, RuntimeError):
            state = TradingDayState.UNKNOWN
        if state in {TradingDayState.FULL_TRADING_DAY, TradingDayState.HALF_TRADING_DAY_AM}:
            sessions.append(day)
        elif state == TradingDayState.NON_TRADING_DAY:
            excluded.append(day)
        else:
            unknown.append(day)
    return dict(
        session_dates=sessions,
        excluded_dates=excluded,
        unknown_calendar_dates=unknown,
        calendar_status='VERIFIED' if not unknown else 'PARTIAL',
        calendar_sha256=calendar_sha256,
    )


def read_existing_materials(date: str, *, research_source: Any = None,
                            vibe_binding: Mapping[str, Any] | None = None,
                            context: Mapping[str, Any] | None = None) -> dict:
    date=date_token(date)
    from .workspace_plan import plan_context, temporal_role
    context = dict(context) if context is not None else plan_context(date)
    if context.get('plan_trade_date') != date:
        raise ValueError('MATERIAL_PLAN_CONTEXT_TARGET_MISMATCH')
    dates=list(context['source_dates'])
    materials,bindings,gaps=[],[],[]
    attempted=0
    if research_source is None:
        gaps.append('RESEARCH_ARCHIVE_READER_NOT_BOUND')
    else:
        for day in dates:
            checkpoint()
            try:
                slots=research_source.hourly_store.list_slots(day,mode='LIVE')
                if not isinstance(slots,list) or any(not re.fullmatch(r'\d{4}',str(s)) for s in slots):
                    raise ValueError('ARCHIVE_SLOT_LIST_INVALID')
            except (ImportError,OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
                gaps.append('RESEARCH_SLOT_READ_FAILED:'+day+':'+type(exc).__name__); slots=[]
            for slot in ['',*slots]:
                checkpoint()
                if attempted>=MAX_ARTIFACTS:
                    gaps.append('EXISTING_ARCHIVE_SCAN_BOUND_REACHED'); break
                attempted+=1
                try:
                    with phase('archive_original_read_and_validation'):
                        rows,missing,binding=_read_archive(research_source,day,slot)
                    materials.extend(rows); gaps.extend(missing)
                    if binding: bindings.append(binding)
                except (ImportError,OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
                    # One bad artifact cannot erase other verified independent inputs.
                    gaps.append('RESEARCH_ARTIFACT_READ_FAILED:'+day+':'+(slot or 'daily')+':'+type(exc).__name__)
        if not bindings:
            gaps.append('NO_VERIFIED_RESEARCH_ARCHIVE_IN_EXACT_WINDOW')
    from .vibe_binding_preflight import preflight_vibe_binding, finalize_vibe_preflight
    vibe_scope = _vibe_a_share_session_scope(dates)
    vibe_dates = vibe_scope['session_dates']
    vibe_preflight = preflight_vibe_binding(vibe_binding, vibe_dates)
    vibe_preflight.update(
        market_scope='A_SHARE_ONLY',
        calendar_owner='contracts.trading_calendar / a_share',
        calendar_status=vibe_scope['calendar_status'],
        calendar_sha256=vibe_scope['calendar_sha256'],
        a_share_session_dates=vibe_dates,
        excluded_dates=vibe_scope['excluded_dates'],
        unknown_calendar_dates=vibe_scope['unknown_calendar_dates'],
    )
    vibe_verified_dates: list[str] = []
    vibe_failed_dates: list[str] = []
    vibe_rows_by_date: dict[str, list[dict]] = {}
    if vibe_binding is None:
        gaps.append('VIBE_OWNER_INPUT_BINDING_NOT_CONFIGURED')
    else:
        for day in vibe_dates:
            attempted+=1
            try:
                with phase('vibe_original_read_and_validation'):
                    rows,binding=_read_vibe(vibe_binding,day)
                rows=list(rows)
                vibe_rows_by_date[day]=rows
                materials.extend(rows);bindings.append(binding);vibe_verified_dates.append(day)
                # Existing aggregate contract cannot certify article publication/PIT.
                gaps.append('VIBE_AGGREGATE_NOT_ARTICLE_PUBLICATION_EVIDENCE:'+day)
            except (ImportError,OSError,ValueError,TypeError,KeyError,RuntimeError) as exc:
                vibe_failed_dates.append(day)
                gaps.append('VIBE_INPUT_READ_FAILED:'+day+':'+str(exc)[:160])
    vibe_preflight = finalize_vibe_preflight(vibe_preflight, verified_dates=vibe_verified_dates, failed_dates=vibe_failed_dates)
    for day in vibe_scope['unknown_calendar_dates']:
        marker = 'VIBE_A_SHARE_CALENDAR_UNKNOWN:'+day
        gaps.append(marker)
        vibe_preflight['gaps'] = sorted(set(list(vibe_preflight.get('gaps') or []) + [marker]))
    if not vibe_dates:
        gaps.append('VIBE_A_SHARE_SESSION_WINDOW_EMPTY')
        vibe_preflight['status'] = 'CANNOT_CONFIRM'
        vibe_preflight['gaps'] = sorted(set(list(vibe_preflight.get('gaps') or []) + ['VIBE_A_SHARE_SESSION_WINDOW_EMPTY']))
    elif vibe_scope['unknown_calendar_dates']:
        if vibe_preflight.get('status') == 'READY_A_SHARE_CONTEXT_ONLY':
            vibe_preflight['status'] = 'PARTIAL_A_SHARE_CONTEXT_ONLY'

    vibe_radar_snapshot: dict[str, Any] = dict(status='NOT_CONFIGURED', projected_material_count=0,
                                               included_material_count=0, excluded_after_cutoff_count=0)
    radar_material_count = 0
    if (isinstance(vibe_binding, Mapping)
            and (vibe_binding.get('radar_snapshot') is not None
                 or vibe_binding.get('radar_snapshots_by_plan_date') is not None)):
        try:
            with phase('vibe_radar_snapshot_read_and_validation'):
                radar_rows, radar_binding = _read_vibe_radar_snapshot(vibe_binding, date)
            radar_material_count = len(radar_rows)
            materials.extend(radar_rows)
            if radar_binding.get('status') == 'VERIFIED':
                bindings.append(radar_binding)
            vibe_radar_snapshot = {**radar_binding, 'projected_material_count': radar_material_count}
        except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
            vibe_radar_snapshot = dict(status='FAILED', projected_material_count=0,
                                       included_material_count=0, excluded_after_cutoff_count=0,
                                       gap='VIBE_RADAR_SNAPSHOT_READ_FAILED:'+str(exc)[:160])
            gaps.append(vibe_radar_snapshot['gap'])
    vibe_projection_counts: dict[str, dict[str, int]] = {}
    vibe_projection_empty_dates: list[str] = []
    vibe_empty_dates: list[str] = []
    vibe_context_dates: list[str] = []
    vibe_material_count = 0
    for day in vibe_verified_dates:
        projected = vibe_rows_by_date.get(day, [])
        usable = [material for material in projected
                  if temporal_role(material, context) != 'AFTER_CUTOFF_EXCLUDED']
        projected_count = len(projected)
        usable_count = len(usable)
        vibe_projection_counts[day] = {
            'projected': projected_count,
            'usable_after_temporal_filter': usable_count,
        }
        vibe_material_count += usable_count
        if projected_count == 0:
            vibe_projection_empty_dates.append(day)
            marker = 'VIBE_VERIFIED_INPUT_HAS_NO_USABLE_THEME_ROWS:'+day
            gaps.append(marker)
            vibe_preflight['gaps'] = sorted(set(list(vibe_preflight.get('gaps') or []) + [marker]))
        if usable_count == 0:
            vibe_empty_dates.append(day)
            if projected_count:
                marker = 'VIBE_CONTEXT_EMPTY_AFTER_TEMPORAL_FILTER:'+day
                gaps.append(marker)
                vibe_preflight['gaps'] = sorted(set(list(vibe_preflight.get('gaps') or []) + [marker]))
        else:
            vibe_context_dates.append(day)

    if vibe_binding is None:
        owner_verification_status = 'NOT_CONFIGURED'
    elif not vibe_dates:
        owner_verification_status = 'NOT_RUN'
    elif len(vibe_verified_dates) == len(vibe_dates) and not vibe_failed_dates:
        owner_verification_status = 'VERIFIED'
    elif vibe_verified_dates:
        owner_verification_status = 'PARTIAL'
    elif vibe_failed_dates:
        owner_verification_status = 'FAILED'
    else:
        owner_verification_status = 'NOT_RUN'

    if vibe_verified_dates and vibe_material_count == 0:
        vibe_preflight['status'] = 'CANNOT_CONFIRM'
        availability_reason = '来源已校验，但暂无可用的主题资料'
    elif vibe_material_count and (vibe_empty_dates or vibe_failed_dates or vibe_scope['unknown_calendar_dates']):
        vibe_preflight['status'] = 'PARTIAL_A_SHARE_CONTEXT_ONLY'
        availability_reason = '来源已校验，部分日期存在可用的主题资料'
    elif vibe_material_count:
        vibe_preflight['status'] = 'READY_A_SHARE_CONTEXT_ONLY'
        availability_reason = '来源已校验，存在可用的主题资料'
    else:
        availability_reason = None
    vibe_preflight.update(
        owner_verification_status=owner_verification_status,
        usable_context_available=bool(vibe_material_count),
        projected_material_count=sum(counts['projected'] for counts in vibe_projection_counts.values()),
        material_count=vibe_material_count,
        projection_counts_by_date=vibe_projection_counts,
        context_dates=vibe_context_dates,
        empty_dates=vibe_empty_dates,
        projection_empty_dates=vibe_projection_empty_dates,
        availability_reason=availability_reason,
    )
    excluded=[m for m in materials if temporal_role(m,context)=='AFTER_CUTOFF_EXCLUDED']
    excluded_radar_count=sum(1 for material in excluded
                             if material.get('claim_type')=='NEWS_ARTICLE_OBSERVATION'
                             and material.get('source_kind')=='VIBE_EXISTING_RSS_SNAPSHOT')
    materials=[{**m,'temporal_role':temporal_role(m,context)} for m in materials if temporal_role(m,context)!='AFTER_CUTOFF_EXCLUDED']
    if excluded:gaps.append('MATERIAL_RECORDS_AFTER_ACTUAL_CUTOFF_EXCLUDED:'+str(len(excluded)))
    vibe_radar_snapshot.update(
        included_material_count=radar_material_count-excluded_radar_count,
        excluded_after_cutoff_count=excluded_radar_count,
        network_requests=0,
    )
    return dict(materials=materials,input_bindings=bindings,gaps=sorted(set(gaps)),plan_context=dict(context),
                coverage=dict(window_dates=dates,attempted_artifact_count=attempted,
                              verified_artifact_count=len(bindings),material_count=len(materials),
                              global_market_coverage='NOT_ESTABLISHED',vibe_binding=vibe_preflight,excluded_after_cutoff_count=len(excluded),
                              vibe_radar_snapshot=vibe_radar_snapshot,
                              plan_trade_date=date,research_cutoff=context['research_cutoff'],market_session=context['market_session']))
