"""Same verified report retrieval service for HTTP, MCP and Stage sidecars."""
from __future__ import annotations
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from infrastructure.report_evidence_index import ReportIndex, SAFETY, digest, timestamp
from domains.report_subjects import canonical_title_code

class ReportEvidenceService:
    def __init__(self, index: ReportIndex, native=None, *, document_allowlist=None):
        self.index, self.native = index, native
        self.document_allowlist = None if document_allowlist is None else frozenset(document_allowlist)

    def eligible(self, db, *, security='', market='', source='', date_from='', date_to='', mode='current_research', as_of=None):
        if mode not in {'current_research', 'historical_evidence'}:
            raise ValueError('INVALID_MODE')
        cutoff = timestamp(as_of)
        if mode == 'historical_evidence' and cutoff is None:
            raise ValueError('HISTORICAL_AS_OF_REQUIRED_WITH_TIMEZONE')
        if as_of is not None and cutoff is None:
            raise ValueError('INVALID_AS_OF')
        if market and market not in {'A', 'HK'}:
            raise ValueError('INVALID_MARKET')
        code = canonical_title_code(security) if security else None
        if security and not code:
            raise ValueError('EXPLICIT_SECURITY_CODE_REQUIRED')
        for day in (date_from, date_to):
            if day:
                datetime.strptime(day, '%Y%m%d')
        if date_from and date_to and date_from > date_to:
            raise ValueError('INVALID_DATE_INTERVAL')
        docs = {}
        self._eligibility_gaps = set()
        for row in db.execute('SELECT id,metadata FROM documents WHERE active=1').fetchall():
            if self.document_allowlist is not None and row['id'] not in self.document_allowlist:
                continue
            m = json.loads(row['metadata'])
            if m.get('retracted'):
                continue
            if (code or market) and not any((not code or s['code']==code) and (not market or s['market']==market) for s in m['subjects']):
                continue
            if source and source not in {m.get('source'), m.get('publisher')}:
                continue
            if date_from and m['research_date'] < date_from or date_to and m['research_date'] > date_to:
                continue
            available = timestamp(m.get('available_at'))
            if cutoff and (available is None or available > cutoff):
                continue
            published = timestamp(m.get('published_at'))
            if cutoff and published and published > cutoff:
                continue
            # Both branches consume only currently authorized owner records.
            try:
                if hasattr(self.index.owner,'authorized'):
                    if not self.index.owner.authorized(m):
                        self._eligibility_gaps.add('SOURCE_PAGE_RECEIPT_OR_PERMISSION_CHANGED')
                        continue
                else:
                    detail=self.index.owner.verified(m['document_id'],m['research_date'])
                    if detail['receipt']['verified_pdf_sha256']!=m['pdf_sha'] or detail['receipt']['sha256']!=m['receipt_sha']:
                        self._eligibility_gaps.add('SOURCE_PAGE_RECEIPT_OR_PERMISSION_CHANGED')
                        continue
            except Exception:
                self._eligibility_gaps.add('SOURCE_PAGE_RECEIPT_OR_PERMISSION_CHANGED')
                continue
            docs[row['id']] = m
        return docs

    def verify(self, m, row, cache):
        key = m['document_id']
        if key not in cache:
            try:
                detail = self.index.owner.verified(key, m['research_date'])
                receipt = detail['receipt']
                if receipt['verified_pdf_sha256'] != m['pdf_sha'] or receipt['sha256'] != m['receipt_sha']:
                    raise ValueError('SOURCE_SHA_DRIFT')
                cache[key] = detail
            except Exception:
                cache[key] = None
        detail = cache[key]
        if detail is None:
            return False
        page = next((p for p in detail['pages'] if p['page_number'] == row['page']), None)
        return page is not None and page['text_sha256'] == row['page_sha']

    async def search(self, text, *, security='', market='', source='', date_from='', date_to='',
                     mode='current_research', as_of=None, limit=10, strategy='hybrid'):
        if not isinstance(text, str) or not text.strip() or len(text) > 2000 or not 1 <= limit <= 20:
            raise ValueError('INVALID_QUERY_OR_LIMIT')
        try: text.encode('utf-8')
        except UnicodeEncodeError: raise ValueError('QUERY_INVALID_UTF8') from None
        if strategy not in {'keyword', 'vector', 'hybrid'}:
            raise ValueError('INVALID_STRATEGY')
        if mode == 'historical_evidence' and timestamp(as_of) is None:
            raise ValueError('HISTORICAL_AS_OF_REQUIRED_WITH_TIMEZONE')
        if not self.index.path.is_file():
            return dict(status='EVIDENCE_GAP', gaps=['INDEX_NOT_MATERIALIZED'], hits=[], **SAFETY)
        if not self.native or not callable(getattr(self.native, 'token_count', None)):
            raise ValueError('TOKEN_BUDGET_UNVERIFIED')
        # The zero-hit body is exactly the query plus one newline; the final body is
        # counted by the same pinned tokenizer service after hit selection.
        try: query_tokens = await self.native.token_count(text + '\n')
        except ValueError as error:
            if str(error) == 'TOKEN_COUNT_EXCEEDS_TOKENIZER_LIMIT': raise ValueError('QUERY_TOKEN_BUDGET_EXCEEDED') from None
            raise ValueError('TOKEN_BUDGET_UNVERIFIED') from error
        if query_tokens > 6000: raise ValueError('QUERY_TOKEN_BUDGET_EXCEEDED')
        if hasattr(self.index.owner,'begin_query'):
            try:
                self.index.owner.begin_query()
            except Exception:
                return dict(status='EVIDENCE_GAP',gaps=['OWNER_AUTHORIZATION_UNAVAILABLE'],hits=[],**SAFETY)
        with self.index.connect() as db:
            docs = self.eligible(db, security=security, market=market, source=source, date_from=date_from,
                                 date_to=date_to, mode=mode, as_of=as_of)
            db.execute('CREATE TEMP TABLE legal_documents(id TEXT PRIMARY KEY)')
            db.executemany('INSERT INTO legal_documents VALUES(?)', [(k,) for k in docs])
            rows = {r['id']: dict(r) for r in db.execute('SELECT c.* FROM chunks c JOIN legal_documents d ON c.document_id=d.id')}
            generation = self.index.generation(db)
            # FTS query syntax is never interpreted from user input. Every term is quoted.
            terms = list(dict.fromkeys(re.findall(r'[A-Za-z0-9_.]+|[\u4e00-\u9fff]+', text)))
            long = [t for t in terms if len(t) >= 3]
            lexical = {}
            if long:
                match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in long)
                # SQL document eligibility precedes ranking: no global top-k then filter.
                db.execute('CREATE TEMP TABLE legal(id TEXT PRIMARY KEY)')
                db.executemany('INSERT INTO legal VALUES(?)', [(k,) for k in rows])
                for r in db.execute('SELECT keyword.id,bm25(keyword) AS score FROM keyword JOIN legal ON legal.id=keyword.id WHERE keyword MATCH ? ORDER BY score', (match,)):
                    lexical[r['id']] = -r['score']
            # Trigram cannot find <3 chars. Codes, aliases and short Chinese have an
            # explicit exact substring route over only SQL-eligible documents.
            exact = [t for t in terms if len(t) < 3 or re.search(r'\d', t)]
            for cid, row in rows.items():
                m = docs[row['document_id']]
                aliases = ' '.join(s['name'] + ' ' + s['code'] for s in m['subjects'])
                score = sum(1 for t in exact if t.casefold() in (row['body'] + ' ' + aliases).casefold())
                if score:
                    lexical[cid] = lexical.get(cid, 0) + score
            keyword = sorted(lexical, key=lambda k: (-lexical[k], k))[:50]
            uris = sorted({(docs[r['document_id']].get('vector_scope_uri') if docs[r['document_id']].get('vector_scope_uri') and r['uri'].startswith(docs[r['document_id']]['vector_scope_uri'] + '/') else r['uri']) for r in rows.values() if r['uri']})
        vector, gaps = [], list(self._eligibility_gaps)
        vector_attempted = vector_succeeded = False
        if strategy != 'keyword' and docs:
            if not self.native or not uris:
                gaps.append('VECTORS_UNAVAILABLE_KEYWORD_ONLY')
            else:
                try:
                    vector_attempted = True
                    found = await self.native.find(text, uris, 50)
                    vector_succeeded = True
                    by_uri = defaultdict(list)
                    for cid, row in rows.items():
                        by_uri[row['uri']].append(cid)
                    vector = [cid for hit in found for cid in sorted(by_uri[hit['uri']])][:50]
                    if any(not r['uri'] for r in rows.values()):
                        gaps.append('VECTOR_COVERAGE_PARTIAL')
                except Exception:
                    gaps.append('VECTOR_FIND_FAILED_KEYWORD_ONLY')
        branches = ([keyword] if strategy == 'keyword' else [vector] if strategy == 'vector' and not gaps else [keyword, vector])
        fused = defaultdict(float)
        for branch in branches:
            for rank, cid in enumerate(branch, 1):
                fused[cid] += 1 / (60 + rank)
        cache, hits, per_pdf, spans = {}, [], defaultdict(int), defaultdict(list)
        merged_spans = {}
        # Exact body budget is enforced post-selection by the pinned tokenizer through
        # the local embedding service; chunk['tokens'] sums are the conservative pre-filter.
        tokens = query_tokens
        for cid in sorted(fused, key=lambda k: (-fused[k], k)):
            row = rows[cid]; m = docs[row['document_id']]; chunk = json.loads(row['detail'])
            pdf = row['pdf_sha']; page_key = (pdf, row['page'])
            overlaps = [h for h in hits if (h['pdf_sha256'], h['page']) == page_key and
                        max(merged_spans[h['chunk_id']][0], chunk['start']) < min(merged_spans[h['chunk_id']][1], chunk['end'])]
            if overlaps:
                h = overlaps[0]
                if h['document_id'] == m['document_id'] and h['input_tokens_upper_bound'] + chunk['tokens'] <= 1024 and tokens + chunk['tokens'] <= 6000 and self.verify(m, row, cache):
                    start, end = merged_spans[h['chunk_id']]
                    start, end = min(start, chunk['start']), max(end, chunk['end'])
                    page = next(p for p in cache[m['document_id']]['pages'] if p['page_number'] == row['page'])
                    h['text'] = chunk['repeated_header'] + page['text'][start:end]
                    h['merged_chunk_ids'].append(cid)
                    h['input_tokens_upper_bound'] += chunk['tokens']
                    tokens += chunk['tokens']
                    merged_spans[h['chunk_id']] = (start,end)
                continue
            if per_pdf[pdf] >= 3:
                continue
            if tokens + chunk['tokens'] > 6000:
                continue
            if not self.verify(m, row, cache):
                gaps.append('SOURCE_PAGE_RECEIPT_OR_PERMISSION_CHANGED')
                continue
            tokens += chunk['tokens']; per_pdf[pdf] += 1; spans[page_key].append((chunk['start'], chunk['end']))
            hits.append(dict(chunk_id=cid, document_id=m['document_id'], research_date=m['research_date'],
                title=m['title'], source=m['source'], publisher=m['publisher'], subjects=m['subjects'],
                entity_role='TITLE_SUBJECT_EXPLICIT_CODE' if m['subjects'] else 'UNKNOWN_NOT_SUBJECT_CONFIRMED',
                page=row['page'], pdf_sha256=pdf, page_sha256=row['page_sha'], receipt_sha256=m['receipt_sha'],
                text=row['body'], quality=chunk['quality'], native_uri=row['uri'],
                merged_chunk_ids=[cid], input_tokens_upper_bound=chunk['tokens'],
                original_url=f"/api/v4/research/pdf-documents/{m['document_id']}?research_date={m['research_date']}",
                published_at=m['published_at'], fetched_at=m['fetched_at'], text_ready_at=m['text_ready_at'],
                analysis_at=m['analysis_at'], available_at=m['available_at'], pit_status=m['pit_status'],
                retrieval_score=fused[cid], score_role='RETRIEVAL_ONLY_NOT_SELECTION', independent_evidence_key=pdf))
            merged_spans[cid] = (chunk['start'],chunk['end'])
            if len(hits) == limit:
                break
        body = text + '\n' + '\n\n'.join(h['text'] for h in hits)
        try: exact = await self.native.token_count(body)
        except ValueError: raise ValueError('TOKEN_BUDGET_UNVERIFIED') from None
        while exact > 6000 and hits:
            hits.pop(); gaps.append('TOKEN_BUDGET_TRUNCATED')
            body = text + '\n' + '\n\n'.join(h['text'] for h in hits)
            try: exact = await self.native.token_count(body)
            except ValueError: raise ValueError('TOKEN_BUDGET_UNVERIFIED') from None
        return dict(schema_version='v4.report_evidence.v1', status='CANDIDATES' if hits else 'NO_EVIDENCE',
                    mode=mode, as_of=as_of, search_mode=('keyword_only' if strategy=='keyword' or any('KEYWORD_ONLY' in g for g in gaps) else (strategy+'_partial' if gaps else strategy)),
                    gaps=sorted(set(gaps)), hits=hits, index_generation=generation, input_tokens_upper_bound=exact,
                    token_counter='PINNED_BGE_M3_IN_PROCESS_V1',
                    vector_attempted=vector_attempted, vector_succeeded=vector_succeeded,
                    vector_scope_sha256=digest(json.dumps(uris,sort_keys=True)), branch_counts={'keyword':len(keyword),'vector':len(vector)},
                    query_coverage={'eligible_documents':len(docs),'eligible_chunks':len(rows),'native_indexed_chunks':sum(bool(r['uri']) for r in rows.values()),'native_scope_uris':len(uris)},
                    answer_status='ORIGINAL_TEXT_CANDIDATES_NOT_FACT_CERTIFICATION', **SAFETY)

    def read(self, chunk_id):
        if not re.fullmatch('[0-9a-f]{64}', chunk_id):
            raise ValueError('INVALID_CHUNK_ID')
        with self.index.connect() as db:
            row = db.execute('SELECT c.*,d.metadata,d.active FROM chunks c JOIN documents d ON c.document_id=d.id WHERE c.id=?', (chunk_id,)).fetchone()
        if row is None or not row['active']:
            raise ValueError('OUT_OF_SCOPE_OR_RETRACTED')
        row = dict(row); m = json.loads(row['metadata'])
        if self.document_allowlist is not None and m['document_id'] not in self.document_allowlist:
            raise ValueError('OUT_OF_SCOPE_OR_RETRACTED')
        if m.get('retracted') or not self.verify(m, row, {}):
            raise ValueError('SOURCE_PAGE_RECEIPT_OR_PERMISSION_CHANGED')
        return dict(document_id=m['document_id'], page=row['page'], text=row['body'],
                    pdf_sha256=row['pdf_sha'], page_sha256=row['page_sha'], receipt_sha256=m['receipt_sha'], **SAFETY)
