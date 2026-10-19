#!/usr/bin/env python3
"""Prepare only three exact-parent overlays. No service call, POST or fetch."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import sys

HERE = Path(__file__).resolve().parent
WT = HERE.parents[2]
BASE = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local')
LOCAL = HERE / 'local_only'
SCOPE = json.loads((HERE / 'SCOPE.json').read_text())
INPUT = 'v4/manager_workbench/inputs/source_bindings.py'
HELPER = 'v4/manager_workbench/inputs/us_mapping_close_scope.py'
CONSUMPTION = 'v4/manager_workbench/engines/us_mapping_consumption.py'
MARKET = 'ops/_us_market_digest_parts/market_snapshot.py'
ACCEPTED = {
    'v4/manager_workbench/engines/us_mapping.py': '6d98c575e9c03ca58eace87331bb08ec17243738923af9160a8e1eee5eac6ec1',
    'v4/manager_workbench/engines/strict_us_selection.py': '7178bb4f0b19ee2c09c1f1a6d32ac1b7e0f1d7afd980512f44afc238d1615c48',
}
ROLES = {
    'producer': {'parent': 'futu-native-us-20261018-r1', 'candidate': 'us-mapping-close-producer-20261020-r1',
        'label': 'com.lexi.v4.us-market-digest', 'plist_sha256': 'dfe1fbffa8fc82602163012fb47c2074cc71b8f06b9b496b9f6c24225c92ea45',
        'manifest_sha256': 'd187670c193c659fb5ff15bdf7446e7edcc751a35b0e6947d84214631f64fd18',
        'delta': [MARKET, HELPER]},
    'scheduler': {'parent': 'full-us-hk-mapping-scheduler-20261019-r2', 'candidate': 'us-mapping-close-scheduler-20261020-r1',
        'label': 'com.lexi.v35.scheduler', 'plist_sha256': '9d051a538692e8b9f2d7d93caf708de15346a186dd45862d11d8ad566770b702',
        'manifest_sha256': 'f273d60db4935d6654df3d9042a837002f0d5606d2bace03cac4bdf3ea0b42be',
        'delta': [INPUT, HELPER, CONSUMPTION, *ACCEPTED]},
    'api': {'parent': 'announcement-transport-recovery-20261019-r3', 'candidate': 'us-mapping-close-api-20261020-r1',
        'label': 'com.lexi.v35.api-only', 'plist_sha256': '50d7f5b13c3c0e7ffc85d29d33bcb98cef156a227ac92f92b715e488cbd927f4',
        'manifest_sha256': '841543208b6f14e9dc1367d149dd8658de4d1d0a6da1b4292a61a4d0f7f207a9',
        'delta': [INPUT, HELPER, CONSUMPTION]},
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def replace_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    shutil.copy2(source, target)


def nodes(text):
    return {node.name: ast.get_source_segment(text, node) for node in ast.parse(text).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def scheduler_input_merge(original, source):
    """Only three US functions and the recovery constant can differ."""
    tree = ast.parse(original)
    candidate = ast.parse(source)
    wanted = {'_full_mapping_overlay', 'us_mapping'}
    replacements = []
    by_name = nodes(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in wanted:
            replacements.append((node.lineno - 1, node.end_lineno, by_name[node.name]))
    assert len(replacements) == len(wanted)
    lines = original.splitlines(keepends=True)
    for start, end, replacement in sorted(replacements, reverse=True):
        lines[start:end] = [replacement + '\n']
    result = ''.join(lines)
    assert '_adapt_effective_research_schema' not in nodes(original)
    constant = next(node for node in candidate.body if isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Name) and t.id == '_RECOVERY_STATE_PATHS' for t in node.targets))
    addition = ast.get_source_segment(source, constant) + '\n\n\n' + by_name['_adapt_effective_research_schema'] + '\n\n\n'
    result = result.replace('def _full_mapping_overlay():', addition + 'def _full_mapping_overlay():', 1)
    before, after = nodes(original), nodes(result)
    preserved = {k: v for k, v in before.items() if k not in wanted}
    assert all(after[k] == v for k, v in preserved.items()), 'non-US scheduler function drift'
    assert after['_tdxpy_history_for_exact_parents'] == before['_tdxpy_history_for_exact_parents']
    assert after['resolve_bindings'] == before['resolve_bindings']
    # Top-level bytes around all replacements are retained by exact spans.
    ast.parse(result)
    return result, sorted(preserved)


def main():
    assert not (HERE / 'PREPARED.json').exists(), 'already prepared; inspect instead of overwriting'
    config = BASE / 'config/us-mapping-close-quote-scope-20261020-r1.json'
    assert not config.exists(), 'scope config exists; refuse overwrite'
    spec = importlib.util.spec_from_file_location('retained_inventory',
        BASE / 'releases' / ROLES['api']['parent'] / 'app/ops/api_release_integration.py')
    inventory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory)
    checks = {}
    for role, row in ROLES.items():
        parent = BASE / 'releases' / row['parent']
        candidate = BASE / 'releases' / row['candidate']
        plist = Path('/Users/lexi/Library/LaunchAgents') / (row['label'] + '.plist')
        assert not candidate.exists(), str(candidate) + ' already exists'
        assert sha(parent / 'release-manifest.json') == row['manifest_sha256'], role + ' manifest drift'
        assert sha(plist) == row['plist_sha256'], role + ' plist drift'
        manifest = json.loads((parent / 'release-manifest.json').read_text())
        before = inventory.inventory_tree(parent / 'app')
        assert before == manifest['application_inventory']['entries'], role + ' app inventory drift'
        checks[role] = (parent, candidate, plist, before)
    for rel, expected in ACCEPTED.items():
        assert sha(WT / rel) == expected, 'accepted source drift: ' + rel
    assert sha(checks['api'][0] / 'app' / INPUT) == SCOPE['preimage_sha256'][INPUT]
    assert sha(checks['api'][0] / 'app' / CONSUMPTION) == SCOPE['preimage_sha256'][CONSUMPTION]
    assert sha(checks['producer'][0] / 'app' / MARKET) == SCOPE['preimage_sha256'][MARKET]
    LOCAL.mkdir(exist_ok=True)
    config.write_bytes((HERE / 'quote_scope.json').read_bytes())
    prepared = {}
    for role, (parent, candidate, plist, before) in checks.items():
        row = ROLES[role]
        old_plist = plist.read_bytes()
        (LOCAL / (role + '-original.plist')).write_bytes(old_plist)
        shutil.copytree(parent / 'app', candidate / 'app', symlinks=True)
        preserved_functions = []
        for rel in row['delta']:
            target = candidate / 'app' / rel
            if role == 'scheduler' and rel == INPUT:
                merged, preserved_functions = scheduler_input_merge(target.read_text(), (WT / rel).read_text())
                target.unlink()
                target.write_text(merged)
            else:
                replace_file(WT / rel, target)
        after = inventory.inventory_tree(candidate / 'app')
        a, b = ({e['path']: e for e in entries} for entries in (before, after))
        changed = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
        assert set(changed) == set(row['delta']), (role, changed)
        assert not a.keys() - b.keys(), role + ' unexpected deletion'
        assert all(a[k] == b[k] for k in a.keys() - set(changed)), role + ' preservation failed'
        identity = dict(json.loads((parent / 'release-manifest.json').read_text())['candidate'])
        identity.update(root=str(candidate), app_root=str(candidate / 'app'), release_id=candidate.name)
        if identity.get('formal_release_root') == str(parent):
            identity['formal_release_root'] = str(candidate)
        manifest = {'schema_version': 'v4.release_candidate.v1', 'activation_status': 'PREPARED',
            'candidate': identity,
            'application_inventory': {'entries': after, 'entry_count': len(after),
                'aggregate_sha256': inventory.inventory_digest(after)},
            'task_overlay': {'parent': str(parent), 'parent_manifest_sha256': row['manifest_sha256'],
                'source_worktree': str(WT), 'source_base_commit': SCOPE['base_commit'],
                'full_git_equivalence_claimed': False, 'role': role,
                'delta': [{'path': k, 'before': a.get(k), 'after': b.get(k)} for k in changed],
                'all_non_delta_entries_preserved': True,
                'scheduler_non_us_functions_preserved': preserved_functions}}
        write_json(candidate / 'release-manifest.json', manifest)
        value = plistlib.loads(old_plist)
        def rebind(v):
            if isinstance(v, str):
                return v.replace(str(parent), str(candidate)).replace(parent.name, candidate.name).replace(
                    row['manifest_sha256'], sha(candidate / 'release-manifest.json'))
            if isinstance(v, list):
                return [rebind(x) for x in v]
            if isinstance(v, dict):
                return {k: rebind(x) for k, x in v.items()}
            return v
        proposed = rebind(value)
        if role == 'producer':
            assert value.get('RunAtLoad') is False and not value.get('KeepAlive'), 'producer bootstrap could execute'
            proposed.setdefault('EnvironmentVariables', {})['V4_US_MAPPING_CLOSE_SCOPE_PATH'] = str(config)
            assert proposed['StartCalendarInterval'] == value['StartCalendarInterval']
        path = LOCAL / (role + '-candidate.plist')
        path.write_bytes(plistlib.dumps(proposed, sort_keys=False))
        prepared[role] = {'parent': str(parent), 'parent_manifest_sha256': row['manifest_sha256'],
            'candidate': str(candidate), 'manifest_sha256': sha(candidate / 'release-manifest.json'),
            'parent_inventory_sha256': inventory.inventory_digest(before),
            'candidate_inventory_sha256': inventory.inventory_digest(after),
            'delta': manifest['task_overlay']['delta'], 'all_non_delta_entries_preserved': True,
            'preserved_scheduler_functions': preserved_functions,
            'plist_path': str(plist), 'original_plist_sha256': sha(LOCAL / (role + '-original.plist')),
            'candidate_plist_sha256': sha(path), 'label': row['label'],
            'producer_no_start_on_bootstrap': role == 'producer', 'activated': False}
    write_json(HERE / 'PREPARED.json', {'state': 'PREPARED_PENDING_INDEPENDENT_REVIEW', 'roles': prepared,
        'scope_config_path': str(config), 'scope_config_sha256': sha(config),
        'provider_fetches': 0, 'business_posts': 0, 'service_reloads': 0,
        'natural_verification': 'NOT_RUN'})
    print(json.dumps({role: {'candidate': value['candidate'], 'delta_paths': [e['path'] for e in value['delta']]}
                      for role, value in prepared.items()}))


def refresh_owned_consumers():
    """One pre-review source-ingress correction, retaining the producer."""
    receipt_path = HERE / 'PREPARED.json'
    receipt = json.loads(receipt_path.read_text())
    assert receipt['state'] == 'PREPARED_PENDING_INDEPENDENT_REVIEW'
    spec = importlib.util.spec_from_file_location('retained_inventory_refresh',
        BASE / 'releases' / ROLES['api']['parent'] / 'app/ops/api_release_integration.py')
    inventory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory)
    updates = []
    for role in ['scheduler', 'api']:
        row = receipt['roles'][role]
        candidate, parent = Path(row['candidate']), Path(row['parent'])
        assert sha(row['plist_path']) == row['original_plist_sha256'], 'candidate activated or binding drift'
        assert sha(candidate / 'release-manifest.json') == row['manifest_sha256']
        assert inventory.inventory_digest(inventory.inventory_tree(candidate / 'app')) == row['candidate_inventory_sha256']
        assert sha(parent / 'release-manifest.json') == row['parent_manifest_sha256']
        previous = {'manifest_sha256': row['manifest_sha256'], 'input_sha256': sha(candidate / 'app' / INPUT)}
        target = candidate / 'app' / INPUT
        if role == 'scheduler':
            merged, preserved = scheduler_input_merge((parent / 'app' / INPUT).read_text(), (WT / INPUT).read_text())
            assert preserved == row['preserved_scheduler_functions']
            target.unlink()
            target.write_text(merged)
        else:
            replace_file(WT / INPUT, target)
        after = inventory.inventory_tree(candidate / 'app')
        index = {e['path']: e for e in after}
        manifest = json.loads((candidate / 'release-manifest.json').read_text())
        manifest['application_inventory'] = {'entries': after, 'entry_count': len(after),
            'aggregate_sha256': inventory.inventory_digest(after)}
        for delta in manifest['task_overlay']['delta']:
            if delta['path'] == INPUT:
                delta['after'] = index[INPUT]
        write_json(candidate / 'release-manifest.json', manifest)
        proposed = LOCAL / (role + '-candidate.plist')
        old_proposal = proposed.read_bytes()
        assert sha(proposed) == row['candidate_plist_sha256']
        proposed.write_bytes(old_proposal.replace(previous['manifest_sha256'].encode(), sha(candidate / 'release-manifest.json').encode()))
        row.update(manifest_sha256=sha(candidate / 'release-manifest.json'),
                   candidate_inventory_sha256=inventory.inventory_digest(after),
                   candidate_plist_sha256=sha(proposed), delta=manifest['task_overlay']['delta'])
        updates.append({'role': role, 'reason': 'Same-session PRE_OPEN must not collide with POST_CLOSE directional artifact; controller approved before formal review.',
                        'before': previous, 'after': {'manifest_sha256': row['manifest_sha256'], 'input_sha256': sha(target)}})
    receipt['pre_review_corrections'] = updates
    write_json(receipt_path, receipt)
    print(json.dumps(updates))


def refresh_late_helper():
    """Approved round-two helper-only update of owned unactivated candidates."""
    path = HERE / 'PREPARED.json'
    receipt = json.loads(path.read_text())
    assert receipt['state'] == 'PREPARED_PENDING_INDEPENDENT_REVIEW'
    assert not (HERE / 'ROUND1_PREPARED.json').exists(), 'repair already staged'
    spec = importlib.util.spec_from_file_location('late_repair_inventory',
        BASE / 'releases' / ROLES['api']['parent'] / 'app/ops/api_release_integration.py')
    inventory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(inventory)
    # Check all roles before the first mutation, so a drift cannot leave an
    # unchecked partially updated set.
    for row in receipt['roles'].values():
        candidate = Path(row['candidate'])
        assert row['activated'] is False
        assert sha(row['plist_path']) == row['original_plist_sha256']
        assert sha(candidate / 'release-manifest.json') == row['manifest_sha256']
        assert inventory.inventory_digest(inventory.inventory_tree(candidate / 'app')) == row['candidate_inventory_sha256']
    (HERE / 'ROUND1_PREPARED.json').write_bytes(path.read_bytes())
    changes = []
    for role, row in receipt['roles'].items():
        candidate = Path(row['candidate'])
        manifest_path = candidate / 'release-manifest.json'
        manifest = json.loads(manifest_path.read_text())
        prior = manifest['application_inventory']['entries']
        before = {'manifest_sha256': row['manifest_sha256'], 'helper_sha256': sha(candidate / 'app' / HELPER),
                  'candidate_plist_sha256': row['candidate_plist_sha256']}
        replace_file(WT / HELPER, candidate / 'app' / HELPER)
        after = inventory.inventory_tree(candidate / 'app')
        a, b = ({e['path']: e for e in entries} for entries in (prior, after))
        assert sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k)) == [HELPER]
        manifest['application_inventory'] = {'entries': after, 'entry_count': len(after),
            'aggregate_sha256': inventory.inventory_digest(after)}
        for delta in manifest['task_overlay']['delta']:
            if delta['path'] == HELPER:
                delta['after'] = b[HELPER]
        manifest['task_overlay']['incremental_repair'] = {
            'review_round': 1, 'verdict': 'FAIL', 'finding': 'P1_CONTROLLED_LATE_SCOPE_REJECTED',
            'previous_manifest_sha256': before['manifest_sha256'],
            'previous_helper_sha256': before['helper_sha256'],
            'new_helper_sha256': sha(WT / HELPER), 'non_helper_entries_preserved': True}
        write_json(manifest_path, manifest)
        proposal = LOCAL / (role + '-candidate.plist')
        assert sha(proposal) == row['candidate_plist_sha256']
        proposal.write_bytes(proposal.read_bytes().replace(before['manifest_sha256'].encode(), sha(manifest_path).encode()))
        row.update(manifest_sha256=sha(manifest_path), candidate_inventory_sha256=inventory.inventory_digest(after),
                   candidate_plist_sha256=sha(proposal), delta=manifest['task_overlay']['delta'])
        changes.append({'role': role, 'before': before, 'after': {
            'manifest_sha256': row['manifest_sha256'], 'helper_sha256': sha(candidate / 'app' / HELPER),
            'candidate_plist_sha256': row['candidate_plist_sha256']},
            'incremental_app_delta': [HELPER], 'all_non_helper_entries_preserved': True})
    receipt['round2_helper_repair'] = changes
    write_json(path, receipt)
    print(json.dumps(changes))


if __name__ == '__main__':
    if sys.argv[1:] == ['--refresh-owned-consumers']:
        refresh_owned_consumers()
    elif sys.argv[1:] == ['--refresh-late-helper']:
        refresh_late_helper()
    else:
        assert not sys.argv[1:]
        main()
