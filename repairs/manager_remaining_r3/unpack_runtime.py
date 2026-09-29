#!/usr/bin/env python3
"""Decode the pinned repair into a NEW isolated directory. Never deploy or fetch."""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zlib

BASE = '043e248f82360256de30b55fa45cb77c5be8b90f'
PATCH_SHA = 'cfcb560e72f6c86c9947878fe12ace01971c5dcf922b0eca2b1bcc89c33de1e6'
PATCH_SIZE = 98286
PARTS = (
    '25027b4715683c36f327dc8bf894f7d44ba419b9',
    '80b911cb708bc41814fca0d85ed1093622303985',
    'df4b05bfbb278474a5b8f9d429ee670a0e95827b',
    '22c3ada662074c166c5f4ee1ced2ac413b3c1466',
)
HERE = Path(__file__).resolve().parent

def blob(raw: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()

def decode() -> bytes:
    parts = []
    for i, expected in enumerate(PARTS, 1):
        path = HERE / f'runtime.part{i}'
        if path.is_symlink():
            raise ValueError('PART_SYMLINK')
        raw = path.read_bytes()
        if blob(raw) != expected:
            raise ValueError(f'PART_IDENTITY_MISMATCH:{i}')
        parts.append(raw)
    packed = base64.b64decode(b''.join(parts), validate=True)
    inflater = zlib.decompressobj()
    raw = inflater.decompress(packed, PATCH_SIZE + 1)
    if (not inflater.eof or inflater.unused_data or inflater.unconsumed_tail
            or len(raw) != PATCH_SIZE or hashlib.sha256(raw).hexdigest() != PATCH_SHA):
        raise ValueError('PATCH_IDENTITY_MISMATCH')
    return raw

def entries(raw: bytes) -> list[tuple[str, str, str]]:
    rows = []
    for block in raw.decode('utf-8').split('diff --git ')[1:]:
        header = re.match(r'a/(\S+) b/(\S+)\n', block)
        index = re.search(r'^index ([0-9a-f]{40})\.\.([0-9a-f]{40})(?: 100644)?$', block, re.M)
        if not header or not index or header[1] != header[2]:
            raise ValueError('PATCH_PATH_OR_INDEX_INVALID')
        path = PurePosixPath(header[1])
        if (path.is_absolute() or '..' in path.parts or len(path.parts) < 2
                or path.parts[0] not in {'api', 'scheduler', 'config'}):
            raise ValueError('PATCH_PATH_OUTSIDE_SCOPE')
        if index[2] == '0' * 40:
            raise ValueError('DELETION_NOT_EXPECTED')
        rows.append((str(path), index[1], index[2]))
    if len(rows) != 18 or len({row[0] for row in rows}) != len(rows):
        raise ValueError('PATCH_SET_MISMATCH')
    return rows

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path, help='New isolated output directory')
    parser.add_argument('--repo', type=Path, default=HERE.parents[1])
    parser.add_argument('--preimages', type=Path, help='Alternative exact before/ tree; all Git identities checked')
    args = parser.parse_args()
    raw = decode()
    rows = entries(raw)
    output = args.output.expanduser().absolute()
    if (output.exists() or output.is_symlink() or output.resolve() != output
            or 'releases' in output.parts or output == Path.home()):
        raise ValueError('OUTPUT_MUST_BE_NEW_ISOLATED_PATH')
    prepared = {}
    for rel, before, _ in rows:
        if before == '0' * 40:
            continue
        tree, suffix = rel.split('/', 1)
        if tree not in {'api', 'scheduler'}:
            raise ValueError('UNEXPECTED_EXISTING_CONFIG')
        if args.preimages:
            root = args.preimages.resolve(strict=True)
            source = root / rel
            if source.is_symlink() or source.resolve() != source:
                raise ValueError('PREIMAGE_SYMLINK')
            contents = source.read_bytes()
        else:
            source = f'sources/active_{tree}/{suffix}'
            contents = subprocess.run(
                ['git', '-C', str(args.repo.resolve()), 'show', f'{BASE}:{source}'],
                check=True, capture_output=True).stdout
        if blob(contents) != before:
            raise ValueError('FIXED_PREIMAGE_MISMATCH:' + rel)
        prepared[rel] = contents
    output.mkdir(parents=True, exist_ok=False)
    (output / 'runtime.patch').write_bytes(raw)
    after = output / 'after'
    after.mkdir()
    for rel, contents in prepared.items():
        dest = after / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(contents)
    for options in (['--check'], []):
        subprocess.run(['git', 'apply', '--binary', *options, str(output / 'runtime.patch')],
                       cwd=after, check=True, capture_output=True)
    found = {str(p.relative_to(after)) for p in after.rglob('*') if p.is_file()}
    if found != {r[0] for r in rows}:
        raise ValueError('AFTER_SET_MISMATCH')
    for rel, _, expected in rows:
        if blob((after / rel).read_bytes()) != expected:
            raise ValueError('AFTER_IDENTITY_MISMATCH:' + rel)
    print(json.dumps({'status': 'DECODED_AND_BYTE_VERIFIED_NOT_DEPLOYED',
                      'base_commit': BASE, 'after_files': len(rows),
                      'patch_sha256': PATCH_SHA, 'output': str(output)}, indent=2))

if __name__ == '__main__':
    main()
