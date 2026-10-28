#!/usr/bin/env python3
"""Read-only owner intake; neither subcommand can perform a cutover."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

# In both an isolated candidate layout and a reviewed main layout this is the project root.
PROJECT_ROOT = Path(__file__).absolute().parents[2]
sys.dont_write_bytecode = True
sys.path.insert(0, str(PROJECT_ROOT))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    collect = sub.add_parser('collect', help='Inspect explicitly supplied source/receipt files, not directories')
    collect.add_argument('--request', required=True, type=Path)
    collect.add_argument('--request-sha256', required=True)
    collect.add_argument('--allow-root', action='append', default=[])
    collect.add_argument('--output', type=Path, help='Optional exclusive report outside every input/protected root')
    simulate = sub.add_parser('simulate', help='Print contract obligations only; no adapter loading')
    simulate.add_argument('--scenario-id', required=True)
    args = p.parse_args(argv)
    from v4_migration.owner_binding_intake import collect_request, simulation_contract, validate_output_path
    from v4_migration.contracts import immutable_write_json
    try:
        if args.command == 'collect':
            out = validate_output_path(args.output, args.request, args.allow_root, expected_sha256=args.request_sha256) if args.output else None
            result = collect_request(args.request, expected_sha256=args.request_sha256, allowed_roots=args.allow_root)
            if out is not None:
                immutable_write_json(out, result)
            exit_code = 3 if (result['missing_action_count'] or result['file_error_count']
                              or result['primitive_error_count']) else 0
        else:
            result = simulation_contract(args.scenario_id)
            # A protocol description never represents operational acceptance.
            exit_code = 3
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False))
        return exit_code
    except (OSError, ValueError, TypeError, RecursionError) as exc:
        print(json.dumps({'status': 'READONLY_INTAKE_REJECTED', 'error': str(exc),
                          'error_type': type(exc).__name__, 'execution_performed': False}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
