"""This frozen batch's controller; uses the reviewed projection job unchanged."""
from pathlib import Path
import concurrent.futures as futures
import hashlib
import json
import multiprocessing
import os
import re
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT))
from ops import render_original_formula_projection as job

OUT = Path(sys.argv[1]).resolve()
CONTEXT = None


def resources():
    vm = subprocess.check_output(['vm_stat'], text=True)
    page = int(re.search(r'page size of (\d+)', vm).group(1))
    counts = dict((name.strip(), int(value)) for name, value in re.findall(r'([^\n:]+):\s+(\d+)\.', vm))
    available = page * sum(counts.get(k, 0) for k in ('Pages free', 'Pages inactive', 'Pages speculative'))
    rows = [line.split() for line in subprocess.check_output(['ps', '-axo', 'pid=,ppid=,rss=,pcpu='], text=True).splitlines()]
    descendants = {os.getpid()}
    for _ in range(8):
        descendants.update(int(row[0]) for row in rows if int(row[1]) in descendants)
    return {'available_reclaimable_estimate_bytes': available,
            'job_RSS_conservative_bytes': sum(int(row[2]) * 1024 for row in rows if int(row[0]) in descendants),
            'job_CPU_percent_process_lifetime_average': sum(float(row[3]) for row in rows if int(row[0]) in descendants)}


def compute(symbol):
    engine, inventory, bound, lineage, renderer = CONTEXT
    return job.export_one(engine, inventory, bound[symbol], symbol, lineage, renderer, OUT)


def main():
    global CONTEXT
    started = time.monotonic()
    binding = json.loads((OUT / 'BATCH_EXECUTION_BINDING.json').read_text())
    job.require(job.safe(binding), 'UNSAFE_BATCH_BINDING')
    job.require(str(OUT) == binding['output_root'], 'WRONG_OUTPUT_ROOT')
    job.require(job.sha(Path(binding['scope_ref']).read_bytes()) == binding['scope_sha256'], 'SCOPE_DRIFT')
    code = ROOT / 'ops/render_original_formula_projection.py'
    job.require(job.sha(code.read_bytes()) == binding['code_sha256'], 'REVIEWED_CODE_DRIFT')
    coverage = Path(binding['scope_ref']).parent.parent / 'chart_batch_247/coverage_247.json'
    job.require(job.sha(coverage.read_bytes()) == binding['input_coverage_sha256'], 'COVERAGE_DRIFT')
    order = json.loads((OUT / 'PLANNED_ORDER.json').read_text())['order']
    manifest = json.loads((OUT / 'MANIFEST.json').read_text())
    expected = set(json.loads((OUT / 'INPUT_BINDING.json').read_text())['scope_symbols'])
    job.require(len(expected) == 247 and set(order) == expected - set(binding['reuse']) and len(order) == 243, 'BATCH_SCOPE_CONFLICT')
    job.require(order[:3] == binding['priority'], 'PRIORITY_CONFLICT')
    old_refs = {s: manifest['samples'][s] for s in binding['reuse']}
    for item in old_refs.values():
        job.pinned(item['projection'])
        job.pinned(item['html'])
    frozen = json.loads((OUT / 'INPUT_BINDING.json').read_text())
    engine, inventory, bound, lineage = job.load_bound_inputs(HERE.parent / 'SOURCE_CONFIG.json', coverage,
        Path(frozen['product']['path']).parents[4] / 'index.json', order)
    # The product index is the existing dated product root, not a new source.
    renderer_ref = frozen['renderer']
    renderer = job.pinned(renderer_ref)
    lineage.update(renderer=renderer_ref, projection_code=job.reference(code))
    CONTEXT = engine, inventory, bound, lineage, renderer
    initial = resources()
    history = [initial]
    workers, pending_limit = (14, 28) if initial['available_reclaimable_estimate_bytes'] > 32 * 2**30 else (1, 2)
    stop = None
    ready = {}
    failed = {}
    progress = {'status': 'RUNNING', 'workers': workers, 'pending_limit': pending_limit,
                'ready': ready, 'failed': failed, 'computing_done': False, 'resources': initial}

    def publish():
        progress['completed_new'] = len(ready) + len(failed)
        progress['wall_seconds'] = time.monotonic() - started
        job.write_json(OUT / 'BATCH_PROGRESS.json', progress)
        job.write_json(OUT / 'MANIFEST.json', manifest)

    for symbol, reason in lineage['input_failures'].items():
        failed[symbol] = {'status': 'CANNOT_CONFIRM', 'reason': reason}
        manifest['samples'][symbol] = failed[symbol]
    todo = iter([s for s in order if s not in failed])
    publish()
    node = None
    with futures.ProcessPoolExecutor(max_workers=workers, mp_context=multiprocessing.get_context('fork')) as pool:
        pending = {}

        def submit():
            nonlocal stop
            snapshot = resources()
            history.append(snapshot)
            progress['resources'] = snapshot
            if snapshot['available_reclaimable_estimate_bytes'] < 24 * 2**30 or snapshot['job_RSS_conservative_bytes'] > 64 * 2**30:
                stop = 'RESOURCE_PRESSURE_STOP_NEW_SUBMISSIONS_DRAIN'
                return
            while len(pending) < pending_limit:
                symbol = next(todo, None)
                if symbol is None:
                    break
                pending[pool.submit(compute, symbol)] = symbol

        submit()
        # Workers have forked before starting the separate Chrome controller.
        node = subprocess.Popen(['/Users/lexi/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',
                                 str(HERE / 'headless_batch.cjs'), str(OUT)])
        while pending:
            done, _ = futures.wait(pending, timeout=1, return_when=futures.FIRST_COMPLETED)
            if not done:
                continue
            for future in done:
                symbol = pending.pop(future)
                try:
                    record = future.result()
                except Exception as error:
                    record = {'status': 'CANNOT_CONFIRM', 'reason': type(error).__name__ + ':' + str(error)}
                manifest['samples'][symbol] = record
                (ready if record['status'] == 'READY' else failed)[symbol] = record
            publish()
            if progress['completed_new'] % 25 == 0 or set(binding['priority']) <= set(ready) and not progress.get('priority_computed'):
                progress['priority_computed'] = set(binding['priority']) <= set(ready)
                print(json.dumps({'event': 'COMPUTE_PROGRESS', 'completed': progress['completed_new'], 'ready': len(ready), 'failed': len(failed), 'seconds': progress['wall_seconds']}), flush=True)
            if stop is None:
                submit()
    progress['computing_done'] = True
    progress['status'] = stop or ('COMPUTE_FINISHED_WITH_ERRORS' if failed else 'COMPUTE_COMPLETE')
    progress['resources'] = resources()
    publish()
    node.wait()
    final = {'status': progress['status'], 'ready_new': len(ready), 'failed_new': len(failed),
        'missing_new': sorted(set(order) - set(ready) - set(failed)), 'workers': workers, 'pending_limit': pending_limit,
        'wall_seconds': time.monotonic() - started, 'resource_samples': len(history),
        'min_available_reclaimable_estimate_bytes': min(x['available_reclaimable_estimate_bytes'] for x in history),
        'max_job_RSS_conservative_bytes': max(x['job_RSS_conservative_bytes'] for x in history),
        'headless_exit_code': node.returncode, 'reused': binding['reuse'], **job.FLAGS}
    job.write_json(OUT / 'BATCH_EXECUTION_RESULT.json', final)
    print(json.dumps(final), flush=True)


if __name__ == '__main__':
    main()
