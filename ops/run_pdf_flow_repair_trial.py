"""Bounded v2 trial adapter; only the existing PdfExecutor performs POSTs."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from infrastructure import local_document_model as model
from infrastructure import pdf_research_claims as claims
from infrastructure import pdf_research_execution as execution
from infrastructure import pdf_research_protocol as protocol
from infrastructure.pdf_research_identity import canonical_json
from infrastructure.pdf_research_publication import digest, owned_lock, read_reference

REPO = Path(__file__).resolve().parents[1]
RESEARCH_ROOT = execution.research.PDF_RESEARCH_STATE_ROOT / 'experiments/pdf-flow-repair-long-20261025'
WRITER = '/root/pdf_flow_repair_writer'


def write(path, value):
    raw = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeError('TRIAL_IMMUTABLE_CONFLICT:' + path.name)
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return ref(path)


def ref(path):
    return {'path': str(path), 'sha256': digest(path.read_bytes())}


def configure():
    assert model.ENABLE_THINKING is False
    assert model.REQUEST_TEMPERATURE == 0 and model.MAX_COMPLETION_TOKENS == 32768
    protocol.enable_claims_v2()
    execution.SOURCE_FILES = tuple(dict.fromkeys((*execution.SOURCE_FILES,
        'infrastructure/pdf_research_claims.py', 'ops/run_pdf_flow_repair_trial.py')))


def prepare(folder, stage, specs_path, oracle_path):
    configure()
    assert stage in ('canary', 'long')
    specs = json.loads(specs_path.read_text())
    assert len(specs) == (3 if stage == 'canary' else 1)
    binding = model.build_request_material(protocol.SCHEMA)
    runtime = execution.runtime_preflight(binding)
    rows, compiled = [], []
    for spec in specs:
        task, pages, groups = execution.compile_task(spec, binding)
        assert stage != 'canary' or len(groups) == 1
        assert stage != 'long' or 20 <= len(pages) <= 50
        assert not (RESEARCH_ROOT / 'analysis-execution' / task['analysis_id']).exists()
        compiled.append(task)
        task_ref = write(folder / stage / 'tasks' / (task['analysis_id'] + '.json'), task)
        coverage = claims.coverage(groups)
        for n, group in enumerate(groups, 1):
            request = protocol.request_envelope(protocol.request_messages(group, task['metadata']))
            exact = write(folder / stage / 'requests' / f'{len(rows) + 1:03d}' / 'exact-request.json', request)
            rows.append({'analysis_id': task['analysis_id'], 'chunk_index': n, 'generation': 0,
                'compiled_task': task_ref, 'exact_request': exact, 'coverage': coverage[n - 1],
                'document_id': task['pdf_sha256']})
    run_id = 'pdf-flow-repair-20261025-' + stage
    authority = write(folder / stage / 'authority.json', {'caller_id': WRITER,
        'model_posts_allowed': True, 'analysis_ids': [t['analysis_id'] for t in compiled],
        'generations': [0], 'max_posts': len(rows), 'scope': 'frozen v2; once per chunk; no retry',
        'authority_source': ref(folder / 'controller-brief.md')})
    run = execution.freeze_run(run_id=run_id, tasks=specs, model_binding=binding,
        authority={'caller_id': WRITER, 'reference': authority})
    run_ref = write(folder / stage / 'run-manifest.json', run)
    value = {'schema': 'pdf-flow-repair.frozen.v2', 'stage': stage, 'source_root': str(REPO),
        'source_sha256': execution.source_manifest(), 'protocol_sha256': protocol.PROTOCOL_SHA256,
        'specs': ref(specs_path), 'oracle': ref(oracle_path), 'rows': rows, 'run_id': run_id,
        'run_manifest': run_ref, 'runtime_preflight': runtime, 'max_posts': len(rows),
        'research_root': str(RESEARCH_ROOT), 'retries': 0, 'prompt_candidates': 1,
        'content_error_allowlist': sorted(claims.CONTENT_ERRORS),
        'shared_model_lock': str(execution.research.GLOBAL_MODEL_LOCK_PATH),
        'resource_guard': 'unchanged >=8GiB; swap growth<=512MiB; before every POST',
        'announcement_priority': 'unchanged pdf_priority_snapshot and shared lock',
        'model_files_before': ref(folder / 'model-files-before.json'), **execution.SAFETY}
    write(folder / stage / 'frozen.json', value)
    print(json.dumps({'signal': 'SOURCE_AND_' + stage.upper() + '_FREEZE_READY',
        'snapshot': ref(folder / stage / 'frozen.json'), 'posts': 0, 'budget': len(rows)}), flush=True)


def check_snapshot(folder, stage):
    value = json.loads((folder / stage / 'frozen.json').read_text())
    assert value['source_root'] == str(REPO) and value['research_root'] == str(RESEARCH_ROOT)
    assert execution.source_manifest() == value['source_sha256'], 'SOURCE_DRIFT'
    assert protocol.PROTOCOL_SHA256 == value['protocol_sha256'], 'PROTOCOL_DRIFT'
    for key in ('specs', 'oracle', 'run_manifest', 'model_files_before'):
        read_reference(value[key])
    for row in value['rows']:
        read_reference(row['compiled_task']);read_reference(row['exact_request'])
    before = json.loads(read_reference(value['model_files_before']))
    for row in before['files']:
        path = Path(before['model_root']) / row['name'];stat = path.stat()
        assert (stat.st_size, stat.st_mtime_ns, stat.st_ino) == (row['size'], row['mtime_ns'], row['inode']), 'MODEL_FILE_DRIFT'
        if 'sha256' in row:
            assert digest(path.read_bytes()) == row['sha256'], 'MODEL_CONFIG_DRIFT'
    return value


def stream_diagnostic(raw):
    final, reasoning, ids, usage, stops = [], [], set(), None, []
    for line in raw.splitlines():
        if not line.startswith(b'data:') or line[5:].strip() == b'[DONE]':
            continue
        frame = json.loads(line[5:].strip())
        if frame.get('model') == 'keepalive':
            continue
        if frame.get('id'):
            ids.add(frame['id'])
        if frame.get('usage'):
            usage = frame['usage']
        for choice in frame.get('choices', []):
            delta = choice.get('delta', {})
            final.append(delta.get('content') or '')
            reasoning.append(delta.get('reasoning_content') or '')
            if choice.get('finish_reason'):
                stops.append(choice['finish_reason'])
    final, reasoning = ''.join(final), ''.join(reasoning)
    return {'response_ids': sorted(ids), 'usage': usage, 'finish_reasons': stops,
        'done': b'data: [DONE]' in raw, 'final_sha256': digest(final.encode()),
        'reasoning_sha256': digest(reasoning.encode()) if reasoning else None,
        'reasoning_characters': len(reasoning),
        'reasoning_status': ('COMPATIBILITY_REASONING_EQUALS_FINAL' if reasoning and reasoning == final
                             else 'PRESENT_NOT_INDEPENDENTLY_VERIFIED' if reasoning else 'NOT_EMITTED'),
        'independent_reasoning': 'NOT_PROVEN'}


def worker(folder, stage, index, receipt, receipt_sha):
    configure()
    snapshot = check_snapshot(folder, stage)
    review = json.loads(read_reference({'path': str(receipt), 'sha256': receipt_sha}))
    assert review['signal'] == 'PRE_FREEZE_PASS' and review['stage'] == stage
    assert review['frozen_sha256'] == digest((folder / stage / 'frozen.json').read_bytes())
    row = snapshot['rows'][index]
    out = folder / stage / 'requests' / f'{index + 1:03d}'
    assert not (out / 'worker-result.json').exists(), 'NO_REDISPATCH_COMPLETED_REQUEST'
    journal = execution.Journal(RESEARCH_ROOT, RESEARCH_ROOT / 'analysis-runs' / snapshot['run_id'] / 'journal.jsonl')
    assert execution.dispatched_attempts(journal.events) == index < snapshot['max_posts'], 'POST_ORDER_OR_BUDGET'
    assert not any(x.get('event') == 'intent' and x.get('analysis_id') == row['analysis_id']
        and x.get('chunk_index') == row['chunk_index'] for x in journal.events), 'NO_RETRY_EXISTING_INTENT'
    identity = model.inspect_local_api_identity()
    assert identity['status'] == 'MATCH', identity
    start = time.monotonic()
    def observed_transport(**kwargs):
        callback = kwargs['on_dispatch']
        def dispatched():
            callback()
            print(json.dumps({'event': 'DISPATCHED', 'stage': stage, 'index': index + 1,
                'chunk_index': row['chunk_index'], 'at': execution.now_utc()}), flush=True)
        return model.request_pdf_card(**{**kwargs, 'on_dispatch': dispatched})
    result = execution.PdfExecutor(RESEARCH_ROOT, transport=observed_transport).tick(snapshot['run_manifest'])
    if result.get('model_posts') == 0 and result.get('status') in ('DEFERRED', 'OWNER_BUSY'):
        print(json.dumps({'event': 'DEFERRED', 'stage': stage, 'index': index + 1, 'result': result}), flush=True)
        raise SystemExit(3)
    saved = {'row': row, 'result': result, 'seconds': time.monotonic() - start,
        'identity_before': identity, 'completed_at': execution.now_utc(), **execution.SAFETY}
    chunk = RESEARCH_ROOT / 'analysis-execution' / row['analysis_id'] / 'g000000' / 'chunks' / f"{row['chunk_index']:04d}"
    if (chunk / 'raw.json').exists():
        raw = json.loads((chunk / 'raw.json').read_text())
        assert digest(canonical_json(json.loads((chunk / 'request.json').read_text()))) == row['exact_request']['sha256']
        for name in ('raw.json', 'raw-stream.sse', 'request.json', 'content-failure.json'):
            if (chunk / name).exists():
                target = out / name
                assert not target.exists()
                target.write_bytes((chunk / name).read_bytes())
        (out / 'final.txt').write_text(raw['text'])
        saved['stream'] = stream_diagnostic((chunk / 'raw-stream.sse').read_bytes())
        assert saved['stream']['final_sha256'] == raw['text_sha256'], 'STREAM_FINAL_MISMATCH'
    write(out / 'worker-result.json', saved)
    print(json.dumps({'event': 'COMPLETED', 'stage': stage, 'index': index + 1,
        'result': result, 'seconds': saved['seconds']}), flush=True)
    if result.get('model_posts') != 1 or result['status'] not in {
            'GENERATED_PENDING_REVIEW', 'CONTENT_FAILED', 'PARTIAL_CHUNKS_COMPLETE', 'PARTIAL_CHUNKS_CONTENT_FAILED'}:
        raise RuntimeError('STOP_NEW_REQUESTS:' + json.dumps(result))


def run_stage(folder, stage, receipt, receipt_sha):
    configure()
    snapshot = check_snapshot(folder, stage)
    with owned_lock(folder, folder / 'experiment-owner.lock'):
        assert not (folder / stage / 'run-started.json').exists(), 'NO_AUTOMATIC_RESUME'
        write(folder / stage / 'run-started.json', {'pid': os.getpid(), 'at': execution.now_utc(),
            'review': {'path': str(receipt), 'sha256': receipt_sha}})
        for index in range(snapshot['max_posts']):
            command = [sys.executable, '-B', '-m', 'ops.run_pdf_flow_repair_trial', '--folder', str(folder),
                '--stage', stage, '--worker', str(index), '--receipt', str(receipt), '--receipt-sha256', receipt_sha]
            result = subprocess.run(command, cwd=REPO, env=dict(os.environ, PANEL_PYTHON=sys.executable,
                PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(REPO)), stdin=subprocess.DEVNULL)
            if result.returncode:
                raise SystemExit(result.returncode)
        write(folder / stage / 'run-finished.json', {'at': execution.now_utc(),
            'posts': snapshot['max_posts'], 'status': 'EXECUTED_REQUIRES_INDEPENDENT_CONTENT_REVIEW'})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--folder', type=Path, required=True)
    parser.add_argument('--stage', choices=('canary', 'long'), required=True)
    parser.add_argument('--prepare', action='store_true');parser.add_argument('--specs', type=Path)
    parser.add_argument('--oracle', type=Path);parser.add_argument('--worker', type=int)
    parser.add_argument('--run', action='store_true');parser.add_argument('--receipt', type=Path)
    parser.add_argument('--receipt-sha256')
    args = parser.parse_args()
    if args.prepare:
        prepare(args.folder, args.stage, args.specs, args.oracle)
    elif args.worker is not None:
        worker(args.folder, args.stage, args.worker, args.receipt, args.receipt_sha256)
    elif args.run:
        run_stage(args.folder, args.stage, args.receipt, args.receipt_sha256)
    else:
        parser.error('choose --prepare, --worker, or --run')


if __name__ == '__main__':
    main()
