#!/usr/bin/env python3
"""Read-only verification of the built US manifest/plist candidate."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import plistlib
import sys

from prepare_candidate import (
    CANDIDATE_RELEASE,
    CANDIDATE_RELEASE_ID,
    EXPECTED_ARGUMENTS,
    EXPECTED_TRIGGERS,
    LIVE_PLIST,
    SOURCE_MANIFEST_SHA256,
    SOURCE_PLIST_SHA256,
    SOURCE_RELEASE,
    STAGED_PLIST,
    _all_regular_files,
    _verify_inventory,
    inventory_aggregate,
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    source_manifest_path = SOURCE_RELEASE / "release-manifest.json"
    candidate_manifest_path = CANDIDATE_RELEASE / "release-manifest.json"
    source_manifest_raw = source_manifest_path.read_bytes()
    candidate_manifest_raw = candidate_manifest_path.read_bytes()
    source = json.loads(source_manifest_raw)
    candidate = json.loads(candidate_manifest_raw)
    source_inventory = source["application_inventory"]
    candidate_inventory = candidate["application_inventory"]
    entries = candidate_inventory["entries"]

    assert digest(source_manifest_path) == SOURCE_MANIFEST_SHA256
    assert digest(LIVE_PLIST) == SOURCE_PLIST_SHA256
    assert "entry_count" not in source_inventory
    assert candidate_inventory["entry_count"] == len(entries)
    assert candidate_inventory["entry_count"] == 1189
    assert entries == source_inventory["entries"]
    assert candidate_inventory["aggregate_sha256"] == source_inventory["aggregate_sha256"]
    assert inventory_aggregate(entries) == candidate_inventory["aggregate_sha256"]
    assert candidate["candidate"]["release_id"] == CANDIDATE_RELEASE_ID
    assert candidate["candidate"]["app_root"] == str(CANDIDATE_RELEASE / "app")
    assert candidate["candidate"]["root"] == str(CANDIDATE_RELEASE)
    assert candidate["activation_status"] == "NOT_ACTIVATED"
    assert candidate["candidate_status"] == "READY_FOR_INDEPENDENT_REVIEW"

    listed = _verify_inventory(CANDIDATE_RELEASE / "app", entries)
    source_files = _all_regular_files(SOURCE_RELEASE / "app")
    candidate_files = _all_regular_files(CANDIDATE_RELEASE / "app")
    assert candidate_files == source_files

    original_plist = plistlib.loads(LIVE_PLIST.read_bytes())
    staged_plist = plistlib.loads(STAGED_PLIST.read_bytes())
    original_env = original_plist["EnvironmentVariables"]
    staged_env = staged_plist["EnvironmentVariables"]
    expected_env_changes = {
        "PYTHONPATH",
        "V35_APP_ROOT",
        "V35_RELEASE_ID",
        "V35_RELEASE_MANIFEST_PATH",
        "V35_RELEASE_MANIFEST_SHA256",
    }
    assert {key for key in original_env if original_env.get(key) != staged_env.get(key)} == expected_env_changes
    assert set(staged_env) == set(original_env)
    assert staged_plist["ProgramArguments"] == original_plist["ProgramArguments"] == EXPECTED_ARGUMENTS
    assert staged_plist["StartCalendarInterval"] == original_plist["StartCalendarInterval"] == EXPECTED_TRIGGERS
    assert staged_plist["RunAtLoad"] is original_plist["RunAtLoad"] is False
    assert staged_plist["WorkingDirectory"] == str(CANDIDATE_RELEASE / "app")
    assert staged_env["V35_RELEASE_ID"] == CANDIDATE_RELEASE_ID
    assert staged_env["V35_APP_ROOT"] == str(CANDIDATE_RELEASE / "app")
    assert staged_env["V35_RELEASE_MANIFEST_PATH"] == str(candidate_manifest_path)
    assert staged_env["V35_RELEASE_MANIFEST_SHA256"] == digest(candidate_manifest_path)
    for key, expected in {
        "RESEARCH_ONLY": "1",
        "production_allowed": "false",
        "PRODUCTION_ALLOWED": "false",
        "buy_gate_updated": "false",
        "BUY_GATE_UPDATED": "false",
        "orders_sent": "false",
        "ORDERS_SENT": "false",
    }.items():
        assert staged_env[key] == expected

    print("status=PASS")
    print(f"source_manifest_sha256={digest(source_manifest_path)}")
    print(f"candidate_manifest_sha256={digest(candidate_manifest_path)}")
    print(f"candidate_plist_sha256={digest(STAGED_PLIST)}")
    print(f"entry_count_derived={len(entries)}")
    print(f"listed_inventory_bytes_verified={listed['listed_bytes']}")
    print(f"app_files_byte_mode_identical={len(candidate_files)}")
    print(f"unlisted_app_files_preserved={len(set(candidate_files) - {item['path'] for item in entries})}")
    print("run_at_load_false_and_calendar_argv_preserved=true")
    print("research_only_and_no_order_flags_preserved=true")
    return 0


if __name__ == "__main__":
    sys.exit(main())
