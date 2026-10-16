"""Explicitly gated, candidate-bound v2r1 activation and rollback entrypoint.

Default mode is plan-only. This helper does not authorize activation by itself;
future activation requires a separate direct authorization and independent
runtime review bound to the prepared candidate manifest.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import urllib.request


HANDOFF = Path(__file__).resolve().parents[1]
BASE = Path("/Users/lexi/Library/Application Support/com.lexi.v4.local")
PLIST = Path("/Users/lexi/Library/LaunchAgents/com.lexi.v35.api-only.plist")
CANDIDATE = BASE / "releases/us-hk-recovery-v2r1-20261016-r1"
PLAN_PATH = HANDOFF / "runtime/receipts/RUNTIME_PREPARATION_RECEIPT.json"
ACTIVATION_RECEIPT_PATH = HANDOFF / "runtime/receipts/RUNTIME_ACTIVATION_RECEIPT.json"
REVIEW_RECEIPT_PATH = HANDOFF / "runtime/receipts/RUNTIME_INDEPENDENT_REVIEW_REPAIR_20261016.md"
CORE_PATH = Path(__file__).resolve().parents[2] / "us_hk_700_supplement_20261016/activate_runtime_candidate.py"
WRITER_IDENTITY = "mapping_recovery_writer"
PORT = 8873


def load_core():
    """Load shared lock/release and low-level macOS helpers without its main()."""
    spec = importlib.util.spec_from_file_location("v2r1_activation_shared_helpers", CORE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("ACTIVATION_SHARED_HELPERS_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def configure_core(core, plan: dict[str, object]) -> None:
    """Bind imported low-level helpers to this candidate; never delegate main()."""
    core.CANDIDATE = Path(plan["candidate_root"])
    core.ACTIVE_CONFIG = Path(plan["active_config_path"])
    core.NEW_CONFIG = Path(plan["new_config_path"])
    core.STAGED_PLIST = Path(plan["staged_plist_path"])
    core.ROLLBACK_PLIST = Path(plan["rollback_plist_path"])
    core.PORT = PORT


def require_review(path: Path, manifest_sha: str) -> str:
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    if path.resolve() != REVIEW_RECEIPT_PATH.resolve():
        raise RuntimeError("UNEXPECTED_RUNTIME_REVIEW_RECEIPT_PATH")
    if text.count("# Runtime independent review") != 1:
        raise RuntimeError("REVIEW_RECEIPT_FORMAT_INVALID")
    reviewer_lines = re.findall(r"(?m)^Reviewer:.*$", text)
    if len(reviewer_lines) != 1:
        raise RuntimeError("REVIEWER_IDENTITY_REQUIRED")
    match = re.fullmatch(
        r"Reviewer: `([^`\r\n]+)` \(independent from `([^`\r\n]+)`\)", reviewer_lines[0]
    )
    if (match is None or not match.group(1).strip()
            or match.group(2).strip().casefold() != WRITER_IDENTITY
            or match.group(1).strip().casefold() == WRITER_IDENTITY):
        raise RuntimeError("REVIEWER_IDENTITY_NOT_INDEPENDENT")
    manifest_lines = re.findall(r"(?m)^Candidate manifest SHA256:.*$", text)
    manifest_match = re.fullmatch(
        r"Candidate manifest SHA256: `([0-9a-fA-F]{64})`",
        manifest_lines[0] if len(manifest_lines) == 1 else "",
    )
    if manifest_match is None or manifest_match.group(1).casefold() != manifest_sha.casefold():
        raise RuntimeError("REVIEW_RECEIPT_CANDIDATE_SHA_MISMATCH")
    reviewed = re.findall(r"(?m)^REVIEWED=.*$", text)
    behavior = re.findall(r"(?m)^BEHAVIOR_VERIFIED=.*$", text)
    if len(reviewed) != 1 or not re.fullmatch(r"REVIEWED=PASS(?:\s+—.*)?", reviewed[0]):
        raise RuntimeError("REVIEWED_PASS_REQUIRED")
    if len(behavior) != 1 or not re.fullmatch(r"BEHAVIOR_VERIFIED=PASS(?:\s+—.*)?", behavior[0]):
        raise RuntimeError("BEHAVIOR_VERIFIED_PASS_REQUIRED")
    return core_sha(raw)


def core_sha(raw: bytes) -> str:
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def check_live_api() -> dict[str, object]:
    base_url = f"http://127.0.0.1:{PORT}/api/v4/manager-workbench/mapping-catalog"

    def read(query: str | None = None) -> tuple[dict[str, object], int]:
        url = base_url if query is None else base_url + "?q=" + query
        with urllib.request.urlopen(url, timeout=5) as response:
            raw = response.read()
        return json.loads(raw)["data"], len(raw)

    data, default_bytes = read()
    recovery = data.get("recovery_v2r1", {})
    counts = recovery.get("counts", {})
    expected = {"snapshot_stocks": 667, "original_relations": 1003, "processed_relations": 1003}
    if any(counts.get(key) != value for key, value in expected.items()):
        raise RuntimeError("LIVE_V2R1_COUNT_MISMATCH")
    if counts.get("closure_status_counts") != {
        "CLOSED_RESEARCH_SCOPE": 757, "CLOSED_EXCLUDED_SCOPE": 25, "OPEN": 221,
    }:
        raise RuntimeError("LIVE_V2R1_CLOSURE_COUNTS_MISMATCH")
    if (recovery.get("prior_700_history", {}).get("record_count") != 700
            or recovery.get("prior_700_history", {}).get("status_crosswalk") != "NOT_ESTABLISHED"):
        raise RuntimeError("LIVE_PRIOR_700_HISTORY_MISMATCH")
    if data.get("safety", {}).get("production_allowed") is not False:
        raise RuntimeError("LIVE_RESEARCH_ONLY_BOUNDARY_MISMATCH")

    exact_rows: dict[str, dict[str, object]] = {}
    for relation_id in ("R006", "R003", "R001", "R700"):
        body, _ = read(relation_id)
        matches = [relation for item in body.get("items", [])
                   for relation in item.get("relations", [])
                   if relation.get("relation_id") == relation_id]
        if len(matches) != 1:
            raise RuntimeError("LIVE_EXACT_RID_MISMATCH:" + relation_id)
        exact_rows[relation_id] = matches[0]

    if (exact_rows["R001"].get("source_review_status") != "SOURCE_REVIEWED"
            or exact_rows["R001"].get("review_detail_level") != "FULL"
            or not exact_rows["R001"].get("review_revision", {}).get("evidence")):
        raise RuntimeError("LIVE_R001_PRIOR_HISTORY_MISMATCH")
    if (exact_rows["R700"].get("source_review_status") != "NOT_PROCESSED"
            or exact_rows["R700"].get("review_detail_level") != "FULL"
            or exact_rows["R700"].get("review_revision") is not None
            or exact_rows["R700"].get("recovery_v2r1", {}).get("detail_level") != "FULL"):
        raise RuntimeError("LIVE_R700_SEPARATE_HISTORY_MISMATCH")
    for relation_id, status in (("R006", "CLOSED_RESEARCH_SCOPE"),
                                ("R003", "CLOSED_EXCLUDED_SCOPE"),
                                ("R001", "OPEN")):
        if exact_rows[relation_id].get("recovery_v2r1", {}).get("closure_status") != status:
            raise RuntimeError("LIVE_V2R1_EXACT_STATUS_MISMATCH:" + relation_id)
    for key, value in (("RESEARCH_ONLY", True), ("production_allowed", False),
                       ("buy_gate_updated", False), ("orders_sent", False)):
        if data.get("safety", {}).get(key) is not value:
            raise RuntimeError("LIVE_SAFETY_FLAG_MISMATCH:" + key)
    return {"default_response_bytes": default_bytes, "snapshot_stocks": 667,
            "relations": 1003, "closure_status_counts": counts["closure_status_counts"],
            "exact_rids": ["R006", "R003", "R001", "R700"],
            "old_700_history_preserved": True, "trading_flags_safe": True}


def inspect_service_identity(target: str, label: str) -> dict[str, object]:
    """Read only: retain PID/listener identity without dumping process environments."""
    try:
        state = subprocess.run(["/bin/launchctl", "print", target + "/" + label],
                               capture_output=True, text=True, timeout=10)
        state_text = state.stdout.splitlines()
        state_value = next((line.strip().split("=", 1)[1].strip() for line in state_text
                            if line.strip().startswith("state =")), None)
        pid_raw = next((line.strip().split("=", 1)[1].strip() for line in state_text
                        if line.strip().startswith("pid =")), None)
        listeners = subprocess.run(["/usr/sbin/lsof", "-t", "-nP", f"-iTCP:{PORT}", "-sTCP:LISTEN"],
                                   capture_output=True, text=True, timeout=10)
        if state.returncode not in (0, 113) or listeners.returncode not in (0, 1):
            return {"status": "UNKNOWN", "launchctl_exit_code": state.returncode,
                    "lsof_exit_code": listeners.returncode}
        pids = sorted({int(value) for value in listeners.stdout.split() if value.isdecimal()})
        return {"status": "KNOWN", "label_present": state.returncode == 0,
                "launchd_state": state_value, "launchd_pid": int(pid_raw) if pid_raw and pid_raw.isdecimal() else None,
                "port_listener_pids": pids}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "UNKNOWN", "error": f"{type(exc).__name__}:{exc}"}


def _service_is_detached(identity: dict[str, object]) -> bool:
    return (identity.get("status") == "KNOWN" and identity.get("label_present") is False
            and identity.get("launchd_pid") is None and identity.get("port_listener_pids") == [])


def rollback_after_failure(*, original: bytes, mode: int, target: str, label: str,
                           candidate_selected: bool, prior_service_detached: bool,
                           detach, install, bootstrap, probe, read_plist) -> dict[str, object]:
    """Restore the saved plist despite detach failure; bootstrap only after proven detach."""
    result: dict[str, object] = {
        "candidate_plist_was_selected": candidate_selected,
        "detach": {"status": "NOT_REQUIRED"},
        "original_plist_restore": {"status": "NOT_REQUIRED"},
        "prior_service_bootstrap": {"status": "NOT_ATTEMPTED"},
    }
    detach_confirmed = prior_service_detached
    if candidate_selected:
        try:
            detach_result = detach()
            if (not isinstance(detach_result, dict)
                    or detach_result.get("old_pids_exited") is not True
                    or detach_result.get("label_absent") is not True):
                raise RuntimeError("SERVICE_DETACH_NOT_CONFIRMED")
            result["detach"] = {"status": "PASS", "result": detach_result}
            detach_confirmed = True
        except Exception as exc:  # preserve the detach failure while continuing restore
            result["detach"] = {"status": "FAIL", "error": f"{type(exc).__name__}:{exc}"}
            detach_confirmed = False

        try:
            install(original, mode)
            restored = read_plist()
            if restored != original:
                raise RuntimeError("RESTORED_PLIST_READBACK_MISMATCH")
            result["original_plist_restore"] = {"status": "PASS", "sha256": core_sha(restored)}
        except Exception as exc:
            result["original_plist_restore"] = {"status": "FAIL", "error": f"{type(exc).__name__}:{exc}"}

    try:
        identity = probe()
    except Exception as exc:
        identity = {"status": "UNKNOWN", "error": f"{type(exc).__name__}:{exc}"}
    result["process_identity_after_detach"] = identity
    if not detach_confirmed:
        skipped_status = ("SKIPPED_PROCESS_IDENTITY_UNCONFIRMED"
                          if identity.get("status") == "UNKNOWN"
                          else "SKIPPED_DETACH_CONFIRMATION_FAILED")
        result["prior_service_bootstrap"] = {
            "status": skipped_status,
            "reason": "Detach did not confirm; avoid creating a duplicate API-only service.",
        }
    elif not _service_is_detached(identity):
        result["prior_service_bootstrap"] = {
            "status": "SKIPPED_SERVICE_NOT_PROVEN_DETACHED",
            "reason": "The launchd label and listener state do not prove the old service is fully detached.",
        }
    elif result["original_plist_restore"]["status"] == "FAIL":
        result["prior_service_bootstrap"] = {
            "status": "SKIPPED_PLIST_RESTORE_FAILED",
            "reason": "The saved active plist was not verified after atomic restoration.",
        }
    else:
        try:
            result["prior_service_bootstrap"] = {"status": "PASS", "result": bootstrap(target)}
        except Exception as exc:
            result["prior_service_bootstrap"] = {"status": "FAIL", "error": f"{type(exc).__name__}:{exc}"}

    if (result["original_plist_restore"]["status"] in ("PASS", "NOT_REQUIRED")
            and result["prior_service_bootstrap"]["status"] == "PASS"):
        result["status"] = "ROLLED_BACK_PRIOR_SERVICE_RESTARTED"
    elif (result["original_plist_restore"]["status"] == "PASS"
          and result["prior_service_bootstrap"]["status"] == "SKIPPED_PROCESS_IDENTITY_UNCONFIRMED"):
        result["status"] = "ORIGINAL_PLIST_RESTORED_SERVICE_IDENTITY_UNKNOWN"
    elif (result["original_plist_restore"]["status"] == "PASS"
          and result["prior_service_bootstrap"]["status"] == "SKIPPED_DETACH_CONFIRMATION_FAILED"):
        result["status"] = "ORIGINAL_PLIST_RESTORED_DETACH_CONFIRMATION_FAILED"
    else:
        result["status"] = "ROLLBACK_INCOMPLETE"
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-receipt", type=Path)
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--root-authorization-ref")
    args = parser.parse_args()
    if not PLAN_PATH.is_file():
        raise RuntimeError("RUNTIME_PREPARATION_RECEIPT_REQUIRED")
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    if (plan.get("status") != "PREPARED_NOT_ACTIVATED"
            or plan.get("activation_status") != "NOT_ACTIVATED"
            or plan.get("candidate_root") != str(CANDIDATE)):
        raise RuntimeError("CANDIDATE_NOT_PREPARED_FOR_ACTIVATION")
    if (plan.get("source_review", {}).get("status")
            != "REVIEWED_PASS_AND_BEHAVIOR_VERIFIED_PASS"):
        raise RuntimeError("SOURCE_REVIEW_NOT_PASS")
    if not args.activate:
        print(json.dumps({"status": "PREPARED_ONLY", "launchctl_called": False,
                          "activation_requires": "--activate plus separate root authorization and independent runtime review PASS"}))
        return
    if not args.root_authorization_ref or not args.root_authorization_ref.strip():
        raise RuntimeError("EXPLICIT_ROOT_AUTHORIZATION_REFERENCE_REQUIRED")
    if args.review_receipt is None or not args.review_receipt.is_file():
        raise RuntimeError("INDEPENDENT_REVIEW_RECEIPT_REQUIRED")
    if ACTIVATION_RECEIPT_PATH.exists():
        raise RuntimeError("ACTIVATION_RECEIPT_ALREADY_EXISTS_REFUSE_OVERWRITE")

    core = load_core()
    configure_core(core, plan)
    review_sha = require_review(args.review_receipt, str(plan["candidate_manifest_sha256"]))
    receipt: dict[str, object] = {
        "started_at": datetime.now(timezone.utc).isoformat(), "status": "PREFLIGHT",
        "launchctl_called": False, "launchctl_read_only_probe_called": False,
        "root_authorization_ref": args.root_authorization_ref.strip(),
        "review_receipt": str(args.review_receipt), "review_receipt_sha256": review_sha,
        "candidate_manifest_sha256": plan["candidate_manifest_sha256"], "commands": [],
    }
    operation_error: Exception | None = None
    try:
        with core.shared_api_release_lock(PLIST, timeout_seconds=5, role="gateway") as lease:
            original = core.ROLLBACK_PLIST.read_bytes()
            original_sha = core.sha(original)
            mode = stat.S_IMODE(PLIST.stat().st_mode)
            target = "gui/" + str(os.getuid())
            label = "com.lexi.v35.api-only"
            preflight_detached = False
            mutation_started = False
            try:
                if core.file_sha(PLIST) != plan["active_plist_sha256"]:
                    raise RuntimeError("ACTIVE_PLIST_CAS_CHANGED_REBASE_REQUIRED")
                if core.file_sha(core.ACTIVE_CONFIG) != plan["active_config_sha256"]:
                    raise RuntimeError("ACTIVE_CONFIG_CAS_CHANGED_REBASE_REQUIRED")
                if core.file_sha(core.NEW_CONFIG) != plan["new_config_sha256"]:
                    raise RuntimeError("CANDIDATE_CONFIG_CAS_CHANGED")
                if core.file_sha(core.STAGED_PLIST) != plan["staged_plist_sha256"]:
                    raise RuntimeError("STAGED_PLIST_CAS_CHANGED")
                if original_sha != plan["rollback_plist_sha256"] or original != PLIST.read_bytes():
                    raise RuntimeError("ROLLBACK_PREIMAGE_CAS_MISMATCH")
                if original_sha != plan["active_plist_sha256"]:
                    raise RuntimeError("BASE_PLIST_AND_ROLLBACK_PREIMAGE_DIFFER")
                receipt["preflight"] = core.verify_api_release_candidate(
                    candidate_root=CANDIDATE, active_api_plist_path=PLIST,
                    expected_manifest_sha256=plan["candidate_manifest_sha256"],
                    active_pointer="base", require_shared_lock=True, lock_lease=lease,
                    role="gateway", base_role="gateway")
                receipt["launchctl_called"] = True
                mutation_started = True
                try:
                    detached = core.bootout_and_wait(target, label)
                    receipt["commands"].append(detached)
                    receipt["preflight_detach"] = {"status": "PASS", "result": detached}
                except Exception as detach_error:
                    receipt["preflight_detach"] = {
                        "status": "FAIL", "error": f"{type(detach_error).__name__}:{detach_error}"}
                    raise
                preflight_detached = True
                core.atomic_install(core.STAGED_PLIST.read_bytes(), mode)
                if core.file_sha(PLIST) != plan["staged_plist_sha256"]:
                    raise RuntimeError("STAGED_PLIST_INSTALL_READBACK_MISMATCH")
                receipt["commands"].append(core.launch("bootstrap", target, str(PLIST)))
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
                receipt["postflight"] = core.verify_api_release_candidate(
                    candidate_root=CANDIDATE, active_api_plist_path=PLIST,
                    expected_manifest_sha256=plan["candidate_manifest_sha256"],
                    active_pointer="candidate", require_shared_lock=True, lock_lease=lease,
                    role="gateway", base_role="gateway")
                receipt["status"] = "ACTIVATED_API_READBACK_OK"
                receipt["active_plist_sha256"] = core.file_sha(PLIST)
            except Exception as exc:
                operation_error = exc
                receipt["activation_error"] = f"{type(exc).__name__}:{exc}"
                if not mutation_started:
                    receipt["status"] = "PREFLIGHT_FAILED"
                    raise
                try:
                    current_sha = core.file_sha(PLIST)
                except Exception as inspect_error:
                    current_sha = None
                    receipt["active_plist_read_error"] = f"{type(inspect_error).__name__}:{inspect_error}"
                staged_sha = plan["staged_plist_sha256"]
                if current_sha == staged_sha:
                    candidate_selected = True
                elif current_sha == original_sha:
                    candidate_selected = False
                else:
                    candidate_selected = False
                    receipt["rollback_refusal"] = "ACTIVE_PLIST_IDENTITY_UNEXPECTED_NO_OVERWRITE"
                if current_sha in (staged_sha, original_sha):
                    receipt["launchctl_read_only_probe_called"] = True
                    receipt["rollback"] = rollback_after_failure(
                        original=original, mode=mode, target=target, label=label,
                        candidate_selected=candidate_selected,
                        prior_service_detached=preflight_detached,
                        detach=lambda: core.bootout_and_wait(target, label, check=False),
                        install=core.atomic_install,
                        bootstrap=lambda bootstrap_target: core.launch(
                            "bootstrap", bootstrap_target, str(PLIST)),
                        probe=lambda: inspect_service_identity(target, label),
                        read_plist=PLIST.read_bytes)
                    receipt["launchctl_called"] = receipt["launchctl_called"] or (
                        receipt["rollback"].get("detach", {}).get("status") == "PASS"
                        or receipt["rollback"].get("prior_service_bootstrap", {}).get("status") == "PASS")
                    if receipt["rollback"]["status"] == "ROLLED_BACK_PRIOR_SERVICE_RESTARTED":
                        receipt["status"] = "FAILED_ROLLED_BACK"
                    else:
                        receipt["status"] = "FAILED_ROLLBACK_INCOMPLETE"
                else:
                    receipt["launchctl_read_only_probe_called"] = True
                    receipt["process_identity_after_active_plist_mismatch"] = inspect_service_identity(
                        target, label)
                    receipt["status"] = "FAILED_ACTIVE_PLIST_IDENTITY_UNKNOWN"
            except BaseException as exc:
                operation_error = exc
                raise
    except Exception as exc:
        if operation_error is None:
            operation_error = exc
            receipt["activation_error"] = f"{type(exc).__name__}:{exc}"
            receipt["status"] = "PREFLIGHT_FAILED"

    receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
    with ACTIVATION_RECEIPT_PATH.open("x", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")
    if operation_error is not None:
        raise RuntimeError("ACTIVATION_FAILED; receipt=" + str(ACTIVATION_RECEIPT_PATH)) from operation_error
    print(json.dumps({key: value for key, value in receipt.items()
                      if key not in ("preflight", "postflight")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
