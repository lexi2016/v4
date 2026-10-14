#!/usr/bin/env python3
"""Bounded local adaptation of the pinned RSSHub Zhitong announcement route.

The upstream route requests announcement page 1 only, selects its first `limit`
items, and uses create_time for pubDate. This trial paginates that same source
API to a fixed publish_time cutoff and uses the same article URL plus the same
digest/body CSS selectors. It does not run or deploy RSSHub.
"""

from __future__ import annotations

import csv
import hashlib
import html.parser
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
PAGE1_PATH = Path('/tmp/zt_announcement_page1.json')
CONNECT_CSV = ROOT / 'docs/handoffs/hk_connect_list_20261014/港股通股票名单_667只_20261014.csv'
UPSTREAM_RECEIPT = OUT / 'upstream_receipt.json'
API_URL = 'https://www.zhitongcaijing.com/announcement.html?data_type=1&page={page}'
SITE_ROOT = 'https://www.zhitongcaijing.com'
TZ = ZoneInfo('Asia/Shanghai')
WINDOW_START = datetime(2026, 10, 13, 22, 55, 58, tzinfo=TZ)
WINDOW_END = datetime(2026, 10, 14, 22, 55, 58, tzinfo=TZ)
MAX_PAGES = 25
MAX_BODY_ARTICLES = 200
BODY_WORKERS = 2
PAGE_PAUSE_SECONDS = 0.25
USER_AGENT = 'Mozilla/5.0 (compatible; ZhitongAnnouncementTrial/1.0; +https://github.com/DIYgod/RSSHub)'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iso_epoch(value: object) -> str | None:
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).astimezone(TZ).isoformat()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def as_epoch(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return None


def read_json_bytes(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    return json.loads(raw.decode('utf-8-sig')), raw


def fetch_json(url: str) -> tuple[dict, bytes, int]:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'application/json,text/plain,*/*'})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            status = response.status
            raw = response.read(15 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as exc:
        raw = exc.read(2 * 1024 * 1024)
        raise RuntimeError(f'HTTP {exc.code} for {url}: {raw[:300]!r}') from exc
    if len(raw) > 15 * 1024 * 1024:
        raise RuntimeError(f'response exceeded 15 MiB: {url}')
    try:
        parsed = json.loads(raw.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        if b'parm_0' in raw and b'parm_1' in raw and b'check()' in raw:
            raise RuntimeError(f'verification page returned for {url}') from exc
        raise RuntimeError(f'non-JSON response for {url}: {raw[:300]!r}') from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get('data'), list):
        raise RuntimeError(f'unexpected API envelope for {url}: {json.dumps(parsed, ensure_ascii=False)[:500]}')
    return parsed, raw, status


class TargetMarkupParser(html.parser.HTMLParser):
    TARGETS = {'digetst-box', 'telegram-origin-contentn', 'news-body-content'}
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
    DROP_IDS = {'subscribe-vip-box', 'news-content'}
    DROP_TAGS = {'script', 'style', 'noscript'}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: dict[str, dict[str, str]] = {}
        self.active: str | None = None
        self.depth = 0
        self.html_parts: list[str] = []
        self.text_parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key.lower(): value or '' for key, value in attrs}
        classes = set(values.get('class', '').split())
        is_void = tag.lower() in self.VOID
        dropped = values.get('id') in self.DROP_IDS or tag.lower() in self.DROP_TAGS
        if self.skip_depth:
            if not is_void:
                self.skip_depth += 1
            return
        if dropped:
            if not is_void:
                self.skip_depth = 1
            return
        match = next((name for name in self.TARGETS if name in classes and name not in self.results), None)
        if self.active:
            self.html_parts.append(self.get_starttag_text() or f'<{tag}>')
            if not is_void:
                self.depth += 1
        elif match:
            self.active = match
            self.depth = 1
            self.html_parts = [self.get_starttag_text() or f'<{tag}>']
            self.text_parts = []

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        if self.skip_depth:
            self.skip_depth = max(0, self.skip_depth - 1)
            return
        if not self.active:
            return
        self.html_parts.append(f'</{tag}>')
        self.depth -= 1
        if self.depth <= 0:
            self.results[self.active] = {
                'html': ''.join(self.html_parts),
                'text': ''.join(self.text_parts),
            }
            self.active = None
            self.depth = 0
            self.html_parts = []
            self.text_parts = []

    def handle_data(self, data: str) -> None:
        if self.active and not self.skip_depth:
            self.html_parts.append(data)
            self.text_parts.append(data)


def normalize_text(value: str) -> str:
    value = value.replace('\xa0', ' ')
    value = re.sub(r'[ \t\r\f\v]+', ' ', value)
    value = re.sub(r' *\n *', '\n', value)
    value = re.sub(r'\n{3,}', '\n\n', value)
    return value.strip()


def extract_upstream_sections(raw_html: str) -> dict[str, str]:
    parser = TargetMarkupParser()
    parser.feed(raw_html)
    parser.close()
    digest = parser.results.get('digetst-box') or parser.results.get('telegram-origin-contentn') or {}
    body = parser.results.get('news-body-content') or {}
    return {
        'digest_html': digest.get('html', ''),
        'digest_text': normalize_text(digest.get('text', '')),
        'body_html': body.get('html', ''),
        'body_text': normalize_text(body.get('text', '')),
    }


def fetch_article_body(row: dict) -> dict:
    url = urllib.parse.urljoin(SITE_ROOT, str(row.get('url') or ''))
    if not url.startswith(SITE_ROOT + '/'):
        return {'body_fetch_status': 'invalid_article_url', 'article_url': url}
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,*/*'})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            status = response.status
            raw = response.read(10 * 1024 * 1024 + 1)
        if len(raw) > 10 * 1024 * 1024:
            return {'body_fetch_status': 'response_over_10_mib', 'article_url': url, 'http_status': status}
        html_text = raw.decode('utf-8', errors='replace')
        sections = extract_upstream_sections(html_text)
        if not sections['body_text'] and not sections['digest_text']:
            is_check = 'check()' in html_text and 'parm_0' in html_text and 'parm_1' in html_text
            return {
                'body_fetch_status': 'verification_page' if is_check else 'selectors_empty',
                'article_url': url,
                'http_status': status,
                'response_sha256': sha256(raw),
                'response_bytes': len(raw),
                **sections,
            }
        full_text = '\n\n'.join(x for x in (sections['digest_text'], sections['body_text']) if x)
        return {
            'body_fetch_status': 'extracted',
            'article_url': url,
            'http_status': status,
            'response_sha256': sha256(raw),
            'response_bytes': len(raw),
            'body_text': full_text,
            'body_text_chars': len(full_text),
            'body_text_utf8_bytes': len(full_text.encode('utf-8')),
            'digest_html': sections['digest_html'],
            'body_html': sections['body_html'],
        }
    except urllib.error.HTTPError as exc:
        raw = exc.read(1024 * 1024)
        return {'body_fetch_status': f'http_{exc.code}', 'article_url': url, 'http_status': exc.code, 'error_excerpt': raw[:300].decode('utf-8', errors='replace')}
    except Exception as exc:  # record one bounded attempt; no blind retry
        return {'body_fetch_status': 'request_error', 'article_url': url, 'error': f'{type(exc).__name__}: {exc}'}


def read_connect_codes() -> tuple[set[str], str]:
    raw = CONNECT_CSV.read_bytes()
    codes: set[str] = set()
    with CONNECT_CSV.open('r', encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = re.sub(r'\D', '', (row.get('港股代码') or '').strip())
            if code:
                codes.add(code.zfill(5))
    return codes, sha256(raw)


def codes_from_stock_list(value: object) -> list[str]:
    result: set[str] = set()
    for code in re.findall(r'(?<!\d)\d{4,5}(?!\d)', str(value or '')):
        result.add(code.zfill(5))
    return sorted(result)


def candidate_flags(row: dict) -> dict:
    text = ' '.join(str(row.get(k) or '') for k in ('title', 'digest', 'body_text'))
    quantified = bool(
        re.search(r'订单|合同|合约|订立|签订|中标|供货|采购|EPC|销售协议|销售合同', text, re.I)
        and re.search(r'\d[\d,.]*\s*(?:亿元|亿港元|亿港币|亿元人民币|万元|万港元|万港币|万美元|百万|千万|港元|人民币|美元)', text)
    )
    earnings = bool(re.search(r'预增|扭亏|净利润.{0,12}(?:增长|上升|增加)|盈利.{0,12}增长|收入.{0,12}增长|业绩.{0,12}(?:增长|改善|大增)', text))
    approval = bool(re.search(r'(?:获批|获准|获得.{0,8}批准|批准.{0,8}(?:上市|注册|商业化)|授出.{0,8}上市批准)', text) and re.search(r'药|医疗|注册证|上市许可|商业化|产品|药品|生物', text))
    transaction = bool(
        re.search(r'收购|出售|转让|投资|注资|并购|合资|资产交易|股权交易|购入|收购事项', text)
        and re.search(r'\d[\d,.]*\s*(?:亿元|亿港元|亿港币|亿元人民币|万元|万港元|万港币|万美元|百万|千万|港元|人民币|美元)', text)
    )
    buyback = bool(re.search(r'回购|购回', text))
    buyback_plan = bool(buyback and re.search(r'计划|授权|扩大|增加|调整|最高|不超过|额度|延长', text))
    routine_buyback = bool(buyback and not buyback_plan and re.search(r'斥资|购回.{0,12}股|回购.{0,12}股|今日|当日|10月14日', text))
    excluded = []
    if re.search(r'配股|供股|发行.{0,12}(?:债券|票据)|融资|可续期公司债', text):
        excluded.append('financing')
    if re.search(r'全流通', text):
        excluded.append('full_float')
    if re.search(r'委任|获委任|辞任|辞职|核数师|董事会主席', text):
        excluded.append('personnel')
    core = quantified or earnings or approval or transaction
    return {
        'quantified_order_contract_candidate': quantified,
        'earnings_improvement_candidate': earnings,
        'approved_commercialization_candidate': approval,
        'material_transaction_candidate': transaction,
        'expanded_buyback_plan_candidate': buyback_plan,
        'routine_daily_buyback': routine_buyback,
        'excluded_non_catalyst_tags': excluded,
        'core_candidate_flag': bool(core),
        'candidate_rule_note': 'keyword/amount screen only; requires human semantic review and original-filing verification',
    }


def page_summary(page: int, source: str, payload: dict, raw: bytes, http_status: int | None) -> dict:
    rows = payload['data']
    stamps = [as_epoch(row.get('publish_time')) for row in rows]
    stamps = [x for x in stamps if x is not None]
    return {
        'page': page,
        'source': source,
        'request_url': None if page == 1 else API_URL.format(page=page),
        'http_status': http_status,
        'response_sha256': sha256(raw),
        'item_count': len(rows),
        'newest_publish_time': iso_epoch(max(stamps)) if stamps else None,
        'oldest_publish_time': iso_epoch(min(stamps)) if stamps else None,
        'has_at_or_before_start': any(x <= int(WINDOW_START.timestamp()) for x in stamps),
        'content_ids': [str(row.get('content_id') or row.get('id') or '') for row in rows],
    }


def main() -> int:
    if not PAGE1_PATH.is_file():
        raise SystemExit(f'missing cached page-one input: {PAGE1_PATH}')
    if not CONNECT_CSV.is_file():
        raise SystemExit(f'missing authorized Stock Connect list: {CONNECT_CSV}')
    upstream = json.loads(UPSTREAM_RECEIPT.read_text(encoding='utf-8'))
    route_bytes = (OUT / 'upstream_zhitong_route.tsx').read_bytes()
    if sha256(route_bytes) != upstream['source_sha256']:
        raise SystemExit('pinned route source SHA mismatch')

    page1, page1_raw = read_json_bytes(PAGE1_PATH)
    if not isinstance(page1, dict) or not isinstance(page1.get('data'), list):
        raise SystemExit('cached page-one input has an unexpected shape')
    connect_codes, connect_sha = read_connect_codes()
    page_log = [page_summary(1, str(PAGE1_PATH), page1, page1_raw, None)]
    seen_rows: dict[str, dict] = {}
    duplicate_rows = 0
    boundary_reached = page_log[0]['has_at_or_before_start']
    fetch_error = None
    for row in page1['data']:
        key = str(row.get('content_id') or row.get('id') or row.get('url') or '')
        if key in seen_rows:
            duplicate_rows += 1
        else:
            seen_rows[key] = row

    if not boundary_reached:
        for page in range(2, MAX_PAGES + 1):
            time.sleep(PAGE_PAUSE_SECONDS)
            try:
                payload, raw, status = fetch_json(API_URL.format(page=page))
            except Exception as exc:
                fetch_error = f'page {page}: {type(exc).__name__}: {exc}'
                break
            page_log.append(page_summary(page, 'live_api', payload, raw, status))
            stamps = [as_epoch(row.get('publish_time')) for row in payload['data']]
            stamps = [x for x in stamps if x is not None]
            for row in payload['data']:
                key = str(row.get('content_id') or row.get('id') or row.get('url') or '')
                if key in seen_rows:
                    duplicate_rows += 1
                else:
                    seen_rows[key] = row
            if any(x <= int(WINDOW_START.timestamp()) for x in stamps):
                boundary_reached = True
                break
            if len(payload['data']) == 0:
                break

    start_epoch = int(WINDOW_START.timestamp())
    end_epoch = int(WINDOW_END.timestamp())
    category_rows = []
    missing_publish = 0
    out_of_window = 0
    for row in seen_rows.values():
        stamp = as_epoch(row.get('publish_time'))
        category = str(row.get('category_name') or row.get('category', {}).get('category_name') or '')
        if category != '港股公告':
            continue
        if stamp is None:
            missing_publish += 1
            continue
        if start_epoch < stamp <= end_epoch:
            category_rows.append(row)
        else:
            out_of_window += 1
    category_rows.sort(key=lambda r: (as_epoch(r.get('publish_time')) or 0, str(r.get('content_id') or '')))

    body_errors = []
    body_count = len(category_rows)
    if body_count <= MAX_BODY_ARTICLES:
        selected_for_body = category_rows
    else:
        selected_for_body = []
        prelim_terms = re.compile(r'订单|合同|合约|中标|收购|出售|投资|注资|业绩|利润|收入|获批|批准|药|产品|回购|股权|资产', re.I)
        for row in category_rows:
            if prelim_terms.search(f"{row.get('title', '')} {row.get('digest', '')}"):
                selected_for_body.append(row)
        if len(selected_for_body) > MAX_BODY_ARTICLES:
            selected_for_body = selected_for_body[:MAX_BODY_ARTICLES]

    body_results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=BODY_WORKERS) as pool:
        futures = {}
        for row in selected_for_body:
            key = str(row.get('content_id') or row.get('id') or row.get('url') or '')
            futures[pool.submit(fetch_article_body, row)] = key
        for future in as_completed(futures):
            key = futures[future]
            try:
                body_results[key] = future.result()
            except Exception as exc:
                body_results[key] = {'body_fetch_status': 'worker_error', 'error': f'{type(exc).__name__}: {exc}'}

    output_rows = []
    for raw_row in category_rows:
        row = dict(raw_row)
        row['raw_api_metadata'] = dict(raw_row)
        key = str(row.get('content_id') or row.get('id') or row.get('url') or '')
        stock_codes = codes_from_stock_list(row.get('stock_list'))
        matched = sorted(set(stock_codes) & connect_codes)
        body = body_results.get(key, {'body_fetch_status': 'skipped_body_cap'})
        row['raw_publish_time'] = row.get('publish_time')
        row['publish_time_iso_shanghai'] = iso_epoch(row.get('publish_time'))
        row['create_time_iso_shanghai'] = iso_epoch(row.get('create_time'))
        row['update_time_iso_shanghai'] = iso_epoch(row.get('update_time'))
        row['stock_codes_parsed'] = stock_codes
        row['hkconnect_match'] = bool(matched)
        row['hkconnect_matched_codes'] = matched
        row['body'] = body
        row.update(candidate_flags({
            'title': row.get('title'),
            'digest': row.get('digest'),
            'body_text': body.get('body_text', ''),
        }))
        if body.get('body_fetch_status') != 'extracted':
            body_errors.append({'content_id': key, 'title': row.get('title'), 'status': body.get('body_fetch_status')})
        output_rows.append(row)

    articles_json = OUT / 'articles_window.json'
    articles_json.write_text(json.dumps(output_rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    titles_csv = OUT / 'titles_for_semantic_review.csv'
    csv_fields = [
        'content_id', 'title', 'stock_list', 'hkconnect_match', 'hkconnect_matched_codes',
        'publish_time_iso_shanghai', 'create_time_iso_shanghai', 'update_time_iso_shanghai',
        'digest', 'core_candidate_flag', 'quantified_order_contract_candidate',
        'earnings_improvement_candidate', 'approved_commercialization_candidate',
        'material_transaction_candidate', 'expanded_buyback_plan_candidate',
        'routine_daily_buyback', 'excluded_non_catalyst_tags', 'body_fetch_status',
    ]
    with titles_csv.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction='ignore')
        writer.writeheader()
        for row in output_rows:
            flat = dict(row)
            flat['body_fetch_status'] = (row.get('body') or {}).get('body_fetch_status')
            flat['excluded_non_catalyst_tags'] = ';'.join(row.get('excluded_non_catalyst_tags') or [])
            flat['hkconnect_matched_codes'] = ';'.join(row.get('hkconnect_matched_codes') or [])
            writer.writerow(flat)

    all_csv = OUT / 'articles_window.csv'
    all_fields = [
        'content_id', 'title', 'category_name', 'stock_list', 'hkconnect_match', 'hkconnect_matched_codes',
        'publish_time', 'publish_time_iso_shanghai', 'create_time', 'create_time_iso_shanghai',
        'update_time', 'update_time_iso_shanghai', 'digest', 'url', 'keywords', 'author_info',
        'body_fetch_status', 'body_text', 'body_text_chars', 'body_text_utf8_bytes', 'body_html', 'digest_html',
        'core_candidate_flag', 'quantified_order_contract_candidate', 'earnings_improvement_candidate',
        'approved_commercialization_candidate', 'material_transaction_candidate', 'expanded_buyback_plan_candidate',
        'routine_daily_buyback', 'excluded_non_catalyst_tags', 'raw_metadata_json',
    ]
    with all_csv.open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction='ignore')
        writer.writeheader()
        for row in output_rows:
            body = row.get('body') or {}
            flat = dict(row)
            flat.update({k: body.get(k) for k in ('body_fetch_status', 'body_text', 'body_text_chars', 'body_text_utf8_bytes', 'body_html', 'digest_html')})
            flat['author_info'] = json.dumps(row.get('author_info'), ensure_ascii=False, separators=(',', ':'))
            flat['raw_metadata_json'] = json.dumps(row.get('raw_api_metadata') or {}, ensure_ascii=False, separators=(',', ':'))
            flat['hkconnect_matched_codes'] = ';'.join(row.get('hkconnect_matched_codes') or [])
            flat['excluded_non_catalyst_tags'] = ';'.join(row.get('excluded_non_catalyst_tags') or [])
            writer.writerow(flat)

    page_log_path = OUT / 'page_scan.json'
    page_log_path.write_text(json.dumps(page_log, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    counts = {
        'hk_announcement_window_rows': len(output_rows),
        'unique_content_ids': len({str(x.get('content_id') or x.get('id') or x.get('url') or '') for x in output_rows}),
        'duplicate_rows_across_scanned_pages': duplicate_rows,
        'stockconnect_matched_rows': sum(bool(x.get('hkconnect_match')) for x in output_rows),
        'core_candidate_flag_rows': sum(bool(x.get('core_candidate_flag')) for x in output_rows),
        'quantified_order_contract_candidate_rows': sum(bool(x.get('quantified_order_contract_candidate')) for x in output_rows),
        'earnings_improvement_candidate_rows': sum(bool(x.get('earnings_improvement_candidate')) for x in output_rows),
        'approved_commercialization_candidate_rows': sum(bool(x.get('approved_commercialization_candidate')) for x in output_rows),
        'material_transaction_candidate_rows': sum(bool(x.get('material_transaction_candidate')) for x in output_rows),
        'expanded_buyback_plan_candidate_rows': sum(bool(x.get('expanded_buyback_plan_candidate')) for x in output_rows),
        'routine_daily_buyback_rows': sum(bool(x.get('routine_daily_buyback')) for x in output_rows),
        'body_extracted_rows': sum((x.get('body') or {}).get('body_fetch_status') == 'extracted' for x in output_rows),
        'body_failed_or_skipped_rows': len(body_errors),
        'missing_publish_time_scanned_hk_category_rows': missing_publish,
        'out_of_window_hk_category_rows_scanned': out_of_window,
        'pages_scanned': len(page_log),
        'unique_scanned_source_rows': len(seen_rows),
        'max_page_bound': MAX_PAGES,
        'body_request_concurrency': BODY_WORKERS,
    }
    extracted_body_rows = counts['body_extracted_rows']
    final_state = 'PASS' if boundary_reached and not fetch_error and body_count <= MAX_BODY_ARTICLES and extracted_body_rows > 0 else 'CANNOT_CONFIRM'
    receipt = {
        'status': final_state,
        'goal': 'bounded research-only trial of the Zhitong 港股公告 column for one frozen 24-hour window',
        'window': {
            'timezone': 'Asia/Shanghai',
            'start_exclusive': WINDOW_START.isoformat(),
            'end_inclusive': WINDOW_END.isoformat(),
            'date_field_for_filter': 'publish_time (raw Unix seconds)',
            'create_time_and_update_time_preserved': True,
        },
        'scope': {
            'source_channel': '智通财经 announcement route; rows restricted to category_name == 港股公告',
            'market_claim': 'Zhitong 港股公告栏目 coverage only; not all market announcements',
            'stockconnect_match_source': str(CONNECT_CSV),
            'stockconnect_membership_recomputed': False,
        },
        'upstream': upstream,
        'adaptation': {
            'type': 'faithful minimal local adaptation; RSSHub handler not executed/deployed',
            'same_source_endpoint': API_URL,
            'same_upstream_selectors': ['.digetst-box', '.telegram-origin-contentn (fallback)', '.news-body-content'],
            'differences_required_for_trial': ['paginate page=1..N until publish_time crosses frozen start', 'filter on publish_time; upstream route maps create_time to pubDate', 'retain all raw API metadata and extracted body text', 'HK Connect match against provided CSV'],
            'page_cap': MAX_PAGES,
            'body_article_cap': MAX_BODY_ARTICLES,
            'body_concurrency': BODY_WORKERS,
            'retry_policy': 'single attempt per page/body; no blind retries',
        },
        'inputs': {
            'page1_path': str(PAGE1_PATH),
            'page1_sha256': sha256(page1_raw),
            'page1_mtime_epoch': PAGE1_PATH.stat().st_mtime,
            'hkconnect_csv_path': str(CONNECT_CSV),
            'hkconnect_csv_sha256': connect_sha,
        },
        'pagination': {
            'boundary_reached': boundary_reached,
            'fetch_error': fetch_error,
            'stop_reason': 'first page containing publish_time <= window start' if boundary_reached else ('fetch error' if fetch_error else 'page cap, empty response, or no older timestamp'),
            'pages_scanned': len(page_log),
            'page_scan_path': str(page_log_path),
        },
        'counts': counts,
        'body_errors': body_errors,
        'body_coverage_complete': len(body_errors) == 0 and body_count <= MAX_BODY_ARTICLES,
        'artifacts': {
            'articles_json': str(articles_json),
            'articles_csv': str(all_csv),
            'semantic_review_titles_csv': str(titles_csv),
            'page_scan_json': str(page_log_path),
        },
        'candidate_semantics': 'Flags are deterministic title/digest/body keyword and amount screens only; they are not a financial ranking or final valuable-announcement count. Routine daily buybacks and financing/personnel/full-float notices are explicitly separated. Original filings were not all cross-checked.',
        'research_only': True,
        'production_allowed': False,
        'buy_gate_updated': False,
        'orders_sent': False,
    }
    (OUT / 'trial_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': final_state, 'counts': counts, 'pagination': receipt['pagination'], 'body_errors': body_errors, 'artifacts': receipt['artifacts']}, ensure_ascii=False, indent=2))
    return 0 if final_state == 'PASS' else 2


def extend_pages_11_to_25() -> int:
    """One-shot extension of the preserved 10-page capture; never refetch old bodies."""
    if not PAGE1_PATH.is_file() or not CONNECT_CSV.is_file():
        raise SystemExit('required cached page-one input or Stock Connect list is missing')
    extension_receipt_path = OUT / 'extension_receipt.json'
    if extension_receipt_path.exists():
        raise SystemExit(f'extension already recorded; refusing a second network scan: {extension_receipt_path}')

    initial_scan_path = OUT / 'page_scan_initial_10.json'
    initial_receipt_path = OUT / 'trial_receipt_initial.json'
    articles_path = OUT / 'articles_window.json'
    if not all(path.is_file() for path in (initial_scan_path, initial_receipt_path, articles_path)):
        raise SystemExit('preserved initial scan, receipt, or article set is missing')
    initial_scan = json.loads(initial_scan_path.read_text(encoding='utf-8'))
    receipt = json.loads((OUT / 'trial_receipt.json').read_text(encoding='utf-8'))
    upstream = json.loads(UPSTREAM_RECEIPT.read_text(encoding='utf-8'))
    route_bytes = (OUT / 'upstream_zhitong_route.tsx').read_bytes()
    if sha256(route_bytes) != upstream['source_sha256']:
        raise SystemExit('pinned route source SHA mismatch')
    rows = json.loads(articles_path.read_text(encoding='utf-8'))
    if len(initial_scan) != 10 or len(rows) != 181:
        raise SystemExit('initial evidence differs from the expected preserved 10-page / 181-row capture')

    connect_codes, connect_sha = read_connect_codes()
    start_epoch = int(WINDOW_START.timestamp())
    end_epoch = int(WINDOW_END.timestamp())
    seen_ids = {
        str(content_id)
        for page in initial_scan
        for content_id in page.get('content_ids', [])
        if str(content_id)
    }
    existing_article_ids = {
        str(row.get('content_id') or row.get('id') or row.get('url') or '')
        for row in rows
    }
    new_ids: set[str] = set()
    new_window_rows: list[dict] = []
    extension_pages: list[dict] = []
    extension_unique_source_rows = 0
    extension_duplicates = 0
    extension_missing_publish = 0
    extension_out_of_window = 0
    fetch_error = None
    exhausted = False
    stop_reason = 'page cap reached'
    for page in range(11, MAX_PAGES + 1):
        time.sleep(PAGE_PAUSE_SECONDS)
        try:
            payload, raw, status = fetch_json(API_URL.format(page=page))
        except Exception as exc:
            fetch_error = f'page {page}: {type(exc).__name__}: {exc}'
            stop_reason = 'fetch error'
            break
        extension_pages.append(page_summary(page, 'live_api', payload, raw, status))
        page_rows = payload['data']
        if not page_rows:
            exhausted = True
            stop_reason = f'empty page {page}'
            break
        for row in page_rows:
            key = str(row.get('content_id') or row.get('id') or row.get('url') or '')
            if not key:
                continue
            if key in seen_ids:
                extension_duplicates += 1
                continue
            seen_ids.add(key)
            extension_unique_source_rows += 1
            category = str(row.get('category_name') or row.get('category', {}).get('category_name') or '')
            if category != '港股公告':
                continue
            stamp = as_epoch(row.get('publish_time'))
            if stamp is None:
                extension_missing_publish += 1
            elif start_epoch < stamp <= end_epoch:
                if key not in existing_article_ids and key not in new_ids:
                    new_ids.add(key)
                    new_window_rows.append(row)
            else:
                extension_out_of_window += 1
    if extension_pages and extension_pages[-1]['page'] == MAX_PAGES and not exhausted and not fetch_error:
        stop_reason = f'page cap {MAX_PAGES} reached with nonempty response'

    discovery_path = OUT / 'extension_discovery.json'
    discovery = {
        'scope': 'single incremental scan of pages 11 through 25 from the pinned announcement API',
        'initial_page_scan_sha256': sha256(initial_scan_path.read_bytes()),
        'fetched_pages': extension_pages,
        'new_in_window_rows': new_window_rows,
        'new_in_window_content_ids': sorted(new_ids),
        'new_in_window_titles': [
            {'content_id': str(row.get('content_id') or row.get('id') or ''), 'title': row.get('title'), 'stock_list': row.get('stock_list'), 'publish_time_iso_shanghai': iso_epoch(row.get('publish_time')), 'digest': row.get('digest')}
            for row in new_window_rows
        ],
        'fetch_error': fetch_error,
        'exhausted_by_empty_page': exhausted,
        'stop_reason': stop_reason,
        'page_cap_reached_without_end_proof': bool(extension_pages and extension_pages[-1]['page'] == MAX_PAGES and not exhausted and not fetch_error),
    }
    discovery_path.write_text(json.dumps(discovery, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    titles_path = OUT / 'new_titles_for_semantic_review.csv'
    with titles_path.open('w', encoding='utf-8-sig', newline='') as f:
        fields = ['content_id', 'title', 'stock_list', 'publish_time_iso_shanghai', 'digest']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(discovery['new_in_window_titles'])
    print(json.dumps({
        'phase': 'discovery_complete',
        'pages_fetched': [item['page'] for item in extension_pages],
        'new_in_window_count': len(new_window_rows),
        'new_titles': discovery['new_in_window_titles'],
        'stop_reason': stop_reason,
    }, ensure_ascii=False), flush=True)

    # The original 181 article bodies are kept byte-for-byte in their rows.
    old_body_attempts = sum(bool(row.get('body')) for row in rows)
    remaining_body_slots = max(0, MAX_BODY_ARTICLES - old_body_attempts)
    selected_new_rows = sorted(
        new_window_rows,
        key=lambda row: (as_epoch(row.get('publish_time')) or 0, str(row.get('content_id') or '')),
    )[:remaining_body_slots]
    selected_ids = {str(row.get('content_id') or row.get('id') or row.get('url') or '') for row in selected_new_rows}
    body_results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=BODY_WORKERS) as pool:
        futures = {
            pool.submit(fetch_article_body, row): str(row.get('content_id') or row.get('id') or row.get('url') or '')
            for row in selected_new_rows
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                body_results[key] = future.result()
            except Exception as exc:
                body_results[key] = {'body_fetch_status': 'worker_error', 'error': f'{type(exc).__name__}: {exc}'}

    new_output_rows = []
    for raw_row in new_window_rows:
        row = dict(raw_row)
        row['raw_api_metadata'] = dict(raw_row)
        key = str(row.get('content_id') or row.get('id') or row.get('url') or '')
        stock_codes = codes_from_stock_list(row.get('stock_list'))
        matched = sorted(set(stock_codes) & connect_codes)
        body = body_results.get(key, {'body_fetch_status': 'skipped_body_cap'})
        row['raw_publish_time'] = row.get('publish_time')
        row['publish_time_iso_shanghai'] = iso_epoch(row.get('publish_time'))
        row['create_time_iso_shanghai'] = iso_epoch(row.get('create_time'))
        row['update_time_iso_shanghai'] = iso_epoch(row.get('update_time'))
        row['stock_codes_parsed'] = stock_codes
        row['hkconnect_match'] = bool(matched)
        row['hkconnect_matched_codes'] = matched
        row['body'] = body
        row.update(candidate_flags({'title': row.get('title'), 'digest': row.get('digest'), 'body_text': body.get('body_text', '')}))
        new_output_rows.append(row)

    merged_by_id = {str(row.get('content_id') or row.get('id') or row.get('url') or ''): row for row in rows}
    for row in new_output_rows:
        key = str(row.get('content_id') or row.get('id') or row.get('url') or '')
        if key not in merged_by_id:
            merged_by_id[key] = row
    rows = sorted(merged_by_id.values(), key=lambda row: (as_epoch(row.get('publish_time')) or 0, str(row.get('content_id') or '')))
    articles_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    def csv_values(row: dict) -> dict:
        value = dict(row)
        body = row.get('body') or {}
        value.update({key: body.get(key) for key in ('body_fetch_status', 'body_text', 'body_text_chars', 'body_text_utf8_bytes', 'body_html', 'digest_html')})
        value['author_info'] = json.dumps(row.get('author_info'), ensure_ascii=False, separators=(',', ':'))
        value['raw_metadata_json'] = json.dumps(row.get('raw_api_metadata') or {}, ensure_ascii=False, separators=(',', ':'))
        value['hkconnect_matched_codes'] = ';'.join(row.get('hkconnect_matched_codes') or [])
        value['excluded_non_catalyst_tags'] = ';'.join(row.get('excluded_non_catalyst_tags') or [])
        return value

    csv_fields = [
        'content_id', 'title', 'category_name', 'stock_list', 'hkconnect_match', 'hkconnect_matched_codes',
        'publish_time', 'publish_time_iso_shanghai', 'create_time', 'create_time_iso_shanghai',
        'update_time', 'update_time_iso_shanghai', 'digest', 'url', 'keywords', 'author_info',
        'body_fetch_status', 'body_text', 'body_text_chars', 'body_text_utf8_bytes', 'body_html', 'digest_html',
        'core_candidate_flag', 'review_candidate_flag', 'quantified_order_contract_candidate', 'earnings_improvement_candidate',
        'approved_commercialization_candidate', 'material_transaction_candidate', 'expanded_buyback_plan_candidate',
        'routine_daily_buyback', 'excluded_non_catalyst_tags', 'raw_metadata_json',
    ]
    with (OUT / 'articles_window.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(csv_values(row) for row in rows)
    titles_fields = [
        'content_id', 'title', 'stock_list', 'hkconnect_match', 'hkconnect_matched_codes',
        'publish_time_iso_shanghai', 'create_time_iso_shanghai', 'update_time_iso_shanghai', 'digest',
        'core_candidate_flag', 'review_candidate_flag', 'quantified_order_contract_candidate', 'earnings_improvement_candidate',
        'approved_commercialization_candidate', 'material_transaction_candidate', 'expanded_buyback_plan_candidate',
        'routine_daily_buyback', 'excluded_non_catalyst_tags', 'body_fetch_status',
    ]
    with (OUT / 'titles_for_semantic_review.csv').open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=titles_fields, extrasaction='ignore')
        writer.writeheader()
        for row in rows:
            value = dict(row)
            value['body_fetch_status'] = (row.get('body') or {}).get('body_fetch_status')
            value['excluded_non_catalyst_tags'] = ';'.join(row.get('excluded_non_catalyst_tags') or [])
            value['hkconnect_matched_codes'] = ';'.join(row.get('hkconnect_matched_codes') or [])
            writer.writerow(value)

    combined_page_log = initial_scan + extension_pages
    page_log_path = OUT / 'page_scan.json'
    page_log_path.write_text(json.dumps(combined_page_log, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    body_errors = [
        {'content_id': str(row.get('content_id') or row.get('id') or ''), 'title': row.get('title'), 'status': (row.get('body') or {}).get('body_fetch_status')}
        for row in rows if (row.get('body') or {}).get('body_fetch_status') != 'extracted'
    ]
    counts = receipt['counts']
    counts.update({
        'hk_announcement_window_rows': len(rows),
        'unique_content_ids': len({str(row.get('content_id') or row.get('id') or row.get('url') or '') for row in rows}),
        'duplicate_rows_across_scanned_pages': counts.get('duplicate_rows_across_scanned_pages', 0) + extension_duplicates,
        'stockconnect_matched_rows': sum(bool(row.get('hkconnect_match')) for row in rows),
        'core_candidate_flag_rows': sum(bool(row.get('core_candidate_flag')) for row in rows),
        'quantified_order_contract_candidate_rows': sum(bool(row.get('quantified_order_contract_candidate')) for row in rows),
        'earnings_improvement_candidate_rows': sum(bool(row.get('earnings_improvement_candidate')) for row in rows),
        'approved_commercialization_candidate_rows': sum(bool(row.get('approved_commercialization_candidate')) for row in rows),
        'material_transaction_candidate_rows': sum(bool(row.get('material_transaction_candidate')) for row in rows),
        'expanded_buyback_plan_candidate_rows': sum(bool(row.get('expanded_buyback_plan_candidate')) for row in rows),
        'routine_daily_buyback_rows': sum(bool(row.get('routine_daily_buyback')) for row in rows),
        'body_extracted_rows': sum((row.get('body') or {}).get('body_fetch_status') == 'extracted' for row in rows),
        'body_failed_or_skipped_rows': len(body_errors),
        'missing_publish_time_scanned_hk_category_rows': counts.get('missing_publish_time_scanned_hk_category_rows', 0) + extension_missing_publish,
        'out_of_window_hk_category_rows_scanned': counts.get('out_of_window_hk_category_rows_scanned', 0) + extension_out_of_window,
        'pages_scanned': len(combined_page_log),
        'unique_scanned_source_rows': counts.get('unique_scanned_source_rows', 0) + extension_unique_source_rows,
        'extension_new_window_rows': len(new_output_rows),
        'extension_bodies_attempted': len(selected_new_rows),
        'review_candidate_flag_rows': sum(bool(row.get('review_candidate_flag')) for row in rows),
        'max_page_bound': MAX_PAGES,
    })
    receipt['counts'] = counts
    receipt['body_errors'] = body_errors
    receipt['body_coverage_complete'] = len(body_errors) == 0 and len(rows) <= MAX_BODY_ARTICLES
    receipt['pagination'].update({
        'stop_reason': stop_reason,
        'pages_scanned': len(combined_page_log),
        'full_window_set_complete': exhausted,
        'extension_page_range': '11..25',
        'extension_pages_scanned': [item['page'] for item in extension_pages],
        'extension_fetch_error': fetch_error,
        'page_cap_reached_without_end_proof': discovery['page_cap_reached_without_end_proof'],
        'extension_discovery_path': str(discovery_path),
        'page_scan_path': str(page_log_path),
    })
    receipt['artifacts'].update({
        'page_scan_json': str(page_log_path),
        'extension_discovery_json': str(discovery_path),
        'new_titles_for_semantic_review_csv': str(titles_path),
    })
    receipt['semantic_review'] = dict(receipt.get('semantic_review') or {})
    if new_output_rows:
        receipt['semantic_review']['review_status'] = 'initial 181 rows reviewed; newly discovered extension rows pending controller semantic review'
        receipt['semantic_review']['extension_pending_content_ids'] = sorted(new_ids)
    cannot_confirm = list(receipt.get('cannot_confirm') or [])
    if not exhausted:
        reason = 'Extension stopped before an empty/end page; the full 24-hour set cannot be confirmed from pages 1-25.' if not fetch_error else f'Extension fetch error: {fetch_error}; the full 24-hour set cannot be confirmed.'
        if reason not in cannot_confirm:
            cannot_confirm.append(reason)
    if new_output_rows:
        cannot_confirm.append('New extension rows are pending controller semantic review; prior semantic counts cover the initial 181 rows only.')
    receipt['cannot_confirm'] = cannot_confirm
    receipt['status'] = 'CANNOT_CONFIRM' if (not exhausted or fetch_error or new_output_rows) else 'PASS'
    receipt.setdefault('collection_execution', {})['extension_command'] = 'python3 docs/handoffs/zhitong_announcement_trial_20261014/zt_trial_collector.py --extend-pages-11-25'
    receipt['collection_execution']['extension_collector_sha256'] = sha256(Path(__file__).read_bytes())
    receipt['collection_execution']['extension_outcome'] = stop_reason
    receipt['collection_execution']['extension_new_rows'] = len(new_output_rows)
    receipt['collection_execution']['extension_body_requests'] = len(selected_new_rows)

    artifact_hashes = dict(receipt.get('artifact_sha256') or {})
    for filename in ('zt_trial_collector.py', 'articles_window.json', 'articles_window.csv', 'titles_for_semantic_review.csv', 'page_scan.json'):
        artifact_hashes[filename] = sha256((OUT / filename).read_bytes())
    artifact_hashes['extension_discovery.json'] = sha256(discovery_path.read_bytes())
    artifact_hashes['new_titles_for_semantic_review.csv'] = sha256(titles_path.read_bytes())
    receipt['artifact_sha256'] = artifact_hashes
    (OUT / 'trial_receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    extension_receipt = {
        'status': receipt['status'],
        'stop_reason': stop_reason,
        'full_window_set_complete': exhausted,
        'page_cap_reached_without_end_proof': discovery['page_cap_reached_without_end_proof'],
        'fetch_error': fetch_error,
        'new_window_rows': len(new_output_rows),
        'new_body_attempts': len(selected_new_rows),
        'new_body_ids': sorted(selected_ids),
        'body_errors': body_errors,
        'pages_fetched': [item['page'] for item in extension_pages],
        'artifact_sha256': {name: artifact_hashes[name] for name in ('extension_discovery.json', 'new_titles_for_semantic_review.csv', 'articles_window.json', 'articles_window.csv', 'titles_for_semantic_review.csv', 'page_scan.json')},
    }
    extension_receipt_path.write_text(json.dumps(extension_receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(extension_receipt, ensure_ascii=False, indent=2))
    return 0 if receipt['status'] == 'PASS' else 2


if __name__ == '__main__':
    if sys.argv[1:] == ['--extend-pages-11-25']:
        sys.exit(extend_pages_11_to_25())
    if sys.argv[1:]:
        raise SystemExit('usage: zt_trial_collector.py [--extend-pages-11-25]')
    sys.exit(main())
