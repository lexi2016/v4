#!/usr/bin/env python3
"""Freeze and capture the 41 missing-page-1 bodies under fixed per-document caps.

Network is only used by the explicit ``capture-41`` mode. It goes through the
existing Eastmoney provider/helper/shared MaterialStore, uses force=False, and
records one durable attempt plus one terminal receipt per exact URL.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

import capture_body_corpus as base

OUT = base.OUT
RUN_DIR = OUT / 'body_corpus_20260929_v2'
TARGET_PATH = OUT / 'missing_page1_targets_20260929_v2.json'
CANARY_ACCOUNTING_PATH = OUT / 'canary_capture_accounting_20260929_v2.json'
CANARY_ORIGINAL_PATH = OUT / 'missing_page1_canary_20260929.json'
CORPUS_V1_PATH = OUT / 'body_corpus_20260929.json'
TARGET_DATE = '2026-09-29'
EXCLUDED_CANARY_CODES = {
    'AN202609291830008202', 'AN202609291830006795', 'AN202609291830007157',
}
FROZEN_V1_SHA256 = '0978ae6fc652b2ee9ffda64575b642816046088c278416168bad39bd330a7ec4'
FROZEN_CANARY_SHA256 = '1f1f731384fbe4d5c3078a40f63b0c2293b83127bf432b5dc2b2a4f7fda4f3b5'
BATCH_SECONDS = 45.0
BATCH_REQUESTS = 57
BATCH_RESPONSE_BYTES = 64 * 1024 * 1024
PROVIDER_TIMEOUT_SECONDS = 20.0
ATTEMPT_POLICY = 'one exact URL attempt; durable marker precedes capture; terminal failure is never retried'
WORKSPACE_PYTHON = Path('/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3')


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_sha(value: Any) -> str:
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8'))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def durable_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.tmp')
    payload = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    with temp.open('w', encoding='utf-8') as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        pass


def _imports():
    api = base.imports()
    return api


def reconcile_original_canary() -> dict:
    """Verify the frozen per-URL canary responses and separate replay budget."""
    original_raw = CANARY_ORIGINAL_PATH.read_bytes()
    original_sha = sha(original_raw)
    if original_sha != FROZEN_CANARY_SHA256:
        raise ValueError('FROZEN_ORIGINAL_CANARY_SHA_MISMATCH')
    summary = json.loads(original_raw.decode('utf-8'))
    api = _imports()
    store, _provider = base.make_provider(api)
    urls: dict[str, dict] = {}
    for article in summary.get('results', []):
        receipts = list(article.get('content_receipts', []))
        if article.get('pdf_receipt'):
            receipts.append(article['pdf_receipt'])
        for receipt in receipts:
            url = receipt.get('request_url')
            ref = receipt.get('source_ref')
            if not isinstance(url, str) or not isinstance(ref, Mapping):
                raise ValueError('ORIGINAL_CANARY_RECEIPT_OR_REF_MISSING')
            if url in urls:
                prior = urls[url]
                if prior.get('source_ref') != ref:
                    raise ValueError('DUPLICATE_CANARY_URL_REF_CONFLICT')
                continue
            raw = api['read_eastmoney_response'](store, ref)
            raw_sha = sha(raw)
            if (ref.get('request', {}).get('url') != url or ref.get('http_status') != 200
                    or ref.get('from_cache') is not False or raw_sha != receipt.get('raw_body_sha256')
                    or len(raw) != receipt.get('response_bytes')):
                raise ValueError('ORIGINAL_CANARY_RESPONSE_RECEIPT_MISMATCH')
            urls[url] = {
                'art_code': receipt.get('art_code'), 'kind': receipt.get('kind'),
                'page_index': receipt.get('page_index'), 'request_url': url,
                'http_status': ref.get('http_status'), 'from_cache': ref.get('from_cache'),
                'response_bytes': len(raw), 'raw_body_sha256': raw_sha,
                'blob_sha256': ref.get('blob_sha256'), 'retrieved_at': ref.get('retrieved_at'),
            }
    if len(urls) != 7:
        raise ValueError('ORIGINAL_CANARY_UNIQUE_URL_COUNT_NOT_SEVEN')
    rows = sorted(urls.values(), key=lambda row: (row['art_code'], str(row['kind']), str(row['page_index'])))
    body_bytes = sum(row['response_bytes'] for row in rows)
    old_budget = summary.get('budget', {})
    if (body_bytes != 5_724_152 or max(row['response_bytes'] for row in rows) != 5_191_219
            or old_budget.get('requests_used') != 0 or old_budget.get('response_bytes_used') != 0):
        raise ValueError('ORIGINAL_CANARY_CAPTURE_ACCOUNTING_EXPECTATION_MISMATCH')
    result = {
        'schema': 'v4.manager_research.eastmoney_hk_canary_capture_accounting.v2',
        'status': 'PASS_SOURCE_URL_RECEIPT_ACCOUNTING',
        'target_notice_date': TARGET_DATE,
        'frozen_original_summary_path': str(CANARY_ORIGINAL_PATH),
        'frozen_original_summary_sha256': original_sha,
        'source_corpus_v1_sha256': FROZEN_V1_SHA256,
        'unique_source_url_count': len(rows),
        'provider_boundary_fetch_count_recorded_by_from_cache_false': sum(row['from_cache'] is False for row in rows),
        'all_http_200': all(row['http_status'] == 200 for row in rows),
        'all_from_cache_false': all(row['from_cache'] is False for row in rows),
        'captured_response_bytes': body_bytes,
        'max_response_bytes': max(row['response_bytes'] for row in rows),
        'aggregate_summary_budget_snapshot': {
            'requests_used': old_budget.get('requests_used'),
            'response_bytes_used': old_budget.get('response_bytes_used'),
            'interpretation': 'Later no-op replay budget snapshot; it is not the original per-URL capture total.',
        },
        'physical_http_hops': 'CANNOT_CONFIRM',
        'text_consistency_evidence_status': summary.get('text_consistency_evidence_status'),
        'text_consistency_reviewable_count': summary.get('text_consistency_reviewable_count'),
        'per_url_receipts': rows,
        'network_policy': 'Accounting only; this command makes no network request.',
    }
    if not result['all_http_200'] or not result['all_from_cache_false']:
        result['status'] = 'PARTIAL_SOURCE_URL_RECEIPT_ACCOUNTING'
    durable_json(CANARY_ACCOUNTING_PATH, result)
    corpus = json.loads(CORPUS_V1_PATH.read_text(encoding='utf-8'))
    if sha(CORPUS_V1_PATH.read_bytes()) != FROZEN_V1_SHA256:
        raise ValueError('FROZEN_BODY_CORPUS_V1_SHA_MISMATCH')
    interpretations = json.loads((OUT / 'six_interpretations_20260929.json').read_text(encoding='utf-8'))
    base.generate_readme(corpus, interpretations)
    return result


def freeze_targets() -> dict:
    """Write the exact 44-minus-3=41 frozen v1 target set once."""
    if TARGET_PATH.exists():
        existing = json.loads(TARGET_PATH.read_text(encoding='utf-8'))
        codes = {row.get('art_code') for row in existing.get('targets', [])}
        expected = {row['art_code'] for row in json.loads(CORPUS_V1_PATH.read_text())['rows']
                    if row.get('body_status') == 'MISSING_PAGE1'} - EXCLUDED_CANARY_CODES
        hashable = dict(existing)
        recorded_hash = hashable.pop('target_manifest_sha256', None)
        if (existing.get('source_corpus_sha256') != FROZEN_V1_SHA256 or codes != expected or len(codes) != 41
                or recorded_hash != canonical_sha(hashable)):
            raise ValueError('FROZEN_MISSING_PAGE1_TARGET_MANIFEST_MISMATCH')
        return existing
    corpus_raw = CORPUS_V1_PATH.read_bytes()
    if sha(corpus_raw) != FROZEN_V1_SHA256:
        raise ValueError('FROZEN_BODY_CORPUS_V1_SHA_MISMATCH')
    corpus = json.loads(corpus_raw.decode('utf-8'))
    source_manifest = json.loads((base.DATE_DIR / 'manifest.json').read_text(encoding='utf-8'))
    missing = [row for row in corpus.get('rows', []) if row.get('body_status') == 'MISSING_PAGE1']
    missing_codes = {row.get('art_code') for row in missing}
    if len(missing) != 44 or (missing_codes & EXCLUDED_CANARY_CODES) != EXCLUDED_CANARY_CODES:
        raise ValueError('MISSING_PAGE1_BASELINE_SCOPE_NOT_44_MINUS_3')
    targets = []
    for row in missing:
        if row.get('art_code') in EXCLUDED_CANARY_CODES:
            continue
        targets.append({
            'art_code': row.get('art_code'), 'title': row.get('title'),
            'matched_master_codes': row.get('matched_master_codes', []),
            'hk_source_stock_codes_116': row.get('hk_source_stock_codes_116', []),
            'listing_evidence': row.get('listing_evidence'),
        })
    if len(targets) != 41 or len({row['art_code'] for row in targets}) != 41:
        raise ValueError('MISSING_PAGE1_FROZEN_TARGET_COUNT_INVALID')
    body = {
        'schema': 'v4.manager_research.eastmoney_hk_missing_page1_targets.v2',
        'target_notice_date': TARGET_DATE,
        'source_corpus_path': str(CORPUS_V1_PATH),
        'source_corpus_sha256': FROZEN_V1_SHA256,
        'source_catalog_manifest_sha256': corpus.get('source_listing_manifest_sha256'),
        'canary_summary_path': str(CANARY_ORIGINAL_PATH),
        'canary_summary_sha256': FROZEN_CANARY_SHA256,
        'target_rule': 'v1 body_status=MISSING_PAGE1, excluding exactly the three separately captured canaries',
        'original_missing_page1_count': len(missing),
        'excluded_canary_codes': sorted(EXCLUDED_CANARY_CODES),
        'target_count': len(targets), 'targets': targets,
    }
    body['target_manifest_sha256'] = canonical_sha(body)
    durable_json(TARGET_PATH, body)
    return body


def _url_paths(url: str) -> tuple[Path, Path, str]:
    key = sha(url.encode('utf-8'))
    return RUN_DIR / 'attempts' / f'{key}.attempt.json', RUN_DIR / 'receipts' / f'{key}.json', key


def capture_url_once(api, store, provider, *, art_code: str, kind: str,
                     page_index: int | str, url: str, budget, batch_run_id: str) -> dict:
    if not api['_safe_eastmoney_url'](url):
        return {'schema': 'eastmoney_body_v2_url_receipt.v1', 'art_code': art_code,
            'kind': kind, 'page_index': page_index, 'request_url': url,
            'status': 'URL_UNSAFE_NO_ATTEMPT', 'batch_run_id': batch_run_id}
    marker_path, receipt_path, url_sha = _url_paths(url)
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipt.get('request_url') != url:
            raise ValueError('V2_URL_RECEIPT_KEY_COLLISION')
        if isinstance(receipt.get('source_ref'), Mapping):
            raw = api['read_eastmoney_response'](store, receipt['source_ref'])
            if sha(raw) != receipt.get('raw_body_sha256') or len(raw) != receipt.get('response_bytes'):
                raise ValueError('V2_EXISTING_URL_RECEIPT_READBACK_MISMATCH')
        return receipt
    if marker_path.exists():
        receipt = {'schema': 'eastmoney_body_v2_url_receipt.v1', 'art_code': art_code,
            'kind': kind, 'page_index': page_index, 'request_url': url,
            'request_url_sha256': url_sha, 'status': 'ATTEMPT_INDETERMINATE_NO_RETRY',
            'error': 'PRIOR_ATTEMPT_MARKER_WITHOUT_TERMINAL_RECEIPT',
            'attempt_path': str(marker_path), 'batch_run_id': batch_run_id,
            'retrieved_at': None}
        durable_json(receipt_path, receipt)
        return receipt
    if budget.elapsed_seconds >= budget.seconds or budget.requests >= budget.max_requests:
        return {'schema': 'eastmoney_body_v2_url_receipt.v1', 'art_code': art_code,
            'kind': kind, 'page_index': page_index, 'request_url': url,
            'request_url_sha256': url_sha, 'status': 'NOT_ATTEMPTED_BUDGET_BOUNDARY',
            'batch_run_id': batch_run_id}
    # Reserve the largest legal single response so the cooperative total cap
    # cannot be crossed by a response of unknown size.
    if (budget.max_response_bytes is not None
            and budget.response_bytes + api['MAX_EASTMONEY_RESPONSE_BYTES'] > budget.max_response_bytes):
        return {'schema': 'eastmoney_body_v2_url_receipt.v1', 'art_code': art_code,
            'kind': kind, 'page_index': page_index, 'request_url': url,
            'request_url_sha256': url_sha, 'status': 'NOT_ATTEMPTED_RESPONSE_BUDGET_BOUNDARY',
            'batch_run_id': batch_run_id}
    marker = {'schema': 'eastmoney_body_v2_url_attempt.v1', 'art_code': art_code,
        'kind': kind, 'page_index': page_index, 'request_url': url,
        'request_url_sha256': url_sha, 'batch_run_id': batch_run_id,
        'started_at': now_utc(), 'force': False,
        'provider_timeout_seconds': PROVIDER_TIMEOUT_SECONDS,
        'one_attempt_only': True, 'attempt_policy': ATTEMPT_POLICY}
    durable_json(marker_path, marker)
    receipt = {'schema': 'eastmoney_body_v2_url_receipt.v1', 'art_code': art_code,
        'kind': kind, 'page_index': page_index, 'request_url': url,
        'request_url_sha256': url_sha, 'attempt_path': str(marker_path),
        'batch_run_id': batch_run_id, 'started_at': marker['started_at']}
    try:
        ref = api['capture_eastmoney'](provider, url, budget=budget, force=False)
        raw = api['read_eastmoney_response'](store, ref)
        budget.record_response_bytes(len(raw))
        receipt.update(source_ref=ref, raw_body_sha256=sha(raw), response_bytes=len(raw),
            http_status=ref.get('http_status'), from_cache=ref.get('from_cache'),
            retrieved_at=ref.get('retrieved_at'), final_url=ref.get('final_url'),
            status='CAPTURED' if ref.get('http_status') == 200 else 'HTTP_FAILED')
        if kind == 'content' and ref.get('http_status') == 200:
            try:
                detail = base.parse_content(raw)
                text = detail.get('notice_content')
                receipt['content_metadata'] = {
                    'art_code': detail.get('art_code'), 'notice_title': detail.get('notice_title'),
                    'notice_date': detail.get('notice_date'), 'display_time': detail.get('eitime'),
                    'page_total': detail.get('page_size'), 'attachment_url': detail.get('attach_url_web'),
                    'text_characters': len(text) if isinstance(text, str) else None,
                    'text_sha256': sha(text.encode('utf-8')) if isinstance(text, str) else None,
                    'notice_content': text if isinstance(text, str) else None,
                }
                if not isinstance(text, str) or not text.strip():
                    receipt['status'] = 'CONTENT_TEXT_MISSING'
                elif detail.get('art_code') != art_code or base.notice_day(detail.get('notice_date')) != TARGET_DATE:
                    receipt['status'] = 'CONTENT_IDENTITY_OR_DATE_MISMATCH'
            except Exception as exc:
                receipt.update(status='CONTENT_PARSE_FAILED',
                    error=api['safe_reason'](exc, 'CONTENT_PARSE_FAILED'))
        elif kind == 'pdf' and ref.get('http_status') == 200:
            receipt['pdf_signature_valid'] = raw.startswith(b'%PDF')
            receipt['pdf_sha256'] = sha(raw)
            if not receipt['pdf_signature_valid']:
                receipt['status'] = 'INVALID_PDF_BYTES'
    except Exception as exc:
        receipt.update(status='CAPTURE_FAILED',
            error=api['safe_reason'](exc, 'BODY_V2_CAPTURE_FAILED'), failed_at=now_utc())
    durable_json(receipt_path, receipt)
    return receipt


def _receipt_for_url(url: str) -> dict | None:
    _marker, receipt_path, _key = _url_paths(url)
    if not receipt_path.exists():
        return None
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('request_url') != url:
        raise ValueError('V2_URL_RECEIPT_KEY_COLLISION')
    return receipt


def capture_one_document(api, store, provider, target: Mapping[str, Any], batch_run_id: str) -> dict:
    art = str(target.get('art_code', ''))
    budget = api['CaptureBudget'](seconds=BATCH_SECONDS, max_requests=BATCH_REQUESTS,
        interval=0.5, max_response_bytes=BATCH_RESPONSE_BYTES)
    page_receipts: list[dict] = []
    issues: list[str] = []
    content_issues: list[str] = []
    pages: list[dict] = []
    expected_total: int | None = None
    attachment_url: str | None = None
    page1_url = api['eastmoney_content_url'](art, page_index=1)
    first = capture_url_once(api, store, provider, art_code=art, kind='content',
        page_index=1, url=page1_url, budget=budget, batch_run_id=batch_run_id)
    page_receipts.append(first)
    metadata = first.get('content_metadata')
    if first.get('status') not in {'CAPTURED'} or not isinstance(metadata, Mapping):
        issue = f'PAGE1_{first.get("status", "MISSING")}: {first.get("error", "")}'.strip()
        issues.append(issue)
        content_issues.append(issue)
        if (isinstance(metadata, Mapping) and metadata.get('art_code') == art
                and base.notice_day(metadata.get('notice_date')) == TARGET_DATE):
            attachment_url = metadata.get('attachment_url') if isinstance(metadata.get('attachment_url'), str) else None
    else:
        expected_total = metadata.get('page_total') if type(metadata.get('page_total')) is int else None
        attachment_url = metadata.get('attachment_url') if isinstance(metadata.get('attachment_url'), str) else None
        pages.append(metadata)
        if expected_total is None:
            issues.append('PAGE1_TOTAL_INVALID')
            content_issues.append('PAGE1_TOTAL_INVALID')
        elif expected_total > api['MAX_EASTMONEY_CONTENT_PAGES']:
            issues.append('OVER_CONTENT_PAGE_LIMIT')
            content_issues.append('OVER_CONTENT_PAGE_LIMIT')
        elif (metadata.get('text_characters') or 0) > api['MAX_EASTMONEY_BODY_CHARACTERS']:
            issues.append('OVER_CONTENT_TEXT_LIMIT')
            content_issues.append('OVER_CONTENT_TEXT_LIMIT')
        else:
            for page_index in range(2, expected_total + 1):
                url = api['eastmoney_content_url'](art, page_index=page_index)
                receipt = capture_url_once(api, store, provider, art_code=art, kind='content',
                    page_index=page_index, url=url, budget=budget, batch_run_id=batch_run_id)
                page_receipts.append(receipt)
                page_meta = receipt.get('content_metadata')
                if receipt.get('status') != 'CAPTURED' or not isinstance(page_meta, Mapping):
                    issue = f'PAGE_{page_index}_{receipt.get("status", "MISSING")}'
                    issues.append(issue)
                    content_issues.append(issue)
                    break
                if page_meta.get('page_total') != expected_total:
                    issues.append(f'PAGE_{page_index}_TOTAL_DRIFT')
                    content_issues.append(f'PAGE_{page_index}_TOTAL_DRIFT')
                    break
                pages.append(page_meta)
                total_chars = sum(int(item.get('text_characters') or 0) for item in pages)
                if total_chars > api['MAX_EASTMONEY_BODY_CHARACTERS']:
                    issues.append('OVER_CONTENT_TEXT_LIMIT')
                    content_issues.append('OVER_CONTENT_TEXT_LIMIT')
                    break
    pdf_receipt = None
    if attachment_url and api['_safe_eastmoney_url'](attachment_url):
        pdf_receipt = capture_url_once(api, store, provider, art_code=art, kind='pdf',
            page_index='pdf', url=attachment_url, budget=budget, batch_run_id=batch_run_id)
    elif attachment_url:
        issues.append('PDF_ATTACHMENT_URL_UNSAFE')
    elif metadata and first.get('status') == 'CAPTURED':
        issues.append('PDF_ATTACHMENT_URL_MISSING')
    texts = [str(page.get('notice_content') or '') for page in pages]
    text_chars = sum(len(text) for text in texts)
    present_indexes = [int(receipt['page_index']) for receipt in page_receipts
        if receipt.get('kind') == 'content' and receipt.get('status') == 'CAPTURED'
        and isinstance(receipt.get('content_metadata'), Mapping)]
    body_status = 'CONTENT_PAGES_INCOMPLETE_OR_INVALID'
    if 'OVER_CONTENT_PAGE_LIMIT' in issues:
        body_status = 'OVER_CONTENT_PAGE_LIMIT'
    elif 'OVER_CONTENT_TEXT_LIMIT' in issues or text_chars > api['MAX_EASTMONEY_BODY_CHARACTERS']:
        body_status = 'OVER_CONTENT_TEXT_LIMIT'
    elif (expected_total is not None and expected_total <= api['MAX_EASTMONEY_CONTENT_PAGES']
            and present_indexes == list(range(1, expected_total + 1)) and not content_issues):
        body_status = 'COMPLETE_CONTENT_API_BODY'
    elif not first.get('content_metadata'):
        body_status = 'MISSING_PAGE1'
    if pdf_receipt is None:
        pdf_status = 'PDF_URL_MISSING_OR_UNSAFE'
    elif pdf_receipt.get('status') == 'CAPTURED' and pdf_receipt.get('pdf_signature_valid'):
        pdf_status = 'VALID_PDF_BYTES'
    elif pdf_receipt.get('status') == 'HTTP_FAILED':
        pdf_status = 'PDF_HTTP_FAILED'
    else:
        pdf_status = pdf_receipt.get('status', 'PDF_CAPTURE_FAILED')
    page1_terminal = first.get('status') not in {
        'NOT_ATTEMPTED_BUDGET_BOUNDARY', 'NOT_ATTEMPTED_RESPONSE_BUDGET_BOUNDARY', 'URL_UNSAFE_NO_ATTEMPT'}
    if expected_total is not None and expected_total <= api['MAX_EASTMONEY_CONTENT_PAGES'] and metadata:
        content_terminal = (present_indexes == list(range(1, expected_total + 1)) or
            any(receipt.get('status') in {'CAPTURE_FAILED', 'HTTP_FAILED', 'CONTENT_PARSE_FAILED',
                'CONTENT_TEXT_MISSING', 'CONTENT_IDENTITY_OR_DATE_MISMATCH', 'ATTEMPT_INDETERMINATE_NO_RETRY'}
                for receipt in page_receipts))
    else:
        content_terminal = page1_terminal
    pdf_required = bool(attachment_url and api['_safe_eastmoney_url'](attachment_url))
    pdf_terminal = (not pdf_required or (pdf_receipt is not None and pdf_receipt.get('status') not in {
        'NOT_ATTEMPTED_BUDGET_BOUNDARY', 'NOT_ATTEMPTED_RESPONSE_BUDGET_BOUNDARY', 'URL_UNSAFE_NO_ATTEMPT'}))
    capture_attempts_accounted = page1_terminal and content_terminal and pdf_terminal
    document = {
        'art_code': art, 'title': target.get('title'),
        'matched_master_codes': target.get('matched_master_codes', []),
        'hk_source_stock_codes_116': target.get('hk_source_stock_codes_116', []),
        'listing_evidence': target.get('listing_evidence'),
        'body_status': body_status, 'content_page_count': expected_total,
        'present_page_indexes': present_indexes,
        'body_text_characters': text_chars,
        'body_text_sha256': sha('\n\n'.join(texts).encode('utf-8')) if body_status == 'COMPLETE_CONTENT_API_BODY' else None,
        'body_text': '\n\n'.join(texts) if body_status == 'COMPLETE_CONTENT_API_BODY' else None,
        'pages': [{'page_index': idx + 1, 'text': page.get('notice_content'),
            'text_sha256': page.get('text_sha256'), 'source_receipt_url': page_receipts[idx].get('request_url'),
            'source_ref': page_receipts[idx].get('source_ref'), 'retrieved_at': page_receipts[idx].get('retrieved_at'),
            'notice_date': page.get('notice_date'), 'display_time': page.get('display_time')}
            for idx, page in enumerate(pages)],
        'content_receipt_urls': [receipt.get('request_url') for receipt in page_receipts],
        'content_receipt_statuses': [receipt.get('status') for receipt in page_receipts],
        'attachment_url': attachment_url,
        'pdf_status': pdf_status,
        'pdf_ref': (pdf_receipt or {}).get('source_ref'),
        'pdf_bytes': (pdf_receipt or {}).get('response_bytes'),
        'pdf_sha256': (pdf_receipt or {}).get('pdf_sha256'),
        'pdf_receipt_url': (pdf_receipt or {}).get('request_url'),
        'capture_issues': sorted(set(issues)),
        'capture_attempts_accounted': capture_attempts_accounted,
        'document_budget': {'seconds': budget.seconds, 'max_requests': budget.max_requests,
            'max_response_bytes': budget.max_response_bytes, 'requests_used': budget.requests,
            'response_bytes_used': budget.response_bytes, 'elapsed_seconds': round(budget.elapsed_seconds, 3),
            'provider_boundary_requests': budget.requests},
    }
    durable_json(RUN_DIR / 'documents' / f'{art}.json', document)
    return document


def derive_v2_outputs(target_manifest: Mapping[str, Any]) -> dict:
    corpus_v1 = json.loads(CORPUS_V1_PATH.read_text(encoding='utf-8'))
    v1_by = {row['art_code']: row for row in corpus_v1.get('rows', [])}
    targets = {row['art_code']: row for row in target_manifest.get('targets', [])}
    document_results = {}
    for art in targets:
        path = RUN_DIR / 'documents' / f'{art}.json'
        if path.exists():
            document_results[art] = json.loads(path.read_text(encoding='utf-8'))
    rows = []
    for old in corpus_v1.get('rows', []):
        replacement = document_results.get(old['art_code'])
        rows.append({**old, **replacement} if replacement else old)
    body_counts = Counter(row.get('body_status') for row in rows)
    pdf_counts = Counter(row.get('pdf_status') for row in rows)
    processed = len(document_results)
    accounting_complete = processed == len(targets) and all(
        row.get('body_status') in {'COMPLETE_CONTENT_API_BODY', 'OVER_CONTENT_PAGE_LIMIT', 'OVER_CONTENT_TEXT_LIMIT'}
        and row.get('pdf_status') in {'VALID_PDF_BYTES', 'PDF_HTTP_FAILED', 'INVALID_PDF_BYTES', 'PDF_URL_MISSING_OR_UNSAFE', 'CAPTURE_FAILED'}
        for row in document_results.values())
    capture_run = json.loads((RUN_DIR / 'capture_manifest.json').read_text(encoding='utf-8')) if (RUN_DIR / 'capture_manifest.json').exists() else {}
    result = {
        'schema': 'v4.manager_research.eastmoney_hk_body_corpus.v2',
        'status': 'PASS_41_TARGETS_RECONCILED' if accounting_complete else 'PARTIAL_41_TARGETS_RECONCILED',
        'target_notice_date': TARGET_DATE,
        'source_scope': 'EASTMONEY_HK_DATE_CATALOG',
        'source_listing_status': corpus_v1.get('source_listing_status'),
        'source_corpus_v1_sha256': FROZEN_V1_SHA256,
        'target_manifest_sha256': target_manifest.get('target_manifest_sha256'),
        'canary_summary_v1_sha256': FROZEN_CANARY_SHA256,
        'article_count': len(rows), 'updated_target_count': processed,
        'body_status_counts': dict(body_counts), 'pdf_status_counts': dict(pdf_counts),
        'capture_run': capture_run,
        'retrieved_at_range': _retrieval_range(rows),
        'interpretation': '独立版本保留v1基线，并仅替换冻结41篇缺首页目标的正文/PDF来源回执；这不是新权威源、PIT重建或语义结论。',
        'rows': rows,
    }
    durable_json(OUT / 'body_corpus_20260929_v2.json', result)
    fields = ['art_code', 'title', 'body_status', 'content_page_count', 'present_page_indexes',
        'body_text_characters', 'body_text_sha256', 'pdf_status', 'pdf_bytes', 'pdf_sha256',
        'listing_page_index', 'listing_retrieved_at', 'listing_raw_body_sha256']
    with (OUT / 'body_corpus_20260929_v2.csv').open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            listing = row.get('listing_evidence', {})
            writer.writerow({'art_code': row.get('art_code'), 'title': row.get('title'),
                'body_status': row.get('body_status'), 'content_page_count': row.get('content_page_count'),
                'present_page_indexes': ','.join(map(str, row.get('present_page_indexes', []))),
                'body_text_characters': row.get('body_text_characters'), 'body_text_sha256': row.get('body_text_sha256'),
                'pdf_status': row.get('pdf_status'), 'pdf_bytes': row.get('pdf_bytes'), 'pdf_sha256': row.get('pdf_sha256'),
                'listing_page_index': listing.get('page_index'), 'listing_retrieved_at': listing.get('retrieved_at'),
                'listing_raw_body_sha256': listing.get('raw_body_sha256')})
    return result


def _retrieval_range(rows: list[dict]) -> dict:
    values = []
    for row in rows:
        for page in row.get('pages', []):
            if page.get('retrieved_at'):
                values.append(page['retrieved_at'])
        pdf_ref = row.get('pdf_ref') or {}
        if pdf_ref.get('retrieved_at'):
            values.append(pdf_ref['retrieved_at'])
    return {'first': min(values) if values else None, 'last': max(values) if values else None}


def run_capture_41() -> dict:
    manifest = freeze_targets()
    api = _imports()
    store, provider = base.make_provider(api)
    if provider._timeout != PROVIDER_TIMEOUT_SECONDS:
        raise ValueError('PROVIDER_TIMEOUT_CHANGED')
    original_request = provider._request_eastmoney_hk
    def request_with_timeout_cap(url, *, timeout):
        return original_request(url, timeout=min(float(timeout), PROVIDER_TIMEOUT_SECONDS))
    provider._request_eastmoney_hk = request_with_timeout_cap
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    documents = []
    for index, target in enumerate(manifest['targets'], 1):
        document = capture_one_document(api, store, provider, target, run_id)
        documents.append(document)
        print(json.dumps({'progress': f'{index}/{manifest["target_count"]}', 'art_code': document['art_code'],
            'body_status': document['body_status'], 'pdf_status': document['pdf_status'],
            'requests_used': document['document_budget']['requests_used'],
            'response_bytes_used': document['document_budget']['response_bytes_used']}, ensure_ascii=False), flush=True)
    all_receipts = []
    for path in sorted((RUN_DIR / 'receipts').glob('*.json')):
        all_receipts.append(json.loads(path.read_text(encoding='utf-8')))
    receipt_urls = [row.get('request_url') for row in all_receipts]
    unique_urls = len(set(receipt_urls)) == len(receipt_urls)
    body_counts = Counter(row.get('body_status') for row in documents)
    pdf_counts = Counter(row.get('pdf_status') for row in documents)
    current_run = {
        'schema': 'v4.manager_research.eastmoney_hk_body_v2_capture_manifest.v1',
        'run_id': run_id,
        'status': 'PASS_RUN_COMPLETE' if len(documents) == 41 else 'PARTIAL_RUN',
        'target_notice_date': TARGET_DATE, 'target_manifest_path': str(TARGET_PATH),
        'target_manifest_sha256': manifest.get('target_manifest_sha256'),
        'source_corpus_v1_sha256': FROZEN_V1_SHA256,
        'target_count': manifest.get('target_count'), 'processed_count': len(documents),
        'document_budget_policy': {'seconds_per_document': BATCH_SECONDS,
            'max_provider_boundary_requests_per_document': BATCH_REQUESTS,
        'max_response_bytes_per_document': BATCH_RESPONSE_BYTES,
        'max_single_response_bytes': api['MAX_EASTMONEY_RESPONSE_BYTES'],
            'provider_timeout_seconds': PROVIDER_TIMEOUT_SECONDS,
            'max_content_pages': api['MAX_EASTMONEY_CONTENT_PAGES'],
            'attempt_policy': ATTEMPT_POLICY},
        'url_receipt_count': len(all_receipts), 'url_receipt_urls_unique': unique_urls,
        'provider_boundary_requests_this_run': sum(row['document_budget']['provider_boundary_requests'] for row in documents),
        'response_bytes_this_run': sum(row['document_budget']['response_bytes_used'] for row in documents),
        'physical_http_hops': 'CANNOT_CONFIRM',
        'body_status_counts': dict(body_counts), 'pdf_status_counts': dict(pdf_counts),
        'document_runs': documents,
        'no_retry_note': 'Existing terminal receipts are read back; marker-without-receipt is terminal indeterminate; failed URLs are not retried.',
    }
    durable_json(RUN_DIR / 'runs' / f'{run_id}.json', current_run)
    terminal_receipts = [row for row in all_receipts if row.get('status') not in {
        'NOT_ATTEMPTED_BUDGET_BOUNDARY', 'NOT_ATTEMPTED_RESPONSE_BUDGET_BOUNDARY', 'URL_UNSAFE_NO_ATTEMPT'}]
    attempts_complete = len(documents) == 41 and all(row.get('capture_attempts_accounted') for row in documents)
    result = {
        'schema': 'v4.manager_research.eastmoney_hk_body_v2_capture_manifest.v1',
        'status': 'PASS_41_TARGETS_RECONCILED' if attempts_complete and unique_urls else 'PARTIAL_41_TARGETS_RECONCILED',
        'target_notice_date': TARGET_DATE, 'target_manifest_path': str(TARGET_PATH),
        'target_manifest_sha256': manifest.get('target_manifest_sha256'),
        'source_corpus_v1_sha256': FROZEN_V1_SHA256,
        'target_count': manifest.get('target_count'), 'processed_count': len(documents),
        'current_run_id': run_id, 'current_run_receipt_path': str(RUN_DIR / 'runs' / f'{run_id}.json'),
        'document_budget_policy': current_run['document_budget_policy'],
        'url_receipt_count': len(terminal_receipts), 'url_receipt_urls_unique': unique_urls,
        'provider_boundary_fetch_count_cumulative': sum(row.get('from_cache') is False for row in terminal_receipts),
        'response_bytes_cumulative': sum(int(row.get('response_bytes') or 0) for row in terminal_receipts),
        'provider_boundary_requests_this_run': current_run['provider_boundary_requests_this_run'],
        'response_bytes_this_run': current_run['response_bytes_this_run'],
        'physical_http_hops': 'CANNOT_CONFIRM',
        'body_status_counts': dict(body_counts), 'pdf_status_counts': dict(pdf_counts),
        'document_runs': documents,
        'no_retry_note': current_run['no_retry_note'],
    }
    durable_json(RUN_DIR / 'capture_manifest.json', result)
    derived = derive_v2_outputs(manifest)
    # The README is regenerated only after the corrected historical accounting exists.
    corpus_v1 = json.loads(CORPUS_V1_PATH.read_text(encoding='utf-8'))
    interpretations = json.loads((OUT / 'six_interpretations_20260929.json').read_text(encoding='utf-8'))
    base.generate_readme(corpus_v1, interpretations)
    return {'status': result['status'], 'capture_manifest_status': result['status'], 'body_corpus_v2_status': derived['status'],
        'target_count': result['target_count'], 'processed_count': result['processed_count'],
        'body_status_counts': result['body_status_counts'], 'pdf_status_counts': result['pdf_status_counts'],
        'provider_boundary_requests_this_run': result['provider_boundary_requests_this_run'],
        'response_bytes_this_run': result['response_bytes_this_run']}


def run_first_document_canary() -> dict:
    manifest = freeze_targets()
    api = _imports()
    store, provider = base.make_provider(api)
    if provider._timeout != PROVIDER_TIMEOUT_SECONDS:
        raise ValueError('PROVIDER_TIMEOUT_CHANGED')
    original_request = provider._request_eastmoney_hk
    def request_with_timeout_cap(url, *, timeout):
        return original_request(url, timeout=min(float(timeout), PROVIDER_TIMEOUT_SECONDS))
    provider._request_eastmoney_hk = request_with_timeout_cap
    run_id = 'CANARY_' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    document = capture_one_document(api, store, provider, manifest['targets'][0], run_id)
    result = {
        'schema': 'v4.manager_research.eastmoney_hk_body_v2_first_document_canary.v1',
        'status': 'PASS_FIRST_DOCUMENT_BOUNDED_CAPTURE' if document.get('capture_attempts_accounted')
            and document.get('body_status') in {'COMPLETE_CONTENT_API_BODY', 'OVER_CONTENT_PAGE_LIMIT', 'OVER_CONTENT_TEXT_LIMIT'}
            else 'PARTIAL_FIRST_DOCUMENT_CANARY',
        'target_manifest_sha256': manifest.get('target_manifest_sha256'),
        'per_document_limits': {'seconds': BATCH_SECONDS, 'requests': BATCH_REQUESTS,
            'response_bytes': BATCH_RESPONSE_BYTES, 'single_response_bytes': api['MAX_EASTMONEY_RESPONSE_BYTES'],
            'provider_timeout_seconds': PROVIDER_TIMEOUT_SECONDS,
            'content_pages': api['MAX_EASTMONEY_CONTENT_PAGES']},
        'physical_http_hops': 'CANNOT_CONFIRM', 'document': document,
    }
    durable_json(RUN_DIR / 'runs' / 'first_document_canary.json', result)
    return {'status': result['status'], 'art_code': document['art_code'],
        'body_status': document['body_status'], 'pdf_status': document['pdf_status'],
        'capture_attempts_accounted': document['capture_attempts_accounted'],
        'requests_used': document['document_budget']['requests_used'],
        'response_bytes_used': document['document_budget']['response_bytes_used'],
        'receipt_path': str(RUN_DIR / 'runs' / 'first_document_canary.json')}


def derive_pdf_text_canary() -> dict:
    """Locally extract the saved 333-page canary PDF into <=120k char segments."""
    api = _imports()
    store, _provider = base.make_provider(api)
    summary = json.loads(CANARY_ORIGINAL_PATH.read_text(encoding='utf-8'))
    if sha(CANARY_ORIGINAL_PATH.read_bytes()) != FROZEN_CANARY_SHA256:
        raise ValueError('FROZEN_ORIGINAL_CANARY_SHA_MISMATCH')
    sample = next(row for row in summary['results'] if row.get('art_code') == 'AN202609291830006795')
    receipt = sample.get('pdf_receipt') or {}
    ref = receipt.get('source_ref')
    if not isinstance(ref, Mapping):
        raise ValueError('SAVED_PDF_CANARY_REF_MISSING')
    raw = api['read_eastmoney_response'](store, ref)
    pdf_sha = sha(raw)
    if pdf_sha != receipt.get('pdf_sha256') or not raw.startswith(b'%PDF'):
        raise ValueError('SAVED_PDF_CANARY_HASH_OR_SIGNATURE_INVALID')
    # pypdfium2 is present in the bundled workspace Python (the application
    # runtime intentionally does not install it). Send verified PDF bytes over
    # stdin so this local read-only parse creates no sidecar source file.
    extract_code = r'''import json,sys
import pypdfium2 as pdfium
raw=sys.stdin.buffer.read()
doc=pdfium.PdfDocument(raw)
pages=[]
for idx in range(len(doc)):
    page=doc.get_page(idx)
    textpage=page.get_textpage()
    text=textpage.get_text_range() or ""
    pages.append(text)
    textpage.close()
    page.close()
doc.close()
sys.stdout.write(json.dumps({"pages":pages},ensure_ascii=False,separators=(",",":")))
'''
    if not WORKSPACE_PYTHON.is_file():
        raise RuntimeError('WORKSPACE_PYPDFIUM2_RUNTIME_UNAVAILABLE')
    extracted = subprocess.run([str(WORKSPACE_PYTHON), '-c', extract_code], input=raw,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180, check=False)
    if extracted.returncode != 0:
        raise RuntimeError('PYPDFIUM2_LOCAL_EXTRACTION_FAILED:' + extracted.stderr.decode('utf-8', 'replace')[-500:])
    parsed = json.loads(extracted.stdout.decode('utf-8'))
    raw_pages = parsed.get('pages')
    if not isinstance(raw_pages, list) or any(not isinstance(text, str) for text in raw_pages):
        raise RuntimeError('PYPDFIUM2_PAGE_TEXT_SHAPE_INVALID')
    page_count = len(raw_pages)
    page_limit = api['MAX_EASTMONEY_BODY_CHARACTERS']
    page_rows = []
    segments = []
    full_parts = []
    for page_index, text in enumerate(raw_pages):
        full_parts.append(text)
        page_sha = sha(text.encode('utf-8'))
        segment_ids = []
        offsets = range(0, len(text), page_limit) if text else [0]
        for start in offsets:
            chunk = text[start:start + page_limit]
            segment = {'segment_index': len(segments) + 1, 'page_start': page_index + 1,
                'page_end': page_index + 1, 'page_index': page_index + 1,
                'character_start': start, 'character_end': start + len(chunk),
                'text_characters': len(chunk), 'text_sha256': sha(chunk.encode('utf-8')),
                'text': chunk}
            segments.append(segment)
            segment_ids.append(segment['segment_index'])
        page_rows.append({'page_index': page_index + 1, 'text_characters': len(text),
            'text_sha256': page_sha, 'segment_indexes': segment_ids})
    joined = '\n\n'.join(full_parts)
    covered = sorted({segment['page_index'] for segment in segments})
    if page_count != 333 or covered != list(range(1, 334)) or any(s['text_characters'] > page_limit for s in segments):
        raise ValueError('PDF_TEXT_CANARY_PAGE_OR_SEGMENT_COVERAGE_INVALID')
    result = {
        'schema': 'v4.manager_research.eastmoney_hk_pdf_physical_text_canary.v2',
        'status': 'PASS_LOCAL_FULL_PHYSICAL_PAGE_COVERAGE',
        'art_code': sample['art_code'], 'target_notice_date': TARGET_DATE,
        'pdf_source_ref': ref, 'pdf_sha256': pdf_sha, 'pdf_bytes': len(raw),
        'pdf_page_count': page_count, 'extraction': 'local pypdfium2 only; no content fetch, network or LLM',
        'segment_character_limit': page_limit,
        'full_text_characters': len(joined), 'full_text_sha256': sha(joined.encode('utf-8')),
        'full_page_coverage': covered,
        'pages': page_rows, 'segments': segments,
    }
    durable_json(OUT / 'pdf_text_canary_20260929_AN202609291830006795_v2.json', result)
    return {'status': result['status'], 'pdf_sha256': pdf_sha,
        'pdf_page_count': page_count, 'segment_count': len(segments),
        'full_text_characters': len(joined), 'full_text_sha256': result['full_text_sha256']}


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else 'help'
    if mode == 'reconcile-canary':
        result = reconcile_original_canary()
    elif mode == 'freeze-targets':
        result = freeze_targets()
    elif mode == 'capture-41':
        result = run_capture_41()
    elif mode == 'capture-first':
        result = run_first_document_canary()
    elif mode == 'derive-pdf-text-canary':
        result = derive_pdf_text_canary()
    else:
        print('usage: capture_missing_page1_v2.py [reconcile-canary|freeze-targets|capture-first|capture-41|derive-pdf-text-canary]', file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    passed = result.get('status', '').startswith('PASS') or (mode == 'freeze-targets' and result.get('target_count') == 41)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
