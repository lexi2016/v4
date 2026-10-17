#!/usr/bin/env python3
"""Build the one-field US release-manifest repair candidate."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import plistlib
import shutil
import stat
from typing import Any


SOURCE_RELEASE_ID = "futu-industry-us-20261016-r1"
SOURCE_MANIFEST_SHA256 = "bb8a0bc023842df643581c1ad82f9b818017720b0213d48f781673c53ab04ec0"
SOURCE_PLIST_SHA256 = "7483f0d6e56e0e2ffdc28d1c2fd6963c122a0541661d6a382514beee9d016332"
CANDIDATE_RELEASE_ID = "us-entry-count-repair-20261017-r1"
RELEASES_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases")
LIVE_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v4.us-market-digest.plist")
STAGED_PLIST_NAME = "com.lexi.v4.us-market-digest.candidate.plist"

HERE = Path(__file__).resolve().parent
SOURCE_RELEASE = RELEASES_ROOT / SOURCE_RELEASE_ID
CANDIDATE_RELEASE = RELEASES_ROOT / CANDIDATE_RELEASE_ID
STAGED_PLIST = HERE / STAGED_PLIST_NAME

EXPECTED_ARGUMENTS = [
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/runtime/venvs/v3.5-mac/bin/python",
    "-B",
    "-m",
    "ops.run_us_market_slot",
    "--data-root",
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data",
    "--ledger-root",
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/dispatcher",
]
EXPECTED_TRIGGERS = [
    {"Hour": 4, "Minute": 15},
    {"Hour": 5, "Minute": 15},
    {"Hour": 21, "Minute": 0},
    {"Hour": 22, "Minute": 0},
]
EXPECTED_IDENTITY = {
    "V35_APP_ROOT": str(SOURCE_RELEASE / "app"),
    "V35_RELEASE_ID": SOURCE_RELEASE_ID,
    "V35_RELEASE_MANIFEST_PATH": str(SOURCE_RELEASE / "release-manifest.json"),
    "V35_RELEASE_MANIFEST_SHA256": SOURCE_MANIFEST_SHA256,
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory_aggregate(entries: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        entries,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded)


def _verify_inventory(app_root: Path, entries: list[dict[str, Any]]) -> dict[str, int]:
    if not isinstance(entries, list):
        raise ValueError("SOURCE_INVENTORY_ENTRIES_NOT_LIST")
    seen: set[str] = set()
    total_bytes = 0
    for item in entries:
        relative = item.get("path")
        posix = PurePosixPath(relative or "")
        if (
            item.get("kind") != "file"
            or not relative
            or posix.is_absolute()
            or ".." in posix.parts
            or relative in seen
        ):
            raise ValueError("SOURCE_INVENTORY_ENTRY_INVALID")
        seen.add(relative)
        path = app_root.joinpath(*posix.parts)
        if path.is_symlink() or not path.is_file():
            raise ValueError("SOURCE_INVENTORY_FILE_MISSING_OR_UNSAFE:" + relative)
        content = path.read_bytes()
        mode = f"{stat.S_IMODE(path.stat().st_mode):04o}"
        if (
            len(content) != item.get("size")
            or sha256(content) != item.get("sha256")
            or mode != item.get("mode")
        ):
            raise ValueError("SOURCE_INVENTORY_FILE_MISMATCH:" + relative)
        total_bytes += len(content)
    return {"entry_count": len(entries), "listed_bytes": total_bytes}


def _all_regular_files(root: Path) -> dict[str, tuple[int, str, str]]:
    result: dict[str, tuple[int, str, str]] = {}
    for base, dirs, files in os.walk(root):
        base_path = Path(base)
        for name in dirs:
            if (base_path / name).is_symlink():
                raise ValueError("APP_TREE_SYMLINK_UNSUPPORTED")
        for name in files:
            path = base_path / name
            if path.is_symlink() or not path.is_file():
                raise ValueError("APP_TREE_FILE_UNSAFE")
            content = path.read_bytes()
            result[path.relative_to(root).as_posix()] = (
                len(content),
                sha256(content),
                f"{stat.S_IMODE(path.stat().st_mode):04o}",
            )
    return result


def _verify_live_plist() -> dict[str, Any]:
    raw = LIVE_PLIST.read_bytes()
    if sha256(raw) != SOURCE_PLIST_SHA256:
        raise ValueError("LIVE_PLIST_CHANGED_STOP")
    payload = plistlib.loads(raw)
    env = payload["EnvironmentVariables"]
    if any(env.get(name) != value for name, value in EXPECTED_IDENTITY.items()):
        raise ValueError("LIVE_RELEASE_IDENTITY_CHANGED_STOP")
    if payload.get("ProgramArguments") != EXPECTED_ARGUMENTS:
        raise ValueError("LIVE_PROGRAM_ARGUMENTS_CHANGED_STOP")
    if payload.get("RunAtLoad") is not False:
        raise ValueError("LIVE_RUN_AT_LOAD_CHANGED_STOP")
    if payload.get("StartCalendarInterval") != EXPECTED_TRIGGERS:
        raise ValueError("LIVE_CALENDAR_TRIGGERS_CHANGED_STOP")
    return payload


def _candidate_manifest(
    source: dict[str, Any], candidate_app: Path, candidate_release: Path
) -> dict[str, Any]:
    result = copy.deepcopy(source)
    inventory = result["application_inventory"]
    entries = inventory.get("entries")
    if "entry_count" in inventory:
        raise ValueError("SOURCE_ENTRY_COUNT_ALREADY_PRESENT_STOP")
    if inventory_aggregate(entries) != inventory.get("aggregate_sha256"):
        raise ValueError("SOURCE_INVENTORY_AGGREGATE_MISMATCH_STOP")
    inventory["entry_count"] = len(entries)
    candidate = result["candidate"]
    candidate["app_root"] = str(candidate_app)
    candidate["release_id"] = CANDIDATE_RELEASE_ID
    candidate["root"] = str(candidate_release)
    result["candidate_status"] = "READY_FOR_INDEPENDENT_REVIEW"
    if result.get("activation_status") != "NOT_ACTIVATED":
        raise ValueError("SOURCE_ACTIVATION_STATUS_CHANGED_STOP")
    return result


def build() -> dict[str, Any]:
    if CANDIDATE_RELEASE.exists() or STAGED_PLIST.exists():
        raise FileExistsError("CANDIDATE_OR_STAGED_PLIST_EXISTS_STOP")
    live_plist = _verify_live_plist()

    source_manifest_path = SOURCE_RELEASE / "release-manifest.json"
    source_manifest_bytes = source_manifest_path.read_bytes()
    if sha256(source_manifest_bytes) != SOURCE_MANIFEST_SHA256:
        raise ValueError("SOURCE_MANIFEST_IDENTITY_CHANGED_STOP")
    source_manifest = json.loads(source_manifest_bytes)
    if source_manifest.get("schema_version") != "v4.release_candidate.v1":
        raise ValueError("SOURCE_MANIFEST_SCHEMA_CHANGED_STOP")
    if source_manifest.get("candidate", {}).get("release_id") != SOURCE_RELEASE_ID:
        raise ValueError("SOURCE_MANIFEST_RELEASE_ID_CHANGED_STOP")

    source_app = SOURCE_RELEASE / "app"
    source_inventory = source_manifest["application_inventory"]
    entries = source_inventory.get("entries")
    if source_inventory.get("entry_count") is not None:
        raise ValueError("SOURCE_ENTRY_COUNT_ALREADY_PRESENT_STOP")
    if inventory_aggregate(entries) != source_inventory.get("aggregate_sha256"):
        raise ValueError("SOURCE_INVENTORY_AGGREGATE_MISMATCH_STOP")
    listed = _verify_inventory(source_app, entries)
    source_files = _all_regular_files(source_app)

    candidate_app = CANDIDATE_RELEASE / "app"
    candidate_manifest = _candidate_manifest(
        source_manifest, candidate_app, CANDIDATE_RELEASE
    )
    CANDIDATE_RELEASE.mkdir()
    shutil.copytree(source_app, candidate_app, copy_function=shutil.copy2)
    candidate_files = _all_regular_files(candidate_app)
    if candidate_files != source_files:
        raise ValueError("CANDIDATE_APP_BYTES_CHANGED_STOP")
    _verify_inventory(candidate_app, candidate_manifest["application_inventory"]["entries"])

    candidate_manifest_path = CANDIDATE_RELEASE / "release-manifest.json"
    candidate_manifest_bytes = (
        json.dumps(candidate_manifest, ensure_ascii=False, indent=2) + "\n"
    ).encode("utf-8")
    candidate_manifest_path.write_bytes(candidate_manifest_bytes)
    os.chmod(candidate_manifest_path, stat.S_IMODE(source_manifest_path.stat().st_mode))
    manifest_digest = sha256(candidate_manifest_bytes)

    staged_plist = copy.deepcopy(live_plist)
    env = staged_plist["EnvironmentVariables"]
    env.update(
        {
            "V35_APP_ROOT": str(candidate_app),
            "V35_RELEASE_ID": CANDIDATE_RELEASE_ID,
            "V35_RELEASE_MANIFEST_PATH": str(candidate_manifest_path),
            "V35_RELEASE_MANIFEST_SHA256": manifest_digest,
            "PYTHONPATH": f"{candidate_app}/upstreams:{candidate_app}",
        }
    )
    staged_plist["WorkingDirectory"] = str(candidate_app)
    if (
        staged_plist["ProgramArguments"] != EXPECTED_ARGUMENTS
        or staged_plist["RunAtLoad"] is not False
        or staged_plist["StartCalendarInterval"] != EXPECTED_TRIGGERS
    ):
        raise ValueError("STAGED_PLIST_SCHEDULE_OR_ARGUMENTS_CHANGED")
    staged_bytes = plistlib.dumps(staged_plist, fmt=plistlib.FMT_XML, sort_keys=False)
    plistlib.loads(staged_bytes)
    STAGED_PLIST.write_bytes(staged_bytes)

    return {
        "source_release_id": SOURCE_RELEASE_ID,
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "candidate_release_id": CANDIDATE_RELEASE_ID,
        "candidate_manifest_sha256": manifest_digest,
        "entry_count_derived_from_entries": listed["entry_count"],
        "listed_inventory_bytes_verified": listed["listed_bytes"],
        "app_files_copied_and_byte_mode_verified": len(candidate_files),
        "app_files_not_in_application_inventory_preserved": len(
            set(candidate_files) - {item["path"] for item in entries}
        ),
        "staged_plist": str(STAGED_PLIST),
        "staged_plist_sha256": sha256(staged_bytes),
        "run_at_load": staged_plist["RunAtLoad"],
        "calendar_triggers": staged_plist["StartCalendarInterval"],
        "program_arguments": staged_plist["ProgramArguments"],
        "activation_status": candidate_manifest["activation_status"],
        "candidate_status": candidate_manifest["candidate_status"],
    }


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
