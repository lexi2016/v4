"""Explicit-date Eastmoney HK announcement listing catalog.

This module only captures the existing Eastmoney listing endpoint through the
existing provider and MaterialStore helpers. It does not request article
bodies or attachments and does not interpret announcement content.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import re
from typing import Any, Callable, Mapping
from urllib.parse import urlencode
from uuid import uuid4

from .workspace_projection import FLAGS, canonical_symbol, date_token, digest, timestamp

SCHEMA = 'v4.manager_research.eastmoney_hk_date_catalog.v1'
OWNER = 'ManagerResearchJobService.refresh_announcements'
SOURCE = 'EASTMONEY_HK'
SOURCE_SCOPE = 'EASTMONEY_HK_DATE_CATALOG'
LIST_URL = 'https://np-anotice-stock.eastmoney.com/api/security/ann'
PAGE_SIZE = 20
MAX_DATA_PAGES = 1000


def _date(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('ANNOUNCEMENT_CATALOG_NOTICE_DATE_INVALID')
    if re.fullmatch(r'\d{8}', value):
        token = value
    elif re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        token = value.replace('-', '')
    else:
        raise ValueError('ANNOUNCEMENT_CATALOG_NOTICE_DATE_INVALID')
    try:
        return datetime.strptime(token, '%Y%m%d').strftime('%Y-%m-%d')
    except ValueError as exc:
        raise ValueError('ANNOUNCEMENT_CATALOG_NOTICE_DATE_INVALID') from exc


def date_scoped_url(notice_date: str, page_index: int, *, page_size: int = PAGE_SIZE) -> str:
    """Build the proven complete-date Eastmoney listing query, in stable order."""
    day = _date(notice_date)
    if type(page_index) is not int or page_index < 1 or page_index > MAX_DATA_PAGES + 1:
        raise ValueError('ANNOUNCEMENT_CATALOG_PAGE_INDEX_INVALID')
    if type(page_size) is not int or page_size != PAGE_SIZE:
        raise ValueError('ANNOUNCEMENT_CATALOG_PAGE_SIZE_INVALID')
    query = urlencode((
        ('ann_type', 'H'), ('client_source', 'web'), ('f_node', '0'),
        ('begin_time', day), ('end_time', day), ('page_size', str(page_size)),
        ('page_index', str(page_index)),
    ))
    return LIST_URL + '?' + query


def _seal(value: Mapping[str, Any]) -> dict[str, Any]:
    out = {key: item for key, item in value.items() if key != 'sha256'}
    out['sha256'] = digest(out)
    return out


def _master_identity(master_codes: list[str], identity_witness: Mapping[str, Any] | None) -> str | None:
    if not master_codes and identity_witness is None:
        return None
    if (not master_codes or master_codes != sorted(set(master_codes))
            or any(canonical_symbol(code) != code for code in master_codes)
            or not isinstance(identity_witness, Mapping)
            or identity_witness.get('owner') != 'load_verified_hk_security_master'):
        raise ValueError('ANNOUNCEMENT_CATALOG_VERIFIED_MASTER_REQUIRED')
    return digest(master_codes)


def _source_stock_identity(value: Any) -> tuple[str, str] | None:
    """Return an exact Eastmoney 116/H research key and its raw code.

    Numeric HK tickers use the existing canonical form. The source's documented
    applicant identifier form (for example H5354) is preserved verbatim as a
    source key; neither form is a Connect-membership assertion.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().upper()
    canonical = canonical_symbol(raw)
    if canonical is not None:
        return canonical, raw
    if re.fullmatch(r'H\d{4}', raw):
        return raw, raw
    return None


def _int_field(value: Any) -> bool:
    return type(value) is int and value >= 0


def _parse_response(raw: bytes, *, page_index: int, page_size: int,
                    requested_total: int | None) -> tuple[dict, list[str]]:
    issues: list[str] = []
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError):
        return {}, ['EASTMONEY_CATALOG_RESPONSE_JSON_INVALID']
    data = payload.get('data') if isinstance(payload, dict) else None
    if (not isinstance(payload, dict) or type(payload.get('success')) is not int
            or payload.get('success') != 1 or not isinstance(data, dict)):
        return {}, ['EASTMONEY_CATALOG_RESPONSE_SHAPE_INVALID']
    rows = data.get('list')
    response_page = data.get('page_index')
    response_size = data.get('page_size')
    total = data.get('total_hits')
    if not isinstance(rows, list):
        issues.append('EASTMONEY_CATALOG_LIST_MISSING')
        rows = []
    if type(response_page) is not int or response_page != page_index:
        issues.append('EASTMONEY_CATALOG_PAGE_INDEX_MISMATCH')
    if type(response_size) is not int or response_size != page_size:
        issues.append('EASTMONEY_CATALOG_PAGE_SIZE_MISMATCH')
    if not _int_field(total):
        issues.append('EASTMONEY_CATALOG_TOTAL_HITS_INVALID')
        total = None
    elif requested_total is not None and total != requested_total:
        issues.append('EASTMONEY_CATALOG_TOTAL_HITS_DRIFT')
    return dict(rows=rows, response_page_index=response_page, response_page_size=response_size,
                total_hits=total), issues


def _row_source_codes(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    codes = row.get('codes')
    if not isinstance(codes, list):
        return []
    out = []
    for item in codes:
        if isinstance(item, Mapping):
            out.append(dict(market_code=deepcopy(item.get('market_code')),
                stock_code=deepcopy(item.get('stock_code')), ann_type=deepcopy(item.get('ann_type')),
                short_name=deepcopy(item.get('short_name'))))
    return out


def _source_row(row: Any, *, page_index: int, item_index: int, ref: Mapping[str, Any],
                expected_notice_date: str, master_names: Mapping[str, Mapping[str, Any]]) -> tuple[dict, list[str], list[dict]]:
    from .announcement_source import _eastmoney_display_time, _eastmoney_notice_date

    issues: list[str] = []
    if not isinstance(row, Mapping):
        return dict(page_index=page_index, item_index=item_index, source_ref=deepcopy(dict(ref)),
                    raw_row=row, notice_date_iso=None, display_date=None,
                    display_notice_date_mismatch=False, source_codes_116_H=[], source_issuer_codes=[],
                    matched_master_codes=[]), [
                        'EASTMONEY_CATALOG_ROW_INVALID'], []
    raw_row = deepcopy(dict(row))
    art_code = row.get('art_code')
    if not isinstance(art_code, str) or re.fullmatch(r'AN[A-Z0-9]{8,32}', art_code) is None:
        issues.append('EASTMONEY_CATALOG_ART_CODE_INVALID')
    notice_value = row.get('notice_date')
    notice_iso = None
    try:
        notice_iso = _eastmoney_notice_date(notice_value)
        if notice_iso != expected_notice_date:
            issues.append('EASTMONEY_CATALOG_NOTICE_DATE_MISMATCH')
    except ValueError:
        issues.append('EASTMONEY_CATALOG_NOTICE_DATE_INVALID')
    display_value = row.get('display_time')
    display_date = None
    try:
        display_date = _eastmoney_display_time(display_value).date().isoformat()
    except ValueError:
        issues.append('EASTMONEY_CATALOG_DISPLAY_TIME_INVALID')
    display_mismatch = bool(notice_iso and display_date and display_date != notice_iso)

    source_codes = _row_source_codes(row)
    hk_codes = [item for item in source_codes
                if item['market_code'] == '116' and item['ann_type'] == 'H']
    if not hk_codes:
        issues.append('EASTMONEY_CATALOG_HK_116_H_CODE_MISSING')
    source_identities: dict[str, dict[str, Any]] = {}
    matched: dict[str, dict[str, Any]] = {}
    for item in hk_codes:
        identity = _source_stock_identity(item.get('stock_code'))
        if identity is None:
            issue = ('EASTMONEY_CATALOG_HK_116_H_STOCK_CODE_MISSING'
                     if not isinstance(item.get('stock_code'), str) or not item['stock_code'].strip()
                     else 'EASTMONEY_CATALOG_HK_116_H_STOCK_CODE_INVALID')
            issues.append(issue)
            continue
        code, raw_code = identity
        source_identities[code] = dict(code=code, source_stock_code=raw_code,
            market_code='116', ann_type='H', name=(item.get('short_name')
                if isinstance(item.get('short_name'), str) and item.get('short_name').strip() else None))
        master_code = canonical_symbol(raw_code)
        if master_code is not None and master_code in master_names:
            matched[master_code] = dict(code=master_code, name=master_names[master_code].get('name'),
                                 source_short_name=item.get('short_name'))
    blob_sha = ref.get('blob_sha256')
    body_sha = ref.get('body_sha256')
    receipt = dict(art_code=art_code, blob_sha256=blob_sha, display_time=display_value,
        matched_master_codes=[matched[code] for code in sorted(matched)], notice_date=notice_value,
        page_index=page_index, item_index=item_index, raw_body_sha256=body_sha,
        raw_row=raw_row, request_url=ref.get('request', {}).get('url'),
        retrieved_at=ref.get('retrieved_at'), source_codes_116_H=hk_codes, title=row.get('title'),
        source_issuer_codes=[source_identities[code] for code in sorted(source_identities)],
        source_ref=deepcopy(dict(ref)), notice_date_iso=notice_iso, display_date=display_date,
        display_notice_date_mismatch=display_mismatch)
    return receipt, issues, [source_identities[code] for code in sorted(source_identities)]


def collect_date_scoped_catalog(provider: Any, store: Any, *, target_trade_date: str,
                                publication_date: str,
                                master_names: Mapping[str, Mapping[str, Any]] | None = None,
                                identity_witness: Mapping[str, Any] | None = None,
                                resume_refs: Mapping[int, Mapping[str, Any]] | None = None,
                                run_id: str | None = None, generated_at: str | None = None,
                                before_page: Callable[[int, str, bool], str | None] | None = None,
                                after_page: Callable[[dict[str, Any]], str | None] | None = None) -> dict[str, Any]:
    """Capture or read one explicit notice date, requiring dynamic and terminal proof.

    A supplied reference is read from the same shared MaterialStore without a
    network call. Pages absent from ``resume_refs`` are captured once if a
    provider is available. No failure path retries a request.
    """
    from .announcement_source import capture_eastmoney, read_eastmoney_response

    target = date_token(target_trade_date)
    publication = _date(publication_date)
    master_names = master_names or {}
    master_codes = sorted(master_names)
    if any(not isinstance(master_names[code], Mapping)
           or not isinstance(master_names[code].get('name'), str)
           or not master_names[code]['name'].strip() for code in master_codes):
        raise ValueError('ANNOUNCEMENT_CATALOG_VERIFIED_MASTER_REQUIRED')
    master_hash = _master_identity(master_codes, identity_witness)
    run_id = run_id or uuid4().hex
    generated_at = generated_at or datetime.now(timezone.utc).isoformat(timespec='microseconds')
    if not re.fullmatch(r'[0-9a-f]{32}', run_id) or timestamp(generated_at) is None:
        raise ValueError('ANNOUNCEMENT_CATALOG_RUN_ID_OR_TIME_INVALID')
    refs = {int(page): deepcopy(dict(ref)) for page, ref in (resume_refs or {}).items()
            if type(page) is int and page >= 1 and isinstance(ref, Mapping)}
    gaps: set[str] = set()
    pages: list[dict[str, Any]] = []
    source_rows: list[dict[str, Any]] = []
    manager_rows: list[dict[str, Any]] = []
    seen_art_codes: set[str] = set()
    duplicates: set[str] = set()
    expected_total: int | None = None
    data_pages: int | None = None
    display_mismatches: list[dict[str, Any]] = []
    page_index = 1
    terminal_seen = False

    def record_page(receipt: dict[str, Any]) -> None:
        if after_page is not None:
            try:
                owner_receipt = after_page(deepcopy(receipt))
                if owner_receipt is not None:
                    receipt['owner_receipt_path'] = owner_receipt
                else:
                    gaps.add('EASTMONEY_CATALOG_OWNER_PAGE_RECEIPT_MISSING')
            except (ValueError, RuntimeError, OSError, KeyError, TypeError):
                gaps.add('EASTMONEY_CATALOG_OWNER_PAGE_RECEIPT_WRITE_FAILED')
            if not receipt.get('owner_attempt_path'):
                gaps.add('EASTMONEY_CATALOG_OWNER_ATTEMPT_RECEIPT_MISSING')
        pages.append(receipt)

    while page_index <= MAX_DATA_PAGES + 1:
        url = date_scoped_url(publication, page_index)
        ref = refs.get(page_index)
        reused = ref is not None
        page_receipt: dict[str, Any] = dict(schema='v4.manager_research.eastmoney_hk_page_receipt.v1',
            target_trade_date=target, publication_date=publication, source_scope=SOURCE_SCOPE,
            run_id=run_id, page_index=page_index, requested_url=url, capture_status='FAILED',
            source_ref=None, error=None, retrieved_at=None, http_status=None, total_hits=None,
            response_page_index=None, response_page_size=None, row_count=None, raw_body_sha256=None,
            blob_sha256=None, from_cache=None, contract_issues=[])
        try:
            if before_page is not None:
                page_receipt['owner_attempt_path'] = before_page(page_index, url, reused)
            if ref is None:
                if provider is None:
                    raise ValueError('EASTMONEY_CATALOG_PAGE_REFERENCE_MISSING')
                ref = capture_eastmoney(provider, url, force=True)
            # Preserve even a rejected supplied ref in the derived receipt so
            # offline owner readback can reproduce the same fail-closed gap.
            page_receipt['source_ref'] = deepcopy(dict(ref))
            if (ref.get('request') != dict(source=SOURCE, method='GET', url=url)
                    or ref.get('final_url') != url
                    or type(ref.get('http_status')) is not int
                    or timestamp(ref.get('retrieved_at')) is None):
                raise ValueError('EASTMONEY_CATALOG_REFERENCE_IDENTITY_INVALID')
            page_receipt.update(source_ref=deepcopy(dict(ref)), retrieved_at=ref.get('retrieved_at'),
                http_status=ref.get('http_status'), raw_body_sha256=ref.get('body_sha256'),
                blob_sha256=ref.get('blob_sha256'), from_cache=ref.get('from_cache'))
            raw = read_eastmoney_response(store, ref)
            if ref['http_status'] != 200:
                raise ValueError('EASTMONEY_CATALOG_HTTP_STATUS_NOT_200')
            parsed, parse_issues = _parse_response(raw, page_index=page_index, page_size=PAGE_SIZE,
                requested_total=expected_total)
            page_receipt['raw_body_sha256'] = sha256(raw).hexdigest()
            page_receipt.update(total_hits=parsed.get('total_hits'),
                response_page_index=parsed.get('response_page_index'),
                response_page_size=parsed.get('response_page_size'),
                row_count=len(parsed.get('rows', [])), contract_issues=parse_issues)
            if parse_issues:
                gaps.update(parse_issues)
            row_issues_on_page: set[str] = set()
            for item_index, row in enumerate(parsed.get('rows', []), start=1):
                entry, row_issues, source_codes = _source_row(row, page_index=page_index,
                    item_index=item_index, ref=ref, expected_notice_date=publication,
                    master_names=master_names)
                if row_issues:
                    row_issues_on_page.update(row_issues)
                    gaps.update(row_issues)
                art_code = entry.get('art_code')
                if isinstance(art_code, str):
                    if art_code in seen_art_codes:
                        duplicates.add(art_code)
                        gaps.add('EASTMONEY_CATALOG_ART_CODE_DUPLICATE')
                    seen_art_codes.add(art_code)
                if entry['display_notice_date_mismatch']:
                    display_mismatches.append(dict(art_code=art_code, notice_date=entry['notice_date'],
                        display_time=entry['display_time']))
                source_rows.append(entry)
                if source_codes:
                    manager_entry = {key: deepcopy(value) for key, value in entry.items()
                                     if key not in {'notice_date_iso', 'display_date', 'display_notice_date_mismatch', 'source_ref'}}
                    manager_entry['source_ref'] = deepcopy(dict(ref))
                    manager_rows.append(manager_entry)
            page_receipt['contract_issues'] = sorted(set(parse_issues) | row_issues_on_page)
            page_receipt['capture_status'] = 'PARTIAL' if parse_issues or row_issues_on_page else 'PASS'
            if expected_total is None and _int_field(parsed.get('total_hits')):
                expected_total = parsed['total_hits']
                data_pages = math.ceil(expected_total / PAGE_SIZE)
                if data_pages > MAX_DATA_PAGES:
                    gaps.add('EASTMONEY_CATALOG_PAGE_LIMIT_EXCEEDED')
                    page_receipt['capture_status'] = 'PARTIAL'
                    record_page(page_receipt)
                    break
            elif expected_total is None:
                gaps.add('EASTMONEY_CATALOG_TOTAL_HITS_UNKNOWN')
                page_receipt['capture_status'] = 'PARTIAL'
                record_page(page_receipt)
                break
            assert expected_total is not None and data_pages is not None
            expected_rows = (min(PAGE_SIZE, max(0, expected_total - (page_index - 1) * PAGE_SIZE))
                             if page_index <= data_pages else 0)
            page_receipt['expected_row_count'] = expected_rows
            if page_receipt['row_count'] != expected_rows:
                gaps.add('EASTMONEY_CATALOG_PAGE_ROW_COUNT_MISMATCH')
            if page_receipt['row_count'] != expected_rows or parse_issues or row_issues_on_page:
                page_receipt['capture_status'] = 'PARTIAL'
            record_page(page_receipt)
            if page_index > data_pages:
                terminal_seen = len(parsed.get('rows', [])) == 0
                if not terminal_seen:
                    gaps.add('EASTMONEY_CATALOG_TERMINAL_PAGE_NOT_EMPTY')
                break
            page_index += 1
        except (ValueError, RuntimeError, OSError, KeyError, TypeError) as exc:
            page_receipt['error'] = str(exc)[:200]
            page_receipt['capture_status'] = 'FAILED'
            gaps.add('EASTMONEY_CATALOG_PAGE_CAPTURE_OR_READ_FAILED')
            record_page(page_receipt)
            if page_index == 1 or (data_pages is not None and page_index > data_pages):
                break
            page_index += 1

    if expected_total is None:
        gaps.add('EASTMONEY_CATALOG_TOTAL_HITS_UNKNOWN')
    else:
        if not terminal_seen:
            gaps.add('EASTMONEY_CATALOG_TERMINAL_PAGE_MISSING')
        if len(source_rows) != expected_total:
            gaps.add('EASTMONEY_CATALOG_TOTAL_ROW_COUNT_MISMATCH')
        if len(seen_art_codes) != expected_total:
            gaps.add('EASTMONEY_CATALOG_UNIQUE_ART_CODE_COUNT_MISMATCH')
    unexpected_refs = sorted(set(refs) - {page['page_index'] for page in pages})
    if unexpected_refs:
        gaps.add('EASTMONEY_CATALOG_UNEXPECTED_RESUME_PAGE_REFERENCE')

    status = 'PARTIAL' if gaps else ('COMPLETE_EMPTY' if expected_total == 0 else 'COMPLETE')
    product = dict(schema_version=SCHEMA, owner=OWNER, source=SOURCE, source_scope=SOURCE_SCOPE,
        target_trade_date=target, publication_date=publication, run_id=run_id,
        generated_at=generated_at, page_size=PAGE_SIZE, total_hits=expected_total,
        expected_data_page_count=data_pages, expected_terminal_page_index=(data_pages + 1 if data_pages is not None and expected_total > 0 else 1 if expected_total == 0 else None),
        terminal_empty_seen=terminal_seen, captured_page_count=len(pages),
        captured_row_count=len(source_rows), unique_art_code_count=len(seen_art_codes),
        duplicate_art_codes=sorted(duplicates), page_receipts=pages, source_rows=source_rows,
        unused_resume_refs={str(page):deepcopy(refs[page]) for page in unexpected_refs},
        manager_consumer_rows=manager_rows, manager_consumer_row_count=len(manager_rows),
        manager_matched_master_codes=sorted({item['code'] for row in manager_rows for item in row['matched_master_codes']}),
        manager_source_codes=sorted({item['code'] for row in manager_rows for item in row['source_issuer_codes']}),
        manager_source_identity_count=sum(len(row['source_issuer_codes']) for row in manager_rows),
        source_identity_basis='EASTMONEY_116_H_SOURCE_REFERENCE',
        connect_eligibility_status='NOT_ASSESSED',
        master_scope_identity=master_hash, master_scope_count=len(master_codes),
        master_names={code: {'name': master_names[code].get('name')} for code in master_codes},
        master_identity_witness=deepcopy(dict(identity_witness)) if isinstance(identity_witness, Mapping) else None,
        master_enrichment_status='VERIFIED_REFERENCE_ONLY' if master_hash is not None else 'NOT_ATTEMPTED',
        display_notice_date_mismatch_count=len(display_mismatches),
        display_notice_date_mismatches=display_mismatches,
        gaps=sorted(gaps), status=status,
        coverage_scope='EASTMONEY_HK_DATE_SCOPED_LISTING_MIRROR',
        hkex_first_publication_verified=False, content_body_fetch='NOT_REQUESTED',
        attachment_fetch='NOT_REQUESTED', semantic_analysis='NOT_RUN',
        manager_consumer_use='SOURCE_IDENTITY_RESEARCH_REFERENCE_ONLY_NOT_CONNECT_ELIGIBILITY_OR_SELECTION_RESULT', **FLAGS)
    return _seal(product)


def validate_product(value: Mapping[str, Any], *, target_trade_date: str,
                     publication_date: str) -> dict[str, Any]:
    target = date_token(target_trade_date)
    publication = _date(publication_date)
    if (not isinstance(value, dict) or value.get('schema_version') != SCHEMA
            or value.get('owner') != OWNER or value.get('source') != SOURCE
            or value.get('source_scope') != SOURCE_SCOPE
            or value.get('target_trade_date') != target or value.get('publication_date') != publication
            or value.get('sha256') != _seal(value)['sha256']
            or any(value.get(key) is not item for key, item in FLAGS.items())
            or value.get('coverage_scope') != 'EASTMONEY_HK_DATE_SCOPED_LISTING_MIRROR'
            or value.get('hkex_first_publication_verified') is not False
            or value.get('content_body_fetch') != 'NOT_REQUESTED'
            or value.get('attachment_fetch') != 'NOT_REQUESTED'
            or value.get('semantic_analysis') != 'NOT_RUN'
            or value.get('manager_consumer_use') not in {
                'CODE_INTERSECTION_ONLY_NOT_SELECTION_RESULT',
                'SOURCE_IDENTITY_RESEARCH_REFERENCE_ONLY_NOT_CONNECT_ELIGIBILITY_OR_SELECTION_RESULT',
            }
            or value.get('page_size') != PAGE_SIZE
            or not re.fullmatch(r'[0-9a-f]{32}', str(value.get('run_id', '')))
            or timestamp(value.get('generated_at')) is None
            or not isinstance(value.get('page_receipts'), list)
            or not isinstance(value.get('source_rows'), list)
            or not isinstance(value.get('manager_consumer_rows'), list)
            or not isinstance(value.get('master_names'), dict)
            or len(value['master_names']) != value.get('master_scope_count')
            or value.get('captured_page_count') != len(value.get('page_receipts', []))
            or value.get('captured_row_count') != len(value.get('source_rows', []))
            or value.get('manager_consumer_row_count') != len(value.get('manager_consumer_rows', []))
            or not isinstance(value.get('gaps'), list)):
        raise ValueError('ANNOUNCEMENT_CATALOG_PRODUCT_IDENTITY_INVALID')
    duplicates=value.get('duplicate_art_codes')
    if (not isinstance(duplicates,list) or any(not isinstance(item,str) for item in duplicates)
            or duplicates!=sorted(set(duplicates)) or any(not isinstance(item,str) for item in value['gaps'])
            or value['gaps']!=sorted(set(value['gaps']))):
        raise ValueError('ANNOUNCEMENT_CATALOG_PRODUCT_CONTRACT_INVALID')
    if value.get('status') not in {'COMPLETE', 'COMPLETE_EMPTY', 'PARTIAL'}:
        raise ValueError('ANNOUNCEMENT_CATALOG_PRODUCT_STATUS_INVALID')
    if value.get('status') != 'PARTIAL':
        total = value.get('total_hits')
        expected_pages = 0 if total == 0 else math.ceil(total / PAGE_SIZE) if _int_field(total) else None
        if (not _int_field(total) or value.get('gaps') or value.get('expected_data_page_count') != expected_pages
                or value.get('captured_row_count') != total or value.get('unique_art_code_count') != total
                or value.get('terminal_empty_seen') is not True
                or value.get('captured_page_count') != (1 if total == 0 else expected_pages + 1)
                or value.get('status') != ('COMPLETE_EMPTY' if total == 0 else 'COMPLETE')):
            raise ValueError('ANNOUNCEMENT_CATALOG_PRODUCT_COMPLETENESS_INVALID')
    master_hash = _master_identity(sorted(value['master_names']), value.get('master_identity_witness'))
    if (type(value.get('master_scope_count')) is not int
            or value.get('master_scope_identity') != master_hash):
        raise ValueError('ANNOUNCEMENT_CATALOG_MASTER_IDENTITY_INVALID')
    if value.get('source_identity_basis') is not None:
        source_codes = value.get('manager_source_codes')
        if (value.get('source_identity_basis') != 'EASTMONEY_116_H_SOURCE_REFERENCE'
                or value.get('connect_eligibility_status') != 'NOT_ASSESSED'
                or value.get('master_enrichment_status') not in {'NOT_ATTEMPTED', 'VERIFIED_REFERENCE_ONLY'}
                or not isinstance(source_codes, list)
                or source_codes != sorted(set(source_codes))
                or any(not isinstance(code, str) or not code for code in source_codes)
                or type(value.get('manager_source_identity_count')) is not int
                or value.get('manager_source_identity_count') < 0):
            raise ValueError('ANNOUNCEMENT_CATALOG_SOURCE_IDENTITY_CONTRACT_INVALID')
    return deepcopy(dict(value))


def verify_product_sources(value: Mapping[str, Any], store: Any) -> dict[str, Any]:
    """Re-read every retained listing ref and re-derive the sealed row views."""
    if not isinstance(value,Mapping):
        raise ValueError('ANNOUNCEMENT_CATALOG_PRODUCT_IDENTITY_INVALID')
    product = validate_product(value,target_trade_date=value.get('target_trade_date'),
        publication_date=value.get('publication_date'))
    refs: dict[int, dict[str, Any]] = {}
    for receipt in product.get('page_receipts', []):
        if not isinstance(receipt, dict):
            raise ValueError('ANNOUNCEMENT_CATALOG_PAGE_RECEIPT_INVALID')
        page = receipt.get('page_index')
        ref = receipt.get('source_ref')
        if ref is not None:
            if type(page) is not int or page in refs:
                raise ValueError('ANNOUNCEMENT_CATALOG_PAGE_REFERENCE_DUPLICATE')
            refs[page] = ref
    unused_refs=product.get('unused_resume_refs',{})
    if isinstance(unused_refs,Mapping):
        for page,ref in unused_refs.items():
            try:
                page_index=int(page)
            except (TypeError,ValueError):
                continue
            if type(page_index) is int and page_index >= 1 and page_index not in refs and isinstance(ref,Mapping):
                refs[page_index]=dict(ref)
    derived = collect_date_scoped_catalog(None, store,
        target_trade_date=product['target_trade_date'], publication_date=product['publication_date'],
        master_names={item['code']: {'name': item['name']} for item in _flatten_master_rows(product)},
        identity_witness=product['master_identity_witness'], resume_refs=refs,
        run_id=product['run_id'], generated_at=product['generated_at'])
    legacy_master_intersection = product.get('source_identity_basis') is None
    if legacy_master_intersection:
        derived['source_rows'] = [
            {key: deepcopy(value) for key, value in row.items() if key != 'source_issuer_codes'}
            for row in derived['source_rows']
        ]
        derived['manager_consumer_rows'] = [
            {key: deepcopy(value) for key, value in row.items() if key != 'source_issuer_codes'}
            for row in derived['manager_consumer_rows'] if row.get('matched_master_codes')
        ]
        derived['manager_consumer_row_count'] = len(derived['manager_consumer_rows'])
        derived['manager_matched_master_codes'] = sorted({
            item['code'] for row in derived['manager_consumer_rows'] for item in row['matched_master_codes']
        })
        for key in ('manager_source_codes', 'manager_source_identity_count', 'source_identity_basis',
                    'connect_eligibility_status', 'master_enrichment_status'):
            derived.pop(key, None)
        derived['manager_consumer_use'] = 'CODE_INTERSECTION_ONLY_NOT_SELECTION_RESULT'
    compare_keys = ('total_hits', 'expected_data_page_count', 'expected_terminal_page_index',
        'terminal_empty_seen', 'captured_page_count', 'captured_row_count', 'unique_art_code_count',
        'duplicate_art_codes', 'unused_resume_refs', 'source_rows', 'manager_consumer_rows', 'manager_consumer_row_count',
        'manager_matched_master_codes', 'master_scope_identity', 'master_scope_count',
        'display_notice_date_mismatch_count', 'display_notice_date_mismatches', 'gaps', 'status')
    if not legacy_master_intersection:
        compare_keys += ('manager_source_codes', 'manager_source_identity_count', 'source_identity_basis',
                         'connect_eligibility_status', 'master_enrichment_status')
    if any(derived.get(key) != product.get(key, {} if key == 'unused_resume_refs' else None)
           for key in compare_keys):
        raise ValueError('ANNOUNCEMENT_CATALOG_SOURCE_DERIVATION_MISMATCH')
    return derived


def _flatten_master_rows(product: Mapping[str, Any]) -> list[dict[str, Any]]:
    # A separate immutable name list is retained for full verification.
    names = product.get('master_names')
    if isinstance(names, dict) and len(names) == product.get('master_scope_count'):
        if not names and product.get('master_identity_witness') is None:
            return []
        return [dict(code=code, name=row.get('name')) for code, row in sorted(names.items())]
    raise ValueError('ANNOUNCEMENT_CATALOG_MASTER_NAMES_MISSING')
