#!/usr/bin/env python3
"""Guarded installer for the reviewed, two-symbol Futu chart profile.

The default invocation is a read-only dry run. Activation requires the fixed
independent-review receipt. The script only writes the exact targets below and
keeps byte-preserving backups and an activation record under J/implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TASK_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION_ROOT = TASK_ROOT / "implementation"
ARTIFACT_ROOT = IMPLEMENTATION_ROOT / "futu_qfq_profile_v1"
REVIEW_RECEIPT = TASK_ROOT / "review" / "FUTU_PROFILE_REVIEW_PASS.json"
ACTIVATION_ROOT = IMPLEMENTATION_ROOT / "activation_backups"
PROFILE_ID = "FUTU_QFQ_ASOF"
REVIEWER_ID = "/root/yellow_line_review"
SCOPE_ID = "FUTU_PROFILE_CHART_DERIVATIVE"

STATE_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state"
)
READER_DIR = STATE_ROOT / "workspace/数据/data_layer_interface_current"
PROFILE_DIR = STATE_ROOT / "research_panel_daily/formula_profiles/futu_qfq"
SKILL_DIR = Path("/Users/lexi/.codex/skills/zettaranc-skill")


class InstallError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise InstallError(f"INVALID_JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise InstallError(f"EXPECTED_JSON_OBJECT: {path}")
    return value


def candidate_paths() -> dict[str, Path]:
    return {
        "reader": SOURCE_ROOT / "upstreams/v3_shared_data/shared_data/selector_data_layer_interface.py",
        "helper": SOURCE_ROOT / "upstreams/v3_shared_data/shared_data/futu_formula_projection.py",
        "profile": ARTIFACT_ROOT / "futu_formula_profile.json",
        "cache": ARTIFACT_ROOT / "futu_qfq_derived_cache.parquet",
        "skill_doc": IMPLEMENTATION_ROOT / "staged_skill_docs/SKILL.md",
        "contract_doc": IMPLEMENTATION_ROOT / "staged_skill_docs/PANEL_READ_CONTRACT.md",
    }


def target_specs(candidates: dict[str, Path]) -> list[dict[str, Any]]:
    return [
        {"id": "profile_cache", "source_key": "cache", "path": PROFILE_DIR / "futu_qfq_derived_cache.parquet", "before_sha256": None},
        {"id": "profile_manifest", "source_key": "profile", "path": PROFILE_DIR / "futu_formula_profile.json", "before_sha256": None},
        {"id": "reader_profile_manifest", "source_key": "profile", "path": READER_DIR / "futu_formula_profile.json", "before_sha256": None},
        {"id": "projection_helper", "source_key": "helper", "path": READER_DIR / "futu_formula_projection.py", "before_sha256": None},
        {"id": "selector_reader", "source_key": "reader", "path": READER_DIR / "DATA_LAYER_INTERFACE.py", "before_sha256": "79d79dd1f7fd454a01a00e532c015779e3f86d37196903066b9800fb9aefede6"},
        {"id": "skill_doc", "source_key": "skill_doc", "path": SKILL_DIR / "SKILL.md", "before_sha256": "96ee2379cb1a636cac12e8dc147bce39026b60ce15c5dec46036fe2886c1839e"},
        {"id": "panel_contract", "source_key": "contract_doc", "path": SKILL_DIR / "PANEL_READ_CONTRACT.md", "before_sha256": "4d6ef86248f16a2d4596c18e68dbc535f95e7f8120bb230af29112876a4ac1ab"},
    ]


def _load_helper(path: Path):
    spec = importlib.util.spec_from_file_location("futu_profile_installer_helper", path)
    if spec is None or spec.loader is None:
        raise InstallError(f"HELPER_LOAD_FAILED: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise InstallError(f"HELPER_LOAD_FAILED: {exc}") from exc
    return module


def preflight() -> tuple[list[dict[str, Any]], dict[str, str], dict[str, Any]]:
    candidates = candidate_paths()
    missing = [str(path) for path in candidates.values() if not path.is_file()]
    if missing:
        raise InstallError(f"CANDIDATE_FILE_MISSING: {missing}")
    hashes = {key: sha256_file(path) for key, path in candidates.items()}

    profile = load_json(candidates["profile"])
    if profile.get("profile_id") != PROFILE_ID or profile.get("chart_only") is not True:
        raise InstallError("PROFILE_IDENTITY_OR_SCOPE_MISMATCH")
    profile_payload = {key: value for key, value in profile.items() if key != "manifest_sha256"}
    if profile.get("manifest_sha256") != json_sha256(profile_payload):
        raise InstallError("PROFILE_MANIFEST_SHA256_MISMATCH")
    helper = _load_helper(candidates["helper"])
    try:
        bound = helper.validate_profile(
            ARTIFACT_ROOT,
            Path(profile["source_panel_path"]),
            profile.get("asof_date"),
        )
    except Exception as exc:
        raise InstallError(f"PROFILE_ARTIFACT_VALIDATION_FAILED: {exc}") from exc
    if bound["profile_sha256"] != hashes["profile"]:
        raise InstallError("PROFILE_HASH_READBACK_MISMATCH")

    factor_metadata = profile["factor_metadata"]
    for code, entry in factor_metadata["symbols"].items():
        source_csv = Path(entry["source_csv_path"])
        if not source_csv.is_file() or sha256_file(source_csv) != entry["source_csv_sha256"]:
            raise InstallError(f"FACTOR_CSV_SOURCE_SHA256_MISMATCH: {code}")
    rehab_report = TASK_ROOT / "FUTU_REHAB_CROSSCHECK.json"
    if not rehab_report.is_file() or sha256_file(rehab_report) != factor_metadata.get("source_capture_sha256"):
        raise InstallError("FACTOR_CAPTURE_REPORT_SHA256_MISMATCH")
    formula_source = Path(profile["formula_source_path"])
    if not formula_source.is_file() or sha256_file(formula_source) != profile.get("formula_source_sha256"):
        raise InstallError("PINNED_FORMULA_SOURCE_SHA256_MISMATCH")
    user_formula = TASK_ROOT / "USER_FORMULA.txt"
    if not user_formula.is_file() or sha256_file(user_formula) != profile.get("user_formula_sha256"):
        raise InstallError("USER_FORMULA_SHA256_MISMATCH")

    specs = target_specs(candidates)
    for spec in specs:
        target = spec["path"]
        expected = spec["before_sha256"]
        if target.exists():
            if not target.is_file():
                raise InstallError(f"TARGET_NOT_REGULAR_FILE: {target}")
            actual = sha256_file(target)
            if expected is None or actual != expected:
                raise InstallError(f"TARGET_DRIFT_OR_UNEXPECTED_EXISTENCE: {target}: {actual}")
            spec["actual_before_sha256"] = actual
            spec["before_exists"] = True
        else:
            if expected is not None:
                raise InstallError(f"TARGET_MISSING: {target}")
            spec["actual_before_sha256"] = None
            spec["before_exists"] = False
        source = candidates[spec["source_key"]]
        spec["source_path"] = source
        spec["after_sha256"] = hashes[spec["source_key"]]
    return specs, hashes, bound


def _require_review_receipt(hashes: dict[str, str]) -> dict[str, Any]:
    receipt = load_json(REVIEW_RECEIPT)
    if receipt.get("status") != "PASS":
        raise InstallError("INDEPENDENT_REVIEW_NOT_PASS")
    if receipt.get("reviewer_agent") != REVIEWER_ID:
        raise InstallError("REVIEWER_IDENTITY_MISMATCH")
    if receipt.get("scope_id") != SCOPE_ID:
        raise InstallError("REVIEW_SCOPE_MISMATCH")
    expected = {
        "reader_sha256": hashes["reader"],
        "helper_sha256": hashes["helper"],
        "profile_sha256": hashes["profile"],
        "cache_sha256": hashes["cache"],
        "skill_doc_sha256": hashes["skill_doc"],
        "contract_doc_sha256": hashes["contract_doc"],
    }
    if receipt.get("reviewed_hashes") != expected:
        raise InstallError("REVIEWED_HASHES_DO_NOT_MATCH_CANDIDATE")
    return receipt


def _write_atomic(path: Path, payload: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_fd = None
        if directory_fd is not None:
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except Exception:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    _write_atomic(path, payload, 0o600)


def _backup_existing(specs: list[dict[str, Any]], backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=False)
    for spec in specs:
        if spec["before_exists"]:
            backup = backup_dir / f"{spec['id']}.before"
            shutil.copy2(spec["path"], backup)
            if sha256_file(backup) != spec["actual_before_sha256"]:
                raise InstallError(f"BACKUP_SHA256_MISMATCH: {spec['id']}")
            spec["backup_path"] = str(backup)
        else:
            spec["backup_path"] = None


def _restore_one(spec: dict[str, Any], *, verify_installed: bool) -> None:
    target = Path(spec["path"])
    before_sha = spec.get("actual_before_sha256", spec.get("before_sha256"))
    if verify_installed:
        if not target.is_file() or sha256_file(target) != spec["after_sha256"]:
            raise InstallError(f"ROLLBACK_INSTALLED_SHA256_MISMATCH: {target}")
    if spec["before_exists"]:
        backup = Path(spec["backup_path"])
        if not backup.is_file() or sha256_file(backup) != before_sha:
            raise InstallError(f"ROLLBACK_BACKUP_SHA256_MISMATCH: {backup}")
        mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else stat.S_IMODE(backup.stat().st_mode)
        _write_atomic(target, backup.read_bytes(), mode)
    else:
        if target.exists():
            target.unlink()


def apply_install(specs: list[dict[str, Any]], hashes: dict[str, str], review: dict[str, Any], bound: dict[str, Any]) -> dict[str, Any]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_dir = ACTIVATION_ROOT / stamp
    _backup_existing(specs, backup_dir)
    record_path = backup_dir / "activation_record.json"
    record: dict[str, Any] = {
        "schema": "FUTU_QFQ_INSTALL_RECEIPT_V1",
        "status": "INSTALLING",
        "scope_id": SCOPE_ID,
        "profile_id": PROFILE_ID,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "review_receipt_path": str(REVIEW_RECEIPT),
        "review_receipt_sha256": sha256_file(REVIEW_RECEIPT),
        "reviewed_hashes": review["reviewed_hashes"],
        "source_panel_path": bound["source_panel_path"],
        "source_panel_sha256": bound["source_panel_sha256"],
        "targets": [
            {
                "id": spec["id"],
                "path": str(spec["path"]),
                "before_exists": spec["before_exists"],
                "before_sha256": spec["actual_before_sha256"],
                "after_sha256": spec["after_sha256"],
                "backup_path": spec["backup_path"],
            }
            for spec in specs
        ],
    }
    _atomic_json(record_path, record)
    installed: list[dict[str, Any]] = []
    try:
        for spec in specs:
            source = Path(spec["source_path"])
            target = Path(spec["path"])
            if spec["before_exists"] and sha256_file(target) != spec["actual_before_sha256"]:
                raise InstallError(f"TARGET_CHANGED_DURING_INSTALL: {target}")
            if not spec["before_exists"] and target.exists():
                raise InstallError(f"TARGET_APPEARED_DURING_INSTALL: {target}")
            payload = source.read_bytes()
            if hashlib.sha256(payload).hexdigest() != spec["after_sha256"]:
                raise InstallError(f"CANDIDATE_CHANGED_DURING_INSTALL: {source}")
            mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else stat.S_IMODE(source.stat().st_mode)
            _write_atomic(target, payload, mode)
            if sha256_file(target) != spec["after_sha256"]:
                raise InstallError(f"TARGET_READBACK_SHA256_MISMATCH: {target}")
            installed.append(spec)
        record["status"] = "INSTALLED"
        record["installed_at_utc"] = datetime.now(timezone.utc).isoformat()
        record["installed_hashes"] = hashes
        _atomic_json(record_path, record)
    except Exception as exc:
        rollback_errors = []
        for spec in reversed(specs):
            try:
                target = Path(spec["path"])
                if spec["before_exists"] and target.is_file() and sha256_file(target) == spec["actual_before_sha256"]:
                    continue
                if not spec["before_exists"] and not target.exists():
                    continue
                _restore_one(spec, verify_installed=True)
            except Exception as rollback_exc:
                rollback_errors.append(str(rollback_exc))
        record["status"] = "ROLLED_BACK_AFTER_INSTALL_FAILURE" if not rollback_errors else "PARTIAL_INSTALL_REQUIRES_MANUAL_AUDIT"
        record["install_error"] = str(exc)
        record["rollback_errors"] = rollback_errors
        _atomic_json(record_path, record)
        raise InstallError(f"INSTALL_FAILED: {exc}; rollback_errors={rollback_errors}; receipt={record_path}") from exc
    return {"status": "INSTALLED", "activation_record": str(record_path), "targets": record["targets"]}


def rollback_install(record_path: Path) -> dict[str, Any]:
    resolved = record_path.resolve(strict=True)
    try:
        resolved.relative_to(ACTIVATION_ROOT.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise InstallError("ROLLBACK_RECEIPT_OUTSIDE_ACTIVATION_BACKUPS") from exc
    record = load_json(resolved)
    if record.get("schema") != "FUTU_QFQ_INSTALL_RECEIPT_V1" or record.get("status") != "INSTALLED":
        raise InstallError("ROLLBACK_RECEIPT_NOT_INSTALLED")
    candidates = candidate_paths()
    expected_ids = {spec["id"] for spec in target_specs(candidates)}
    target_rows = record.get("targets")
    if not isinstance(target_rows, list) or {row.get("id") for row in target_rows} != expected_ids:
        raise InstallError("ROLLBACK_TARGET_SET_MISMATCH")
    known_paths = {spec["id"]: str(spec["path"]) for spec in target_specs(candidates)}
    for row in target_rows:
        if row.get("path") != known_paths.get(row.get("id")):
            raise InstallError(f"ROLLBACK_TARGET_PATH_MISMATCH: {row.get('id')}")
        target = Path(row["path"])
        if not target.is_file() or sha256_file(target) != row.get("after_sha256"):
            raise InstallError(f"ROLLBACK_INSTALLED_SHA256_MISMATCH: {target}")
        if row.get("before_exists"):
            backup = Path(row["backup_path"])
            if not backup.is_file() or sha256_file(backup) != row.get("before_sha256"):
                raise InstallError(f"ROLLBACK_BACKUP_SHA256_MISMATCH: {backup}")
    for row in reversed(target_rows):
        _restore_one(row, verify_installed=True)
    record["status"] = "ROLLED_BACK"
    record["rolled_back_at_utc"] = datetime.now(timezone.utc).isoformat()
    _atomic_json(resolved, record)
    return {"status": "ROLLED_BACK", "activation_record": str(resolved), "restored_targets": sorted(expected_ids)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true", help="apply only after matching independent PASS receipt")
    mode.add_argument("--rollback", type=Path, help="restore the exact targets in an installer activation record")
    args = parser.parse_args()
    try:
        if args.rollback is not None:
            result = rollback_install(args.rollback)
        else:
            specs, hashes, bound = preflight()
            if args.apply:
                review = _require_review_receipt(hashes)
                result = apply_install(specs, hashes, review, bound)
            else:
                result = {
                    "status": "DRY_RUN_ONLY",
                    "apply_requires_review_receipt": str(REVIEW_RECEIPT),
                    "candidate_hashes": hashes,
                    "source_panel_path": bound["source_panel_path"],
                    "source_panel_sha256": bound["source_panel_sha256"],
                    "targets": [
                        {
                            "id": spec["id"],
                            "path": str(spec["path"]),
                            "before_exists": spec["before_exists"],
                            "before_sha256": spec["actual_before_sha256"],
                            "after_sha256": spec["after_sha256"],
                        }
                        for spec in specs
                    ],
                }
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "CANNOT_CONFIRM", "error": str(exc)}, ensure_ascii=False, sort_keys=True), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
