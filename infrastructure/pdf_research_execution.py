"""Durable single-owner PDF analysis ticks. One chunk and at most one POST per tick."""
from __future__ import annotations
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid
from typing import Any

from infrastructure import local_document_model as model
from infrastructure import pdf_research as research
from infrastructure import pdf_research_protocol as protocol
from infrastructure.pdf_research_identity import AnalysisConfiguration, SourceOccurrence, build_analysis_identity, canonical_json
from infrastructure.pdf_research_publication import (PdfPublisher, PublicationError, checked_path, digest,
    fsync_directory, owned_lock, read_bytes, read_json, read_reference, write_json)
from infrastructure.pdf_research_validation import CardValidationError, validate_protocol_card

RUN_SCHEMA = 'v4.pdf_research.run_manifest.v1'
RUN_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')
REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = ('infrastructure/pdf_research_protocol.py', 'infrastructure/pdf_research_validation.py',
    'infrastructure/pdf_research_execution.py', 'infrastructure/pdf_research_publication.py',
    'infrastructure/pdf_research_identity.py', 'infrastructure/pdf_text_preparation.py',
    'infrastructure/pdf_text_source.py', 'infrastructure/local_document_model.py', 'infrastructure/pdf_research.py',
    'infrastructure/zsxq_pdf_ingestion.py', 'ops/run_zsxq_hourly_delta.py', 'ops/run_v35_macos_scheduler_daemon.py',
    'ops/run_pdf_research_full_once.py', 'ops/run_pdf_research_batch.py', 'ops/run_pdf_research_sample.py',
    'ops/run_pdf_research_package_once.py', 'ops/run_pdf_research_remaining_once.py')
SAFETY = {'research_only': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}


class ExecutionError(RuntimeError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def integrity_failure(code, exception=None):
    # These are the same identity/source/configuration/path families which
    # already fail closed outside transport. Do not let a transport wrapper
    # downgrade them to an ordinary unusable document. Ignore model error
    # details after ':'; those are model/HTTP failures, not local identities.
    category = str(code).split(':', 1)[0]
    return (isinstance(exception, (ExecutionError, PublicationError))
        or isinstance(exception, model.LocalModelError) and not isinstance(exception, model.PdfCardTransportError)
        or category.startswith(('PINNED_', 'PDF_LOCAL_SOURCE_', 'PDF_SOURCE_OCCURRENCE_'))
        or any(marker in category for marker in ('IDENTITY', 'MODEL_ID', 'SHA', 'BINDING',
            'CONFIG', 'RUNTIME', 'PROFILE', 'OWNED_PATH', 'PATH_OUTSIDE', 'IMMUTABLE', 'MANIFEST')))


def request_key(intent):
    return {key: intent[key] for key in ('analysis_id', 'generation', 'chunk_index', 'request_sha256')}


def durable_halt_reason(events):
    halts = [event for event in events if event.get('event') == 'halt']
    if halts:
        return halts[-1]['code']
    broken = next((event for event in events
        if event.get('event') in {'attempt_outcome', 'failed', 'unknown_outcome'}
        and (event.get('integrity_failure') is True or integrity_failure(event.get('code', '')))), None)
    return broken['code'] if broken is not None else None


def dispatched_attempts(events):
    keys = [canonical_json(request_key(event)) for event in events if event.get('event') == 'request_dispatched']
    if len(keys) != len(set(keys)):
        raise ExecutionError('PDF_DUPLICATE_REQUEST_DISPATCH')
    return len(keys)


def now_utc():
    return datetime.now(timezone.utc).isoformat()


def source_manifest():
    return {name: digest(read_bytes(REPO_ROOT / name)) for name in SOURCE_FILES}


def runtime_preflight(binding):
    model.require_runtime_python()
    if tuple(sys.version_info[:3]) != (3, 12, 13):
        raise ExecutionError('PDF_RUNTIME_VERSION_MISMATCH')
    import httpx
    import psutil
    observed = model.build_request_material(protocol.SCHEMA)
    model.verify_request_material(binding, observed)
    return {'python': str(Path(sys.executable).resolve()), 'version': list(sys.version_info[:3]),
            'imports': {'model': model.__file__, 'httpx': httpx.__file__, 'psutil': psutil.__file__}}


def resources():
    import psutil
    return {'available_bytes': int(psutil.virtual_memory().available), 'swap_used_bytes': int(psutil.swap_memory().used)}


def resource_reason(sample, baseline_swap):
    if any(type(sample.get(k)) is not int or sample[k] < 0 for k in ('available_bytes', 'swap_used_bytes')):
        return 'RESOURCE_SAMPLE_CANNOT_CONFIRM'
    if sample['available_bytes'] < 8 * 1024**3:
        return 'AVAILABLE_MEMORY_BELOW_8_GIB'
    if baseline_swap is not None and sample['swap_used_bytes'] - baseline_swap > 512 * 1024**2:
        return 'SWAP_GROWTH_ABOVE_512_MIB'
    return None


def model_configuration(binding):
    return AnalysisConfiguration(model.MODEL_ID, binding['model_settings_sha256'],
        {key: binding[key] for key in ('runtime_settings_sha256', 'model_settings_sha256', 'request_temperature',
            'enable_thinking', 'runtime_limits', 'max_completion_tokens', 'request_policy')},
        protocol.SCHEMA, protocol.PROTOCOL_VERSION, protocol.PROMPT, protocol.PROTOCOL_VERSION,
        protocol.SEMANTIC_PIPELINE_VERSION)


def compile_task(spec, binding, *, validate_pdf_path=research._validate_pdf_path):
    raw = read_reference(spec['prepared_input'])
    value = json.loads(raw)
    pdf_path = validate_pdf_path(Path(spec['pdf_path']))
    sha = hashlib.sha256()
    with pdf_path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            sha.update(block)
    pdf_sha = sha.hexdigest()
    if spec['pdf_sha256'] != pdf_sha or value.get('pdf_sha256') != pdf_sha:
        raise ExecutionError('PDF_ACTUAL_SHA_MISMATCH')
    source = value.get('source', {})
    rows = value.get('pages')
    count = source.get('page_count')
    if (type(count) is not int or not isinstance(rows, list) or len(rows) != count or count < 1
            or source.get('page_extraction_status', 'COMPLETE') != 'COMPLETE'
            or source.get('all_pages_nonempty', True) is not True):
        raise ExecutionError('PDF_PREPARED_COVERAGE_INVALID')
    pages = []
    for n, row in enumerate(rows, 1):
        text = row.get('text')
        if (row.get('page_number') != n or row.get('page_total') not in (None, count)
                or not isinstance(text, str) or not text.strip()
                or row.get('status') not in {'COMPLETE', 'NATIVE_TEXT', 'OCR_OK'}
                or row.get('text_sha256') != digest(text.encode())):
            raise ExecutionError('PDF_PREPARED_PAGE_SHA_OR_COVERAGE_INVALID')
        pages.append(research.PageText(n, count, text, row['status'], row['text_sha256'], row.get('extraction_method')))
    provenance_keys = ('renderer_sha256', 'renderer_version', 'vision_source_sha256',
        'vision_config_sha256', 'slice_helper_sha256', 'slice_geometry_helper_sha256', 'render_scale_to')
    provenance = {'extractor_identity_sha256': source.get('extractor_identity_sha256'),
        'methods': [p.extraction_method for p in pages],
        'ocr': [{key: row.get('repair_provenance', row).get(key) for key in provenance_keys}
                for row in source.get('page_extraction_sources', [])]}
    # The prepared file is provenance; physical path and occurrence IDs are not
    # model inputs. The content SHA here is not a location-derived identity.
    identity = build_analysis_identity(pdf_sha256=pdf_sha, pages=pages, page_count=count,
        extraction_provenance=provenance, extraction_version='prepared-exact-page-input-v1',
        model_visible_metadata=spec['metadata'], configuration=model_configuration(binding))
    if spec.get('analysis_id') not in (None, identity.analysis_id):
        raise ExecutionError('PDF_ANALYSIS_INPUT_IDENTITY_MISMATCH')
    metadata = identity.manifest['model_visible_metadata']
    occurrences = []
    for occurrence in spec['occurrences']:
        SourceOccurrence(occurrence['namespace'], occurrence['original_source_id'])
        visible = dict(occurrence.get('model_visible_metadata', spec['metadata']))
        visible.setdefault('source_document_date', None)
        visible.setdefault('archived_date', None)
        if visible != metadata:
            raise ExecutionError('PDF_OCCURRENCE_CONTEXT_MISMATCH')
        occurrences.append({**occurrence, 'model_visible_metadata': visible})
    if not occurrences:
        raise ExecutionError('PDF_SOURCE_OCCURRENCE_REQUIRED')
    spans = protocol.evidence_spans(pages)
    groups = protocol.chunk_spans(spans, metadata)
    chunks = [{'sha256': digest(canonical_json([x.evidence_id for x in group])),
               'evidence_ids': [x.evidence_id for x in group]} for group in groups]
    task = {**spec, 'analysis_id': identity.analysis_id, 'context_id': identity.analysis_id,
            'input_manifest': identity.manifest, 'metadata': metadata, 'occurrences': occurrences,
            'page_count': count, 'chunks': chunks}
    return task, pages, groups


def freeze_run(*, run_id, tasks, model_binding, authority, generation=0, paused=False,
               validate_pdf_path=research._validate_pdf_path):
    if not RUN_ID.fullmatch(str(run_id)) or type(generation) is not int or generation < 0:
        raise ExecutionError('PDF_RUN_ID_OR_GENERATION_INVALID')
    compiled = [compile_task(x, model_binding, validate_pdf_path=validate_pdf_path)[0] for x in tasks]
    if not compiled:
        raise ExecutionError('PDF_RUN_EMPTY_ANALYSIS')
    unique = {}
    for task in compiled:
        if task['analysis_id'] not in unique:
            unique[task['analysis_id']] = task
        else:
            target = unique[task['analysis_id']]
            for occurrence in task['occurrences']:
                if occurrence not in target['occurrences']:
                    target['occurrences'].append(occurrence)
    compiled = list(unique.values())
    authority_value = json.loads(read_reference(authority['reference']))
    if authority.get('caller_id') != authority_value.get('caller_id'):
        raise ExecutionError('PDF_CALLER_AUTHORITY_MISMATCH')
    return {'schema': RUN_SCHEMA, 'run_id': run_id, 'generation': generation, 'paused': bool(paused),
        'tasks': compiled, 'model_binding': dict(model_binding), 'authority': dict(authority),
        'protocol_sha256': protocol.PROTOCOL_SHA256, 'source_sha256': source_manifest(),
        'runtime_python': str(model.RUNTIME_PYTHON.resolve()), **SAFETY}


def read_run(reference):
    value = json.loads(read_reference(reference))
    if (value.get('schema') != RUN_SCHEMA or not RUN_ID.fullmatch(str(value.get('run_id', '')))
            or type(value.get('generation')) is not int or value['generation'] < 0
            or value.get('protocol_sha256') != protocol.PROTOCOL_SHA256
            or value.get('source_sha256') != source_manifest()
            or value.get('runtime_python') != str(model.RUNTIME_PYTHON.resolve())
            or any(value.get(k) != v for k, v in SAFETY.items())):
        raise ExecutionError('PDF_RUN_INPUT_SOURCE_OR_CONFIG_DRIFT')
    return value


class Journal:
    def __init__(self, root, path):
        self.root, self.path = root, checked_path(root, path)
        self.events = self.read()

    def read(self):
        checked_path(self.root, self.path)
        if not self.path.exists():
            return []
        raw = read_bytes(self.path, root=self.root)
        if raw and not raw.endswith(b'\n'):
            raise ExecutionError('PDF_JOURNAL_TRUNCATED')
        result = []
        previous = None
        for n, line in enumerate(raw.splitlines()):
            try:
                event = json.loads(line)
            except ValueError:
                raise ExecutionError('PDF_JOURNAL_INVALID') from None
            claimed = event.pop('sha256', None)
            if event.get('sequence') != n or event.get('previous') != previous or digest(canonical_json(event)) != claimed:
                raise ExecutionError('PDF_JOURNAL_HASH_CHAIN_INVALID')
            event['sha256'] = claimed
            result.append(event)
            previous = claimed
        return result

    def append(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        checked_path(self.root, self.path)
        event = {'at': now_utc(), **value, 'sequence': len(self.events),
                 'previous': self.events[-1]['sha256'] if self.events else None}
        event['sha256'] = digest(canonical_json(event))
        fd = os.open(self.path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            raw = memoryview(canonical_json(event) + b'\n')
            while raw:
                raw = raw[os.write(fd, raw):]
            os.fsync(fd)
        finally:
            os.close(fd)
        fsync_directory(self.path.parent)
        self.events.append(event)
        return event

    def outcome(self, intent):
        key = request_key(intent)
        found = [event for event in self.events if event.get('event') == 'attempt_outcome'
            and all(event.get(name) == key[name] for name in ('analysis_id', 'generation', 'chunk_index'))]
        if len(found) > 1:
            raise ExecutionError('PDF_DUPLICATE_ATTEMPT_OUTCOME')
        if found and found[0].get('request_sha256') != key['request_sha256']:
            raise ExecutionError('PDF_ATTEMPT_REQUEST_BINDING_MISMATCH')
        return found[0] if found else None

    def record_outcome(self, intent, *, reuse_verified=False, **fields):
        value = {'event': 'attempt_outcome', **request_key(intent), **fields}
        prior = self.outcome(intent)
        if prior is not None:
            actual = {key: item for key, item in prior.items() if key not in {'at', 'sequence', 'previous', 'sha256'}}
            if actual != value:
                raise ExecutionError('PDF_ATTEMPT_OUTCOME_CONFLICT')
            return prior
        # No matching dispatch is not proof of a foreign request. A caller
        # must have verified its origin, or the exact local durable intent.
        if not any(event.get('event') == 'request_dispatched'
                and all(event.get(key) == item for key, item in request_key(intent).items()) for event in self.events):
            local = [event for event in self.events if event.get('event') == 'intent'
                and all(event.get(key) == item for key, item in request_key(intent).items())]
            if not reuse_verified and (len(local) != 1 or canonical_json({key: item for key, item in local[0].items()
                    if key not in {'event', 'sequence', 'previous', 'sha256'}}) != canonical_json(intent)):
                raise ExecutionError('PDF_REQUEST_ORIGIN_UNPROVEN')
            return None
        return self.append(value)


def breaker_reason(events):
    attempts = [e for e in events if e.get('event') == 'attempt_outcome']
    if len(attempts) >= 3 and all(not x['usable'] for x in attempts[-3:]):
        return 'THREE_CONSECUTIVE_UNUSABLE_ATTEMPTS'
    if sum(x.get('content_failure') is True for x in attempts[-10:]) >= 3:
        return 'THREE_CONTENT_FAILURES_IN_LAST_TEN'
    return None


class PdfExecutor:
    def __init__(self, research_root=research.PDF_RESEARCH_STATE_ROOT, *, transport=model.request_pdf_card,
                 preflight=runtime_preflight, resource_probe=resources, priority_reader=None,
                 shared_lock=research.GLOBAL_MODEL_LOCK_PATH, validate_pdf_path=research._validate_pdf_path,
                 crash=None):
        self.root = checked_path(Path(research_root), Path(research_root))
        self.publisher = PdfPublisher(self.root)
        self.transport, self.preflight = transport, preflight
        self.resource_probe, self.priority_reader = resource_probe, priority_reader or model.pdf_priority_snapshot
        self.shared_lock, self.validate_pdf_path = Path(shared_lock), validate_pdf_path
        self.crash = crash or (lambda _point: None)

    def enqueue(self, reference):
        run = read_run(reference)
        run_root = self.root / 'analysis-runs' / run['run_id']
        with owned_lock(self.root, run_root / 'owner.lock'):
            write_json(self.root, run_root / 'manifest.json', run)
            write_json(self.root, self.root / 'analysis-queue' / (run['run_id'] + '.json'),
                {'run_id': run['run_id'], 'reference': dict(reference)})
        return run['run_id']

    def _progress(self, run_root, kind, **fields):
        # Only called on real persistence transitions or model tokens.
        path = run_root / 'progress.json'
        prior = read_json(path, root=self.root) if path.exists() else {'sequence': 0}
        value = {'sequence': prior['sequence'] + 1, 'at': now_utc(), 'kind': kind, **fields}
        write_json(self.root, path, value, immutable=False)

    def status(self, run_id, *, daemon_running=False):
        if not RUN_ID.fullmatch(str(run_id)):
            raise ExecutionError('PDF_RUN_ID_INVALID')
        run_root = self.root / 'analysis-runs' / run_id
        manifest_path = run_root / 'manifest.json'
        if not manifest_path.exists():
            return {'status': 'NOT_ENQUEUED', 'pending': 0, **SAFETY}
        run = read_json(manifest_path, root=self.root)
        journal = Journal(self.root, run_root / 'journal.jsonl')
        done = {e['analysis_id'] for e in journal.events if e.get('event') in {'generated', 'failed', 'isolated', 'unknown_outcome'}}
        last = journal.events[-1] if journal.events else {}
        pending = len(run['tasks']) - len(done)
        status = 'PAUSED' if run['paused'] else 'ALL_TASKS_TERMINAL' if not pending else 'WAITING_TICK' if daemon_running else 'WAITING_HOST_TICK'
        halt = run_root / 'halt.json'
        reason = durable_halt_reason(journal.events)
        if reason is not None:
            status = 'HALTED'
            last = {'event': 'halt', 'code': reason}
        elif halt.exists():
            status = 'HALTED'
            last = read_json(halt, root=self.root)
        return {'status': status, 'pending': pending, 'completed': len(done), 'last_error': last.get('code'),
            'last_event': last.get('event'), 'attempts': dispatched_attempts(journal.events),
            'outcomes': sum(e.get('event') == 'attempt_outcome' for e in journal.events),
            'generated': sum(e.get('event') == 'generated' for e in journal.events),
            'failed': sum(e.get('event') == 'failed' for e in journal.events),
            'isolated': sum(e.get('event') == 'isolated' for e in journal.events), 'model_posts': 0, **SAFETY}

    def _halt(self, run_root, journal, code, *, posts=0):
        value = {'event': 'halt', 'code': code}
        journal.append(value)
        write_json(self.root, run_root / 'halt.json', value)
        return {'status': 'HALTED', 'code': code, 'model_posts': posts, **SAFETY}

    @contextmanager
    def _run_owner(self, run_root):
        with owned_lock(self.root, run_root / 'owner.lock'):
            try:
                yield
            finally:
                path = run_root / 'journal.jsonl'
                if path.exists():
                    events = Journal(self.root, path).events
                    terminals = [x for x in events if x.get('event') in {'generated', 'failed', 'isolated', 'unknown_outcome'}]
                    for count in range(20, len(terminals) + 1, 20):
                        terminal = terminals[count - 1]
                        prefix = events[:terminal['sequence'] + 1]
                        value = {'terminal_count': count, 'journal_sha256': terminal['sha256'],
                            'attempts': dispatched_attempts(prefix),
                            'outcomes': sum(x.get('event') == 'attempt_outcome' for x in prefix),
                            'generated': sum(x.get('event') == 'generated' for x in prefix),
                            'failed': sum(x.get('event') == 'failed' for x in prefix),
                            'isolated': sum(x.get('event') == 'isolated' for x in prefix),
                            'unknown_outcome': sum(x.get('event') == 'unknown_outcome' for x in prefix),
                            'accepted': 'REQUIRES_BOUND_CONTENT_REVIEW', 'pending_review': sum(x.get('event') == 'generated' for x in prefix)}
                        write_json(self.root, run_root / 'checkpoints' / f'{count:06d}.json', value)

    def tick(self, reference):
        run = read_run(reference)
        run_root = self.root / 'analysis-runs' / run['run_id']
        try:
            with self._run_owner(run_root):
                write_json(self.root, run_root / 'manifest.json', run)
                journal = Journal(self.root, run_root / 'journal.jsonl')
                if not journal.events:
                    journal.append({'event': 'binding', 'run_manifest_sha256': reference['sha256']})
                if journal.events[0].get('run_manifest_sha256') != reference['sha256']:
                    raise ExecutionError('PDF_RUN_MANIFEST_BINDING_MISMATCH')
                # Stop decisions come from durable journal evidence, including
                # zero-dispatch terminals, not completion of a status file.
                halts = [event for event in journal.events if event.get('event') == 'halt']
                if halts and not (run_root / 'halt.json').exists():
                    write_json(self.root, run_root / 'halt.json', {'event': 'halt', 'code': halts[-1]['code']})
                if (run_root / 'halt.json').exists():
                    return self.status(run['run_id'])
                broken = durable_halt_reason(journal.events)
                if broken is not None:
                    return self._halt(run_root, journal, broken)
                reason = breaker_reason(journal.events)
                if reason:
                    return self._halt(run_root, journal, reason)
                if run['paused']:
                    return {'status': 'PAUSED', 'model_posts': 0, **SAFETY}
                done = {e['analysis_id'] for e in journal.events if e.get('event') in {'generated', 'failed', 'isolated', 'unknown_outcome'}}
                for spec in run['tasks']:
                    if spec['analysis_id'] in done:
                        continue
                    if spec.get('source_invalid') is True:
                        journal.append({'event': 'isolated', 'analysis_id': spec['analysis_id'], 'code': 'SOURCE_PREISOLATED', 'attempts': 0})
                        continue
                    dispatched_before = dispatched_attempts(journal.events)
                    try:
                        task, pages, groups = compile_task(spec, run['model_binding'], validate_pdf_path=self.validate_pdf_path)
                        if task != spec:
                            raise ExecutionError('PDF_FROZEN_TASK_MANIFEST_DRIFT')
                        with owned_lock(self.root, self.root / 'analysis-execution' / task['analysis_id'] / 'owner.lock'):
                            return self._advance(run, reference, task, pages, groups, run_root, journal)
                    except PublicationError as exc:
                        if exc.code == 'PDF_OWNER_BUSY':
                            return {'status': 'OWNER_BUSY',
                                'model_posts': dispatched_attempts(journal.events) - dispatched_before, **SAFETY}
                        return self._halt(run_root, journal, exc.code,
                            posts=dispatched_attempts(journal.events) - dispatched_before)
                    except (ExecutionError, model.LocalModelError, ValueError, OSError) as exc:
                        return self._halt(run_root, journal, str(exc),
                            posts=dispatched_attempts(journal.events) - dispatched_before)
                return self.status(run['run_id'])
        except PublicationError as exc:
            if exc.code == 'PDF_OWNER_BUSY':
                return {'status': 'OWNER_BUSY', 'model_posts': 0, **SAFETY}
            raise

    def _verify_saved_request(self, run, reference, task, index, spans, chunk_root, journal):
        intent_path, raw_path = chunk_root / 'intent.json', chunk_root / 'raw.json'
        intent = read_json(intent_path, root=self.root)
        envelope = protocol.request_envelope(protocol.request_messages(spans, task['metadata']))
        expected = {'analysis_id': task['analysis_id'], 'generation': run['generation'], 'chunk_index': index,
            'chunk_sha256': task['chunks'][index - 1]['sha256'], 'request_sha256': digest(canonical_json(envelope)),
            'schema_sha256': digest(canonical_json(protocol.SCHEMA))}
        if (canonical_json({key: intent.get(key) for key in expected}) != canonical_json(expected)
                or digest(canonical_json(read_json(chunk_root / 'request.json', root=self.root))) != expected['request_sha256']):
            raise ExecutionError('PDF_REQUEST_INTENT_BINDING_MISMATCH')
        origin_reference = intent.get('run_manifest_reference')
        origin = read_run(origin_reference)
        if (intent.get('run_id') != origin['run_id'] or origin['generation'] != run['generation']
                or intent.get('writer_id') != origin['authority']['caller_id']):
            raise ExecutionError('PDF_REQUEST_ORIGIN_BINDING_MISMATCH')
        origin_root = self.root / 'analysis-runs' / origin['run_id']
        if canonical_json(read_json(origin_root / 'manifest.json', root=self.root)) != canonical_json(origin):
            raise ExecutionError('PDF_ORIGIN_RUN_MANIFEST_MISMATCH')
        original_tasks = [item for item in origin['tasks'] if item['analysis_id'] == task['analysis_id']]
        if (len(original_tasks) != 1 or original_tasks[0]['input_manifest'] != task['input_manifest']
                or original_tasks[0]['context_id'] != task['context_id'] or original_tasks[0]['chunks'] != task['chunks']):
            raise ExecutionError('PDF_REQUEST_ORIGIN_CONTEXT_MISMATCH')
        foreign = origin['run_id'] != run['run_id']
        if foreign:
            original_task, _, _ = compile_task(original_tasks[0], origin['model_binding'], validate_pdf_path=self.validate_pdf_path)
            if original_task != original_tasks[0]:
                raise ExecutionError('PDF_ORIGIN_FROZEN_TASK_DRIFT')
            origin_journal = Journal(self.root, origin_root / 'journal.jsonl')
            if any(event.get('event') in {'intent', 'request_dispatched', 'attempt_outcome'}
                    and event.get('analysis_id') == task['analysis_id'] and event.get('chunk_index') == index
                    for event in journal.events):
                raise ExecutionError('PDF_CURRENT_RUN_REQUEST_ORIGIN_CONFLICT')
        else:
            origin_journal = journal
            if origin_reference['sha256'] != reference['sha256']:
                raise ExecutionError('PDF_CURRENT_RUN_MANIFEST_BINDING_MISMATCH')
        if (not origin_journal.events
                or origin_journal.events[0].get('run_manifest_sha256') != origin_reference['sha256']):
            raise ExecutionError('PDF_ORIGIN_JOURNAL_BINDING_MISMATCH')
        original_intents = [event for event in origin_journal.events if event.get('event') == 'intent'
            and event.get('analysis_id') == task['analysis_id'] and event.get('chunk_index') == index]
        if (len(original_intents) != 1 or canonical_json({key: item for key, item in original_intents[0].items()
                if key not in {'event', 'sequence', 'previous', 'sha256'}}) != canonical_json(intent)):
            raise ExecutionError('PDF_DURABLE_INTENT_BINDING_MISMATCH')
        intent_sha = digest(read_bytes(intent_path, root=self.root))
        dispatches = [event for event in origin_journal.events if event.get('event') == 'request_dispatched'
            and event.get('analysis_id') == task['analysis_id'] and event.get('chunk_index') == index]
        dispatch_binding = {**request_key(intent), 'run_id': origin['run_id'],
            'run_manifest_sha256': origin_reference['sha256'], 'intent_sha256': intent_sha}
        if len(dispatches) > 1 or any(canonical_json({key: event.get(key) for key in dispatch_binding})
                != canonical_json(dispatch_binding) for event in dispatches):
            raise ExecutionError('PDF_DISPATCH_INTENT_BINDING_MISMATCH')
        if not raw_path.exists():
            return intent, None, foreign
        raw = read_json(raw_path, root=self.root)
        raw_binding = {**request_key(intent), 'chunk_sha256': expected['chunk_sha256'],
            'run_id': origin['run_id'], 'run_manifest_sha256': origin_reference['sha256'], 'intent_sha256': intent_sha}
        receipts = [event for event in origin_journal.events if event.get('event') == 'raw_durable'
            and event.get('analysis_id') == task['analysis_id'] and event.get('chunk_index') == index]
        if (len(dispatches) != 1 or len(receipts) != 1
                or canonical_json({key: raw.get(key) for key in raw_binding}) != canonical_json(raw_binding)
                or receipts[0].get('raw_artifact_sha256') != digest(read_bytes(raw_path, root=self.root))
                or canonical_json({key: receipts[0].get(key) for key in request_key(intent)}) != canonical_json(request_key(intent))
                or raw.get('stream_sha256') != digest(read_bytes(chunk_root / 'raw-stream.sse', root=self.root))
                or not isinstance(raw.get('text'), str) or digest(raw['text'].encode()) != raw.get('text_sha256')):
            raise ExecutionError('PDF_RAW_REQUEST_BINDING_MISMATCH')
        if any(event.get('analysis_id') == task['analysis_id'] and event.get('chunk_index') == index
                and event.get('event') in {'attempt_outcome', 'failed', 'unknown_outcome'}
                and (event.get('integrity_failure') is True or integrity_failure(event.get('code', '')))
                for event in origin_journal.events):
            raise ExecutionError('PDF_ORIGIN_REQUEST_HALTED')
        return intent, raw, foreign

    def _advance(self, run, reference, task, pages, groups, run_root, journal):
        aid, generation = task['analysis_id'], run['generation']
        execution_root = self.root / 'analysis-execution' / aid / f'g{generation:06d}'
        binding_path = execution_root / 'binding.json'
        binding = {'analysis_id': aid, 'generation': generation, 'input_manifest': task['input_manifest'],
                   'protocol_sha256': protocol.PROTOCOL_SHA256, 'source_sha256': run['source_sha256']}
        write_json(self.root, binding_path, binding)
        write_json(self.root, execution_root / 'claim.json', {'owner_pid': os.getpid(), 'owner_token': uuid.uuid4().hex,
            'analysis_id': aid, 'generation': generation, 'run_id': run['run_id']}, immutable=False)
        completed = []
        content_failed = []
        writer_id = None
        posts = 0
        for index, spans in enumerate(groups, 1):
            chunk_root = execution_root / 'chunks' / f'{index:04d}'
            raw_path, intent_path = chunk_root / 'raw.json', chunk_root / 'intent.json'
            intent, raw, foreign = None, None, False
            if intent_path.exists() or raw_path.exists():
                intent, raw, foreign = self._verify_saved_request(run, reference, task, index, spans, chunk_root, journal)
                if index == 1:
                    writer_id = intent['writer_id']
            validated = self.publisher.read_chunk(aid, generation, index)
            if validated is not None:
                prior = [x for x in journal.events if x.get('event') == 'chunk_validated'
                         and x.get('analysis_id') == aid and x.get('chunk_index') == index]
                if prior and prior[-1].get('published_chunk_sha256') != digest(canonical_json(validated) + b'\n'):
                    raise ExecutionError('PDF_VALIDATED_CHUNK_SHA_MISMATCH')
                if not prior:
                    validated = None
            if validated is not None:
                if validated['chunk_sha256'] != task['chunks'][index - 1]['sha256'] or not raw_path.exists():
                    raise ExecutionError('PDF_COMPLETED_CHUNK_INPUT_MISMATCH')
                if canonical_json({key: validated.get(key) for key in ('analysis_id', 'generation', 'chunk_index')}) != canonical_json(
                        {key: intent[key] for key in ('analysis_id', 'generation', 'chunk_index')}):
                    raise ExecutionError('PDF_COMPLETED_CHUNK_INPUT_MISMATCH')
                if digest(raw['text'].encode()) != raw['text_sha256'] or raw['text_sha256'] != validated['raw_sha256']:
                    raise ExecutionError('PDF_COMPLETED_RAW_SHA_MISMATCH')
                completed.append(validated)
                continue
            if intent_path.exists() and not raw_path.exists():
                prior_outcome = journal.outcome(intent)
                if prior_outcome is not None:
                    if prior_outcome.get('terminal_event') not in {'failed', 'unknown_outcome'}:
                        raise ExecutionError('PDF_ATTEMPT_OUTCOME_WITHOUT_RAW')
                    journal.append({'event': prior_outcome['terminal_event'], **request_key(intent), 'code': prior_outcome['code'],
                        'integrity_failure': prior_outcome.get('integrity_failure', False)})
                    return {'status': 'FAILED' if prior_outcome['terminal_event'] == 'failed' else 'CANNOT_CONFIRM',
                        'code': prior_outcome['code'], 'model_posts': 0, **SAFETY}
                journal.record_outcome(intent, reuse_verified=foreign, usable=False, content_failure=False,
                    terminal_event='unknown_outcome', code='CANNOT_CONFIRM_PRIOR_REQUEST_OUTCOME', integrity_failure=False)
                journal.append({'event': 'unknown_outcome', 'analysis_id': aid, 'chunk_index': index,
                    'code': 'CANNOT_CONFIRM_PRIOR_REQUEST_OUTCOME', 'repost_allowed': False})
                return {'status': 'CANNOT_CONFIRM', 'code': 'CANNOT_CONFIRM_PRIOR_REQUEST_OUTCOME', 'model_posts': 0, **SAFETY}
            if not raw_path.exists():
                authority = run['authority']
                authority_value = json.loads(read_reference(authority['reference']))
                if (authority_value.get('model_posts_allowed') is not True or aid not in authority_value.get('analysis_ids', [])
                        or generation not in authority_value.get('generations', []) or authority.get('caller_id') != authority_value.get('caller_id')):
                    journal.append({'event': 'deferred', 'analysis_id': aid, 'code': 'MODEL_POST_NOT_AUTHORIZED', 'attempts': 0})
                    return {'status': 'DEFERRED', 'code': 'MODEL_POST_NOT_AUTHORIZED', 'model_posts': 0, **SAFETY}
                try:
                    sample = self.resource_probe()
                except Exception:
                    journal.append({'event': 'deferred', 'analysis_id': aid, 'code': 'RESOURCE_SAMPLE_CANNOT_CONFIRM', 'attempts': 0})
                    return {'status': 'DEFERRED', 'code': 'RESOURCE_SAMPLE_CANNOT_CONFIRM', 'model_posts': 0, **SAFETY}
                baseline_path = run_root / 'resource-baseline.json'
                if baseline_path.exists():
                    baseline = read_json(baseline_path, root=self.root)
                else:
                    baseline = sample
                    write_json(self.root, baseline_path, baseline)
                reason = resource_reason(sample, baseline.get('swap_used_bytes'))
                priority = self.priority_reader()
                if reason or priority.get('status') != 'ALLOW':
                    reason = reason or priority.get('reason') or 'ANNOUNCEMENT_PRIORITY_DEFER'
                    journal.append({'event': 'deferred', 'analysis_id': aid, 'code': reason, 'attempts': 0})
                    return {'status': 'DEFERRED', 'code': reason, 'model_posts': 0, **SAFETY}
                if (type(authority_value.get('max_posts')) is not int or
                        sum(e.get('event') == 'request_dispatched' for e in journal.events) >= authority_value['max_posts']):
                    return self._halt(run_root, journal, 'PDF_AUTHORIZED_POST_BUDGET_EXHAUSTED')
                runtime = self.preflight(run['model_binding'])
                messages = protocol.request_messages(spans, task['metadata'])
                envelope = protocol.request_envelope(messages)
                if self.shared_lock == research.GLOBAL_MODEL_LOCK_PATH and not self.shared_lock.is_file():
                    raise ExecutionError('PDF_SHARED_MODEL_LOCK_UNAVAILABLE')
                with owned_lock(self.shared_lock.parent, self.shared_lock):
                    intent = {'analysis_id': aid, 'generation': generation, 'chunk_index': index,
                        'chunk_sha256': task['chunks'][index - 1]['sha256'], 'request_sha256': digest(canonical_json(envelope)),
                        'schema_sha256': digest(canonical_json(protocol.SCHEMA)), 'runtime': runtime,
                        'writer_id': run['authority']['caller_id'], 'at': now_utc(),
                        'run_id': run['run_id'], 'run_manifest_reference': dict(reference)}
                    write_json(self.root, chunk_root / 'request.json', envelope)
                    intent_sha = write_json(self.root, intent_path, intent)
                    journal.append({'event': 'intent', **intent})
                    self._progress(run_root, 'intent', analysis_id=aid, chunk_index=index)
                    self.crash('after_intent')
                    stream_path = checked_path(self.root, chunk_root / 'raw-stream.sse')
                    def on_raw(block):
                        fd = os.open(stream_path, os.O_CREAT | os.O_APPEND | os.O_WRONLY | getattr(os, 'O_NOFOLLOW', 0), 0o600)
                        try:
                            view = memoryview(block)
                            while view:
                                view = view[os.write(fd, view):]
                            os.fsync(fd)
                        finally:
                            os.close(fd)
                    def on_dispatch():
                        nonlocal posts
                        if posts:
                            raise ExecutionError('PDF_DUPLICATE_REQUEST_DISPATCH')
                        journal.append({'event': 'request_dispatched', **request_key(intent), 'run_id': run['run_id'],
                            'run_manifest_sha256': reference['sha256'], 'intent_sha256': intent_sha})
                        posts = 1
                    try:
                        text = self.transport(messages=messages, schema=protocol.SCHEMA,
                            expected_binding=run['model_binding'], on_raw=on_raw,
                            on_progress=lambda event: self._progress(run_root, event['kind'], **{k: v for k, v in event.items() if k != 'kind'}),
                            on_dispatch=on_dispatch)
                    except Exception as exc:
                        code = getattr(exc, 'code', type(exc).__name__)
                        known = getattr(exc, 'outcome_known', False)
                        broken = integrity_failure(code, exc)
                        terminal_event = 'failed' if known else 'unknown_outcome'
                        journal.record_outcome(intent, usable=False, content_failure=False, code=code,
                            terminal_event=terminal_event, integrity_failure=broken)
                        journal.append({'event': terminal_event, **request_key(intent), 'code': code, 'integrity_failure': broken})
                        if broken:
                            return self._halt(run_root, journal, code, posts=posts)
                        reason = breaker_reason(journal.events)
                        if reason:
                            return self._halt(run_root, journal, reason, posts=posts)
                        return {'status': 'FAILED' if known else 'CANNOT_CONFIRM', 'code': code, 'model_posts': posts, **SAFETY}
                    raw = {'analysis_id': aid, 'generation': generation, 'chunk_index': index,
                        'chunk_sha256': task['chunks'][index - 1]['sha256'], 'request_sha256': intent['request_sha256'],
                        'text': text, 'text_sha256': digest(text.encode()), 'received_at': now_utc(),
                        'run_id': run['run_id'], 'run_manifest_sha256': reference['sha256'], 'intent_sha256': intent_sha,
                        'stream_sha256': digest(read_bytes(stream_path, root=self.root))}
                    raw_sha = write_json(self.root, raw_path, raw)
                    journal.append({'event': 'raw_durable', **request_key(intent), 'raw_artifact_sha256': raw_sha})
                    self._progress(run_root, 'raw_durable', analysis_id=aid, chunk_index=index)
                    self.crash('after_raw')
            intent, raw, foreign = self._verify_saved_request(run, reference, task, index, spans, chunk_root, journal)
            if index == 1:
                writer_id = intent['writer_id']
            try:
                value = validate_protocol_card(raw['text'], spans, pages)
            except CardValidationError as exc:
                if protocol.PROTOCOL_VERSION == 'pdf-claims-source-v2':
                    from infrastructure import pdf_research_claims as claims
                    # All unlisted exceptions are input/integrity/unknown failures.
                    # Never infer continuation from the exception type or its name.
                    if exc.code not in claims.CONTENT_ERRORS:
                        journal.record_outcome(intent, reuse_verified=foreign, usable=False,
                            content_failure=False, code=exc.code, terminal_event='failed',
                            raw_sha256=raw['text_sha256'], integrity_failure=True)
                        return self._halt(run_root, journal, exc.code, posts=posts)
                    failure = {'analysis_id': aid, 'generation': generation, 'chunk_index': index,
                        'raw_sha256': raw['text_sha256'], 'code': exc.code,
                        'semantic_acceptance': 'NOT_GRANTED', **SAFETY}
                    failure_sha = write_json(self.root, chunk_root / 'content-failure.json', failure)
                    journal.record_outcome(intent, reuse_verified=foreign, usable=False,
                        content_failure=True, code=exc.code, terminal_event='chunk_content_failed',
                        raw_sha256=raw['text_sha256'], integrity_failure=False)
                    previous = [event for event in journal.events if event.get('event') == 'chunk_content_failed'
                        and all(event.get(key) == val for key, val in request_key(intent).items())]
                    if previous:
                        if len(previous) != 1 or previous[0].get('failure_sha256') != failure_sha:
                            raise ExecutionError('PDF_CLAIMS_CONTENT_FAILURE_BINDING_MISMATCH')
                    else:
                        journal.append({'event': 'chunk_content_failed', **request_key(intent),
                            'code': exc.code, 'failure_sha256': failure_sha})
                    content_failed.append(failure)
                    reason = breaker_reason(journal.events)
                    if reason:
                        return self._halt(run_root, journal, reason, posts=posts)
                    if index != len(groups) and posts:
                        return {'status': 'PARTIAL_CHUNKS_CONTENT_FAILED', 'analysis_id': aid,
                            'completed_chunks': index, 'total_chunks': len(groups),
                            'code': exc.code, 'model_posts': posts, **SAFETY}
                    continue
                broken = integrity_failure(exc.code)
                journal.record_outcome(intent, reuse_verified=foreign, usable=False, content_failure=not broken, code=exc.code,
                    terminal_event='failed', raw_sha256=raw['text_sha256'], integrity_failure=broken)
                journal.append({'event': 'failed', **request_key(intent), 'code': exc.code, 'raw_sha256': raw['text_sha256'], 'integrity_failure': broken})
                if broken:
                    return self._halt(run_root, journal, exc.code, posts=posts)
                reason = breaker_reason(journal.events)
                if reason:
                    return self._halt(run_root, journal, reason, posts=posts)
                return {'status': 'CONTENT_FAILED', 'code': exc.code, 'model_posts': posts, **SAFETY}
            validated = {'analysis_id': aid, 'generation': generation, 'chunk_index': index,
                'chunk_sha256': task['chunks'][index - 1]['sha256'], 'raw_sha256': raw['text_sha256'],
                'received_at': raw['received_at'], 'validated': value, 'deterministic_status': 'PASS'}
            published_chunk_sha = self.publisher.record_chunk(aid, generation, index, validated)
            journal.record_outcome(intent, reuse_verified=foreign, usable=True, content_failure=False,
                terminal_event='chunk_validated', raw_sha256=raw['text_sha256'],
                published_chunk_sha256=published_chunk_sha, integrity_failure=False)
            journal.append({'event': 'chunk_validated', 'analysis_id': aid, 'chunk_index': index, 'raw_sha256': raw['text_sha256'], 'published_chunk_sha256': published_chunk_sha})
            self._progress(run_root, 'chunk_validated', analysis_id=aid, chunk_index=index)
            completed.append(validated)
            if index != len(groups):
                return {'status': 'PARTIAL_CHUNKS_COMPLETE', 'analysis_id': aid, 'completed_chunks': index,
                    'total_chunks': len(groups), 'model_posts': posts, **SAFETY}
        if content_failed:
            journal.append({'event': 'failed', 'analysis_id': aid, 'generation': generation,
                'code': 'PDF_CLAIMS_COMPLETED_WITH_CONTENT_FAILURES',
                'content_failed_chunks': [item['chunk_index'] for item in content_failed]})
            return {'status': 'CONTENT_FAILED', 'analysis_id': aid,
                'code': 'PDF_CLAIMS_COMPLETED_WITH_CONTENT_FAILURES',
                'content_failed_chunks': [item['chunk_index'] for item in content_failed],
                'completed_chunks': len(groups), 'total_chunks': len(groups), 'model_posts': posts, **SAFETY}
        meta = self.publisher.publish(task, generation, completed,
            generated_at=completed[-1]['received_at'],
            writer_id=writer_id,
            source_sha256=run['source_sha256'], crash=self.crash)
        journal.append({'event': 'generated', 'analysis_id': aid, 'generation': generation, 'result_sha256': meta['result_sha256']})
        self._progress(run_root, 'published', analysis_id=aid)
        return {'status': 'GENERATED_PENDING_REVIEW', 'analysis_id': aid, 'generation': generation,
                'result_sha256': meta['result_sha256'], 'model_posts': posts, **SAFETY}


def next_analysis_task(research_root=research.PDF_RESEARCH_STATE_ROOT):
    """Read-only queue selection; a stopped host leaves a durable waiting item."""
    executor = PdfExecutor(research_root)
    for path in sorted((Path(research_root) / 'analysis-queue').glob('*.json')):
        item = read_json(path, root=Path(research_root))
        run = read_run(item['reference'])
        if item['run_id'] != run['run_id']:
            raise ExecutionError('PDF_QUEUED_RUN_BINDING_MISMATCH')
        status = executor.status(run['run_id'], daemon_running=True)
        if status['pending'] and status['status'] not in {'HALTED', 'PAUSED'}:
            return {**item, 'task_type': 'ANALYSIS', 'progress_path': str(Path(research_root) / 'analysis-runs' / run['run_id'] / 'progress.json')}
    return None


def dispatch_analysis_tick(reference, *, research_root=research.PDF_RESEARCH_STATE_ROOT, run_child=None):
    """API/scheduler host delegates computation to the verified existing Qwen Python."""
    import subprocess
    run = read_run(reference)
    command = [str(model.RUNTIME_PYTHON), '-B', '-m', 'infrastructure.pdf_research_execution',
        '--run-manifest', reference['path'], '--run-manifest-sha256', reference['sha256'],
        '--research-root', str(research_root), '--execute', '--worker']
    env = dict(os.environ)
    env.update(PYTHONNOUSERSITE='1', PYTHONPATH=str(REPO_ROOT),
        PRODUCTION_ALLOWED='false', BUY_GATE_UPDATED='false', ORDERS_SENT='false')
    process = (run_child or subprocess.run)(command, cwd=str(REPO_ROOT), env=env,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if process.returncode != 0:
        return {'status': 'CANNOT_CONFIRM', 'task_type': 'ANALYSIS', 'run_id': run['run_id'],
            'code': 'PDF_ANALYSIS_CHILD_FAILED', 'return_code': process.returncode, 'model_posts': None,
            'runtime_python': str(model.RUNTIME_PYTHON), **SAFETY}
    try:
        result = json.loads(process.stdout)
    except (ValueError, UnicodeError):
        raise ExecutionError('PDF_ANALYSIS_CHILD_OUTPUT_INVALID') from None
    return {'task_type': 'ANALYSIS', 'run_id': run['run_id'], **result}


def cli_dispatch(argv=None, *, legacy_main=None):
    """Shared old-CLI adapter: old history/plan reads remain, execution is unified."""
    import argparse
    args_list = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--run-manifest', type=Path)
    parser.add_argument('--run-manifest-sha256')
    parser.add_argument('--research-root', type=Path, default=research.PDF_RESEARCH_STATE_ROOT)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--enqueue', action='store_true')
    parser.add_argument('--worker', action='store_true')
    args, extra = parser.parse_known_args(args_list)
    legacy_execute = any(x in args_list for x in ('--execute', '--execute-protocol', '--worker-id', '--protocol-worker', '--close-normalized'))
    if args.run_manifest is None:
        if not legacy_execute and legacy_main is not None:
            return legacy_main(args_list)
        print(json.dumps({'status': 'CANNOT_CONFIRM', 'code': 'PDF_IMMUTABLE_RUN_MANIFEST_REQUIRED', **SAFETY}))
        return 2
    try:
        if extra or args.run_manifest_sha256 is None or args.execute and args.enqueue:
            raise ExecutionError('PDF_GENERIC_RUN_ARGS_INVALID')
        # A command-line caller may not redirect a production writer into a
        # second research store. Unit tests inject temporary roots directly.
        if args.research_root.resolve() != research.PDF_RESEARCH_STATE_ROOT.resolve():
            raise ExecutionError('PDF_FORMAL_RESEARCH_ROOT_REQUIRED')
        reference = {'path': str(args.run_manifest.absolute()), 'sha256': args.run_manifest_sha256}
        run = read_run(reference)
        if args.enqueue:
            result = {'status': 'ENQUEUED_WAITING_EXISTING_HOST', 'run_id': PdfExecutor(args.research_root).enqueue(reference), **SAFETY}
        elif args.execute:
            if args.worker:
                model.require_runtime_python()
                result = PdfExecutor(args.research_root).tick(reference)
            else:
                result = dispatch_analysis_tick(reference, research_root=args.research_root)
        else:
            result = {'status': 'PLAN_ONLY', 'run_id': run['run_id'], 'analysis_count': len(run['tasks']),
                'max_chunks_per_tick': 1, 'runtime_python': run['runtime_python'], **SAFETY}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ExecutionError, PublicationError, model.LocalModelError, ValueError, OSError) as exc:
        print(json.dumps({'status': 'CANNOT_CONFIRM', 'code': str(getattr(exc, 'code', type(exc).__name__)), **SAFETY}))
        return 2


if __name__ == '__main__':
    raise SystemExit(cli_dispatch())
