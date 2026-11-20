"""Create a source-only deployed Stage fixture and apply just this recovery patch.

Usage: PANEL_PYTHON -B tests/stage_recovery_source_parity.py /absolute/new/temp/root
No data, runtime assets, services, configuration or deployed bytes are modified.
"""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
import shutil
import sys

SOURCE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/candidates/v4-forward-inputs-20261119-r1/stage/app')
CANDIDATE = Path(__file__).resolve().parents[1]


def function_text(source, name):
    node = next(n for n in ast.parse(source).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name)
    return ''.join(source.splitlines(keepends=True)[node.lineno - 1:node.end_lineno])


def replace_function(source, name, replacement):
    old = function_text(source, name)
    return source.replace(old, replacement, 1)


def build_fixture(target, *, apply_patch=True):
    target = Path(target).resolve()
    if target.exists():
        raise ValueError('fixture target must not exist')
    manifest = json.loads((SOURCE.parent / 'release-manifest.json').read_text())
    expected = {item['path']: item for item in manifest['app_files']}
    paths = list((SOURCE / 'stage_center').rglob('*.py'))
    paths.extend(SOURCE / p for p in ['infrastructure/__init__.py', 'infrastructure/interprocess_lock.py', 'infrastructure/owned_io.py', 'contracts/__init__.py', 'contracts/a_share_instruments.py'])
    paths.extend((SOURCE / 'infrastructure').glob('preselection_pool*.py'))
    paths.extend(SOURCE / ('infrastructure/' + name + '.py') for name in ['data_store', 'owned_path', 'trading_safety', 'scope_gate', 'market_time'])
    # Only entry source is needed to inspect scheduler instrumentation. Imports
    # for the actual runner/store tests remain the exact deployed source edition.
    paths.append(SOURCE / 'ops/_run_stage_center_nodes_parts/node_entry.py')
    pinned = {}
    for source in paths:
        rel = source.relative_to(SOURCE).as_posix()
        data = source.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        if rel not in expected or expected[rel]['sha256'] != sha or expected[rel]['size'] != len(data):
            raise ValueError(f'deployed source does not match release manifest: {rel}')
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        pinned[rel] = sha
    baseline_shared = {
        'stage_center/_runner_parts/slot_idempotency.py': '2f79cdfedd50e047f22beaafe254edff420a7fb28be6379ba9a92a475abfa39c',
        'stage_center/_runner_parts/slot_execution.py': '5a1fa904ae99ae4768603f1a583ac1d81c02f52a556984b995faa74b327acd44',
        'stage_center/end_to_end_deadline.py': 'f25d91cf1eaf4ea7d1a9a57fc1f8288d14d98536a63dee16467550974b2a812e',
    }
    if any(pinned[rel] != sha for rel, sha in baseline_shared.items()):
        raise ValueError('shared deployed baseline drifted')
    if apply_patch:
        # Raw publishing's temporal contract differs between branches. Keep the
        # original deployed signature and validation verbatim; patch the common
        # publication tail and bundle body only.
        rel = 'stage_center/_raw_store_parts/transaction_publish.py'
        original = (target / rel).read_text()
        current = (CANDIDATE / rel).read_text()
        head = current[current.index('# A small publication journal'):current.index('def _RawStore_publish_body')]
        old_fn = function_text(original, '_RawStore_publish_body')
        new_fn = function_text(current, '_RawStore_publish_body')
        new_fn = old_fn[:old_fn.index('    status =')] + new_fn[new_fn.index('    status ='):]
        patched = replace_function(original, '_RawStore_publish_body', new_fn)
        patched = replace_function(patched, '_RawStore_publish_bundle_body', function_text(current, '_RawStore_publish_bundle_body'))
        patched = patched.replace('\n\ndef _RawStore_publish_body', '\n\n' + head + 'def _RawStore_publish_body', 1)
        (target / rel).write_text(patched)
        rel = 'stage_center/_selection_parts/store_publication.py'
        original = (target / rel).read_text()
        current = (CANDIDATE / rel).read_text()
        (target / rel).write_text(replace_function(original, '_SelectionStore_publish_body', function_text(current, '_SelectionStore_publish_body')))
        for rel in ['stage_center/_runner_parts/slot_idempotency.py', 'stage_center/_runner_parts/slot_execution.py', 'stage_center/end_to_end_deadline.py']:
            # These files' frozen baseline bytes equal the deployed edition.
            (target / rel).write_bytes((CANDIDATE / rel).read_bytes())
        rel = 'stage_center/_runner_parts/runner_receipts.py'
        original = (target / rel).read_text()
        current = (CANDIDATE / rel).read_text()
        start = current.index("    timing = _v4_global(_v4_scope, '_deadline').summary()")
        end = current.index('    from stage_center.receipt_lineage import bind_owner_receipt', start)
        marker = '    from stage_center.receipt_lineage import bind_owner_receipt'
        assert original.count(marker) == 1
        (target / rel).write_text(original.replace(marker, current[start:end] + marker, 1))
        rel = 'ops/_run_stage_center_nodes_parts/node_entry.py'
        original = (target / rel).read_text()
        current = (CANDIDATE / rel).read_text()
        start = current.index("        _v4_global(_v4_scope, '_deadline').event(\n            \"SCHEDULER_WAKE\"")
        end = current.index('        authorization_error =', start)
        marker = '        trade_date = args.trade_date or evaluated.strftime("%Y%m%d")\n'
        assert original.count(marker) == 1
        (target / rel).write_text(original.replace(marker, marker + current[start:end], 1))
    test = target / 'tests/test_stage_publication_recovery.py'
    test.parent.mkdir()
    shutil.copyfile(CANDIDATE / 'tests/test_stage_publication_recovery.py', test)
    (target / 'SOURCE_FIXTURE_RECEIPT.json').write_text(json.dumps({
        'schema': 'stage.recovery.source_fixture.v1', 'source': str(SOURCE),
        'source_manifest_sha256': hashlib.sha256((SOURCE.parent / 'release-manifest.json').read_bytes()).hexdigest(),
        'pinned_source_file_sha256': pinned, 'contains_runtime_data': False, 'recovery_patch_applied': apply_patch,
        'production_allowed': False, 'orders_sent': False,
    }, sort_keys=True, indent=2) + '\n')
    return {'fixture': str(target), 'source_files': len(pinned), 'contains_runtime_data': False}


if __name__ == '__main__':
    print(json.dumps(build_fixture(sys.argv[1], apply_patch='--baseline' not in sys.argv[2:]), sort_keys=True))
