#!/usr/bin/env python3
"""Read-only preimage/postimage check; never applies a patch or changes a service."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app-root', type=Path, required=True)
    parser.add_argument('--side', choices=('before', 'after'), required=True)
    parser.add_argument('--manifest', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'SOURCE_SHA256.json')
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    root = args.app_root.resolve(strict=True)
    failures = []
    checked = 0
    rows = [(row['path'], row.get(args.side + '_sha256')) for row in manifest['modified_files']]
    rows += [(row['path'], row['sha256']) for row in manifest['unchanged_prerequisites']]
    for relative, expected in rows:
        path = root / relative
        if not path.resolve().is_relative_to(root):
            failures.append(dict(path=relative, reason='PATH_OUTSIDE_APP_ROOT'))
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        checked += 1
        if actual != expected or (expected is None and path.exists()):
            failures.append(dict(path=relative, expected_sha256=expected, actual_sha256=actual))
    print(json.dumps(dict(status='PASS' if not failures else 'FAIL_CLOSED',
                          side=args.side, app_root=str(root), checked=checked,
                          mismatches=failures), ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
