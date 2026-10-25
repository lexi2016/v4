"""Bounded process-local ablation; all POSTs use the unchanged PDF executor."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from infrastructure import local_document_model as model
from infrastructure import pdf_research_execution as execution
from infrastructure import pdf_research_protocol as protocol
from infrastructure.pdf_research_identity import canonical_json
from infrastructure.pdf_research_publication import digest, read_reference, owned_lock

BASE_PROMPT = protocol.PROMPT
BASE_PROTOCOL_SHA = protocol.PROTOCOL_SHA256
BASE_THINKING = model.ENABLE_THINKING
REPO = Path(__file__).resolve().parents[1]
GROUPS = ('A', 'B', 'C', 'D')
WRAPPER_REL = 'ops/run_pdf_single_variable_experiment.py'
EXPERIMENT_RESEARCH_ROOT = execution.research.PDF_RESEARCH_STATE_ROOT / 'experiments/pdf-single-variable-20261025'


def write(path, value):
    raw = canonical_json(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeError('EXPERIMENT_IMMUTABLE_ARTIFACT_CONFLICT:' + path.name)
    else:
        with path.open('xb') as stream:
            stream.write(raw)
    return {'path': str(path), 'sha256': digest(raw)}


def ref(path):
    return {'path': str(path), 'sha256': digest(path.read_bytes())}


def apply_group(group, folder):
    """Only this isolated Python process changes protocol/request globals."""
    if group not in GROUPS:
        raise ValueError('INVALID_GROUP')
    protocol.PROMPT = (folder / ('prompt-simplified.txt' if group == 'C' else 'prompt-baseline.txt')).read_text()
    model.ENABLE_THINKING = group == 'D'
    protocol.PROTOCOL_SHA256 = digest(canonical_json({'schema': protocol.SCHEMA,
        'prompt': protocol.PROMPT, 'version': protocol.PROTOCOL_VERSION,
        'semantic_pipeline': protocol.SEMANTIC_PIPELINE_VERSION}))
    # Honest source binding includes the adapter, while existing producer bytes stay fixed.
    execution.SOURCE_FILES = tuple(dict.fromkeys((*execution.SOURCE_FILES, WRAPPER_REL)))


def changed_paths(left, right, path=''):
    if type(left) is not type(right):
        return [path]
    if isinstance(left, dict):
        if left.keys() != right.keys():
            return [path]
        return [p for k in left for p in changed_paths(left[k], right[k], path + '/' + k)]
    if isinstance(left, list):
        if len(left) != len(right):
            return [path]
        return [p for i, (a, b) in enumerate(zip(left, right)) for p in changed_paths(a, b, path + '/' + str(i))]
    return [] if left == right else [path]


def prepare(folder, prior_path):
    prior = json.loads(prior_path.read_text())
    expected = prior['source_sha256']
    assert {k: v for k, v in execution.source_manifest().items() if k != WRAPPER_REL} == expected
    assert BASE_PROMPT == (folder / 'prompt-baseline.txt').read_text()
    assert BASE_PROTOCOL_SHA == prior['protocol_sha256']
    rows, runs = [], []
    baseline_requests = []
    preflight = {}
    for group in GROUPS:
        apply_group(group, folder)
        binding = model.build_request_material(protocol.SCHEMA)
        current = execution.runtime_preflight(binding)
        for key in prior['model_binding']:
            if key not in {'configuration_sha256', 'enable_thinking'}:
                assert binding[key] == prior['model_binding'][key], key
        assert binding['enable_thinking'] == (group == 'D')
        assert binding['request_temperature'] == 0 and binding['max_completion_tokens'] == 32768
        specs, records = [], []
        for n, sample in enumerate(prior['samples'], 1):
            doc = sample['document_id']
            old_task = json.loads(Path(sample['compiled_task']['path']).read_text())
            spec = {k: old_task[k] for k in ('pdf_path', 'pdf_sha256', 'prepared_input', 'metadata', 'occurrences')}
            if group == 'B':
                value = json.loads(read_reference(spec['prepared_input']))
                text = (folder / 'inputs' / doc / 'clean.txt').read_text()
                value['pages'][0].update(text=text, text_sha256=digest(text.encode()), text_characters=len(text),
                    extraction_method='diagnostic manual original-page-verified text; not authoritative OCR')
                value['source']['extractor_identity_sha256'] = digest(canonical_json({'kind': 'page-verified-diagnostic-v1',
                    'original_prepared_input': spec['prepared_input'], 'page_diff': ref(folder / 'inputs' / doc / 'page-diff.json')}))
                spec['prepared_input'] = write(folder / 'inputs' / doc / 'clean-page-input.json', value)
            task, pages, chunks = execution.compile_task(spec, binding)
            assert len(chunks) == len(pages) == 1
            request = protocol.request_envelope(protocol.request_messages(chunks[0], task['metadata']))
            assert request['temperature'] == 0 and request['max_tokens'] == 32768
            if group == 'A':
                assert request == json.loads(Path(sample['exact_request']['path']).read_text())
                baseline_requests.append(request)
            differences = changed_paths(baseline_requests[n-1], request)
            if group == 'A': assert differences == []
            if group == 'B': assert differences == ['/messages/1/content']
            if group == 'C': assert differences == ['/messages/0/content']
            if group == 'D': assert differences == ['/enable_thinking']
            out = folder / 'matrix' / (group + str(n))
            request_ref = write(out / 'exact-request.json', request)
            task_ref = write(out / 'compiled-task.json', task)
            generation = 1 if group == 'A' else 0
            root = EXPERIMENT_RESEARCH_ROOT
            assert not (root / 'analysis-execution' / task['analysis_id'] / f'g{generation:06d}').exists()
            records.append({'group':group, 'sample_number':n, 'document_id':doc,'analysis_id':task['analysis_id'],
                'generation': generation,'exact_request':request_ref,'compiled_task':task_ref,'request_differences_from_A':differences,
                'protocol_sha256':protocol.PROTOCOL_SHA256,'model_configuration_sha256':binding['configuration_sha256'],
                'source_text_sha256':digest(pages[0].text.encode()),'evidence_ids':task['chunks'][0]['evidence_ids']})
            specs.append(spec)
        runid = 'pdf-single-variable-20261025-' + group.lower() + '-r1'
        authority = {'caller_id':'/root/single_variable_writer','model_posts_allowed':True,
            'analysis_ids':[x['analysis_id'] for x in records],'generations':[records[0]['generation']],
            'max_posts':3,'scope':'frozen single-variable experiment; one dispatch per matrix cell; no retry',
            'authority_source':ref(folder/'controller-brief.md')}
        authority_ref=write(folder/'runs'/group/'authority.json',authority)
        run=execution.freeze_run(run_id=runid,tasks=specs,model_binding=binding,
            authority={'caller_id':authority['caller_id'],'reference':authority_ref},generation=records[0]['generation'])
        reference=write(folder/'runs'/group/'manifest.json',run)
        for r in records:r['run_manifest']=reference;r['run_id']=runid
        rows.extend(records);runs.append(reference);preflight[group]=current
    snapshot={'schema':'pdf-single-variable-frozen.v1','rows':rows,'runs':runs,
        'source_root':str(REPO),'source_sha256':execution.source_manifest(),
        'baseline_dependency_ref':'fb96f2da2415f86641f8a0633f47c64696de9b24',
        'static_inputs':{name:ref(folder/name) for name in ('oracle-v1.json','input-cleaning-manifest.json','prompt-baseline.txt','prompt-simplified.txt','model-files-before.json')},
        'max_posts':12,'retries':0,'prompt_candidates':1,'runtime_preflight':preflight,
        'shared_model_lock':str(execution.research.GLOBAL_MODEL_LOCK_PATH),
        'experiment_research_root':str(EXPERIMENT_RESEARCH_ROOT),
        'artifact_status':'DIAGNOSTIC_DERIVED_NOT_AUTHORITATIVE_OR_ACCEPTED',
        'resource_guard':'unchanged PdfExecutor resource_reason before POST; >=8GiB available, swap growth <=512MiB per run',
        'priority_guard':'unchanged PdfExecutor model.pdf_priority_snapshot before shared lock',
        'identity_rule':'A has same content identity as prior baseline and fresh generation1. B/C/D content/config identity differs and use generation0.',
        **execution.SAFETY}
    write(folder/'frozen-matrix.json',snapshot)
    print(json.dumps({'signal':'PRE_FREEZE_READY','matrix':ref(folder/'frozen-matrix.json'),'source_sha256':snapshot['source_sha256'],'rows':len(rows)}),flush=True)


def check_snapshot(folder):
    snapshot=json.loads((folder/'frozen-matrix.json').read_text())
    for reference in snapshot['static_inputs'].values():read_reference(reference)
    assert execution.source_manifest()==snapshot['source_sha256'],'EXPERIMENT_SOURCE_DRIFT'
    assert snapshot['max_posts']==12 and len(snapshot['rows'])==12
    # Stat weights, and hash only small configuration/tokenizer/template/index files.
    before=json.loads((folder/'model-files-before.json').read_text())
    for row in before['files']:
        p=Path(before['model_root'])/row['name'];st=p.stat()
        assert (st.st_size,st.st_mtime_ns,st.st_ino)==(row['size'],row['mtime_ns'],row['inode']),'MODEL_FILE_DRIFT'
        if 'sha256' in row:assert digest(p.read_bytes())==row['sha256'],'MODEL_CONFIG_DRIFT'
    return snapshot


def completed_result(result, row, root):
    if result.get('model_posts') != 1:
        return False
    if result.get('status') in {'CONTENT_FAILED', 'GENERATED_PENDING_REVIEW'}:
        return True
    # The unchanged run-local breaker may fire after its third completed content
    # failure. No fourth tick is run for this group; do not confuse it with an
    # incomplete transport result or disable the original breaker.
    if (row['sample_number'] == 3 and result.get('status') == 'HALTED'
            and result.get('code') in {'THREE_CONSECUTIVE_UNUSABLE_ATTEMPTS', 'THREE_CONTENT_FAILURES_IN_LAST_TEN'}):
        chunk = root/'analysis-execution'/row['analysis_id']/f"g{row['generation']:06d}"/'chunks/0001/raw.json'
        if not chunk.is_file():
            return False
        journal = execution.Journal(root, root/'analysis-runs'/row['run_id']/'journal.jsonl')
        outcomes = [x for x in journal.events if x.get('event') == 'attempt_outcome' and x.get('analysis_id') == row['analysis_id']]
        return bool(outcomes and outcomes[-1].get('content_failure') is True and outcomes[-1].get('integrity_failure') is False)
    return False


def worker(folder,index,receipt,receipt_sha):
    initial=json.loads((folder/'frozen-matrix.json').read_text());row=initial['rows'][index]
    apply_group(row['group'],folder);snapshot=check_snapshot(folder)
    review=json.loads(read_reference({'path':str(receipt),'sha256':receipt_sha}))
    assert review['signal']=='PRE_FREEZE_PASS'
    assert review['frozen_matrix_sha256']==digest((folder/'frozen-matrix.json').read_bytes())
    identity=model.inspect_local_api_identity();assert identity['status']=='MATCH',identity
    status_path=folder/'matrix'/(row['group']+str(row['sample_number']))/'worker-result.json'
    assert not status_path.exists(),'NO_REDISPATCH_COMPLETED_CELL'
    journal=execution.Journal(EXPERIMENT_RESEARCH_ROOT,
        EXPERIMENT_RESEARCH_ROOT/'analysis-runs'/row['run_id']/'journal.jsonl')
    assert not any(x.get('analysis_id')==row['analysis_id'] and x.get('event') in {'intent','request_dispatched'} for x in journal.events),'NO_RETRY_PRIOR_INTENT'
    total=sum(execution.dispatched_attempts(execution.Journal(EXPERIMENT_RESEARCH_ROOT,
        EXPERIMENT_RESEARCH_ROOT/'analysis-runs'/x['run_id']/'journal.jsonl').events)
        for x in [snapshot['rows'][i] for i in (0,3,6,9)])
    assert total==index and total<12,'GLOBAL_POST_ORDER_OR_BUDGET'
    started=time.monotonic()
    def observed_transport(**kwargs):
        # Observer only; actual HTTP remains the single original request_pdf_card path.
        callback=kwargs['on_dispatch']
        def on_dispatch():
            callback();print(json.dumps({'event':'DISPATCHED','cell':row['group']+str(row['sample_number']),'index':index+1,'at':execution.now_utc()}),flush=True)
        return model.request_pdf_card(**{**kwargs,'on_dispatch':on_dispatch})
    executor=execution.PdfExecutor(research_root=EXPERIMENT_RESEARCH_ROOT,transport=observed_transport)
    result=executor.tick(row['run_manifest'])
    saved={'row':row,'result':result,'seconds':time.monotonic()-started,'model_identity_before':identity,
        'frozen_matrix':ref(folder/'frozen-matrix.json'),'review':{'path':str(receipt),'sha256':receipt_sha},**execution.SAFETY}
    write(status_path,saved)
    print(json.dumps({'event':'COMPLETED','index':index+1,'cell':row['group']+str(row['sample_number']),'result':result,'seconds':saved['seconds']}),flush=True)
    if not completed_result(result,row,EXPERIMENT_RESEARCH_ROOT):
        raise RuntimeError('STOP_NEW_REQUESTS:'+json.dumps(result))


def run_all(folder,receipt,receipt_sha):
    # One parent, sequential isolated workers; no retries. Any nonzero child stops.
    lock=folder/'experiment-owner.lock'
    with owned_lock(folder,lock):
        assert not (folder/'run-started.json').exists(),'RUN_ALREADY_STARTED_NO_AUTOMATIC_RESUME'
        write(folder/'run-started.json',{'pid':os.getpid(),'at':execution.now_utc(),'review':{'path':str(receipt),'sha256':receipt_sha}})
        for index in range(12):
            command=[sys.executable,'-B','-m','ops.run_pdf_single_variable_experiment','--folder',str(folder),
                '--worker',str(index),'--receipt',str(receipt),'--receipt-sha256',receipt_sha]
            env=dict(os.environ,PANEL_PYTHON=sys.executable,PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(REPO))
            result=subprocess.run(command,cwd=REPO,env=env,stdin=subprocess.DEVNULL)
            if result.returncode:raise SystemExit(result.returncode)
        write(folder/'run-finished.json',{'at':execution.now_utc(),'requests':12,'status':'EXECUTION_FINISHED_REQUIRES_INDEPENDENT_CONTENT_REVIEW'})


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--folder',type=Path,required=True)
    parser.add_argument('--prepare',type=Path);parser.add_argument('--worker',type=int)
    parser.add_argument('--run-all',action='store_true');parser.add_argument('--receipt',type=Path);parser.add_argument('--receipt-sha256')
    args=parser.parse_args();folder=args.folder.resolve()
    if args.prepare:prepare(folder,args.prepare)
    elif args.worker is not None:
        assert 0<=args.worker<12;worker(folder,args.worker,args.receipt,args.receipt_sha256)
    elif args.run_all:run_all(folder,args.receipt,args.receipt_sha256)
    else:parser.error('choose --prepare, --worker or --run-all')

if __name__=='__main__':main()
