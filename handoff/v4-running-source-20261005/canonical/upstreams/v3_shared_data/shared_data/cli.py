"""CLI: file-replay / verify / status. Fail closed: any error exits non-zero.

The CLI carries no allowlist entries and parses no user-selected path
configuration. Until a fixed production source is registered by trusted code,
``file-replay`` fails closed with a structured error; the formal API
(SafeRootStore + injected AllowlistRegistry) is the only way to replay.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .store import SafeRootStore, StoreError

DEFAULT_STORE = Path(__file__).resolve().parent.parent / ".runtime" / "data"
WRITER_OWNERS = ("v3_shared_data",)


class _JsonArgumentParser(argparse.ArgumentParser):
    """Argument-validation failures emit structured JSON instead of text."""

    def error(self, message: str) -> None:
        print(json.dumps({"ok": False, "error": message}, ensure_ascii=False, sort_keys=True))
        self.exit(2)


def _store(args: argparse.Namespace) -> SafeRootStore:
    root = Path(args.store).resolve()
    return SafeRootStore(root=root)


def _print(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2))


def cmd_file_replay(args: argparse.Namespace) -> int:
    try:
        result = _store(args).replay_file(
            owner=args.owner,
            trade_date=args.date,
            role=args.role,
            source_id=args.source_id,
            stage_id=args.stage,
            dry_run=args.dry_run,
        )
    except StoreError as error:
        _print({"ok": False, "error": str(error)})
        return 2
    except (ValueError, FileNotFoundError) as error:
        _print({"ok": False, "error": str(error)})
        return 2
    _print({"ok": True, **result})
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    try:
        result = _store(args).verify_latest(trade_date=args.date, role=args.role)
    except StoreError as error:
        _print({"ok": False, "error": str(error)})
        return 2
    except (ValueError, FileNotFoundError) as error:
        _print({"ok": False, "error": str(error)})
        return 2
    _print({"ok": True, **result})
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    _print(_store(args).status())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = _JsonArgumentParser(
        prog="shared_data",
        description="v3_shared_data raw store (file replay only; fail closed).",
    )
    parser.add_argument("--store", default=str(DEFAULT_STORE), help="store root (default: .runtime/data)")
    sub = parser.add_subparsers(dest="command", required=True)

    replay = sub.add_parser("file-replay", help="replay an allowlisted raw CSV into an immutable run dir")
    replay.add_argument("--owner", required=True, choices=WRITER_OWNERS)
    replay.add_argument("--date", required=True, help="trade date YYYYMMDD")
    replay.add_argument("--role", required=True, help="date role, e.g. A_SHARE_1MIN_RAW_FILE_REPLAY")
    replay.add_argument("--source-id", required=True)
    replay.add_argument("--stage", default=None, help="stage id (must be allowlisted for the source)")
    replay.add_argument("--dry-run", action="store_true", help="validate without writing")
    replay.set_defaults(func=cmd_file_replay)

    verify = sub.add_parser("verify", help="verify the latest run for a (date, role)")
    verify.add_argument("--date", required=True)
    verify.add_argument("--role", required=True)
    verify.set_defaults(func=cmd_verify)

    status = sub.add_parser("status", help="show store summary")
    status.set_defaults(func=cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
