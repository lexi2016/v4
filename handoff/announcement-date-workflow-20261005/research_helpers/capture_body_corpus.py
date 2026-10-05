#!/usr/bin/env python3
"""Build a date-scoped HK announcement body corpus from existing source refs.

Inventory is read-only against the existing shared MaterialStore.  The only
network-enabled mode is the fixed three-article canary, and every request is
made through the existing Eastmoney helper/provider/store with a durable
attempt marker and terminal receipt.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, urlsplit

REPO = Path('/Users/lexi/Desktop/学习/v4_app')
DIAG = Path('/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_SELECTION_PATH_DIAG_20261005')
DATE_DIR = DIAG / 'date_scoped_collection'
OUT = DIAG / 'announcement_understanding'
STORE_ROOT = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/materials')
PYTHON_RUNTIME = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python')

CANARY_CODES = (
    'AN202609291830008202',  # 股份购回翌日披露报表
    'AN202609291830006795',  # 中期业绩报告
    'AN202609291830007157',  # A股董事会决议海外监管公告
)
SIX_CODES = (
    'AN202609291829998939',
    'AN202609291829996809',
    'AN202609291829976776',
    'AN202609291830002096',
    'AN202609291829976846',
    'AN202609291830000678',
)
EXPECTED_PDF_SHA256 = {
    'AN202609291829998939': 'b59e8ac3509f96c9c0ae1050037130ff81c22f8c5f89ed00a08017cb175cf667',
    'AN202609291829996809': '4f1db39c9555de8e0419792770c6e83af22d5eebc1debc3f23f3d37c5c418a01',
    'AN202609291829976776': 'ee31a2a9756794955f850d2dec4bcb7b477ba61103f69f5036c811e2f43fa486',
    'AN202609291830002096': '46d3e4b95240c7f9ad22dc0bee4f083a240f12371d3c96f8aba585397f3ef574',
    'AN202609291829976846': 'f5707149722b4f50cc130a298186381244ae4112da618b217866243fabfc312a',
    'AN202609291830000678': 'c99e1a25619b341823546b0836f7adb89c06e38980517d629229887113a2afcc',
}


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def notice_day(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.match(r'^\s*(\d{4}-\d{2}-\d{2})', value)
    return match.group(1) if match else None


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    tmp.replace(path)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding='utf-8'))


def imports():
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    from v4.manager_research.announcement_source import (
        CaptureBudget, EASTMONEY_CONTENT_URL, EASTMONEY_REQUEST_PREFIX,
        EASTMONEY_SOURCE, MAX_BYTES, MAX_EASTMONEY_BODY_CHARACTERS,
        MAX_EASTMONEY_CONTENT_PAGES, MAX_EASTMONEY_RESPONSE_BYTES,
        MAX_EASTMONEY_TOTAL_RESPONSE_BYTES, _safe_eastmoney_url,
        capture_eastmoney, eastmoney_content_url, extract_pdf_pages,
        read_eastmoney_response, safe_reason,
    )
    from v4.manager_research.hkex_provider import HkexOfficialProvider
    from v4.manager_research.materials import MaterialStore
    from v4.manager_research.workspace_projection import digest
    return locals()


def make_provider(api):
    store = api['MaterialStore'](STORE_ROOT)
    provider = api['HkexOfficialProvider'](timeout=20.0, material_store=store)
    return store, provider


def load_material_url_index(store) -> dict[str, dict]:
    """Read the existing index filenames, retaining only exact Eastmoney refs."""
    result: dict[str, dict] = {}
    for path in (store.root / 'index').glob('*.json'):
        try:
            entry = json.loads(path.read_bytes())
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        url = entry.get('url') if isinstance(entry, dict) else None
        if not isinstance(url, str):
            continue
        parts = urlsplit(url)
        if ((parts.hostname == 'np-cnotice-stock.eastmoney.com' and parts.path == '/api/content/ann')
                or (parts.hostname == 'pdf.dfcfw.com' and re.fullmatch(r'/pdf/H2_AN[A-Z0-9]{8,32}_1\.pdf', parts.path))):
            result[url] = entry
    return result


def existing_response(api, store, provider, url: str, known_urls: set[str] | None = None):
    """Return a verified cache ref/body only if its index already exists."""
    if known_urls is not None and url not in known_urls:
        return None
    req = {'source': api['EASTMONEY_SOURCE'], 'method': 'GET', 'url': url}
    key = api['EASTMONEY_REQUEST_PREFIX'] + api['digest'](req)
    if not store.stat_source(key):
        return None
    ref = api['capture_eastmoney'](provider, url, force=False)
    if ref.get('from_cache') is not True:
        raise RuntimeError('EXISTING_MATERIAL_REF_NOT_CACHE_REUSED')
    raw = api['read_eastmoney_response'](store, ref)
    return ref, raw


def parse_content(raw: bytes) -> dict:
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('CONTENT_JSON_INVALID') from exc
    if not isinstance(payload, Mapping) or payload.get('success') != 1 or not isinstance(payload.get('data'), Mapping):
        raise ValueError('CONTENT_RESPONSE_NOT_SUCCESSFUL')
    detail = dict(payload['data'])
    if type(detail.get('page_size')) is not int or detail['page_size'] < 1:
        raise ValueError('CONTENT_PAGE_TOTAL_INVALID')
    return detail


def source_page_receipt(page_index: int) -> dict:
    return load_json(DATE_DIR / 'page_receipts' / f'page_{page_index:03}.json')


def load_source_inputs() -> tuple[list[dict], dict, dict]:
    view = load_json(DATE_DIR / 'manager_consumer_view.json')
    manifest = load_json(DATE_DIR / 'manifest.json')
    rows = view.get('rows')
    if not isinstance(rows, list):
        raise ValueError('DATE_CATALOG_MANAGER_ROWS_MISSING')
    receipts = {}
    for row in rows:
        idx = row.get('page_index')
        if isinstance(idx, int) and idx not in receipts:
            receipts[idx] = source_page_receipt(idx)
    return rows, view, dict(manifest=manifest, page_receipts=receipts)


def article_hk_stocks(row: Mapping[str, Any]) -> list[str]:
    codes = row.get('raw_row', {}).get('codes', [])
    return sorted({str(c.get('stock_code')) for c in codes if isinstance(c, Mapping)
                   and str(c.get('market_code')) == '116' and c.get('ann_type') == 'H'
                   and re.fullmatch(r'\d{5}', str(c.get('stock_code', '')))})


def observed_content_for_row(api, store, provider, row: Mapping[str, Any], known_urls: set[str]) -> dict:
    art = str(row.get('art_code', ''))
    entries: list[tuple[int, str, dict]] = []
    for url in known_urls:
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.netloc != 'np-cnotice-stock.eastmoney.com' or parts.path != '/api/content/ann':
            continue
        query = parse_qs(parts.query)
        if (query.get('art_code') or [''])[0] != art:
            continue
        try:
            page_index = int((query.get('page_index') or ['1'])[0])
        except ValueError:
            continue
        entries.append((page_index, url, {}))
    entries.sort(key=lambda item: item[0])
    pages: list[dict] = []
    detail0: dict | None = None
    expected_total: int | None = None
    total_chars = 0
    issues: list[str] = []
    for page_index, url, _ in entries:
        try:
            result = existing_response(api, store, provider, url, known_urls)
            if result is None:
                continue
            ref, raw = result
            if ref.get('http_status') != 200:
                issues.append(f'PAGE_{page_index}_HTTP_{ref.get("http_status")}')
                pages.append({'page_index': page_index, 'source_ref': ref, 'raw_body_sha256': ref.get('body_sha256'), 'error': 'HTTP_NOT_200'})
                continue
            detail = parse_content(raw)
            text = detail.get('notice_content')
            if not isinstance(text, str) or not text.strip():
                issues.append(f'PAGE_{page_index}_TEXT_MISSING')
            page_total = detail['page_size']
            if expected_total is None:
                expected_total = page_total
                detail0 = detail
            elif page_total != expected_total:
                issues.append(f'PAGE_{page_index}_TOTAL_DRIFT')
            if detail.get('art_code') != art:
                issues.append(f'PAGE_{page_index}_ART_CODE_MISMATCH')
            stocks = article_hk_stocks(row)
            sec = detail.get('security')
            securities = [str(s.get('stock', '')).zfill(5) for s in sec if isinstance(s, Mapping)
                          and str(s.get('market_uni', '')) == '116'] if isinstance(sec, list) else []
            if not set(stocks).intersection(securities):
                issues.append(f'PAGE_{page_index}_SECURITY_MISMATCH')
            if isinstance(text, str):
                total_chars += len(text)
            pages.append({'page_index': page_index, 'source_ref': ref,
                'raw_body_sha256': ref.get('body_sha256'), 'blob_sha256': ref.get('blob_sha256'),
                'retrieved_at': ref.get('retrieved_at'), 'text': text if isinstance(text, str) else None,
                'text_sha256': sha256_bytes(text.encode('utf-8')) if isinstance(text, str) else None,
                'page_total': page_total, 'notice_date': detail.get('notice_date'),
                'notice_title': detail.get('notice_title'), 'security_116_codes': sorted(set(securities)),
                'attach_url_web': detail.get('attach_url_web')})
        except Exception as exc:
            issues.append(f'PAGE_{page_index}_{api["safe_reason"](exc,"EXISTING_CONTENT_READ_FAILED")}')
            pages.append({'page_index': page_index, 'error': api['safe_reason'](exc, 'EXISTING_CONTENT_READ_FAILED')})
    total = expected_total
    present = sorted(p.get('page_index') for p in pages if isinstance(p.get('page_index'), int) and p.get('text'))
    if 1 not in present:
        status = 'MISSING_PAGE1'
    elif total is not None and total > api['MAX_EASTMONEY_CONTENT_PAGES']:
        status = 'OVER_CONTENT_PAGE_LIMIT'
    elif total_chars > api['MAX_EASTMONEY_BODY_CHARACTERS']:
        status = 'OVER_CONTENT_TEXT_LIMIT'
    elif total is not None and present == list(range(1, total + 1)) and not issues:
        status = 'COMPLETE_CONTENT_API_BODY'
    else:
        status = 'CONTENT_PAGES_INCOMPLETE_OR_INVALID'
    body_text = '\n\n'.join(str(p['text']) for p in pages if isinstance(p.get('text'), str))
    return {'body_status': status, 'content_page_count': total,
        'present_page_indexes': present, 'pages': pages, 'body_text_characters': total_chars,
        'body_text': body_text if status == 'COMPLETE_CONTENT_API_BODY' else None,
        'body_text_sha256': sha256_bytes(body_text.encode('utf-8')) if status == 'COMPLETE_CONTENT_API_BODY' else None,
        'attachment_url': (detail0 or {}).get('attach_url_web'), 'content_notice_date': (detail0 or {}).get('notice_date'),
        'content_display_time': (detail0 or {}).get('eitime'), 'issues': sorted(set(issues))}


def pdf_inventory(api, store, provider, article: Mapping[str, Any], known_urls: set[str], candidate_url: str | None) -> dict:
    art = str(article.get('art_code', ''))
    pdf_urls = [url for url in known_urls if (urlsplit(url).hostname == 'pdf.dfcfw.com'
                 and urlsplit(url).path == f'/pdf/H2_{art}_1.pdf')]
    if candidate_url and candidate_url in known_urls:
        pdf_urls = [candidate_url]
    if not pdf_urls:
        return {'pdf_status': 'PDF_REF_MISSING', 'pdf_ref': None, 'pdf_bytes': None, 'pdf_sha256': None}
    url = sorted(pdf_urls)[0]
    try:
        result = existing_response(api, store, provider, url, known_urls)
        if result is None:
            return {'pdf_status': 'PDF_REF_MISSING', 'pdf_ref': None, 'pdf_bytes': None, 'pdf_sha256': None}
        ref, raw = result
        valid = ref.get('http_status') == 200 and raw.startswith(b'%PDF')
        return {'pdf_status': 'VALID_PDF_BYTES' if valid else 'INVALID_PDF_BYTES',
            'pdf_ref': ref, 'pdf_bytes': len(raw), 'pdf_sha256': sha256_bytes(raw),
            'content_type': store.stat_source(ref['source_key']).get('content_type'),
            'pdf_header_hex': raw[:8].hex()}
    except Exception as exc:
        return {'pdf_status': api['safe_reason'](exc, 'PDF_READBACK_FAILED'), 'pdf_ref': None,
            'pdf_bytes': None, 'pdf_sha256': None}


def build_body_corpus() -> dict:
    api = imports()
    store, provider = make_provider(api)
    rows, view, source_inputs = load_source_inputs()
    index = load_material_url_index(store)
    known_urls = set(index)
    page_receipts = source_inputs['page_receipts']
    result_rows: list[dict] = []
    for row in rows:
        source_row = dict(row)
        art = str(row.get('art_code', ''))
        body = observed_content_for_row(api, store, provider, row, known_urls)
        pdf = pdf_inventory(api, store, provider, row, known_urls, body.get('attachment_url'))
        page_rcpt = page_receipts.get(row.get('page_index'), {})
        listing = dict(page_index=row.get('page_index'), request_url=row.get('request_url'),
            notice_date=row.get('notice_date'), display_time=row.get('display_time'),
            retrieved_at=row.get('retrieved_at'), raw_body_sha256=row.get('raw_body_sha256'),
            blob_sha256=row.get('blob_sha256'), source_ref=page_rcpt.get('source_ref'))
        result_rows.append({'art_code': art, 'title': row.get('title'),
            'matched_master_codes': row.get('matched_master_codes', []),
            'hk_source_stock_codes_116': article_hk_stocks(row), 'listing_evidence': listing,
            **body, **pdf})
    body_counts = Counter(r['body_status'] for r in result_rows)
    pdf_counts = Counter(r['pdf_status'] for r in result_rows)
    manifest = source_inputs['manifest']
    status = 'PASS_INVENTORY_READBACK' if (
        len(result_rows) == int(manifest.get('manager_consumer_row_count', -1)) == 234
        and body_counts.get('COMPLETE_CONTENT_API_BODY') == 167
        and body_counts.get('OVER_CONTENT_PAGE_LIMIT') == 23
        and body_counts.get('MISSING_PAGE1') == 44
        and pdf_counts.get('VALID_PDF_BYTES') == 164
    ) else 'PARTIAL_INVENTORY_COUNTS_DIFFER'
    return {'schema': 'v4.manager_research.eastmoney_hk_body_corpus.v1',
        'status': status, 'target_notice_date': '2026-09-29', 'source_scope': 'EASTMONEY_HK_DATE_CATALOG',
        'source_listing_status': manifest.get('status'), 'source_listing_manifest_sha256': sha256_bytes((DATE_DIR / 'manifest.json').read_bytes()),
        'manager_view_sha256': sha256_bytes((DATE_DIR / 'manager_consumer_view.json').read_bytes()),
        'material_store_root': str(STORE_ROOT), 'material_store_refs_verified_via': 'capture_eastmoney(force=false)+read_eastmoney_response',
        'body_limit_pages': api['MAX_EASTMONEY_CONTENT_PAGES'], 'body_limit_characters': api['MAX_EASTMONEY_BODY_CHARACTERS'],
        'single_response_byte_limit': api['MAX_EASTMONEY_RESPONSE_BYTES'],
        'total_response_byte_limit': api['MAX_EASTMONEY_TOTAL_RESPONSE_BYTES'],
        'article_count': len(result_rows), 'body_status_counts': dict(body_counts), 'pdf_status_counts': dict(pdf_counts),
        'interpretation': '这是从同一MaterialStore与日期清单导出的可追溯研究语料视图；不是新权威源、不是PIT重建，也不证明首次披露时间。',
        'retrieved_at_range': _retrieval_range(result_rows), 'rows': result_rows}


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


def write_inventory_outputs(corpus: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    atomic_json(OUT / 'body_corpus_20260929.json', corpus)
    fields = ['art_code', 'title', 'body_status', 'content_page_count', 'present_page_indexes',
        'body_text_characters', 'body_text_sha256', 'pdf_status', 'pdf_bytes', 'pdf_sha256',
        'listing_page_index', 'listing_retrieved_at', 'listing_raw_body_sha256']
    with (OUT / 'body_corpus_20260929.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in corpus['rows']:
            listing = row.get('listing_evidence', {})
            writer.writerow({'art_code': row.get('art_code'), 'title': row.get('title'),
                'body_status': row.get('body_status'), 'content_page_count': row.get('content_page_count'),
                'present_page_indexes': ','.join(map(str, row.get('present_page_indexes', []))),
                'body_text_characters': row.get('body_text_characters'), 'body_text_sha256': row.get('body_text_sha256'),
                'pdf_status': row.get('pdf_status'), 'pdf_bytes': row.get('pdf_bytes'), 'pdf_sha256': row.get('pdf_sha256'),
                'listing_page_index': listing.get('page_index'), 'listing_retrieved_at': listing.get('retrieved_at'),
                'listing_raw_body_sha256': listing.get('raw_body_sha256')})


def interpretation_definitions() -> dict[str, dict]:
    return {
        'AN202609291829998939': {
            'category': '常规披露（所涉证券类别需拆分）', 'impact_state': 'NO_AUTOMATIC_POSITIVE',
            'hk_issuer': {'code': 'HK.02333', 'name': '长城汽车'},
            'security_class_distinction': '清单发行人为H股长城汽车；附件事实涉及A股601633，不能标注为H股回购。',
            'facts': [
                {'statement': 'PDF第1页记载9月28日注销217,932股、价格人民币12.51元；另注销48,111股、价格人民币11.94元。', 'pdf_pages': [1]},
                {'statement': 'PDF第2页记载9月29日结余6,259,427,749股。', 'pdf_pages': [2]},
            ],
            'unknowns': ['HKEX首次披露时间与原始PIT可用时间：CANNOT_CONFIRM', '相对既有公告的增量：CANNOT_CONFIRM'],
        },
        'AN202609291829996809': {
            'category': '混合（经营下滑、销售与债务信息）', 'impact_state': 'MIXED_OPERATING_AND_BALANCE_SHEET_DISCLOSURE',
            'hk_issuer': {'code': 'HK.00119', 'name': '保利置业集团'},
            'security_class_distinction': '香港上市发行人HK.00119。',
            'facts': [
                {'statement': '2026年上半年收入人民币15.089bn，同比下降18.2%；归母净亏损人民币740.303m；毛利人民币906.538m。', 'pdf_pages': [5, 16]},
                {'statement': '合约销售人民币23.207bn。', 'pdf_pages': [5, 7]},
                {'statement': '借贷人民币67.81545bn。', 'pdf_pages': [13]},
                {'statement': '现金人民币27.833315bn。', 'pdf_pages': [18, 23]},
                {'statement': '经营活动现金净流出人民币417.464m。', 'pdf_pages': [22]},
                {'statement': '没有宣派中期股息。', 'pdf_pages': [32, 44]},
            ],
            'api_segment_count': 12, 'pdf_physical_page_count': 48,
            'unknowns': ['HKEX首次披露时间与原始PIT可用时间：CANNOT_CONFIRM', '相对既有公告的增量：CANNOT_CONFIRM'],
        },
        'AN202609291829976776': {
            'category': '风险（有条件的新股配售与稀释）', 'impact_state': 'CONDITIONAL_DILUTION_NOT_COMPLETED',
            'hk_issuer': {'code': 'HK.02635', 'name': '诺比侃'},
            'security_class_distinction': '配售对象为新H股。',
            'facts': [
                {'statement': '拟配售16,488,500股新H股，每股港币8.19元；相对港币9.48元参考价折让13.61%；扩大后股本占比4.17%。', 'pdf_pages': [1, 3]},
                {'statement': '总额港币135.04m、净额港币131.47m；募集资金用途分为40%/20%/20%/20%。', 'pdf_pages': [3, 7]},
                {'statement': 'PDF第4页列示条件尚未成就，期限为10月16日16:00或书面延长；本材料不能记作已完成配售。', 'pdf_pages': [4]},
            ],
            'unknowns': ['条件最终是否成就及实际完成时间：CANNOT_CONFIRM', 'HKEX首次披露时间与原始PIT可用时间：CANNOT_CONFIRM', '相对既有公告的增量：CANNOT_CONFIRM'],
        },
        'AN202609291830002096': {
            'category': '风险（新增担保敞口）', 'impact_state': 'GUARANTEE_EXPOSURE_INCREASE',
            'hk_issuer': {'code': 'HK.06806', 'name': '申万宏源'},
            'security_class_distinction': '香港清单发行人为HK.06806；所附A股发行人公告编号A000166，所涉证券为A股文件。',
            'facts': [
                {'statement': 'PDF第2页披露新增担保额度人民币6亿元；此前额度人民币2.55亿元。', 'pdf_pages': [2]},
                {'statement': 'PDF第3页披露新增人民币1亿元后累计人民币3.55亿元。', 'pdf_pages': [3]},
                {'statement': 'PDF第5页披露集团担保余额由人民币56.81亿元升至57.81亿元，占净资产5.18%。', 'pdf_pages': [5]},
            ],
            'unknowns': ['HKEX首次披露时间与原始PIT可用时间：CANNOT_CONFIRM', '相对既有公告的增量：CANNOT_CONFIRM'],
        },
        'AN202609291829976846': {
            'category': '风险与不确定（重大交易预案）', 'impact_state': 'PROPOSED_TRANSACTION_APPROVALS_PENDING',
            'hk_issuer': {'code': 'HK.02238', 'name': '广汽集团'},
            'security_class_distinction': 'HK清单对应HK.02238；附件提及A股601238。附件称A股9月29日复牌；H股状态CANNOT_CONFIRM。',
            'facts': [
                {'statement': 'PDF第2页披露拟收购一汽丰田50%股权，并向不超过35名对象募集配套资金。', 'pdf_pages': [2]},
                {'statement': 'PDF第2至3页注明审计、评估未完成，交易尚待审批；属于预案，不代表交易完成。', 'pdf_pages': [2, 3]},
                {'statement': 'PDF第1页为香港封面；所涉A股601238于9月29日复牌。', 'pdf_pages': [1, 2]},
            ],
            'unknowns': ['H股复牌/停牌状态：CANNOT_CONFIRM', '交易审批和完成状态：CANNOT_CONFIRM', 'HKEX首次披露时间与原始PIT可用时间：CANNOT_CONFIRM', '相对既有公告的增量：CANNOT_CONFIRM'],
        },
        'AN202609291830000678': {
            'category': '混合（增资登记进展；新颖性未知）', 'impact_state': 'REGISTRATION_COMPLETION_REPORTED_INCREMENTALITY_UNKNOWN',
            'hk_issuer': {'code': 'HK.02691', 'name': '南华期货股份'},
            'security_class_distinction': 'PDF第1页香港封面日期为9月29日；附件为A股603093公告，落款9月30日，两个日期对应不同层级。',
            'facts': [
                {'statement': 'PDF第2至3页记载向全资子公司增资人民币1.5亿元，注册资本由人民币6亿元增至7.5亿元，持股100%，并称已完成工商变更登记。', 'pdf_pages': [2, 3]},
                {'statement': '该文引用9月23日旧公告；此次材料没有完成与旧公告的逐项增量比较。', 'pdf_pages': [2, 3]},
            ],
            'unknowns': ['相对9月23日公告的增量：CANNOT_CONFIRM', 'HKEX首次披露时间与原始PIT可用时间：CANNOT_CONFIRM'],
        },
    }


def build_interpretations(corpus: dict) -> dict:
    by_code = {row['art_code']: row for row in corpus['rows']}
    definitions = interpretation_definitions()
    docs = []
    for art in SIX_CODES:
        source = by_code.get(art)
        fact_def = definitions[art]
        if not source:
            docs.append({'art_code': art, 'status': 'SOURCE_ROW_MISSING', 'claims': []})
            continue
        listing = source['listing_evidence']
        body_refs = [p['source_ref'] for p in source.get('pages', []) if p.get('source_ref')]
        pdf_ref = source.get('pdf_ref')
        actual_pdf_sha = source.get('pdf_sha256')
        expected_pdf_sha = EXPECTED_PDF_SHA256[art]
        pdf_match = actual_pdf_sha == expected_pdf_sha
        status = 'PASS_SOURCE_BINDINGS' if (
            source.get('body_status') == 'COMPLETE_CONTENT_API_BODY'
            and source.get('pdf_status') == 'VALID_PDF_BYTES'
            and pdf_match and bool(listing.get('source_ref'))
        ) else 'CANNOT_CONFIRM_SOURCE_BINDING'
        docs.append({
            'art_code': art, 'status': status, 'listing': {
                'notice_date': listing.get('notice_date'), 'display_time': listing.get('display_time'),
                'captured_at': listing.get('retrieved_at'), 'page_index': listing.get('page_index'),
                'source_ref': listing.get('source_ref')},
            'hk_issuer': fact_def['hk_issuer'], 'title': source.get('title'),
            'category': fact_def['category'], 'impact_state': fact_def['impact_state'],
            'security_class_distinction': fact_def['security_class_distinction'],
            'body_evidence': {'status': source.get('body_status'), 'api_segment_count': source.get('content_page_count'),
                'api_pages': [{'page_index': p.get('page_index'), 'sha256': p.get('raw_body_sha256'),
                    'blob_sha256': p.get('blob_sha256'), 'retrieved_at': p.get('retrieved_at'),
                    'source_ref': p.get('source_ref')} for p in source.get('pages', [])]},
            'pdf_evidence': {'status': source.get('pdf_status'), 'sha256': actual_pdf_sha,
                'expected_independent_review_sha256': expected_pdf_sha, 'sha256_match': pdf_match,
                'bytes': source.get('pdf_bytes'), 'source_ref': pdf_ref,
                'physical_page_count': fact_def.get('pdf_physical_page_count', 'CANNOT_CONFIRM')},
            'facts': fact_def['facts'], 'unknowns': fact_def['unknowns'],
            'first_hkex_publication_time': 'CANNOT_CONFIRM',
            'original_pit_available_at': 'CANNOT_CONFIRM',
            'incremental_novelty_vs_prior_disclosure': 'CANNOT_CONFIRM',
            'all_content_and_pdf_retrieved_after_target_date': True,
        })
    return {'schema': 'v4.manager_research.eastmoney_hk_six_interpretations.v1',
        'status': 'PASS_SOURCE_BINDINGS' if all(d.get('status') == 'PASS_SOURCE_BINDINGS' for d in docs) else 'PARTIAL_SOURCE_BINDINGS',
        'target_notice_date': '2026-09-29', 'interpretation_method': '独立审阅者逐篇核对所附原始PDF；这里只落盘其事实、原文物理页引用及未知项，不调用外部LLM。',
        'corpus_sha256': sha256_bytes((OUT / 'body_corpus_20260929.json').read_bytes()),
        'documents': docs}


def write_interpretation_outputs(value: dict) -> None:
    atomic_json(OUT / 'six_interpretations_20260929.json', value)
    lines = [
        '# 2026-09-29 六篇公告原文核对', '',
        '六篇清单日期均为Eastmoney的 `notice_date=2026-09-29`；正文与PDF材料在10月4日至10月5日补取/复核。清单日期不等于HKEX首次披露时间，也不等于原始PIT可用时间。',
        '每条事实以附录物理PDF页码为引，API正文分段与PDF物理页分别记录；未完成状态、证券类别和相对旧公告增量按原文保留。', '',
    ]
    for doc in value['documents']:
        lines.extend([f"## {doc['art_code']} · {doc.get('hk_issuer',{}).get('code','')} {doc.get('hk_issuer',{}).get('name','')}",
            f"- 分类：{doc.get('category')}；状态：`{doc.get('status')}`；影响：{doc.get('impact_state')}",
            f"- 证券区分：{doc.get('security_class_distinction')}"])
        pdf = doc.get('pdf_evidence', {})
        lines.append(f"- 原PDF SHA-256：`{pdf.get('sha256')}`；独立审阅核验：`{pdf.get('sha256_match')}`；API分段：{doc.get('body_evidence',{}).get('api_segment_count')}；PDF物理页：{pdf.get('physical_page_count')}")
        for fact in doc.get('facts', []):
            lines.append(f"- 事实（PDF p{','.join(map(str, fact.get('pdf_pages', [])))}）：{fact.get('statement')}")
        for unknown in doc.get('unknowns', []):
            lines.append(f"- 未知：{unknown}")
        lines.append('- 首次披露、原始PIT及旧公告增量不得由这次事后抓取补推。')
        lines.append('')
    (OUT / 'six_interpretations_20260929.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def cached_existing_or_capture(api, store, provider, url: str, budget, *, force: bool = False):
    """The only network writer: one durable attempt followed by one terminal receipt."""
    kind = 'pdf' if urlsplit(url).hostname == 'pdf.dfcfw.com' else 'content'
    q = parse_qs(urlsplit(url).query)
    art = (q.get('art_code') or [re.search(r'H2_(AN[A-Z0-9]+)_1\.pdf', urlsplit(url).path).group(1) if kind == 'pdf' else 'unknown'])[0]
    page = int((q.get('page_index') or ['1'])[0]) if kind == 'content' else 'pdf'
    stem = f'{art}.{kind}.p{page}'
    marker = OUT / 'canary_receipts' / 'attempts' / f'{stem}.attempt.json'
    receipt_path = OUT / 'canary_receipts' / 'receipts' / f'{stem}.json'
    if receipt_path.exists():
        return load_json(receipt_path)
    if marker.exists():
        receipt = {'schema': 'eastmoney_body_canary_receipt.v1', 'art_code': art,
            'kind': kind, 'page_index': page, 'request_url': url, 'status': 'ATTEMPT_INDETERMINATE_NO_RETRY',
            'error': 'PRIOR_ATTEMPT_MARKER_WITHOUT_TERMINAL_RECEIPT', 'retrieved_at': None}
        atomic_json(receipt_path, receipt)
        return receipt
    marker_data = {'schema': 'eastmoney_body_canary_attempt.v1', 'art_code': art, 'kind': kind,
        'page_index': page, 'request_url': url, 'started_at': now_utc(), 'force': bool(force),
        'provider_timeout_seconds': 20, 'one_attempt_only': True}
    atomic_json(marker, marker_data)
    receipt: dict[str, Any] = {'schema': 'eastmoney_body_canary_receipt.v1', 'art_code': art,
        'kind': kind, 'page_index': page, 'request_url': url, 'attempt_path': str(marker),
        'started_at': marker_data['started_at']}
    try:
        ref = api['capture_eastmoney'](provider, url, budget=budget, force=force)
        raw = api['read_eastmoney_response'](store, ref)
        if budget is not None:
            budget.record_response_bytes(len(raw))
        item = {'source_ref': ref, 'raw_body_sha256': sha256_bytes(raw), 'response_bytes': len(raw),
            'status': 'CAPTURED' if ref.get('http_status') == 200 else 'HTTP_FAILED',
            'retrieved_at': ref.get('retrieved_at'), 'from_cache': ref.get('from_cache')}
        if kind == 'content' and ref.get('http_status') == 200:
            try:
                detail = parse_content(raw)
                text = detail.get('notice_content')
                item['content_metadata'] = {'art_code': detail.get('art_code'), 'notice_title': detail.get('notice_title'),
                    'notice_date': detail.get('notice_date'), 'display_time': detail.get('eitime'),
                    'page_total': detail.get('page_size'), 'attachment_url': detail.get('attach_url_web'),
                    'text_characters': len(text) if isinstance(text, str) else None,
                    'text_sha256': sha256_bytes(text.encode('utf-8')) if isinstance(text, str) else None,
                    'notice_content': text if isinstance(text, str) else None}
            except Exception as exc:
                item['status'] = 'CONTENT_PARSE_FAILED'
                item['error'] = api['safe_reason'](exc, 'CONTENT_PARSE_FAILED')
        if kind == 'pdf' and ref.get('http_status') == 200:
            item['pdf_header_hex'] = raw[:8].hex()
            item['pdf_signature_valid'] = raw.startswith(b'%PDF')
            item['pdf_sha256'] = sha256_bytes(raw)
            item['pdf_bytes'] = len(raw)
        receipt.update(item)
    except Exception as exc:
        receipt.update(status='CAPTURE_FAILED', error=api['safe_reason'](exc, 'BODY_CAPTURE_FAILED'),
            failed_at=now_utc())
    atomic_json(receipt_path, receipt)
    return receipt


def run_canaries() -> dict:
    api = imports()
    store, provider = make_provider(api)
    rows, _view, _source = load_source_inputs()
    rows_by = {str(r['art_code']): r for r in rows}
    budget = api['CaptureBudget'](seconds=45, max_requests=57, interval=0.5,
        max_response_bytes=api['MAX_EASTMONEY_TOTAL_RESPONSE_BYTES'])
    results = []
    for art in CANARY_CODES:
        row = rows_by.get(art)
        if not row:
            results.append({'art_code': art, 'status': 'SOURCE_ROW_MISSING'})
            continue
        url1 = api['eastmoney_content_url'](art, page_index=1)
        first = cached_existing_or_capture(api, store, provider, url1, budget, force=False)
        item: dict[str, Any] = {'art_code': art, 'title': row.get('title'), 'category': row.get('raw_row', {}).get('columns'),
            'listing_evidence': {'notice_date': row.get('notice_date'), 'page_index': row.get('page_index'),
                'listing_raw_body_sha256': row.get('raw_body_sha256')}, 'content_receipts': [first]}
        content_pages = []
        metadata = first.get('content_metadata')
        if first.get('status') == 'CAPTURED' and first.get('source_ref', {}).get('http_status') == 200 and metadata:
            content_pages.append(metadata)
            total = metadata.get('page_total')
            item['content_page_total'] = total
            if type(total) is int and total > api['MAX_EASTMONEY_CONTENT_PAGES']:
                item['content_boundary'] = 'OVER_CONTENT_PAGE_LIMIT'
            elif type(total) is int and total > 1:
                for page in range(2, total + 1):
                    if budget.elapsed_seconds >= budget.seconds:
                        item['content_boundary'] = 'TIME_BUDGET_EXHAUSTED'
                        break
                    receipt = cached_existing_or_capture(api, store, provider,
                        api['eastmoney_content_url'](art, page_index=page), budget, force=False)
                    item['content_receipts'].append(receipt)
                    m = receipt.get('content_metadata')
                    if receipt.get('status') != 'CAPTURED' or not m:
                        item['content_boundary'] = receipt.get('error') or receipt.get('status')
                        break
                    content_pages.append(m)
                    chars = sum(len(p.get('notice_content') or '') for p in content_pages)
                    if chars > api['MAX_EASTMONEY_BODY_CHARACTERS']:
                        item['content_boundary'] = 'OVER_CONTENT_TEXT_LIMIT'
                        break
            text_chars = sum(len(p.get('notice_content') or '') for p in content_pages)
            item['body_text_characters_observed'] = text_chars
            item['content_page_indexes_captured'] = [r.get('page_index') for r in item['content_receipts']]
            item['body_text_observed'] = '\n\n'.join(p.get('notice_content') or '' for p in content_pages)
            item['body_text_sha256_observed'] = sha256_bytes(item['body_text_observed'].encode('utf-8'))
            item['content_api_segment_set_complete'] = (type(total) is int and total <= api['MAX_EASTMONEY_CONTENT_PAGES'
                ] and len(content_pages) == total and item['content_page_indexes_captured'] == list(range(1, total + 1)))
            if not item.get('content_boundary'):
                item['content_boundary'] = 'WITHIN_CONTENT_PAGE_AND_TEXT_LIMITS'
            if all(p.get('art_code') == art and notice_day(p.get('notice_date')) == notice_day(row.get('notice_date')) for p in content_pages):
                item['content_identity_status'] = 'MATCH'
            else:
                item['content_identity_status'] = 'MISMATCH_OR_INCOMPLETE'
            attachment_url = metadata.get('attachment_url')
            if isinstance(attachment_url, str) and api['_safe_eastmoney_url'](attachment_url):
                pdf_receipt = cached_existing_or_capture(api, store, provider, attachment_url, budget, force=False)
                item['pdf_receipt'] = pdf_receipt
                item['pdf_capture_status'] = pdf_receipt.get('status')
                if pdf_receipt.get('status') == 'CAPTURED' and pdf_receipt.get('pdf_signature_valid'):
                    raw = api['read_eastmoney_response'](store, pdf_receipt['source_ref'])
                    try:
                        pages = api['extract_pdf_pages'](raw, max_bytes=api['MAX_BYTES'], max_pages=40,
                            max_text_characters=240000, timeout_seconds=10)
                        item['pdf_physical_pages'] = [{'page': p.get('page'), 'text_sha256': sha256_bytes(str(p.get('text','')).encode('utf-8')),
                            'text': p.get('text')} for p in pages]
                        item['pdf_extraction_status'] = 'PARSED'
                    except Exception as exc:
                        item['pdf_extraction_status'] = api['safe_reason'](exc, 'PDF_PARSE_FAILED')
            else:
                item['pdf_capture_status'] = 'ATTACHMENT_URL_MISSING_OR_UNSAFE'
        else:
            item['content_boundary'] = first.get('error') or first.get('status') or 'CONTENT_PAGE1_MISSING'
        item['raw_source_capture_status'] = ('PASS' if item.get('content_identity_status') == 'MATCH'
            and item.get('pdf_capture_status') == 'CAPTURED' and item.get('pdf_receipt', {}).get('pdf_signature_valid')
            else 'PARTIAL')
        item['original_text_consistency_evidence'] = ('COMPLETE_FOR_REVIEW' if
            item.get('content_api_segment_set_complete') is True and item.get('pdf_extraction_status') == 'PARSED'
            else 'CANNOT_CONFIRM')
        item['status'] = ('PASS_CANARY_RAW_SOURCE_CAPTURE' if item['raw_source_capture_status'] == 'PASS'
            else 'PARTIAL_CANARY')
        results.append(item)
    summary = {'schema': 'v4.manager_research.eastmoney_hk_missing_page1_canary.v1',
        'status': 'PASS_THREE_SAMPLE_RAW_CAPTURE' if len(results) == 3 and all(r.get('status') == 'PASS_CANARY_RAW_SOURCE_CAPTURE' for r in results) else 'PARTIAL_CANARY_RAW_CAPTURE',
        'target_notice_date': '2026-09-29', 'canary_codes': list(CANARY_CODES),
        'sample_count': len(results),
        'text_consistency_evidence_status': ('REVIEWABLE_FOR_ALL_THREE' if len(results) == 3 and all(
            r.get('original_text_consistency_evidence') == 'COMPLETE_FOR_REVIEW' for r in results) else 'PARTIAL_CANNOT_CONFIRM'),
        'text_consistency_reviewable_count': sum(r.get('original_text_consistency_evidence') == 'COMPLETE_FOR_REVIEW' for r in results),
        'budget': {'seconds': budget.seconds, 'max_requests': budget.max_requests,
            'max_response_bytes': budget.max_response_bytes, 'requests_used': budget.requests,
            'response_bytes_used': budget.response_bytes, 'elapsed_seconds': round(budget.elapsed_seconds, 3)},
        'limits': {'content_pages': api['MAX_EASTMONEY_CONTENT_PAGES'], 'body_text_characters': api['MAX_EASTMONEY_BODY_CHARACTERS'],
            'per_response_bytes': api['MAX_EASTMONEY_RESPONSE_BYTES'], 'total_response_bytes': api['MAX_EASTMONEY_TOTAL_RESPONSE_BYTES'],
            'provider_timeout_seconds': provider._timeout},
        'attempt_policy': '每个URL只尝试一次；先写attempt marker，失败落终态receipt，不盲重试、不提升全局上限。',
        'results': results}
    atomic_json(OUT / 'missing_page1_canary_20260929_v2.json', summary)
    return summary


def generate_readme(corpus: dict, interpretations: dict, canaries: dict | None = None) -> None:
    rows = corpus.get('rows', [])
    counts = corpus.get('body_status_counts', {})
    pdf_counts = corpus.get('pdf_status_counts', {})
    lines = [
        '# 2026-09-29 香港公告正文语料与六篇事实核对', '',
        '此目录仅存储从既有Eastmoney日期清单和原MaterialStore导出的研究派生材料。每篇的原始正文/PDF通过原始URL、source key、blob SHA、响应SHA及原retrieved_at回指共享MaterialStore；这里的文本投影不是新的权威源。', '',
        f"- 日期目录：`{corpus.get('source_listing_status')}`；manager view：{corpus.get('article_count')}篇。",
        f"- v1基线正文状态：完整 {counts.get('COMPLETE_CONTENT_API_BODY',0)}；API分页超过现有20页上限 {counts.get('OVER_CONTENT_PAGE_LIMIT',0)}；缺首页 {counts.get('MISSING_PAGE1',0)}；其他/异常 {sum(v for k,v in counts.items() if k not in {'COMPLETE_CONTENT_API_BODY','OVER_CONTENT_PAGE_LIMIT','MISSING_PAGE1'})}。",
        f"- v1基线PDF字节验证：有效 {pdf_counts.get('VALID_PDF_BYTES',0)}；未取到或无有效引用 {sum(v for k,v in pdf_counts.items() if k != 'VALID_PDF_BYTES')}。",
        f"- 输入日期目录manifest SHA-256：`{corpus.get('source_listing_manifest_sha256')}`。正文读取时间范围：{corpus.get('retrieved_at_range')}。", '',
        '正文状态没有把上限截断误写为完整：超过20页、120,000字符、8 MiB单响应、64 MiB累计响应及45秒采集时间均保留具体边界；本脚本不提高全局限制。缺页表示MaterialStore当时无该页引用，不推断源端没有正文。', '',
        '六篇解读引用物理PDF页码，并单独记录API分段数。分类保留“常规披露 / 实质事项 / 风险 / 混合 / 不确定”；只报告源材料中明确事实，不自动推成利好、交易完成、首次披露或PIT。六篇首次HKEX披露时间、原始PIT可用时间及相对旧公告增量均为 `CANNOT_CONFIRM`。', '',
    ]
    accounting_path = OUT / 'canary_capture_accounting_20260929_v2.json'
    if accounting_path.exists():
        accounting = load_json(accounting_path)
        lines += [
            f"- 缺首页三篇canary：原始逐URL回执记录 {accounting.get('unique_source_url_count')} 个不同URL，均为 HTTP 200、`from_cache=false`；原始响应合计 {accounting.get('captured_response_bytes')} bytes，最大单响应 {accounting.get('max_response_bytes')} bytes。原汇总JSON内 0 次/0 bytes 是后续缓存重放时的预算快照，不是首次采集量；物理HTTP跳数 `CANNOT_CONFIRM`。一致性仅 {accounting.get('text_consistency_reviewable_count')}/3 篇可复核。详见 `canary_capture_accounting_20260929_v2.json`；冻结原文件 `missing_page1_canary_20260929.json` 未改写。", '']
    elif canaries:
        lines += [f"- 缺首页三篇canary版本化回执：`{canaries.get('status')}`；原文一致性：`{canaries.get('text_consistency_evidence_status')}`（可完整复核 {canaries.get('text_consistency_reviewable_count')}/3 篇）。本次预算字段只描述本次命令运行，不能覆盖或替代原始逐URL采集回执。详见 `missing_page1_canary_20260929_v2.json`。", '']

    v2_run_path = OUT / 'body_corpus_20260929_v2' / 'capture_manifest.json'
    if v2_run_path.exists():
        run = load_json(v2_run_path)
        lines += [f"- 冻结的缺首页补采范围：目标 {run.get('target_count')} 篇；已处理 {run.get('processed_count')} 篇；正文状态计数 `{run.get('body_status_counts')}`；PDF状态计数 `{run.get('pdf_status_counts')}`。明细见 `body_corpus_20260929_v2.json`、`missing_page1_targets_20260929_v2.json` 和 `body_corpus_20260929_v2/capture_manifest.json`。", '']
    v2_audit_path = OUT / 'body_corpus_20260929_v2_readback_audit.json'
    if v2_audit_path.exists():
        audit = load_json(v2_audit_path)
        metrics = audit.get('document_run_metrics', {})
        lines += [f"- 41篇补采离线回执核对：`{audit.get('status')}`；137个不同URL各有一个尝试及终态回执（首次canary 2个，后续批次135个）；MaterialStore成功响应135份、合计 {audit.get('raw_response_bytes_across_successful_material_refs')} bytes，另2个PDF为一次性终态失败且无响应体。后续批次预算为 {metrics.get('provider_boundary_requests_this_run')} 次、{metrics.get('response_bytes_this_run')} bytes；物理HTTP跳数 `CANNOT_CONFIRM`。详见 `body_corpus_20260929_v2_readback_audit.json`。", '']
    pdf_text_path = OUT / 'pdf_text_canary_20260929_AN202609291830006795_v2.json'
    if pdf_text_path.exists():
        pdf_text = load_json(pdf_text_path)
        lines += [f"- 缺首页中期业绩PDF本地文本canary：`{pdf_text.get('status')}`；物理页 {pdf_text.get('pdf_page_count')}，分段 {len(pdf_text.get('segments', []))}，段长上限 {pdf_text.get('segment_character_limit')}字符；只用本地pypdfium2解析，不作PIT或语义结论。", '']
    lines += [
        '## 文件', '',
        '- `body_corpus_20260929.json` / `.csv`：234篇的逐篇正文状态、文本投影、来源ref、PDF状态和日期目录引用。',
        '- `six_interpretations_20260929.json` / `.md`：六篇事实、证券类别、完成/条件状态、物理页引用及未知项。',
        '- `missing_page1_canary_20260929.json`：冻结的原始三篇汇总回执；`missing_page1_canary_20260929_v2.json` 与 `canary_receipts/`：版本化汇总和逐URL attempt/response回执。',
        '- `canary_capture_accounting_20260929_v2.json`：从冻结逐URL回执验证原始采集量，并与后续预算快照分开。',
        '- `missing_page1_targets_20260929_v2.json`：由v1冻结的41篇补采目标与来源SHA。',
        '- `body_corpus_20260929_v2.json` / `.csv`：保留v1并追加41篇补采回执的独立版本。',
        '- `body_corpus_20260929_v2_readback_audit.json`：137个补采URL的attempt/terminal receipt与MaterialStore离线哈希核对。',
        '- `pdf_text_canary_20260929_AN202609291830006795_v2.json`：保存PDF按物理页切分、段SHA及完整页覆盖的本地文本canary。',
        '- `capture_missing_page1_v2.py`：冻结目标、回算canary计数、有限额补取及本地PDF文本canary脚本。',
        '- `capture_body_corpus.py`：可重复的离线清单构建和固定canary获取脚本。', '',
        '此批只达到数据/文本派生与小样本原文回执层；不代表V4产品状态、模型影响、公告首次披露、真实选股结果、部署、API/UI或自然时段验收。',
    ]
    (OUT / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else 'inventory'
    if mode not in {'inventory', 'canary', 'all'}:
        print('usage: capture_body_corpus.py [inventory|canary|all]', file=sys.stderr)
        return 2
    corpus = None
    interpretations = None
    if mode in {'inventory', 'all'}:
        corpus = build_body_corpus()
        write_inventory_outputs(corpus)
        interpretations = build_interpretations(corpus)
        write_interpretation_outputs(interpretations)
    canaries = run_canaries() if mode in {'canary', 'all'} else None
    if corpus is None:
        corpus = load_json(OUT / 'body_corpus_20260929.json')
    if interpretations is None:
        interpretations = load_json(OUT / 'six_interpretations_20260929.json')
    generate_readme(corpus, interpretations, canaries)
    print(json.dumps({'mode': mode, 'corpus_status': corpus.get('status'),
        'article_count': corpus.get('article_count'), 'body_status_counts': corpus.get('body_status_counts'),
        'pdf_status_counts': corpus.get('pdf_status_counts'), 'interpretation_status': interpretations.get('status'),
        'canary_status': canaries.get('status') if canaries else None}, ensure_ascii=False, sort_keys=True))
    return 0 if corpus.get('status') == 'PASS_INVENTORY_READBACK' and interpretations.get('status') == 'PASS_SOURCE_BINDINGS' and (not canaries or canaries.get('status') == 'PASS_THREE_SAMPLE_RAW_CAPTURE' and canaries.get('text_consistency_evidence_status') == 'REVIEWABLE_FOR_ALL_THREE') else 1


if __name__ == '__main__':
    raise SystemExit(main())
