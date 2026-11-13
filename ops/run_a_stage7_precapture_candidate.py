"""Dry-run or manually capture A-share Stage7 in an isolated candidate root."""
import argparse
import json
from pathlib import Path

from stage_center.a_stage7_precapture import capture, dry_run


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True, help='A-share trade date (YYYYMMDD)')
    parser.add_argument('--candidate-root', type=Path, required=True)
    parser.add_argument('--candidate-current-sha256', required=True)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--shared-root', type=Path)
    parser.add_argument('--output-root', type=Path)
    args = parser.parse_args()
    if not args.dry_run and (args.shared_root is None or args.output_root is None):
        parser.error('capture requires --shared-root and an existing isolated --output-root')
    inputs = args.candidate_root, args.date, args.candidate_current_sha256
    try:
        result = dry_run(*inputs) if args.dry_run else capture(
            *inputs, shared_root=args.shared_root, output_root=args.output_root,
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {'status': 'CANNOT_CONFIRM', 'cannot_confirm': [str(error)], 'natural_verified': False,
                  'formal_pool_ready': False}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 2 if result['status'] == 'CANNOT_CONFIRM' else 0


if __name__ == '__main__':
    raise SystemExit(main())
