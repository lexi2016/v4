#!/usr/bin/env python3
"""Build a frozen 167-row retrospective announcement reading catalog.

Inputs are the prior source-review shards and the verified v3 body corpus.
This script joins exact article/page provenance and never infers PIT or novelty.
"""
from __future__ import annotations
import csv, difflib, hashlib, json, re, unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORPUS = ROOT / 'body_corpus_20260929_v3.json'
SIX = ROOT / 'six_interpretations_20260929.json'
INPUT = ROOT / 'semantic_161_input.tsv'
OUT_JSON = ROOT / 'semantic_catalog_20260929_v1.json'
OUT_CSV = ROOT / 'semantic_catalog_20260929_v1.csv'
OUT_MD = ROOT / 'semantic_catalog_20260929_v1.md'
TARGET_DATE = '2026-09-30'
NOTICE_DATE = '2026-09-29'
MAX_QUOTE = 60


def normalize_with_spans(s: str):
    chars, spans = [], []
    for i, ch in enumerate(s):
        v = unicodedata.normalize('NFKC', ch)
        for c in v:
            if c.isspace():
                c = ' '
                if chars and chars[-1] == ' ':
                    spans[-1] = (spans[-1][0], i + 1)
                    continue
            chars.append(c)
            spans.append((i, i + 1))
    # Remove only spaces that split adjacent Han characters.
    out, outspans = [], []
    for i, c in enumerate(chars):
        if c == ' ' and i > 0 and i + 1 < len(chars) and is_han(chars[i-1]) and is_han(chars[i+1]):
            continue
        out.append(c); outspans.append(spans[i])
    left = 0
    right = len(out)
    while left < right and out[left] == ' ':
        left += 1
    while right > left and out[right - 1] == ' ':
        right -= 1
    return ''.join(out[left:right]), outspans[left:right]


def is_han(c):
    return bool(c) and ('\u3400' <= c <= '\u9fff' or '\uf900' <= c <= '\ufaff')


def normalize(s):
    return normalize_with_spans(s)[0]


def direct_excerpt(pages, desired, context=''):
    """Return source substring <=60 chars and its exact page/ref, with match type."""
    desired = desired or ''
    wanted, _ = normalize_with_spans(desired)
    if len(wanted) > MAX_QUOTE:
        # Preserve the most useful tail if it contains figures, otherwise first 60.
        nums = list(re.finditer(r'(?:RMB|HKD|USD|GBP|人民币|港元|美元)?[0-9][0-9,\.\-–%]*', wanted, re.I))
        if nums:
            m = nums[0]
            left = max(0, min(m.start(), len(wanted) - MAX_QUOTE))
            wanted = wanted[left:left + MAX_QUOTE]
        else:
            wanted = wanted[:MAX_QUOTE]
    best = None
    for page in pages:
        text = page.get('text') or ''
        norm_text, spans = normalize_with_spans(text)
        if wanted and wanted in norm_text:
            pos = norm_text.index(wanted)
            start = spans[pos][0]
            end = spans[pos + len(wanted) - 1][1]
            q = text[start:end]
            # Source text may contain expanded whitespace. Keep exact raw text concise.
            if len(q) > MAX_QUOTE:
                q = q[:MAX_QUOTE]
            return q, page, 'LITERAL' if desired in text else 'NFKC_WHITESPACE'
        if wanted:
            match = difflib.SequenceMatcher(None, wanted, norm_text, autojunk=False)
            block = max(match.get_matching_blocks(), key=lambda b: b.size, default=None)
            if block and block.size >= 5 and (best is None or block.size > best[0]):
                best = (block.size, page, text, spans, block)
    if best and best[0] >= 8:
        size, page, text, spans, block = best
        a = spans[block.b][0]
        b = spans[block.b + block.size - 1][1]
        # A direct source window around the best overlap, never synthesized text.
        start = max(0, min(a - 20, max(0, len(text) - MAX_QUOTE)))
        end = min(len(text), start + MAX_QUOTE)
        return text[start:end], page, f'OVERLAP_{size}'
    # Prefer an exact numeric fact over a weak lexical overlap.
    search_texts = []
    for token in re.findall(r'(?<!\d)\d[\d,]*(?:\.\d+)?%?', context):
        if token not in search_texts:
            search_texts.append(token)
    search_texts.sort(key=len, reverse=True)
    for token in search_texts:
        for page in pages:
            text = page.get('text') or ''
            norm_text, spans = normalize_with_spans(text)
            norm_token, _ = normalize_with_spans(token)
            pos = norm_text.find(norm_token)
            if pos >= 0:
                a = spans[pos][0]
                b = spans[pos + len(norm_token) - 1][1]
                start = max(0, min(a - 24, max(0, len(text) - MAX_QUOTE)))
                return text[start:min(len(text), start + MAX_QUOTE)], page, 'EXACT_NUMERIC_CONTEXT'
    if best:
        size, page, text, spans, block = best
        a = spans[block.b][0]
        start = max(0, min(a - 20, max(0, len(text) - MAX_QUOTE)))
        return text[start:min(len(text), start + MAX_QUOTE)], page, f'OVERLAP_{size}'
    # Search the article title inside a source page before using a page prefix.
    title = normalize(context.split('\u241e', 1)[-1])
    if title:
        for page in pages:
            text = page.get('text') or ''
            norm_text, spans = normalize_with_spans(text)
            ntitle, _ = normalize_with_spans(title)
            pos = norm_text.find(ntitle)
            if pos >= 0:
                a = spans[pos][0]
                return text[a:min(len(text), a + MAX_QUOTE)], page, 'TITLE_MATCH'
    # For notice-only records, choose a meaningful direct line rather than a legal header.
    for page in pages:
        text = page.get('text') or ''
        if 'interim report' in text.lower() or '中期报告' in text or '中期報告' in text:
            candidates = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]
            for line in candidates:
                low = line.lower()
                if (('interim report' in low or '中期报告' in line or '中期報告' in line) and
                    ('publication' in low or 'available' in low or '刊發' in line or '發布' in line or '发布' in line)):
                    return line[:MAX_QUOTE], page, 'CONTENT_LINE_FALLBACK'
    # Otherwise take a content line after the standard exchange disclaimer, not the header.
    for page in pages:
        text = page.get('text') or ''
        candidates = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip()]
        for line in candidates:
            low = line.lower()
            if any(x in low for x in ('hkex', 'joint stock company', 'company limited', 'limited company', '股份有限公司', '股份代號', '股份编号', '概不負責', '不負責')):
                continue
            if len(line) >= 10:
                return line[:MAX_QUOTE], page, 'CONTENT_LINE_FALLBACK'
    # Last fallback: use a literal short title/body prefix, labeled as a weak locator.
    for page in pages:
        text = page.get('text') or ''
        clean = re.sub(r'\s+', ' ', text).strip()
        if clean:
            return clean[:MAX_QUOTE], page, 'TITLE_OR_PAGE_PREFIX_FALLBACK'
    return '', None, 'NO_TEXT_CANNOT_CONFIRM'


def event_status(category, facts):
    s = facts
    conditional = any(x in s for x in ('拟', '建議', '建议', '提议', '仍待', '尚待', '待股东', '待批准', '尚未', '预期', '預期', '预计', '目標', '目标', '上限', '条件', '若全额', '不确定'))
    realized = any(x in s for x in ('已回购', '回购', '已增持', '增持', '已发行', '发行完成', '完成', '获批', '获委任', '任命', '辞任', '签署', '已签', '通过', '收入', '净利', '亏损', '披露', '报告'))
    if category == 'FINANCIAL_REPORT': return 'REPORTED_FINANCIAL_RESULTS'
    if category == 'ROUTINE': return 'NOTICE_OR_GOVERNANCE; see factual_summary for effective dates'
    if conditional and realized: return 'REPORTED_FACTS_WITH_CONDITIONAL_OR_FUTURE_COMPONENTS'
    if conditional: return 'CONDITIONAL_OR_FUTURE'
    if realized: return 'REPORTED_OR_COMPLETED; see factual_summary for exact status'
    return 'STATUS_NOT_INDEPENDENTLY_CLASSIFIED'


def rows_from_tsv(path):
    records = []
    with path.open(encoding='utf-8') as f:
        header = f.readline().rstrip('\n').split('\\t')
        if header != ['art_code','category','security_scope','facts','why_useful','evidence_excerpt']:
            raise ValueError(f'unexpected TSV header: {header}')
        for line_no, line in enumerate(f, 2):
            cells = line.rstrip('\n').split('\\t')
            if len(cells) != 6:
                raise ValueError(f'bad input line {line_no}: {len(cells)} columns')
            records.append(dict(zip(header, cells)))
    return records


def make_new_record(x, source):
    context = x['facts'] + '\u241e' + (source.get('title') or '')
    quote, page, quote_method = direct_excerpt(source.get('pages', []), x['evidence_excerpt'], context)
    evidence = None
    if page:
        evidence = {
            'exact_excerpt': quote,
            'match_method': quote_method,
            'page_index': page.get('page_index'),
            'page_text_sha256': hashlib.sha256((page.get('text') or '').encode('utf-8')).hexdigest(),
            'source_ref': page.get('source_ref'),
        }
    source_retrieved = [p.get('retrieved_at') for p in source.get('pages', []) if p.get('retrieved_at')]
    return {
        'art_code': x['art_code'],
        'issuer_codes': source.get('matched_master_codes', []),
        'title': source.get('title'),
        'classification': x['category'],
        'security_scope': x['security_scope'],
        'factual_summary': x['facts'],
        'why_useful': re.sub(r'^YES：|^NO：', '', x['why_useful']),
        'research_priority': 'YES' if x['why_useful'].startswith('YES') else 'NO',
        'event_status_assessment': event_status(x['category'], x['facts']),
        'evidence': evidence,
        'body_source': {
            'body_status': source.get('body_status'),
            'body_text_sha256': source.get('body_text_sha256'),
            'body_text_characters': source.get('body_text_characters'),
            'content_page_count': source.get('content_page_count'),
            'api_page_count_read': len(source.get('pages', [])),
            'page_source_refs': [p.get('source_ref') for p in source.get('pages', [])],
        },
        'date_semantics': {
            'notice_date': source.get('content_notice_date') or NOTICE_DATE,
            'display_time': source.get('content_display_time'),
            'retrieved_at': min(source_retrieved) if source_retrieved else None,
            'target_research_date': TARGET_DATE,
            'first_publication_timestamp': 'CANNOT_CONFIRM',
            'available_at_for_target_cutoff': 'CANNOT_CONFIRM',
            'novelty_vs_prior_disclosure': 'CANNOT_CONFIRM',
        },
        'cutoff_boundary': 'RETROSPECTIVE_RESEARCH_ONLY; original target-date availability not established',
    }


def normalize_legacy_category(s):
    if '风险' in s: return 'RISK'
    if '混合' in s: return 'MIXED'
    if '资本' in s: return 'CAPITAL_ACTION'
    if '财务' in s or '业绩' in s: return 'FINANCIAL_REPORT'
    if '经营' in s: return 'BUSINESS_EVENT'
    return 'ROUTINE'


def make_legacy_record(x, source):
    statements = [f.get('statement','') for f in x.get('facts', [])]
    return {
        'art_code': x['art_code'],
        'issuer_codes': [x.get('hk_issuer', {})] if x.get('hk_issuer') else [],
        'title': x.get('title'),
        'classification': normalize_legacy_category(x.get('category','')),
        'classification_as_authored': x.get('category'),
        'security_scope': x.get('security_class_distinction'),
        'factual_summary': '；'.join(statements),
        'why_useful': x.get('impact_state'),
        'research_priority': 'REVIEWED_LEGACY',
        'event_status_assessment': x.get('impact_state'),
        'evidence': {
            'exact_excerpt': 'CANNOT_CONFIRM_EXACT_SHORT_QUOTE; retain source-linked facts and physical PDF pages below',
            'api_page_refs': x.get('body_evidence', {}).get('api_pages', []),
            'pdf_physical_pages': [p for f in x.get('facts', []) for p in f.get('pdf_pages', [])],
            'pdf_sha256': x.get('pdf_evidence', {}).get('sha256'),
            'pdf_source_ref': x.get('pdf_evidence', {}).get('source_ref'),
        },
        'body_source': {
            'body_status': source.get('body_status') if source else x.get('body_evidence', {}).get('status'),
            'body_text_sha256': source.get('body_text_sha256') if source else None,
            'body_page_source_refs': [p.get('source_ref') for p in (source or {}).get('pages', [])],
        },
        'date_semantics': {
            'notice_date': (source or {}).get('content_notice_date') or NOTICE_DATE,
            'display_time': (source or {}).get('content_display_time') or x.get('listing', {}).get('display_time'),
            'retrieved_at': min([p.get('retrieved_at') for p in (source or {}).get('pages', []) if p.get('retrieved_at')], default=None),
            'target_research_date': TARGET_DATE,
            'first_publication_timestamp': x.get('first_hkex_publication_time', 'CANNOT_CONFIRM'),
            'available_at_for_target_cutoff': x.get('original_pit_available_at', 'CANNOT_CONFIRM'),
            'novelty_vs_prior_disclosure': x.get('incremental_novelty_vs_prior_disclosure', 'CANNOT_CONFIRM'),
        },
        'cutoff_boundary': 'RETROSPECTIVE_RESEARCH_ONLY; original target-date availability not established',
        'legacy_source_record': x,
    }


def write_csv(path, records):
    fields = ['art_code','title','classification','security_scope','research_priority','event_status_assessment','factual_summary','why_useful','evidence_excerpt','evidence_page_index','evidence_page_text_sha256','body_text_sha256','notice_date','display_time','retrieved_at','target_research_date','first_publication_timestamp','available_at_for_target_cutoff','novelty_vs_prior_disclosure','cutoff_boundary']
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in records:
            ev = r.get('evidence') or {}
            dt = r.get('date_semantics') or {}
            bs = r.get('body_source') or {}
            w.writerow({
                'art_code':r.get('art_code'),'title':r.get('title'),'classification':r.get('classification'),
                'security_scope':r.get('security_scope'),'research_priority':r.get('research_priority'),
                'event_status_assessment':r.get('event_status_assessment'),'factual_summary':r.get('factual_summary'),
                'why_useful':r.get('why_useful'),'evidence_excerpt':ev.get('exact_excerpt'),
                'evidence_page_index':ev.get('page_index'),'evidence_page_text_sha256':ev.get('page_text_sha256'),
                'body_text_sha256':bs.get('body_text_sha256'),'notice_date':dt.get('notice_date'),
                'display_time':dt.get('display_time'),'retrieved_at':dt.get('retrieved_at'),
                'target_research_date':dt.get('target_research_date'),'first_publication_timestamp':dt.get('first_publication_timestamp'),
                'available_at_for_target_cutoff':dt.get('available_at_for_target_cutoff'),'novelty_vs_prior_disclosure':dt.get('novelty_vs_prior_disclosure'),
                'cutoff_boundary':r.get('cutoff_boundary')})


def main():
    corpus = json.loads(CORPUS.read_text(encoding='utf-8'))
    sources = {r['art_code']:r for r in corpus['rows']}
    inputs = rows_from_tsv(INPUT)
    if len(inputs) != 161 or len({r['art_code'] for r in inputs}) != 161:
        raise SystemExit(f'expected 161 unique manual rows, got {len(inputs)}')
    docs = {x['art_code']:x for x in json.loads(SIX.read_text(encoding='utf-8'))['documents']}
    ids = set()
    records = []
    quote_warnings = []
    for x in inputs:
        code = x['art_code']
        if code in ids: raise SystemExit(f'duplicate code {code}')
        ids.add(code)
        src = sources.get(code)
        if not src: raise SystemExit(f'corpus row missing: {code}')
        if src.get('body_status') != 'COMPLETE_CONTENT_API_BODY': raise SystemExit(f'body not complete for {code}: {src.get("body_status")}')
        if not src.get('body_text_sha256'): raise SystemExit(f'body SHA missing: {code}')
        rec = make_new_record(x, src)
        if not rec['evidence'] or not rec['evidence']['exact_excerpt']:
            quote_warnings.append((code, 'NO_QUOTE'))
        elif rec['evidence']['match_method'].startswith('OVERLAP_') or rec['evidence']['match_method'].endswith('FALLBACK'):
            quote_warnings.append((code, rec['evidence']['match_method']))
        records.append(rec)
    for code, legacy in docs.items():
        if code in ids: raise SystemExit(f'duplicate legacy code {code}')
        ids.add(code)
        records.append(make_legacy_record(legacy, sources.get(code)))
    records.sort(key=lambda r:r['art_code'])
    if len(records) != 167 or len(ids) != 167: raise SystemExit(f'expected 167 unique rows, got {len(records)}')
    counts = Counter(r['classification'] for r in records)
    payload = {
        'schema':'announcement_semantic_catalog_v1',
        'status':'AUTHOR_FROZEN_PENDING_INDEPENDENT_REVIEW',
        'corpus_path':str(CORPUS),
        'corpus_sha256':hashlib.sha256(CORPUS.read_bytes()).hexdigest(),
        'source_input_path':str(INPUT),
        'source_input_row_count':len(inputs),
        'legacy_prior_row_count':len(docs),
        'row_count':len(records),
        'target_notice_date':NOTICE_DATE,
        'target_research_date':TARGET_DATE,
        'interpretation_boundary':'Retrospective body/PDF research. Do not infer target-date availability, first publication time, or novelty from notice/display date or post-event retrieval.',
        'first_publication_and_cutoff_status':'CANNOT_CONFIRM',
        'novelty_vs_prior_status':'CANNOT_CONFIRM',
        'classification_counts':dict(sorted(counts.items())),
        'quote_match_warning_count':len(quote_warnings),
        'quote_match_warnings':[{'art_code':c,'method':m} for c,m in quote_warnings],
        'records':records,
    }
    OUT_JSON.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    write_csv(OUT_CSV,records)
    with OUT_MD.open('w',encoding='utf-8') as f:
        f.write('# 2026-09-29 公告事后研究语义目录（冻结初稿）\n\n')
        f.write(f'共{len(records)}篇：原有结构化解读6篇，按来源索引逐条整合161篇。目标研究日为2026-09-30。首发时点、目标cutoff可得性及相对旧公告增量均为 `CANNOT_CONFIRM`；页面展示日和事后抓取时间不能证明当时可得。该目录是公告事实与研究价值的事后归纳，不代表选股/交易结论。\n\n')
        f.write('| 公告编号 | 证券/类别 | 状态 | 事实摘要 | 关注理由 | 短原文证据/来源 | PIT/首发/增量 |\n|---|---|---|---|---|---|---|\n')
        for r in records:
            ev=r.get('evidence') or {}; dt=r.get('date_semantics') or {}; bs=r.get('body_source') or {}
            if ev.get('source_ref'):
                src=f"p.{ev.get('page_index')} / {ev.get('source_ref',{}).get('body_sha256','')}"
            else:
                src='PDF/API source refs in JSON'
            excerpt=ev.get('exact_excerpt','')
            for a,b in [('|','／'),('\n',' '),('\r',' ')]:
                excerpt=excerpt.replace(a,b)
            fact=r.get('factual_summary','').replace('|','／').replace('\n',' ')
            why=str(r.get('why_useful','')).replace('|','／').replace('\n',' ')
            scope=str(r.get('security_scope','')).replace('|','／')
            f.write(f"| {r['art_code']} | {scope} / {r.get('classification','')} | {r.get('event_status_assessment','')} | {fact} | {why} | {excerpt} ({src}) | CANNOT_CONFIRM |\n")
    print(json.dumps({'status':'PASS_SEMANTIC_CATALOG_V1_BUILT','rows':len(records),'source_rows':len(inputs),'legacy_rows':len(docs),'classification_counts':dict(counts),'quote_warnings':quote_warnings,'json_path':str(OUT_JSON),'csv_path':str(OUT_CSV),'md_path':str(OUT_MD),'json_sha256':hashlib.sha256(OUT_JSON.read_bytes()).hexdigest(),'csv_sha256':hashlib.sha256(OUT_CSV.read_bytes()).hexdigest(),'md_sha256':hashlib.sha256(OUT_MD.read_bytes()).hexdigest()},ensure_ascii=False,indent=2))

if __name__ == '__main__': main()
