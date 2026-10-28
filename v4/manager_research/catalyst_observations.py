"""Independent observation projection inside the existing manager material owner.

No Stage, quote, daily-price, BUY, network, or scheduler dependency. An explicit
owner admission stores reviewed source bytes in MaterialStore; GET re-reads the
bytes and re-projects the committed input set. A hash inside an output is never
accepted as evidence of an input. Supplemental research can NEVER assert that
an event was captured by the live system at the historical target time.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .contracts import canonical_json, sha256_json, strict_trade_date
from .materials import MaterialStore
from .store import ManagerResearchStore
from infrastructure.owned_io import SafeRoot

SCHEMA = 'v4.manager_research.catalyst_observations.v1'
ADMISSION = 'v4.manager_research.catalyst_admission.v1'
RECEIPT = 'v4.manager_research.catalyst_admission_receipt.v1'
FLAGS = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)
HK = ZoneInfo('Asia/Hong_Kong')
HEX = re.compile(r'^[0-9a-f]{64}$')
SYMBOL = re.compile(r'^HK\.[0-9]{5}$')


class CatalystIntegrityError(ValueError):
    """A source/publication binding failed; return no cards."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> datetime:
    if not isinstance(value, str):
        raise CatalystIntegrityError('CATALYST_TIME_MISSING')
    try:
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError as exc:
        raise CatalystIntegrityError('CATALYST_TIME_INVALID') from exc
    if value.tzinfo is None:
        raise CatalystIntegrityError('CATALYST_TIMEZONE_MISSING')
    return value


def _text(value: Any, *, limit: int = 4000) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise CatalystIntegrityError('CATALYST_TEXT_INVALID')
    return value.strip()


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _news_binding(path: Path, data_root: Path) -> dict[str, Any]:
    """Freeze one scanned owner artifact, including an absent publication.

    The hourly owner can retain historical archives that predate publication
    attestations.  Those files still belong to the requested source window:
    their absence is a typed coverage gap, not permission to drop them from
    the replay set.  ``None`` is therefore an explicit, hash-bound
    publication absence; it is never treated as a positive event binding.
    """
    from infrastructure.manager_input_attestation import resolve
    relative = path.absolute().relative_to(data_root.absolute()).as_posix()
    path = resolve(data_root, relative)
    sidecar = Path(str(path) + '.publication.json')
    return {
        'kind': 'HOURLY_NEWS',
        'artifact_ref': relative,
        'artifact_sha256': _sha(path.read_bytes()),
        'publication_sha256': _sha(sidecar.read_bytes()) if sidecar.is_file() else None,
    }


def _url(value: Any) -> str:
    value = _text(value, limit=4096)
    parsed = urlsplit(value)
    if parsed.scheme not in {'https', 'http'} or not parsed.hostname or parsed.username or parsed.password or any(ord(c) < 32 for c in value):
        raise CatalystIntegrityError('CATALYST_URL_INVALID')
    return value


def _cutoff(date: str) -> datetime:
    # Full HK session context, not a fabricated 15:30 capture. Unknown/day-only
    # publication times cannot prove intraday availability.
    return datetime.combine(datetime.strptime(date, '%Y%m%d').date(), time(16, 10), HK)


def _empty(date: str, status: str = 'NOT_MATERIALIZED') -> dict:
    return dict(schema_version=SCHEMA, kind='CATALYST_RESEARCH_OBSERVATIONS', target_trade_date=date,
                status=status, cards=[], gaps=[], can_refresh=True, stage_dependency=False,
                quote_dependency=False, input_bindings=[], generated_at=None, **FLAGS)


def _checked_bundle(value: Any, texts: Mapping[str, str], *, now: datetime) -> dict:
    if not isinstance(value, dict) or value.get('schema_version') != ADMISSION or value.get('research_kind') != 'POST_HOC_RESEARCH':
        raise CatalystIntegrityError('CATALYST_ADMISSION_SCHEMA')
    strict_trade_date(value.get('target_trade_date'))
    _text(value.get('researcher'), limit=200)
    sources, events = value.get('sources'), value.get('events')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 32 or not isinstance(events, list) or not 1 <= len(events) <= 64:
        raise CatalystIntegrityError('CATALYST_ADMISSION_BOUNDS')
    source_ids = set()
    for src in sources:
        sid = _text(src.get('source_id'), limit=100)
        if sid in source_ids or sid not in texts:
            raise CatalystIntegrityError('CATALYST_SOURCE_ID')
        source_ids.add(sid)
        _url(src.get('url'))
        if src.get('representation') not in {'VERIFIED_WEB_EXCERPT', 'RAW_HTTP_BODY'}:
            raise CatalystIntegrityError('CATALYST_SOURCE_REPRESENTATION')
        if _aware(src.get('retrieved_at')) > now or not HEX.fullmatch(str(src.get('sha256', ''))):
            raise CatalystIntegrityError('CATALYST_SOURCE_TIME_OR_HASH')
        _text(src.get('retrieval_method'), limit=100)
        _text(src.get('verification_reference'), limit=500)

    def quote(sid: Any, q: Any) -> str:
        q = _text(q)
        if sid not in texts or q not in texts[sid]:
            raise CatalystIntegrityError('CATALYST_QUOTE_NOT_IN_SOURCE')
        return q

    keys = set()
    for event in events:
        key = _text(event.get('event_key'), limit=150)
        if key in keys:
            raise CatalystIntegrityError('CATALYST_DUPLICATE_EVENT')
        keys.add(key)
        _text(event.get('title'), limit=240)
        pd = datetime.strptime(event.get('published_date', ''), '%Y-%m-%d').date()
        if pd > now.astimezone(HK).date():
            raise CatalystIntegrityError('CATALYST_FUTURE_EVENT')
        at = event.get('published_at')
        if at is not None:
            if event.get('time_precision') not in {'SECOND', 'MINUTE'} or _aware(at) > now or _aware(at).astimezone(HK).date() != pd:
                raise CatalystIntegrityError('CATALYST_EVENT_TIME')
            if event['time_precision'] == 'MINUTE' and (_aware(at).second or _aware(at).microsecond):
                raise CatalystIntegrityError('CATALYST_MINUTE_PRECISION_INVALID')
        elif event.get('time_precision') != 'DAY':
            raise CatalystIntegrityError('CATALYST_EVENT_PRECISION')
        if event.get('event_nature') not in {'OFFICIAL_PUBLICATION', 'MEDIA_REPORT'}:
            raise CatalystIntegrityError('CATALYST_EVENT_NATURE')
        quote(event.get('source_id'), event.get('evidence_quote'))
        themes = event.get('themes')
        if not isinstance(themes, list) or not themes or len(themes) > 8 or any(not isinstance(t, str) or not t or len(t) > 80 for t in themes):
            raise CatalystIntegrityError('CATALYST_THEMES')
        mappings = event.get('mappings', [])
        if not isinstance(mappings, list) or len(mappings) > 64:
            raise CatalystIntegrityError('CATALYST_MAPPING_BOUNDS')
        mapped = set()
        for rel in mappings:
            symbol = rel.get('symbol', '')
            if not isinstance(symbol, str) or not SYMBOL.fullmatch(symbol) or symbol in mapped:
                raise CatalystIntegrityError('CATALYST_SECURITY_ID')
            mapped.add(symbol)
            name = _text(rel.get('name'), limit=120)
            iq = quote(rel.get('identity_source_id'), rel.get('identity_quote'))
            if name not in iq or re.search(r'(?<!\d)0*' + str(int(symbol[3:])) + r'(?!\d)', iq) is None:
                raise CatalystIntegrityError('CATALYST_ISSUER_IDENTITY_NOT_BOUND')
            quote(rel.get('relation_source_id'), rel.get('relation_quote'))
            _text(rel.get('rationale'), limit=1000)
            if rel.get('relationship_type') not in {'DIRECT', 'INDUSTRY_INFERENCE'}:
                raise CatalystIntegrityError('CATALYST_RELATION_TYPE')
            if rel['relationship_type'] == 'DIRECT' and name not in event['evidence_quote']:
                raise CatalystIntegrityError('CATALYST_DIRECT_ENTITY_NOT_IN_EVENT')
    canonical_json(value)
    return value


def admit(store: ManagerResearchStore, materials: MaterialStore | None, bundle_path: Path, *, expected_sha256: str) -> dict:
    """Explicit server-side/local-owner import. Browser routes cannot call this."""
    if materials is None or not HEX.fullmatch(expected_sha256):
        raise CatalystIntegrityError('CATALYST_OWNER_OR_EXPECTED_SHA_MISSING')
    path = Path(bundle_path).absolute()
    io = SafeRoot(path.parent)
    raw = io.read_bytes(path.name)
    if len(raw) > 2_000_000 or _sha(raw) != expected_sha256:
        raise CatalystIntegrityError('CATALYST_BUNDLE_SHA_MISMATCH')
    value = json.loads(raw)
    contents = {}
    texts = {}
    for src in value.get('sources', []):
        body = io.read_bytes(src['path'])  # existing owned I/O rejects traversal and symlinks
        if not 0 < len(body) <= 2_000_000 or _sha(body) != src.get('sha256'):
            raise CatalystIntegrityError('CATALYST_SOURCE_SHA_MISMATCH')
        contents[src['source_id']] = body
        texts[src['source_id']] = body.decode('utf-8')
    now = _now()
    value = _checked_bundle(value, texts, now=now)
    date = value['target_trade_date']
    ref = f'catalyst_admissions/{date}/{expected_sha256}'
    with store._transaction(date, 'catalyst-admission'):
        prior = store._read(store.root / (ref + '.receipt.json'))
        if prior is not None:
            _read_admission(store, materials, {'bundle_sha256': expected_sha256}, date, now)
            return prior
        # Save through the shared MaterialStore. A unique immutable source key
        # prevents one admission from silently replacing another's provenance.
        for src in value['sources']:
            body = contents[src['source_id']]
            material = materials.fetch('catalyst:' + expected_sha256 + ':' + src['source_id'], url=src['url'], ttl_seconds=None,
                transport=lambda _url, b=body, s=src: {'body': b, 'retrieved_at': s['retrieved_at'], 'content_type': s.get('content_type', 'text/plain; charset=utf-8')})
            if material.sha256 != src['sha256'] or _sha(material.body) != src['sha256']:
                raise CatalystIntegrityError('CATALYST_MATERIAL_CONFLICT')
        store._io.write_bytes(ref + '.bundle.json', raw)
        receipt = dict(schema_version='v4.manager_research.catalyst_admission_receipt.v1', target_trade_date=date,
                       bundle_sha256=expected_sha256, admitted_at=_now().isoformat(), material_owner='v4.manager_research.MaterialStore',
                       research_kind='POST_HOC_RESEARCH', event_count=len(value['events']), **FLAGS)
        store._write_atomic(store.root / (ref + '.receipt.json'), receipt)
    return receipt


def _read_admission(store, materials, binding, date, now):
    sha = binding.get('bundle_sha256', '')
    if not isinstance(sha, str) or not HEX.fullmatch(sha) or materials is None:
        raise CatalystIntegrityError('CATALYST_ADMISSION_BINDING')
    ref = f'catalyst_admissions/{date}/{sha}'
    raw = store._io.read_bytes(ref + '.bundle.json')
    if _sha(raw) != sha:
        raise CatalystIntegrityError('CATALYST_ADMISSION_BYTES_CHANGED')
    receipt_raw = store._io.read_bytes(ref + '.receipt.json')
    receipt = json.loads(receipt_raw)
    if not isinstance(receipt, dict):
        raise CatalystIntegrityError('CATALYST_ADMISSION_RECEIPT_SCHEMA')
    if (
        binding.get('receipt_sha256') not in (None, _sha(receipt_raw))
        or receipt.get('schema_version') != RECEIPT
        or receipt.get('bundle_sha256') != sha
        or receipt.get('target_trade_date') != date
        or receipt.get('material_owner') != 'v4.manager_research.MaterialStore'
        or receipt.get('research_kind') != 'POST_HOC_RESEARCH'
    ):
        raise CatalystIntegrityError('CATALYST_ADMISSION_RECEIPT_CHANGED')
    admitted = _aware(receipt['admitted_at'])
    if admitted > now or any(receipt.get(k) is not v for k, v in FLAGS.items()):
        raise CatalystIntegrityError('CATALYST_ADMISSION_TIME_OR_SAFETY')
    bundle = json.loads(raw)
    if not isinstance(bundle, dict):
        raise CatalystIntegrityError('CATALYST_ADMISSION_SCHEMA')
    if bundle.get('target_trade_date') != date:
        raise CatalystIntegrityError('CATALYST_ADMISSION_DATE')
    texts, sources = {}, {}
    for src in bundle['sources']:
        digest = src.get('sha256', '')
        if not isinstance(digest, str) or not HEX.fullmatch(digest):
            raise CatalystIntegrityError('CATALYST_MATERIAL_SHA_FORMAT')
        body = materials._io.read_bytes('blobs/' + digest)
        if _sha(body) != digest:
            raise CatalystIntegrityError('CATALYST_MATERIAL_BYTES_CHANGED')
        key = 'catalyst:' + sha + ':' + src['source_id']
        index = json.loads(materials._io.read_bytes('index/' + _sha(key.encode()) + '.json'))
        if any(index.get(k) != src.get(k) for k in ('url', 'sha256', 'retrieved_at')) or index.get('source_key') != key:
            raise CatalystIntegrityError('CATALYST_MATERIAL_PROVENANCE_CHANGED')
        if _aware(src['retrieved_at']) > admitted:
            raise CatalystIntegrityError('CATALYST_MATERIAL_AFTER_ADMISSION')
        texts[src['source_id']] = body.decode('utf-8')
        sources[src['source_id']] = {k: src[k] for k in ('source_id', 'url', 'sha256', 'retrieved_at', 'representation', 'retrieval_method', 'verification_reference')}
    bundle = _checked_bundle(bundle, texts, now=now)
    event_count = receipt.get('event_count')
    if isinstance(event_count, bool) or not isinstance(event_count, int) or event_count != len(bundle['events']):
        raise CatalystIntegrityError('CATALYST_ADMISSION_EVENT_COUNT')
    binding = dict(kind='MATERIAL_ADMISSION', bundle_sha256=sha, receipt_sha256=_sha(receipt_raw))
    return bundle, sources, admitted, binding


def _card(event, relation, sources, *, date, available, supplemental, event_id):
    source = sources[event['source_id']]
    at = event.get('published_at')
    published_after = (_aware(at) > _cutoff(date)) if at else event['published_date'].replace('-', '') > date
    category = 'AFTER_CLOSE_RESEARCH' if published_after else ('POST_HOC_RESEARCH' if supplemental or available > _cutoff(date) else 'CAPTURED_AT_TARGET')
    relation_type = relation['relationship_type'] if relation else 'UNMAPPED'
    source_refs = [source]
    if relation:
        source_refs += [sources[s] for s in (relation['identity_source_id'], relation['relation_source_id']) if s in sources]
    return dict(card_id=sha256_json([date, event_id, relation.get('symbol') if relation else None]),
                event_id=event_id, title=event['title'], symbol=relation.get('symbol') if relation else None,
                name=relation.get('name') if relation else ' / '.join(event['themes']), market='HK_LISTED' if relation else 'THEME',
                connect_eligibility='NOT_CHECKED', themes=event['themes'], event_nature=event['event_nature'],
                published_date=event['published_date'], published_at=at, time_precision=event['time_precision'],
                retrieved_at=source['retrieved_at'], available_at=available.isoformat(), source_url=source['url'],
                source_refs=list({s['source_id']: s for s in source_refs}.values()), evidence_quote=event['evidence_quote'],
                relationship_type=relation_type, mapping_reason=relation['rationale'] if relation else '主题事件有来源；个股关系证据尚未绑定，不推断股票代码。',
                relation_quote=relation.get('relation_quote') if relation else None,
                temporal_classification=category, captured_at_target=category == 'CAPTURED_AT_TARGET',
                volume_condition='UNKNOWN', price_position='UNKNOWN', qualified=False,
                research_role='CATALYST_OBSERVATION_ONLY', unknown_conditions=['SAME_TIME_VOLUME_BASELINE_UNVERIFIED', 'HISTORICAL_PRICE_POSITION_UNVERIFIED'], **FLAGS)


def _project_admissions(store, materials, bindings, date, now):
    cards, actual = [], []
    for binding in bindings:
        bundle, sources, available, checked = _read_admission(store, materials, binding, date, now)
        actual.append(checked)
        for event in bundle['events']:
            for relation in event.get('mappings') or [None]:
                cards.append(_card(event, relation, sources, date=date, available=available, supplemental=True,
                                   event_id=sha256_json([checked['bundle_sha256'], event['event_key']])))
    return cards, actual


def _hourly_cards(data_root, owner_root, date, now, *, bindings=None):
    """Reuse the existing attested news reader; unlinked themes stay visible."""
    from domains.manager_catalyst_tracking import read_catalyst_events
    from infrastructure.manager_input_attestation import resolve, digest
    if data_root is None or owner_root is None:
        if bindings:
            raise CatalystIntegrityError('CATALYST_NEWS_OWNER_BINDING_LOST')
        return [], [], ['NEWS_OWNER_BINDING_NOT_CONFIGURED']
    data, owner = Path(data_root).expanduser().resolve(), Path(owner_root).expanduser().resolve()
    if bindings is None:
        paths = []
        day = datetime.strptime(date, '%Y%m%d')
        for offset in range(3):
            directory = resolve(data, 'research/incoming/' + (day - timedelta(days=offset)).strftime('%Y%m%d'))
            if directory.is_dir():
                paths.extend(p for p in sorted(directory.glob('*.json')) if re.fullmatch(r'\d{4}', p.stem))
        paths = paths[:72]
        # Keep every scanned artifact in the replay envelope.  A historical
        # file without a publication sidecar remains a source-derived gap and
        # must not disappear merely because it cannot yield a positive card.
        bound = [_news_binding(path, data) for path in paths]
    else:
        if not isinstance(bindings, list):
            raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
        bound = []
        paths = []
        seen_refs = set()
        for b in bindings:
            if not isinstance(b, dict) or set(b) != {'kind', 'artifact_ref', 'artifact_sha256', 'publication_sha256'}:
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            if b.get('kind') != 'HOURLY_NEWS' or not isinstance(b.get('artifact_ref'), str) or b['artifact_ref'] in seen_refs:
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            if not HEX.fullmatch(str(b.get('artifact_sha256', ''))):
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            publication_sha = b.get('publication_sha256')
            if publication_sha is not None and not HEX.fullmatch(str(publication_sha)):
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            seen_refs.add(b['artifact_ref'])
            try:
                p = resolve(data, b['artifact_ref'])
                raw_sha = digest(p.read_bytes())
            except (OSError, ValueError, TypeError):
                raise CatalystIntegrityError('CATALYST_NEWS_BYTES_CHANGED')
            sidecar = Path(str(p) + '.publication.json')
            current_publication_sha = digest(sidecar.read_bytes()) if sidecar.is_file() else None
            if raw_sha != b['artifact_sha256'] or current_publication_sha != publication_sha:
                raise CatalystIntegrityError('CATALYST_NEWS_BYTES_CHANGED')
            paths.append(p)
            bound.append(dict(b))
    # Empty names intentionally retains verified THEME events without borrowing
    # Stage or inventing issuer codes. Reviewed mappings enter via MaterialStore.
    events, gaps = read_catalyst_events(
        paths,
        as_of=now,
        universe_names={},
        reference_root=data,
        owner_root=owner,
        include_extended_themes=True,
    )
    cards = []
    for event in events:
        url = event.source_url
        if not url:
            gaps.append('NEWS_SOURCE_URL_MISSING:' + event.event_id)
            continue
        try:
            _url(url)
        except ValueError:
            gaps.append('NEWS_SOURCE_URL_INVALID:' + event.event_id)
            continue
        if not event.themes:
            gaps.append('NEWS_THEME_MAPPING_MISSING:' + event.event_id)
            continue
        src = dict(source_id=event.source_ref, url=url, sha256=event.source_sha256, retrieved_at=event.first_seen_at,
                   representation='ATTESTED_HOURLY_ARTIFACT', retrieval_method=event.source_owner,
                   verification_reference=event.publication_ref)
        e = dict(title=event.title, source_id=event.source_ref, published_date=_aware(event.published_at).astimezone(HK).date().isoformat(),
                 published_at=event.published_at, time_precision='SECOND', themes=list(event.themes),
                 event_nature='OWNER_ARCHIVED_EVENT', evidence_quote=event.title)
        cards.append(_card(e, None, {event.source_ref: src}, date=date, available=_aware(event.source_available_at),
                           supplemental=False, event_id=event.event_id))
    if not paths:
        gaps.append('NEWS_ARCHIVE_NOT_PRESENT_FOR_REQUESTED_WINDOW')
    return cards, bound, sorted(set(gaps))


def refresh(store, materials, date, *, data_root=None, owner_root=None, archive_source=None, security_master_root=None):
    date = strict_trade_date(date)
    now = _now()
    if date > now.astimezone(HK).strftime('%Y%m%d'):
        raise CatalystIntegrityError('CATALYST_FUTURE_TARGET')
    with store._transaction(date, 'catalyst-observations'):
        folder = store.root / 'catalyst_admissions' / date
        bindings = []
        if folder.is_dir():
            for p in sorted(folder.glob('*.receipt.json')):
                raw_receipt = store._io.read_bytes(str(p.relative_to(store.root)))
                bindings.append({
                    'bundle_sha256': p.name.removesuffix('.receipt.json'),
                    'receipt_sha256': _sha(raw_receipt),
                })
        if len(bindings) > 32:
            raise CatalystIntegrityError('CATALYST_ADMISSION_LIMIT')
        cards, inputs = _project_admissions(store, materials, bindings, date, now)
        hourly, news_inputs, gaps = _hourly_cards(data_root, owner_root, date, now)
        cards += hourly
        archive=None
        if archive_source is not None:
            from .archive_catalyst_inputs import project_archive_catalysts
            from .workspace_plan import plan_context
            archive=project_archive_catalysts(archive_source,plan_context(date,now=now),security_master_root)
            cards+=archive['cards'];gaps=sorted(set([*gaps,*archive['gaps']]))
        value = _empty(date, 'READY' if cards else 'EMPTY')
        value.update(cards=cards, gaps=gaps, input_bindings=inputs + news_inputs, generated_at=now.isoformat())
        if archive is not None:value['archive_projection']=archive
        value['content_sha256'] = sha256_json(value)
        store._write_atomic(store.root / f'catalyst_observations/{date}.json', value)
        return value


def read(store, materials, date, *, data_root=None, owner_root=None, archive_source=None, security_master_root=None):
    date = strict_trade_date(date)
    value = store._read(store.root / f'catalyst_observations/{date}.json')
    if value is None:
        return _empty(date)
    now = _now()
    if value.get('schema_version') != SCHEMA or value.get('target_trade_date') != date or _aware(value.get('generated_at')) > now:
        raise CatalystIntegrityError('CATALYST_PUBLICATION_IDENTITY')
    if value.get('content_sha256') != sha256_json({k: v for k, v in value.items() if k != 'content_sha256'}):
        raise CatalystIntegrityError('CATALYST_PUBLICATION_HASH')
    inputs = value.get('input_bindings')
    if not isinstance(inputs, list) or len(inputs) > 104 or any(not isinstance(b, dict) for b in inputs):
        raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
    seen_admissions, seen_news = set(), set()
    for binding in inputs:
        kind = binding.get('kind')
        if kind == 'MATERIAL_ADMISSION':
            if set(binding) != {'kind', 'bundle_sha256', 'receipt_sha256'} or not HEX.fullmatch(str(binding.get('bundle_sha256', ''))):
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            receipt_sha = binding.get('receipt_sha256')
            if receipt_sha is not None and not HEX.fullmatch(str(receipt_sha)):
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            if binding['bundle_sha256'] in seen_admissions:
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            seen_admissions.add(binding['bundle_sha256'])
        elif kind == 'HOURLY_NEWS':
            if set(binding) != {'kind', 'artifact_ref', 'artifact_sha256', 'publication_sha256'}:
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            if not isinstance(binding.get('artifact_ref'), str) or not HEX.fullmatch(str(binding.get('artifact_sha256', ''))):
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            publication_sha = binding.get('publication_sha256')
            if publication_sha is not None and not HEX.fullmatch(str(publication_sha)):
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            if binding['artifact_ref'] in seen_news:
                raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
            seen_news.add(binding['artifact_ref'])
        else:
            raise CatalystIntegrityError('CATALYST_PUBLICATION_INPUTS')
    cards, rebound = _project_admissions(store, materials, [b for b in inputs if b['kind'] == 'MATERIAL_ADMISSION'], date, now)
    news_bindings = [b for b in inputs if b['kind'] == 'HOURLY_NEWS']
    hourly, rebound_news, gaps = _hourly_cards(data_root, owner_root, date, now, bindings=news_bindings)
    expected_cards = cards + hourly
    if 'archive_projection' in value:
        from .archive_catalyst_inputs import project_archive_catalysts
        previous=value['archive_projection']
        if not isinstance(previous,dict) or not isinstance(previous.get('snapshot'),dict):raise CatalystIntegrityError('ARCHIVE_CATALYST_SNAPSHOT_INVALID')
        ctx=previous['snapshot'].get('context',{})
        if ctx.get('plan_trade_date')!=date or _aware(ctx.get('research_cutoff'))>_aware(value['generated_at']):
            raise CatalystIntegrityError('ARCHIVE_CATALYST_DATE_OR_CUTOFF_CHANGED')
        actual=project_archive_catalysts(archive_source,ctx,security_master_root,frozen=previous['snapshot'])
        if actual!=previous:raise CatalystIntegrityError('ARCHIVE_CATALYST_PROJECTION_CHANGED')
        expected_cards+=actual['cards'];gaps=sorted(set([*gaps,*actual['gaps']]))
    expected_status = 'READY' if expected_cards else 'EMPTY'
    expected_envelope = {
        'kind': 'CATALYST_RESEARCH_OBSERVATIONS',
        'status': expected_status,
        'gaps': gaps,
        'can_refresh': True,
        'stage_dependency': False,
        'quote_dependency': False,
        **FLAGS,
    }
    if (
        value.get('cards') != expected_cards
        or inputs != rebound + rebound_news
        or any(value.get(key) != expected for key, expected in expected_envelope.items())
    ):
        raise CatalystIntegrityError('CATALYST_PUBLICATION_NOT_BOUND_TO_SOURCE')
    return value
