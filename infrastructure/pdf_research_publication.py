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
