#!/usr/bin/env python3
"""Read-only byte verifier for the R3 package and explicitly selected source profile."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

SCHEMA = 'v4.manager_r3.delivery.v1'
MAX_FILE_BYTES = 8 * 1024 * 1024


def read_file(root: Path, relative: str) -> bytes | None:
    path = PurePosixPath(relative)
    if not relative or path.is_absolute() or '..' in path.parts or str(path) != relative:
        raise ValueError('UNSAFE_RELATIVE_PATH:' + relative)
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('SYMLINK_REJECTED:' + relative)
    if not current.exists():
        return None
    if not current.is_file() or current.stat().st_size > MAX_FILE_BYTES:
        raise ValueError('NOT_BOUNDED_REGULAR_FILE:' + relative)
    with current.open('rb') as stream:
        value = stream.read(MAX_FILE_BYTES + 1)
    if len(value) > MAX_FILE_BYTES:
        raise ValueError('FILE_LIMIT_EXCEEDED:' + relative)
    return value


def sha(value: bytes | None) -> str | None:
    return hashlib.sha256(value).hexdigest() if value is not None else None


def verify(package: Path, *, profile: str | None = None,
           source_root: Path | None = None, against: str = 'after') -> dict:
    package = package.absolute()
    if package.resolve() != package:
        raise ValueError('PACKAGE_ROOT_NOT_EXACT')
    manifest_raw = read_file(package, 'source_manifest.json')
    if manifest_raw is None:
        raise ValueError('MANIFEST_MISSING')
    manifest = json.loads(manifest_raw)
    if manifest.get('schema_version') != SCHEMA:
        raise ValueError('MANIFEST_SCHEMA_INVALID')
    if profile is not None and profile not in manifest['profiles']:
        raise ValueError('PROFILE_UNKNOWN:' + profile)
    if source_root is not None and profile is None:
        raise ValueError('SOURCE_ROOT_REQUIRES_PROFILE')
    if against not in {'before', 'after'}:
        raise ValueError('AGAINST_INVALID')
    if source_root is not None:
        source_root = source_root.absolute()
        if source_root.resolve() != source_root or not source_root.is_dir():
            raise ValueError('SOURCE_ROOT_NOT_EXACT_DIRECTORY')
    seen = set()
    payloads = []
    source_checks = []
    for row in manifest['files']:
        identity = (row['profile'], row['path'])
        if identity in seen:
            raise ValueError('DUPLICATE_SOURCE_RECORD:' + '/'.join(identity))
        seen.add(identity)
        for side in ('before', 'after'):
            expected = row[side + '_sha256']
            rel = row.get(side + '_path')
            if expected is None:
                if rel is not None:
                    raise ValueError('NULL_IDENTITY_WITH_PAYLOAD:' + row['path'])
                continue
            if not isinstance(rel, str):
                raise ValueError('PAYLOAD_PATH_MISSING:' + row['path'])
            raw = read_file(package, rel)
            if sha(raw) != expected or len(raw) != row[side + '_bytes']:
                raise ValueError('PAYLOAD_MISMATCH:' + rel)
            payloads.append(rel)
        if source_root is not None and row['profile'] == profile:
            actual = sha(read_file(source_root, row['path']))
            if actual != row[against + '_sha256']:
                raise ValueError('SOURCE_' + against.upper() + '_MISMATCH:' + row['path'])
            source_checks.append(row['path'])
    for name, spec in manifest['profiles'].items():
        raw = read_file(package, spec['patch_path'])
        if sha(raw) != spec['patch_sha256']:
            raise ValueError('PATCH_MISMATCH:' + name)
        for side in ('before', 'after'):
            expected = {row[side + '_path'] for row in manifest['files']
                        if row['profile'] == name and row.get(side + '_path') is not None}
            folder = package / side / name
            actual = {str(p.relative_to(package)) for p in folder.rglob('*') if p.is_file()} if folder.exists() else set()
            if actual != expected:
                raise ValueError('PAYLOAD_SET_MISMATCH:' + side + ':' + name)
    preserved = []
    if source_root is not None:
        for row in manifest.get('preserve', []):
            if profile in row['profiles']:
                if sha(read_file(source_root, row['path'])) != row['sha256']:
                    raise ValueError('PRESERVED_SOURCE_MISMATCH:' + row['path'])
                preserved.append(row['path'])
    return {'status': 'PASS', 'schema_version': SCHEMA,
            'manifest_sha256': sha(manifest_raw), 'payload_count': len(payloads),
            'profile': profile, 'against': against if source_root else None,
            'source_checked': source_checks, 'preserved_checked': preserved,
            'source_root': str(source_root) if source_root else None,
            'source_writes': 0, 'business_io': False, 'deployment_claimed': False}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--profile')
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--against', choices=('before', 'after'), default='after')
    args = parser.parse_args(argv)
    try:
        result = verify(args.package, profile=args.profile,
                        source_root=args.source_root, against=args.against)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'FAIL', 'reason': str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
