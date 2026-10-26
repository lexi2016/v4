"""Controller-only launchd activation/rollback for the three owned one-shots.

No API or main-scheduler lifecycle action. Disable prevents another calendar
start while the current process finishes naturally; bootout is only issued
after every owned job is idle. No signal, kill, kickstart, or forced timeout.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import time
import uuid

from integrate_batch1 import CASE, owned_lock, reviewed_inputs, sha, wait_natural_exit
from api_activation_gate import verify_api_ready


def command(args, *, run=subprocess.run, check=True):
    result = run(["/bin/launchctl", *args], capture_output=True, text=True, timeout=15)
    if check and result.returncode:
        # Preserve diagnostic text locally, without echoing process env.
        raise RuntimeError("LAUNCHCTL_FAILED:" + args[0] + ":" + result.stderr[:2048])
    return result


def disabled_state(labels, *, run=subprocess.run):
    text = command(["print-disabled", f"gui/{os.getuid()}"], run=run).stdout
    return {label: bool(re.search(r'"' + re.escape(label) + r'"\s*=>\s*true\b', text)) for label in labels}


def loaded_state(operation, *, run=subprocess.run):
    result = command(["print", f"gui/{os.getuid()}/{operation['label']}"], run=run, check=False)
    if result.returncode:
        if "Could not find service" in result.stderr + result.stdout:
            return {"loaded": False}
        raise RuntimeError("LOADED_STATE_UNAVAILABLE:" + operation["label"])
    interval = re.search(r"run interval = (\d+) seconds", result.stdout)
    pid = re.search(r"^\s*pid = (\d+)\s*$", result.stdout, re.MULTILINE)
    return {"loaded": True, "interval_seconds": int(interval.group(1)) if interval else None,
            "pid": int(pid.group(1)) if pid else None, "text": result.stdout}


def activate(plan, *, rollback, wait_seconds, run=subprocess.run, journal_root=CASE / "integration",
             api_receipt=None, api_validator=verify_api_ready):
    operations = [op for op in plan["operations"] if op["role"] == "graph"]
    if [(op['role'],op['label']) for op in operations] != [('graph','com.lexi.v35.runtime-graph')]:
        raise ValueError('R4_EXACT_GRAPH_ONLY')
    if not rollback and api_receipt is None:
        raise ValueError("API_CURRENT_BINDING_RECEIPT_REQUIRED")
    labels = [op["label"] for op in operations]
    # Do not silently re-enable a job disabled by the user or another owner.
    old_disabled = disabled_state(labels, run=run)
    if any(old_disabled.values()):
        raise ValueError("OWNED_JOB_ALREADY_DISABLED_STOP_FOR_CONTROLLER")
    expected_key = "expected_sha256" if rollback else "proposed_sha256"
    for op in operations:
        if sha(Path(op["target"]).read_bytes()) != op[expected_key]:
            raise ValueError("INSTALLED_PLIST_DRIFT:" + op["label"])
    directory = journal_root / (("deactivate-rollback-" if rollback else "activate-") + uuid.uuid4().hex)
    directory.mkdir()
    journal = {"status":"DRAINING", "rollback":rollback, "disabled_before":old_disabled,
               "operations":[], "main_scheduler_actions":0, "api_actions":0, "signals_sent":0}
    def record():
        (directory / "receipt.json").write_text(json.dumps(journal, ensure_ascii=False, indent=2) + "\n")
    disabled = []
    record()
    try:
        if not rollback:
            # The first mutating launchctl operation is below this fresh
            # observation, not merely behind caller-supplied declarations.
            journal["api_gate_before_disable"] = api_validator(api_receipt, plan, run=run)
            record()
        # All three are gated before waiting, so none can start between the
        # natural-exit read and bootout. Existing processes keep running.
        for op in operations:
            command(["disable", f"gui/{os.getuid()}/{op['label']}"], run=run)
            disabled.append(op["label"])
        journal["waits"] = [wait_natural_exit(op["label"], wait_seconds, run=run) for op in operations]
        journal["status"] = "DRAINED"
        record()
        if not rollback:
            # A healthy one-shot may take time to drain. Recheck API identity
            # before the graph can actually enter its new 300-second cadence.
            journal["api_gate_after_drain"] = api_validator(api_receipt, plan, run=run)
            record()
        # During rollback restore the 60-second producer before any separate
        # controller rollback of the API's 360-second display contract.
        operations.sort(key=lambda op: (op["role"] != "graph", op["role"]))
        for op in operations:
            journal["current_operation"] = {"label":op["label"], "phase":"BEFORE_BOOTOUT"}
            record()
            if sha(Path(op["target"]).read_bytes()) != op[expected_key]:
                raise ValueError("PLIST_CHANGED_AFTER_DRAIN:" + op["label"])
            state = loaded_state(op, run=run)
            if state.get("pid"):
                raise RuntimeError("JOB_RESTARTED_WHILE_DISABLED:" + op["label"])
            if state["loaded"]:
                command(["bootout", f"gui/{os.getuid()}/{op['label']}"], run=run)
                # Bounded disappearance check; no --wait that can block forever.
                stop = time.monotonic() + 10
                while loaded_state(op, run=run)["loaded"]:
                    if time.monotonic() >= stop:
                        raise RuntimeError("BOOTOUT_STILL_PENDING:" + op["label"])
                    time.sleep(0.25)
            command(["enable", f"gui/{os.getuid()}/{op['label']}"], run=run)
            disabled.remove(op["label"])
            journal["current_operation"]["phase"] = "BEFORE_BOOTSTRAP"
            record()
            command(["bootstrap", f"gui/{os.getuid()}", op["target"]], run=run)
            observed = loaded_state(op, run=run)
            # Persist only selected scheduling fields, never a process env dump.
            text = observed.pop("text", "")
            if not observed["loaded"]:
                raise RuntimeError("BOOTSTRAP_NOT_LOADED:" + op["label"])
            if op["role"] == "graph":
                expected = 60 if rollback else 300
                if observed["interval_seconds"] != expected:
                    raise RuntimeError("LOADED_GRAPH_INTERVAL_MISMATCH")
            if op["role"] == "daily" and not rollback and observed["interval_seconds"] is not None:
                raise RuntimeError("DAILY_INTERVAL_STILL_PRESENT")
            proposed = Path(op["baseline"] if rollback else op["proposed"])
            import plistlib
            p = plistlib.loads(proposed.read_bytes())
            wanted = p["WorkingDirectory"] if op["role"] != "daily" else p["ProgramArguments"][2]
            if wanted not in text:
                raise RuntimeError("LOADED_RELEASE_BINDING_MISMATCH:" + op["label"])
            journal["operations"].append({"label":op["label"], "installed_sha256":op[expected_key],
                                           "loaded":observed, "binding_observed":wanted})
            journal["current_operation"] = None
            record()
        journal["status"] = "LOADED_ONE_SHOT_BINDINGS_VERIFIED_NATURAL_SLOT_UNVERIFIED"
        record()
        return journal
    except BaseException as error:
        journal.update(status="STOP_PRESERVE_HEALTHY_PROCESSES", error=str(error))
        record()
        raise
    finally:
        # Timeout/failure never leaves a previously enabled job disabled.
        # It also never bootouts a newly-started healthy task to undo a partial
        # activation. The journal gives the controller exact partial ownership.
        failures = []
        for label in disabled:
            try:
                command(["enable", f"gui/{os.getuid()}/{label}"], run=run)
            except Exception as error:
                failures.append({"label":label,"error":str(error)})
        journal["disabled_restore_failures"] = failures
        record()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("activate", "rollback"))
    parser.add_argument("--review-receipt", required=True, type=Path)
    parser.add_argument("--api-ready-receipt", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--wait-seconds", type=float, default=45)
    args = parser.parse_args()
    if not args.execute or not 0 <= args.wait_seconds <= 60:
        raise ValueError("EXPLICIT_EXECUTE_AND_BOUNDED_WAIT_REQUIRED")
    plan = reviewed_inputs(json.loads(args.review_receipt.read_text()))
    api = None
    if args.action == "activate":
        if args.api_ready_receipt is None:
            raise ValueError("API_360_SECOND_BOUND_READER_ACCEPTANCE_REQUIRED_FIRST")
        api = json.loads(args.api_ready_receipt.read_text())
    with owned_lock():
        result = activate(plan, rollback=args.action == "rollback", wait_seconds=args.wait_seconds, api_receipt=api)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
