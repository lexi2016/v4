"""Prepare a new immutable scheduler candidate. Never activates or writes business state."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import shutil

DOC = Path(__file__).resolve().parent
ROOT = DOC.parents[2]
PLIST = Path('/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist')
INVENTORY_TOOL = Path('/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/announcement-transport-recovery-20261020-r6/app/ops/api_release_integration.py')
INVENTORY_TOOL_SHA = '2034b1f3c18bf6f15a77ab22c714cbe4aa05daafa9c7413aeb36d05fbbe35f5b'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def inventory_tool():
    assert sha(INVENTORY_TOOL) == INVENTORY_TOOL_SHA, 'INVENTORY_TOOL_DRIFT'
    spec = importlib.util.spec_from_file_location('frozen_inventory', INVENTORY_TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def guard():
    scope = json.loads((DOC / 'SCOPE.json').read_bytes())
    frozen = json.loads((DOC / 'local_only/parent_inventory.json').read_bytes())
    parent = Path(scope['scheduler_parent'])
    assert sha(scope['config']) == scope['config_sha256'], 'LIVE_CONFIG_DRIFT'
    assert sha(PLIST) == scope['scheduler_plist_sha256'], 'LIVE_PLIST_DRIFT'
    manifest_path = parent.parent / 'release-manifest.json'
    assert sha(manifest_path) == frozen['parent_manifest_sha256'], 'PARENT_MANIFEST_DRIFT'
    inv = inventory_tool()
    manifest = json.loads(manifest_path.read_bytes())
    entries = inv.inventory_tree(parent)
    # Controller accepted exactly this pre-existing Finder metadata addition.
    historical_entries = manifest['application_inventory']['entries']
    extra = 'upstreams/review_core/.DS_Store'
    expected = {entry['path']:entry for entry in historical_entries}
    actual = {entry['path']:entry for entry in entries}
    assert actual.keys() - expected.keys() == {extra}, 'UNAPPROVED_PARENT_ADDITION'
    assert expected.keys() - actual.keys() == set(), 'PARENT_ENTRY_REMOVED'
    assert all(actual[key] == entry for key,entry in expected.items()), 'PARENT_INVENTORY_DRIFT'
    assert actual[extra]['sha256'] == 'de3be1dd5f9e047bcbc508cd0570567669de847b5cc82b69cc85c1b03bb2c099'
    assert inv.inventory_digest(historical_entries) == manifest['application_inventory']['aggregate_sha256']
    # Freeze includes generated caches as well; preserve them without importing them as source.
    import stat
    complete_actual = {p.relative_to(parent).as_posix(): dict(sha256=sha(p),mode=stat.S_IMODE(p.stat().st_mode))
        for p in parent.rglob('*') if p.is_file()}
    assert complete_actual == frozen['parent_inventory'], 'ACTUAL_FROZEN_PARENT_DRIFT'
    return scope, parent, manifest, entries, inv


def config_delta(original):
    value = json.loads(json.dumps(original))
    bindings = value['source_bindings']['hk_industry_classification']
    assert 'observed_policy_template' not in bindings, 'TEMPLATE_ALREADY_PRESENT'
    pin = bindings['20261020']
    assert pin['policy'] == 'LATEST_OBSERVED' and pin['observed_trade_date'] == '20261014'
    bindings['observed_policy_template'] = {key:item for key,item in pin.items() if key != 'target_date'}
    reverted = json.loads(json.dumps(value))
    del reverted['source_bindings']['hk_industry_classification']['observed_policy_template']
    assert reverted == original, 'UNRELATED_CONFIG_DELTA'
    return value


def prepare(output):
    scope, parent, manifest, before, inv = guard()
    assert not output.exists(), 'CANDIDATE_COLLISION'
    overlay = json.loads((DOC / 'OVERLAY_SPEC.json').read_bytes())
    assert set(overlay) == set(scope['allowed_source_paths']), 'OVERLAY_ALLOWLIST_MISMATCH'
    output.mkdir(parents=True)
    shutil.copytree(parent, output / 'app', symlinks=True)
    for rel, spec in overlay.items():
        target = output / 'app' / rel
        assert sha(target) == spec['before_sha256'], 'SOURCE_PARENT_DRIFT:' + rel
        text = target.read_text()
        for chunk in spec['replacements']:
            assert text.count(chunk['before']) == 1, 'OVERLAY_CONTEXT_MISMATCH:' + rel
            text = text.replace(chunk['before'], chunk['after'])
        target.write_text(text)
        assert sha(target) == spec['after_sha256'], 'OVERLAY_RESULT_MISMATCH:' + rel
    after = inv.inventory_tree(output / 'app')
    aa = {entry['path']:entry for entry in before}
    bb = {entry['path']:entry for entry in after}
    assert aa.keys() == bb.keys(), 'INVENTORY_KEYS_CHANGED'
    changed = [rel for rel in aa if aa[rel] != bb[rel]]
    assert set(changed) == set(overlay), 'UNEXPECTED_RUNTIME_DELTA'
    # The complete live config may contain operational tokens. Keep it local only.
    config = json.loads(Path(scope['config']).read_bytes())
    new_config = output / 'us-industry-observed-scheduler-20261021-r2.json'
    dump(new_config, config_delta(config))
    candidate_manifest = dict(schema_version='v4.release_candidate.v1', activation_status='PREPARED',
        candidate=dict(root=str(output), app_root=str(output/'app'), release_id=output.name),
        application_inventory=dict(entries=after, entry_count=len(after), aggregate_sha256=inv.inventory_digest(after)),
        task_overlay=dict(parent=str(parent.parent), parent_manifest_sha256=sha(parent.parent/'release-manifest.json'),
            overlay_spec_sha256=sha(DOC/'OVERLAY_SPEC.json'), full_git_equivalence_claimed=False,
            all_non_delta_entries_preserved=True,
            delta=[dict(path=rel, before=aa[rel], after=bb[rel], provenance=overlay[rel]['provenance']) for rel in changed]))
    dump(output/'release-manifest.json',candidate_manifest)
    old_plist = plistlib.loads(PLIST.read_bytes())
    old_manifest_sha = sha(parent.parent/'release-manifest.json')
    def rebind(value):
        if isinstance(value,str):
            return value.replace(str(parent.parent),str(output)).replace(parent.parent.name,output.name).replace(old_manifest_sha,sha(output/'release-manifest.json'))
        if isinstance(value,list):return [rebind(item) for item in value]
        if isinstance(value,dict):return {key:rebind(item) for key,item in value.items()}
        return value
    proposed = rebind(old_plist)
    proposed['EnvironmentVariables']['V4_MANAGER_WORKBENCH_CONFIG_PATH'] = str(new_config)
    (output/'scheduler-proposed.plist').write_bytes(plistlib.dumps(proposed,sort_keys=False))
    (output/'scheduler-original.plist').write_bytes(PLIST.read_bytes())
    (output/'config-original.json').write_bytes(Path(scope['config']).read_bytes())
    # Guard again after copying so preparation cannot silently bind concurrent drift.
    guard()
    receipt = dict(state='PREPARED_NOT_ACTIVATED', candidate=str(output),
        historical_manifest_gap='Controller accepted existing upstreams/review_core/.DS_Store exact SHA; old manifest has 871 entries, actual 872; all actual bytes preserved',
        parent=str(parent), parent_manifest_sha256=old_manifest_sha,
        parent_inventory_sha256=inv.inventory_digest(before), candidate_inventory_sha256=inv.inventory_digest(after),
        candidate_manifest_sha256=sha(output/'release-manifest.json'),
        old_config_sha256=scope['config_sha256'], new_config_sha256=sha(new_config),
        original_plist_sha256=sha(PLIST), proposed_plist_sha256=sha(output/'scheduler-proposed.plist'),
        source_delta={rel:dict(before=overlay[rel]['before_sha256'],after=overlay[rel]['after_sha256']) for rel in overlay},
        exact_delta_count=len(changed), non_delta_entries_preserved=len(before)-len(changed),
        config_delta=['/source_bindings/hk_industry_classification/observed_policy_template'],
        live_activation='NOT_RUN', official_state_writes=False, collection_or_model_calls=False)
    dump(output/'PREPARED.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path)
    parser.add_argument('--guard-only',action='store_true')
    args=parser.parse_args()
    if args.guard_only:
        guard()
        print('PARENT_SOURCE_CONFIG_PLIST_GUARD_PASS; idle workload guard still required immediately before activation')
    else:
        assert args.output and args.output.is_absolute(), 'ABSOLUTE_NEW_OUTPUT_REQUIRED'
        prepare(args.output)
