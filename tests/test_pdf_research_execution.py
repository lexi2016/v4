import json
from pathlib import Path
import pytest
from infrastructure import pdf_research_execution as e, pdf_research_protocol as p
from infrastructure import local_document_model as model
from infrastructure import pdf_research_claims as claims
from infrastructure.pdf_research_publication import digest, owned_lock, read_json


def claims_profile(monkeypatch):
    for key in ('PROTOCOL_VERSION', 'SEMANTIC_PIPELINE_VERSION', 'PROMPT', 'SCHEMA', 'PROTOCOL_SHA256'):
        monkeypatch.setattr(p, key, getattr(p, key))
    p.enable_claims_v2()
    monkeypatch.setattr(e, 'SOURCE_FILES', (*e.SOURCE_FILES, 'infrastructure/pdf_research_claims.py'))


def claims_transport(calls, *, invalid_first=False):
    def fake(**kwargs):
        calls.append(kwargs)
        kwargs['on_dispatch']()
        kwargs['on_raw'](b'data: offline-complete-fixture\n\n')
        if invalid_first and len(calls) == 1:
            return '{invalid'
        span = json.loads(kwargs['messages'][1]['content'])['source_spans'][0]
        return json.dumps({'claims': [{'statement': span['text'], 'kind': 'FACT',
            'subject': 'UNKNOWN', 'attribution': 'UNKNOWN',
            'evidence': [{'evidence_id': span['evidence_id']}]}], 'unknowns': []})
    return fake


def test_v2_offline_executor_to_existing_publisher_and_render_is_complete(tmp_path, monkeypatch):
    claims_profile(monkeypatch)
    calls = []
    executor, ref, manifest, _, _ = fixture(tmp_path, transport=claims_transport(calls))
    assert executor.tick(ref)['status'] == 'GENERATED_PENDING_REVIEW'
    aid = manifest['tasks'][0]['analysis_id']
    result = read_json(executor.publisher.version_root(aid, 0) / 'result.json')
    assert result['cards'][0]['schema'] == 'pdf-claims-source-v2'
    assert '原文称公司业务发展。' in result['body_markdown']
    assert '第1页' in result['body_markdown']
    assert result['semantic_review'] == 'PENDING_INDEPENDENT_REVIEW'
    assert result['production_allowed'] is False
    assert not list(executor.root.glob('**/accepted*.json'))
    executor.tick(ref)
    assert len(calls) == 1


def test_v2_complete_content_failure_advances_chunks_without_repost_or_promotion(tmp_path, monkeypatch):
    claims_profile(monkeypatch)
    calls = []
    executor, ref, manifest, _, _ = fixture(tmp_path, text='原文称公司业务发展。' * 1800,
        transport=claims_transport(calls, invalid_first=True))
    chunks = len(manifest['tasks'][0]['chunks'])
    assert chunks >= 2
    first = executor.tick(ref)
    assert first['status'] == 'PARTIAL_CHUNKS_CONTENT_FAILED'
    for _ in range(1, chunks):
        result = executor.tick(ref)
    assert result['status'] == 'CONTENT_FAILED'
    assert result['completed_chunks'] == chunks
    assert len(calls) == chunks
    assert len(list(executor.root.glob('analysis-execution/**/raw.json'))) == chunks
    assert len(list(executor.root.glob('analysis-execution/**/content-failure.json'))) == 1
    assert not list(executor.root.glob('analysis-results/**/result.json'))
    assert executor.tick(ref)['model_posts'] == 0
    assert len(calls) == chunks


@pytest.mark.parametrize('code', ['PDF_DUPLICATE_EVIDENCE_ID', 'PDF_EVIDENCE_INPUT_SHA_MISMATCH',
    'PDF_CLAIMS_INPUT_MAPPING_INVALID', 'UNRECOGNIZED_CARD_ERROR'])
def test_v2_unlisted_card_errors_halt_even_when_old_name_rule_misses_them(tmp_path, monkeypatch, code):
    claims_profile(monkeypatch)
    calls = []
    executor, ref, _, _, _ = fixture(tmp_path, text='原文称公司业务发展。' * 1800,
        transport=claims_transport(calls))
    def bad(*args):
        raise e.CardValidationError(code)
    monkeypatch.setattr(e, 'validate_protocol_card', bad)
    assert executor.tick(ref)['status'] == 'HALTED'
    assert executor.tick(ref)['status'] == 'HALTED'
    assert len(calls) == 1


def test_v2_original_breaker_stops_three_complete_content_failures(tmp_path, monkeypatch):
    claims_profile(monkeypatch)
    calls = []
    def bad(**kwargs):
        calls.append(1);kwargs['on_dispatch']();kwargs['on_raw'](b'complete-fixture')
        return '{invalid'
    executor, ref, _, _, _ = fixture(tmp_path, text='原文称公司业务发展。' * 4000, transport=bad)
    for _ in range(3):
        result = executor.tick(ref)
    assert result['status'] == 'HALTED'
    assert result['code'] == 'THREE_CONSECUTIVE_UNUSABLE_ATTEMPTS'
    executor.tick(ref)
    assert len(calls) == 3


@pytest.mark.parametrize('code', sorted(claims.CONTENT_ERRORS))
def test_each_explicit_v2_complete_content_code_can_advance_once(tmp_path, monkeypatch, code):
    claims_profile(monkeypatch)
    calls = []
    executor, ref, manifest, _, _ = fixture(tmp_path, text='原文称公司业务发展。' * 900,
        transport=claims_transport(calls))
    original = e.validate_protocol_card
    # The first exact raw may recur in overlap; the durable chunk, rather than
    # model output identity, determines the injected validation failure.
    def bad_first_chunk(raw, spans, pages):
        first_span = p.evidence_spans(pages)[0]
        if spans[0].evidence_id == first_span.evidence_id:
            raise e.CardValidationError(code)
        return original(raw, spans, pages)
    monkeypatch.setattr(e, 'validate_protocol_card', bad_first_chunk)
    assert executor.tick(ref)['status'] == 'PARTIAL_CHUNKS_CONTENT_FAILED'
    assert executor.tick(ref)['status'] == 'CONTENT_FAILED'
    assert len(calls) == len(manifest['tasks'][0]['chunks']) == 2


def test_v2_unknown_prior_intent_never_dispatches(tmp_path, monkeypatch):
    claims_profile(monkeypatch)
    def crash(point):
        if point == 'after_intent':
            raise Crash(point)
    calls = []
    executor, ref, _, _, _ = fixture(tmp_path, transport=claims_transport(calls), crash=crash)
    with pytest.raises(Crash):
        executor.tick(ref)
    executor.crash = lambda _point: None
    assert executor.tick(ref)['status'] == 'CANNOT_CONFIRM'
    assert calls == []


class Crash(BaseException):
    pass


def raw_card(messages):
    source = json.loads(messages[1]['content'])['source_spans']
    span = next(x for x in source if x['text'].strip())
    return json.dumps({'material_type': '研究材料', 'event_or_meeting_object': 'UNKNOWN',
        'speaker_and_source_attribution': [], 'date': {'value': None, 'basis': 'UNKNOWN', 'evidence': []},
        'facts': [{'claim': '原文称业务发展', 'attribution': 'UNKNOWN', 'period': 'UNKNOWN', 'unit': 'UNKNOWN',
                   'evidence': [{'evidence_id': span['evidence_id']}]}],
        'forecasts': [], 'inferences': [], 'numeric_values': [], 'related_entities': [],
        'unknowns': [], 'source_usage_limits': [], 'risks': []}, ensure_ascii=False)


def fixture(tmp_path, *, count=1, text='原文称公司业务发展。', metadata=None, generation=0, run_id='run', transport=None, crash=None):
    root = tmp_path / 'research'
    inputs = tmp_path / ('inputs-' + run_id)
    inputs.mkdir(parents=True, exist_ok=True)
    binding = {'model_settings_sha256': 'b' * 64, 'runtime_settings_sha256': 'c' * 64,
        'request_temperature': 0, 'enable_thinking': False, 'runtime_limits': {'context_length': 32768},
        'max_completion_tokens': model.MAX_COMPLETION_TOKENS, 'request_policy': {'sampling': 'retained'}}
    specs = []
    for n in range(count):
        pdf = inputs / f'{n}.pdf'
        pdf.write_bytes(b'%PDF-exact-source-' + str(n).encode())
        sha = digest(pdf.read_bytes())
        prepared = inputs / f'{n}.json'
        prepared.write_text(json.dumps({'pdf_sha256': sha, 'source': {'page_count': 1, 'page_extraction_status': 'COMPLETE', 'all_pages_nonempty': True},
            'pages': [{'page_number': 1, 'page_total': 1, 'text': text, 'text_sha256': digest(text.encode()), 'status': 'NATIVE_TEXT', 'extraction_method': 'pypdf-6.10.0'}]}))
        specs.append({'pdf_path': str(pdf), 'pdf_sha256': sha,
            'prepared_input': {'path': str(prepared), 'sha256': digest(prepared.read_bytes())},
            'metadata': metadata or {'title': f'Document {n}', 'source_document_date': None, 'archived_date': None},
            'occurrences': [{'namespace': 'zsxq', 'original_source_id': str(n)}]})
    aids = [e.compile_task(s, binding, validate_pdf_path=lambda path: path)[0]['analysis_id'] for s in specs]
    auth = inputs / 'authority.json'
    auth.write_text(json.dumps({'model_posts_allowed': True, 'analysis_ids': aids, 'generations': [0, 1], 'caller_id': 'writer', 'max_posts': 100}))
    authority = {'caller_id': 'writer', 'reference': {'path': str(auth), 'sha256': digest(auth.read_bytes())}}
    manifest = e.freeze_run(run_id=run_id, tasks=specs, model_binding=binding, authority=authority,
        generation=generation, validate_pdf_path=lambda path: path)
    path = inputs / 'run.json'
    path.write_bytes(e.canonical_json(manifest))
    reference = {'path': str(path), 'sha256': digest(path.read_bytes())}
    calls = []
    def fake(**kwargs):
        calls.append(kwargs)
        kwargs['on_dispatch']()
        kwargs['on_raw'](b'data: exact raw stream\n\n')
        kwargs['on_progress']({'kind': 'model_stream', 'characters': 10})
        return raw_card(kwargs['messages'])
    executor = e.PdfExecutor(root, transport=transport or fake, preflight=lambda _binding: {'python': 'injected-local-transport'},
        resource_probe=lambda: {'available_bytes': 16 * 1024**3, 'swap_used_bytes': 0},
        priority_reader=lambda: {'status': 'ALLOW'}, shared_lock=tmp_path / 'shared.lock',
        validate_pdf_path=lambda path: path, crash=crash)
    return executor, reference, manifest, calls, specs


def test_record_append_reopen_and_generated_reuse_never_reposts(tmp_path):
    executor, ref, manifest, calls, _ = fixture(tmp_path)
    assert executor.tick(ref)['status'] == 'GENERATED_PENDING_REVIEW'
    assert len(calls) == 1
    executor2 = e.PdfExecutor(executor.root, transport=lambda **_kw: pytest.fail('completed analysis reposted'),
        validate_pdf_path=lambda path: path)
    assert executor2.tick(ref)['status'] == 'ALL_TASKS_TERMINAL'
    journal = e.Journal(executor.root, executor.root / 'analysis-runs/run/journal.jsonl')
    assert journal.read() == journal.events
    assert executor.status('run')['generated'] == 1
    assert (executor.root / 'analysis-index.json').is_file()


def test_zero_request_resource_defer_can_later_start_without_attempt_loss(tmp_path):
    executor, ref, manifest, calls, _ = fixture(tmp_path)
    executor.resource_probe = lambda: {'available_bytes': 1, 'swap_used_bytes': 0}
    assert executor.tick(ref)['model_posts'] == 0
    assert executor.status('run')['attempts'] == 0
    assert not list(executor.root.glob('analysis-execution/**/intent.json'))
    executor.resource_probe = lambda: {'available_bytes': 16 * 1024**3, 'swap_used_bytes': 0}
    assert executor.tick(ref)['status'] == 'GENERATED_PENDING_REVIEW'
    assert len(calls) == 1


@pytest.mark.parametrize('point', ['after_intent', 'after_raw', 'after_result', 'before_index', 'after_index'])
def test_real_storage_crash_boundaries_resume_without_duplicate_post(tmp_path, point):
    def crash(where):
        if where == point: raise Crash(where)
    executor, ref, manifest, calls, _ = fixture(tmp_path, crash=crash)
    with pytest.raises(Crash): executor.tick(ref)
    executor.crash = lambda _point: None
    result = executor.tick(ref)
    if point == 'after_intent':
        assert result['status'] == 'CANNOT_CONFIRM'
        assert result['code'] == 'CANNOT_CONFIRM_PRIOR_REQUEST_OUTCOME'
        assert calls == []
    else:
        assert result['status'] == 'GENERATED_PENDING_REVIEW'
        assert len(calls) == 1
    assert result['model_posts'] == 0


@pytest.mark.parametrize('owner', ['run', 'analysis', 'model'])
def test_claim_and_shared_model_contention_issue_zero_requests(tmp_path, owner):
    executor, ref, manifest, calls, _ = fixture(tmp_path)
    aid = manifest['tasks'][0]['analysis_id']
    path = {'run': executor.root / 'analysis-runs/run/owner.lock',
        'analysis': executor.root / 'analysis-execution' / aid / 'owner.lock', 'model': executor.shared_lock}[owner]
    root = executor.root if owner != 'model' else executor.shared_lock.parent
    with owned_lock(root, path):
        assert executor.tick(ref)['status'] == 'OWNER_BUSY'
    assert calls == []
    assert not list(executor.root.glob('analysis-execution/**/intent.json'))


def test_long_pdf_runs_one_complete_chunk_per_tick_and_all_scope_is_published(tmp_path):
    text = '原文称公司业务发展。' * 900
    executor, ref, manifest, calls, _ = fixture(tmp_path, text=text)
    count = len(manifest['tasks'][0]['chunks'])
    assert count > 1
    for n in range(count):
        result = executor.tick(ref)
        assert result['model_posts'] == 1
        assert len(calls) == n + 1
        assert result['status'] == ('GENERATED_PENDING_REVIEW' if n + 1 == count else 'PARTIAL_CHUNKS_COMPLETE')
    aid = manifest['tasks'][0]['analysis_id']
    result = read_json(executor.publisher.version_root(aid, 0) / 'result.json')
    assert result['coverage']['status'] == 'COMPLETE'
    assert result['coverage']['chunk_count'] == count
    assert result['coverage']['evidence_ids'] == [x for group in manifest['tasks'][0]['chunks'] for x in group['evidence_ids']]


@pytest.mark.parametrize('tamper', ['pdf', 'prepared', 'journal', 'raw'])
def test_input_and_persistence_tampering_fail_closed(tmp_path, tamper):
    def crash(where):
        if where == 'after_raw': raise Crash(where)
    executor, ref, manifest, calls, specs = fixture(tmp_path, crash=crash)
    if tamper in {'raw', 'journal'}:
        with pytest.raises(Crash): executor.tick(ref)
        executor.crash = lambda _point: None
    if tamper == 'pdf': Path(specs[0]['pdf_path']).write_bytes(b'%PDF-changed')
    if tamper == 'prepared': Path(specs[0]['prepared_input']['path']).write_text('{}')
    if tamper == 'raw':
        path = next(executor.root.glob('analysis-execution/**/raw.json'))
        value = read_json(path);value['text'] = '{}';path.write_text(json.dumps(value))
    if tamper == 'journal':
        path = executor.root / 'analysis-runs/run/journal.jsonl';path.write_bytes(path.read_bytes()[:-1])
        with pytest.raises(e.ExecutionError, match='TRUNCATED'): executor.tick(ref)
        return
    assert executor.tick(ref)['status'] == 'HALTED'
    assert len(calls) <= 1


def test_mixed_error_breaker_stops_after_three_unusable_actual_attempts(tmp_path):
    errors = iter(['PDF_HTTP_STATUS:400', 'PDF_OTHER_KNOWN', 'PDF_THIRD_ERROR'])
    calls = []
    def bad(**kwargs):
        calls.append(1);kwargs['on_dispatch']()
        raise model.PdfCardTransportError(next(errors), outcome_known=True)
    executor, ref, manifest, _, _ = fixture(tmp_path, count=4, transport=bad)
    for n in range(3):
        assert executor.tick(ref)['status'] == ('HALTED' if n == 2 else 'FAILED')
    assert executor.tick(ref)['status'] == 'HALTED'
    assert executor.status('run')['last_error'] == 'THREE_CONSECUTIVE_UNUSABLE_ATTEMPTS'
    assert len(calls) == 3


def test_content_failure_window_excludes_defer_and_isolation():
    events = [{'event': 'deferred'}, {'event': 'isolated'}]
    for usable, content in [(False, True), (True, False), (False, True), (True, False), (False, True)]:
        events.append({'event': 'attempt_outcome', 'usable': usable, 'content_failure': content})
    assert e.breaker_reason(events) == 'THREE_CONTENT_FAILURES_IN_LAST_TEN'
    assert e.breaker_reason([{'event': 'deferred'}, {'event': 'isolated'}] * 5) is None


def test_api_interpreter_cannot_become_analysis_runtime(tmp_path):
    executor, ref, manifest, calls, _ = fixture(tmp_path)
    executor.preflight = lambda _binding: (_ for _ in ()).throw(model.LocalModelError('PDF_RUNTIME_INTERPRETER_MISMATCH'))
    assert executor.tick(ref)['status'] == 'HALTED'
    assert not calls
    assert not list(executor.root.glob('analysis-execution/**/intent.json'))


def test_daemon_down_and_paused_states_are_persistently_visible(tmp_path):
    executor, ref, manifest, calls, _ = fixture(tmp_path)
    executor.enqueue(ref)
    assert executor.status('run', daemon_running=False)['status'] == 'WAITING_HOST_TICK'
    manifest['paused'] = True
    path = Path(ref['path']);path.write_bytes(e.canonical_json(manifest));ref['sha256'] = digest(path.read_bytes())
    other, ref2, manifest2, _, _ = fixture(tmp_path / 'paused')
    value = json.loads(Path(ref2['path']).read_text());value['paused'] = True
    Path(ref2['path']).write_bytes(e.canonical_json(value));ref2['sha256'] = digest(Path(ref2['path']).read_bytes())
    assert other.tick(ref2)['status'] == 'PAUSED'


def test_new_occurrence_with_identical_model_input_reuses_prior_raw_and_analysis_version(tmp_path):
    from infrastructure.pdf_research_identity import SourceOccurrence
    executor, ref, manifest, calls, specs = fixture(tmp_path)
    original = executor.tick(ref)
    spec = dict(specs[0]);spec['occurrences'] = [{'namespace': 'upload', 'original_source_id': 'duplicate-source'}]
    raw = json.loads(Path(spec['prepared_input']['path']).read_text());raw['document_id'] = 'legacy-other-occurrence'
    path = tmp_path / 'other-page-input.json';path.write_text(json.dumps(raw))
    spec['prepared_input'] = {'path': str(path), 'sha256': digest(path.read_bytes())}
    run = e.freeze_run(run_id='duplicate', tasks=[spec], model_binding=manifest['model_binding'],
        authority=manifest['authority'], validate_pdf_path=lambda path: path)
    assert run['tasks'][0]['analysis_id'] == original['analysis_id']
    manifest_path = tmp_path / 'duplicate-run.json';manifest_path.write_bytes(e.canonical_json(run))
    result = executor.tick({'path': str(manifest_path), 'sha256': digest(manifest_path.read_bytes())})
    assert result['status'] == 'GENERATED_PENDING_REVIEW' and result['model_posts'] == 0
    assert result['result_sha256'] == original['result_sha256'] and len(calls) == 1
    assert executor.publisher.pointers(SourceOccurrence('upload', 'duplicate-source'), original['analysis_id'])['latest_generated']['result_sha256'] == original['result_sha256']


def test_duplicate_occurrences_merge_before_model_execution(tmp_path):
    executor, ref, manifest, calls, specs = fixture(tmp_path)
    spec = dict(specs[0]);spec['occurrences'] = [{'namespace': 'upload', 'original_source_id': 'second'}]
    frozen = e.freeze_run(run_id='two-occurrences', tasks=[specs[0], spec], model_binding=manifest['model_binding'],
        authority=manifest['authority'], validate_pdf_path=lambda path: path)
    assert len(frozen['tasks']) == 1 and len(frozen['tasks'][0]['occurrences']) == 2


def test_rehashed_validated_chunk_tamper_does_not_override_durable_receipt(tmp_path):
    executor, ref, manifest, calls, specs = fixture(tmp_path, text='原文称公司业务发展。' * 900)
    assert executor.tick(ref)['status'] == 'PARTIAL_CHUNKS_COMPLETE'
    path = next(executor.root.glob('analyses/*/g*/chunks/0001.json'))
    value = read_json(path);value['validated']['card']['facts'][0]['claim'] = 'tampered';path.write_bytes(e.canonical_json(value) + b'\n')
    assert executor.tick(ref)['code'] == 'PDF_VALIDATED_CHUNK_SHA_MISMATCH'
    assert len(calls) == 1


def test_checkpoint_every_twenty_failed_documents_is_durable(tmp_path):
    def bad(**kwargs):
        kwargs['on_dispatch']()
        raise model.PdfCardTransportError('KNOWN_RESPONSE_FAILURE', outcome_known=True)
    executor, ref, manifest, calls, _ = fixture(tmp_path, count=20, transport=bad)
    # Exercise checkpoint persistence independently of the already separately
    # tested breaker policy, with existing terminal history and a stopped run.
    executor.enqueue(ref)
    run_root = executor.root / 'analysis-runs/run'
    with e.owned_lock(executor.root, run_root / 'owner.lock'):
        journal = e.Journal(executor.root, run_root / 'journal.jsonl')
        journal.append({'event': 'binding', 'run_manifest_sha256': ref['sha256']})
        for task in manifest['tasks']:
            journal.append({'event': 'failed', 'analysis_id': task['analysis_id'], 'code': 'HISTORICAL_KNOWN'})
        e.write_json(executor.root, run_root / 'halt.json', {'event': 'halt', 'code': 'FROZEN_STOP'})
    assert executor.tick(ref)['status'] == 'HALTED'
    checkpoint = read_json(run_root / 'checkpoints/000020.json')
    assert checkpoint['terminal_count'] == checkpoint['failed'] == 20
    assert checkpoint['generated'] == 0 and checkpoint['attempts'] == 0


@pytest.mark.parametrize('module_name', ['full_once', 'batch', 'sample', 'package_once', 'remaining_once'])
def test_all_legacy_clis_read_same_frozen_generic_manifest_without_execution(tmp_path, monkeypatch, capsys, module_name):
    import importlib
    executor, reference, manifest, calls, _ = fixture(tmp_path)
    module = importlib.import_module('ops.run_pdf_research_' + module_name)
    monkeypatch.setattr(module, '_legacy_main', lambda *_a: pytest.fail('old producer entered'))
    assert module.main(['--run-manifest', reference['path'], '--run-manifest-sha256', reference['sha256']]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result['status'] == 'PLAN_ONLY' and result['analysis_count'] == len(manifest['tasks'])
    assert result['runtime_python'] == str(model.RUNTIME_PYTHON.resolve())
    assert calls == [] and not executor.root.exists()


@pytest.mark.parametrize('code', ['PDF_RESPONSE_MODEL_ID_MISMATCH', 'PINNED_SHARED_SOURCE_SHA_MISMATCH', 'REQUEST_BINDING_MISMATCH'])
@pytest.mark.parametrize('known', [True, False])
def test_integrity_failure_is_terminal_for_the_run_even_if_outcome_terminal_crashes(tmp_path, monkeypatch, code, known):
    calls = []
    def broken(**kwargs):
        calls.append(1)
        kwargs['on_dispatch']()
        kwargs['on_raw'](b'identity error retained')
        raise model.PdfCardTransportError(code, outcome_known=known)
    executor, ref, manifest, _, _ = fixture(tmp_path, count=2, transport=broken)
    append = e.Journal.append
    def crash_before_terminal(journal, value):
        if value.get('event') in {'failed', 'unknown_outcome'}:
            raise Crash('after integrity outcome')
        return append(journal, value)
    monkeypatch.setattr(e.Journal, 'append', crash_before_terminal)
    with pytest.raises(Crash):
        executor.tick(ref)
    monkeypatch.setattr(e.Journal, 'append', append)
    assert executor.tick(ref)['status'] == 'HALTED'
    assert executor.tick(ref)['status'] == 'HALTED'
    assert executor.status('run')['attempts'] == 1 and len(calls) == 1
    outcome = next(x for x in e.Journal(executor.root, executor.root / 'analysis-runs/run/journal.jsonl').events if x['event'] == 'attempt_outcome')
    assert outcome['terminal_event'] == ('failed' if known else 'unknown_outcome')
    assert next(executor.root.glob('analysis-execution/**/raw-stream.sse')).read_bytes() == b'identity error retained'


def test_known_transport_outcome_reopens_without_raw_or_new_attempt(tmp_path, monkeypatch):
    calls = []
    def bad(**kwargs):
        calls.append(1)
        kwargs['on_dispatch']()
        raise model.PdfCardTransportError('PDF_HTTP_STATUS:400', outcome_known=True)
    executor, ref, manifest, _, _ = fixture(tmp_path, count=2, transport=bad)
    append = e.Journal.append
    def crash_before_terminal(journal, value):
        if value.get('event') == 'failed': raise Crash('after known transport outcome')
        return append(journal, value)
    monkeypatch.setattr(e.Journal, 'append', crash_before_terminal)
    for _ in range(3):
        with pytest.raises(Crash): executor.tick(ref)
    monkeypatch.setattr(e.Journal, 'append', append)
    assert executor.tick(ref)['status'] == 'FAILED'
    assert executor.status('run')['attempts'] == 1 and calls == [1]


def test_conflicting_outcome_is_not_silently_deduplicated(tmp_path, monkeypatch):
    executor, ref, manifest, calls, _ = fixture(tmp_path)
    append = e.Journal.append
    def crash_before_receipt(journal, value):
        if value.get('event') == 'chunk_validated': raise Crash('outcome already durable')
        return append(journal, value)
    monkeypatch.setattr(e.Journal, 'append', crash_before_receipt)
    with pytest.raises(Crash): executor.tick(ref)
    monkeypatch.setattr(e.Journal, 'append', append)
    def changed_validation(*args):
        raise e.CardValidationError('DIFFERENT_RESULT_FOR_SAME_REQUEST')
    monkeypatch.setattr(e, 'validate_protocol_card', changed_validation)
    result = executor.tick(ref)
    assert result['status'] == 'HALTED' and result['code'] == 'PDF_ATTEMPT_OUTCOME_CONFLICT'
    assert len(calls) == executor.status('run')['attempts'] == 1


@pytest.mark.parametrize('code', ['FULL_SOURCE_FORECAST_CLASSIFIED_AS_FACT', 'FULL_SOURCE_USE_LIMIT_OMITTED', 'PDF_EVIDENCE_FOREIGN_OR_UNKNOWN'])
def test_ordinary_content_failures_keep_three_actual_request_breaker(tmp_path, monkeypatch, code):
    executor, ref, manifest, calls, _ = fixture(tmp_path, count=4)
    def invalid(*args): raise e.CardValidationError(code)
    monkeypatch.setattr(e, 'validate_protocol_card', invalid)
    assert executor.tick(ref)['status'] == 'CONTENT_FAILED'
    assert executor.tick(ref)['status'] == 'CONTENT_FAILED'
    third = executor.tick(ref)
    assert third['status'] == 'HALTED' and third['code'] == 'THREE_CONSECUTIVE_UNUSABLE_ATTEMPTS'
    assert len(calls) == executor.status('run')['attempts'] == 3


def test_validation_v2_changes_analysis_and_protocol_identity_and_rejects_v1_run(tmp_path, monkeypatch):
    from dataclasses import replace
    executor, reference, run, calls, specs = fixture(tmp_path)
    assert p.SEMANTIC_PIPELINE_VERSION == 'pdf-source-bound-validation-v3'
    current = e.model_configuration(run['model_binding'])
    assert current.semantic_pipeline_version == p.SEMANTIC_PIPELINE_VERSION
    with monkeypatch.context() as context:
        context.setattr(e, 'model_configuration', lambda binding: replace(current, semantic_pipeline_version='pdf-source-bound-validation-v1'))
        old_task = e.compile_task(specs[0], run['model_binding'], validate_pdf_path=lambda path: path)[0]
    assert old_task['analysis_id'] != run['tasks'][0]['analysis_id']
    assert old_task['metadata'] == run['tasks'][0]['metadata']
    old_protocol_sha = digest(e.canonical_json({'schema': p.SCHEMA, 'prompt': p.PROMPT,
        'version': p.PROTOCOL_VERSION, 'semantic_pipeline': 'pdf-source-bound-validation-v1'}))
    assert old_protocol_sha != p.PROTOCOL_SHA256
    run['protocol_sha256'] = old_protocol_sha
    path = Path(reference['path']);path.write_bytes(e.canonical_json(run))
    with pytest.raises(e.ExecutionError, match='PDF_RUN_INPUT_SOURCE_OR_CONFIG_DRIFT'):
        executor.tick({'path': str(path), 'sha256': digest(path.read_bytes())})
    assert calls == [] and not executor.root.exists()


def test_twentieth_checkpoint_counts_real_requests_after_repeated_bad_raw_crashes(tmp_path, monkeypatch):
    executor, ref, manifest, calls, _ = fixture(tmp_path, count=20)
    original = executor.transport
    def nineteenth_bad(**kwargs):
        result = original(**kwargs)
        return '{}' if len(calls) == 19 else result
    executor.transport = nineteenth_bad
    for _ in range(18): assert executor.tick(ref)['status'] == 'GENERATED_PENDING_REVIEW'
    append = e.Journal.append
    def crash_before_terminal(journal, value):
        if value.get('event') == 'failed': raise Crash('same nineteenth bad raw')
        return append(journal, value)
    monkeypatch.setattr(e.Journal, 'append', crash_before_terminal)
    for _ in range(3):
        with pytest.raises(Crash): executor.tick(ref)
        assert executor.status('run')['attempts'] == len(calls) == 19
    raw = next(p for p in executor.root.glob('analysis-execution/**/raw.json') if read_json(p)['text'] == '{}')
    raw_sha = digest(raw.read_bytes())
    monkeypatch.setattr(e.Journal, 'append', append)
    assert executor.tick(ref)['status'] == 'CONTENT_FAILED'
    assert executor.tick(ref)['status'] == 'GENERATED_PENDING_REVIEW'
    checkpoint = read_json(executor.root / 'analysis-runs/run/checkpoints/000020.json')
    assert checkpoint['attempts'] == checkpoint['terminal_count'] == len(calls) == 20
    assert checkpoint['failed'] == 1 and checkpoint['generated'] == 19
    assert digest(raw.read_bytes()) == raw_sha


@pytest.mark.parametrize('known', [False, True])
@pytest.mark.parametrize('gap', ['terminal', 'halt'])
def test_zero_dispatch_integrity_terminal_and_halt_gaps_remain_stopped(tmp_path, monkeypatch, known, gap):
    executor, ref, manifest, calls, _ = fixture(tmp_path, count=2)
    invocations = []
    def broken(**kwargs):
        invocations.append(1)
        raise model.PdfCardTransportError('REQUEST_BINDING_MISMATCH', outcome_known=known)
    executor.transport = broken
    append = e.Journal.append
    target = ('failed' if known else 'unknown_outcome') if gap == 'terminal' else 'halt'
    def crash_after_persistence(journal, value):
        result = append(journal, value)
        if value.get('event') == target: raise Crash('stop evidence durable before status projection')
        return result
    monkeypatch.setattr(e.Journal, 'append', crash_after_persistence)
    with pytest.raises(Crash): executor.tick(ref)
    assert executor.status('run')['status'] == 'HALTED'
    assert executor.status('run')['attempts'] == executor.status('run')['outcomes'] == 0
    monkeypatch.setattr(e.Journal, 'append', append)
    assert executor.tick(ref)['status'] == 'HALTED'
    assert executor.tick(ref)['status'] == 'HALTED'
    assert calls == [] and invocations == [1]


@pytest.mark.parametrize('field', ['analysis_id', 'generation', 'chunk_index', 'chunk_sha256', 'request_sha256',
    'schema_sha256', 'run_id', 'run_manifest_reference', 'writer_id', 'runtime'])
def test_after_raw_intent_tampering_halts_without_hiding_the_dispatched_request(tmp_path, field):
    def crash(where):
        if where == 'after_raw': raise Crash(where)
    executor, ref, manifest, calls, _ = fixture(tmp_path, crash=crash)
    with pytest.raises(Crash): executor.tick(ref)
    path = next(executor.root.glob('analysis-execution/**/intent.json'))
    value = read_json(path)
    if field in {'generation', 'chunk_index'}: value[field] += 1
    elif field == 'run_manifest_reference': value[field] = {**value[field], 'sha256': 'f' * 64}
    elif field == 'runtime': value[field] = {'python': 'forged-runtime'}
    else: value[field] = 'f' * 64
    path.write_bytes(e.canonical_json(value) + b'\n')
    tampered_sha = digest(path.read_bytes())
    raw = next(executor.root.glob('analysis-execution/**/raw.json'))
    raw_sha = digest(raw.read_bytes())
    executor.crash = lambda _where: None
    assert executor.tick(ref)['status'] == 'HALTED'
    status = executor.status('run')
    assert status['attempts'] == len(calls) == 1 and status['outcomes'] == 0
    assert digest(path.read_bytes()) == tampered_sha and digest(raw.read_bytes()) == raw_sha
    assert not list(executor.root.glob('analyses/**/result.json'))


@pytest.mark.parametrize('artifact', ['raw', 'request', 'stream'])
def test_adjacent_raw_request_stream_tampering_retains_one_actual_attempt(tmp_path, artifact):
    def crash(where):
        if where == 'after_raw': raise Crash(where)
    executor, ref, manifest, calls, _ = fixture(tmp_path, crash=crash)
    with pytest.raises(Crash): executor.tick(ref)
    if artifact == 'stream':
        path = next(executor.root.glob('analysis-execution/**/raw-stream.sse'))
        path.write_bytes(b'changed stream')
    else:
        path = next(executor.root.glob('analysis-execution/**/' + artifact + '.json'))
        value = read_json(path)
        if artifact == 'raw':
            value['text'] = '{}';value['text_sha256'] = digest(b'{}')
        else: value['messages'][1]['content'] += ' changed source'
        path.write_bytes(e.canonical_json(value) + b'\n')
    executor.crash = lambda _where: None
    assert executor.tick(ref)['status'] == 'HALTED'
    assert executor.status('run')['attempts'] == len(calls) == 1
    assert executor.status('run')['outcomes'] == 0


def _same_input_run(tmp_path, executor, manifest, spec, name):
    copy = dict(spec)
    copy['occurrences'] = [{'namespace': 'upload', 'original_source_id': name}]
    run = e.freeze_run(run_id=name, tasks=[copy], model_binding=manifest['model_binding'],
        authority=manifest['authority'], validate_pdf_path=lambda path: path)
    path = tmp_path / (name + '.json');path.write_bytes(e.canonical_json(run))
    return {'path': str(path), 'sha256': digest(path.read_bytes())}


def test_same_input_cross_run_raw_reuse_requires_origin_proof_and_counts_no_new_attempt(tmp_path):
    def crash(where):
        if where == 'after_raw': raise Crash(where)
    executor, ref, manifest, calls, specs = fixture(tmp_path, crash=crash)
    with pytest.raises(Crash): executor.tick(ref)
    other = _same_input_run(tmp_path, executor, manifest, specs[0], 'raw-reuse')
    executor.crash = lambda _where: None
    reused = executor.tick(other)
    assert reused['status'] == 'GENERATED_PENDING_REVIEW' and reused['model_posts'] == 0
    assert executor.status('raw-reuse')['attempts'] == executor.status('raw-reuse')['outcomes'] == 0
    assert executor.status('run')['attempts'] == 1 and executor.status('run')['outcomes'] == 0
    original = executor.tick(ref)
    assert original['status'] == 'GENERATED_PENDING_REVIEW' and original['model_posts'] == 0
    assert executor.status('run')['attempts'] == executor.status('run')['outcomes'] == len(calls) == 1
    assert original['result_sha256'] == reused['result_sha256']


def test_another_valid_same_input_manifest_does_not_prove_the_intents_foreign_origin(tmp_path):
    def crash(where):
        if where == 'after_raw': raise Crash(where)
    executor, ref, manifest, calls, specs = fixture(tmp_path, crash=crash)
    with pytest.raises(Crash): executor.tick(ref)
    other = _same_input_run(tmp_path, executor, manifest, specs[0], 'unstarted-origin')
    executor.enqueue(other)
    path = next(executor.root.glob('analysis-execution/**/intent.json'))
    intent = read_json(path)
    intent['run_id'] = 'unstarted-origin';intent['run_manifest_reference'] = other
    path.write_bytes(e.canonical_json(intent) + b'\n')
    tampered_sha = digest(path.read_bytes())
    executor.crash = lambda _where: None
    result = executor.tick(ref)
    assert result['status'] == 'HALTED'
    assert executor.status('run')['attempts'] == len(calls) == 1
    assert executor.status('run')['outcomes'] == 0
    assert digest(path.read_bytes()) == tampered_sha
    assert not list(executor.root.glob('analyses/**/result.json'))


def test_same_tick_identity_rejection_retains_the_dispatch_in_result_and_status(tmp_path):
    executor, ref, manifest, calls, _ = fixture(tmp_path)
    healthy = executor.transport
    def corrupt_after_dispatch(**kwargs):
        result = healthy(**kwargs)
        path = next(executor.root.glob('analysis-execution/**/intent.json'))
        intent = read_json(path);intent['generation'] += 1
        path.write_bytes(e.canonical_json(intent) + b'\n')
        return result
    executor.transport = corrupt_after_dispatch
    result = executor.tick(ref)
    assert result['status'] == 'HALTED' and result['model_posts'] == len(calls) == 1
    assert executor.status('run')['attempts'] == 1 and executor.status('run')['outcomes'] == 0


@pytest.mark.parametrize('lock_phase', ['before_dispatch', 'after_dispatch'])
def test_owner_busy_receipt_counts_dispatch_and_raw_resume_without_repost(tmp_path, lock_phase):
    executor, ref, manifest, calls, _ = fixture(tmp_path)
    before = lock_phase == 'before_dispatch'
    lock_path = executor.shared_lock if before else executor.root / 'publication.lock'
    lock_root = executor.shared_lock.parent if before else executor.root
    with owned_lock(lock_root, lock_path):
        busy = executor.tick(ref)
    expected = 0 if before else 1
    assert busy['status'] == 'OWNER_BUSY' and busy['model_posts'] == expected
    assert len(calls) == executor.status('run')['attempts'] == expected
    originals = {path: digest(path.read_bytes()) for path in executor.root.glob('analysis-execution/**/raw.json')}
    assert len(originals) == expected
    resumed = executor.tick(ref)
    assert resumed['status'] == 'GENERATED_PENDING_REVIEW'
    assert resumed['model_posts'] == (1 if before else 0) and len(calls) == 1
    assert all(digest(path.read_bytes()) == sha for path, sha in originals.items())


def test_compatible_chunks_from_two_runs_keep_each_requests_original_owner(tmp_path):
    executor, ref, manifest, calls, specs = fixture(tmp_path, text='原文称公司业务发展。' * 900)
    assert executor.tick(ref)['status'] == 'PARTIAL_CHUNKS_COMPLETE'
    other = _same_input_run(tmp_path, executor, manifest, specs[0], 'chunk-reuse')
    chunks = len(manifest['tasks'][0]['chunks'])
    # Revalidation of the foreign first chunk is itself one bounded tick.
    for _ in range(chunks): result = executor.tick(other)
    assert result['status'] == 'GENERATED_PENDING_REVIEW' and len(calls) == chunks
    assert executor.status('chunk-reuse')['attempts'] == executor.status('chunk-reuse')['outcomes'] == chunks - 1
    for _ in range(chunks - 1):
        original = executor.tick(ref)
        assert original['model_posts'] == 0
    assert original['status'] == 'GENERATED_PENDING_REVIEW'
    assert executor.status('run')['attempts'] == executor.status('run')['outcomes'] == 1
    assert len(calls) == chunks
