#!/usr/bin/env python3
"""Build the isolated API receipt-compatibility candidate from the pinned API release."""
from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import stat
import subprocess
import sys
from typing import Any


SOURCE_RELEASE_ID = "announcement-continuation-api-20261017-r11c"
SOURCE_MANIFEST_SHA256 = "7c10d630ff2c48e927c83013b98cbbfaa3254648d3a312ee172446a3a7e352ba"
CANDIDATE_RELEASE_ID = "us-receipt-compat-api-20261017-r1"
RELEASES_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases")
SOURCE_RELEASE = RELEASES_ROOT / SOURCE_RELEASE_ID
CANDIDATE_RELEASE = RELEASES_ROOT / CANDIDATE_RELEASE_ID
TARGET_RELATIVE = "infrastructure/research_peripheral_store.py"
HANDOFF = Path(__file__).resolve().parent
PATCH_PATH = HANDOFF / "source_delta.patch"
SOURCE_API_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
SOURCE_API_PLIST_SHA256 = "03095bd9b06e38da5c3fe4ebe9031851252fc78e95ac4020bfacc4bdd6f545f3"
CANDIDATE_PLIST = HANDOFF / "com.lexi.v35.api-only.candidate.plist"


NEW_READ_EXACT = '''    def read_exact(self, trade_date: str, source: str) -> dict[str, Any] | None:
        normalized_date = _date(trade_date)
        normalized_source = _source(source)
        relative = self._relative(normalized_date, normalized_source)
        receipt_relative = self._receipt_relative(normalized_date, normalized_source)
        artifact_path = self._path(relative)
        receipt_path = self._path(receipt_relative)
        manifest = self._manifest()
        tracked = relative in manifest
        if not artifact_path.exists() and not receipt_path.exists() and not tracked:
            return None
        if not artifact_path.is_file() or not receipt_path.is_file() or not tracked:
            raise ValueError("research peripheral manifest or receipt mismatch")
        payload = self._read(relative)
        digest = _sha256(payload)
        if manifest.get(relative) != digest:
            raise ValueError("research peripheral manifest or receipt mismatch")

        stored_receipt = self._read(receipt_relative)
        expected_receipt = self._receipt(payload, digest)

        def exact_json(left: Any, right: Any) -> bool:
            """Compare JSON values canonically without Python bool/int aliases."""
            try:
                left_json = json.dumps(
                    left, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                )
                right_json = json.dumps(
                    right, ensure_ascii=False, sort_keys=True,
                    separators=(",", ":"), allow_nan=False,
                )
            except (TypeError, ValueError):
                return False
            return left_json == right_json

        def validate_exact_identity() -> None:
            if validate_research_peripheral(
                payload,
                expected_trade_date=normalized_date,
                expected_source=normalized_source,
            ) != (normalized_date, normalized_source):
                raise ValueError("research peripheral manifest or receipt mismatch")

        if exact_json(stored_receipt, expected_receipt):
            validate_exact_identity()
            return payload

        # This compatibility form is deliberately local to exact reads of the
        # US external_finance artifact.  _receipt/publish/replace remain strict.
        if normalized_source == "external_finance":
            validate_exact_identity()
            snapshot = payload.get("market_snapshot")
            captures = payload.get("us_session_captures")
            snapshot_fields = ("captured_at", "source_response_sha256")
            capture_fields = (
                "capture_origin",
                "original_time_capture",
                "quote_capture_status",
                "rss_item_count",
                "rss_raw_item_count",
                "rss_status",
            )
            late_capture = next(
                (
                    row for row in reversed(captures)
                    if isinstance(row, Mapping) and row.get("late") is True
                ),
                None,
            ) if isinstance(captures, list) else None
            if (
                isinstance(snapshot, Mapping)
                and all(field in snapshot for field in snapshot_fields)
                and isinstance(late_capture, Mapping)
                and all(field in late_capture for field in capture_fields)
            ):
                extended_receipt = dict(expected_receipt)
                extended_receipt.update(
                    {
                        "market_snapshot_captured_at": snapshot["captured_at"],
                        "market_snapshot_source_response_sha256": snapshot[
                            "source_response_sha256"
                        ],
                        **{field: late_capture[field] for field in capture_fields},
                    }
                )
                if exact_json(stored_receipt, extended_receipt):
                    return payload

        raise ValueError("research peripheral manifest or receipt mismatch")
'''


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory_digest(entries: list[dict[str, Any]]) -> str:
    raw = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return sha256(raw)


def file_inventory(root: Path) -> dict[str, tuple[int, str, str]]:
    found: dict[str, tuple[int, str, str]] = {}
    for base, dirs, files in os.walk(root):
        base_path = Path(base)
        for name in dirs:
            if (base_path / name).is_symlink():
                raise ValueError("APP_TREE_SYMLINK_UNSUPPORTED")
        for name in files:
            path = base_path / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("APP_TREE_FILE_UNSAFE")
            raw = path.read_bytes()
            found[path.relative_to(root).as_posix()] = (
                len(raw), sha256(raw), f"{stat.S_IMODE(path.stat().st_mode):04o}"
            )
    return found


def verify_listed_inventory(app_root: Path, entries: list[dict[str, Any]]) -> None:
    if not isinstance(entries, list):
        raise ValueError("SOURCE_INVENTORY_ENTRIES_NOT_LIST")
    seen: set[str] = set()
    for item in entries:
        relative = item.get("path")
        posix = PurePosixPath(relative or "")
        if item.get("kind") != "file" or not relative or posix.is_absolute() or ".." in posix.parts or relative in seen:
            raise ValueError("SOURCE_INVENTORY_ENTRY_INVALID")
        seen.add(relative)
        path = app_root.joinpath(*posix.parts)
        if path.is_symlink() or not path.is_file():
            raise ValueError("SOURCE_INVENTORY_FILE_MISSING_OR_UNSAFE:" + relative)
        raw = path.read_bytes()
        mode = f"{stat.S_IMODE(path.stat().st_mode):04o}"
        if len(raw) != item.get("size") or sha256(raw) != item.get("sha256") or mode != item.get("mode"):
            raise ValueError("SOURCE_INVENTORY_FILE_MISMATCH:" + relative)


def source_inputs() -> tuple[dict[str, Any], bytes, str]:
    manifest_path = SOURCE_RELEASE / "release-manifest.json"
    raw = manifest_path.read_bytes()
    if sha256(raw) != SOURCE_MANIFEST_SHA256:
        raise ValueError("SOURCE_MANIFEST_IDENTITY_CHANGED_STOP")
    manifest = json.loads(raw)
    candidate = manifest.get("candidate") or {}
    if candidate.get("release_id") != SOURCE_RELEASE_ID or candidate.get("root") != str(SOURCE_RELEASE):
        raise ValueError("SOURCE_MANIFEST_RELEASE_ID_CHANGED_STOP")
    if manifest.get("activation_status") != "NOT_ACTIVATED":
        raise ValueError("SOURCE_ACTIVATION_STATUS_CHANGED_STOP")
    inventory = manifest.get("application_inventory") or {}
    entries = inventory.get("entries")
    if (
        inventory.get("entry_count") != len(entries or [])
        or inventory_digest(entries) != inventory.get("aggregate_sha256")
    ):
        raise ValueError("SOURCE_INVENTORY_AGGREGATE_MISMATCH_STOP")
    app_root = SOURCE_RELEASE / "app"
    verify_listed_inventory(app_root, entries)
    return manifest, raw, str(inventory["aggregate_sha256"])


def replacement_source(source_text: str) -> str:
    start = source_text.find("    def read_exact(")
    end = source_text.find("\n    def list_dates(", start)
    if start < 0 or end < 0:
        raise ValueError("SOURCE_READ_EXACT_BOUNDARY_MISSING")
    old = source_text[start:end]
    if old.count("raise ValueError(\"research peripheral manifest or receipt mismatch\")") < 2:
        raise ValueError("SOURCE_READ_EXACT_BASE_CHANGED_STOP")
    return source_text[:start] + NEW_READ_EXACT.rstrip("\n") + source_text[end:]


def expected_patch_bytes() -> bytes:
    source = (SOURCE_RELEASE / "app" / TARGET_RELATIVE).read_text(encoding="utf-8")
    updated = replacement_source(source)
    diff = difflib.unified_diff(
        source.splitlines(keepends=True),
        updated.splitlines(keepends=True),
        fromfile="a/" + TARGET_RELATIVE,
        tofile="b/" + TARGET_RELATIVE,
    )
    return "".join(diff).encode("utf-8")


def write_source_delta() -> dict[str, str]:
    source_inputs()
    expected = expected_patch_bytes()
    if PATCH_PATH.exists() and PATCH_PATH.read_bytes() != expected:
        raise ValueError("SOURCE_DELTA_ALREADY_EXISTS_WITH_DIFFERENT_BYTES_STOP")
    PATCH_PATH.write_bytes(expected)
    return {"path": str(PATCH_PATH), "sha256": sha256(expected)}


def _candidate_plist(manifest_path: Path, manifest_sha: str) -> bytes:
    raw = SOURCE_API_PLIST.read_bytes()
    if sha256(raw) != SOURCE_API_PLIST_SHA256:
        raise ValueError("SOURCE_API_PLIST_CHANGED_STOP")
    payload = plistlib.loads(raw)
    if payload.get("Label") != "com.lexi.v35.api-only":
        raise ValueError("SOURCE_API_LABEL_CHANGED_STOP")
    args = payload.get("ProgramArguments")
    if not isinstance(args, list):
        raise ValueError("SOURCE_API_ARGUMENTS_INVALID")
    old_app = str(SOURCE_RELEASE / "app")
    old_manifest = str(SOURCE_RELEASE / "release-manifest.json")
    replacements = {
        "V35_APP_ROOT": (old_app, str(CANDIDATE_RELEASE / "app")),
        "V35_RELEASE_ID": (SOURCE_RELEASE_ID, CANDIDATE_RELEASE_ID),
        "V35_RELEASE_MANIFEST_PATH": (old_manifest, str(manifest_path)),
        "V35_RELEASE_MANIFEST_SHA256": (SOURCE_MANIFEST_SHA256, manifest_sha),
        "PYTHONPATH": (
            f"{old_app}/upstreams:{old_app}",
            f"{CANDIDATE_RELEASE / 'app'}/upstreams:{CANDIDATE_RELEASE / 'app'}",
        ),
    }
    for name, (before, after) in replacements.items():
        indexes = [i for i, value in enumerate(args) if isinstance(value, str) and value.startswith(name + "=")]
        if len(indexes) != 1 or args[indexes[0]] != f"{name}={before}":
            raise ValueError("SOURCE_API_PLIST_IDENTITY_CHANGED_STOP:" + name)
        args[indexes[0]] = f"{name}={after}"
    payload["WorkingDirectory"] = str(CANDIDATE_RELEASE / "app")
    encoded = plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False)
    plistlib.loads(encoded)
    return encoded


def build_candidate() -> dict[str, Any]:
    if CANDIDATE_RELEASE.exists():
        raise FileExistsError("CANDIDATE_RELEASE_ALREADY_EXISTS_STOP")
    source_manifest, _, source_inventory_sha = source_inputs()
    patch_bytes = expected_patch_bytes()
    if not PATCH_PATH.is_file() or PATCH_PATH.read_bytes() != patch_bytes:
        raise ValueError("SOURCE_DELTA_PATCH_MISMATCH_STOP")

    source_app = SOURCE_RELEASE / "app"
    candidate_app = CANDIDATE_RELEASE / "app"
    CANDIDATE_RELEASE.mkdir()
    shutil.copytree(source_app, candidate_app, copy_function=shutil.copy2)
    patch_result = subprocess.run(
        ["patch", "--batch", "--forward", "-p1"],
        cwd=candidate_app,
        input=patch_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if patch_result.returncode != 0:
        raise RuntimeError("CANDIDATE_PATCH_FAILED:" + patch_result.stdout.decode("utf-8", "replace"))

    source_files = file_inventory(source_app)
    candidate_files = file_inventory(candidate_app)
    changed = sorted(
        path for path in set(source_files) | set(candidate_files)
        if source_files.get(path) != candidate_files.get(path)
    )
    if changed != [TARGET_RELATIVE]:
        raise ValueError("CANDIDATE_CHANGED_PATHS_INVALID:" + json.dumps(changed))

    manifest = copy.deepcopy(source_manifest)
    entries = manifest["application_inventory"]["entries"]
    target_entry = next((entry for entry in entries if entry.get("path") == TARGET_RELATIVE), None)
    if target_entry is None:
        raise ValueError("TARGET_NOT_IN_SOURCE_INVENTORY")
    size, digest, mode = candidate_files[TARGET_RELATIVE]
    target_entry.update({"size": size, "sha256": digest, "mode": mode})
    inventory = manifest["application_inventory"]
    inventory["entry_count"] = len(entries)
    inventory["aggregate_sha256"] = inventory_digest(entries)

    manifest["candidate"].update(
        {
            "root": str(CANDIDATE_RELEASE),
            "app_root": str(candidate_app),
            "release_id": CANDIDATE_RELEASE_ID,
            "formal_release_root": str(CANDIDATE_RELEASE),
        }
    )
    manifest["candidate_status"] = "READY_FOR_INDEPENDENT_REVIEW"
    manifest["activation_status"] = "NOT_ACTIVATED"
    base_inventory = source_manifest["application_inventory"]["entries"]
    non_delta_entries = [entry for entry in base_inventory if entry.get("path") != TARGET_RELATIVE]
    before = next(entry for entry in base_inventory if entry.get("path") == TARGET_RELATIVE)
    integration = manifest.setdefault("api_integration", {})
    integration.clear()
    integration.update(
        {
            "schema_version": "v4.api_release_integration.v1",
            "base": {
                "release_root": str(SOURCE_RELEASE),
                "app_root": str(source_app),
                "release_id": SOURCE_RELEASE_ID,
                "release_manifest_path": str(SOURCE_RELEASE / "release-manifest.json"),
                "release_manifest_sha256": SOURCE_MANIFEST_SHA256,
                "application_inventory_sha256": source_inventory_sha,
                "application_inventory_entry_count": len(base_inventory),
            },
            "target_role": manifest["candidate"].get("module_role"),
            "base_role": manifest["candidate"].get("module_role"),
            "bootstrap_transition": False,
            "delta_receipt_source_path": str(PATCH_PATH),
            "delta_receipt_file": "source_delta.patch",
            "delta_receipt_sha256": sha256(patch_bytes),
            "delta_entries": [
                {
                    "path": TARGET_RELATIVE,
                    "before_sha256": before["sha256"],
                    "after_sha256": digest,
                    "unified_diff_sha256": sha256(patch_bytes),
                    "unified_diff_hunk_count": sum(
                        line.startswith(b"@@") for line in patch_bytes.splitlines()
                    ),
                }
            ],
            "non_delta_active_release_bytes_preserved": True,
            "non_delta_entry_count": len(non_delta_entries),
            "non_delta_inventory_sha256": inventory_digest(non_delta_entries),
            "active_application_inventory_sha256": source_inventory_sha,
            "source_workspace_full_tree_copied": False,
        }
    )

    manifest_path = CANDIDATE_RELEASE / "release-manifest.json"
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    manifest_path.write_bytes(manifest_bytes)
    os.chmod(manifest_path, stat.S_IMODE((SOURCE_RELEASE / "release-manifest.json").stat().st_mode))
    manifest_sha = sha256(manifest_bytes)
    plist_bytes = _candidate_plist(manifest_path, manifest_sha)
    if CANDIDATE_PLIST.exists() and CANDIDATE_PLIST.read_bytes() != plist_bytes:
        raise ValueError("CANDIDATE_PLIST_ALREADY_EXISTS_WITH_DIFFERENT_BYTES_STOP")
    CANDIDATE_PLIST.write_bytes(plist_bytes)

    verify_listed_inventory(candidate_app, entries)
    return {
        "source_release_id": SOURCE_RELEASE_ID,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "candidate_release_id": CANDIDATE_RELEASE_ID,
        "candidate_manifest_sha256": manifest_sha,
        "candidate_app_root": str(candidate_app),
        "candidate_module_sha256": digest,
        "candidate_plist": str(CANDIDATE_PLIST),
        "candidate_plist_sha256": sha256(plist_bytes),
        "inventory_entry_count": len(entries),
        "candidate_file_count": len(candidate_files),
        "unlisted_files_preserved": len(set(candidate_files) - {item["path"] for item in entries}),
        "changed_app_paths": changed,
        "activation_status": manifest["activation_status"],
        "candidate_status": manifest["candidate_status"],
        "patch_output": patch_result.stdout.decode("utf-8", "replace"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("prepare-patch", "build"))
    mode = parser.parse_args().mode
    result = write_source_delta() if mode == "prepare-patch" else build_candidate()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
