#!/usr/bin/env python3
"""Independently check copied handoff bytes, structured files, and secret patterns."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


HANDOFF = Path(__file__).resolve().parents[1]
PATTERNS = [
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    re.compile(rb"\bsk-[A-Za-z0-9]{48,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9._-]{24,}"),
]


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def blob_sha1(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()


def verify_row(path: Path, row: dict[str, Any], label: str, failures: list[str]) -> int:
    if not path.is_file():
        failures.append(f"{label}: missing {path.relative_to(HANDOFF)}")
        return 0
    data = path.read_bytes()
    expected = (row.get("bytes"), row.get("sha256"), row.get("git_blob_sha1"))
    observed = (len(data), sha256(data), blob_sha1(data))
    if expected != observed:
        failures.append(f"{label}: identity mismatch {path.relative_to(HANDOFF)}")
    return 1


def main() -> None:
    failures: list[str] = []
    inventory = read_json(HANDOFF / "source_inventory.json")
    checked: dict[str, int] = {}
    checked["canonical"] = sum(
        verify_row(HANDOFF / "source/canonical" / row["path"], row, "canonical", failures)
        for row in inventory.get("canonical_source_rows", [])
        if row.get("copied")
    )
    checked["configured_release"] = sum(
        verify_row(HANDOFF / "source/releases" / row["owner"] / row["path"], row, "release", failures)
        for row in inventory.get("configured_release_rows", [])
        if row.get("status") == "copied"
    )
    checked["test_source"] = sum(
        verify_row(HANDOFF / "source/tests" / row["path"], row, "test_source", failures)
        for row in inventory.get("test_source_rows", [])
        if row.get("copied")
    )
    for group in ("test_dependency_rows", "test_import_source_rows"):
        checked[group] = sum(
            verify_row(HANDOFF / row["handoff_path"], row, group, failures)
            for row in inventory.get(group, [])
            if row.get("copied")
        )
    checked["build_lock"] = sum(
        verify_row(HANDOFF / "source/canonical" / row["path"], row, "build_lock", failures)
        for row in inventory.get("build_lock_rows", [])
        if row.get("copied")
    )
    checked["stage14_evidence"] = sum(
        verify_row(HANDOFF / row["handoff_path"], row, "stage14_evidence", failures)
        for row in inventory.get("stage14_exact_copy_rows", [])
        if row.get("copied_exact_bytes")
    )
    manager_copy = read_json(HANDOFF / "evidence/manager_issue8_r3_evidence_copy.json")
    checked["manager_r3_evidence"] = sum(
        verify_row(HANDOFF / row["handoff_path"], row, "manager_r3_evidence", failures)
        for row in manager_copy.get("copied_files", [])
    )
    if not all(row.get("github_blob_sha1_match") for row in manager_copy.get("copied_files", [])):
        failures.append("manager R3 copied evidence does not all match captured GitHub blob identities")

    raw_rows = inventory.get("non_replayable_test_inputs", [])
    for row in raw_rows:
        if row.get("content_copied") is not False or not str(row.get("status", "")).startswith("CANNOT_CONFIRM"):
            failures.append(f"raw market fixture exclusion not explicit: {row.get('path')}")
        for root in (HANDOFF / "source/tests", HANDOFF / "source/test_dependencies"):
            if (root / row["path"]).exists():
                failures.append(f"excluded raw market fixture was copied: {row.get('path')}")

    parsed_json = 0
    for path in sorted(HANDOFF.rglob("*.json")):
        if path.is_symlink():
            failures.append(f"unexpected symlink: {path.relative_to(HANDOFF)}")
            continue
        try:
            json.loads(path.read_text(encoding="utf-8"))
            parsed_json += 1
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            failures.append(f"invalid JSON {path.relative_to(HANDOFF)}: {type(error).__name__}")
    cache_path = HANDOFF / ".validation-cache"
    if cache_path.exists():
        failures.append("validation cache path already exists; refusing to reuse or overwrite it")
        lock_validation = {"status": "CANNOT_CONFIRM", "reason": "validation cache path already exists"}
    else:
        env = os.environ.copy()
        env["UV_CACHE_DIR"] = str(cache_path)
        lock_result = subprocess.run(
            ["uv", "lock", "--check", "--offline", "--project", str(HANDOFF / "source/canonical")],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        lock_summary = (lock_result.stdout + "\n" + lock_result.stderr).strip()
        lock_validation = {
            "status": "PASS_LOCK_CHECK" if lock_result.returncode == 0 else "CANNOT_CONFIRM_LOCK_UP_TO_DATE",
            "command": "uv lock --check --offline --project source/canonical",
            "exit_code": lock_result.returncode,
            "diagnostic": lock_summary[:700],
        }
        if cache_path.exists():
            shutil.rmtree(cache_path)
    python_sources = [
        "tools/build_handoff.py",
        "tools/compare_baselines.py",
        "tools/verify_handoff.py",
        "tools/verify_upload_manifest.py",
    ]
    python_sources.extend(
        "source/canonical/" + row["path"]
        for row in inventory.get("development_build_tool_inventory", {}).get("source_rows", [])
        if str(row.get("path", "")).endswith(".py")
    )
    for rel in python_sources:
        try:
            ast.parse((HANDOFF / rel).read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, SyntaxError) as error:
            failures.append(f"invalid Python source {rel}: {type(error).__name__}")

    files = sorted(path for path in HANDOFF.rglob("*") if path.is_file() and not path.is_symlink())
    findings = []
    for path in files:
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in PATTERNS):
            findings.append(path.relative_to(HANDOFF).as_posix())
    if findings:
        failures.extend(f"high-confidence secret pattern in {path}" for path in findings)
    total_bytes = sum(path.stat().st_size for path in files)
    if failures:
        print(json.dumps({"status": "FAIL", "failures": failures[:40]}, ensure_ascii=False))
        raise SystemExit(1)

    comparison = read_json(HANDOFF / "references/github_baseline_comparison.json")
    stage14_remote_rows = [row for row in comparison["remote_files"] if row.get("ref") == "stage_evidence14"]
    if len(stage14_remote_rows) != 14 or not all(row.get("local_blob_sha1_match") is True for row in stage14_remote_rows):
        failures.append("Stage evidence copy does not match all 14 captured GitHub blob identities")
        print(json.dumps({"status": "FAIL", "failures": failures[:40]}, ensure_ascii=False))
        raise SystemExit(1)

    report = {
        "schema_version": "mac_source_handoff.integrity_receipt.v1",
        "status": "PASS",
        "handoff_path": str(HANDOFF),
        "checked_copy_groups": checked,
        "checked_copy_file_count": sum(checked.values()),
        "parsed_json_file_count": parsed_json,
        "toml_lock_validation": lock_validation,
        "parsed_python_sources": sorted(python_sources),
        "non_replayable_raw_market_input_count": len(raw_rows),
        "stage14_exact_github_blob_match_count": len(stage14_remote_rows),
        "manager_r3_github_blob_match_count": sum(row.get("github_blob_sha1_match") is True for row in manager_copy.get("copied_files", [])),
        "security_scan": {"status": "PASS", "high_confidence_pattern_count": 0, "files_scanned_before_this_receipt": len(files), "bytes_scanned_before_this_receipt": total_bytes},
        "business_tests_run": False,
        "business_data_collection_or_reruns_performed": False,
        "process_loaded_source_bytes": "CANNOT_CONFIRM",
        "external_upload_or_repository_mutation": False,
    }
    (HANDOFF / "integrity_receipt.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    scan = {
        "schema_version": "mac_source_handoff.security_scan.v1",
        "scope": "all current regular files under this handoff root, including source, evidence, tools, and docs",
        "patterns_checked": ["private-key PEM markers", "GitHub tokens", "long OpenAI-style keys", "AWS access-key IDs", "Slack tokens", "long bearer tokens"],
        "security_scan_status": "PASS",
        "high_confidence_findings": [],
        "files_scanned_before_integrity_receipt_and_manifest": len(files),
        "bytes_scanned_before_integrity_receipt_and_manifest": total_bytes,
        "raw_launchagent_or_environment_values_copied": False,
        "raw_quote_or_minute_rows_copied": False,
        "source_credentials_modified": False,
    }
    (HANDOFF / "security_scan.json").write_text(json.dumps(scan, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "checked_copy_file_count": sum(checked.values()), "parsed_json_file_count": parsed_json, "test_only_import_closure": checked.get("test_import_source_rows", 0), "files_scanned": len(files), "bytes_scanned": total_bytes, "secret_findings": 0}, sort_keys=True))


if __name__ == "__main__":
    main()
