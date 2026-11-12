"""Disposable, date-sharded PDF search hints maintained by the existing owner.

This module has no scheduler or acquisition path. A hit only chooses a document
for the existing PDF/receipt/source verifier; the index is never authority.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from infrastructure.data_store import NativeDataStore

INDEX_ROOT = 'external_sources/zsxq_hourly/pdf_search_derived_v1'
SCHEMA = 'v4.zsxq_pdf_search_day.v1'
BIT_COUNT = 16384
BIT_BYTES = BIT_COUNT // 8
MAX_DAY_BYTES = 16 * 1024 * 1024
MAX_BATCH_DOCUMENTS = 10
INLINE_PDF_BYTES = 4 * 1024 * 1024
MAX_PDF_BYTES = 64 * 1024 * 1024
SAFETY = {'research_only': True, 'production_allowed': False,
          'buy_gate_updated': False, 'orders_sent': False}


class SearchIndexError(ValueError):
    pass


def _owner():
    from infrastructure import zsxq_pdf_ingestion
    return zsxq_pdf_ingestion


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _path(day: str) -> str:
    if not isinstance(day, str) or not re.fullmatch(r'[0-9]{8}', day):
        raise SearchIndexError('SEARCH_DATE_INVALID')
    try:
        _owner()._date(day)
    except ValueError as error:
        raise SearchIndexError('SEARCH_DATE_INVALID') from error
    return f'{INDEX_ROOT}/days/{day}.json'


def _fingerprint(index: Mapping[str, Any], document_id: str) -> tuple[str, str, str]:
    row = index['documents'].get(document_id)
    if not isinstance(row, Mapping) or not isinstance(row.get('source'), Mapping):
        return _sha(_canonical({'document_id': document_id, 'row': row})), '', 'INVALID'
    source = row['source']
    day = str(source.get('trade_date') or '')
    run_id = str(source.get('source_run_id') or '')
    latest = _owner()._latest_engine_run(row)
    status = str(latest[1].get('status') or 'PENDING').upper() if latest else 'PENDING'
    version = {'source': source, 'source_entry': index['sources'].get(run_id),
               'latest_engine_id': latest[0] if latest else None,
               'latest_engine': latest[1] if latest else None}
    return _sha(_canonical(version)), day, status


def _positions(gram: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(gram.encode('utf-8')).digest()
    return tuple(int.from_bytes(digest[i:i+2], 'big') % BIT_COUNT for i in (0, 2, 4))


def _text_bits(segments: Sequence[str]) -> bytes:
    bits = bytearray(BIT_BYTES)
    grams: set[str] = set()
    for segment in segments:
        text = segment.casefold()
        grams.update(text[i:i+2] for i in range(len(text)-1))
    for gram in grams:
        for pos in _positions(gram):
            bits[pos >> 3] |= 1 << (pos & 7)
    return bytes(bits)


def _term_positions(term: str) -> tuple[int, ...]:
    text = term.casefold()
    if len(text) < 2:
        raise SearchIndexError('SEARCH_TERM_TOO_SHORT')
    return tuple(sorted({pos for i in range(len(text)-1) for pos in _positions(text[i:i+2])}))


def _maybe(bits: bytes, positions: Sequence[int]) -> bool:
    return all(bits[p >> 3] & (1 << (p & 7)) for p in positions)


def _read_day(store: NativeDataStore, day: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        raw = _owner()._store_io(store).read_bytes(_path(day), max_bytes=MAX_DAY_BYTES)
    except FileNotFoundError:
        return None, None
    except (OSError, ValueError) as error:
        raise SearchIndexError('SEARCH_INDEX_DAY_UNREADABLE') from error
    try:
        outer = json.loads(raw.decode('utf-8'))
        body = outer['body']
        if (not isinstance(body, dict) or body.get('schema_version') != SCHEMA
                or body.get('research_date') != day or not isinstance(body.get('entries'), dict)
                or outer.get('sha256') != _sha(_canonical(body))):
            raise ValueError('invalid envelope')
        for doc_id, record in body['entries'].items():
            if (not isinstance(doc_id, str) or not re.fullmatch(r'[0-9a-f]{64}', doc_id)
                    or not isinstance(record, dict) or not re.fullmatch(r'[0-9a-f]{64}', str(record.get('fingerprint') or ''))):
                raise ValueError('invalid entry')
            bloom = record.get('bloom')
            if bloom is not None:
                if (len(base64.b64decode(bloom, validate=True)) != BIT_BYTES
                        or not re.fullmatch(r'[0-9a-f]{64}', str(record.get('verified_pdf_sha256') or ''))
                        or not re.fullmatch(r'[0-9a-f]{64}', str(record.get('receipt_sha256') or ''))
                        or type(record.get('page_count')) is not int or record['page_count'] < 1
                        or ('verified_pdf_size' in record and
                            (type(record['verified_pdf_size']) is not int or not 1 <= record['verified_pdf_size'] <= MAX_PDF_BYTES))
                        or ('verified_pages_size' in record and
                            (type(record['verified_pages_size']) is not int or not 1 <= record['verified_pages_size'] <= 32 * 1024 * 1024))):
                    raise ValueError('invalid bloom or provenance')
    except (UnicodeError, ValueError, TypeError, KeyError, binascii.Error) as error:
        raise SearchIndexError('SEARCH_INDEX_DAY_CORRUPT') from error
    return body, _sha(raw)


def _write_day(store: NativeDataStore, body: Mapping[str, Any]) -> str:
    raw = _canonical({'body': body, 'sha256': _sha(_canonical(body))})
    if len(raw) > MAX_DAY_BYTES:
        raise SearchIndexError('SEARCH_INDEX_DAY_SIZE_LIMIT')
    _owner()._store_io(store).write_bytes(_path(str(body['research_date'])), raw)
    return _sha(raw)


def _next_pending_locked(store: NativeDataStore, index: Mapping[str, Any], day: str, *,
                         max_pdf_bytes: int, exclude: set[str]) -> str | None:
    """Choose one bounded, previously unindexed READY doc without retry loops."""
    body, _ = _read_day(store, day)
    entries = (body or {}).get('entries', {})
    for doc_id, row in sorted(index['documents'].items()):
        if (doc_id in exclude or not isinstance(row, Mapping) or not isinstance(row.get('source'), Mapping)
                or row['source'].get('trade_date') != day):
            continue
        fingerprint, _day, status = _fingerprint(index, doc_id)
        previous = entries.get(doc_id) or {}
        if status != 'READY' or (previous.get('fingerprint') == fingerprint and previous.get('verification_error')):
            continue
        if previous.get('fingerprint') == fingerprint and previous.get('bloom') and previous.get('verified_pdf_size') and previous.get('verified_pages_size'):
            continue
        latest = _owner()._latest_engine_run(row)
        if latest and int(latest[1].get('pdf_size') or 0) <= max_pdf_bytes:
            return doc_id
    return None


def _refresh_locked(store: NativeDataStore, index: Mapping[str, Any], day: str, ids: Sequence[str], *,
                    max_pdf_bytes: int, reset_corrupt: bool = False, force_verify: bool = False) -> dict[str, Any]:
    """Update one date under the PDF owner's existing kernel lock."""
    _path(day)
    if (not 1 <= max_pdf_bytes <= MAX_PDF_BYTES or len(ids) > MAX_BATCH_DOCUMENTS
            or any(not isinstance(x, str) or not re.fullmatch(r'[0-9a-f]{64}', x) for x in ids)):
        raise SearchIndexError('SEARCH_UPDATE_ARGUMENT_INVALID')
    reset_or_missing = False
    try:
        body, _ = _read_day(store, day)
    except SearchIndexError as error:
        if str(error) != 'SEARCH_INDEX_DAY_CORRUPT' or not reset_corrupt:
            raise
        raw = _owner()._store_io(store).read_bytes(_path(day), max_bytes=MAX_DAY_BYTES)
        quarantine = f'{INDEX_ROOT}/quarantine/{day}-{_sha(raw)}.json'
        try:
            _owner()._store_io(store).write_bytes(quarantine, raw, require_absent=True)
        except FileExistsError:
            if _owner()._store_io(store).read_bytes(quarantine, max_bytes=MAX_DAY_BYTES) != raw:
                raise SearchIndexError('SEARCH_QUARANTINE_CONFLICT')
        body = None
        reset_or_missing = True
    if body is None:
        reset_or_missing = True
    body = body or {'schema_version': SCHEMA, 'research_date': day, 'entries': {}}
    entries = body['entries']
    results = []
    changed = False
    for doc_id in dict.fromkeys(ids):
        if doc_id not in index['documents']:
            results.append({'document_id': doc_id, 'status': 'OWNER_DOCUMENT_REMOVED'})
            continue  # preserve the old derived record; query excludes it.
        fingerprint, observed_day, status = _fingerprint(index, doc_id)
        if observed_day != day:
            results.append({'document_id': doc_id, 'status': 'SEARCH_DATE_MISMATCH'})
            continue
        prior = entries.get(doc_id)
        if status != 'READY':
            if prior:
                updated = dict(prior, verification_error='OWNER_DOCUMENT_NOT_READY')
                entries[doc_id] = updated
                changed = changed or updated != prior
            results.append({'document_id': doc_id, 'status': 'OWNER_DOCUMENT_NOT_READY'})
            continue
        row = index['documents'][doc_id]
        latest = _owner()._latest_engine_run(row)
        if prior and prior.get('fingerprint') == fingerprint and prior.get('verified_pdf_size') and prior.get('verified_pages_size') and not prior.get('verification_error') and not force_verify:
            results.append({'document_id': doc_id, 'status': 'ALREADY_INDEXED'})
            continue
        if int(latest[1].get('pdf_size') or 0) > max_pdf_bytes:
            results.append({'document_id': doc_id, 'status': 'SEARCH_UPDATE_PDF_SIZE_LIMIT'})
            continue
        try:
            detail = _owner()._verified_document_detail(store, index, doc_id, verify_pdf=True)
            receipt = detail['receipt']
            # The original owner verifies this same engine artifact but returns
            # only a receipt reference, not duplicated PDF hashes/file lengths.
            artifact = latest[1]
            pdf_sha = artifact.get('pdf_sha256')
            pdf_size = artifact.get('pdf_size')
            if (detail.get('status') != 'READY' or receipt.get('integrity') != 'SOURCE_PDF_AND_PAGE_HASHES_VERIFIED'
                    or not isinstance(pdf_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', pdf_sha)
                    or type(pdf_size) is not int or not 1 <= pdf_size <= MAX_PDF_BYTES):
                raise SearchIndexError('SEARCH_OWNER_DETAIL_INVALID')
            pages_raw = _owner()._store_io(store).read_bytes(artifact['pages_path'], max_bytes=32 * 1024 * 1024)
            if _sha(pages_raw) != artifact.get('pages_file_sha256'):
                raise SearchIndexError('SEARCH_OWNER_PAGES_SHA_DRIFT')
            pages_size = len(pages_raw)
            if not 1 <= pages_size <= 32 * 1024 * 1024:
                raise SearchIndexError('SEARCH_OWNER_DETAIL_INVALID')
            source = detail['source']
            pages = detail['pages']
            segments = [str(source.get('topic_title') or ''), str(source.get('original_filename') or '')]
            segments.extend(str(page.get('text') or '') for page in pages)
            entries[doc_id] = {'fingerprint': fingerprint, 'verified_pdf_sha256': pdf_sha,
                               'verified_pdf_size': pdf_size,
                               'verified_pages_size': pages_size,
                               'receipt_sha256': receipt.get('sha256'), 'source_run_id': source.get('source_run_id'),
                               'page_count': len(pages), 'bloom': base64.b64encode(_text_bits(segments)).decode('ascii'),
                               'verification_error': None}
            changed = True
            results.append({'document_id': doc_id, 'status': 'INDEXED', 'page_count': len(pages)})
        except (ValueError, OSError, KeyError, TypeError) as error:
            reason = getattr(error, 'code', None) or (str(error) if isinstance(error, SearchIndexError) else type(error).__name__)
            if prior:
                updated = dict(prior, verification_error=reason)
            else:
                updated = {'fingerprint': fingerprint, 'verification_error': reason, 'bloom': None}
            entries[doc_id] = updated
            changed = changed or updated != prior
            results.append({'document_id': doc_id, 'status': 'CANNOT_CONFIRM', 'reason': reason})
    result_status = 'PARTIAL' if any(r['status'] not in {'INDEXED', 'ALREADY_INDEXED'} for r in results) else 'READY'
    if results and (changed or reset_or_missing or any(r['status'] != 'ALREADY_INDEXED' for r in results)):
        body['last_attempt_at'] = _owner()._iso()
        body['last_update_status'] = result_status
        if any(r['status'] == 'INDEXED' for r in results):
            body['last_success_at'] = _owner()._iso()
        changed = True
    # One atomic publish for one day; failure leaves the previous committed bytes.
    if changed or reset_or_missing:
        checkpoint = _write_day(store, body)
    else:
        _, checkpoint = _read_day(store, day)
    return {'status': result_status, 'research_date': day, 'results': results, 'checkpoint_sha256': checkpoint,
            'last_success_at': body.get('last_success_at'), 'last_attempt_at': body.get('last_attempt_at'), **SAFETY}


def refresh(data_root: Path | str, *, research_date: str, document_ids: Sequence[str] | None = None,
            max_documents: int = 5, max_pdf_bytes: int = MAX_PDF_BYTES,
            reset_corrupt: bool = False, retry_failed: bool = False) -> dict[str, Any]:
    """Explicit bounded repair/backfill by the existing owner; never schedules work."""
    if type(max_documents) is not int or not 1 <= max_documents <= MAX_BATCH_DOCUMENTS:
        raise SearchIndexError('SEARCH_UPDATE_LIMIT_INVALID')
    root = Path(data_root).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise SearchIndexError('DATA_ROOT_INVALID')
    _path(research_date)
    store = NativeDataStore(root)
    owner = _owner()
    with owner._store_io(store).kernel_lock(owner.LOCK_RELATIVE, timeout=10):
        index = owner._read_index(store)
        if document_ids is None:
            try:
                body, _ = _read_day(store, research_date)
            except SearchIndexError:
                if not reset_corrupt:
                    raise
                body = None
            entries = (body or {}).get('entries', {})
            pending = []
            deferred_failures = 0
            for doc_id in sorted(index['documents']):
                fp, day, status = _fingerprint(index, doc_id)
                prior = entries.get(doc_id) or {}
                if day != research_date or status != 'READY':
                    continue
                same_failed = prior.get('fingerprint') == fp and prior.get('verification_error')
                if same_failed and not retry_failed:
                    deferred_failures += 1
                elif prior.get('fingerprint') != fp or same_failed or not prior.get('bloom') or not prior.get('verified_pdf_size') or not prior.get('verified_pages_size'):
                    pending.append(doc_id)
            ids = pending[:max_documents]
        else:
            if len(document_ids) > max_documents:
                raise SearchIndexError('SEARCH_UPDATE_LIMIT_INVALID')
            ids = list(document_ids)
            pending = []
            deferred_failures = 0
        result = _refresh_locked(store, index, research_date, ids, max_pdf_bytes=max_pdf_bytes,
                                 reset_corrupt=reset_corrupt, force_verify=document_ids is not None)
        result['remaining_ready_candidates'] = max(0, len(pending) - len(ids)) if document_ids is None else None
        result['ready_failed_deferred'] = deferred_failures if document_ids is None else None
        return result


def query(data_root: Path | str, terms: Mapping[str, Sequence[str]]) -> dict[str, Any]:
    """Search every indexed day using a no-false-negative bigram Bloom prefilter."""
    root = Path(data_root).expanduser()
    if not root.is_dir() or root.is_symlink():
        raise SearchIndexError('DATA_ROOT_INVALID')
    store = NativeDataStore(root)
    owner = _owner()
    cache_days: set[str] = set()
    discovery_gaps: list[dict[str, Any]] = []
    try:
        for filename in owner._store_io(store).files(f'{INDEX_ROOT}/days', suffix='.json'):
            candidate_day = filename[:-5]
            try:
                _path(candidate_day)
                cache_days.add(candidate_day)
            except SearchIndexError:
                discovery_gaps.append({'reason': 'SEARCH_INDEX_DAY_NAME_INVALID'})
    except (OSError, ValueError):
        discovery_gaps.append({'reason': 'SEARCH_INDEX_DIRECTORY_UNREADABLE'})
    # No materialized shard can produce a hit. Do not load/fingerprint the much
    # larger ingestion inventory merely to report that the derived index is absent.
    if not cache_days:
        return {'status': 'NOT_MATERIALIZED', 'candidates': [], 'checkpoint_sha256': None,
                'day_sha256': {}, 'inventory_sha256': None, 'source_bindings_sha256': None,
                'coverage': {'scope': 'INGESTION_INDEX_ONLY', 'indexed_dates_seen': None,
                             'cache_dates_seen': 0, 'dates_considered': [], 'dates_scanned': [],
                             'owner_documents': None, 'indexed_documents': 0,
                             'gaps': [*discovery_gaps, {'reason': 'SEARCH_INDEX_NOT_MATERIALIZED'}],
                             'index_updates': {},
                             'search_method': 'ALL_INDEXED_PAGE_BIGRAM_BLOOM_CANDIDATES_REVERIFY_PDF',
                             'historical_sources_complete': False}, **SAFETY}
    index = owner._read_index(store)
    inventory: dict[str, tuple[str, str, str]] = {}
    malformed = 0
    for doc_id in index['documents']:
        try:
            if not re.fullmatch(r'[0-9a-f]{64}', doc_id):
                raise ValueError('document id')
            fp, day, status = _fingerprint(index, doc_id)
            _path(day)
            inventory[doc_id] = (fp, day, status)
        except (ValueError, TypeError, KeyError):
            malformed += 1
    inventory_days = {value[1] for value in inventory.values()}
    days = sorted(inventory_days | cache_days)
    masks = {symbol: [_term_positions(term) for term in values] for symbol, values in terms.items()}
    ledgers: dict[str, dict[str, Any]] = {}
    hashes: dict[str, str] = {}
    updates: dict[str, dict[str, Any]] = {}
    gaps: list[dict[str, Any]] = discovery_gaps
    for day in days:
        try:
            body, digest = _read_day(store, day)
            if body is None:
                gaps.append({'research_date': day, 'reason': 'SEARCH_INDEX_DATE_MISSING'})
            else:
                ledgers[day] = body['entries']
                hashes[day] = str(digest)
                updates[day] = {'last_success_at': body.get('last_success_at'),
                                'last_attempt_at': body.get('last_attempt_at'),
                                'last_update_status': body.get('last_update_status')}
                if body.get('last_update_status') not in (None, 'READY'):
                    gaps.append({'research_date': day, 'reason': 'SEARCH_LAST_UPDATE_PARTIAL',
                                 'last_success_at': body.get('last_success_at')})
        except SearchIndexError as error:
            gaps.append({'research_date': day, 'reason': str(error)})
    if not ledgers:
        gaps.append({'reason': 'SEARCH_INDEX_NOT_MATERIALIZED'})
    candidates = []
    counts = {'owner_documents': len(inventory), 'indexed_documents': 0, 'unindexed_ready': 0, 'size_unknown_documents': 0,
              'stale_documents': 0, 'unavailable_documents': 0, 'removed_documents': 0,
              'large_ready_pending': 0, 'large_verification_error': 0,
              'malformed_documents': malformed}
    for doc_id, (fingerprint, day, status) in inventory.items():
        record = ledgers.get(day, {}).get(doc_id)
        if status != 'READY':
            counts['unavailable_documents'] += 1
            continue
        latest = owner._latest_engine_run(index['documents'][doc_id])
        size = latest[1].get('pdf_size') if latest else None
        if (type(size) is int and INLINE_PDF_BYTES < size <= owner.MAX_PDF_BYTES
                and (not record or record.get('fingerprint') != fingerprint or record.get('verification_error')
                     or not record.get('bloom') or not record.get('verified_pdf_size') or not record.get('verified_pages_size'))):
            counts['large_ready_pending'] += 1
            if record and record.get('fingerprint') == fingerprint and record.get('verification_error'):
                counts['large_verification_error'] += 1
        if not record:
            counts['unindexed_ready'] += 1
            continue
        if record.get('fingerprint') != fingerprint:
            counts['stale_documents'] += 1
            continue
        if record.get('verification_error') or not record.get('bloom'):
            counts['unavailable_documents'] += 1
            continue
        if not record.get('verified_pdf_size') or not record.get('verified_pages_size'):
            counts['size_unknown_documents'] += 1
            continue
        counts['indexed_documents'] += 1
        bits = base64.b64decode(record['bloom'], validate=True)
        if any(_maybe(bits, positions) for symbol_masks in masks.values() for positions in symbol_masks):
            candidates.append({'document_id': doc_id, 'research_date': day,
                               'verified_pdf_sha256': record.get('verified_pdf_sha256'),
                               'verified_pdf_size': record.get('verified_pdf_size'),
                               'verified_pages_size': record.get('verified_pages_size')})
    for day, entries in ledgers.items():
        counts['removed_documents'] += sum(1 for doc_id in entries if doc_id not in inventory or inventory[doc_id][1] != day)
    if counts['large_ready_pending']:
        gaps.append({'reason': 'SEARCH_INDEX_LARGE_PENDING', 'count': counts['large_ready_pending'],
                     'verification_errors': counts['large_verification_error']})
    if malformed:
        gaps.append({'reason': 'OWNER_INDEX_MALFORMED_DOCUMENTS', 'count': malformed})
    for key, reason in [('unindexed_ready', 'SEARCH_INDEX_LAG'), ('size_unknown_documents', 'SEARCH_INDEX_SIZE_UNKNOWN'), ('stale_documents', 'SEARCH_INDEX_STALE'),
                        ('unavailable_documents', 'OWNER_DOCUMENT_UNAVAILABLE'), ('removed_documents', 'SEARCH_INDEX_OWNER_DOCUMENT_REMOVED')]:
        if counts[key]: gaps.append({'reason': reason, 'count': counts[key]})
    scope = owner.read_pdf_index_scope(root)
    gaps.extend(scope.get('gaps') or [])
    inventory_digest = _sha(_canonical(sorted((doc_id, *value) for doc_id, value in inventory.items())))
    binding_digest = _sha(_canonical(scope.get('source_bindings') or {}))
    snapshot = _sha(_canonical({'ledgers': hashes, 'inventory': inventory_digest, 'source_bindings': binding_digest}))
    candidates.sort(key=lambda row: (row['research_date'], row['document_id']), reverse=True)
    return {'status': 'NOT_MATERIALIZED' if not ledgers else 'PARTIAL' if gaps else 'READY', 'candidates': candidates,
            'checkpoint_sha256': snapshot, 'day_sha256': hashes, 'inventory_sha256': inventory_digest,
            'source_bindings_sha256': binding_digest,
            'coverage': {'scope': 'INGESTION_INDEX_ONLY', 'indexed_dates_seen': len(inventory_days),
                         'cache_dates_seen': len(cache_days), 'dates_considered': days,
                         'dates_scanned': sorted(ledgers), **counts, 'gaps': gaps,
                         'index_updates': updates,
                         'search_method': 'ALL_INDEXED_PAGE_BIGRAM_BLOOM_CANDIDATES_REVERIFY_PDF',
                         'historical_sources_complete': False}, **SAFETY}
