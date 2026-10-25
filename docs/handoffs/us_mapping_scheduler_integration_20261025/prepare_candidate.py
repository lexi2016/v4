"""Prepare the frozen r3 + 12-file scheduler cohort; never activate it.

Reuses the retained release inventory primitive and exact-parent overlay pattern
from us_mapping_natural_fix_20261021/prepare_candidate.py. The API builder itself
requires live API-role bindings and is deliberately not used for this scheduler.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def inventory_tool(profile):
    path = Path(profile['inventory_tool'])
    assert sha(path) == profile['inventory_tool_sha256'], 'INVENTORY_TOOL_DRIFT'
    spec = importlib.util.spec_from_file_location('retained_release_inventory', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def complete_inventory(root, tool):
    # The retained primitive excludes generated 3.14 bytecode. Include that
    # separately, plus directory modes, so preservation covers every entry.
    entries, caches = tool._inventory_tree_with_generated_cache(root)
    result = {row['path']: row for row in entries}
    for row in caches:
        result[row['path']] = dict(row, kind='file')
    result['.'] = dict(path='.', kind='directory', mode=f'{stat.S_IMODE(root.stat().st_mode):04o}')
    for directory, dirs, _ in os.walk(root, followlinks=False):
        for name in dirs:
            path = Path(directory) / name
            if not path.is_symlink():
                relative = path.relative_to(root).as_posix()
                result[relative] = dict(path=relative,
                    kind='directory', mode=f'{stat.S_IMODE(path.stat().st_mode):04o}')
    return result


def guard(profile, tool):
    parent, source = Path(profile['parent_app']), Path(profile['source_root'])
    assert sha(parent.parent / 'release-manifest.json') == profile['parent_outer_manifest_sha256'], 'PARENT_MANIFEST_DRIFT'
    assert sha(parent / 'ops/research_panel_qfq.py') == profile['qfq_sha256'], 'PARENT_QFQ_DRIFT'
    for relative, expected in profile['expected_overlays'].items():
        assert sha(source / relative) == expected['source_sha256'], 'SOURCE_DRIFT:' + relative
        old = parent / relative
        actual = sha(old) if old.exists() else None
        assert actual == expected['parent_sha256'], 'PARENT_DRIFT:' + relative
    complete = complete_inventory(parent, tool)
    manifest = json.loads((parent.parent / 'release-manifest.json').read_bytes())
    canonical = {row['path']:row for row in manifest['application_inventory']['entries']}
    extras = {k:v for k,v in complete.items() if k not in canonical}
    approved = profile['excluded_generated_parent_entries']
    assert not extras.keys() - approved.keys(), 'UNAPPROVED_PARENT_EXTRA'
    assert all(value == approved[k] for k,value in extras.items()), 'GENERATED_PARENT_EXTRA_DRIFT'
    assert all(complete.get(k) == v for k,v in canonical.items()), 'PARENT_CANONICAL_DRIFT'
    entries = [canonical[k] for k in sorted(canonical)]
    assert tool.inventory_digest(entries) == manifest['application_inventory']['aggregate_sha256'], 'PARENT_AGGREGATE_DRIFT'
    return canonical, entries, extras


def prepare(profile_path):
    profile = json.loads(profile_path.read_bytes())
    tool = inventory_tool(profile)
    before, public_before, excluded = guard(profile, tool)
    output = Path(profile['candidate_release'])
    assert output.is_absolute() and not output.exists(), 'CANDIDATE_COLLISION'
    parent, source = Path(profile['parent_app']), Path(profile['source_root'])
    output.mkdir()
    def ignore_generated(directory, names):
        return [name for name in names
            if (Path(directory) / name).relative_to(parent).as_posix() in excluded]
    shutil.copytree(parent, output / 'app', symlinks=True, ignore=ignore_generated)
    for relative in profile['expected_overlays']:
        target = output / 'app' / relative
        assert not target.is_symlink(), 'OVERLAY_SYMLINK:' + relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(stat.S_IMODE(target.stat().st_mode) | stat.S_IWUSR)
        shutil.copy2(source / relative, target, follow_symlinks=False)
    after = complete_inventory(output / 'app', tool)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    assert set(changed) == set(profile['expected_overlays']), ('UNEXPECTED_DELTA', changed)
    checked_before, _, checked_excluded = guard(profile, tool)
    assert checked_before == before and checked_excluded == excluded, 'PARENT_CHANGED_DURING_BUILD'
    entries = [after[k] for k in sorted(after)]
    manifest = dict(schema_version='v4.release_candidate.v1', activation_status='PREPARED_NOT_ACTIVATED',
        candidate=dict(root=str(output), app_root=str(output / 'app'), release_id=output.name, role='scheduler'),
        application_inventory=dict(entries=entries, entry_count=len(entries), aggregate_sha256=tool.inventory_digest(entries)),
        task_overlay=dict(parent_app=str(parent), parent_outer_manifest_sha256=profile['parent_outer_manifest_sha256'],
            source_local_commit=profile['source_local_commit'], source_remote_equivalent_commit=profile['source_remote_equivalent_commit'],
            source_tree=profile['source_tree'], cohort_sha256=sha(profile_path),
            delta=[dict(path=k, before=before.get(k), after=after[k]) for k in changed],
            all_non_delta_bytes_and_modes_preserved=True, non_delta_entry_count=len(before.keys() - set(changed)),
            excluded_generated_parent_entries=excluded,
            generated_cache_disposition_sha256=profile['generated_cache_disposition_sha256'],
            full_git_equivalence_claimed=False), financial_safety=profile['safety'])
    dump(output / 'release-manifest.json', manifest)
    dump(output / 'complete-inventory.json', dict(parent=before, candidate=after, excluded_parent_generated=excluded))
    receipt = dict(state='PREPARED_NOT_ACTIVATED', candidate=str(output),
        manifest_sha256=sha(output / 'release-manifest.json'), cohort_sha256=sha(profile_path),
        parent_inventory_sha256=tool.inventory_digest(public_before), candidate_inventory_sha256=tool.inventory_digest(entries),
        exact_overlay_count=len(changed), non_delta_bytes_modes_preserved=True,
        complete_inventory_sha256=sha(output / 'complete-inventory.json'), qfq_sha256=sha(output / 'app/ops/research_panel_qfq.py'),
        excluded_generated_parent_entries=excluded, service_actions=0, live_state_writes=0, activation='NOT_RUN')
    dump(output / 'PREPARED.json', receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, default=HERE / 'COHORT.json')
    args = parser.parse_args()
    prepare(args.profile.resolve())
