#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

_SCRIPT_PATH = Path(os.path.abspath(__file__))
_PROJECT_ROOT = next(
    (parent for parent in _SCRIPT_PATH.parents if (parent / "v4_migration").is_dir() and not (parent / "v4_migration").is_symlink()),
    None,
)
if _PROJECT_ROOT is None:
    raise RuntimeError("V4_PROJECT_ROOT_NOT_FOUND")
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _out(path: Path | None, obj: dict[str, Any]) -> None:
    if path is not None:
        from v4_migration.contracts import immutable_write_json

        immutable_write_json(path, obj)
    print(json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="V4 migration control plane; evidence-bound and fail-closed")
    sub = parser.add_subparsers(dest="cmd", required=True)

    preflight = sub.add_parser("preflight")
    preflight.add_argument("--inputs", type=Path, help="Untrusted legacy input; always blocked without current evidence binding")
    preflight.add_argument("--evidence-root", type=Path)
    preflight.add_argument("--output", type=Path)

    collect = sub.add_parser("collect-owner-bindings")
    collect.add_argument("--spec", required=True, type=Path)
    collect.add_argument("--allowed-root", action="append", default=[])
    collect.add_argument("--output", type=Path)

    dry_run = sub.add_parser("dry-run")
    dry_run.add_argument("--preflight", type=Path)
    dry_run.add_argument("--binding-review", type=Path, help="Accepted for legacy CLI compatibility; never imported or trusted")
    dry_run.add_argument("--cutover-id", required=True)
    dry_run.add_argument("--payload", type=Path)
    dry_run.add_argument("--output", type=Path)

    cutover = sub.add_parser("authorized-cutover")
    cutover.add_argument("--preflight", required=True, type=Path)
    cutover.add_argument("--binding-review", required=True, type=Path)
    cutover.add_argument("--authorization", required=True, type=Path)
    cutover.add_argument("--candidate-zip", required=True, type=Path)
    cutover.add_argument("--cutover-id", required=True)
    cutover.add_argument("--payload", type=Path)
    cutover.add_argument("--output", type=Path)

    retirement = sub.add_parser("retirement-check")
    retirement.add_argument("--input", required=True, type=Path)
    retirement.add_argument("--output", type=Path)

    runtime = sub.add_parser("runtime-assess")
    runtime.add_argument("--input", required=True, type=Path)
    runtime.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    from v4_migration.contracts import load_json

    if args.cmd == "preflight":
        from v4_migration.cutover_controller import build_current_preflight, build_preflight

        if args.evidence_root is not None:
            result = build_current_preflight(str(args.evidence_root))
        elif args.inputs is not None:
            result = build_preflight(load_json(args.inputs))
        else:
            result = build_preflight(None)
        _out(args.output, result)
        return 0 if result.get("status") != "BLOCKED" else 3

    if args.cmd == "collect-owner-bindings":
        from v4_migration.owner_bindings import collect_candidate

        specs = load_json(args.spec)
        result = collect_candidate(specs, allowed_roots=args.allowed_root)
        _out(args.output, result)
        return 0

    if args.cmd == "dry-run":
        from v4_migration.cutover_controller import execute_dry_run

        payload = load_json(args.payload) if args.payload is not None else {}
        result = execute_dry_run(cutover_id=args.cutover_id, payload=payload)
        _out(args.output, result)
        return 0

    if args.cmd == "authorized-cutover":
        result = {
            "schema": "v4_migration.cutover_execution.v2",
            "status": "BLOCKED",
            "blockers": [
                {"code": "AUTHORIZATION_TRUST_ROOT_UNCONFIGURED", "detail": None},
                {"code": "CUTOVER_OWNER_ADAPTERS_UNBOUND", "detail": None},
                {"code": "EXTERNAL_OWNER_PENDING", "detail": None},
            ],
            "production_switch_executed": False,
            "writer_fenced": False,
            "writer_drained": False,
            "canonical_root_changed": False,
            "scheduler_changed": False,
            "old_system_retired": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        _out(args.output, result)
        return 3

    if args.cmd == "retirement-check":
        from v4_migration.retirement import evaluate_retirement

        result = evaluate_retirement(load_json(args.input))
        _out(args.output, result)
        return 0 if str(result.get("status", "")).startswith("READY") else 3

    if args.cmd == "runtime-assess":
        from v4_migration.runtime_policy import evaluate_runtime

        result = evaluate_runtime(load_json(args.input))
        _out(args.output, result)
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
