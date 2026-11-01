"""Bounded Main -> Stage -> API publication using the existing guarded workflow.

Batch1's reviewed two-role files are unchanged. No CLI mutation is authorized
by preparation; activate/rollback need a separate explicit operator flag.
"""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import copy
import json
import os
from pathlib import Path
import plistlib
import stat
import tempfile
import time

from ops import activate_runtime_two_roles as two
from ops.prepare_runtime_governance_publication import omitted_owner_proof

fixed = two.fixed


def assert_main_idle(pid):
    fixed.require(type(pid) is int and pid > 0, "MAIN_PID_REQUIRED")
    rows = fixed.subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,command="], text=True)
    pairs = [(int(parts[0]), int(parts[1])) for line in rows.splitlines() if len(parts := line.strip().split(None, 2)) == 3]
    descendants = {pid}
    while True:
        more = {child for child, parent in pairs if parent in descendants}
        if more <= descendants: break
        descendants |= more
    fixed.require(descendants == {pid}, "MAIN_HEALTHY_CHILDREN_ACTIVE:" + str(sorted(descendants - {pid})))


def configure(plan_path, evidence):
    plan = json.loads(Path(plan_path).read_bytes())
    fixed.require(set(plan["roles"]) == {"main", "stage", "api"} and plan["forward_order"] == ["main", "stage", "api"]
                  and plan["rollback_order"] == ["api", "stage", "main"], "EXACT_MAIN_STAGE_API_ROLES_REQUIRED")
    # Reuse the already reviewed two-role parameter validator without editing
    # it or allowing Main through its public CLI. This projection is validation
    # input only and is deleted immediately; the full plan is pinned below.
    projected = copy.deepcopy(plan)
    projected["roles"] = {role: plan["roles"][role] for role in ("stage", "api")}
    projected["forward_order"] = ["stage", "api"]; projected["rollback_order"] = ["api", "stage"]
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json") as temporary:
        json.dump(projected, temporary); temporary.flush(); two.configure(Path(temporary.name), Path(evidence))
    row = plan["roles"]["main"]; old = Path(row["preimage"]["V4_APP_ROOT"]).parent
    new = Path(row["candidate"]["app_root"]).parent
    fixed.require(row["label"] == "com.lexi.v4.scheduler" and new.is_relative_to(fixed.LOCAL / "candidates") and new != old, "WRONG_MAIN_TARGET")
    before_raw = Path(row["original_plist"]).read_bytes(); after_raw = Path(row["proposed_plist"]).read_bytes()
    fixed.require(fixed.sha(before_raw) == row["original_plist_sha256"] and fixed.sha(after_raw) == row["proposed_plist_sha256"], "MAIN_PROPOSAL_SHA_CHANGED")
    before, after = plistlib.loads(before_raw), plistlib.loads(after_raw)
    fixed.require(before["Label"] == after["Label"] == row["label"], "MAIN_LABEL_CHANGED")
    fixed.require(all(before["EnvironmentVariables"].get(k) == v for k, v in row["preimage"].items()), "MAIN_PREIMAGE_IDENTITY_CHANGED")
    expected = copy.deepcopy(before); expected["WorkingDirectory"] = str(new / "app")
    expected["ProgramArguments"] = [arg.replace(str(old / "app"), str(new / "app")) for arg in before["ProgramArguments"]]
    expected_env = expected["EnvironmentVariables"]
    expected_env.update(dict(zip(fixed.IDENTITY, (str(new / "app"), new.name, str(new / "release-manifest.json"), row["candidate"]["manifest_sha256"]))))
    expected_env["PYTHONPATH"] = expected_env["PYTHONPATH"].replace(str(old / "app"), str(new / "app"))
    fixed.require(expected == after, "UNOWNED_MAIN_PLIST_OR_ENVIRONMENT_DELTA")
    fixed.require(plan["main_binding"] == {"app_root": str(new / "app"), "release_id": new.name, "manifest_sha256": row["candidate"]["manifest_sha256"]}, "STAGE_MAIN_PUBLICATION_BINDING_MISMATCH")
    fixed.TARGETS = {"main": (row["label"], old, row["preimage"]["V4_RELEASE_MANIFEST_SHA256"], new, row["candidate"]["manifest_sha256"]), **fixed.TARGETS}
    two_staged, two_guards, two_unload, two_start = fixed.staged, fixed.guards, fixed.unload, fixed.start

    def staged(role, raw):
        if role != "main": return two_staged(role, raw)
        fixed.require(raw == before_raw, "MAIN_ORIGINAL_PREIMAGE_CHANGED"); return after_raw

    def guards():
        from infrastructure.scheduling.execution_ledger import ExecutionLedger
        stack = ExitStack()
        try:
            stack.enter_context(two_guards())
            ledger = ExecutionLedger(Path(before["EnvironmentVariables"]["V4_DISPATCH_LEDGER_ROOT"]))
            for lane in ("DEFAULT", "A_LONG"):
                fd = ledger.try_acquire_scheduler_lane(lane)
                fixed.require(fd is not None, "MAIN_SCHEDULER_LANE_BUSY:" + lane)
                stack.callback(os.close, fd)
            return stack
        except BaseException: stack.close(); raise

    def unload(role, raw, owned):
        if role != "main": return two_unload(role, raw, owned)
        label = fixed.TARGETS[role][0]; current = fixed.loaded(label, raw, missing=True)
        if current:
            fixed.require(owned is not None and (current["pid"] == owned.get("pid") or owned.get("bootstrapped_by_us") is True), "MAIN_EXTERNAL_PID_CHANGED")
            assert_main_idle(current["pid"])
            result = fixed.lc("bootout", fixed.DOMAIN + "/" + label)
            fixed.require(result.returncode == 0, "MAIN_BOOTOUT_FAILED:" + result.stderr)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            current = fixed.loaded(label, raw, missing=True)
            if current is None and (not (owned or {}).get("pid") or not fixed.pid_alive(owned["pid"])): return
            time.sleep(.2)
        raise RuntimeError("MAIN_UNLOAD_JOB_PID_TIMEOUT")

    def start(role, raw, ownership):
        if role != "main": return two_start(role, raw, ownership)
        label = fixed.TARGETS[role][0]
        result = fixed.lc("bootstrap", fixed.DOMAIN, str(fixed.LA / (label + ".plist")))
        fixed.require(result.returncode == 0, "MAIN_BOOTSTRAP_FAILED:" + result.stderr)
        ownership[role] = {"pid": None, "bootstrapped_by_us": True}
        deadline = time.monotonic() + 35; last = None
        while time.monotonic() < deadline:
            try:
                job = fixed.loaded(label, raw); ownership[role] = job
                fixed.require(job["state"] == "running" and type(job["pid"]) is int, "MAIN_DAEMON_NOT_RUNNING")
                assert_main_idle(job["pid"])
                return job
            except (OSError, ValueError, KeyError) as error: last = repr(error); time.sleep(.3)
        raise RuntimeError("MAIN_START_READINESS_TIMEOUT:" + str(last))

    fixed.staged, fixed.guards, fixed.unload, fixed.start = staged, guards, unload, start
    return plan


def zero_admission(plan):
    proof = plan["omitted_main_owner_zero_proof"]
    fresh = omitted_owner_proof(proof["ledger_root"], proof["release_id"], proof["app_root"], first_date=proof["first_date"])
    fixed.require(not fresh["matching_receipts"], "OMITTED_MAIN_RECEIPTS_APPEARED_COMPATIBILITY_REQUIRED")
    return fresh


def rollback_zero_admission(plan):
    # Restoring the original Stage removes the new Main identity. A delayed
    # rollback is therefore inadmissible once that Main has any receipt.
    proof = plan["omitted_main_owner_zero_proof"]
    candidate = plan["roles"]["main"]["candidate"]
    fresh = omitted_owner_proof(proof["ledger_root"], candidate["release_id"], candidate["app_root"], first_date="00000000")
    fixed.require(not fresh["matching_receipts"], "ROLLBACK_NEW_MAIN_RECEIPTS_EXIST_COMPATIBILITY_REQUIRED")
    return fresh


def admit(role, job):
    if role == "main":
        fixed.require(job["state"] == "running", "MAIN_DAEMON_NOT_RUNNING"); assert_main_idle(job["pid"])
    elif role == "stage": fixed.require(job["pid"] is None and job["state"] == "not running", "STAGE_CALENDAR_BUSY")


def prepare(plan_path, plan):
    fixed.require(fixed.sys.executable == str(fixed.PYTHON), "PINNED_PYTHON_REQUIRED")
    fixed.require(not fixed.EVIDENCE.exists(), "PREPARATION_ALREADY_EXISTS")
    records = {}; releases = []
    with fixed.guards():
        for role, (label, old, oldsha, new, newsha) in fixed.TARGETS.items():
            path = fixed.LA / (label + ".plist"); raw = path.read_bytes(); payload = plistlib.loads(raw)
            fixed.require(tuple(payload["EnvironmentVariables"][k] for k in fixed.IDENTITY) == (str(old / "app"), old.name, str(old / "release-manifest.json"), oldsha), "ACTUAL_PREIMAGE_CHANGED:" + role)
            job = fixed.loaded(label, raw); admit(role, job); desired = fixed.staged(role, raw)
            records[role] = {"label": label, "path": str(path), "mode": stat.S_IMODE(path.stat().st_mode), "original_sha256": fixed.sha(raw), "staged_sha256": fixed.sha(desired), "loaded": job}
            for root, digest in ((old, oldsha), (new, newsha)): releases.append(fixed.verify_release(root, digest, fixed.tools()))
        fixed.assert_idle(records["api"]["loaded"]["pid"]); zero = zero_admission(plan)
        protection = fixed.external_protection(); data = fixed.data_protection()
        fixed.EVIDENCE.mkdir(mode=0o700)
        for role, row in records.items():
            raw = Path(row["path"]).read_bytes(); fixed.require(fixed.sha(raw) == row["original_sha256"], "PREPARATION_CAS_DRIFT")
            for suffix, content in (("original", raw), ("staged", fixed.staged(role, raw))):
                target = fixed.EVIDENCE / (role + "." + suffix + ".plist"); target.write_bytes(content); target.chmod(row["mode"])
        record = {"status": "PREPARED_NOT_ACTIVATED", "records": records, "releases": releases, "protection": protection, "data_protection": data, "zero_owner_proof": zero,
            "plan_path": str(Path(plan_path).resolve()), "plan_sha256": fixed.sha(Path(plan_path).read_bytes()),
            "script_pins": {str(path): fixed.sha(path.read_bytes()) for path in (Path(__file__), Path(two.__file__), Path(fixed.__file__), Path(omitted_owner_proof.__code__.co_filename))},
            "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False, "NATURAL_VERIFIED": "NOT_RUN"}
        fixed.write_json(fixed.EVIDENCE / "preparation.json", record)
    return record


def switch(preparation_sha, plan, *, rollback=False):
    path = fixed.EVIDENCE / "preparation.json"; fixed.pinned(path, preparation_sha); prepared = json.loads(path.read_bytes())
    for filename, digest in prepared["script_pins"].items(): fixed.pinned(Path(filename), digest)
    fixed.pinned(Path(prepared["plan_path"]), prepared["plan_sha256"])
    records = prepared["records"]; raws = {}; ownership = {}; touched = []
    for role, row in records.items():
        old = (fixed.EVIDENCE / (role + ".original.plist")).read_bytes(); new = (fixed.EVIDENCE / (role + ".staged.plist")).read_bytes()
        fixed.require(fixed.sha(old) == row["original_sha256"] and fixed.sha(new) == row["staged_sha256"], "BACKUP_DRIFT"); raws[role] = (old, new)
    def event(name, **fields): fixed.write_json(fixed.EVIDENCE / (f"event-{time.time_ns()}.json"), {"event": name, **fields})
    with fixed.guards():
        for role, row in records.items():
            current = raws[role][1 if rollback else 0]; fixed.cas(row, current); job = fixed.loaded(row["label"], current); admit(role, job)
            if not rollback: fixed.require(job == row["loaded"], "LOADED_ROLE_CHANGED:" + role)
            ownership[role] = job
        fixed.assert_idle(ownership["api"]["pid"])
        if rollback: rollback_zero_admission(plan)
        else: zero_admission(plan)
        protection = fixed.external_protection(); data = fixed.data_protection()
        fixed.require(protection == prepared["protection"], "PROTECTED_BASELINE_CHANGED")
        if not rollback: fixed.require(data == prepared["data_protection"], "STAGE_DATA_CHANGED_SINCE_PREPARE")
        for _, old, oldsha, new, newsha in fixed.TARGETS.values():
            for root, digest in ((old, oldsha), (new, newsha)): fixed.verify_release(root, digest, fixed.tools())
        try:
            for role in (reversed(tuple(fixed.TARGETS)) if rollback else tuple(fixed.TARGETS)):
                old, new = raws[role]; previous, desired = (new, old) if rollback else (old, new)
                touched.append(role); fixed.unload(role, previous, ownership[role]); fixed.replace(records[role], previous, desired); result = fixed.start(role, desired, ownership)
                event("TARGET_VERIFIED", role=role, result=result)
            if not rollback: fixed.verify_forward()
            fixed.require(fixed.external_protection() == protection and fixed.data_protection() == data, "PROTECTION_POSTCHECK_CHANGED")
            event("ROLLBACK_VERIFIED" if rollback else "ACTIVATED_OPERATIONAL_VERIFIED", NATURAL_VERIFIED="NOT_RUN")
        except BaseException as primary:
            restored, failures = fixed.restore_touched(touched, records, raws, ownership, event, rollback=rollback)
            event("RECOVERY_FAILED" if failures else "AUTOMATIC_ROLLBACK_VERIFIED", restored=restored, failures=failures, error=repr(primary))
            if failures: raise RuntimeError("RECOVERY_FAILURES:" + json.dumps(failures)) from primary
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("action", choices=("prepare", "activate", "rollback"))
    parser.add_argument("--plan", required=True, type=Path); parser.add_argument("--evidence", required=True, type=Path)
    parser.add_argument("--preparation-sha"); parser.add_argument("--authorize-live-role-switch", action="store_true")
    args = parser.parse_args(); plan = configure(args.plan, args.evidence)
    if args.action == "prepare":
        prepare(args.plan, plan); print(json.dumps({"status": "PREPARED_NOT_ACTIVATED", "sha256": fixed.sha((args.evidence / "preparation.json").read_bytes())}))
    else:
        fixed.require(args.authorize_live_role_switch and bool(args.preparation_sha), "FUTURE_EXPLICIT_ACTIVATION_AUTHORIZATION_AND_SHA_REQUIRED")
        switch(args.preparation_sha, plan, rollback=args.action == "rollback")
