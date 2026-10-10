"""Read-only verification of the 20 scoped files and delivered patch images."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import stat
import sys


def safe_file(root, relative):
    path = PurePosixPath(relative)
    if path.is_absolute() or '..' in path.parts or '\\' in relative:
        raise ValueError('INVALID_RELATIVE_PATH:' + relative)
    current = root
    for part in path.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('SYMLINK_REJECTED:' + relative)
    if current.exists() and not stat.S_ISREG(current.stat().st_mode):
        raise ValueError('REGULAR_FILE_REQUIRED:' + relative)
    return current


def verify(root, package, manifest, phase):
    failures = []
    for row in manifest['files']:
        relative = row['path']
        if not relative.startswith('V5/'):
            failures.append('OUT_OF_SCOPE:' + relative)
            continue
        checks = [(root, relative, row[phase])]
        checks.extend((package, side + '/' + relative, row[side]) for side in ('before', 'after'))
        for parent, name, expected in checks:
            try:
                path = safe_file(parent, name)
                if expected is None:
                    if path.exists():
                        failures.append('EXPECTED_ABSENT:' + str(path))
                    continue
                raw = path.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                if digest != expected['sha256'] or len(raw) != expected['bytes']:
                    failures.append('SHA_OR_SIZE_MISMATCH:' + str(path))
                blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
                if blob != expected['git_blob_sha']:
                    failures.append('GIT_BLOB_MISMATCH:' + str(path))
            except (OSError, ValueError) as error:
                failures.append(str(error))
    for name, expected in manifest['patches'].items():
        try:
            raw = safe_file(package, name).read_bytes()
            if hashlib.sha256(raw).hexdigest() != expected['sha256'] or len(raw) != expected['bytes']:
                failures.append('PATCH_MISMATCH:' + name)
        except (OSError, ValueError) as error:
            failures.append(str(error))
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', required=True, type=Path)
    parser.add_argument('--phase', choices=('before', 'after'), required=True)
    args = parser.parse_args()
    supplied = args.repo_root.absolute()
    if any(path.is_symlink() for path in (supplied, *supplied.parents)):
        raise ValueError('REPOSITORY_ROOT_SYMLINK_REJECTED')
    root = supplied.resolve(strict=True)
    package = Path(__file__).resolve().parent
    manifest = json.loads((package / 'SOURCE_MANIFEST.json').read_bytes())
    failures = verify(root, package, manifest, args.phase)
    print(json.dumps(dict(status='FAIL' if failures else 'PASS', phase=args.phase,
        repo_root=str(root), code_commit=manifest['code_commit'], files=len(manifest['files']),
        writes_performed=False, failures=failures), ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
