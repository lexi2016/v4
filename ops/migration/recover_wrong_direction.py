"""Fail-closed recovery for the 20260731 wrong-direction V3.5 batch.

This utility intentionally has no dependency beyond the Python standard library.
It records a dry-run inventory before it can restore Git blobs or quarantine data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


TRACKED_PATHS = (
    "apps/api/v35_api/research_router.py", "apps/web/src/components/review/AshareReviewPanel.vue",
    "apps/web/src/components/review/ReviewEvidencePanel.vue", "apps/web/src/contracts/research.ts",
    "apps/web/src/contracts/review.ts", "apps/web/src/views/ResearchView.spec.ts",
    "apps/web/src/views/ResearchView.vue", "apps/web/src/views/ReviewView.spec.ts",
    "domains/a_share_review.py", "domains/preselection.py", "domains/research.py",
    "domains/review_envelope.py", "infrastructure/a_share_review_store.py",
    "infrastructure/data_store.py", "infrastructure/research_store.py",
    "ops/import_a_share_review_reference.py", "ops/import_preselection.py",
    "ops/import_research_archive.py", "tests/test_a_share_review.py",
    "tests/test_a_share_review_store.py", "tests/test_preselection_slice.py",
)
INJECTED_RUNTIME_PATHS = (
    "a_share_reviews/20260731.json", "a_share_reviews/receipts/20260731.json",
    "preselection/20260731.json", "receipts/20260731.json",
    "receipts/research/archives/20260731.json", "receipts/research/desks/20260731.json",
    "receipts/stage_references/20260731/STAGE_0925.json", "research/archives/20260731.json",
    "research/desks/20260731.json", "stage_references/20260731/STAGE_0925.json",
)
PLAN_PATHS = (
    "docs/superpowers/plans/2026-07-31-v35-runtime-and-review-remediation.md",
    "docs/superpowers/plans/2026-08-02-v35-equivalent-rebuild-corrective-plan.md",
)
OWNED_UNTRACKED_PATHS = (
    "ops/migration/recover_wrong_direction.py",
    "tests/test_recover_wrong_direction.py",
    "docs/evidence/v35-corrective-authority-20260802.json",
    ".superpowers/sdd/2026-08-02-v35-equivalent-rebuild-corrective-plan/task-1-report.md",
)
ORACLE_PATHS = (
    ".runtime/evidence/phase2/20260731/preselection_v3_20260731.json",
    ".runtime/evidence/phase2/20260731/stage_0925_v3_20260731.json",
    ".runtime/evidence/phase2/20260731/research_lane_v3_20260731.json",
)
RECOVERY_PREFIX = ".runtime/evidence/recovery/"
OFFICIAL_LATEST_POINTERS = ("research/latest.json", "research/hourly/latest.json")


class RecoveryError(RuntimeError):
    """Raised when a recovery precondition cannot be proven."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git(root: Path, *args: str) -> bytes:
    try:
        return subprocess.run(("git", *args), cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout
    except subprocess.CalledProcessError as error:
        raise RecoveryError(error.stderr.decode("utf-8", "replace").strip() or "git command failed") from error


def current_head(repo_root: Path) -> str:
    return _git(Path(repo_root), "rev-parse", "HEAD").decode("ascii").strip()


def _status(root: Path) -> dict[str, str]:
    raw = _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all")
    rows: dict[str, str] = {}
    pieces = raw.split(b"\0")
    index = 0
    while index < len(pieces) - 1:
        entry = pieces[index]
        index += 1
        if not entry:
            continue
        code, encoded_path = entry[:2].decode("ascii"), entry[3:]
        if code[0] in "RC":
            if index >= len(pieces):
                raise RecoveryError("invalid rename status")
            index += 1
        path = encoded_path.decode("utf-8", "surrogateescape").replace("\\", "/")
        if not path.startswith((RECOVERY_PREFIX, ".runtime/data/")):
            rows[path] = code
    return rows


def _validate_status(root: Path) -> dict[str, str]:
    rows = _status(root)
    expected = {path: " M" for path in TRACKED_PATHS}
    expected.update({path: "??" for path in PLAN_PATHS})
    allowed = set(expected).union(OWNED_UNTRACKED_PATHS)
    unexpected = sorted(set(rows).difference(allowed))
    missing = sorted(set(expected).difference(rows))
    wrong = sorted(path for path in set(rows).intersection(expected) if rows[path] != expected[path])
    wrong.extend(sorted(path for path in set(rows).intersection(OWNED_UNTRACKED_PATHS) if rows[path] != "??"))
    if unexpected or missing or wrong:
        raise RecoveryError(f"unexpected dirty path: unexpected={unexpected}; missing={missing}; wrong_status={wrong}")
    return rows


def _file_inventory(root: Path) -> dict[str, str]:
    runtime = root / ".runtime/data"
    required = (*TRACKED_PATHS, *PLAN_PATHS, *(f".runtime/data/{item}" for item in INJECTED_RUNTIME_PATHS),
                ".runtime/data/manifest.json", ".runtime/data/date_catalog.json", *ORACLE_PATHS)
    hashes: dict[str, str] = {}
    for relative in required:
        target = root / relative
        if not target.is_file():
            raise RecoveryError(f"missing frozen file: {relative}")
        hashes[relative] = _sha256(target)
    return hashes


def _runtime_hashes(root: Path) -> dict[str, str]:
    data_root = root / ".runtime/data"
    return {path: _sha256(data_root / path) for path in INJECTED_RUNTIME_PATHS}


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _reference_files(data_root: Path) -> list[Path]:
    """The official reference surface; backup/lookalike files are excluded."""
    files = set(data_root.rglob("manifest.json"))
    files.add(data_root / "date_catalog.json")
    files.update(data_root / relative for relative in OFFICIAL_LATEST_POINTERS)
    return sorted(path for path in files if path.is_file())


def _encoded_json(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _reference_record(root: Path, path: Path, target_hashes: dict[str, str]) -> dict[str, Any]:
    relative = _relative(root / ".runtime/data", path)
    before = path.read_bytes()
    record: dict[str, Any] = {
        "path": relative,
        "before_sha256": hashlib.sha256(before).hexdigest(),
    }
    if relative == "date_catalog.json":
        record.update({"kind": "date_catalog", "action": "preserve", "after_sha256": record["before_sha256"]})
        return record
    try:
        value = json.loads(before.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"invalid runtime reference file: {path}") from error
    if not isinstance(value, dict):
        raise RecoveryError(f"ambiguous runtime reference file: {path}")
    if path.name == "manifest.json":
        for target, digest in target_hashes.items():
            if target in value and value[target] != digest:
                raise RecoveryError(f"ambiguous manifest reference: {path}")
        updated = {key: item for key, item in value.items() if key not in target_hashes}
        path_values = [item for item in updated.values() if isinstance(item, str) and item in target_hashes]
        if path_values:
            raise RecoveryError(f"ambiguous non-manifest pointer: {path}")
        after = _encoded_json(updated) if updated != value else before
        record.update({"kind": "manifest", "action": "rewrite" if updated != value else "preserve", "after_sha256": hashlib.sha256(after).hexdigest()})
        return record
    path_values = [item for item in value.values() if isinstance(item, str) and item in target_hashes]
    if not path_values:
        record.update({"kind": "latest", "action": "preserve", "after_sha256": record["before_sha256"]})
        return record
    pointer_hashes = [item for item in value.values() if isinstance(item, str) and item in target_hashes.values()]
    if len(path_values) != 1 or len(pointer_hashes) != 1 or target_hashes[path_values[0]] != pointer_hashes[0]:
        raise RecoveryError(f"ambiguous latest pointer: {path}")
    record.update({"kind": "latest", "action": "delete", "after_sha256": None})
    return record


def _reference_plan(root: Path, target_hashes: dict[str, str]) -> list[dict[str, Any]]:
    return [_reference_record(root, path, target_hashes) for path in _reference_files(root / ".runtime/data")]


def _validate_before_evidence(root: Path, expected_head: str) -> tuple[dict[str, str], dict[str, str], list[dict[str, Any]]]:
    if current_head(root) != expected_head:
        raise RecoveryError("unexpected HEAD")
    status, hashes = _validate_status(root), _file_inventory(root)
    return status, hashes, _reference_plan(root, _runtime_hashes(root))


def _evidence_dir(root: Path, expected_head: str) -> Path:
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return root / ".runtime/evidence/recovery" / f"{stamp}-{expected_head[:12]}"


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_bytes(_encoded_json(value))
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _build_dry_run(root: Path, expected_head: str) -> dict[str, Any]:
    status, hashes, references = _validate_before_evidence(root, expected_head)
    evidence = _evidence_dir(root, expected_head)
    evidence.mkdir(parents=True, exist_ok=False)
    patch = _git(root, "diff", "--binary", "--no-ext-diff")
    _write_bytes(evidence / "dirty.patch", patch)
    _write_bytes(evidence / "status.porcelain", _git(root, "status", "--porcelain=v1", "-z", "--untracked-files=all"))
    data_root = root / ".runtime/data"
    shutil.copyfile(data_root / "manifest.json", evidence / "manifest.original.json")
    shutil.copyfile(data_root / "date_catalog.json", evidence / "date_catalog.original.json")
    for relative in TRACKED_PATHS:
        _write_bytes(evidence / "preapply_snapshot" / "tracked" / relative, (root / relative).read_bytes())
    for reference in references:
        _write_bytes(evidence / "preapply_snapshot" / "references" / reference["path"], (data_root / reference["path"]).read_bytes())
    operation = {
        "schema_version": "v35_wrong_direction_recovery.v1", "status": "DRY_RUN_VALIDATED",
        "expected_head": expected_head, "run_id": evidence.name, "before_status": status,
        "sha256": hashes, "runtime_sha256": _runtime_hashes(root),
        "tracked_paths": list(TRACKED_PATHS), "injected_runtime_paths": list(INJECTED_RUNTIME_PATHS),
        "oracle_paths": list(ORACLE_PATHS), "date_catalog_action": "preserved_no_path_sha_reference",
        "reference_files": references,
    }
    _write_json(evidence / "hash-inventory.json", {"sha256": hashes, "runtime_sha256": operation["runtime_sha256"]})
    _write_json(evidence / "operation-manifest.json", operation)
    return {"status": "DRY_RUN_VALIDATED", "run_id": evidence.name, "evidence_dir": str(evidence)}


def _load_operation(evidence: Path) -> dict[str, Any]:
    try:
        value = json.loads((evidence / "operation-manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RecoveryError("invalid recovery evidence manifest") from error
    if not isinstance(value, dict):
        raise RecoveryError("invalid recovery evidence manifest")
    return value


def _pending_evidence(root: Path, expected_head: str) -> tuple[Path, dict[str, Any]]:
    parent = root / ".runtime/evidence/recovery"
    candidates = [] if not parent.is_dir() else sorted(parent.glob(f"*-{expected_head[:12]}"))
    manifests = [(path, _load_operation(path)) for path in candidates if (path / "operation-manifest.json").is_file()]
    matches = [(path, manifest) for path, manifest in manifests if manifest.get("expected_head") == expected_head]
    if not matches:
        raise RecoveryError("apply requires a prior matching dry-run")
    if len(matches) != 1:
        raise RecoveryError("ambiguous recovery evidence")
    return matches[0]


def _assert_unchanged(root: Path, operation: dict[str, Any]) -> None:
    _validate_before_evidence(root, str(operation["expected_head"]))
    expected_references = operation.get("reference_files")
    if not isinstance(expected_references, list):
        raise RecoveryError("missing reference evidence")
    actual_references = _reference_plan(root, _runtime_hashes(root))
    if actual_references != expected_references:
        raise RecoveryError("reference SHA drift between dry-run and apply")
    expected = operation.get("sha256")
    actual = _file_inventory(root)
    if actual != expected:
        raise RecoveryError("SHA drift between dry-run and apply")


def _preflight_destinations(evidence: Path) -> None:
    destination_root = evidence / "injected_runtime"
    for relative in INJECTED_RUNTIME_PATHS:
        destination = destination_root / relative
        if destination.exists():
            raise RecoveryError(f"destination collision: {destination}")
        parent = destination.parent
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            raise RecoveryError(f"destination is not writable: {destination}")


def _apply_reference(root: Path, record: dict[str, Any], target_hashes: dict[str, str]) -> None:
    path = root / ".runtime/data" / record["path"]
    current = _reference_record(root, path, target_hashes)
    if current != record:
        raise RecoveryError("reference SHA drift between dry-run and apply")
    if record["action"] == "preserve":
        return
    if record["action"] == "delete":
        path.unlink()
        return
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    for target in target_hashes:
        value.pop(target, None)
    _write_bytes(path, _encoded_json(value))


def _rollback(root: Path, evidence: Path, operation: dict[str, Any]) -> None:
    snapshot = evidence / "preapply_snapshot"
    references = operation.get("reference_files")
    if not isinstance(references, list):
        raise RecoveryError("rollback evidence is incomplete")
    for record in references:
        relative = str(record["path"])
        _write_bytes(root / ".runtime/data" / relative, (snapshot / "references" / relative).read_bytes())
    for relative in TRACKED_PATHS:
        _write_bytes(root / relative, (snapshot / "tracked" / relative).read_bytes())
    data_root, quarantine = root / ".runtime/data", evidence / "injected_runtime"
    for relative, digest in operation["runtime_sha256"].items():
        source, destination = data_root / relative, quarantine / relative
        if destination.exists():
            if source.exists():
                raise RecoveryError(f"rollback collision: {relative}")
            shutil.move(str(destination), str(source))
        if not source.is_file() or _sha256(source) != digest or destination.exists():
            raise RecoveryError(f"rollback runtime mismatch: {relative}")
    for record in references:
        path = root / ".runtime/data" / str(record["path"])
        if _sha256(path) != record["before_sha256"]:
            raise RecoveryError(f"rollback reference mismatch: {record['path']}")
    for relative in TRACKED_PATHS:
        if (root / relative).read_bytes() != (snapshot / "tracked" / relative).read_bytes():
            raise RecoveryError(f"rollback tracked mismatch: {relative}")


def _validate_applied(root: Path, expected_head: str, evidence: Path, operation: dict[str, Any]) -> None:
    if current_head(root) != expected_head:
        raise RecoveryError("applied-state HEAD drift")
    references = operation.get("reference_files")
    if not isinstance(references, list):
        raise RecoveryError("applied-state missing reference evidence")
    expected_reference_paths = [str(record["path"]) for record in references if record["after_sha256"] is not None]
    current_reference_paths = [_relative(root / ".runtime/data", path) for path in _reference_files(root / ".runtime/data")]
    if current_reference_paths != expected_reference_paths:
        raise RecoveryError("applied-state reference surface drift")
    for relative in TRACKED_PATHS:
        expected = _git(root, "show", f"{expected_head}:{relative}")
        if not (root / relative).is_file() or (root / relative).read_bytes() != expected:
            raise RecoveryError(f"applied-state tracked drift: {relative}")
    frozen = operation.get("sha256", {})
    for relative in (*PLAN_PATHS, *ORACLE_PATHS):
        if not (root / relative).is_file() or _sha256(root / relative) != frozen.get(relative):
            raise RecoveryError(f"applied-state frozen drift: {relative}")
    for relative, digest in operation.get("runtime_sha256", {}).items():
        source, destination = root / ".runtime/data" / relative, evidence / "injected_runtime" / relative
        if source.exists() or not destination.is_file() or _sha256(destination) != digest:
            raise RecoveryError(f"applied-state quarantine drift: {relative}")
    for record in references:
        path = root / ".runtime/data" / str(record["path"])
        expected_sha = record["after_sha256"]
        if expected_sha is None:
            if path.exists():
                raise RecoveryError(f"applied-state reference drift: {record['path']}")
        elif not path.is_file() or _sha256(path) != expected_sha:
            raise RecoveryError(f"applied-state reference drift: {record['path']}")


def _apply(root: Path, expected_head: str) -> dict[str, Any]:
    evidence, operation = _pending_evidence(root, expected_head)
    if operation.get("status") == "APPLIED":
        _validate_applied(root, expected_head, evidence, operation)
        return {"status": "ALREADY_APPLIED", "run_id": evidence.name, "evidence_dir": str(evidence), "quarantined_paths": list(INJECTED_RUNTIME_PATHS)}
    if operation.get("status") != "DRY_RUN_VALIDATED":
        raise RecoveryError("recovery evidence is not applicable")
    _assert_unchanged(root, operation)
    _preflight_destinations(evidence)
    data_root = root / ".runtime/data"
    target_hashes = _runtime_hashes(root)
    try:
        for reference in operation["reference_files"]:
            _apply_reference(root, reference, target_hashes)
        for relative in TRACKED_PATHS:
            _write_bytes(root / relative, _git(root, "show", f"{expected_head}:{relative}"))
        destination = evidence / "injected_runtime"
        for relative in INJECTED_RUNTIME_PATHS:
            source, target = data_root / relative, destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(target))
        operation["after_status"] = _status(root)
        operation["quarantined_paths"] = list(INJECTED_RUNTIME_PATHS)
        operation["status"] = "APPLIED"
        _write_json(evidence / "operation-manifest.json", operation)
    except Exception as error:
        try:
            _rollback(root, evidence, operation)
        except Exception as rollback_error:
            raise RecoveryError("apply failed; rollback failed") from rollback_error
        operation["status"] = "DRY_RUN_VALIDATED"
        operation.pop("after_status", None)
        operation.pop("quarantined_paths", None)
        operation["last_apply_error"] = str(error)
        try:
            _write_json(evidence / "operation-manifest.json", operation)
        except Exception as evidence_error:
            raise RecoveryError("apply failed; rollback evidence failed") from evidence_error
        raise RecoveryError("apply failed; rollback completed") from error
    return {"status": "APPLIED", "run_id": evidence.name, "evidence_dir": str(evidence), "quarantined_paths": list(INJECTED_RUNTIME_PATHS)}


def recover(repo_root: Path, expected_head: str, *, dry_run: bool = False, apply: bool = False) -> dict[str, Any]:
    if dry_run == apply:
        raise RecoveryError("choose exactly one of dry_run or apply")
    root = Path(repo_root).resolve()
    return _build_dry_run(root, expected_head) if dry_run else _apply(root, expected_head)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        print(json.dumps(recover(args.repo_root, args.expected_head, dry_run=args.dry_run, apply=args.apply), sort_keys=True))
    except RecoveryError as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
