#!/usr/bin/env python3
"""Build a 234-announcement retrospective catalog from frozen, source-reviewed shards.

The frozen 167-row v1 is copied verbatim as the first subset. New short and long
interpretations are joined to their existing API/PDF evidence. Five rows with
failed over-limit PDF capture are explicitly coverage gaps and receive no event
interpretation.
"""
from __future__ import annotations
import csv, hashlib, json, unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
V1 = ROOT / 'semantic_catalog_20260929_v1.json'
SHORT = ROOT / 'semantic_short_additions_20260929.json'
LONG = ROOT / 'semantic_long_additions_20260929.json'
CORPUS = ROOT / 'body_corpus_20260929_v3.json'
PDF_INDEX = ROOT / 'pdf_text_derivatives_20260929_v3_index.json'
OUT_JSON = ROOT / 'semantic_catalog_20260929_v2.json'
OUT_CSV = ROOT / 'semantic_catalog_20260929_v2.csv'
OUT_MD = ROOT / 'semantic_catalog_20260929_v2.md'
TARGET_DATE = '2026-09-30'
GAP_CODES = [
    'AN202609291829994275', 'AN202609291829995972',
    'AN202609291829997181', 'AN202609291830002066',
    'AN202609291830005457',
]


def sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def norm(s: str) -> str:
    s = unicodedata.normalize('NFKC', s or '')
    return ''.join(s.split())


def load_json(path: Path):
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def date_fields(src):
    pages = src.get('pages') or []
    p = pages[0] if pages else {}
    notice = src.get('content_notice_date') or p.get('notice_date')
    display = src.get('content_display_time') or p.get('display_time')
    retrieved = p.get('retrieved_at')
    return {
        'notice_date': notice,
        'display_time': display,
        'retrieved_at': retrieved,
        'target_research_date': TARGET_DATE,
        'first_publication_timestamp': 'CANNOT_CONFIRM',
        'available_at_for_target_cutoff': 'CANNOT_CONFIRM',
        'novelty_vs_prior_disclosure': 'CANNOT_CONFIRM',
    }


def find_api_quote(src, quote):
    matches = []
    nq = norm(quote)
    for p in src.get('pages') or []:
        text = p.get('text') or ''
        if quote in text or (nq and nq in norm(text)):
            matches.append(p)
    if not matches:
        raise ValueError(f"short quote has no API page match: {src.get('art_code')} {quote!r}")
    p = matches[0]
    return {
        'exact_excerpt': quote,
        'source_layer': 'CONTENT_API_PAGE',
        'page_index': p.get('page_index'),
        'page_text_sha256': p.get('text_sha256') or hashlib.sha256((p.get('text') or '').encode()).hexdigest(),
        'source_ref': p.get('source_ref'),
        'excerpt_sha256': hashlib.sha256(quote.encode('utf-8')).hexdigest(),
        'literal_source_substring': quote in (p.get('text') or ''),
    }


def make_added_row(rec, src, mode, pdf_idx=None):
    out = dict(rec)
    out['record_origin'] = 'ADDED_SHORT_READ' if mode == 'short' else 'ADDED_LONG_PDF_READ'
    out['title'] = src.get('title')
    out['issuer_codes'] = src.get('matched_master_codes') or []
    out['target_research_date'] = TARGET_DATE
    out['source_status'] = src.get('body_status')
    out['source_body_sha256'] = src.get('body_text_sha256')
    out['source_body_retrieved_at'] = (src.get('pages') or [{}])[0].get('retrieved_at')
    out['date_semantics'] = date_fields(src)
    out['first_publication_and_cutoff_status'] = 'CANNOT_CONFIRM'
    out['novelty_vs_prior_status'] = 'CANNOT_CONFIRM'
    out['source_notice_date'] = out['date_semantics']['notice_date']
    out['source_display_time'] = out['date_semantics']['display_time']
    out['source_listing_evidence'] = src.get('listing_evidence')
    out['source_pdf_sha256'] = src.get('pdf_sha256')
    out['source_pdf_ref'] = src.get('pdf_ref')
    if mode == 'short':
        quote = rec['exact_quote']
        out['evidence'] = find_api_quote(src, quote)
        out['quote_location'] = {'layer': 'CONTENT_API_PAGE', 'page_index': out['evidence']['page_index']}
        out['pdf_derivative'] = None
        out['pdf_physical_pages_reviewed'] = []
    else:
        idx = pdf_idx.get(rec['art_code'])
        if not idx:
            raise ValueError(f"missing PDF derivative index row: {rec['art_code']}")
        deriv_path = Path(idx['derivative_path'])
        if not deriv_path.is_absolute():
            deriv_path = ROOT / deriv_path
        deriv = load_json(deriv_path)
        page_number = rec.get('quote_pdf_page')
        quote = rec['exact_quote']
        segs = [s for s in deriv.get('segments', []) if s.get('page_index') == page_number]
        if len(segs) != 1:
            raise ValueError(f"PDF quote page must map to one segment: {rec['art_code']} p{page_number}")
        seg = segs[0]
        if quote not in (seg.get('text') or ''):
            raise ValueError(f"long quote is not literal on cited PDF page: {rec['art_code']} p{page_number}")
        out['evidence'] = {
            'exact_excerpt': quote,
            'source_layer': 'PDF_PHYSICAL_PAGE',
            'page_index': page_number,
            'page_text_sha256': seg.get('text_sha256'),
            'excerpt_sha256': hashlib.sha256(quote.encode('utf-8')).hexdigest(),
            'literal_source_substring': True,
            'pdf_sha256': deriv.get('pdf_sha256'),
            'pdf_source_ref': deriv.get('pdf_source_ref'),
            'derivative_sha256': idx.get('derivative_sha256'),
            'derivative_path': str(deriv_path),
        }
        out['quote_location'] = {'layer': 'PDF_PHYSICAL_PAGE', 'page_index': page_number}
        out['pdf_derivative'] = {
            'path': str(deriv_path),
            'derivative_sha256': idx.get('derivative_sha256'),
            'full_text_sha256': deriv.get('full_text_sha256'),
            'pdf_sha256': deriv.get('pdf_sha256'),
            'pdf_page_count': deriv.get('pdf_page_count'),
            'derivative_status': idx.get('derivative_status'),
            'physical_pages_reviewed': rec.get('pdf_physical_pages_reviewed') or [],
        }
        out['source_api_page_refs'] = [{
            'page_index': p.get('page_index'),
            'page_text_sha256': p.get('text_sha256'),
            'retrieved_at': p.get('retrieved_at'),
            'source_ref': p.get('source_ref'),
        } for p in src.get('pages', [])]
    return out


def make_gap(code, src):
    pages = src.get('pages') or []
    return {
        'art_code': code,
        'record_origin': 'TEXT_INSUFFICIENT_CAPTURE_GAP',
        'title': src.get('title'),
        'issuer_codes': src.get('matched_master_codes') or [],
        'classification': 'UNASSESSED_MISSING_TEXT',
        'classification_as_authored': 'CANNOT_CONFIRM: 正文缺失，无法判断类别',
        'security_scope': 'CANNOT_CONFIRM: 正文缺失，无法确认涉及的证券类别',
        'factual_summary': 'CANNOT_CONFIRM：超出正文页数上限，完整附件PDF采集失败；仅保留一页API片段，不对公告内容作事实解读。',
        'why_useful': 'CANNOT_CONFIRM：现有文本不足以判断公告的研究价值。',
        'event_status_assessment': 'CANNOT_CONFIRM_TEXT_INSUFFICIENT',
        'research_priority': 'CANNOT_CONFIRM',
        'limitations': 'PDF_CAPTURE_FAILED；无有效PDF引用；只读取到不完整API页面，禁止据此推断未见内容。',
        'source_status': src.get('body_status'),
        'pdf_status': src.get('pdf_status'),
        'pdf_capture_status': src.get('pdf_capture_status') or 'CAPTURE_FAILED',
        'source_body_sha256': src.get('body_text_sha256'),
        'source_body_characters': src.get('body_text_characters'),
        'content_page_count': src.get('content_page_count'),
        'source_pdf_sha256': None,
        'source_pdf_ref': None,
        'evidence': {
            'source_layer': 'PARTIAL_CONTENT_API_PAGE_ONLY',
            'exact_excerpt': None,
            'literal_source_substring': None,
            'pages': [{
                'page_index': p.get('page_index'),
                'page_text_sha256': p.get('text_sha256'),
                'body_sha256': (p.get('source_ref') or {}).get('body_sha256'),
                'blob_sha256': (p.get('source_ref') or {}).get('blob_sha256'),
                'source_ref': p.get('source_ref'),
                'text_characters': len(p.get('text') or ''),
                'retrieved_at': p.get('retrieved_at'),
            } for p in pages],
        },
        'date_semantics': date_fields(src),
        'first_publication_and_cutoff_status': 'CANNOT_CONFIRM',
        'novelty_vs_prior_status': 'CANNOT_CONFIRM',
        'source_listing_evidence': src.get('listing_evidence'),
    }


def compact(v):
    if v is None: return ''
    if isinstance(v, (dict, list)): return json.dumps(v, ensure_ascii=False, separators=(',', ':'))
    return str(v)


def csv_row(r):
    ev = r.get('evidence') or {}
    dates = r.get('date_semantics') or {}
    return {
        'art_code': r.get('art_code'), 'title': r.get('title'),
        'issuer_codes': compact(r.get('issuer_codes')),
        'record_origin': r.get('record_origin') or 'FROZEN_V1_BASELINE',
        'classification': r.get('classification'), 'security_scope': r.get('security_scope'),
        'factual_summary': r.get('factual_summary'), 'why_useful': r.get('why_useful'),
        'event_status_assessment': r.get('event_status_assessment'),
        'research_priority': r.get('research_priority'),
        'exact_excerpt': ev.get('exact_excerpt'), 'source_layer': ev.get('source_layer'),
        'quote_page_index': ev.get('page_index'), 'page_text_sha256': ev.get('page_text_sha256'),
        'excerpt_sha256': ev.get('excerpt_sha256'), 'source_body_sha256': r.get('source_body_sha256'),
        'source_pdf_sha256': r.get('source_pdf_sha256') or ev.get('pdf_sha256'),
        'pdf_derivative_sha256': (r.get('pdf_derivative') or {}).get('derivative_sha256') or ev.get('derivative_sha256'),
        'notice_date': dates.get('notice_date'), 'display_time': dates.get('display_time'),
        'retrieved_at': dates.get('retrieved_at'),
        'first_publication_timestamp': dates.get('first_publication_timestamp'),
        'available_at_for_target_cutoff': dates.get('available_at_for_target_cutoff'),
        'novelty_vs_prior_disclosure': dates.get('novelty_vs_prior_disclosure'),
        'limitations': r.get('limitations'),
    }


def md_escape(s):
    return compact(s).replace('|', '\\|').replace('\n', ' ').replace('\r', ' ')


def main():
    v1 = load_json(V1)
    short = load_json(SHORT)['records']
    long = load_json(LONG)['records']
    corpus_obj = load_json(CORPUS)
    corpus = {r['art_code']: r for r in corpus_obj['rows']}
    idx = {r['art_code']: r for r in load_json(PDF_INDEX)['rows']}
    base = v1['records']
    all_codes = [r['art_code'] for r in base]
    if len(all_codes) != len(set(all_codes)):
        raise ValueError('v1 contains duplicate article codes')
    additions = []
    for rec in short:
        additions.append(make_added_row(rec, corpus[rec['art_code']], 'short'))
    for rec in long:
        additions.append(make_added_row(rec, corpus[rec['art_code']], 'long', idx))
    for code in GAP_CODES:
        additions.append(make_gap(code, corpus[code]))
    # One-pass independent cross-review corrections. These apply only to the
    # new 67 rows; the frozen v1 records remain byte-semantically unchanged.
    patches = {
        'AN202609291829998019': {
            'factual_summary': '剂泰科技2026H1收入人民币1.543亿元（上年同期0.011亿元），其中合作协议收入1.536亿元；归母亏损1.532亿元，非IFRS经调整亏损0.511亿元。公司称已与Boulevard签署MTS-128全球独家授权并已收到USD20m首付款；另有最高USD1.6bn开发、注册及商业化里程碑付款，以及分级销售提成；公司称潜在总交易价值超过USD1.6bn。',
            'limitations': '经营现金流净流出1.622亿元，现金增量主要来自上市融资；经调整亏损属非IFRS口径。协议签署日、首付款与报告期的准确关系CANNOT_CONFIRM。',
        },
        'AN202609291829995974': {
            'factual_summary': '中国信达2026H1持续经营收入人民币226.27亿元、同比-28.0%；归母净利7.844亿元、同比-65.6%。信达证券因拟议换股吸收合并被列为持有待售并作为终止经营，比较期损益已重列；该合并于6月8日获相关股东会批准，但报告未证明交易完成。H1不良债权公允价值变动收益人民币4,201.3m；其中收购的FVTPL不良债权子项人民币4,144.4m，含已实现2,167.7m及未实现1,976.7m。',
            'why_useful': '应区分总不良债权公允价值变动与收购FVTPL子项；利润受估值及资产盘活影响，不能只读headline净利。',
        },
        'AN202609291829996484': {
            'factual_summary': '安徽皖通高速2026H1未经审计；按中国会计准则（PRC GAAP）收入人民币32.2658亿元（-13.75%）、归母净利10.074066亿元（+4.89%）；同报告HKFRS归母净利为10.08182亿元，口径分列。收费公路收入25.033亿元（+0.99%）、通行费24.736亿元（+0.92%）；建造服务收入6.898亿元（-43.59%）。公司称整体收入下滑主要由建造服务减少；部分路段车流/通行费受新路分流、改扩建和汛期影响。董事会未提中期派息预案。',
            'limitations': '报告未经审计；需区分PRC GAAP与HKFRS净利口径。通行费/车流解释取自MD&A选读页，不代表全路段日频统计。首次公开、目标日可得性及新颖性CANNOT_CONFIRM。',
        },
        'AN202609291830004799': {
            'factual_summary': '濱化股份擬聘畢馬威華振為2026年度財報與內控審計機構，費用RMB2m（財報1.55m、內控0.45m，不含稅），待股東會批准；另披露約RMB4.6m債券訴訟賠償及監管警示，屬擬聘審計機構畢馬威華振及相關人員的過往執業事項，不是濱化股份自身責任。',
            'why_useful': '審計聘任及擬聘機構既往執業紀錄屬治理/審計風險資料；所述賠償及警示不應歸為濱化股份自身責任。',
        },
    }
    by_code = {r['art_code']: r for r in additions}
    for code, fields in patches.items():
        if code not in by_code:
            raise ValueError(f'cross-review patch must target a new row, not frozen v1: {code}')
        by_code[code].update(fields)
    add_codes = [r['art_code'] for r in additions]
    if len(add_codes) != len(set(add_codes)):
        raise ValueError('new additions contain duplicate article codes')
    overlap = set(all_codes) & set(add_codes)
    if overlap:
        raise ValueError(f'new additions overlap frozen v1: {sorted(overlap)}')
    records = base + additions
    codes = [r['art_code'] for r in records]
    if len(records) != 234 or len(set(codes)) != 234:
        raise ValueError(f'expected 234 unique articles, got rows={len(records)}, unique={len(set(codes))}')
    quote_rows = [r for r in additions if r.get('evidence', {}).get('exact_excerpt')]
    if any(len(r['evidence']['exact_excerpt']) > 60 for r in quote_rows):
        raise ValueError('short excerpt exceeds 60 characters')
    if any(not r['evidence'].get('literal_source_substring') for r in quote_rows):
        raise ValueError('a new quote is not a literal page substring')
    counts = Counter(r.get('classification', 'UNKNOWN') for r in records)
    origin_counts = Counter(r.get('record_origin', 'FROZEN_V1_BASELINE') for r in records)
    out = {
        'schema': 'v4.announcement-semantic-catalog.v2',
        'status': 'PASS_234_UNIQUE_ANNOUNCEMENTS_WITH_SOURCE_BOUND_READS_AND_EXPLICIT_GAPS',
        'row_count': len(records),
        'announcement_count_not_independent_event_count': True,
        'target_notice_date': '2026-09-29',
        'target_research_date': TARGET_DATE,
        'first_publication_and_cutoff_status': 'CANNOT_CONFIRM',
        'novelty_vs_prior_status': 'CANNOT_CONFIRM',
        'interpretation_boundary': '事后公告阅读目录。报道事实、拟议事项、未来目标与缺失文本分开；不得视作目标日可得信息、历史PIT资格、交易信号或BUY输入。',
        'frozen_v1': {'path': str(V1), 'sha256': sha_file(V1), 'row_count': len(base)},
        'inputs': {
            'short_additions': {'path': str(SHORT), 'sha256': sha_file(SHORT), 'row_count': len(short)},
            'long_additions': {'path': str(LONG), 'sha256': sha_file(LONG), 'row_count': len(long)},
            'body_corpus': {'path': str(CORPUS), 'sha256': sha_file(CORPUS), 'row_count': len(corpus_obj['rows'])},
            'pdf_derivative_index': {'path': str(PDF_INDEX), 'sha256': sha_file(PDF_INDEX), 'row_count': len(idx)},
        },
        'coverage': {
            'frozen_semantic_v1': len(base), 'added_short_reads': len(short),
            'added_long_pdf_reads': len(long), 'text_insufficient_gaps': len(GAP_CODES),
            'api_body_complete': corpus_obj.get('body_status_counts', {}).get('COMPLETE_CONTENT_API_BODY'),
            'api_body_over_limit': corpus_obj.get('body_status_counts', {}).get('OVER_CONTENT_PAGE_LIMIT'),
            'valid_pdfs_in_source_corpus': corpus_obj.get('pdf_status_counts', {}).get('VALID_PDF_BYTES'),
            'failed_pdf_captures_in_source_corpus': corpus_obj.get('pdf_status_counts', {}).get('CAPTURE_FAILED'),
            'missing_pdf_refs_in_source_corpus': corpus_obj.get('pdf_status_counts', {}).get('PDF_REF_MISSING'),
        },
        'classification_counts': dict(sorted(counts.items())),
        'origin_counts': dict(sorted(origin_counts.items())),
        'records': records,
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    cols = ['art_code','title','issuer_codes','record_origin','classification','security_scope','factual_summary','why_useful','event_status_assessment','research_priority','exact_excerpt','source_layer','quote_page_index','page_text_sha256','excerpt_sha256','source_body_sha256','source_pdf_sha256','pdf_derivative_sha256','notice_date','display_time','retrieved_at','first_publication_timestamp','available_at_for_target_cutoff','novelty_vs_prior_disclosure','limitations']
    with OUT_CSV.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction='ignore')
        w.writeheader()
        w.writerows(csv_row(r) for r in records)
    lines = [
        '# 2026-09-29 公告事后解读目录（v2，234篇）', '',
        '本版逐篇保留234条公告记录：冻结v1 167篇、新增短公告解读40篇、长PDF解读22篇、正文不足缺口5篇。234是公告篇数，不是234个独立事件；同一事项的多篇披露仍逐行保留。', '',
        '## 阅读边界', '',
        '- 目标研究日为2026-09-30。公告列示/页面展示日、附件落款/会议日、事后采集时间和原始首次公开时间是不同字段；首次公开时点、目标日cutoff可得性、相对既有披露的新颖性均为 `CANNOT_CONFIRM`。',
        '- 已报告事实与拟议交易、待审批事项、未来派息/经营目标/里程碑分开；未来值不回填为历史事实。该目录是事后研究阅读，不是历史PIT资格、投资建议、选股结果或BUY输入。',
        '- 正文来源共207篇完整、27篇超正文页数限制；22篇有效长PDF已逐页提取并按读者实际阅读页码引用。全语料有226份有效PDF、5份采集失败、3份引用缺失。另有5篇在本文中列为文本不足，因完整PDF采集失败，不作语义推断。',
        '- 可将广汽/一汽丰田重组、埃斯顿激励、比亚迪交流、旭阳框架协议视作待研究的事项簇；目录保留各自公告编号和来源，不把它们计成多个独立事件，也不因同簇而合并证据。', '',
        f"类别计数：{'；'.join(f'{k} {v}' for k,v in sorted(counts.items()))}。", '',
        '| 公告编号 | 标题 | 证券范围/类别 | 状态 | 事实摘要 | 关注理由 | 短原文证据/物理页 | PIT/首发/增量 |',
        '|---|---|---|---|---|---|---|---|',
    ]
    for r in records:
        ev = r.get('evidence') or {}
        q = ev.get('exact_excerpt')
        layer = ev.get('source_layer')
        page = ev.get('page_index')
        page_sha = ev.get('page_text_sha256')
        cite = 'CANNOT_CONFIRM：无完整正文/PDF' if not q else f"{layer} p.{page} / {page_sha} — {q}"
        dates = r.get('date_semantics') or {}
        date_state = '/'.join([dates.get('first_publication_timestamp','CANNOT_CONFIRM'), dates.get('available_at_for_target_cutoff','CANNOT_CONFIRM'), dates.get('novelty_vs_prior_disclosure','CANNOT_CONFIRM')])
        lines.append('| ' + ' | '.join(md_escape(v) for v in [
            r.get('art_code'), r.get('title'), r.get('security_scope') or compact(r.get('issuer_codes')),
            r.get('event_status_assessment') or r.get('classification'), r.get('factual_summary'),
            r.get('why_useful'), cite, date_state,
        ]) + ' |')
    OUT_MD.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps({
        'status': out['status'], 'row_count': len(records), 'unique_art_codes': len(set(codes)),
        'base_rows_preserved': len(base), 'new_rows': len(additions), 'new_quote_rows': len(quote_rows),
        'classifications': dict(counts), 'origins': dict(origin_counts),
        'quote_failures': sum(not r['evidence'].get('literal_source_substring') for r in quote_rows),
        'sha256': {str(p): sha_file(p) for p in [OUT_JSON, OUT_CSV, OUT_MD]},
    }, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
