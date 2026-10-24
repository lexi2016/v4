"""Sole writer of immutable PDF cards/results, review receipts and derived indexes."""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import base64
from datetime import datetime
from typing import Any, Mapping

from infrastructure.pdf_research_identity import SourceOccurrence, canonical_json
from infrastructure import pdf_research_protocol as protocol

SHA = re.compile(r'^[0-9a-f]{64}$')


class PublicationError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def checked_path(root: Path, path: Path) -> Path:
    root, path = Path(root).absolute(), Path(path).absolute()
    if '..' in root.parts or '..' in path.parts:
        raise PublicationError('PDF_OWNED_PATH_INVALID')
    try:
        path.relative_to(root)
    except ValueError:
        raise PublicationError('PDF_PATH_OUTSIDE_OWNED_ROOT') from None
    cursor = path
    while True:
        if cursor.is_symlink():
            raise PublicationError('PDF_OWNED_PATH_SYMLINK')
        if cursor == cursor.parent:
            break
        cursor = cursor.parent
    return path


def read_bytes(path: Path, *, root: Path | None = None) -> bytes:
    path = checked_path(root or path.parent, path)
    if not path.is_file():
        raise PublicationError('PDF_ARTIFACT_UNAVAILABLE')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
    try:
        with os.fdopen(fd, 'rb') as stream:
            return stream.read()
    except Exception:
        raise


def read_json(path, *, root=None):
    try:
        def pairs(items):
            value = {}
            for key, item in items:
                if key in value:
                    raise ValueError('duplicate key')
                value[key] = item
            return value
        return json.loads(read_bytes(Path(path), root=root), object_pairs_hook=pairs,
                          parse_constant=lambda _value: (_ for _ in ()).throw(ValueError('nonfinite')))
    except (ValueError, UnicodeError):
        raise PublicationError('PDF_ARTIFACT_JSON_INVALID') from None


def read_reference(reference):
    if (not isinstance(reference, Mapping) or set(reference) - {'path', 'sha256'}
            or not SHA.fullmatch(str(reference.get('sha256', ''))) or not isinstance(reference.get('path'), str)):
        raise PublicationError('PDF_REFERENCE_INVALID')
    path = Path(reference['path'])
    if not path.is_absolute():
        raise PublicationError('PDF_REFERENCE_PATH_INVALID')
    raw = read_bytes(path)
    if digest(raw) != reference['sha256']:
        raise PublicationError('PDF_REFERENCE_SHA_MISMATCH')
    return raw


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_bytes(root, path, raw, *, immutable):
    path = checked_path(root, path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    checked_path(root, path)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temporary = Path(name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if immutable:
            try:
                os.link(temporary, path)
            except FileExistsError:
                if read_bytes(path, root=root) != raw:
                    raise PublicationError('PDF_IMMUTABLE_ARTIFACT_CONFLICT') from None
        else:
            os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)
    return digest(raw)


def write_json(root, path, value, *, immutable=True):
    return write_bytes(root, path, canonical_json(value) + b'\n', immutable=immutable)


@contextmanager
def owned_lock(root, path):
    path = checked_path(root, path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PublicationError('PDF_OWNER_BUSY') from None
        yield
    finally:
        os.close(fd)


class PdfPublisher:
    def __init__(self, research_root):
        self.root = checked_path(Path(research_root), Path(research_root))
        self.base = self.root / 'analyses'

    def version_root(self, analysis_id, generation):
        if not SHA.fullmatch(str(analysis_id)) or type(generation) is not int or generation < 0:
            raise PublicationError('PDF_RESULT_VERSION_INVALID')
        return checked_path(self.root, self.base / analysis_id / f'g{generation:06d}')

    def record_chunk(self, analysis_id, generation, chunk_index, value):
        if type(chunk_index) is not int or chunk_index < 1:
            raise PublicationError('PDF_CHUNK_INDEX_INVALID')
        if value.get('analysis_id') != analysis_id or value.get('generation') != generation or value.get('chunk_index') != chunk_index:
            raise PublicationError('PDF_CHUNK_BINDING_MISMATCH')
        path = self.version_root(analysis_id, generation) / 'chunks' / f'{chunk_index:04d}.json'
        with owned_lock(self.root, self.root / 'publication.lock'):
            return write_json(self.root, path, value)

    def read_chunk(self, analysis_id, generation, chunk_index):
        path = self.version_root(analysis_id, generation) / 'chunks' / f'{chunk_index:04d}.json'
        checked_path(self.root, path)
        return read_json(path, root=self.root) if path.exists() else None

    def publish(self, task, generation, chunks, *, generated_at, writer_id, source_sha256, crash=None):
        analysis_id = task['analysis_id']
        expected = task['chunks']
        if len(chunks) != len(expected) or any(
            c.get('analysis_id') != analysis_id or c.get('generation') != generation
            or c.get('chunk_index') != index or c.get('chunk_sha256') != expected[index - 1]['sha256']
            or c.get('deterministic_status') != 'PASS'
            for index, c in enumerate(chunks, 1)):
            raise PublicationError('PDF_COMPLETE_CHUNK_COVERAGE_REQUIRED')
        occurrences = []
        for occurrence in task['occurrences']:
            value = SourceOccurrence(occurrence['namespace'], occurrence['original_source_id'])
            if occurrence.get('model_visible_metadata') != task['metadata']:
                raise PublicationError('PDF_OCCURRENCE_CONTEXT_MISMATCH')
            occurrences.append({'namespace': value.namespace, 'original_source_id': value.original_source_id,
                'occurrence_id': value.occurrence_id})
        result = {'schema': 'v4.pdf_research.immutable_result.v1', 'analysis_id': analysis_id,
            'input_manifest': task['input_manifest'], 'generation': generation, 'context_id': analysis_id,
            'metadata': task['metadata'], 'pdf_sha256': task['pdf_sha256'],
            'protocol_sha256': protocol.PROTOCOL_SHA256, 'source_sha256': dict(source_sha256),
            'generated_at': generated_at, 'writer_id': writer_id,
            'cards': [c['validated']['card'] for c in chunks],
            'body_markdown': '\n\n'.join(f"来源分块 {i}/{len(chunks)}\n" + protocol.render_card(c['validated']['card']) for i, c in enumerate(chunks, 1)),
            'coverage': {'status': 'COMPLETE', 'page_count': task['page_count'],
                'chunk_count': len(chunks), 'evidence_ids': [x for c in expected for x in c['evidence_ids']]},
            'chunk_raw_sha256': [c['raw_sha256'] for c in chunks],
            'validation_status': 'PASS', 'semantic_review': 'PENDING_INDEPENDENT_REVIEW',
            'research_only': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
        version_root = self.version_root(analysis_id, generation)
        with owned_lock(self.root, self.root / 'publication.lock'):
            result_sha = write_json(self.root, version_root / 'result.json', result)
            if crash: crash('after_result')
            metadata = {key: result[key] for key in ('analysis_id', 'generation', 'context_id',
                'metadata', 'pdf_sha256', 'protocol_sha256', 'generated_at', 'coverage', 'validation_status', 'writer_id')}
            metadata.update(schema='v4.pdf_research.result_metadata.v1', result_sha256=result_sha,
                result_path=str((version_root / 'result.json').relative_to(self.root)),
                body_preview=result['body_markdown'][:240], semantic_review='PENDING_INDEPENDENT_REVIEW')
            write_json(self.root, version_root / 'metadata.json', metadata)
            for occurrence in occurrences:
                association = {'analysis_id': analysis_id, 'generation': generation, 'context_id': analysis_id,
                    'occurrence': occurrence, 'result_sha256': result_sha, 'metadata': task['metadata']}
                write_json(self.root, version_root / 'occurrence-associations' / (occurrence['occurrence_id'] + '.json'), association)
            if crash: crash('before_index')
            self._rebuild_index_locked()
            if crash: crash('after_index')
        return metadata

    def accept(self, analysis_id, generation, review_reference):
        receipt = json.loads(read_reference(review_reference))
        version_root = self.version_root(analysis_id, generation)
        with owned_lock(self.root, self.root / 'publication.lock'):
            meta = read_json(version_root / 'metadata.json', root=self.root)
            if (receipt.get('verdict') != 'PASS' or receipt.get('review_type') != 'CONTENT'
                    or receipt.get('scope') != 'FULL_ANALYSIS' or receipt.get('critical_errors') != 0
                    or receipt.get('analysis_id') != analysis_id or receipt.get('input_manifest_sha256') != analysis_id
                    or receipt.get('context_id') != analysis_id or receipt.get('generation') != generation
                    or receipt.get('result_sha256') != meta['result_sha256']
                    or receipt.get('protocol_sha256') != meta['protocol_sha256']
                    or receipt.get('independent') is not True or not receipt.get('reviewer_id')
                    or receipt['reviewer_id'] == meta['writer_id']):
                raise PublicationError('PDF_INDEPENDENT_CONTENT_REVIEW_REQUIRED')
            proof = {'schema': 'v4.pdf_research.content_review.v1', 'receipt': receipt,
                     'source_reference': dict(review_reference)}
            write_json(self.root, version_root / 'accepted-review.json', proof)
            self._rebuild_index_locked()

    def _rebuild_index_locked(self):
        summaries = []
        for path in sorted(self.base.glob('*/g*/metadata.json')):
            meta = read_json(path, root=self.root)
            result_path = checked_path(self.root, self.root / meta['result_path'])
            result_bytes = read_bytes(result_path, root=self.root)
            if digest(result_bytes) != meta['result_sha256']:
                raise PublicationError('PDF_RESULT_SHA_MISMATCH')
            result = json.loads(result_bytes)
            if (meta['context_id'] != meta['analysis_id'] or any(meta[key] != result[key]
                    for key in ('analysis_id', 'generation', 'context_id', 'metadata', 'pdf_sha256',
                                'protocol_sha256', 'generated_at', 'coverage', 'validation_status', 'writer_id'))):
                raise PublicationError('PDF_RESULT_METADATA_BINDING_MISMATCH')
            proof_path = path.parent / 'accepted-review.json'
            accepted = proof_path.exists()
            if accepted:
                proof = read_json(proof_path, root=self.root)
                receipt = proof.get('receipt', {})
                external = json.loads(read_reference(proof.get('source_reference')))
                if (receipt != external or receipt.get('result_sha256') != meta['result_sha256']
                        or receipt.get('analysis_id') != meta['analysis_id'] or receipt.get('context_id') != meta['context_id']
                        or receipt.get('input_manifest_sha256') != meta['analysis_id']
                        or receipt.get('generation') != meta['generation'] or receipt.get('protocol_sha256') != meta['protocol_sha256']
                        or receipt.get('verdict') != 'PASS' or receipt.get('scope') != 'FULL_ANALYSIS'
                        or receipt.get('review_type') != 'CONTENT' or receipt.get('critical_errors') != 0
                        or receipt.get('independent') is not True or not receipt.get('reviewer_id')
                        or receipt['reviewer_id'] == meta['writer_id']):
                    raise PublicationError('PDF_REVIEW_RESULT_BINDING_MISMATCH')
            associations = []
            for association_path in sorted((path.parent / 'occurrence-associations').glob('*.json')):
                association = read_json(association_path, root=self.root)
                occurrence = association['occurrence']
                identity = SourceOccurrence(occurrence['namespace'], occurrence['original_source_id'])
                if (association.get('analysis_id') != meta['analysis_id'] or association.get('context_id') != meta['context_id']
                        or association.get('generation') != meta['generation'] or association.get('metadata') != meta['metadata']
                        or association.get('result_sha256') != meta['result_sha256']
                        or occurrence.get('occurrence_id') != identity.occurrence_id):
                    raise PublicationError('PDF_OCCURRENCE_ASSOCIATION_MISMATCH')
                associations.append(occurrence)
            summaries.append({**meta, 'occurrences': associations, 'semantic_review': 'ACCEPTED' if accepted else 'PENDING_INDEPENDENT_REVIEW'})
        families = {}
        for meta in sorted(summaries, key=lambda x: (x['analysis_id'], x['generation'])):
            for occurrence in meta['occurrences']:
                key = (occurrence['occurrence_id'], meta['context_id'])
                family = families.setdefault(key, {'occurrence': occurrence, 'context_id': meta['context_id'],
                    'latest_generated': None, 'accepted': None})
                pointer = {key: meta[key] for key in ('analysis_id', 'generation', 'result_sha256', 'result_path')}
                family['latest_generated'] = pointer
                if meta['semantic_review'] == 'ACCEPTED':
                    family['accepted'] = pointer
        for (occurrence_id, context), value in families.items():
            write_json(self.root, self.root / 'occurrences' / occurrence_id / (context + '.json'), value, immutable=False)
        write_json(self.root, self.root / 'analysis-index.json', {'schema': 'v4.pdf_research.index.v1',
            'items': sorted(summaries, key=lambda x: (x['generated_at'], x['analysis_id'], x['generation']), reverse=True)}, immutable=False)
        return len(summaries)

    def rebuild_index(self):
        with owned_lock(self.root, self.root / 'publication.lock'):
            return self._rebuild_index_locked()

    def pointers(self, occurrence: SourceOccurrence, analysis_id):
        if not SHA.fullmatch(str(analysis_id)):
            raise PublicationError('PDF_CONTEXT_INVALID')
        path = self.root / 'occurrences' / occurrence.occurrence_id / (analysis_id + '.json')
        checked_path(self.root, path)
        if not path.exists():
            return {'occurrence': {'namespace': occurrence.namespace, 'original_source_id': occurrence.original_source_id},
                    'context_id': analysis_id, 'latest_generated': None, 'accepted': None}
        value = read_json(path, root=self.root)
        if value['context_id'] != analysis_id or value['occurrence']['occurrence_id'] != occurrence.occurrence_id:
            raise PublicationError('PDF_POINTER_CONTEXT_MISMATCH')
        return value


    def import_legacy_reference(self, occurrence, pdf_sha256, result_reference, review_reference, scope):
        # Legacy input identity cannot be invented. Keep the original scoped
        # acceptance as a read-only reference, outside new analysis pointers.
        read_reference(result_reference)
        review = json.loads(read_reference(review_reference))
        if not SHA.fullmatch(str(pdf_sha256)) or not scope or not isinstance(review, dict):
            raise PublicationError('PDF_LEGACY_REFERENCE_INVALID')
        value = {'schema': 'v4.pdf_research.legacy_reference.v1', 'namespace': occurrence.namespace,
            'original_source_id': occurrence.original_source_id, 'occurrence_id': occurrence.occurrence_id,
            'pdf_sha256': pdf_sha256, 'result_reference': dict(result_reference),
            'review_reference': dict(review_reference), 'scope': scope,
            'status': 'LEGACY_SCOPED_REFERENCE_NOT_NEW_INPUT_ACCEPTANCE', 'analysis_id': None}
        key = digest(canonical_json(value))
        with owned_lock(self.root, self.root / 'publication.lock'):
            write_json(self.root, self.root / 'legacy-references' / (key + '.json'), value)
        return value


def _document_date(metadata):
    """Only explicit source-document dates select a dated report bucket."""
    value = metadata.get('source_document_date')
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    compact = value.replace('-', '')
    try:
        if not re.fullmatch(r'[0-9]{8}', compact):
            return None
        datetime.strptime(compact, '%Y%m%d')
    except ValueError:
        return None
    return compact


class PdfResearchReader:
    """Read immutable summaries and lazy bodies; never rebuild or acquire locks.

    The index and occurrence pointers are writer-owned derived conveniences.
    Reads use immutable metadata/associations instead, so a crash before index
    publication cannot cause a GET to repair state. Bodies are opened only by
    detail(). Legacy references retain their own identity and original scope.
    """
    def __init__(self, research_root):
        self.root = checked_path(Path(research_root), Path(research_root))

    def _review(self, directory, meta):
        path = directory / 'accepted-review.json'
        checked_path(self.root, path)
        if not path.exists():
            return None
        proof = read_json(path, root=self.root)
        receipt = proof.get('receipt', {})
        external = json.loads(read_reference(proof.get('source_reference')))
        if (receipt != external or any(receipt.get(key) != value for key, value in {
                'result_sha256': meta['result_sha256'], 'analysis_id': meta['analysis_id'],
                'context_id': meta['analysis_id'], 'input_manifest_sha256': meta['analysis_id'],
                'generation': meta['generation'], 'protocol_sha256': meta['protocol_sha256'],
                'verdict': 'PASS', 'scope': 'FULL_ANALYSIS', 'review_type': 'CONTENT',
                'critical_errors': 0, 'independent': True}.items())
                or not receipt.get('reviewer_id') or receipt['reviewer_id'] == meta['writer_id']):
            raise PublicationError('PDF_REVIEW_RESULT_BINDING_MISMATCH')
        return proof

    def _versions(self):
        families = {}
        for path in sorted((self.root / 'analyses').glob('*/g*/metadata.json')):
            meta = read_json(path, root=self.root)
            aid, gen = meta.get('analysis_id'), meta.get('generation')
            expected = PdfPublisher(self.root).version_root(aid, gen)
            if (path.parent != expected or meta.get('context_id') != aid
                    or meta.get('schema') != 'v4.pdf_research.result_metadata.v1'
                    or not SHA.fullmatch(str(meta.get('result_sha256', '')))
                    or meta.get('result_path') != str((expected / 'result.json').relative_to(self.root))):
                raise PublicationError('PDF_RESULT_METADATA_BINDING_MISMATCH')
            proof = self._review(expected, meta)
            version = {key: meta[key] for key in ('analysis_id', 'generation', 'result_sha256', 'generated_at', 'validation_status')}
            version.update(semantic_review='ACCEPTED' if proof else 'PENDING_INDEPENDENT_REVIEW',
                scope='FULL_ANALYSIS' if proof else None, body_preview=meta.get('body_preview', ''))
            for association_path in sorted((expected / 'occurrence-associations').glob('*.json')):
                association = read_json(association_path, root=self.root)
                occurrence = association.get('occurrence', {})
                try:
                    identity = SourceOccurrence(occurrence['namespace'], occurrence['original_source_id'])
                except (ValueError, KeyError, TypeError):
                    raise PublicationError('PDF_OCCURRENCE_ASSOCIATION_MISMATCH') from None
                if (association_path.stem != identity.occurrence_id or occurrence.get('occurrence_id') != identity.occurrence_id
                        or any(association.get(key) != meta[key] for key in ('analysis_id', 'generation', 'context_id', 'metadata', 'result_sha256'))):
                    raise PublicationError('PDF_OCCURRENCE_ASSOCIATION_MISMATCH')
                key = (aid, identity.occurrence_id)
                family = families.setdefault(key, {'analysis_id': aid, 'reference_id': aid, 'reference_kind': 'ANALYSIS',
                    'occurrence': occurrence, 'metadata': meta['metadata'], 'research_date': _document_date(meta['metadata']),
                    'pdf_sha256': meta['pdf_sha256'], 'versions': [], 'preparation_status': 'COMPLETE',
                    'execution_status': 'GENERATED', 'reason_code': None})
                if family['metadata'] != meta['metadata'] or family['pdf_sha256'] != meta['pdf_sha256']:
                    raise PublicationError('PDF_RESULT_METADATA_BINDING_MISMATCH')
                family['versions'].append(version)
        for family in families.values():
            family['versions'].sort(key=lambda x: x['generation'])
            family['latest_generated'] = family['versions'][-1]
            accepted = [x for x in family['versions'] if x['semantic_review'] == 'ACCEPTED']
            family['accepted'] = accepted[-1] if accepted else None
        return families

    def _summaries(self):
        families = self._versions()
        # Journal reading validates the durable hash chain and never appends.
        # Do not call read_run(): a historical source/config version remains a
        # readable historical record even when the current producer changes.
        from infrastructure.pdf_research_execution import Journal, RUN_SCHEMA
        for path in sorted((self.root / 'analysis-runs').glob('*/manifest.json')):
            run = read_json(path, root=self.root)
            events = Journal(self.root, path.parent / 'journal.jsonl').events
            queue = read_json(self.root / 'analysis-queue' / (path.parent.name + '.json'), root=self.root)
            reference = queue.get('reference')
            if (run.get('schema') != RUN_SCHEMA or run.get('run_id') != path.parent.name
                    or queue.get('run_id') != run['run_id'] or json.loads(read_reference(reference)) != run
                    or events and (events[0].get('event') != 'binding' or events[0].get('run_manifest_sha256') != reference['sha256'])):
                raise PublicationError('PDF_RUN_SUMMARY_BINDING_INVALID')
            for task in run.get('tasks', []):
                aid = task.get('analysis_id')
                if not SHA.fullmatch(str(aid)):
                    raise PublicationError('PDF_RUN_SUMMARY_BINDING_INVALID')
                if digest(canonical_json(task.get('input_manifest'))) != aid:
                    raise PublicationError('PDF_RUN_SUMMARY_BINDING_INVALID')
                terminals = [x for x in events if x.get('analysis_id') == aid and x.get('event') in {'failed', 'isolated', 'unknown_outcome'}]
                last = terminals[-1] if terminals else {}
                progress = path.parent / 'progress.json'
                recent = read_json(progress, root=self.root) if progress.exists() else None
                for occurrence in task.get('occurrences', []):
                    identity = SourceOccurrence(occurrence['namespace'], occurrence['original_source_id'])
                    if occurrence.get('model_visible_metadata') != task.get('metadata'):
                        raise PublicationError('PDF_OCCURRENCE_CONTEXT_MISMATCH')
                    key = (aid, identity.occurrence_id)
                    if key in families:
                        if last:
                            families[key]['latest_execution'] = {'status': last['event'].upper(), 'reason_code': last.get('code')}
                        continue
                    families[key] = {'analysis_id': aid, 'reference_id': aid, 'reference_kind': 'ANALYSIS',
                        'occurrence': {'namespace': identity.namespace, 'original_source_id': identity.original_source_id, 'occurrence_id': identity.occurrence_id},
                        'metadata': task['metadata'], 'research_date': _document_date(task['metadata']),
                        'pdf_sha256': task['pdf_sha256'], 'versions': [], 'accepted': None, 'latest_generated': None,
                        'preparation_status': 'COMPLETE', 'execution_status': last.get('event', 'WAITING_HOST_TICK').upper(),
                        'reason_code': last.get('code'), 'progress': recent if recent and recent.get('analysis_id') == aid else None}
        for path in sorted((self.root / 'legacy-references').glob('*.json')):
            value = read_json(path, root=self.root)
            if (digest(canonical_json(value)) != path.stem or value.get('schema') != 'v4.pdf_research.legacy_reference.v1'
                    or value.get('analysis_id') is not None):
                raise PublicationError('PDF_LEGACY_REFERENCE_INVALID')
            identity = SourceOccurrence(value['namespace'], value['original_source_id'])
            if value.get('occurrence_id') != identity.occurrence_id:
                raise PublicationError('PDF_OCCURRENCE_ASSOCIATION_MISMATCH')
            review = json.loads(read_reference(value['review_reference']))
            reviewed_document = next((item for item in review.get('documents', [])
                if isinstance(item, dict) and item.get('document_id') == identity.original_source_id), None)
            if review.get('document_id') is not None and review['document_id'] != identity.original_source_id:
                raise PublicationError('PDF_LEGACY_REVIEW_BINDING_MISMATCH')
            bound_result = review.get('card') or (reviewed_document or {}).get('prepared_receipt')
            if bound_result is not None and bound_result != value['result_reference']:
                raise PublicationError('PDF_LEGACY_REVIEW_BINDING_MISMATCH')
            isolated = reviewed_document is not None and str(reviewed_document.get('status', '')).startswith('SOURCE_INVALID')
            # Imported historical scopes are never full-analysis acceptance.
            families[(path.stem, identity.occurrence_id)] = {'analysis_id': None, 'reference_id': path.stem,
                'reference_kind': 'LEGACY_REFERENCE', 'occurrence': {'namespace': identity.namespace,
                    'original_source_id': identity.original_source_id, 'occurrence_id': identity.occurrence_id},
                'metadata': {'title': '历史来源引用', 'source_document_date': None, 'archived_date': None}, 'research_date': None,
                'pdf_sha256': value['pdf_sha256'], 'versions': [], 'accepted': None, 'latest_generated': None,
                'preparation_status': 'HISTORICAL_REFERENCE', 'execution_status': 'ISOLATED' if isolated else value['status'],
                'semantic_review': review.get('status', 'LEGACY_REVIEW_SCOPE_ONLY'), 'scope': value['scope'],
                'result_sha256': value['result_reference']['sha256'], 'reason_code': reviewed_document.get('status') if isolated else None}
        rows = list(families.values())
        for row in rows:
            if row['reference_kind'] == 'ANALYSIS':
                row['legacy_references'] = [dict(other) for other in rows if other['reference_kind'] == 'LEGACY_REFERENCE'
                    and other['occurrence'] == row['occurrence'] and other['pdf_sha256'] == row['pdf_sha256']
                    and other['research_date'] == row['research_date']]
        return rows

    def list(self, *, research_date=None, undated=False, cursor=None, limit=20, occurrence_id=None):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise PublicationError('PDF_PAGE_LIMIT_INVALID')
        if (research_date is None) == (not undated) or (research_date is not None and _document_date({'source_document_date': research_date}) != research_date):
            raise PublicationError('PDF_DATE_SELECTION_REQUIRED')
        if occurrence_id is not None and not SHA.fullmatch(str(occurrence_id)):
            raise PublicationError('PDF_OCCURRENCE_INVALID')
        rows = [x for x in self._summaries() if x['research_date'] == research_date
                and (occurrence_id is None or x['occurrence']['occurrence_id'] == occurrence_id)]
        rows.sort(key=lambda x: (str((x.get('latest_generated') or {}).get('generated_at', '')), x['reference_id'], x['occurrence']['occurrence_id']), reverse=True)
        snapshot = digest(canonical_json({'date': research_date, 'undated': undated, 'occurrence': occurrence_id, 'rows': rows}))
        offset = 0
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
                offset = decoded['offset']
                if set(decoded) != {'snapshot', 'offset'} or decoded['snapshot'] != snapshot or type(offset) is not int or offset < 1 or offset >= len(rows):
                    raise ValueError()
            except (ValueError, TypeError, KeyError):
                raise PublicationError('PDF_CURSOR_INVALID_OR_STALE') from None
        next_offset = offset + limit
        next_cursor = base64.urlsafe_b64encode(canonical_json({'snapshot': snapshot, 'offset': next_offset})).decode().rstrip('=') if next_offset < len(rows) else None
        exists = self.root.exists()
        return {'schema_version': 'v4.pdf_research.list.v1', 'status': ('READY' if rows else 'READY_EMPTY') if exists else 'NOT_MATERIALIZED',
            'research_date': research_date, 'date_mode': 'UNDATED' if undated else 'EXACT', 'date_basis': 'source_document_date',
            'items': rows[offset:offset + limit], 'total_count': len(rows), 'next_cursor': next_cursor, 'snapshot_sha256': snapshot,
            'write_policy': 'read_only', 'research_only': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}

    def detail(self, reference_id, *, occurrence_id, generation=None, research_date=None, undated=False):
        if not SHA.fullmatch(str(reference_id)):
            raise PublicationError('PDF_RESULT_VERSION_INVALID')
        if (research_date is None) == (not undated) or (research_date is not None and _document_date({'source_document_date': research_date}) != research_date):
            raise PublicationError('PDF_DATE_SELECTION_REQUIRED')
        if not SHA.fullmatch(str(occurrence_id)):
            raise PublicationError('PDF_OCCURRENCE_INVALID')
        # A detail lookup must not be truncated by the public page size.
        family = next((x for x in self._summaries() if x['reference_id'] == reference_id
            and x['occurrence']['occurrence_id'] == occurrence_id and x['research_date'] == research_date), None)
        if family is None:
            raise PublicationError('PDF_OCCURRENCE_DATE_VERSION_NOT_FOUND')
        if family['reference_kind'] == 'LEGACY_REFERENCE':
            if generation is not None:
                raise PublicationError('PDF_RESULT_VERSION_INVALID')
            value = read_json(self.root / 'legacy-references' / (reference_id + '.json'), root=self.root)
            raw = read_reference(value['result_reference'])
            review_raw = read_reference(value['review_reference'])
            card = json.loads(raw)
            body = card.get('content') if isinstance(card, dict) else None
            display_card = body if isinstance(body, dict) else card
            if isinstance(body, dict):
                lines = [str(body.get('material_type', '')), str(body.get('event_or_meeting_object', ''))]
                for field, label, key in [('facts', '事实', 'claim'), ('forecasts', '来源预测', 'claim'),
                        ('risks', '风险', 'risk'), ('source_usage_limits', '用途限制', 'limitation')]:
                    if body.get(field):
                        lines.append('\n' + label)
                        for claim in body[field]:
                            pages = ' '.join('[第' + str(evidence.get('page_number', '未知')) + '页]' for evidence in claim.get('evidence', []))
                            lines.append(str(claim.get(key, '')) + ' ' + pages)
                body = '\n'.join(lines)
            if not isinstance(body, str):
                body = raw.decode('utf-8')
            if family['execution_status'] == 'ISOLATED':
                body = ''
            return {**family, 'schema_version': 'v4.pdf_research.detail.v1', 'generation': None,
                'body_markdown': body, 'body_sha256': digest(body.encode('utf-8')), 'result_sha256': digest(raw),
                'cards': [display_card], 'review': json.loads(review_raw), 'references': value,
                'write_policy': 'read_only', 'research_only': True}
        if type(generation) is not int:
            raise PublicationError('PDF_RESULT_VERSION_REQUIRED')
        version = next((x for x in family['versions'] if x['generation'] == generation), None)
        if version is None:
            raise PublicationError('PDF_OCCURRENCE_DATE_VERSION_NOT_FOUND')
        directory = PdfPublisher(self.root).version_root(reference_id, generation)
        meta = read_json(directory / 'metadata.json', root=self.root)
        raw = read_bytes(directory / 'result.json', root=self.root)
        if digest(raw) != version['result_sha256']:
            raise PublicationError('PDF_RESULT_SHA_MISMATCH')
        result = json.loads(raw)
        if any(result.get(key) != meta.get(key) for key in ('analysis_id', 'generation', 'context_id', 'metadata', 'pdf_sha256', 'protocol_sha256', 'generated_at', 'coverage', 'validation_status', 'writer_id')):
            raise PublicationError('PDF_RESULT_METADATA_BINDING_MISMATCH')
        proof = self._review(directory, meta)
        return {**family, **version, 'schema_version': 'v4.pdf_research.detail.v1', 'body_markdown': result['body_markdown'],
            'body_sha256': digest(result['body_markdown'].encode('utf-8')), 'cards': result['cards'], 'coverage': result['coverage'],
            'provenance': {key: result[key] for key in ('input_manifest', 'protocol_sha256', 'source_sha256', 'chunk_raw_sha256')},
            'review': proof, 'write_policy': 'read_only', 'research_only': True}
