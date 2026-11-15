"""Offline attestation, terminal gate and exact two-role restore tests."""

from datetime import datetime
import json
import plistlib
from urllib.parse import parse_qs, urlsplit

import pytest

from ops import prepare_top200_archive_api_release as release


def write_json(path, value):
    path.write_bytes(release.json_bytes(value))
    return release.reference(path)


def test_main_policy_rebind_only_changes_api_references_and_two_main_fields(tmp_path, monkeypatch):
    folder = tmp_path.resolve()
    old_api, new_api = folder / "previous", folder / "candidate"
    old_refs = []
    for relative in sorted(release.FORMAL_API_READERS):
        for root, text in ((old_api, "old"), (new_api, "new")):
            target = root / "app" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        old_refs.append(release.reference(old_api / "app" / relative))
    live_api = folder / "api.plist"
    monkeypatch.setattr(release, "LIVE_API", live_api)
    old_sha, new_sha = "a" * 64, "b" * 64
    stage = {"path": str(folder / "stage"), "sha256": "c" * 64}
    main_root = str(folder / "existing-main")
    pins = {"expected_main_app_root": main_root, "pins": [{"kind": "fixture-retained"}],
            "source_bindings": [*old_refs, {"path": str(live_api), "sha256": old_sha}, stage]}
    api = {"label": "com.lexi.v4.api", "plist_path": str(live_api), "plist_sha256": old_sha, "source_refs": old_refs}
    reader_stage = {"label": "com.lexi.stage-center.scheduler", "source_refs": [stage]}
    controls = {}
    controls["pins"] = write_json(folder / "old-pins.json", pins)
    controls["reader_attestation"] = write_json(folder / "old-readers.json", {"consumers": [api, reader_stage]})
    policy = {"dry_run": True, "auto_gc_enabled": False, "keep_completed": 1,
              "managed_pin_inventory": controls["pins"],
              "single_generation_lifecycle": {"pair_root": "existing", "reader_inventory": controls["reader_attestation"]}}
    controls["policy"] = write_json(folder / "old-policy.json", policy)
    payload = {"Label": "com.lexi.v4.scheduler", "ProgramArguments": ["launch-scheduler"],
               "EnvironmentVariables": {"V4_APP_ROOT": main_root, "V4_RELEASE_ID": "existing-main",
                   "V4_RESEARCH_RETENTION_POLICY": controls["policy"]["path"],
                   "V4_RESEARCH_RETENTION_POLICY_SHA256": controls["policy"]["sha256"]}}
    launch = folder / "old-main.plist"
    launch.write_bytes(plistlib.dumps(payload))
    source = {"control": controls, "roles": {"main": {"proposed_plist": release.reference(launch)}}}
    preimage, candidate = release.bind_main_controls(new_api, old_api, old_sha, new_sha, source)
    assert preimage == launch.read_bytes()
    payload_after = plistlib.loads(candidate)
    settings = payload_after["EnvironmentVariables"]
    assert settings["V4_RESEARCH_RETENTION_POLICY"] == str(new_api / "policy.json")
    keys = ("V4_RESEARCH_RETENTION_POLICY", "V4_RESEARCH_RETENTION_POLICY_SHA256")
    assert {**payload_after, "EnvironmentVariables": {**settings, **{k: payload["EnvironmentVariables"][k] for k in keys}}} == payload
    new_pins = json.loads((new_api / "managed-pins.json").read_bytes())
    assert new_pins["source_bindings"] == [
        *[release.reference(new_api / "app" / relative) for relative in sorted(release.FORMAL_API_READERS)],
        {"path": str(live_api), "sha256": new_sha}, stage,
    ]
    updated = json.loads((new_api / "reader-attestation.json").read_bytes())
    assert updated["consumers"] == [{**api, "plist_sha256": new_sha, "source_refs": new_pins["source_bindings"][:3]}, reader_stage]
    assert new_pins["pins"] == pins["pins"]
    new_policy = json.loads((new_api / "policy.json").read_bytes())
    assert {**new_policy, "managed_pin_inventory": policy["managed_pin_inventory"],
            "single_generation_lifecycle": {**new_policy["single_generation_lifecycle"],
                "reader_inventory": controls["reader_attestation"]}} == policy


@pytest.fixture
def final_receipt(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 17, 1, tzinfo=release.TZ)

    monkeypatch.setattr(release, "datetime", Clock)
    root = tmp_path.resolve()

    def make(status="NATURAL_SESSION_EVIDENCE_VERIFIED", timestamp="2026-11-16T17:15:30+08:00",
             complete=True):
        headers = {"session_status": status, "observed_at": timestamp, "trade_date": release.DAY,
                   "RESEARCH_ONLY": True, "auto_gc_enabled": False, **release.SAFETY}
        refs = {name: write_json(root / name, headers) for name in release.READ_RECEIPTS}
        value = {"status": status, "trade_date": release.DAY, "observed_at": timestamp,
                 "observed_release_variant": "FORWARD", "session_evidence": {"complete": complete},
                 "write_receipts": refs, "release_storage_failures": []}
        ref = write_json(root / "NATURAL_RESULT.json", value)
        return ref["sha256"]

    return root, make


def test_terminal_requires_date_observation_window_and_verified_receipts(final_receipt):
    root, make = final_receipt
    assert release.terminal_result(make(), root)[0] == "forward"
    with pytest.raises(ValueError, match="NOT_TERMINAL"):
        release.terminal_result(make(status="OBSERVING"), root)
    with pytest.raises(ValueError, match="CLOCK_CONFLICT"):
        release.terminal_result(make(timestamp="2026-11-16T17:14:59+08:00"), root)
    checksum = make()
    (root / "STAGE_WRITE_RECEIPT.json").write_bytes(b"{}")
    with pytest.raises(ValueError, match="SHA_DRIFT"):
        release.terminal_result(checksum, root)


def test_terminal_partial_is_explicit_and_requires_day_end(final_receipt):
    root, make = final_receipt
    status = "TRADING_DAY_WINDOW_ENDED_WITH_MISSING_RECEIPTS"
    with pytest.raises(ValueError, match="CLOCK_CONFLICT"):
        release.terminal_result(make(status=status, complete=False), root)
    assert release.terminal_result(make(status=status, timestamp="2026-11-16T23:58:00+08:00", complete=False), root) == (
        "forward", status)


@pytest.fixture
def controlled_switch(tmp_path, monkeypatch):
    operations = []
    states = {"api": True, "main": True}

    def payload(role, variant):
        return plistlib.dumps({"EnvironmentVariables": {"V4_APP_ROOT": f"/{role}",
            "V4_RELEASE_ID": f"{role}-{variant}", "V4_RELEASE_MANIFEST_SHA256": f"manifest-{role}-{variant}",
            "V4_RESEARCH_RETENTION_POLICY_SHA256": f"policy-{role}-{variant}"}})

    previous = {role: payload(role, "old") for role in states}
    desired = {role: payload(role, "new") for role in states}

    class Controller:
        def live(self, role):
            return tmp_path / (role + ".plist")

        def state(self, role):
            settings = plistlib.loads(self.live(role).read_bytes())["EnvironmentVariables"]
            return {"loaded": states[role], "path": str(self.live(role)), "pid": 100 if role == "api" else 200,
                    "working directory": settings["V4_APP_ROOT"]}, " ".join(settings.values())

        def exact_job(self, role):
            if role == "stage":
                return {"pid": None, "manifest_sha256": "preserved", "plist": {"sha256": "stage"}}
            assert states[role]
            return self.state(role)[0]

        def stop_role(self, role):
            operations.append(("stop", role))
            states[role] = False

        def start_role(self, role):
            operations.append(("start", role))
            states[role] = True

        def atomic_plist(self, path, raw, expected):
            assert release.digest(path.read_bytes()) == expected
            operations.append(("swap", path.stem))
            path.write_bytes(raw)

        def main_log(self):
            return "Main boot log offset"

        def ready(self, offset, identity):
            return True

    control = Controller()
    for role, raw in previous.items():
        control.live(role).write_bytes(raw)
    monkeypatch.setattr(release, "listeners", lambda: {"100"} if states["api"] else set())
    monkeypatch.setattr(release, "read_http", lambda *a, **kw: {"status": "ok"})
    monkeypatch.setattr(release, "verify_controls", lambda _: {"status": "PASS"})
    monkeypatch.setattr(release, "assert_main_workbench_idle", lambda _: None)
    return control, previous, desired, {"api": 100, "main": 200}, operations, states


def test_switch_and_explicit_inverse_have_exact_role_order(controlled_switch):
    control, previous, desired, pids, operations, _ = controlled_switch
    order = [("stop", "main"), ("stop", "api"), ("swap", "api"), ("swap", "main"),
             ("start", "api"), ("start", "main")]
    assert release.switch(control, previous, desired, pids, lambda: "verified")[1] == "verified"
    assert operations == order
    assert {role: control.live(role).read_bytes() for role in desired} == desired
    release.switch(control, desired, previous, pids, lambda: "verified")
    assert operations == order * 2
    assert {role: control.live(role).read_bytes() for role in previous} == previous


def test_failed_readback_restores_exact_preimages(controlled_switch):
    control, previous, desired, pids, operations, states = controlled_switch

    def fail():
        raise ValueError("failed representative API readback")

    with pytest.raises(ValueError, match="failed representative") as failed:
        release.switch(control, previous, desired, pids, fail)
    assert "api" in failed.value.exact_recovery and "main" in failed.value.exact_recovery
    assert set(role for op, role in operations) == {"api", "main"}
    assert all(states.values())
    assert {role: control.live(role).read_bytes() for role in previous} == previous


def test_live_pid_or_plist_drift_stops_before_service_mutation(controlled_switch):
    control, previous, desired, pids, operations, _ = controlled_switch
    with pytest.raises(ValueError, match="PREIMAGE_MOVED"):
        release.switch(control, previous, desired, {**pids, "api": 300}, lambda: None)
    control.live("api").write_bytes(b"foreign")
    with pytest.raises(ValueError, match="PREIMAGE_MOVED"):
        release.switch(control, previous, desired, pids, lambda: None)
    assert not operations


def test_full_api_verification_matches_sealed_archive_rows_including_yidong(monkeypatch):
    payload = {"EnvironmentVariables": {"V4_RELEASE_ID": "candidate", "V4_RELEASE_MANIFEST_SHA256": "manifest"}}
    data = {"source": [{"number": index, "generation": str(index), "sha256": str(index) * 32} for index in (17, 18)]}
    archive = {}
    for entry in data["source"]:
        responses = {}
        for symbol in (*release.SAMPLES, "920201.BJ"):
            status = "CANNOT_CONFIRM" if symbol == "920201.BJ" else "READY"
            row = None if status == "CANNOT_CONFIRM" else {
                "ts_code": symbol, "trade_date": "20261030", "market_type": "BJ" if symbol.endswith(".BJ") else "A_SHARE",
                "close": 37.46, "volume": 1000, "kb_violence_k": False, "kb_yidong": True,
            }
            responses[symbol] = {"status": status, "row": row, "source": {"artifact_sha256": entry["sha256"]}}
        archive[entry["generation"]] = responses
    r4 = {"status": "READY_FOR_RESEARCH_REVIEW"}
    r4_sha = release.digest(json.dumps(r4, sort_keys=True).encode())
    expected = {"samples": {symbol: {"meta_sha256": r4_sha} for symbol in release.SAMPLES},
                "exact_archived_routes": archive}
    observed = []

    def http(port, route, status=200):
        if route == "/healthz":
            return {"status": "ok"}
        if route == "/readyz":
            return release.SAFETY
        if route == "/api/v4/runtime-graph/frontend-build":
            return {"status": "VERIFIED", "api_release_id": "candidate", "api_manifest_sha256": "manifest"}
        if "archived-selector" in route:
            url = urlsplit(route)
            params = parse_qs(url.query)
            generation, symbol = params["generation"][0], url.path.split("/")[-2]
            assert params["trade_date"] == ["2026-10-30"]
            assert params["columns"] == ["close,volume,kb_violence_k,kb_yidong"]
            observed.append((generation, symbol))
            return archive[generation][symbol]
        return r4

    monkeypatch.setattr(release, "read_http", http)
    receipt = release.verify_http(8873, payload, expected, data, active=True, full=True)
    assert receipt["archive_ready_rows"] == 6 and receipt["archive_unknown_rows"] == 2
    assert set(observed) == {(str(index), symbol) for index in (17, 18) for symbol in (*release.SAMPLES, "920201.BJ")}


def test_interrupted_first_plist_swap_recovers_prior_group_and_preserves_stage(controlled_switch):
    control, previous, desired, _, operations, states = controlled_switch
    states.update(main=False, api=False)
    control.live("api").write_bytes(desired["api"])
    stage = control.exact_job("stage")
    _, readback = release.recover_after_interruption(control, previous, desired, stage, lambda: "prior verified")
    assert readback == "prior verified"
    assert operations == [("swap", "api"), ("start", "api"), ("start", "main")]
    assert {role: control.live(role).read_bytes() for role in previous} == previous
    assert control.exact_job("stage") == stage


def test_interrupted_recovery_refuses_foreign_preimage_without_service_changes(controlled_switch):
    control, previous, desired, _, operations, _ = controlled_switch
    control.live("main").write_bytes(b"unrelated")
    with pytest.raises(ValueError, match="FOREIGN_PLIST"):
        release.recover_after_interruption(control, previous, desired, control.exact_job("stage"), lambda: None)
    assert operations == []


def test_recovery_with_loaded_main_respects_existing_active_workbench_guard(controlled_switch, monkeypatch):
    control, previous, desired, _, operations, states = controlled_switch
    states.update(api=False)

    def active(raw):
        assert raw == previous["main"]
        raise ValueError("MAIN_WORKBENCH_ACTIVE_KEEP_RUNNING")

    monkeypatch.setattr(release, "assert_main_workbench_idle", active)
    with pytest.raises(ValueError, match="ACTIVE_KEEP_RUNNING"):
        release.recover_after_interruption(control, previous, desired, control.exact_job("stage"), lambda: None)
    assert operations == []


def test_workbench_idle_checks_live_owner_claims(tmp_path):
    root = tmp_path.resolve()
    config = root / "existing-workbench.json"
    write_json(config, {"state_root": str(root)})
    payload = plistlib.dumps({"EnvironmentVariables": {"V4_MANAGER_WORKBENCH_CONFIG_PATH": str(config)}})
    claims = root / "manager_workbench" / "claims"
    attempts = root / "manager_workbench" / "attempts"
    claims.mkdir(parents=True)
    attempts.mkdir()
    job = "a" * 32
    write_json(claims / "scope.json", {"job_id": job})
    write_json(attempts / f"{job}.json", {"state": "RUNNING"})
    with pytest.raises(ValueError, match="ACTIVE_KEEP_RUNNING"):
        release.assert_main_workbench_idle(payload)
    write_json(attempts / f"{job}.json", {"state": "COMPLETED"})
    release.assert_main_workbench_idle(payload)


@pytest.fixture
def starter(controlled_switch, tmp_path, monkeypatch):
    control, previous, desired, pids, _, _ = controlled_switch
    candidate = tmp_path.resolve() / "candidate"
    monkeypatch.setattr(release, "TARGET", candidate)
    path = candidate / "forward" / "00000001-activate-20261116T171530000000-123" / "START.json"
    path.parent.mkdir(parents=True)
    live = {role: control.live(role) for role in previous}
    owners = {}
    for role, raw in previous.items():
        env = plistlib.loads(raw)["EnvironmentVariables"]
        owners[role] = {"pid": pids[role], "plist": {**release.reference(live[role]), "bytes": len(raw)},
            "app_root": env["V4_APP_ROOT"], "release_id": env["V4_RELEASE_ID"],
            "manifest_sha256": env["V4_RELEASE_MANIFEST_SHA256"], "loaded": True, "state": "running"}
    value = {"variant": "forward", "action": "activate", "seal_sha256": "seal", "natural_sha256": "terminal",
             "preimages": {role: release.digest(raw) for role, raw in previous.items()},
             "target_plists": {role: release.digest(raw) for role, raw in desired.items()},
             "before": owners}
    ref = write_json(path, value)
    arguments = (path, ref["sha256"], "forward", "seal", "terminal", previous, desired, live)
    return path, value, previous, desired, arguments


def test_recovery_requires_exact_unfinished_attempt_and_companion_seals(starter):
    path, value, previous, desired, arguments = starter
    assert release.unfinished_attempt(*arguments) == (value, previous, desired)
    mismatch = (*arguments[:3], "different", *arguments[4:])
    with pytest.raises(ValueError, match="ATTEMPT_IDENTITY_CONFLICT"):
        release.unfinished_attempt(*mismatch)
    write_json(path.parent / "RESULT.json", {"status": "VERIFIED"})
    with pytest.raises(ValueError, match="ATTEMPT_NOT_UNFINISHED"):
        release.unfinished_attempt(*arguments)


def test_recovery_rejects_superseded_starter_even_if_newer_clock_appears_older(starter):
    path, _, _, _, arguments = starter
    later = path.parent.parent / "00000002-rollback-20261116T170000000000-456"
    later.mkdir()
    with pytest.raises(ValueError, match="ATTEMPT_SUPERSEDED"):
        release.unfinished_attempt(*arguments)


def test_recovery_rejects_a_verified_internal_recovery_and_wrong_owner_identity(starter):
    path, value, _, _, arguments = starter
    failure = path.parent / "FAILURE.json"
    write_json(failure, {**value, "exact_recovery": {"api": "verified", "main": "verified"}})
    with pytest.raises(ValueError, match="ALREADY_VERIFIED"):
        release.unfinished_attempt(*arguments)
    value["before"]["main"]["release_id"] = "foreign"
    checksum = write_json(path, value)["sha256"]
    with pytest.raises(ValueError, match="ATTEMPT_IDENTITY_CONFLICT"):
        release.unfinished_attempt(path, checksum, *arguments[2:])


def test_recovery_rejects_restarted_previous_process_in_mixed_state(controlled_switch):
    control, previous, desired, pids, operations, states = controlled_switch
    states.update(api=False)
    with pytest.raises(ValueError, match="PREIMAGE_PROCESS_NOT_OWNED"):
        release.recover_after_interruption(control, previous, desired, control.exact_job("stage"),
            lambda: None, expected_pids={**pids, "main": 999})
    assert operations == []
