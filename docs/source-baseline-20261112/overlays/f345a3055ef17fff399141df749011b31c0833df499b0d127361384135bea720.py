"""Disposable report index. Only explicit operations write; queries open SQLite read-only.

The existing PDF owner remains the authority and is re-read before returning a hit.
No downloader, OCR, analysis, selection scoring or scheduler lives in this module.
"""
from __future__ import annotations
import hashlib
import json
import os
import stat
from functools import lru_cache
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

CHUNK_VERSION = 'report-structure-bge512-max1024-overlap64-v1'
MODEL_REVISION = '5617a9f61b028005a4858fdac845db406aefb181'
NAMESPACE = 'viking://resources/v4-report-evidence-20261102'
SAFETY = dict(RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False)

def digest(value: str | bytes) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()

def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

def timestamp(value: Any) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d if d.tzinfo is not None else None
    except (ValueError, TypeError):
        return None

class PdfOwner:
    def __init__(self, data_root: Path | str):
        self.root = Path(data_root)
        try:
            from infrastructure import zsxq_pdf_ingestion
        except ImportError:
            from infrastructure import report_evidence_pdf_owner as zsxq_pdf_ingestion
        # Current API retains its canonical owner. Older Main/Stage readers use
        # only the fixed, byte-pinned read-contract alias, never a caller path.
        owner=zsxq_pdf_ingestion
        if 'verified_pdf_sha256' not in repr(getattr(getattr(getattr(owner,'_verified_document_detail',None),'__code__',None),'co_consts',())):
            from infrastructure import report_evidence_pdf_owner
            owner=report_evidence_pdf_owner
        self.owner = owner
        self.store = self.owner.NativeDataStore(self.root)
        self._query_index = None
        self._index_signature = None
        self._authorization = {}
        self._query_signatures = {}

    def _signature(self, relative):
        # Open every ancestry through the existing no-follow owner boundary.
        io = self.owner._store_io(self.store)
        with io.parent(relative) as (parent, name):
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
            try:
                s = os.fstat(fd)
                if not stat.S_ISREG(s.st_mode):
                    raise ValueError('SOURCE_NOT_REGULAR')
                return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_mode,s.st_uid,s.st_gid)
            finally:
                os.close(fd)

    def begin_query(self):
        signature = self._signature(self.owner.STATE_RELATIVE)
        if signature != self._index_signature:
            self._query_index = self.owner._read_index(self.store)
            self._authorization.clear()
            if signature != self._signature(self.owner.STATE_RELATIVE):
                raise ValueError('OWNER_INDEX_CHANGED_DURING_READ')
            self._index_signature = signature
        self._query_signatures = {}

    def authorized(self, m):
        """Source/permission preflight BEFORE either ranked candidate branch.

        Cache only a successful full owner verification. Reuse requires the same
        owner index and no-follow readable file identities/ctime/mode for every
        bound input and artifact. Candidate readback still performs fresh hashes.
        """
        try:
            if self._query_index is None:
                self.begin_query()
            row = self._query_index['documents'][m['document_id']]
            if row.get('retracted') is True:
                return False
            source = row['source']; latest = self.owner._latest_engine_run(row)
            if latest is None or latest[1].get('status') != 'READY':
                return False
            pdf,pages,receipt = self.owner._safe_document_paths(source,latest[1],latest[0])
            entry = self._query_index['sources'][source['source_run_id']]
            day,slot,run = source['trade_date'],entry['slot'],source['source_run_id']
            paths = [self.owner.STATE_RELATIVE,pdf,pages,receipt,
                f'research_module/runtime_outputs/zsxq_hourly/{day}/{slot}/v35_zsxq_hourly_status_{day}_{slot}.json',
                *[f'external_sources/zsxq_hourly/{run}/{name}' for name in
                  ('zsxq_recent_topics_fetch_result.json','zsxq_recent_topics.json','zsxq_summary.json')]]
            signatures = tuple((p,self._signature(p)) for p in paths)
            key = digest(canonical({k:v for k,v in m.items() if k!='vector_scope_uri'}))
            if self._authorization.get(key) == signatures:
                return True
            detail = self.owner._verified_document_detail(self.store,self._query_index,m['document_id'],verify_pdf=True)
            detail['schema_version'] = 'v4.zsxq_pdf_document_detail.v1'
            if metadata(detail) != {k:v for k,v in m.items() if k!='vector_scope_uri'}:
                return False
            if signatures != tuple((p,self._signature(p)) for p in paths):
                return False
            self._authorization[key] = signatures
            return True
        except Exception:
            return False

    def inventory(self):
        # Enumerate the existing owner's index, never directory-scan PDFs.
        index = self.owner._read_index(self.owner.NativeDataStore(self.root))
        for doc_id, row in sorted(index['documents'].items()):
            yield doc_id, row.get('source', {}).get('trade_date')

    def detail(self, document_id: str, research_date: str) -> dict:
        return self.owner.read_pdf_document_detail(self.root, document_id, research_date)

    def verified(self, document_id: str, research_date: str) -> dict:
        detail = self.detail(document_id, research_date)
        if (detail.get('status') != 'READY' or
            detail.get('receipt', {}).get('integrity') != 'SOURCE_PDF_AND_PAGE_HASHES_VERIFIED' or
            not re.fullmatch('[0-9a-f]{64}', str(detail.get('receipt', {}).get('verified_pdf_sha256', '')))):
            raise ValueError('OWNER_DOCUMENT_NOT_READY_OR_VERIFIED')
        for page in detail.get('pages', []):
            if digest(page['text']) != page.get('text_sha256'):
                raise ValueError('PAGE_SHA_MISMATCH')
        return detail

@lru_cache(maxsize=4)
def shared_pdf_owner(data_root: str):
    return PdfOwner(data_root)

class BgeTokenizer:
    """Pinned official local tokenizer, no model load and no network download."""
    def __init__(self, model_dir: str):
        from tokenizers import Tokenizer
        self.tokenizer = Tokenizer.from_file(str(Path(model_dir) / 'tokenizer.json'))
    def encode(self, text):
        return self.tokenizer.encode(text, add_special_tokens=False)
    def count(self, text):
        return len(self.encode(text).ids) + 2


def structure_chunks(text: str, tokenizer: BgeTokenizer):
    """Keep source character spans and line boundaries; never reconstruct OCR cells.

    Markdown tables split on rows, repeating the original header and units. Flattened
    OCR financial tables are explicitly uncertain and keep their original line order.
    """
    enc = tokenizer.encode(text)
    if not enc.ids:
        return
    table = bool(re.search(r'财务|现金流量表|资产负债表|\|.*\|', text))
    markdown = bool(re.search(r'^\s*\|(?:\s*:?-{3,}:?\s*\|)+\s*$', text, re.M))
    prefix = ''
    if table:
        headers = [line for line in text.splitlines() if re.search(r'百万元|亿元|单位|20\d\d[AE]|\|.*\|', line)]
        prefix = '\n'.join(headers[:8])[:400] + '\n'
        while tokenizer.count(prefix) > 160:
            prefix = prefix[:len(prefix)//2]
    start = 0
    while start < len(enc.ids):
        reserve = tokenizer.count(prefix) if prefix else 0
        end = min(start + 512 - reserve, len(enc.ids))
        char_start = enc.offsets[start][0]
        char_end = enc.offsets[end-1][1]
        # Prefer a paragraph/row boundary in the latter half of a normal chunk.
        boundary = text.rfind('\n', char_start + (char_end-char_start)//2, char_end)
        if end < len(enc.ids) and boundary > char_start:
            char_end = boundary + 1
            while end > start+1 and enc.offsets[end-1][0] >= char_end:
                end -= 1
        body = text[char_start:char_end]
        content = prefix + body if prefix and char_start else body
        if tokenizer.count(content) > 1024:
            raise ValueError('CHUNK_TOKEN_LIMIT')
        yield dict(text=content, source_text=body, start=char_start, end=char_end,
                   tokens=tokenizer.count(content), quality='TABLE_ROWS_PRESERVED' if markdown else
                   ('LINEARIZED_OCR_TABLE_UNCERTAIN' if table else 'OWNER_PAGE_TEXT'),
                   repeated_header=prefix if prefix and char_start else '')
        if end == len(enc.ids):
            break
        # Table rows are not split by synthetic column inference. Ordinary prose overlaps.
        next_start = end if table else max(start+1, end-64)
        start = next_start


def metadata(detail: dict) -> dict:
    from domains.report_subjects import report_title_evidence
    source, processing, receipt = detail['source'], detail['processing'], detail['receipt']
    roles = report_title_evidence(source.get('original_filename', ''), 'research_report')
    times = [timestamp(processing.get(k)) for k in ('available_at', 'completed_at')]
    times += [timestamp(source.get('source_fetched_at'))]
    available = max(times).isoformat() if all(times) else None
    return dict(document_id=detail['document_id'], research_date=detail['research_date'],
                title=source.get('original_filename'), source=source.get('group_name'),
                publisher=roles['publisher'], subjects=roles['subjects'],
                pdf_sha=receipt['verified_pdf_sha256'], receipt_sha=receipt['sha256'],
                receipt_path=receipt['path'], published_at=source.get('pdf_published_at'),
                fetched_at=source.get('source_fetched_at'), text_ready_at=processing.get('completed_at'),
                analysis_at=None, available_at=available, pit_status=processing.get('pit_status'),
                source_run_id=source.get('source_run_id'), retracted=False)

class ReportIndex:
    def __init__(self, root: str | Path, owner: PdfOwner):
        self.root, self.owner = Path(root).absolute(), owner
        if (self.root.is_symlink() or any(p.is_symlink() for p in self.root.parents) or self.root.resolve() == owner.root.resolve()
            or owner.root.resolve() in self.root.resolve().parents or self.root.resolve() in owner.root.resolve().parents):
            raise ValueError('INDEX_ROOT_MUST_BE_ISOLATED')
        self.path = self.root / 'reports.sqlite3'

    @contextmanager
    def connect(self, write=False):
        if self.path.is_symlink():
            raise ValueError('INDEX_SYMLINK_REJECTED')
        if write:
            self.root.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path, timeout=30)
        else:
            db = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            if write:
                db.commit()
        finally:
            db.close()

    def initialize(self):
        with self.connect(True) as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS documents(id TEXT PRIMARY KEY, metadata TEXT NOT NULL, fingerprint TEXT NOT NULL, active INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS chunks(id TEXT PRIMARY KEY, document_id TEXT NOT NULL, pdf_sha TEXT NOT NULL,
                page INTEGER NOT NULL, page_sha TEXT NOT NULL, body TEXT NOT NULL, detail TEXT NOT NULL, uri TEXT, model_revision TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS chunk_document ON chunks(document_id);
            CREATE VIRTUAL TABLE IF NOT EXISTS keyword USING fts5(id UNINDEXED, body, tokenize='trigram');
            CREATE TABLE IF NOT EXISTS ledger(id TEXT PRIMARY KEY,status TEXT NOT NULL, reason TEXT);
            CREATE TABLE IF NOT EXISTS native_tasks(id TEXT PRIMARY KEY, entry TEXT NOT NULL);
            ''')

    def upsert(self, detail: dict, tokenizer: BgeTokenizer) -> str:
        m = metadata(detail)
        fp = digest(canonical([m, [(p['page_number'], p['text_sha256']) for p in detail['pages']], CHUNK_VERSION, MODEL_REVISION]))
        with self.connect(True) as db:
            old = db.execute('SELECT fingerprint FROM documents WHERE id=?', (m['document_id'],)).fetchone()
            if old and old[0] == fp:
                db.execute('UPDATE documents SET active=1 WHERE id=?', (m['document_id'],))
                return 'REUSED'
            ids = [r[0] for r in db.execute('SELECT id FROM chunks WHERE document_id=?', (m['document_id'],))]
            db.executemany('DELETE FROM keyword WHERE id=?', [(x,) for x in ids])
            db.execute('DELETE FROM chunks WHERE document_id=?', (m['document_id'],))
            db.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,1)', (m['document_id'], canonical(m), fp))
            for page in detail['pages']:
                for chunk in structure_chunks(page['text'], tokenizer):
                    cid = digest(canonical([m['pdf_sha'], page['text_sha256'], page['page_number'], chunk['start'], chunk['end'], CHUNK_VERSION, MODEL_REVISION]))
                    # Multiple forwarded copies share native content identity but retain source rows.
                    rowid = digest(m['document_id'] + cid)
                    chunk['content_id'] = cid
                    db.execute('INSERT INTO chunks VALUES(?,?,?,?,?,?,?,?,?)',
                               (rowid, m['document_id'], m['pdf_sha'], page['page_number'], page['text_sha256'], chunk['text'], canonical(chunk), None, MODEL_REVISION))
                    db.execute('INSERT INTO keyword VALUES(?,?)', (rowid, chunk['text']))
            db.execute('INSERT OR REPLACE INTO ledger VALUES(?,?,?)', (m['document_id'], 'INDEXED', None))
        return 'INDEXED'

    def record_gap(self, doc_id: str, reason: str):
        with self.connect(True) as db:
            db.execute('UPDATE documents SET active=0 WHERE id=?', (doc_id,))
            db.execute('INSERT OR REPLACE INTO ledger VALUES(?,?,?)', (doc_id, 'CANNOT_CONFIRM', reason))

    def generation(self, db):
        return digest(canonical([tuple(r) for r in db.execute('SELECT id,fingerprint,active FROM documents ORDER BY id')]) +
                      canonical([tuple(r) for r in db.execute('SELECT id,uri,model_revision FROM chunks ORDER BY id')]))

    def coverage(self):
        with self.connect() as db:
            return dict(documents=db.execute('SELECT count(*) FROM documents WHERE active=1').fetchone()[0],
                        chunks=db.execute('SELECT count(*) FROM chunks').fetchone()[0],
                        vectors=db.execute('SELECT count(*) FROM chunks WHERE uri IS NOT NULL').fetchone()[0],
                        statuses={r[0]: r[1] for r in db.execute('SELECT status,count(*) FROM ledger GROUP BY status')},
                        generation=self.generation(db), chunk_version=CHUNK_VERSION, model_revision=MODEL_REVISION)
