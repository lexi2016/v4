#!/usr/bin/env python3
"""US-only, compare-and-swap LaunchAgent candidate activation helper.

Default mode is read-only. --apply or --rollback is required for any mutation.
Never run --apply before independent review and explicit integration approval.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import plistlib
import re
import stat
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

BASE = Path("/Users/lexi/Desktop/学习/agents调试/V4_US_CLOSE_RETRY_20261016/candidate")
BASELINE = Path("/Users/lexi/Desktop/学习/agents调试/V4_US_CLOSE_RETRY_20261016/integration/baseline.json")
CANDIDATE_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-close-retry-us-20261016-r3")
CANDIDATE_APP = CANDIDATE_ROOT / "app"
CANDIDATE_MANIFEST = CANDIDATE_ROOT / "release-manifest.json"
CANDIDATE_PLIST = BASE / "us-market-digest.r3.candidate.plist"
ORIGINAL_PLIST = BASE / "us-market-digest.candidate.plist"
ACTIVE_PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v4.us-market-digest.plist")
US_LABEL = "com.lexi.v4.us-market-digest"
DOMAIN = f"gui/{os.getuid()}"
CANDIDATE_RELEASE_ID = "us-close-retry-us-20261016-r3"
PROTECTED_CURRENT = BASE / "protected-current-baseline.json"
CANDIDATE_MANIFEST_SHA256 = "592bb39ce93fd9d564d34088403d96fd14213c2380991b239a458e80c72a9139"
CANDIDATE_PLIST_SHA256 = "d9cc2ea72a17177a5054d1034a9a361af4cf10b5a08036b476ade505ffc74f7d"
ORIGINAL_PLIST_SHA256 = "9aa5c54d2b75f59f039da3618453a1abc99d1e8662875a87409f201d0023b5bb"
R1_ACTIVE_MANIFEST = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-close-retry-us-20261016-r1/release-manifest.json")
R1_ACTIVE_MANIFEST_SHA256 = "3793d0acb6937828fccc0c6f1a5331be699e7ad62ac448654050a62ab70225a9"
EXPECTED = {
    "com.lexi.v4.us-market-digest": {
        "plist_path": "/Users/lexi/Library/LaunchAgents/com.lexi.v4.us-market-digest.plist",
        "plist_sha256": "a44d1903f89e94b8dc481fb60d6418fc204f767b2bb64e4f11fd0f2d30a48228",
        "manifest_path": "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/us-close-recovery-us-20261015-r1/release-manifest.json",
        "manifest_sha256": "a22b7e6079fd701e996f73f8c0e8ab37610f7127bd0d5516b293e7dd3b31b1f2",
    },
    "com.lexi.v35.api-only": {
        "plist_path": "/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist",
        "plist_sha256": "e8ed284bdab74997fa2e7717d95a981452449df8b6b76e00c9efc6639182ed62",
        "manifest_path": "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/zsxq-pdf-ocr-api-20261016-r4/release-manifest.json",
        "manifest_sha256": "a2dd8358300d0b61e8a365ed1ac8fe57e5872857208d5bd888e505b47a6cb135",
    },
    "com.lexi.v35.scheduler": {
        "plist_path": "/Users/lexi/Library/LaunchAgents/com.lexi.v35.scheduler.plist",
        "plist_sha256": "12fec20f665af3ce0a20ffd2c989684ff580c36ae2d932fdc285bb798e93d137",
        "manifest_path": "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/oversold-daily-cache-20261016-r1/release-manifest.json",
        "manifest_sha256": "03f1c61fe881039b286bd4d0d9acbcb29d32593747e7c0119b8e3c261237bfb2",
    },
    "com.lexi.stage-center.scheduler": {
        "plist_path": "/Users/lexi/Library/LaunchAgents/com.lexi.stage-center.scheduler.plist",
        "plist_sha256": "ca54499d9dc951f3e395de0cad86748027e43f0faa8fbeacea3f2d0b9b59963c",
        "manifest_path": "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/hk-auto-execution-audit-20261015-r3/release-manifest.json",
        "manifest_sha256": "f8c0be35c421a68ecb9cf2598ef65a61a97ece2e713c43fffea5a031e837d7f6",
    },
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def baseline_rows() -> dict[str, dict]:
    payload = json.loads(BASELINE.read_text(encoding="utf-8"))
    rows = payload.get("services")
    require(isinstance(rows, list), "BASELINE_SERVICES_INVALID")
    by_label = {row.get("label"): row for row in rows if isinstance(row, dict)}
    require(set(by_label) == set(EXPECTED), "BASELINE_SERVICE_SET_CHANGED")
    for label, expected in EXPECTED.items():
        row = by_label[label]
        for field, value in expected.items():
            require(row.get(field) == value, f"BASELINE_PIN_CHANGED:{label}:{field}")
    return by_label


def verify_protected_services(rows: dict[str, dict]) -> None:
    """Retain historical pins; current non-US state is observational only."""
    require(set(rows) == set(EXPECTED), "BASELINE_SERVICE_SET_CHANGED")


def observe_non_us_services(rows: dict[str, dict]) -> dict:
    observed = {}
    for label in ("com.lexi.v35.api-only", "com.lexi.v35.scheduler", "com.lexi.stage-center.scheduler"):
        row = rows[label]
        item = {"label": label, "plist_path": row["plist_path"], "manifest_path": row["manifest_path"]}
        try:
            item["plist_sha256"] = sha(Path(row["plist_path"]))
            item["manifest_sha256"] = sha(Path(row["manifest_path"]))
            if item["manifest_sha256"] != row["manifest_declared_sha256"]:
                item["status"] = "CANNOT_CONFIRM"
                item["reason"] = "CURRENT_MANIFEST_DIFFERS_FROM_BASELINE_DECLARATION"
            elif (item["plist_sha256"] != row["plist_sha256"]
                  or item["manifest_sha256"] != row["manifest_sha256"]):
                item["status"] = "EXTERNAL_CONCURRENT_CHANGE"
                item["reason"] = "CURRENT_HASH_DIFFERS_FROM_20261016_BASELINE"
            else:
                item["status"] = "UNCHANGED_FROM_BASELINE"
                item["reason"] = None
        except (OSError, KeyError, TypeError) as exc:
            item["status"] = "CANNOT_CONFIRM"
            item["reason"] = f"READ_FAILED:{type(exc).__name__}"
        observed[label] = item
    return {"observed_at": datetime.now().astimezone().isoformat(timespec="seconds"), "services": observed}


def record_observation(mode: str, before: dict, after: dict) -> dict:
    before_rows = before["services"]
    after_rows = after["services"]
    comparisons = {}
    for label, current in after_rows.items():
        previous = before_rows.get(label, {})
        if current.get("status") == "CANNOT_CONFIRM" or previous.get("status") == "CANNOT_CONFIRM":
            status = "CANNOT_CONFIRM"
        elif any(previous.get(key) != current.get(key) for key in ("plist_sha256", "manifest_sha256")):
            status = "EXTERNAL_CONCURRENT_CHANGE"
        else:
            status = current.get("status")
        comparisons[label] = {"status": status, "before": previous, "after": current}
    result = {"schema_version": "us-close-retry.non_us_observation.v1", "mode": mode,
              "captured_at": datetime.now().astimezone().isoformat(timespec="seconds"),
              "mutated_non_us_services": False, "services": comparisons}
    path = BASE / f"non_us_observation_{mode}.json"
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def verify_candidate() -> None:
    require(CANDIDATE_ROOT.is_dir() and CANDIDATE_APP.is_dir(), "CANDIDATE_ROOT_MISSING")
    require(CANDIDATE_MANIFEST.is_file() and sha(CANDIDATE_MANIFEST) == CANDIDATE_MANIFEST_SHA256, "CANDIDATE_MANIFEST_SHA_MISMATCH")
    require(CANDIDATE_PLIST.is_file() and sha(CANDIDATE_PLIST) == CANDIDATE_PLIST_SHA256, "CANDIDATE_PLIST_SHA_MISMATCH")
    require(ORIGINAL_PLIST.is_file() and sha(ORIGINAL_PLIST) == ORIGINAL_PLIST_SHA256, "ORIGINAL_PLIST_BACKUP_MISMATCH")
    manifest = json.loads(CANDIDATE_MANIFEST.read_text(encoding="utf-8"))
    candidate = manifest.get("candidate", {})
    require(manifest.get("activation_status") == "NOT_ACTIVATED", "CANDIDATE_ALREADY_MARKED_ACTIVE")
    require(candidate.get("release_id") == CANDIDATE_RELEASE_ID, "CANDIDATE_RELEASE_ID_MISMATCH")
    require(candidate.get("root") == str(CANDIDATE_ROOT) and candidate.get("app_root") == str(CANDIDATE_APP), "CANDIDATE_ROOT_IDENTITY_MISMATCH")
    inventory = manifest.get("application_inventory", {})
    entries = inventory.get("entries")
    require(isinstance(entries, list) and inventory.get("entry_count") == len(entries), "CANDIDATE_INVENTORY_COUNT_MISMATCH")
    paths = [entry.get("path") for entry in entries if isinstance(entry, dict)]
    require(len(paths) == len(entries) and paths == sorted(paths) and len(set(paths)) == len(paths), "CANDIDATE_INVENTORY_PATHS_INVALID")
    canonical = json.dumps(entries, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    require(hashlib.sha256(canonical).hexdigest() == inventory.get("aggregate_sha256"), "CANDIDATE_INVENTORY_AGGREGATE_MISMATCH")
    for entry in entries:
        relative = Path(entry["path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "CANDIDATE_INVENTORY_PATH_UNSAFE")
        path = CANDIDATE_APP / relative
        try:
            info = path.lstat()
        except OSError as exc:
            raise RuntimeError(f"CANDIDATE_INVENTORY_PATH_MISSING:{relative}") from exc
        if stat.S_ISLNK(info.st_mode):
            require(entry.get("kind") == "symlink" and entry.get("target") == os.readlink(path), f"CANDIDATE_INVENTORY_SYMLINK_MISMATCH:{relative}")
            require(entry.get("target_exists") == path.exists(), f"CANDIDATE_INVENTORY_SYMLINK_STATUS_MISMATCH:{relative}")
        else:
            require(stat.S_ISREG(info.st_mode) and entry.get("kind") == "file", f"CANDIDATE_INVENTORY_KIND_MISMATCH:{relative}")
            require(entry.get("size") == info.st_size and entry.get("mode") == f"{stat.S_IMODE(info.st_mode):04o}", f"CANDIDATE_INVENTORY_METADATA_MISMATCH:{relative}")
            require(entry.get("sha256") == sha(path), f"CANDIDATE_INVENTORY_SHA_MISMATCH:{relative}")
    pinned = plistlib.loads(CANDIDATE_PLIST.read_bytes())["EnvironmentVariables"]
    require(pinned.get("V35_APP_ROOT") == str(CANDIDATE_APP), "CANDIDATE_PLIST_APP_ROOT_MISMATCH")
    require(pinned.get("V35_RELEASE_ID") == CANDIDATE_RELEASE_ID, "CANDIDATE_PLIST_RELEASE_ID_MISMATCH")
    require(pinned.get("V35_RELEASE_MANIFEST_PATH") == str(CANDIDATE_MANIFEST), "CANDIDATE_PLIST_MANIFEST_PATH_MISMATCH")
    require(pinned.get("V35_RELEASE_MANIFEST_SHA256") == CANDIDATE_MANIFEST_SHA256, "CANDIDATE_PLIST_MANIFEST_SHA_MISMATCH")


def verify_candidate_delta_against_backup() -> None:
    before = plistlib.loads(ORIGINAL_PLIST.read_bytes())
    after = plistlib.loads(CANDIDATE_PLIST.read_bytes())
    expected = json.loads(json.dumps(before))
    env = expected["EnvironmentVariables"]
    env.update({
        "PYTHONPATH": f"{CANDIDATE_APP}/upstreams:{CANDIDATE_APP}",
        "V35_APP_ROOT": str(CANDIDATE_APP),
        "V35_RELEASE_ID": CANDIDATE_RELEASE_ID,
        "V35_RELEASE_MANIFEST_PATH": str(CANDIDATE_MANIFEST),
        "V35_RELEASE_MANIFEST_SHA256": CANDIDATE_MANIFEST_SHA256,
    })
    expected["WorkingDirectory"] = str(CANDIDATE_APP)
    require(after == expected, "CANDIDATE_PLIST_HAS_UNEXPECTED_CHANGES")


def check_us_active_state(mode: str, rows: dict[str, dict]) -> None:
    if mode == "activate":
        expected_plist = ORIGINAL_PLIST_SHA256
        expected_manifest = R1_ACTIVE_MANIFEST_SHA256
        manifest_path = R1_ACTIVE_MANIFEST
    else:
        expected_plist = CANDIDATE_PLIST_SHA256
        expected_manifest = CANDIDATE_MANIFEST_SHA256
        manifest_path = CANDIDATE_MANIFEST
    require(ACTIVE_PLIST.is_file() and sha(ACTIVE_PLIST) == expected_plist, "US_ACTIVE_PLIST_CAS_MISMATCH")
    require(manifest_path.is_file() and sha(manifest_path) == expected_manifest, "US_ACTIVE_MANIFEST_CAS_MISMATCH")
    if mode == "activate":
        # The immutable 10:13 baseline remains pinned in EXPECTED; current R1 is CAS-pinned above.
        require(US_LABEL in rows, "US_BASELINE_OWNER_MISSING")


def assert_no_active_us_process() -> None:
    result = subprocess.run(["launchctl", "print", f"{DOMAIN}/{US_LABEL}"], text=True, capture_output=True)
    require(result.returncode == 0, "CANNOT_CONFIRM_US_LAUNCHAGENT_STATE")
    match = re.search(r"^\s*active count = (\d+)\s*$", result.stdout, re.MULTILINE)
    require(match is not None, "CANNOT_CONFIRM_US_ACTIVE_COUNT")
    require(int(match.group(1)) == 0, "US_LAUNCHAGENT_PROCESS_ACTIVE")


def atomic_install(
    payload: bytes,
    *,
    expected_current_sha256: str | None = None,
    expected_current_manifest_path: Path | None = None,
    expected_current_manifest_sha256: str | None = None,
) -> None:
    mode = ACTIVE_PLIST.stat().st_mode & 0o777
    fd, raw = tempfile.mkstemp(prefix=".us-market-digest.", suffix=".tmp", dir=ACTIVE_PLIST.parent)
    temporary = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        if expected_current_manifest_path is not None:
            require(
                expected_current_manifest_sha256 is not None
                and expected_current_manifest_path.is_file()
                and sha(expected_current_manifest_path) == expected_current_manifest_sha256,
                "US_ACTIVE_MANIFEST_CAS_MISMATCH_BEFORE_REPLACE",
            )
        if expected_current_sha256 is not None:
            # Keep every other potentially slow check above this point. The
            # plist comparison must be the final validation immediately before
            # replace so a manifest read cannot hide a concurrent plist write.
            require(
                ACTIVE_PLIST.is_file() and sha(ACTIVE_PLIST) == expected_current_sha256,
                "US_ACTIVE_PLIST_CAS_MISMATCH_BEFORE_REPLACE",
            )
        os.replace(temporary, ACTIVE_PLIST)
        directory_fd = os.open(ACTIVE_PLIST.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def launchctl(*args: str) -> None:
    result = subprocess.run(["launchctl", *args], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f"LAUNCHCTL_FAILED:{' '.join(args)}:{result.stderr.strip()}")


def active_pair_matches(plist_sha256: str, manifest_path: Path, manifest_sha256: str) -> bool:
    return (
        ACTIVE_PLIST.is_file()
        and sha(ACTIVE_PLIST) == plist_sha256
        and manifest_path.is_file()
        and sha(manifest_path) == manifest_sha256
    )


def apply_activation(rows: dict[str, dict]) -> None:
    previous = ORIGINAL_PLIST.read_bytes()
    candidate = CANDIDATE_PLIST.read_bytes()
    previous_manifest_path = R1_ACTIVE_MANIFEST
    previous_manifest_sha256 = R1_ACTIVE_MANIFEST_SHA256
    launchctl("bootout", f"{DOMAIN}/{US_LABEL}")
    try:
        # Re-read after bootout and immediately before the replacement. This
        # catches a US-owner update that raced the initial plan/preflight.
        check_us_active_state("activate", rows)
    except Exception as error:
        try:
            launchctl("bootstrap", DOMAIN, str(ACTIVE_PLIST))
        except Exception as reload_error:
            raise RuntimeError(
                f"US_ACTIVE_CAS_CHANGED_AFTER_BOOTOUT_AND_RELOAD_FAILED:{reload_error}"
            ) from error
        raise RuntimeError("US_ACTIVE_CAS_CHANGED_AFTER_BOOTOUT; replacement skipped") from error
    try:
        atomic_install(
            candidate,
            expected_current_sha256=ORIGINAL_PLIST_SHA256,
            expected_current_manifest_path=previous_manifest_path,
            expected_current_manifest_sha256=previous_manifest_sha256,
        )
        launchctl("bootstrap", DOMAIN, str(ACTIVE_PLIST))
    except Exception as error:
        restore_error = None
        can_restore = active_pair_matches(
            CANDIDATE_PLIST_SHA256, CANDIDATE_MANIFEST, CANDIDATE_MANIFEST_SHA256
        )
        if can_restore:
            try:
                atomic_install(
                    previous,
                    expected_current_sha256=CANDIDATE_PLIST_SHA256,
                    expected_current_manifest_path=CANDIDATE_MANIFEST,
                    expected_current_manifest_sha256=CANDIDATE_MANIFEST_SHA256,
                )
            except Exception as rollback_error:
                restore_error = rollback_error
        try:
            launchctl("bootstrap", DOMAIN, str(ACTIVE_PLIST))
        except Exception as rollback_error:
            if can_restore and restore_error is None:
                raise RuntimeError(f"ACTIVATION_FAILED_AND_ROLLBACK_FAILED:{rollback_error}") from error
            raise RuntimeError(
                f"ACTIVATION_FAILED_US_ACTIVE_CHANGED_ROLLBACK_SKIPPED_RELOAD_FAILED:{rollback_error}"
            ) from error
        if not can_restore or restore_error is not None:
            raise RuntimeError("ACTIVATION_FAILED_US_ACTIVE_CHANGED_ROLLBACK_SKIPPED") from error
        raise


def apply_rollback(rows: dict[str, dict]) -> None:
    previous = CANDIDATE_PLIST.read_bytes()
    original = ORIGINAL_PLIST.read_bytes()
    launchctl("bootout", f"{DOMAIN}/{US_LABEL}")
    try:
        check_us_active_state("rollback", rows)
    except Exception as error:
        try:
            launchctl("bootstrap", DOMAIN, str(ACTIVE_PLIST))
        except Exception as reload_error:
            raise RuntimeError(
                f"US_ACTIVE_CAS_CHANGED_AFTER_BOOTOUT_AND_RELOAD_FAILED:{reload_error}"
            ) from error
        raise RuntimeError("US_ACTIVE_CAS_CHANGED_AFTER_BOOTOUT; rollback skipped") from error
    try:
        atomic_install(
            original,
            expected_current_sha256=CANDIDATE_PLIST_SHA256,
            expected_current_manifest_path=CANDIDATE_MANIFEST,
            expected_current_manifest_sha256=CANDIDATE_MANIFEST_SHA256,
        )
        launchctl("bootstrap", DOMAIN, str(ACTIVE_PLIST))
    except Exception as error:
        previous_manifest_path = R1_ACTIVE_MANIFEST
        previous_manifest_sha256 = R1_ACTIVE_MANIFEST_SHA256
        restore_error = None
        can_restore = active_pair_matches(
            ORIGINAL_PLIST_SHA256, previous_manifest_path, previous_manifest_sha256
        )
        if can_restore:
            try:
                atomic_install(
                    previous,
                    expected_current_sha256=ORIGINAL_PLIST_SHA256,
                    expected_current_manifest_path=previous_manifest_path,
                    expected_current_manifest_sha256=previous_manifest_sha256,
                )
            except Exception as rollback_error:
                restore_error = rollback_error
        try:
            launchctl("bootstrap", DOMAIN, str(ACTIVE_PLIST))
        except Exception as rollback_error:
            if can_restore and restore_error is None:
                raise RuntimeError(f"ROLLBACK_FAILED_AND_CANDIDATE_RESTORE_FAILED:{rollback_error}") from error
            raise RuntimeError(
                f"ROLLBACK_FAILED_US_ACTIVE_CHANGED_RESTORE_SKIPPED_RELOAD_FAILED:{rollback_error}"
            ) from error
        if not can_restore or restore_error is not None:
            raise RuntimeError("ROLLBACK_FAILED_US_ACTIVE_CHANGED_RESTORE_SKIPPED") from error
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--apply", action="store_true", help="perform the US-only LaunchAgent candidate activation")
    group.add_argument("--rollback", action="store_true", help="restore the pinned active R1 US LaunchAgent plist")
    args = parser.parse_args()
    mode = "rollback" if args.rollback else "activate"
    try:
        rows = baseline_rows()
        verify_protected_services(rows)
        non_us_before = observe_non_us_services(rows)
        verify_candidate()
        verify_candidate_delta_against_backup()
        check_us_active_state(mode, rows)
        assert_no_active_us_process()
        if not (args.apply or args.rollback):
            print(json.dumps({"status":"PLAN_READY","mode":mode,"mutations_performed":False,"active_plist":str(ACTIVE_PLIST),"candidate_plist_sha256":CANDIDATE_PLIST_SHA256,"candidate_manifest_sha256":CANDIDATE_MANIFEST_SHA256,"non_us_observation":non_us_before},sort_keys=True))
            return 0
        if args.apply:
            try:
                apply_activation(rows)
            except Exception:
                record_observation("activation", non_us_before, observe_non_us_services(rows))
                raise
            non_us_after = observe_non_us_services(rows)
            observation = record_observation("activation", non_us_before, non_us_after)
            print(json.dumps({"status":"ACTIVATED","mode":"activate","mutations_performed":True,"active_plist_sha256":sha(ACTIVE_PLIST),"non_us_observation":observation},sort_keys=True))
        else:
            try:
                apply_rollback(rows)
            except Exception:
                record_observation("rollback", non_us_before, observe_non_us_services(rows))
                raise
            non_us_after = observe_non_us_services(rows)
            observation = record_observation("rollback", non_us_before, non_us_after)
            print(json.dumps({"status":"ROLLED_BACK","mode":"rollback","mutations_performed":True,"active_plist_sha256":sha(ACTIVE_PLIST),"non_us_observation":observation},sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({"status":"CANNOT_CONFIRM","reason":str(exc),"mutations_performed":False},sort_keys=True),file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
