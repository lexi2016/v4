"""Contract tests. Every write/call other than explicit archived reads is synthetic."""
from __future__ import annotations

from contextlib import contextmanager
import copy
from hashlib import sha256
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

from .authority import AuthorityClient, initialize_authority
from .official_inputs import verify_run_a, verify_canonical_readonly
from .test_v8_fixtures import (
    CAPS, child_process, create_fixture, reserve_data, signed_bundle, start_server, wait_server, write_json,
)
from .validation import Rejected, RUN_A, SYNTHETIC, verify_prepared

CASE_DIR = os.environ.get("P515_V8_TEST_EVIDENCE")
ARCHIVE_CONFIG = os.environ.get("P515_V8_OFFICIAL_CONFIG")
CLI = [sys.executable, "-m", "research.p515_recovery_v8.cli"]


class Harness:
    def __init__(self, root, fault, baseline=None):
        self.root = root
        self.prepared_path, self.prepared, self.private, self.trust = create_fixture(root / "fixture")
        if baseline is not None:
            self.prepared["baseline"] = baseline
            write_json(self.prepared_path, self.prepared)
        self.anchor = initialize_authority(root / "authority", self.prepared_path, self.trust,
                                           domain=SYNTHETIC, test_fault=fault)
        self.proc_log = root / "authority-process.log"
        self.stream = self.proc_log.open("a")
        self.proc = None
        self.responses = []
        self.start()

    def start(self):
        self.proc = start_server(self.anchor, self.stream)
        self.client, result = wait_server(self.anchor, self.proc)
        self.authority_id = result["authority_id"]
        self.responses.append({"start": self.proc.pid, "check": result})
        return result

    def stop(self):
        if self.proc is not None and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=6)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=6)

    def rpc(self, op, **kwargs):
        try:
            result = self.client.request(op, **kwargs)
        except Exception as exc:
            self.responses.append({"op": op, "error": str(exc), "type": type(exc).__name__})
            raise
        record = {k: v for k, v in result.items() if k != "lease_token"}
        self.responses.append({"op": op, "response": record})
        return result

    def bundle(self, **kwargs):
        return signed_bundle(self.prepared_path, self.prepared, self.private, self.authority_id, **kwargs)

    def reserve(self, *, unit="F1_RETRY", mode="SYNTHETIC_EXECUTION", **kwargs):
        return self.rpc("reserve", **reserve_data(*self.bundle(unit=unit, **kwargs), unit=unit, mode=mode))

    def execute(self, receipt):
        return self.rpc("execute", transaction_id=receipt["transaction_id"], lease_token=receipt["lease_token"])

    def query(self, receipt):
        return self.rpc("query", transaction_id=receipt["transaction_id"])

    def cli(self, mode, signed=None, zipbytes=None):
        args = [*CLI, "--anchor", str(self.anchor), "--mode", mode]
        if signed is not None:
            auth_path = self.root / "TEST_AUTH_ONLY.json"
            write_json(auth_path, signed)
            args.extend(["--auth", str(auth_path)])
        if zipbytes is not None:
            prep = self.root / "PRELAUNCH_TEST_ONLY.zip"
            prep.write_bytes(zipbytes)
            args.extend(["--prelaunch", str(prep)])
        proc = subprocess.run(args, capture_output=True, text=True, timeout=25)
        self.responses.append({"argv": args, "exit_code": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr})
        return proc

    def snapshot(self):
        return self.rpc("status")

    def preserve(self, case):
        if self.proc.poll() is None:
            try:
                self.snapshot()
            except (OSError, Rejected):
                pass
        self.stop()
        self.stream.close()
        if CASE_DIR:
            out = Path(CASE_DIR)
            out.mkdir(parents=True, exist_ok=True)
            destination = out / (case + ".json")
            authority_logs = {p.name:p.read_text() for p in self.anchor.parent.glob("*.jsonl")
                              if p.name == "requests.jsonl" or "audit" in p.name.lower() or "rpc" in p.name.lower()}
            destination.write_text(json.dumps({"scope": SYNTHETIC, "authority_id": self.authority_id,
                "responses": self.responses, "authority_process_log": self.proc_log.read_text(),
                "server_pid": self.proc.pid, "server_exit": self.proc.returncode, "authority_rpc_logs": authority_logs}, indent=2, default=str) + "\n")


@pytest.fixture
def lab(request):
    marker = getattr(request, "param", None)
    with tempfile.TemporaryDirectory(prefix="v8t-", dir="/tmp") as folder:
        harness = Harness(Path(folder).resolve(), marker)
        try:
            yield harness
        finally:
            harness.preserve(request.node.name)


def state(receipt):
    return receipt.get("state") or receipt.get("status")


def no_new_calls(lab):
    snapshot = lab.snapshot()
    assert not snapshot.get("starts", [])
    assert not [evt for evt in snapshot.get("events", []) if evt.get("event") in {"UNIT_START", "SYNTHETIC_STAGE_START"}]
    assert all(n == 0 for n in snapshot.get("stub_calls", {}).values() if isinstance(n, int))


def archive_inputs():
    if not ARCHIVE_CONFIG:
        pytest.skip("Pinned archived research originals unavailable in this test environment")
    return json.loads(Path(ARCHIVE_CONFIG).read_bytes())


def log_archive(case, report):
    if CASE_DIR:
        (Path(CASE_DIR) / f"{case}.json").write_text(json.dumps(report, indent=2) + "\n")


def test_01_cli_end_to_end(lab):
    before = lab.cli("CHECK_ONLY")
    assert before.returncode == 0, before.stderr
    proc = lab.cli("SYNTHETIC_EXECUTION", *lab.bundle())
    assert proc.returncode == 0, proc.stderr
    assert "COMMITTED" in proc.stdout
    assert lab.snapshot()["authority_id"] == lab.authority_id


def test_02_no_official_authorization(lab):
    proc = lab.cli("AUTHORIZED_EXECUTION")
    assert proc.returncode != 0 and proc.stderr
    no_new_calls(lab)


def test_03_synthetic_authorization_cannot_unlock_official(lab):
    proc = lab.cli("AUTHORIZED_EXECUTION", *lab.bundle())
    assert proc.returncode != 0 and proc.stderr
    no_new_calls(lab)


def test_04_invalid_signature(lab):
    a, z = lab.bundle()
    a["signature"] = "00" * 64
    with pytest.raises(Rejected, match="INVALID_AUTH_SIGNATURE"):
        lab.rpc("reserve", **reserve_data(a, z))
    no_new_calls(lab)


def test_05_empty_authorization_id(lab):
    with pytest.raises(Rejected, match="EMPTY_AUTHORIZATION_ID"):
        lab.reserve(authid="")
    no_new_calls(lab)


def test_06_wrong_subject(lab):
    with pytest.raises(Rejected, match="UNAUTHORIZED_SUBJECT"):
        lab.reserve(override={"subject": "WRONG_SUBJECT"})
    no_new_calls(lab)


def contest(lab, cloned):
    packet = lab.root / "request.json"
    write_json(packet, reserve_data(*lab.bundle()))
    paths = [lab.root, lab.root]
    if cloned:
        paths = [lab.root / "worker-A", lab.root / "worker-B"]
        for path in paths:
            path.mkdir()
        if ARCHIVE_CONFIG:
            archive = archive_inputs()["archive"]
            from zipfile import ZipFile
            for path in paths:
                with ZipFile(archive) as z:
                    for entry in z.namelist():
                        if entry.startswith("canonical_budget/"):
                            target = path / Path(entry)
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(z.read(entry))
            lpath = paths[0] / "canonical_budget/CANONICAL_TASK_LEDGER.jsonl"
            rpath = paths[1] / "canonical_budget/CANONICAL_TASK_LEDGER.jsonl"
            assert lpath.stat().st_ino != rpath.stat().st_ino
            assert lpath.read_bytes() == rpath.read_bytes()
            lab.responses.append({"cloned_run_a_physical_inodes": [lpath.stat().st_ino, rpath.stat().st_ino],
                                  "ledger_sha": sha256(lpath.read_bytes()).hexdigest()})
        else:
            for path in paths:
                (path / "SYNTHETIC_OFFLINE_LEDGER.json").write_bytes(lab.prepared_path.read_bytes())
    gate = lab.root / "contest.release"
    workers = [child_process(lab.anchor, packet, p, gate=gate) for p in paths]
    from time import monotonic, sleep
    due = monotonic() + 8
    while not all((lab.root / f"ready-{worker.pid}").exists() for worker in workers) and monotonic() < due:
        sleep(0.01)
    assert all((lab.root / f"ready-{worker.pid}").exists() for worker in workers)
    gate.write_text("SYNTHETIC_TEST_ONLY")
    results = []
    for worker in workers:
        stdout, stderr = worker.communicate(timeout=25)
        lab.responses.append({"worker": worker.pid, "stdout": stdout, "stderr": stderr, "rc": worker.returncode})
        assert worker.returncode == 0, stderr
        results.append(json.loads(stdout))
    winners = [r for r in results if state(r.get("execute", {})) == "COMMITTED"]
    assert len(winners) == 1 and len({r["pid"] for r in results}) == 2, results
    losers = [r for r in results if r not in winners]
    assert all("error" in r for r in losers), results
    for r in results:
        assert "REMOTE_MUTATION_FORBIDDEN" in str(r["start"])
        assert "REMOTE_MUTATION_FORBIDDEN" in str(r["commit"])
    snap = lab.snapshot()
    assert snap["authority_id"] == lab.authority_id


def test_07_cloned_physical_ledgers(lab):
    contest(lab, True)


def test_08_stale_snapshot_not_authority(lab):
    source = lab.anchor.parent
    clone = lab.root / "physical-authority-copy"
    shutil.copytree(source, clone, ignore=lambda _d, paths: {p for p in paths if p.endswith(".sock")})
    anchor = clone / lab.anchor.name
    with (lab.root / "copy-attempt.log").open("w+") as stream:
        p = start_server(anchor, stream)
        try:
            status = p.wait(timeout=6)
        finally:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=6)
        stream.seek(0)
        lab.responses.append({"copied_server_rc": status, "copied_server_log": stream.read()})
    assert status != 0
    no_new_calls(lab)


def test_09_authority_disconnect_cannot_fallback(lab):
    a, p = lab.bundle()
    lab.stop()
    with pytest.raises((Rejected, OSError)):
        lab.rpc("reserve", **reserve_data(a, p))
    lab.start()
    no_new_calls(lab)


def test_10_duplicate_reservation_cannot_consume_again(lab):
    a, p = lab.bundle()
    packet = reserve_data(a, p)
    first = lab.rpc("reserve", **packet)
    with pytest.raises(Rejected):
        lab.rpc("reserve", **packet)
    assert state(lab.query(first)) == "RESERVED"
    no_new_calls(lab)


def test_11_two_real_processes(lab):
    contest(lab, False)


def test_12_two_independent_containers():
    if not os.environ.get("P515_V8_RUN_CONTAINER_EVIDENCE"):
        pytest.skip("BLOCKED: no two-container container/volume witness available in this Mac environment")
    loaded = json.loads(Path(os.environ["P515_V8_RUN_CONTAINER_EVIDENCE"]).read_bytes())
    assert loaded["shared_volume"] and len(set(loaded["container_ids"])) == 2
    assert loaded["consumer_count"] == 1 and loaded["raw_traces"]


def test_13_historical_archive_14_events_7_tokens():
    c = archive_inputs()
    a = verify_run_a(Path(c["archive"]), Path(c["original_prelaunch"]))
    assert a["events"] == 14 and a["start_tokens"] == 7
    assert a["execution_identity_sha256"] == RUN_A
    assert a["counts"] == {"preprocessing_fit": 3, "model_fit": 2, "model_api": 2, "failed_attempts": 1}
    assert verify_canonical_readonly(c["legacy_canonical"], a)["matched_count"] == 12
    log_archive("test_13_historical_archive_14_events_7_tokens", a)


def test_14_original_f1_failure_retained():
    c = archive_inputs()
    a = verify_run_a(Path(c["archive"]), Path(c["original_prelaunch"]))
    assert a["historical_units"]["F1"]["state"] == "FAILED_ERROR"
    assert a["historical_files"]["tokens/F1_PREPROC_FIT_START.json"]["sha256"] == "7135ce2016dd285de48dc48fda675e2da7d675044f10277064ad3c89b7c70c0c"
    log_archive("test_14_original_f1_failure_retained", {"F1": a["historical_units"]["F1"],
                "start": a["historical_files"]["tokens/F1_PREPROC_FIT_START.json"]})


@pytest.mark.parametrize(("metric", "cap"), [("preprocessing_fit", 3), ("model_fit", 2), ("model_api", 2)],
                         ids=["15-preprocessing", "16-model", "17-api"])
def test_15_17_budget_before_any_call(lab, metric, cap):
    with pytest.raises(Rejected, match="BUDGET"):
        lab.reserve(caps={**CAPS, metric: cap})
    no_new_calls(lab)


@pytest.mark.parametrize("fault", ["SOURCE", "MISSING_SOURCE", "FOLDS", "IDENTITY"])
def test_18_prelaunch_actual_member_tampering(lab, fault):
    with pytest.raises(Rejected, match="PRELAUNCH"):
        lab.reserve(corrupt=fault)
    no_new_calls(lab)


def test_18b_matrix_actual_bytes(lab):
    data = copy.deepcopy(lab.prepared)
    data["units"]["F1_RETRY"]["holdout_rows"][1]["feature_vector_10"][1] += 1
    write_json(lab.prepared_path, data)
    with pytest.raises(Rejected, match="ROW_80B_SHA_MISMATCH"):
        verify_prepared(lab.prepared_path, SYNTHETIC)
    lab.prepared_path.write_bytes(json.dumps(lab.prepared, sort_keys=True, separators=(",", ":")).encode())
    no_new_calls(lab)


def fault_state(lab, allowed):
    receipt = lab.reserve()
    try:
        result = lab.execute(receipt)
        assert state(result) not in {"COMMITTED", "COMPLETED_OK"}
    except (Rejected, OSError):
        pass
    terminal = lab.query(receipt)
    assert state(terminal) in allowed, terminal
    with pytest.raises(Rejected):
        lab.reserve()
    return terminal


@pytest.mark.parametrize("lab", ["second_row_identity"], indirect=True)
def test_19_second_row_identity(lab):
    fault_state(lab, {"CORRUPTED", "FAILED_ERROR"})


@pytest.mark.parametrize("lab", ["missing_output", "corrupt_output", "wrong_sha", "wrong_model_identity", "missing_model_weights"], indirect=True)
def test_20_output_integrity(lab):
    fault_state(lab, {"CORRUPTED", "FAILED_ERROR"})


@contextmanager
def restarted_after_crash(lab, receipt):
    with pytest.raises((Rejected, OSError)):
        lab.execute(receipt)
    lab.proc.wait(timeout=8)
    before = lab.proc.returncode
    lab.start()
    lab.responses.append({"crash_exit": before, "transaction_id": receipt["transaction_id"]})
    yield lab.query(receipt)


@pytest.mark.parametrize("lab", ["after_start_crash"], indirect=True)
def test_21_crash_after_start(lab):
    r = lab.reserve()
    with restarted_after_crash(lab, r) as after:
        assert state(after) == "INTERRUPTED_UNKNOWN"
    with pytest.raises(Rejected):
        lab.execute(r)


@pytest.mark.parametrize("lab", ["before_commit_crash"], indirect=True)
def test_22a_disconnect_before_commit(lab):
    r = lab.reserve()
    with restarted_after_crash(lab, r) as after:
        assert state(after) == "INTERRUPTED_UNKNOWN"
    with pytest.raises(Rejected):
        lab.reserve(unit="FINAL_DEV", authid="FINAL-01")


@pytest.mark.parametrize("lab", ["after_commit_disconnect"], indirect=True)
def test_22b_disconnect_after_commit(lab):
    r = lab.reserve()
    with pytest.raises((Rejected, OSError)):
        lab.execute(r)
    assert state(lab.query(r)) == "COMMITTED"


def test_23_repeated_execution_does_not_fit_again(lab):
    r = lab.reserve()
    assert state(lab.execute(r)) == "COMMITTED"
    before = lab.snapshot()
    try:
        result = lab.execute(r)
        assert state(result) == "COMMITTED"
    except Rejected:
        pass
    after = lab.snapshot()
    assert before["stub_calls"] == after["stub_calls"] and state(lab.query(r)) == "COMMITTED"


def test_24_archived_f2_f3_readonly():
    c = archive_inputs()
    a = verify_run_a(Path(c["archive"]), Path(c["original_prelaunch"]))
    units = a["historical_units"]
    assert [units[n]["rows"] for n in ("F2", "F3")] == [9503, 5250]
    assert all(units[n]["state"] == "COMMITTED" and units[n]["identity"] == RUN_A for n in ("F2", "F3"))
    log_archive("test_24_archived_f2_f3_readonly", {"F2": units["F2"], "F3": units["F3"], "additional_api": 0})


def test_25_final_dev_prerequisites_and_no_prediction(lab):
    with pytest.raises(Rejected):
        lab.reserve(unit="FINAL_DEV", authid="FINAL-01")
    assert state(lab.execute(lab.reserve())) == "COMMITTED"
    with pytest.raises(Rejected):
        lab.reserve(unit="FINAL_DEV", authid="FINAL-02", caps={**CAPS, "preprocessing_fit": 4})
    before = lab.snapshot()["stub_calls"]
    final = lab.execute(lab.reserve(unit="FINAL_DEV", authid="FINAL-03"))
    assert state(final) == "COMMITTED"
    after = lab.snapshot()["stub_calls"]
    api = next(k for k in before if "predict" in k or k.endswith("model_api"))
    assert before[api] == after[api]


def test_26_bad_archive_sha_rejects():
    c = archive_inputs()
    with tempfile.TemporaryDirectory(dir="/tmp") as td:
        corrupt = Path(td) / "wrong.zip"
        corrupt.write_bytes(Path(c["archive"]).read_bytes() + b"tampered")
        with pytest.raises(ValueError, match="wrong SHA256"):
            verify_run_a(corrupt, Path(c["original_prelaunch"]))
    log_archive("test_26_bad_archive_sha_rejects", {"copied_archive_modified": True, "original_readonly": True, "status": "PASS"})


def test_27_expired_prelaunch_after_reserve_blocks_start(lab):
    from datetime import datetime, timedelta, timezone
    from time import sleep
    deadline = datetime.now(timezone.utc) + timedelta(seconds=1.3)
    r = lab.reserve(deadline=deadline)
    sleep(max(0.0, (deadline - datetime.now(timezone.utc)).total_seconds()) + 0.10)
    with pytest.raises(Rejected, match="EXPIRED"):
        lab.execute(r)
    assert state(lab.query(r)) == "BLOCKED"
    no_new_calls(lab)


def test_28_expired_grant_rejected_before_reserve(lab):
    with pytest.raises(Rejected, match="AUTH_EXPIRED_OR_NOT_EFFECTIVE"):
        lab.reserve(override={"expires_at": "2000-01-01T00:00:00Z"})
    no_new_calls(lab)


def test_29_in_place_rollback_does_not_restore_budget(lab):
    import sqlite3
    from contextlib import closing
    db = lab.anchor.parent / "ledger.sqlite"
    with closing(sqlite3.connect(db)) as read:
        read.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    stale = db.read_bytes()
    inode = db.stat().st_ino
    r = lab.reserve()
    assert state(lab.execute(r)) == "COMMITTED"
    lab.snapshot()
    lab.stop()
    with closing(sqlite3.connect(db)) as read:
        read.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
    fresh = db.read_bytes()
    assert stale != fresh
    # Emulate an operator restoring just the old SQLite bytes while leaving the distinct durable fence unchanged.
    db.write_bytes(stale)
    assert db.stat().st_ino == inode
    lab.responses.append({"sqlite_inode": inode, "stale": sha256(stale).hexdigest(),
                          "after_committed": sha256(fresh).hexdigest(), "restored": sha256(db.read_bytes()).hexdigest()})
    with pytest.raises((Rejected, OSError, RuntimeError, TimeoutError), match="authority exited|FENCE|WATERMARK|ROLLBACK"):
        lab.start()


def test_30_migrate_exact_archive_baseline_into_isolated_service():
    c = archive_inputs()
    base = verify_run_a(Path(c["archive"]), Path(c["original_prelaunch"]))
    before = verify_canonical_readonly(c["legacy_canonical"], base)
    with tempfile.TemporaryDirectory(prefix="v8m-", dir="/tmp") as folder:
        h = Harness(Path(folder).resolve(), None, base)
        try:
            measured = h.snapshot()
            assert measured["scope"] == SYNTHETIC
            assert measured["counts"] == {"preprocessing_fit": 3, "model_fit": 2, "model_api": 2}
            assert not measured["transactions"] and not measured["stub_calls"] and not measured["starts"]
            assert dict.fromkeys(measured["real_counts"], 0) == measured["real_counts"]
            assert verify_canonical_readonly(c["legacy_canonical"], base) == before
            h.responses.append({"archive_before_after": before, "original_binding": base["execution_identity_sha256"],
                                "events": base["events"], "tokens": base["start_tokens"], "failures": base["counts"]["failed_attempts"],
                                "historical": base["historical_units"]})
        finally:
            h.preserve("test_30_migrate_exact_archive_baseline_into_isolated_service")
