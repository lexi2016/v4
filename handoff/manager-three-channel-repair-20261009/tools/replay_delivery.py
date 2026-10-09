#!/usr/bin/env python3
"""Verify forward/reverse patches only in new temporary synthetic source roots."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identity(root):
    return {p.relative_to(root).as_posix(): digest(p.read_bytes())
            for p in root.rglob('*') if p.is_file()}


def run(package):
    package = package.absolute()
    spec = importlib.util.spec_from_file_location('delivery_verifier', package / 'tools/verify_delivery.py')
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    manifest = json.loads((package / 'source_manifest.json').read_text())
    package_verification = verifier.verify(package)
    result = []
    for profile, data in manifest['profiles'].items():
        with tempfile.TemporaryDirectory(prefix='manager-r3-patch-') as temporary:
            source = Path(temporary).resolve()
            for row in manifest['files']:
                if row['profile'] == profile and row['before_path'] is not None:
                    path = source / row['path']
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((package / row['before_path']).read_bytes())
            for row in manifest['preserve']:
                if profile in row['profiles']:
                    path = source / row['path']
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes((package / row['reference_path']).read_bytes())
            original = identity(source)
            before = verifier.verify(package, profile=profile, source_root=source, against='before')
            commands = []
            patch = package / data['patch_path']
            for options in (['--check'], []):
                argv = ['git', '-C', str(source), 'apply', *options, str(patch)]
                completed = subprocess.run(argv, capture_output=True, text=True)
                commands.append({'operation': 'FORWARD_CHECK' if options else 'FORWARD_APPLY',
                                 'exit_code': completed.returncode, 'stderr': completed.stderr})
                if completed.returncode:
                    raise RuntimeError(json.dumps({'profile': profile, 'commands': commands}))
            after = verifier.verify(package, profile=profile, source_root=source, against='after')
            wanted = {r['path'] for r in manifest['files'] if r['profile'] == profile}
            wanted |= {r['path'] for r in manifest['preserve'] if profile in r['profiles']}
            assert set(identity(source)) == wanted, profile
            for options in (['--reverse', '--check'], ['--reverse']):
                argv = ['git', '-C', str(source), 'apply', *options, str(patch)]
                completed = subprocess.run(argv, capture_output=True, text=True)
                commands.append({'operation': 'REVERSE_CHECK' if '--check' in options else 'REVERSE_APPLY',
                                 'exit_code': completed.returncode, 'stderr': completed.stderr})
                if completed.returncode:
                    raise RuntimeError(json.dumps({'profile': profile, 'commands': commands}))
            restored = verifier.verify(package, profile=profile, source_root=source, against='before')
            assert identity(source) == original, profile
            result.append({'profile': profile, 'status': 'PASS', 'commands': commands,
                           'before_files_checked': len(before['source_checked']),
                           'after_files_checked': len(after['source_checked']),
                           'preserved_paths': restored['preserved_checked'],
                           'exact_original_tree_restored': True,
                           'temporary_directory_removed': True})
    return {'schema_version': 'v4.manager_r3.isolated_patch_replay.v1', 'status': 'PASS',
            'manifest_sha256': package_verification['manifest_sha256'],
            'profiles': result, 'runtime_source_writes': 0, 'live_business_io': False,
            'deployment_claimed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.package), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
