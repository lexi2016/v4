#!/usr/bin/env python3
"""Prepare/import/rollback the one frozen announcement-selection product.

The CLI is read-only by default. Its only write target is the exact owner file
below; task receipts/backups are separate. --apply and --rollback are explicit
opt-ins and refuse any unexpected raw or embedded product SHA.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import stat
import sys
from pathlib import Path
from typing import Any, Mapping


TASK_ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_ANNOUNCEMENT_SELECTION_20261005")
OWNER_FILE = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/manager_auto_research/"
    "workspace_announcements/20260930/eastmoney_date_catalog/20260929/analysis.v1.json"
)
CANDIDATE_FILE = TASK_ROOT / "candidate_announcement_selection_20260929_delta1.json"
RECEIPT_FILE = TASK_ROOT / "announcement_selection_owner_import_receipt.json"
ROLLBACK_RECEIPT_FILE = TASK_ROOT / "announcement_selection_owner_rollback_receipt.json"

FROZEN = {
    "owner_file_sha256": "79f385f528400ff43c829d190748bb53df978729183ce80d5c62fdf0cb4b8892",
    "owner_product_sha256": "84090d130d1e19f714c8c0d63340e5eaae00f2506d5885af5afd385a3bc64486",
    "candidate_file_sha256": "61d8d33acba85bf4f10fa8efedfbe6e391a74cb5ae57277decf28514bb6fa465",
    "candidate_product_sha256": "6eedca28b8af6f40b3e9fcf738079fb454496704a33ede4510d2d7f509ab818b",
    "candidate_selection_sha256": "75a0b9271fbaefb7b6539ef0f85d474f9380e185cbd46b8c738870199728aa49",
    "records_canonical_sha256": "4205caaab01ee318e583ac6d339f27b6617d63479eefe52baa81baee15c593ed",
    "source_manifest_sha256": "7960f5f9c7208031c70f6b1e2db3ecd83403c238a9e2b13285c34d10694ad510",
    "target_trade_date": "20260930",
    "publication_date": "2026-09-29",
    "article_count": 234,
}


class OperatorError(RuntimeError):
    pass


def raw_sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_sha(value: Any) -> str:
    return raw_sha(canonical_bytes(value))


def _read_regular(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise OperatorError(f"expected regular non-symlink file: {path}")
    return path.read_bytes()


def _document(data: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OperatorError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise OperatorError(f"{label} must be a JSON object")
    return value


def _product_sha(product: Mapping[str, Any]) -> str:
    return canonical_sha({key: value for key, value in product.items() if key != "sha256"})


def _validate_product(product: Mapping[str, Any], expected_sha: str, label: str) -> None:
    if product.get("sha256") != expected_sha or _product_sha(product) != expected_sha:
        raise OperatorError(f"{label} embedded/canonical product SHA mismatch")


def _validate_owner(owner_bytes: bytes, expected: Mapping[str, Any]) -> dict[str, Any]:
    if raw_sha(owner_bytes) != expected["owner_file_sha256"]:
        raise OperatorError("owner raw SHA changed; refusing unknown overwrite")
    owner = _document(owner_bytes, "owner product")
    _validate_product(owner, expected["owner_product_sha256"], "owner")
    if "stock_selection" in owner:
        raise OperatorError("owner already has a selection extension")
    if canonical_sha(owner.get("records")) != expected["records_canonical_sha256"]:
        raise OperatorError("owner records changed")
    _validate_binding(owner, expected, "owner")
    return owner


def _validate_binding(product: Mapping[str, Any], expected: Mapping[str, Any], label: str) -> None:
    manifest = product.get("source_manifest")
    if not isinstance(manifest, Mapping):
        raise OperatorError(f"{label} source manifest missing")
    required = {
        "target_trade_date": expected["target_trade_date"],
        "publication_date": expected["publication_date"],
    }
    for key, value in required.items():
        if manifest.get(key) != value:
            raise OperatorError(f"{label} {key} mismatch")
    if product.get("source_manifest_sha256") != expected["source_manifest_sha256"]:
        raise OperatorError(f"{label} source manifest SHA mismatch")


def _validate_candidate(candidate_bytes: bytes, expected: Mapping[str, Any],
                        owner: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if raw_sha(candidate_bytes) != expected["candidate_file_sha256"]:
        raise OperatorError("candidate raw SHA mismatch")
    candidate = _document(candidate_bytes, "candidate product")
    _validate_product(candidate, expected["candidate_product_sha256"], "candidate")
    _validate_binding(candidate, expected, "candidate")
    if canonical_sha(candidate.get("records")) != expected["records_canonical_sha256"]:
        raise OperatorError("candidate source records differ from frozen owner records")
    if owner is not None and candidate.get("records") != owner.get("records"):
        raise OperatorError("candidate source records are not byte-equivalent as JSON values")
    extension = candidate.get("stock_selection")
    if not isinstance(extension, Mapping):
        raise OperatorError("candidate selection extension missing")
    if (extension.get("sha256") != expected["candidate_selection_sha256"]
            or canonical_sha({key: value for key, value in extension.items() if key != "sha256"})
            != expected["candidate_selection_sha256"]):
        raise OperatorError("candidate selection extension SHA mismatch")
    decisions = extension.get("article_decisions")
    if (extension.get("status") != "VERIFIED"
            or extension.get("article_count") != expected["article_count"]
            or not isinstance(decisions, list)
            or len(decisions) != expected["article_count"]):
        raise OperatorError("candidate selection count/status mismatch")
    if extension.get("base_product_sha256") != expected["owner_product_sha256"]:
        raise OperatorError("candidate base product identity mismatch")
    return candidate


def _backup_path(target: Path, expected: Mapping[str, Any]) -> Path:
    return target.with_name(f"{target.name}.pre-announcement-selection-{expected['owner_file_sha256'][:12]}.bak")


def _stage_path(target: Path, expected: Mapping[str, Any], operation: str) -> Path:
    return target.with_name(f".{target.name}.announcement-selection-{operation}-{expected['candidate_file_sha256'][:12]}.tmp")


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_exclusive(path: Path, data: bytes, mode: int) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    _fsync_dir(path.parent)


def _write_receipt_exclusive(path: Path, document: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise OperatorError(f"receipt already exists; refusing overwrite: {path}")
    data = (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _write_exclusive(path, data, 0o600)


def dry_run(target_path: Path = OWNER_FILE, candidate_path: Path = CANDIDATE_FILE,
            expected: Mapping[str, Any] = FROZEN) -> dict[str, Any]:
    owner_bytes = _read_regular(target_path)
    owner = _validate_owner(owner_bytes, expected)
    candidate_bytes = _read_regular(candidate_path)
    candidate = _validate_candidate(candidate_bytes, expected, owner)
    return {
        "schema_version": "v4.manager_research.announcement_selection_owner_operator.v1",
        "status": "DRY_RUN_READY",
        "owner_file": str(target_path),
        "owner_raw_sha256": raw_sha(owner_bytes),
        "owner_product_sha256": owner["sha256"],
        "candidate_file": str(candidate_path),
        "candidate_raw_sha256": raw_sha(candidate_bytes),
        "candidate_product_sha256": candidate["sha256"],
        "candidate_selection_sha256": candidate["stock_selection"]["sha256"],
        "records_canonical_sha256": canonical_sha(candidate["records"]),
        "article_count": len(candidate["records"]),
        "backup_path_if_applied": str(_backup_path(target_path, expected)),
        "owner_state_write": False,
    }


def _verify_exact_current(target: Path, expected_sha: str) -> tuple[bytes, os.stat_result]:
    data = _read_regular(target)
    info = target.stat()
    if raw_sha(data) != expected_sha:
        raise OperatorError("owner raw SHA changed; refusing unknown overwrite")
    return data, info


def _transaction_lock(target: Path):
    lock_path = target.with_name(f".{target.name}.announcement-selection.lock")
    if lock_path.exists() or lock_path.is_symlink():
        raise OperatorError(f"operator lock already exists; inspect before retry: {lock_path}")
    fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.write(fd, f"pid={os.getpid()}\n".encode())
    os.fsync(fd)
    _fsync_dir(target.parent)
    return lock_path, fd


def _release_lock(lock_path: Path, fd: int) -> None:
    os.close(fd)
    if lock_path.is_file() and not lock_path.is_symlink():
        lock_path.unlink()
        _fsync_dir(lock_path.parent)


def _atomic_replace(target: Path, data: bytes, mode: int, stage: Path,
                    expected_current_sha: str) -> str:
    if stage.exists() or stage.is_symlink():
        raise OperatorError(f"staging path already exists; refusing overwrite: {stage}")
    _write_exclusive(stage, data, stat.S_IMODE(mode))
    if raw_sha(_read_regular(target)) != expected_current_sha:
        raise OperatorError("owner raw SHA changed immediately before replace")
    os.replace(stage, target)
    _fsync_dir(target.parent)
    return raw_sha(_read_regular(target))


def apply_import(target_path: Path = OWNER_FILE, candidate_path: Path = CANDIDATE_FILE,
                 receipt_path: Path = RECEIPT_FILE, expected: Mapping[str, Any] = FROZEN) -> dict[str, Any]:
    if target_path.resolve() != OWNER_FILE.resolve():
        raise OperatorError("apply target must be the frozen absolute owner path")
    owner_bytes, owner_stat = _verify_exact_current(target_path, expected["owner_file_sha256"])
    owner = _validate_owner(owner_bytes, expected)
    candidate_bytes = _read_regular(candidate_path)
    candidate = _validate_candidate(candidate_bytes, expected, owner)
    backup = _backup_path(target_path, expected)
    stage = _stage_path(target_path, expected, "apply")
    for path in (stage, receipt_path):
        if path.exists() or path.is_symlink():
            raise OperatorError(f"output already exists; refusing overwrite: {path}")
    lock_path, lock_fd = _transaction_lock(target_path)
    try:
        # Save exact original bytes, in the same filesystem, before target replace.
        if backup.exists() or backup.is_symlink():
            if backup.is_symlink() or raw_sha(_read_regular(backup)) != expected["owner_file_sha256"]:
                raise OperatorError("existing backup is not the exact frozen owner bytes")
        else:
            _write_exclusive(backup, owner_bytes, stat.S_IMODE(owner_stat.st_mode))
        if raw_sha(_read_regular(backup)) != expected["owner_file_sha256"]:
            raise OperatorError("backup raw SHA mismatch")
        if raw_sha(_read_regular(target_path)) != expected["owner_file_sha256"]:
            raise OperatorError("owner raw SHA changed after backup; refusing replace")
        target_sha = _atomic_replace(target_path, candidate_bytes, owner_stat.st_mode,
                                     stage, expected["owner_file_sha256"])
        if target_sha != expected["candidate_file_sha256"]:
            raise OperatorError("post-replace target raw SHA mismatch; backup retained")
        receipt = {
            "schema_version": "v4.manager_research.announcement_selection_owner_import_receipt.v1",
            "status": "APPLIED",
            "owner_file": str(target_path),
            "previous_owner_raw_sha256": expected["owner_file_sha256"],
            "previous_owner_product_sha256": expected["owner_product_sha256"],
            "candidate_file_sha256": expected["candidate_file_sha256"],
            "candidate_product_sha256": candidate["sha256"],
            "candidate_selection_sha256": candidate["stock_selection"]["sha256"],
            "installed_owner_raw_sha256": target_sha,
            "backup_file": str(backup),
            "backup_raw_sha256": raw_sha(_read_regular(backup)),
            "atomic_replace": True,
            "owner_state_write": True,
        }
        _write_receipt_exclusive(receipt_path, receipt)
        return receipt
    finally:
        _release_lock(lock_path, lock_fd)


def rollback_import(target_path: Path = OWNER_FILE, candidate_path: Path = CANDIDATE_FILE,
                    receipt_path: Path = ROLLBACK_RECEIPT_FILE,
                    expected: Mapping[str, Any] = FROZEN) -> dict[str, Any]:
    if target_path.resolve() != OWNER_FILE.resolve():
        raise OperatorError("rollback target must be the frozen absolute owner path")
    current_bytes = _read_regular(target_path)
    if raw_sha(current_bytes) != expected["candidate_file_sha256"]:
        raise OperatorError("installed owner is not the exact candidate; refusing rollback over unknown change")
    current = _validate_candidate(current_bytes, expected)
    candidate_bytes = _read_regular(candidate_path)
    if raw_sha(candidate_bytes) != expected["candidate_file_sha256"]:
        raise OperatorError("frozen candidate file changed; refusing rollback")
    backup = _backup_path(target_path, expected)
    backup_bytes = _read_regular(backup)
    old_owner = _validate_owner(backup_bytes, expected)
    if raw_sha(backup_bytes) != expected["owner_file_sha256"]:
        raise OperatorError("backup is not the exact frozen original owner bytes")
    stage = _stage_path(target_path, expected, "rollback")
    if stage.exists() or stage.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():
        raise OperatorError("rollback staging/receipt path already exists; refusing overwrite")
    current_mode = stat.S_IMODE(target_path.stat().st_mode)
    lock_path, lock_fd = _transaction_lock(target_path)
    try:
        target_sha = _atomic_replace(target_path, backup_bytes, current_mode,
                                     stage, expected["candidate_file_sha256"])
        if target_sha != expected["owner_file_sha256"]:
            raise OperatorError("post-rollback raw SHA mismatch")
        receipt = {
            "schema_version": "v4.manager_research.announcement_selection_owner_rollback_receipt.v1",
            "status": "ROLLED_BACK",
            "owner_file": str(target_path),
            "restored_owner_raw_sha256": target_sha,
            "restored_owner_product_sha256": old_owner["sha256"],
            "removed_candidate_raw_sha256": raw_sha(current_bytes),
            "candidate_product_sha256": current["sha256"],
            "backup_file": str(backup),
            "backup_retained": True,
            "atomic_replace": True,
            "owner_state_write": True,
        }
        _write_receipt_exclusive(receipt_path, receipt)
        return receipt
    finally:
        _release_lock(lock_path, lock_fd)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="explicitly write the frozen candidate to the exact owner file")
    mode.add_argument("--rollback", action="store_true", help="explicitly restore exact original bytes from the operator backup")
    args = parser.parse_args(argv)
    try:
        if args.apply:
            result = apply_import()
        elif args.rollback:
            result = rollback_import()
        else:
            result = dry_run()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except (OSError, OperatorError, ValueError) as error:
        print(json.dumps({"status": "REFUSED", "error": f"{type(error).__name__}: {error}"},
                         ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
