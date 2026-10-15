"""Explicitly gated activation/rollback script for a reviewed local candidate.

Do not run during PREPARE_RUNTIME. Activation requires a later explicit root
authorization plus a different-identity review receipt bound to the prepared
candidate manifest SHA. The script uses the existing release lock and CAS.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import stat
import subprocess
import tempfile
import time
import urllib.request

from ops.api_release_integration import (
    shared_api_release_lock,
    verify_api_release_candidate,
)


BASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
CANDIDATE = BASE / "releases/us-hk-mapping700-20261016-r1"
ACTIVE_CONFIG = BASE / "config/oversold-nextday-recovery-20261015-r1.json"
NEW_CONFIG = BASE / "config/us-hk-mapping700-20261016-r1.json"
PLAN_PATH = CANDIDATE / "config/cutover-plan.json"
STAGED_PLIST = CANDIDATE / "config/com.lexi.v35.api-only.plist"
ROLLBACK_PLIST = CANDIDATE / "config/active-api-plist.preimage"
ACTIVATION_RECEIPT_PATH = Path(__file__).resolve().parent / "runtime-activation-receipt.json"
PORT = 8873


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha(path: Path) -> str:
    return sha(path.read_bytes())


def atomic_install(raw: bytes, mode: int) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".com.lexi.v35.api-only.mapping700-", dir=PLIST.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, PLIST)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def launch(*args: str, check: bool = True) -> dict[str, object]:
    result = subprocess.run(["/bin/launchctl", *args], capture_output=True, text=True, timeout=30)
    row = {"argv": ["launchctl", *args], "exit_code": result.returncode,
           "stdout": result.stdout, "stderr": result.stderr}
    if check and result.returncode:
        raise RuntimeError("LAUNCHCTL_FAILED:" + args[0])
    return row


def bootout_and_wait(target: str, label: str, *, check: bool = True) -> dict[str, object]:
    pid_result = subprocess.run(["/usr/sbin/lsof", "-t", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN"],
                                capture_output=True, text=True, timeout=10)
    old_pids = [int(value) for value in pid_result.stdout.split() if value.isdecimal()]
    command = launch("bootout", target + "/" + label, check=check)
    for attempt in range(20):
        state = subprocess.run(["/bin/launchctl", "print", target + "/" + label],
                               capture_output=True, text=True, timeout=10)
        alive = [pid for pid in old_pids if subprocess.run(["/bin/kill", "-0", str(pid)],
                 capture_output=True, timeout=5).returncode == 0]
        if state.returncode and not alive:
            time.sleep(2)
            return {"bootout": command, "old_pids": old_pids, "old_pids_exited": True,
                    "label_absent": True, "settle_seconds": 2}
        time.sleep(0.5)
    raise RuntimeError("SERVICE_DETACH_NOT_CONFIRMED")


def require_review(path: Path, manifest_sha: str) -> str:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    heading_rows = re.findall(r"(?m)^(# Runtime independent review)\s*$", text)
    if heading_rows != ["# Runtime independent review"]:
        raise RuntimeError("REVIEW_RECEIPT_FORMAT_INVALID")

    reviewer_lines = re.findall(r"(?m)^Reviewer:.*$", text)
    if len(reviewer_lines) != 1:
        raise RuntimeError("REVIEWER_IDENTITY_REQUIRED")
    reviewer_match = re.fullmatch(
        r"Reviewer: `([^`\r\n]+)` \(independent from `([^`\r\n]+)`\)", reviewer_lines[0]
    )
    if reviewer_match is None or not reviewer_match.group(1).strip():
        raise RuntimeError("REVIEWER_IDENTITY_REQUIRED")
    reviewer = reviewer_match.group(1).strip().casefold()
    writer_identity = reviewer_match.group(2).strip().casefold()
    if reviewer == "mapping700_writer" or writer_identity != "mapping700_writer":
        raise RuntimeError("REVIEWER_IDENTITY_NOT_INDEPENDENT")

    manifest_lines = re.findall(r"(?m)^Candidate manifest SHA256:.*$", text)
    if len(manifest_lines) != 1:
        raise RuntimeError("REVIEW_RECEIPT_FORMAT_INVALID")
    manifest_match = re.fullmatch(r"Candidate manifest SHA256: `([0-9a-fA-F]{64})`", manifest_lines[0])
    if manifest_match is None:
        raise RuntimeError("REVIEW_RECEIPT_FORMAT_INVALID")
    if manifest_match.group(1).casefold() != manifest_sha.casefold():
        raise RuntimeError("REVIEW_RECEIPT_CANDIDATE_SHA_MISMATCH")

    reviewed_lines = re.findall(r"(?m)^REVIEWED=.*$", text)
    if len(reviewed_lines) != 1 or not re.fullmatch(r"REVIEWED=PASS(?:\s+—.*)?", reviewed_lines[0]):
        raise RuntimeError("REVIEWED_PASS_REQUIRED")
    behavior_lines = re.findall(r"(?m)^BEHAVIOR_VERIFIED=.*$", text)
    if len(behavior_lines) != 1 or not re.fullmatch(
        r"BEHAVIOR_VERIFIED=PASS(?:\s+—.*)?", behavior_lines[0]
    ):
        raise RuntimeError("BEHAVIOR_VERIFIED_PASS_REQUIRED")
    return sha(raw)


def check_live_api() -> dict[str, object]:
    base_url = f"http://127.0.0.1:{PORT}/api/v4/manager-workbench/mapping-catalog"

    def read_catalog(query: str | None = None) -> tuple[dict[str, object], int]:
        url = base_url if query is None else base_url + "?q=" + query
        with urllib.request.urlopen(url, timeout=3) as response:
            raw = response.read()
        return json.loads(raw)["data"], len(raw)

    data, response_bytes = read_catalog()
    if (data["coverage"]["membership_count"] != 667
            or data["coverage"]["relation_row_count"] != 1003
            or data["review_progress"]["source_reviewed_relations"] != 700
            or data["review_progress"]["unprocessed_relations"] != 303
            or data["review_progress"]["independently_verified_relations"] != 0
            or data["safety"].get("RESEARCH_ONLY") is not True
            or data["safety"].get("production_allowed") is not False
            or data["safety"].get("buy_gate_updated") is not False
            or data["safety"].get("orders_sent") is not False):
        raise RuntimeError("LIVE_MAPPING700_IDENTITY_MISMATCH")

    def exact_relation(query: str, relation_id: str) -> dict[str, object]:
        result, _ = read_catalog(query)
        matches = [relation for item in result.get("items", [])
                   for relation in item.get("relations", [])
                   if relation.get("relation_id") == relation_id]
        if len(matches) != 1:
            raise RuntimeError(f"LIVE_{relation_id}_READBACK_MISMATCH")
        return matches[0]

    reviewed = exact_relation("R001", "R001")
    review_revision = reviewed.get("review_revision")
    evidence = review_revision.get("evidence") if isinstance(review_revision, dict) else None
    required_evidence_fields = {
        "declared_unresolved_navigation_reference_json",
        "evidence_wording_clarifications_json",
    }
    if (reviewed.get("source_review_status") != "SOURCE_REVIEWED"
            or reviewed.get("review_detail_level") != "FULL"
            or not isinstance(evidence, list)
            or not any(isinstance(row, dict) and required_evidence_fields <= row.keys()
                       for row in evidence)):
        raise RuntimeError("LIVE_R001_REVIEWED_READBACK_MISMATCH")

    unprocessed = exact_relation("R700", "R700")
    if (unprocessed.get("source_review_status"), unprocessed.get("review_detail_level"),
            unprocessed.get("review_revision")) != ("NOT_PROCESSED", "SUMMARY", None):
        raise RuntimeError("LIVE_R700_UNPROCESSED_READBACK_MISMATCH")

    return {"response_bytes": response_bytes, "membership_count": 667, "relation_count": 1003,
            "reviewed": 700, "unprocessed": 303, "independently_verified": 0,
            "exact_reviewed_rid": "R001/FULL/two evidence fields",
            "exact_unprocessed_rid": "R700/NOT_PROCESSED/SUMMARY/null"}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-receipt", type=Path)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--root-authorization-ref")
    args = parser.parse_args()
    if not args.activate:
        print(json.dumps({"status": "PREPARED_ONLY", "launchctl_called": False,
                          "activation_requires": "--activate plus explicit root authorization and independent review PASS"}))
        return
    if not args.root_authorization_ref:
        raise RuntimeError("EXPLICIT_ROOT_AUTHORIZATION_REFERENCE_REQUIRED")
    if args.review_receipt is None or not args.review_receipt.is_file():
        raise RuntimeError("INDEPENDENT_REVIEW_RECEIPT_REQUIRED")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if plan.get("activation_status") != "NOT_ACTIVATED":
        raise RuntimeError("CANDIDATE_NOT_PREPARED")
    review_sha = require_review(args.review_receipt, plan["candidate_manifest_sha256"])
    receipt = {"started_at": datetime.now(timezone.utc).isoformat(), "status": "PREFLIGHT",
               "launchctl_called": False, "root_authorization_ref": args.root_authorization_ref,
               "review_receipt": str(args.review_receipt), "review_receipt_sha256": review_sha,
               "candidate_manifest_sha256": plan["candidate_manifest_sha256"], "commands": []}
    with shared_api_release_lock(PLIST, timeout_seconds=5, role="gateway") as lease:
        if file_sha(PLIST) != plan["active_plist_sha256"]:
            raise RuntimeError("ACTIVE_PLIST_CAS_CHANGED_REBASE_REQUIRED")
        if file_sha(ACTIVE_CONFIG) != plan["active_config_sha256"]:
            raise RuntimeError("ACTIVE_CONFIG_CAS_CHANGED_REBASE_REQUIRED")
        if file_sha(NEW_CONFIG) != plan["new_config_sha256"]:
            raise RuntimeError("CANDIDATE_CONFIG_CAS_CHANGED")
        if file_sha(STAGED_PLIST) != plan["staged_plist_sha256"]:
            raise RuntimeError("STAGED_PLIST_CAS_CHANGED")
        original = ROLLBACK_PLIST.read_bytes()
        if sha(original) != plan["rollback_plist_sha256"] or original != PLIST.read_bytes():
            raise RuntimeError("ROLLBACK_PREIMAGE_CAS_MISMATCH")
        receipt["preflight"] = verify_api_release_candidate(candidate_root=CANDIDATE,
            active_api_plist_path=PLIST, expected_manifest_sha256=plan["candidate_manifest_sha256"],
            active_pointer="base", require_shared_lock=True, lock_lease=lease, role="gateway", base_role="gateway")
        mode = stat.S_IMODE(PLIST.stat().st_mode)
        target = "gui/" + str(os.getuid())
        label = "com.lexi.v35.api-only"
        bootout_started = False
        try:
            bootout_started = True
            receipt["commands"].append(bootout_and_wait(target, label))
            atomic_install(STAGED_PLIST.read_bytes(), mode)
            receipt["commands"].append(launch("bootstrap", target, str(PLIST)))
            receipt["launchctl_called"] = True
            last_error = None
            for attempt in range(20):
                try:
                    receipt["live_first_read"] = check_live_api()
                    break
                except Exception as exc:
                    last_error = str(exc)
                    if attempt == 19:
                        raise RuntimeError("LIVE_API_READBACK_FAILED:" + last_error)
                    time.sleep(1)
            receipt["postflight"] = verify_api_release_candidate(candidate_root=CANDIDATE,
                active_api_plist_path=PLIST, expected_manifest_sha256=plan["candidate_manifest_sha256"],
                active_pointer="candidate", require_shared_lock=True, lock_lease=lease,
                role="gateway", base_role="gateway")
            receipt["status"] = "ACTIVATED_API_READBACK_OK"
            receipt["active_plist_sha256"] = file_sha(PLIST)
        except Exception:
            if bootout_started:
                if file_sha(PLIST) != plan["active_plist_sha256"]:
                    bootout_and_wait(target, label, check=False)
                    atomic_install(original, mode)
                state = subprocess.run(["/bin/launchctl", "print", target + "/" + label],
                                       capture_output=True, text=True, timeout=10)
                if state.returncode:
                    receipt["commands"].append(launch("bootstrap", target, str(PLIST)))
                receipt["rollback_performed"] = True
                receipt["rollback_plist_sha256"] = file_sha(PLIST)
                receipt["status"] = "FAILED_ROLLED_BACK"
            raise
        finally:
            receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
            out = ACTIVATION_RECEIPT_PATH
            with out.open("x", encoding="utf-8") as handle:
                json.dump(receipt, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
    print(json.dumps({key: value for key, value in receipt.items() if key not in ("preflight", "postflight")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
