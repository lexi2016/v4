#!/usr/bin/env python3
"""Read-only source comparison. Never applies a patch or changes a service."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', required=True)
    parser.add_argument('--manifest', type=Path,
                        default=Path(__file__).resolve().parents[1] / 'SHA_MANIFEST.json')
    args = parser.parse_args()
    root = Path(args.source_root).resolve(strict=True)
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    records = []
    for entry in manifest['changes']:
        relative = Path(entry['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Manifest path escapes the selected source root')
        target = root / relative
        if not target.resolve().is_relative_to(root):
            state, actual = 'PATH_ESCAPE', None
        elif any(p.is_symlink() for p in [target, *target.parents] if p != root and root in p.parents):
            state, actual = 'SYMLINK_REQUIRES_REVIEW', None
        elif not target.exists():
            actual = None
            state = 'BEFORE' if entry['before_sha256'] is None else 'MISSING'
        elif not target.is_file() or target.stat().st_size > 8 * 1024 * 1024:
            state, actual = 'UNEXPECTED_FILE_TYPE_OR_SIZE', None
        else:
            actual = hashlib.sha256(target.read_bytes()).hexdigest()
            state = ('AFTER' if actual == entry['after_sha256'] else
                     'BEFORE' if actual == entry['before_sha256'] else 'CONFLICT')
        records.append({'path': entry['path'], 'state': state,
                        'actual_sha256': actual,
                        'before_sha256': entry['before_sha256'],
                        'after_sha256': entry['after_sha256'],
                        'canonical_sha256_at_input_capture': entry.get('canonical_sha256_at_input_capture')})
    states = {r['state'] for r in records}
    status = ('BEFORE_ALL_READY_FOR_APPLY_CHECK' if states == {'BEFORE'} else
              'AFTER_ALL_SOURCE_BYTES_MATCH' if states == {'AFTER'} else
              'STOP_MIXED_OR_CONFLICT_REQUIRES_THREE_WAY_REVIEW')
    print(json.dumps({'schema': 'v4.three_lane_handoff.source_preflight.v1',
        'checked_at': datetime.now(timezone.utc).isoformat(),
        'requested_root': args.source_root, 'resolved_root': str(root),
        'status': status, 'loaded_process_identity': 'NOT_VERIFIED',
        'deployment_verified': False, 'write_performed': False,
        'files': records}, ensure_ascii=False, indent=2))
    return 0 if states in ({'BEFORE'}, {'AFTER'}) else 2


if __name__ == '__main__':
    raise SystemExit(main())
