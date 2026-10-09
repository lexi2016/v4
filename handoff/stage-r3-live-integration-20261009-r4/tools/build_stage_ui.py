#!/usr/bin/env python3
"""Build an exact prepared live UI in a NEW workspace, preserving its source.

The original npm ci/build scripts run only in that workspace. A successful
receipt binds the prepared source, lock file and complete static inventory.
It is a build receipt, not a service deployment or browser acceptance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import posixpath
import stat
import subprocess
import sys
from urllib.parse import unquote, urlsplit

sys.dont_write_bytecode = True
_spec = importlib.util.spec_from_file_location('_r4_ui_sources', Path(__file__).with_name('canary_sources.py'))
sources = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sources)
FLAGS = {'RESEARCH_ONLY': True, 'production_allowed': False, 'buy_gate_updated': False, 'orders_sent': False}
DIST = 'apps/web/dist'


def _digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _directory(value):
    value = Path(value)
    if not value.is_absolute() or '..' in value.parts:
        raise ValueError('ABSOLUTE_DIRECTORY_REQUIRED')
    sources.no_links(value)
    if not value.is_dir():
        raise ValueError('DIRECTORY_MISSING:' + str(value))
    return value


def _destination(value, roots):
    value = Path(value)
    if not value.is_absolute() or '..' in value.parts:
        raise ValueError('ABSOLUTE_NEW_DESTINATION_REQUIRED')
    sources.no_links(value)
    _directory(value.parent)
    if os.path.lexists(value):
        raise ValueError('DESTINATION_ALREADY_EXISTS')
    if any(value == root or root in value.parents for root in roots):
        raise ValueError('DESTINATION_INSIDE_INPUT_ROOT')
    return value


def _non_dist(entries):
    return {path: entry for path, entry in entries.items()
            if path != DIST and not path.startswith(DIST + '/')}


def _static_inventory(root):
    # Static outputs do not inherit source ignores: every output is accounted for.
    policy = {'copy_roots': [DIST], 'optional_roots': [], 'symlinks': {}, 'sha256': None, 'ignored': frozenset()}
    snap = sources.snapshot(root, policy, candidate=True)
    rows = []
    for path, item in sorted(snap['entries'].items()):
        if item['type'] == 'file':
            raw = sources.read_regular(root / path)
            if _digest(raw) != item['sha256']:
                raise ValueError('STATIC_OUTPUT_CHANGED_DURING_INVENTORY')
            rows.append({'path': path, 'kind': 'file', 'sha256': item['sha256'],
                         'mode': f"{item['mode']:04o}", 'size': len(raw)})
    if snap != sources.snapshot(root, policy, candidate=True):
        raise ValueError('STATIC_OUTPUT_CHANGED_DURING_INVENTORY')
    return rows


class _HtmlDependencies(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.references = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        attribute = 'src' if tag in {'script', 'img', 'iframe', 'audio', 'video', 'source'} else None
        if tag == 'link' and set((attrs.get('rel') or '').lower().split()) & {
                'stylesheet', 'modulepreload', 'preload', 'icon'}:
            attribute = 'href'
        if attribute and attrs.get(attribute):
            self.references.append((tag, attrs[attribute]))


def _validate_html_dependencies(root, rows):
    available = {item['path'] for item in rows}
    checked = []
    external = []
    for entry in sorted(path for path in available if path.endswith('.html')):
        parser = _HtmlDependencies()
        parser.feed(sources.read_regular(root / entry).decode('utf-8'))
        for tag, reference in parser.references:
            url = urlsplit(reference)
            if url.scheme or url.netloc:
                external.append({'entry': entry, 'tag': tag, 'url': reference})
                continue
            path = unquote(url.path)
            if not path:
                continue
            if '\\' in path or '\x00' in path:
                raise ValueError('STATIC_LOCAL_DEPENDENCY_PATH_INVALID:' + entry)
            relative = (path.lstrip('/') if path.startswith('/') else
                        str(PurePosixPath(entry[len(DIST) + 1:]).parent / path))
            relative = posixpath.normpath(relative)
            if relative == '..' or relative.startswith('../'):
                raise ValueError('STATIC_LOCAL_DEPENDENCY_ESCAPES_DIST:' + entry)
            target = DIST + '/' + relative
            if target not in available:
                raise ValueError('STATIC_LOCAL_DEPENDENCY_MISSING:' + entry + ':' + target)
            checked.append({'entry': entry, 'tag': tag, 'target': target})
    return {'checked_local_dependencies': checked, 'external_references_not_fetched': external}


def build_stage_ui(*, package, prepared_ui, destination, npm='npm'):
    result = {'schema_version': 'V4_STAGE_UI_BUILD_V1', 'status': 'PREFLIGHT_FAILED',
              'package': str(package), 'prepared_ui': str(prepared_ui), 'destination': str(destination),
              'write_performed': False, 'commands': [], 'errors': [],
              'source_bytes_and_modes_unchanged': None, 'build_source_bytes_unchanged': None,
              'static_inventory_sha256': None, 'scope': 'ISOLATED_UI_BUILD_NOT_DEPLOYMENT', **FLAGS}
    created = False
    original = policy = prepared = provenance = manifest_identity = None
    try:
        package = _directory(package)
        prepared = _directory(prepared_ui)
        mapping_raw = sources.read_regular(package / 'SOURCE_MAP.json')
        mapping = json.loads(mapping_raw)
        if any(mapping.get(key) is not value for key, value in FLAGS.items()):
            raise ValueError('PACKAGE_SAFETY_FLAGS_INVALID')
        result['source_map_sha256'] = _digest(mapping_raw)
        policy = sources.load_policy(package, mapping, 'ui', sources.IGNORED)
        if policy['copy_roots'] != ['apps/web'] or policy['optional_roots'] or policy['symlinks']:
            raise ValueError('EXACT_LIVE_WEB_SOURCE_POLICY_REQUIRED')
        original = sources.snapshot(prepared, policy, candidate=True)
        provenance = sources.verify_manifest(prepared, policy, result['source_map_sha256'], original)
        if provenance is None:
            raise ValueError('PREPARED_UI_MANIFEST_REQUIRED')
        manifest_stat = (prepared / sources.MANIFEST).lstat()
        manifest_identity = (manifest_stat.st_dev, manifest_stat.st_ino, stat.S_IMODE(manifest_stat.st_mode))
        selected = [x for x in mapping['files'] if x['group'] == 'ui']
        if not selected:
            raise ValueError('UI_SOURCE_MAP_EMPTY')
        for item in selected:
            relative = sources._relative(item['relative_path'])
            after = sources._relative(item['after_path'])
            if not relative.startswith('apps/web/') or not after.startswith('after/ui/'):
                raise ValueError('UI_SOURCE_MAP_PATH_INVALID')
            if (_digest(sources.read_regular(prepared / relative)) != item['after_sha256']
                    or _digest(sources.read_regular(package / after)) != item['after_sha256']):
                raise ValueError('PREPARED_UI_AFTER_SHA_MISMATCH:' + relative)
        destination = _destination(destination, (package, prepared, Path(provenance['manifest']['source_root'])))
        package_json = json.loads(sources.read_regular(prepared / 'apps/web/package.json'))
        script = package_json.get('scripts', {}).get('build')
        if not isinstance(script, str) or not script.strip():
            raise ValueError('EXISTING_NPM_BUILD_SCRIPT_REQUIRED')
        lock = sources.read_regular(prepared / 'apps/web/package-lock.json')
        result.update(prepared_source_manifest_sha256=provenance['sha256'],
                      prepared_source_tree_sha256=sources.tree_id(original['entries']),
                      prepared_source_root=provenance['manifest']['source_root'],
                      lock_sha256=_digest(lock), npm_build_script=script,
                      started_at_utc=datetime.now(timezone.utc).isoformat())
        old_entries = {path[len(DIST) + 1:] for path, item in original['entries'].items()
                       if path.startswith(DIST + '/') and path.endswith('.html') and item['type'] == 'file'}
        old_entries.add('index.html')
        destination.mkdir(mode=0o700)
        created = True
        result.update(status='BUILD_FAILED', write_performed=True)
        # The immutable prepared copy is never chmod'ed or used as npm's cwd.
        for relative, item in sorted(_non_dist(original['entries']).items()):
            if relative == '.':
                continue
            target = destination / relative
            if item['type'] == 'directory':
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(0o755)
            elif item['type'] == 'file':
                raw = sources.read_regular(prepared / relative)
                if _digest(raw) != item['sha256']:
                    raise ValueError('PREPARED_SOURCE_CHANGED_DURING_COPY')
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as stream:
                    stream.write(raw)
                target.chmod(item['mode'] | stat.S_IWUSR)
            else:
                raise ValueError('UNSUPPORTED_BUILD_SOURCE_ENTRY')
        before_build = _non_dist(sources.snapshot(destination, policy, candidate=True)['entries'])
        env = {**os.environ, 'npm_config_cache': str(destination / 'npm-cache')}
        for label, command in (('npm_ci', [str(npm), 'ci']), ('npm_build', [str(npm), 'run', 'build'])):
            completed = subprocess.run(command, cwd=destination / 'apps/web', env=env,
                                       text=True, capture_output=True, check=False)
            stdout = destination / (label + '.stdout.log')
            stderr = destination / (label + '.stderr.log')
            stdout.write_text(completed.stdout)
            stderr.write_text(completed.stderr)
            result['commands'].append({'command': command, 'cwd': str(destination / 'apps/web'),
                                       'exit_code': completed.returncode, 'stdout': str(stdout), 'stderr': str(stderr)})
            if completed.returncode:
                raise ValueError('NPM_COMMAND_FAILED:' + label)
        after_build = _non_dist(sources.snapshot(destination, policy, candidate=True)['entries'])
        result['build_source_bytes_unchanged'] = before_build == after_build
        if not result['build_source_bytes_unchanged']:
            raise ValueError('BUILD_CHANGED_SOURCE_BYTES_OR_MODES')
        rows = _static_inventory(destination)
        paths = {item['path'] for item in rows}
        for entry in sorted(old_entries):
            if DIST + '/' + entry not in paths:
                raise ValueError('STATIC_ENTRY_REMOVED:' + entry)
        if not any(item['path'].endswith('.js') for item in rows):
            raise ValueError('STATIC_JAVASCRIPT_OUTPUT_REQUIRED')
        result['html_dependency_validation'] = _validate_html_dependencies(destination, rows)
        result.update(static_inventory=rows,
                      static_inventory_sha256=_digest(json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                                                 separators=(',', ':')).encode()),
                      built_dist_root=str(destination / DIST),
                      build_source_tree_sha256=sources.tree_id(after_build),
                      retained_html_entries=sorted(old_entries))
        if _digest(sources.read_regular(package / 'SOURCE_MAP.json')) != result['source_map_sha256']:
            raise ValueError('PACKAGE_SOURCE_MAP_CHANGED_DURING_BUILD')
        result['status'] = 'UI_BUILD_PREPARED'
    except (OSError, ValueError, KeyError, TypeError) as error:
        result['errors'].append(str(error))
        result['status'] = 'BUILD_FAILED' if created else 'PREFLIGHT_FAILED'
        result['static_inventory_sha256'] = None
    finally:
        if original is not None:
            try:
                result['source_bytes_and_modes_unchanged'] = original == sources.snapshot(prepared, policy, candidate=True)
                if provenance is not None:
                    current_manifest = sources.read_regular(prepared / sources.MANIFEST)
                    current_stat = (prepared / sources.MANIFEST).lstat()
                    result['source_bytes_and_modes_unchanged'] = (
                        result['source_bytes_and_modes_unchanged']
                        and _digest(current_manifest) == provenance['sha256']
                        and (current_stat.st_dev, current_stat.st_ino, stat.S_IMODE(current_stat.st_mode)) == manifest_identity)
            except (OSError, ValueError):
                result['source_bytes_and_modes_unchanged'] = False
            if not result['source_bytes_and_modes_unchanged']:
                result['status'] = 'BUILD_FAILED' if created else 'PREFLIGHT_FAILED'
                result['static_inventory_sha256'] = None
                result['errors'].append('PREPARED_SOURCE_CHANGED')
        if created:
            result['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
            (destination / 'BUILD_RECEIPT.json').write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + '\n')
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', required=True, type=Path)
    parser.add_argument('--prepared-ui', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    parser.add_argument('--npm', default='npm')
    args = parser.parse_args(argv)
    result = build_stage_ui(package=args.package, prepared_ui=args.prepared_ui, destination=args.destination, npm=args.npm)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if result['status'] == 'UI_BUILD_PREPARED' else 3


if __name__ == '__main__':
    raise SystemExit(main())
