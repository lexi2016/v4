"""Registered synthetic-only same-day revision fixtures; never read market data.

This suite deliberately does not import/re-run the accepted 17-field suite.
The controller/registrar must freeze this file and the producer SHA first.
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest


PAYLOAD = Path(__file__).resolve().parents[1] / "ops/runtime_payloads/data_layer_daily_formula_increment_update_v1.py"
NEW_FIELDS = ("fd_volume_yin", "break_yesterday_keyline", "plry_first")


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_sha(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def ref(path):
    return {"path": str(path), "sha256": file_sha(path)}


def dump(path, value):
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return ref(path)


def bound(items):
    items = sorted(items)
    return {"items": items, "count": len(items), "sha256": json_sha(items)}


@pytest.fixture(scope="session", autouse=True)
def registered_execution():
    # Read only the explicitly supplied registry and frozen synthetic contract.
    contract_path = Path(os.environ["V192_SAME_DAY_FIXTURE_CONTRACT"])
    contract = json.loads(contract_path.read_text())
    assert contract["scope"] in ("SYNTHETIC_SAME_DAY_PANEL_FIXTURE_ONLY", "SYNTHETIC_SAME_DAY_PANEL_V2_INTERFACE_ONLY", "SYNTHETIC_SAME_DAY_PANEL_V2_APPROVED_DELETE_AND_NAME_ONLY")
    assert contract["code_sha256"] == file_sha(PAYLOAD)
    assert contract["test_sha256"] == file_sha(__file__)
    assert contract["market_input_rows_read"] == 0
    assert contract["formal_pointer_writes"] == 0
    execution = os.environ["V192_SAME_DAY_EXECUTION_ID"]
    event_sha = os.environ["V192_SAME_DAY_RUN_STARTED_EVENT_SHA256"]
    found = None
    with Path(os.environ["V192_SAME_DAY_REGISTRY"]).open() as stream:
        for line in stream:
            event = json.loads(line)
            if event.get("event_sha256") == event_sha:
                found = event
    assert found is not None and found["event_type"] == "RUN_STARTED"
    assert found["execution_id"] == execution
    assert found["contract_sha256"] == file_sha(contract_path)


@pytest.fixture
def producer(registered_execution):
    name = "v192_same_day_synthetic_producer"
    spec = importlib.util.spec_from_file_location(name, PAYLOAD)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fixture_bundle(tmp_path, module):
    keys = [["000001.SZ", 20261019], ["000001.SZ", 20261020], ["000002.SZ", 20261019]]
    source_keys = keys + [["000002.SZ", 20261020], ["000003.SZ", 20261020]]
    fields = sorted(set(module.V192_FORMULA_FIELDS) | set(module.V192_REQUIRED_CANONICAL_PROJECTION_FIELDS))
    frame = pd.DataFrame(source_keys, columns=["ts_code", "trade_date"])
    for field in fields:
        frame[field] = module.CANONICAL_FORMULA_SOURCE if field == "formula_source" else 0.0
    frame["close"] = [10.0, 11.0, 20.0, 21.0, 30.0]
    frame["untouched"] = ["a", "b", "c", "d", "e"]
    roles = {}
    for role in ("selector", "backtest"):
        source = tmp_path / f"{role}_source.parquet"
        frame.to_parquet(source, index=False, row_group_size=2)
        pointer = tmp_path / f"{role}.txt"
        pointer.write_bytes(b"\xef\xbb\xbf" + str(source).encode() + b"\r\n")
        roles[role] = {"source": ref(source), "pointer": ref(pointer),
                       "projection_fields": list(module.V192_REQUIRED_CANONICAL_PROJECTION_FIELDS) if role == "selector" else [],
                       "raw_fields": ["close"], "derived_fields": fields if role == "selector" else []}
    overlay_frame = frame.iloc[:3].copy()
    for field in fields:
        if field != "formula_source":
            overlay_frame[field] = [1.0, 2.0, 3.0]
    overlay_frame["close"] = [110.0, 111.0, 120.0]
    artifact = tmp_path / "approved.parquet"
    overlay_frame.to_parquet(artifact, index=False)
    canonical = tmp_path / "canonical.py"
    canonical.write_text("# Synthetic authority identity; never execute this fixture file.\n")
    source_binding = dump(tmp_path / "approved_source_binding.json", {"synthetic": True})
    review = dump(tmp_path / "approved_review.json", {"decision": "SYNTHETIC_EXISTING_PASS"})
    overlay = {"keys": bound(keys), "artifact": ref(artifact), "source_binding": source_binding,
               "review_receipt": review, "raw_and_derived_same_input": True,
               "origin": {"raw_sha256": "1" * 64, "event_sha256": "2" * 64, "window_sha256": "3" * 64,
                          "producer_sha256": "4" * 64, "canonical_sha256": file_sha(canonical)}}
    contract = {"schema": "V192_SAME_DAY_PANEL_REVISION_V1", "revision_id": "SYNTHETIC_REVISION_01",
                "signal_date": 20261020, "target_date": 20261021,
                "research_only": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
                "universe": {"target_symbols": bound(["000001.SZ", "000002.SZ", "000003.SZ"]),
                             "accepted_symbols": bound(["000001.SZ", "000002.SZ"]),
                             "excluded_symbols": bound(["000003.SZ"]), "boundary_excluded_symbols": bound(["000002.SZ"]),
                             "original_target_fingerprint": "SYNTHETIC_TARGET_IDENTITY",
                             "coverage_status": "ACCEPTED_ONLY_EXCLUDED_PRESERVED"},
                "consumer_history": {"consumer_sha256": "5" * 64, "signal_start_date": 20261019,
                                     "signal_end_date": 20261020, "recurrence_start_date": 20261019,
                                     "keys": bound([keys[0], keys[2]])},
                "projection_keys": bound(keys), "raw_repair_keys": bound([keys[1]]),
                "raw_repair_fields": ["close"], "raw_repair_derived_fields": fields,
                "approved_overlays": [overlay], "input_history": None, "xdxr_events": None,
                "canonical_source": ref(canonical), "roles": roles, "candidate_dir": str(tmp_path / "candidate")}
    return contract, frame, overlay_frame


def bind_contract(tmp_path, module, contract):
    binding_keys = ("revision_id", "signal_date", "target_date", "input_history", "xdxr_events", "canonical_source", "roles", "universe", "consumer_history",
                    "projection_keys", "raw_repair_keys", "raw_repair_fields", "raw_repair_derived_fields", "approved_overlays")
    binding = {"decision": "PASS_SAME_DAY_REVISION_INPUT_BINDING", "producer_sha256": file_sha(PAYLOAD),
               "binding_sha256": module._same_day_digest({key: contract[key] for key in binding_keys}),
               "raw_and_derived_same_input": True, "derived_closure_confirmed": True}
    contract["input_binding_receipt"] = dump(tmp_path / "input_binding.json", binding)
    return dump(tmp_path / "contract.json", contract)


def build(tmp_path, module, monkeypatch):
    contract, source, approved = fixture_bundle(tmp_path, module)
    frozen = bind_contract(tmp_path, module, contract)
    monkeypatch.setattr(module, "compute_formula_features", lambda *a, **k: pytest.fail("accepted overlay must be reused"))
    receipt = module.run_same_day_revision_candidate(Path(frozen["path"]), frozen["sha256"])
    return contract, source, approved, receipt


def promotion_refs(tmp_path, candidate):
    candidate_ref = ref(tmp_path / "candidate" / "candidate_receipt.json")
    review = dump(tmp_path / "review.json", {"decision": "PASS_SAME_DAY_PANEL_REVISION",
                 "candidate_receipt_sha256": candidate_ref["sha256"], "producer_sha256": candidate["producer_sha256"],
                 "reviewer_identity": "SYNTHETIC_INDEPENDENT_REVIEWER", "writer_identity": "SYNTHETIC_WRITER"})
    owner = dump(tmp_path / "owner.json", {"decision": "EXCLUSIVE_ORIGINAL_PRODUCER_PUBLISHER_CONFIRMED",
                 "candidate_receipt_sha256": candidate_ref["sha256"], "legacy_publishers_excluded": True,
                 "publisher_owner": "SYNTHETIC_TEST_OWNER", "valid_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()})
    return candidate_ref, review, owner


def test_candidate_reuses_pass_preserves_other_cells_and_pointers(tmp_path, producer, monkeypatch):
    contract, source, approved, receipt = build(tmp_path, producer, monkeypatch)
    actual = pd.read_parquet(receipt["artifacts"]["selector"]["path"])
    expected = source.copy()
    fields = list(producer.V192_REQUIRED_CANONICAL_PROJECTION_FIELDS)
    expected.loc[:2, fields] = approved[fields].to_numpy()
    raw_fields = contract["raw_repair_fields"] + contract["raw_repair_derived_fields"]
    expected.loc[1, raw_fields] = approved.loc[1, raw_fields]
    pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    backtest = source.copy()
    backtest.loc[1, "close"] = approved.loc[1, "close"]
    pd.testing.assert_frame_equal(pd.read_parquet(receipt["artifacts"]["backtest"]["path"]), backtest, check_exact=True)
    assert receipt["computed_key_count"] == 0 and receipt["approved_overlay_key_count"] == 3
    for role in ("selector", "backtest"):
        assert file_sha(contract["roles"][role]["pointer"]["path"]) == contract["roles"][role]["pointer"]["sha256"]
    assert receipt["coverage_status"] == "ACCEPTED_ONLY_EXCLUDED_PRESERVED"


@pytest.mark.parametrize("defect", ["missing_r", "overlapping_excluded", "missing_raw_derived", "boundary_signal", "scope_sha"])
def test_exact_scope_fails_closed(tmp_path, producer, defect):
    contract, _source, _approved = fixture_bundle(tmp_path, producer)
    if defect == "missing_r":
        contract["projection_keys"] = bound([["000001.SZ", 20261020]])
    elif defect == "overlapping_excluded":
        contract["universe"]["excluded_symbols"] = bound(["000001.SZ", "000003.SZ"])
    elif defect == "missing_raw_derived":
        contract["raw_repair_derived_fields"] = []
    elif defect == "boundary_signal":
        contract["consumer_history"]["keys"] = bound([["000002.SZ", 20261020]])
        contract["projection_keys"] = bound([["000001.SZ", 20261020], ["000002.SZ", 20261020]])
    else:
        contract["projection_keys"]["sha256"] = "0" * 64
    with pytest.raises(RuntimeError):
        producer._same_day_scope(contract)


@pytest.mark.parametrize("defect", ["missing_column", "nonfinite", "missing_source_key", "duplicate_source_key"])
def test_overlay_invalid_input_preserves_no_output(tmp_path, producer, defect):
    contract, source, approved = fixture_bundle(tmp_path, producer)
    scope = producer._same_day_scope(contract)
    if defect == "missing_column":
        source = source.drop(columns=[NEW_FIELDS[0]])
    elif defect == "nonfinite":
        approved.loc[1, NEW_FIELDS[1]] = np.inf
    elif defect == "missing_source_key":
        source = source.drop(index=1)
    else:
        source = pd.concat([source, source.iloc[[1]]], ignore_index=True)
    path = tmp_path / "invalid.parquet"
    source.to_parquet(path, index=False, row_group_size=2)
    output = tmp_path / "invalid_candidate.parquet"
    with pytest.raises(RuntimeError):
        producer._same_day_overlay_parquet(path, output, approved, scope, "selector")
    assert not output.exists()


@pytest.mark.parametrize("canonical_values", [[0, 1, 0], [0.0, 1.0, 0.0]])
def test_boolean_overlay_accepts_numeric_flags_and_preserves_unapproved_nulls(tmp_path, producer, canonical_values):
    contract, source, approved = fixture_bundle(tmp_path, producer)
    field = NEW_FIELDS[0]
    source[field] = pd.Series([False, False, True, pd.NA, True], dtype="boolean")
    approved[field] = canonical_values
    path = tmp_path / "bool_source.parquet"
    source.to_parquet(path, index=False)
    output = tmp_path / "bool_candidate.parquet"
    producer._same_day_overlay_parquet(path, output, approved, producer._same_day_scope(contract), "selector")
    actual = pq.read_table(output, columns=[field]).column(field).combine_chunks()
    assert actual.type == pa.bool_()
    assert actual.equals(pa.array([False, True, False, None, True], type=pa.bool_()))


def test_integer_overlay_preserves_unapproved_int64_above_float_precision(tmp_path, producer):
    contract, source, approved = fixture_bundle(tmp_path, producer)
    field = NEW_FIELDS[1]
    source[field] = np.array([0, 0, 0, 2**53 + 1, 2**63 - 1], dtype=np.int64)
    approved[field] = [1.0, 2.0, 3.0]
    path = tmp_path / "int64_source.parquet"
    source.to_parquet(path, index=False)
    output = tmp_path / "int64_candidate.parquet"
    producer._same_day_overlay_parquet(path, output, approved, producer._same_day_scope(contract), "selector")
    actual = pq.read_table(output, columns=[field]).column(field).combine_chunks()
    assert actual.type == pa.int64()
    assert actual.equals(pa.array([1, 2, 3, 2**53 + 1, 2**63 - 1], type=pa.int64()))


def test_candidate_files_and_directory_flush_before_success_receipt(tmp_path, producer, monkeypatch):
    fsync = producer.os.fsync
    replace = producer.os.replace
    events = []
    directory = tmp_path / "candidate"
    def sync(fd):
        identity = producer.os.fstat(fd)
        for role in ("selector", "backtest"):
            temporary = directory / f"{role}.tmp.parquet"
            if temporary.exists() and temporary.stat().st_ino == identity.st_ino:
                events.append(("file_fsync", role))
        if directory.exists() and directory.stat().st_ino == identity.st_ino:
            events.append(("directory_fsync", None))
        return fsync(fd)
    def move(source, target):
        target = Path(target)
        if target.name in ("selector.parquet", "backtest.parquet"):
            role = target.stem
            assert ("file_fsync", role) in events
            events.append(("artifact_replace", role))
        if target.name == "candidate_receipt.json":
            for role in ("selector", "backtest"):
                offset = events.index(("artifact_replace", role))
                assert ("directory_fsync", None) in events[offset + 1:]
            events.append(("success_receipt", None))
        return replace(source, target)
    monkeypatch.setattr(producer.os, "fsync", sync)
    monkeypatch.setattr(producer.os, "replace", move)
    build(tmp_path, producer, monkeypatch)
    assert events[-1] == ("directory_fsync", None)
    assert ("success_receipt", None) in events


@pytest.mark.parametrize("failed_role", ["selector", "backtest"])
@pytest.mark.parametrize("failed_phase", ["file", "directory"])
def test_candidate_flush_failure_never_creates_success_receipt(tmp_path, producer, monkeypatch, failed_role, failed_phase):
    fsync = producer.os.fsync
    def fail(fd):
        directory = tmp_path / "candidate"
        temporary = directory / f"{failed_role}.tmp.parquet"
        inode = producer.os.fstat(fd).st_ino
        file_failure = failed_phase == "file" and temporary.exists() and temporary.stat().st_ino == inode
        current_role = "backtest" if (directory / "backtest.parquet").exists() else "selector"
        directory_failure = (failed_phase == "directory" and directory.exists()
                             and directory.stat().st_ino == inode and current_role == failed_role)
        if file_failure or directory_failure:
            raise OSError("synthetic candidate fsync failure")
        return fsync(fd)
    monkeypatch.setattr(producer.os, "fsync", fail)
    with pytest.raises(OSError, match="candidate fsync failure"):
        build(tmp_path, producer, monkeypatch)
    assert not (tmp_path / "candidate" / "candidate_receipt.json").exists()
    assert (tmp_path / "candidate" / f"{failed_role}.parquet").exists() == (failed_phase == "directory")
    for role in ("selector", "backtest"):
        expected = b"\xef\xbb\xbf" + str(tmp_path / f"{role}_source.parquet").encode() + b"\r\n"
        assert (tmp_path / f"{role}.txt").read_bytes() == expected


def test_remaining_partition_calls_original_producer_once(tmp_path, producer, monkeypatch):
    contract, _source, approved = fixture_bundle(tmp_path, producer)
    overlay = contract["approved_overlays"][0]
    overlay["keys"] = bound([["000002.SZ", 20261019]])
    approved.iloc[[2]].to_parquet(overlay["artifact"]["path"], index=False)
    overlay["artifact"] = ref(overlay["artifact"]["path"])
    history = tmp_path / "history.parquet"
    raw_history = approved.iloc[:2][["ts_code", "trade_date", "close"]].copy()
    for field in ("open", "high", "low", "vol", "amount"):
        raw_history[field] = [10.0, 11.0]
    raw_history.to_parquet(history, index=False)
    events = tmp_path / "events.parquet"
    pd.DataFrame({"ts_code": pd.Series(dtype=str)}).to_parquet(events, index=False)
    contract["input_history"], contract["xdxr_events"] = ref(history), ref(events)
    frozen = bind_contract(tmp_path, producer, contract)
    calls = []
    prior_authority = producer.CANONICAL_FORMULA_PATH
    def compute(frame, *args, **kwargs):
        calls.append((frame.copy(), kwargs))
        assert producer.CANONICAL_FORMULA_PATH == Path(contract["canonical_source"]["path"])
        return approved.iloc[:2].copy()
    monkeypatch.setattr(producer, "compute_formula_features", compute)
    receipt = producer.run_same_day_revision_candidate(Path(frozen["path"]), frozen["sha256"])
    assert len(calls) == 1 and calls[0][1]["emit_all_rows"] is True
    assert set(calls[0][0].ts_code) == {"000001.SZ"}
    assert receipt["computed_key_count"] == 2 and receipt["approved_overlay_key_count"] == 1
    assert producer.CANONICAL_FORMULA_PATH == prior_authority


def test_approved_artifact_drift_rejected_before_candidate(tmp_path, producer):
    contract, _source, _approved = fixture_bundle(tmp_path, producer)
    frozen = bind_contract(tmp_path, producer, contract)
    Path(contract["approved_overlays"][0]["review_receipt"]["path"]).write_text("changed")
    with pytest.raises(RuntimeError, match="bound file missing or changed"):
        producer.run_same_day_revision_candidate(Path(frozen["path"]), frozen["sha256"])
    assert not Path(contract["candidate_dir"]).exists()


def test_promote_is_idempotent_and_saves_old_new(tmp_path, producer, monkeypatch):
    contract, _source, _approved, candidate = build(tmp_path, producer, monkeypatch)
    refs = promotion_refs(tmp_path, candidate)
    result = producer.promote_same_day_revision(*refs)
    assert result["status"] == "PROMOTED" and result["phases"][-1] == "PROMOTED"
    assert producer.promote_same_day_revision(*refs) == result
    for role in ("selector", "backtest"):
        state = result["pointers"][role]
        assert Path(state["path"]).read_bytes() == base64.b64decode(state["new_b64"])
        assert hashlib.sha256(base64.b64decode(state["old_b64"])).hexdigest() == contract["roles"][role]["pointer"]["sha256"]


def test_interrupted_first_pointer_resumes_without_rollback(tmp_path, producer, monkeypatch):
    _contract, _source, _approved, candidate = build(tmp_path, producer, monkeypatch)
    refs = promotion_refs(tmp_path, candidate)
    original = producer._same_day_atomic_json
    def interrupt(path, payload):
        if payload.get("phases", [])[-1:] == ["SELECTOR_NEW"]:
            raise OSError("synthetic interruption after first pointer")
        return original(path, payload)
    monkeypatch.setattr(producer, "_same_day_atomic_json", interrupt)
    with pytest.raises(OSError, match="synthetic interruption"):
        producer.promote_same_day_revision(*refs)
    assert Path(candidate["pointers"]["selector"]["path"]).read_bytes() == base64.b64decode(candidate["pointers"]["selector"]["new_b64"])
    monkeypatch.setattr(producer, "_same_day_atomic_json", original)
    assert producer.promote_same_day_revision(*refs)["status"] == "PROMOTED"


def test_interrupted_staged_pointer_bytes_resume(tmp_path, producer, monkeypatch):
    _contract, _source, _approved, candidate = build(tmp_path, producer, monkeypatch)
    refs = promotion_refs(tmp_path, candidate)
    replace = producer.os.replace
    selector = Path(candidate["pointers"]["selector"]["path"])
    def interrupt(source, target):
        if Path(target) == selector:
            raise OSError("synthetic interruption before replace")
        return replace(source, target)
    monkeypatch.setattr(producer.os, "replace", interrupt)
    with pytest.raises(OSError, match="before replace"):
        producer.promote_same_day_revision(*refs)
    assert selector.with_name(selector.name + ".same_day.tmp").exists()
    monkeypatch.setattr(producer.os, "replace", replace)
    assert producer.promote_same_day_revision(*refs)["status"] == "PROMOTED"


def test_third_writer_between_pointer_writes_stops_without_rollback(tmp_path, producer, monkeypatch):
    _contract, _source, _approved, candidate = build(tmp_path, producer, monkeypatch)
    refs = promotion_refs(tmp_path, candidate)
    original = producer._same_day_atomic_json
    backtest = Path(candidate["pointers"]["backtest"]["path"])
    def competing_writer(path, payload):
        result = original(path, payload)
        if payload.get("phases", [])[-1:] == ["SELECTOR_NEW"]:
            backtest.write_bytes(b"THIRD_VERSION_AFTER_SELECTOR")
        return result
    monkeypatch.setattr(producer, "_same_day_atomic_json", competing_writer)
    with pytest.raises(RuntimeError, match="CAS lost"):
        producer.promote_same_day_revision(*refs)
    assert backtest.read_bytes() == b"THIRD_VERSION_AFTER_SELECTOR"
    selector = candidate["pointers"]["selector"]
    assert Path(selector["path"]).read_bytes() == base64.b64decode(selector["new_b64"])


@pytest.mark.parametrize("defect", ["third_version", "reverse_prefix", "missing_review", "missing_owner", "expired_owner", "candidate_drift"])
def test_promote_rejects_unbound_state(tmp_path, producer, monkeypatch, defect):
    _contract, _source, _approved, candidate = build(tmp_path, producer, monkeypatch)
    refs = list(promotion_refs(tmp_path, candidate))
    if defect == "third_version":
        Path(candidate["pointers"]["selector"]["path"]).write_bytes(b"THIRD_VERSION")
    elif defect == "reverse_prefix":
        state = candidate["pointers"]["backtest"]
        Path(state["path"]).write_bytes(base64.b64decode(state["new_b64"]))
    elif defect in ("missing_review", "missing_owner", "expired_owner"):
        index = 1 if defect == "missing_review" else 2
        path = Path(refs[index]["path"])
        payload = json.loads(path.read_text())
        if defect == "expired_owner":
            payload["valid_until"] = "2000-01-01T00:00:00+00:00"
        else:
            payload["decision"] = "CANNOT_CONFIRM"
        refs[index] = dump(path, payload)
    else:
        Path(candidate["artifacts"]["selector"]["path"]).write_bytes(b"changed")
    before = {r: Path(candidate["pointers"][r]["path"]).read_bytes() for r in ("selector", "backtest")}
    with pytest.raises(RuntimeError):
        producer.promote_same_day_revision(*refs)
    assert before == {r: Path(candidate["pointers"][r]["path"]).read_bytes() for r in ("selector", "backtest")}


def synthetic_history():
    return pd.DataFrame({"ts_code": ["000001.SZ"] * 4, "trade_date": [20261015, 20261016, 20261019, 20261020],
                         "open": [10., 11., 12., 13.], "high": [11., 12., 13., 14.],
                         "low": [9., 10., 11., 12.], "close": [10.5, 11.5, 12.5, 13.5],
                         "vol": [100., 110., 120., 130.], "amount": [1000., 1100., 1200., 1300.]})


def fake_canonical(module, frame):
    result = frame.copy()
    for field in set(module.V192_FORMULA_FIELDS) | set(module.V192_REQUIRED_CANONICAL_PROJECTION_FIELDS):
        result[field] = module.CANONICAL_FORMULA_SOURCE if field == "formula_source" else np.arange(len(frame), dtype=float)
    return result


def test_three_new_columns_project_from_same_canonical_call(producer, monkeypatch):
    calls = []
    def canonical(frame):
        calls.append(frame)
        return fake_canonical(producer, frame)
    monkeypatch.setattr(producer, "_compute_canonical_v192_formula", canonical)
    result = producer.compute_formula_features(synthetic_history(), 0, {}, producer._NoopLogger(), emit_all_rows=True)
    assert len(calls) == 1
    for field in NEW_FIELDS:
        np.testing.assert_array_equal(result[field], np.arange(4, dtype=float))


@pytest.mark.parametrize("field", NEW_FIELDS)
@pytest.mark.parametrize("defect", ["missing", "nan", "inf"])
def test_three_new_columns_fail_closed(producer, monkeypatch, field, defect):
    def canonical(frame):
        result = fake_canonical(producer, frame)
        if defect == "missing":
            return result.drop(columns=[field])
        result.loc[0, field] = np.nan if defect == "nan" else np.inf
        return result
    monkeypatch.setattr(producer, "_compute_canonical_v192_formula", canonical)
    with pytest.raises(RuntimeError, match="required projection fields"):
        producer.compute_formula_features(synthetic_history(), 0, {}, producer._NoopLogger(), emit_all_rows=True)


def test_ordinary_cutoff_still_excludes_same_day(producer):
    frame = pd.DataFrame({"ts_code": ["000001.SZ"] * 2, "trade_date": [20261020, 20261021]})
    result = producer.select_generated_increment_rows(frame, base_after_date=20261020)
    assert result.trade_date.tolist() == [20261021]


@pytest.mark.parametrize("args", [["--same-day-revision"], ["--candidate-only"],
                                   ["--same-day-promote"], ["--same-day-revision", "--same-day-promote"]])
def test_cli_rejects_incomplete_or_mixed_modes(producer, monkeypatch, args):
    monkeypatch.setattr(sys, "argv", [str(PAYLOAD)] + args)
    with pytest.raises(SystemExit) as error:
        producer.parse_args()
    assert error.value.code == 2


def v2_ordered_key_sha(keys):
    digest = hashlib.sha256()
    for code, day in keys:
        digest.update((json.dumps([code, int(day)], ensure_ascii=False, separators=(",", ":")) + "\n").encode())
    return digest.hexdigest()


def v2_fixture(tmp_path, module, *, raw_difference=True):
    """Synthetic new-admission/missing-key fixture; all generations are saved PASS stubs."""
    keys = [("000001.SZ", 20261019), ("000001.SZ", 20261020),
            ("000002.SZ", 20261019), ("000002.SZ", 20261020)]
    feature_columns = ["ts_code", "trade_date", "name", "open", "high", "low", "close", "volume", "amount",
                       "BBI", "J", "macd_dif", "bar_close_pos", "is_st_snapshot", "is_one_word_limit_up_est"]
    selector_columns = ["brick_context", "brick_resonance1", "formula_source", "field_contract_version"]
    consumers = set(feature_columns) | set(selector_columns)
    projected = consumers | set(module.V192_REQUIRED_CANONICAL_PROJECTION_FIELDS)
    feature_source = tmp_path / "frozen_feature.py"
    feature_source.write_text("REQUIRED_BASE_COLUMNS = " + repr(feature_columns) + "\n")
    selector_source = tmp_path / "frozen_selector.py"
    selector_source.write_text("_PREMARKET_SOURCE_FIELDS = " + repr(tuple(selector_columns))
                               + "\ndef run_frozen_v192_oracle(*args):\n    pass\n")
    score_role_source = tmp_path / "frozen_score_role.py"
    score_role_source.write_text("def score_v19(*args):\n    pass\ndef score_multi_head(*args):\n    pass\n"
                                 "def entry_pool(*args):\n    pass\ndef base_fmla04_role(*args):\n    pass\n")
    canonical_source = tmp_path / "canonical_v2.py"
    canonical_source.write_text("# Bound synthetic authority, never imported by approved-only fixture.\n")
    enrichment_source = tmp_path / "enrichment_v2.py"
    enrichment_source.write_text("def add_limit_fields(frame):\n    return {}, frame.copy()\n")
    approval = dump(tmp_path / "independent_approval.json", {"decision": "SYNTHETIC_INDEPENDENT_PASS"})
    raw = pd.DataFrame(keys, columns=["ts_code", "trade_date"])
    for field in ("open", "high", "low", "close", "amount"):
        raw[field] = [10.0, 11.0, 20.0, 21.0]
    raw["volume"] = [100, 101, 200, 201]
    raw["vol"] = raw["volume"]
    produced = raw.copy()
    for field in sorted(projected - set(produced)):
        produced[field] = [1.0, 2.0, 3.0, 4.0]
    produced["name"] = ["Bound A", "Bound A", "Bound B", "Bound B"]
    produced["is_st_snapshot"] = False
    produced["is_one_word_limit_up_est"] = False
    produced["BBI"], produced["J"], produced["macd_dif"] = [11., 12., 21., 22.], [31., 32., 41., 42.], [51., 52., 61., 62.]
    produced["brick_context"] = ["B1", "B2", "B1", "B2"]
    produced["formula_source"] = module.CANONICAL_FORMULA_SOURCE
    produced["field_contract_version"] = module.CONTRACT_PROVENANCE_FIELD_DEFAULTS["field_contract_version"]
    produced["untouched_integer"] = [7, 8, 9, 10]
    canonical = produced.copy()
    canonical[["BBI", "J", "macd_dif"]] = 999.0
    canonical[NEW_FIELDS[0]] = [0.0, 1.0, 0.0, 1.0]
    enriched = produced.copy()
    enriched["is_st_snapshot"] = [False, True, False, True]
    enriched["is_one_word_limit_up_est"] = [True, False, True, False]
    packet_refs = {}
    for name, frame in (("producer", produced), ("canonical", canonical), ("raw", raw), ("enrichment", enriched)):
        path = tmp_path / f"v2_admitted_{name}.parquet"
        frame.to_parquet(path, index=False)
        packet_refs[name] = ref(path)
    static = {"records": [{"ts_code": code, "field": "name", "value": name, "observed_date": 20261020,
                           "status": "CURRENT_REVISION_NON_PIT", "reason": "Bound synthetic current name", "source": approval}
                          for code, name in (("000001.SZ", "Bound A"), ("000002.SZ", "Bound B"))]}
    static_ref = dump(tmp_path / "v2_static.json", static)
    lineage = {}
    for field in projected:
        if field in ("ts_code", "trade_date"):
            lineage[field] = {"kind": "key"}
        elif field in ("open", "high", "low", "close", "volume", "amount"):
            lineage[field] = {"kind": "raw", "field": field}
        elif field == "name":
            lineage[field] = {"kind": "static", "field": field}
        elif field == "field_contract_version":
            lineage[field] = {"kind": "constant", "value": module.CONTRACT_PROVENANCE_FIELD_DEFAULTS[field],
                              "reason": "Original contract constant", "approval": approval}
        elif field in ("is_st_snapshot", "is_one_word_limit_up_est"):
            lineage[field] = {"kind": "enrichment", "field": field}
        elif field in set(module.V192_FORMULA_FIELDS) | set(module.V192_REQUIRED_CANONICAL_PROJECTION_FIELDS):
            lineage[field] = {"kind": "canonical", "field": field}
        else:
            lineage[field] = {"kind": "producer", "field": field}
    old_frames, role_items = {}, {}
    for role, source_keys in (("selector", [keys[1], keys[0], keys[2], ("000003.SZ", 20261020)]),
                              ("backtest", [keys[3], keys[0], keys[1], ("000003.SZ", 20261020)])):
        source_keys = source_keys + [("000003.SZ", 20261020)]  # Preserve unrelated legacy duplicates.
        rows = []
        for position, key in enumerate(source_keys):
            if key in keys:
                row = produced.iloc[keys.index(key)].to_dict()
                if raw_difference and key == keys[1]:
                    row["volume"] -= 1
            else:
                row = produced.iloc[0].to_dict()
                row.update(ts_code=key[0], trade_date=key[1])
            row.update(name="Legacy name", BBI=-11.0, J=-12.0, macd_dif=-13.0,
                       untouched_integer=2**53 + 1 + position, extra_metadata="old metadata")
            rows.append(row)
        frame = pd.DataFrame(rows)
        frame = frame[sorted(projected) + ["untouched_integer", "extra_metadata"]]
        frame[NEW_FIELDS[0]] = pd.Series([False, False, False, pd.NA], dtype="boolean")
        if role == "backtest":
            frame = frame.rename(columns={"volume": "vol"})
            frame["vol"] = frame["vol"].astype("float32")
        table = pa.Table.from_pandas(frame, preserve_index=False)
        encoded = pa.array(frame["ts_code"]).dictionary_encode().cast(pa.dictionary(pa.int16(), pa.string()))
        table = table.set_column(table.schema.get_field_index("ts_code"), pa.field("ts_code", encoded.type), encoded)
        path = tmp_path / f"v2_{role}_source.parquet"
        pq.write_table(table, path, row_group_size=2)
        pointer = tmp_path / f"v2_{role}.txt"
        pointer.write_bytes(str(path).encode() + b"\n")
        updates, inserts = set(source_keys) & set(keys), set(keys) - set(source_keys)
        raw_map = {field: field for field in ("open", "high", "low", "close", "amount")}
        raw_map["volume" if role == "selector" else "vol"] = "volume"
        update_lineage = {field: lineage[field] for field in set(table.schema.names) & (projected - {"ts_code", "trade_date"})}
        update_lineage.update({target: {"kind": "raw", "field": origin} for target, origin in raw_map.items()})
        insert_lineage = dict(update_lineage)
        insert_lineage.update(ts_code={"kind": "key"}, trade_date={"kind": "key"},
                              untouched_integer={"kind": "producer", "field": "untouched_integer"},
                              extra_metadata={"kind": "unknown_null", "reason": "Unknown nonconsumer metadata",
                                              "approval": approval})
        role_items[role] = {"source": ref(path), "pointer": ref(pointer), "existing_update_keys": bound([list(k) for k in updates]),
                            "approved_insert_keys": bound([list(k) for k in inserts]),
                            "approved_raw_replace_keys": bound([list(keys[1])] if raw_difference else []),
                            "raw_field_map": raw_map, "update_lineage": update_lineage, "insert_lineage": insert_lineage,
                            "required_nonnull_fields": [], "expected_old_rows": len(source_keys),
                            "expected_new_rows": len(source_keys) + len(inserts),
                            "source_key_sha256": v2_ordered_key_sha(source_keys),
                            "expected_new_key_sha256": v2_ordered_key_sha(source_keys + sorted(inserts)),
                            "schema_sha256": json_sha([{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in table.schema])}
        old_frames[role] = table
    contract = {"schema": "V192_SAME_DAY_PANEL_REVISION_V2", "revision_id": "SYNTHETIC_V2_ADMISSION_AND_INSERT",
                "signal_date": 20261020, "target_date": 20261021, "research_only": True,
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
                "admission_ledger": {"target": bound(["000001.SZ", "000002.SZ", "000003.SZ"]),
                                     "accepted": bound(["000001.SZ"]), "excluded": bound(["000002.SZ", "000003.SZ"]),
                                     "boundary": bound([]), "original_target_fingerprint": "SYNTHETIC_ORIGINAL_TARGET",
                                     "original_receipts": {"target": approval, "accepted": approval, "boundary": approval},
                                     "approved_changes": [{"ts_code": "000002.SZ", "from": "EXCLUDED", "to": "ACCEPTED_CURRENT_REVISION",
                                                           "original_reason": "QUARANTINED", "current_reason": "Independent raw/derived PASS",
                                                           "input_review": approval, "derived_review": approval}]},
                "effective_universe": {"accepted": bound(["000001.SZ", "000002.SZ"]), "excluded": bound(["000003.SZ"]),
                                       "boundary": bound([]), "coverage_status": "APPROVED_CURRENT_REVISION_EXCLUSIONS_RETAINED"},
                "consumer_history": {"keys": bound([list(keys[0]), list(keys[2])]), "consumer_sha256": file_sha(selector_source),
                                     "signal_start_date": 20261019, "signal_end_date": 20261020, "recurrence_start_date": 20261019},
                "projection_keys": bound([list(key) for key in keys]),
                "consumer_sources": {"feature": ref(feature_source), "selector": ref(selector_source),
                                     "runtime_consumer": ref(selector_source), "score": ref(score_role_source), "role": ref(score_role_source)},
                "consumer_columns": bound(list(consumers)), "projection_lineage": lineage,
                "static_rows": static_ref, "canonical_source": ref(canonical_source), "enrichment_source": ref(enrichment_source),
                "roles": role_items, "candidate_dir": str(tmp_path / "v2_candidate"), "remaining_generation": None,
                "approved_generations": [{"keys": bound([list(key) for key in keys]), **packet_refs,
                                          "source_binding": approval, "review_receipt": approval, "same_input_generation": True,
                                          "origin": {"raw_sha256": packet_refs["raw"]["sha256"], "event_sha256": "e" * 64,
                                                     "window_sha256": packet_refs["raw"]["sha256"], "producer_sha256": "p" * 64,
                                                     "canonical_sha256": file_sha(canonical_source)}}]}
    return contract, old_frames, keys


def v2_bind(tmp_path, module, contract):
    identity = {key: value for key, value in contract.items() if key != "input_binding_receipt"}
    receipt = {"decision": "PASS_SAME_DAY_V2_COMPLETE_INPUT_BINDING", "producer_sha256": file_sha(PAYLOAD),
               "binding_sha256": module._same_day_digest(identity), "complete_consumer_closure": True,
               "exact_raw_derived_generation": True, "approved_generation_reviews": True,
               "effective_admissions": True, "strict_insert_lineage": True, "actual_consumer_history": True}
    contract["input_binding_receipt"] = dump(tmp_path / "v2_input_binding.json", receipt)
    return dump(tmp_path / "v2_contract.json", contract)


def v2_run(tmp_path, module, monkeypatch, contract):
    frozen = v2_bind(tmp_path, module, contract)
    monkeypatch.setattr(module, "compute_formula_features", lambda *a, **k: pytest.fail("accepted generations must not be recomputed"))
    return module.run_same_day_revision_candidate(Path(frozen["path"]), frozen["sha256"])


def v2_exact_row(frame, key):
    selected = frame.loc[frame.ts_code.astype(str).eq(key[0]) & frame.trade_date.eq(key[1])]
    assert len(selected) == 1, f"Expected exactly one approved target row: {key}"
    return selected.iloc[0]


def test_v2_complete_consumer_overlay_role_volume_and_absent_key_insert(tmp_path, producer, monkeypatch):
    contract, old, keys = v2_fixture(tmp_path, producer)
    receipt = v2_run(tmp_path, producer, monkeypatch, contract)
    assert receipt["approved_generation_keys"] == 4 and receipt["computed_generation_keys"] == 0
    assert receipt["u_key_count"] == 2
    for role in ("selector", "backtest"):
        table = pq.read_table(receipt["artifacts"][role]["path"])
        frame = table.to_pandas()
        assert table.num_rows == old[role].num_rows + 1
        assert table.schema == old[role].schema
        assert table.column("untouched_integer").slice(0, old[role].num_rows).equals(old[role].column("untouched_integer"))
        assert table.slice(old[role].num_rows - 2, 2).equals(old[role].slice(old[role].num_rows - 2, 2))
        assert frame.ts_code.astype(str).eq("000003.SZ").sum() == 2
        actual = v2_exact_row(frame, keys[1])
        assert actual["BBI"] == 12.0 and actual["J"] == 32.0
        assert actual["macd_dif"] == 52.0
        assert bool(actual["is_st_snapshot"]) is True
        assert actual["volume" if role == "selector" else "vol"] == 101
        inserted = tuple(contract["roles"][role]["approved_insert_keys"]["items"][0])
        assert pd.isna(v2_exact_row(frame, inserted)["extra_metadata"])
        assert receipt["artifacts"][role]["raw_replaced_key_count"] == 1
        assert file_sha(contract["roles"][role]["pointer"]["path"]) == contract["roles"][role]["pointer"]["sha256"]


def test_v2_required_dictionary_backtest_provenance_uses_original_helper_without_old_carry(tmp_path, producer, monkeypatch):
    contract, _old, keys = v2_fixture(tmp_path, producer)
    role = contract["roles"]["backtest"]
    path = Path(role["source"]["path"])
    table = pq.read_table(path)
    dtype = pa.dictionary(pa.int16(), pa.string())
    table = table.append_column(pa.field("panel_role", dtype), pa.array(["LEGACY_ROLE"] * table.num_rows, type=dtype))
    pq.write_table(table, path)
    role["source"] = ref(path)
    role["schema_sha256"] = json_sha([{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in table.schema])
    role["required_nonnull_fields"] = ["panel_role"]
    for name in ("update_lineage", "insert_lineage"):
        role[name]["panel_role"] = {"kind": "backtest_producer", "field": "panel_role"}
    receipt = v2_run(tmp_path, producer, monkeypatch, contract)
    result = pq.read_table(receipt["artifacts"]["backtest"]["path"])
    assert result.schema.field("panel_role").type == dtype
    frame = result.to_pandas()
    assert set(frame.loc[frame.ts_code.astype(str).isin({key[0] for key in keys}), "panel_role"].astype(str)) == {"BACKTEST_BASE_DAILY_INCREMENT"}
    assert frame.loc[frame.ts_code.astype(str).eq("000003.SZ"), "panel_role"].astype(str).tolist() == ["LEGACY_ROLE", "LEGACY_ROLE"]


@pytest.mark.parametrize("defect", ["generic_alias", "scaled_volume", "wrong_native_field"])
def test_v2_only_exact_role_volume_mapping_is_admitted(tmp_path, producer, defect):
    contract, _old, _keys = v2_fixture(tmp_path, producer)
    mapping = contract["roles"]["backtest"]["raw_field_map"]
    if defect == "generic_alias":
        mapping["bbi"] = "BBI"
    elif defect == "scaled_volume":
        mapping["vol"] = {"field": "volume", "scale": 100}
    else:
        mapping["vol"] = "amount"
    with pytest.raises(RuntimeError, match="volume/vol role mapping"):
        producer._same_day_v2_scope(contract)


@pytest.mark.parametrize("defect", ["native_pair_mismatch", "role_volume_precision_loss"])
def test_v2_native_volume_mismatch_or_loss_stops(tmp_path, producer, monkeypatch, defect):
    contract, _old, keys = v2_fixture(tmp_path, producer)
    packet = contract["approved_generations"][0]
    if defect == "native_pair_mismatch":
        path = Path(packet["raw"]["path"])
        frame = pd.read_parquet(path)
        frame.loc[0, "vol"] += 1
        frame.to_parquet(path, index=False)
        packet["raw"] = ref(path)
    else:
        for channel in ("raw", "producer", "canonical", "enrichment"):
            path = Path(packet[channel]["path"])
            frame = pd.read_parquet(path)
            frame.loc[1, "volume"] = 2**24 + 1
            if "vol" in frame:
                frame.loc[1, "vol"] = 2**24 + 1
            frame.to_parquet(path, index=False)
            packet[channel] = ref(path)
    expected_error = pa.ArrowInvalid if defect == "role_volume_precision_loss" else RuntimeError
    expected_message = "Integer value 16777217.*exactly representable.*IEEE 754 single precision" if defect == "role_volume_precision_loss" else "native vol/volume mismatch"
    with pytest.raises(expected_error, match=expected_message):
        v2_run(tmp_path, producer, monkeypatch, contract)
    assert not (tmp_path / "v2_candidate" / "candidate_receipt.json").exists()


@pytest.mark.parametrize("defect", ["missing_insert_field", "consumer_unknown", "unknown_without_reason", "derived_as_static"])
def test_v2_strict_insert_never_uses_defaults_or_old_derived_carry(tmp_path, producer, monkeypatch, defect):
    contract, _old, _keys = v2_fixture(tmp_path, producer)
    rules = contract["roles"]["selector"]["insert_lineage"]
    if defect == "missing_insert_field":
        del rules["extra_metadata"]
    elif defect == "consumer_unknown":
        rules["BBI"] = rules["extra_metadata"]
    elif defect == "unknown_without_reason":
        rules["extra_metadata"]["reason"] = ""
    else:
        contract["projection_lineage"]["BBI"] = {"kind": "static", "field": "BBI"}
        contract["roles"]["selector"]["update_lineage"]["BBI"] = {"kind": "static", "field": "BBI"}
    monkeypatch.setattr(producer, "build_table_for_schema", lambda *a, **k: pytest.fail("ordinary default builder is forbidden"))
    monkeypatch.setattr(producer, "default_series_for_field", lambda *a, **k: pytest.fail("default filling is forbidden"))
    with pytest.raises(RuntimeError):
        v2_run(tmp_path, producer, monkeypatch, contract)
    assert not (tmp_path / "v2_candidate" / "candidate_receipt.json").exists()


@pytest.mark.parametrize("defect", ["insert_already_exists", "missing_update_key", "wrong_source_key_sha", "wrong_new_key_sha", "wrong_row_count", "raw_mismatch_unapproved"])
def test_v2_exact_update_insert_key_and_raw_bindings_fail_closed(tmp_path, producer, monkeypatch, defect):
    contract, _old, keys = v2_fixture(tmp_path, producer)
    role = contract["roles"]["selector"]
    if defect == "insert_already_exists":
        updates = role["existing_update_keys"]["items"]
        inserts = role["approved_insert_keys"]["items"]
        swap_update, swap_insert = updates[0], inserts[0]
        role["existing_update_keys"] = bound([key for key in updates if key != swap_update] + [swap_insert])
        role["approved_insert_keys"] = bound([swap_update])
        role["approved_raw_replace_keys"] = bound([])
    elif defect == "missing_update_key":
        path = Path(role["source"]["path"])
        table = pq.read_table(path)
        frame = table.to_pandas()
        frame = frame.loc[~(frame.ts_code.eq(keys[0][0]) & frame.trade_date.eq(keys[0][1]))].copy()
        rewritten = pa.Table.from_pandas(frame, schema=table.schema, preserve_index=False)
        pq.write_table(rewritten, path)
        role["source"] = ref(path)
        remaining_keys = list(zip(frame.ts_code.astype(str), frame.trade_date.astype(int)))
        role["expected_old_rows"] = len(frame)
        role["expected_new_rows"] = len(frame) + role["approved_insert_keys"]["count"]
        role["source_key_sha256"] = v2_ordered_key_sha(remaining_keys)
        role["expected_new_key_sha256"] = v2_ordered_key_sha(remaining_keys + [tuple(k) for k in role["approved_insert_keys"]["items"]])
    elif defect == "wrong_source_key_sha":
        role["source_key_sha256"] = "0" * 64
    elif defect == "wrong_new_key_sha":
        role["expected_new_key_sha256"] = "0" * 64
    elif defect == "wrong_row_count":
        role["expected_new_rows"] += 1
    else:
        role["approved_raw_replace_keys"] = bound([])
    with pytest.raises(RuntimeError):
        v2_run(tmp_path, producer, monkeypatch, contract)
    assert not (tmp_path / "v2_candidate" / "candidate_receipt.json").exists()


@pytest.mark.parametrize("defect", ["hard_locked_old_accepted", "missing_admission_review", "incomplete_consumer_closure", "canonical_overwrites_producer_field"])
def test_v2_admission_and_complete_original_consumer_source_are_binding(tmp_path, producer, defect):
    contract, _old, _keys = v2_fixture(tmp_path, producer)
    if defect == "hard_locked_old_accepted":
        contract["effective_universe"]["accepted"] = contract["admission_ledger"]["accepted"]
    elif defect == "missing_admission_review":
        contract["admission_ledger"]["approved_changes"][0]["derived_review"]["sha256"] = "0" * 64
    elif defect == "incomplete_consumer_closure":
        contract["consumer_columns"] = bound([field for field in contract["consumer_columns"]["items"] if field != "BBI"])
    else:
        contract["projection_lineage"]["BBI"] = {"kind": "canonical", "field": "BBI"}
    with pytest.raises(RuntimeError):
        producer._same_day_v2_scope(contract)


def test_v2_nonnullable_unknown_insert_field_stops(tmp_path, producer, monkeypatch):
    contract, _old, _keys = v2_fixture(tmp_path, producer)
    role = contract["roles"]["selector"]
    path = Path(role["source"]["path"])
    table = pq.read_table(path)
    index = table.schema.get_field_index("extra_metadata")
    table = table.set_column(index, table.schema.field(index).with_nullable(False), table.column("extra_metadata"))
    pq.write_table(table, path)
    role["source"] = ref(path)
    role["schema_sha256"] = json_sha([{"name": f.name, "type": str(f.type), "nullable": f.nullable} for f in table.schema])
    with pytest.raises(RuntimeError, match="nullable nonconsumer"):
        v2_run(tmp_path, producer, monkeypatch, contract)
    assert not (tmp_path / "v2_candidate" / "candidate_receipt.json").exists()


@pytest.mark.parametrize("admission", ["missing", "reviewed", "target_day_forbidden"])
def test_v2_original_structural_na_needs_exact_prior_review_and_no_default_zero(tmp_path, producer, monkeypatch, admission):
    contract, _old, keys = v2_fixture(tmp_path, producer)
    packet = contract["approved_generations"][0]
    key = keys[0] if admission != "target_day_forbidden" else keys[1]
    path = Path(packet["producer"]["path"])
    frame = pd.read_parquet(path)
    frame.loc[frame.ts_code.eq(key[0]) & frame.trade_date.eq(key[1]), "BBI"] = np.nan
    frame.to_parquet(path, index=False)
    packet["producer"] = ref(path)
    if admission != "missing":
        contract["structural_na"] = [{"field": "BBI", "keys": bound([list(key)]),
                                      "reason": "Synthetic original first-window undefined value",
                                      "review_receipt": packet["review_receipt"]}]
    if admission == "reviewed":
        receipt = v2_run(tmp_path, producer, monkeypatch, contract)
        actual = pd.read_parquet(receipt["artifacts"]["selector"]["path"])
        assert pd.isna(v2_exact_row(actual, key)["BBI"])
    else:
        with pytest.raises(RuntimeError):
            v2_run(tmp_path, producer, monkeypatch, contract)
        assert not (tmp_path / "v2_candidate" / "candidate_receipt.json").exists()


@pytest.mark.parametrize("flat", [True, False])
def test_v2_signal_day_bar_close_pos_retains_original_reviewed_flat_bar_null_policy(tmp_path, producer, monkeypatch, flat):
    contract, _old, keys = v2_fixture(tmp_path, producer)
    packet = contract["approved_generations"][0]
    path = Path(packet["producer"]["path"])
    frame = pd.read_parquet(path)
    frame.loc[frame.ts_code.eq(keys[1][0]) & frame.trade_date.eq(keys[1][1]), "bar_close_pos"] = np.nan
    frame.to_parquet(path, index=False)
    packet["producer"] = ref(path)
    if not flat:
        for channel in ("producer", "canonical", "raw", "enrichment"):
            path = Path(packet[channel]["path"])
            frame = pd.read_parquet(path)
            frame.loc[frame.ts_code.eq(keys[1][0]) & frame.trade_date.eq(keys[1][1]), "high"] += 1.0
            frame.to_parquet(path, index=False)
            packet[channel] = ref(path)
    approval = packet["review_receipt"]
    contract["structural_na"] = [{"field": "bar_close_pos", "keys": bound([list(keys[1])]),
                                    "reason": "Original high==low bar_close_pos policy", "review_receipt": approval}]
    if flat:
        receipt = v2_run(tmp_path, producer, monkeypatch, contract)
        frame = pd.read_parquet(receipt["artifacts"]["selector"]["path"])
        assert pd.isna(v2_exact_row(frame, keys[1])["bar_close_pos"])
    else:
        with pytest.raises(RuntimeError, match="flat-bar null policy"):
            v2_run(tmp_path, producer, monkeypatch, contract)


def test_v2_only_remaining_partition_computes_and_captures_one_canonical_call(tmp_path, producer, monkeypatch):
    contract, _old, keys = v2_fixture(tmp_path, producer)
    packet = contract["approved_generations"][0]
    packet["keys"] = bound([list(key) for key in keys[:2]])
    original_produced = pd.read_parquet(packet["producer"]["path"])
    original_canonical = pd.read_parquet(packet["canonical"]["path"])
    raw = pd.read_parquet(packet["raw"]["path"])
    raw = raw.loc[raw.ts_code.eq("000002.SZ")].copy()
    history = tmp_path / "v2_remaining_history.parquet"
    raw.to_parquet(history, index=False)
    event_path = tmp_path / "v2_remaining_events.parquet"
    pd.DataFrame({"ts_code": pd.Series(dtype=str)}).to_parquet(event_path, index=False)
    contract["remaining_generation"] = {"keys": bound([list(key) for key in keys[2:]]),
                                        "input_history": ref(history), "xdxr_events": ref(event_path)}
    canonical_calls, producer_calls = [], []
    def canonical(frame):
        canonical_calls.append(frame.copy())
        return original_canonical.loc[original_canonical.ts_code.eq("000002.SZ")].reset_index(drop=True)
    def compute(frame, *args, **kwargs):
        producer_calls.append((frame.copy(), kwargs))
        producer._compute_canonical_v192_formula(frame)
        return original_produced.loc[original_produced.ts_code.eq("000002.SZ")].reset_index(drop=True)
    monkeypatch.setattr(producer, "_compute_canonical_v192_formula", canonical)
    monkeypatch.setattr(producer, "compute_formula_features", compute)
    frozen = v2_bind(tmp_path, producer, contract)
    receipt = producer.run_same_day_revision_candidate(Path(frozen["path"]), frozen["sha256"])
    assert len(producer_calls) == len(canonical_calls) == 1
    assert set(producer_calls[0][0].ts_code) == {"000002.SZ"}
    assert producer_calls[0][1]["emit_all_rows"] is True
    assert receipt["approved_generation_keys"] == receipt["computed_generation_keys"] == 2
    evidence = [item for item in receipt["generation_evidence"] if not item["approved_reused"]]
    assert len(evidence) == 1
    for name in ("producer", "canonical", "enrichment"):
        assert file_sha(evidence[0]["sources"][name]["path"]) == evidence[0]["sources"][name]["sha256"]


def v6_transform(item):
    identity = {"schema": "V192_EXACT_ORDERED_KEY_TRANSFORM_V1", "source_key_sha256": item["source_key_sha256"],
                "delete_keys_sha256": item["approved_delete_keys"]["sha256"],
                "insert_keys_sha256": item["approved_insert_keys"]["sha256"],
                "order": "RETAIN_SOURCE_PHYSICAL_ORDER_THEN_SORTED_APPROVED_INSERTS"}
    return {**identity, "sha256": json_sha(identity)}


def v6_fixture(tmp_path, module):
    contract, old, keys = v2_fixture(tmp_path, module)
    delete_keys = [(keys[0][0], day) for day in (20260526, 20260527, 20260528, 20260529)]
    evidence_ref = dump(tmp_path / "v6_native_absence_review.json", {
        "status": "SYNTHETIC_NATIVE_ABSENCE_REVIEW", "keys": [list(key) for key in delete_keys]})
    for role, item in contract["roles"].items():
        path = Path(item["source"]["path"])
        table = pq.read_table(path)
        extra = []
        for code, day in delete_keys:
            row = table.slice(0, 1)
            for field, value in (("ts_code", code), ("trade_date", day)):
                row = row.set_column(row.schema.get_field_index(field), row.schema.field(field), pa.array([value], type=row.schema.field(field).type))
            extra.append(row)
        table = pa.concat_tables([table, *extra])
        pq.write_table(table, path, row_group_size=2)
        source_keys = [(str(code), int(day)) for code, day in table.select(["ts_code", "trade_date"]).to_pandas().itertuples(index=False, name=None)]
        item["source"] = ref(path)
        item["approved_delete_keys"] = bound([list(key) for key in delete_keys])
        item["approved_delete_evidence"] = [{"key": list(key), "policy": "APPROVED_NATIVE_ABSENT_SUSPENSION_CURRENT_REVISION",
                                             "reason": "Synthetic independently approved suspension-native absent source row",
                                             "review_receipt": evidence_ref, "native_absence_binding": evidence_ref}
                                            for key in delete_keys]
        item["expected_old_rows"] = table.num_rows
        item["source_key_sha256"] = v2_ordered_key_sha(source_keys)
        item["expected_new_key_sha256"] = None
        item["approved_key_transform"] = v6_transform(item)
        # Removing the four appended legacy-only rows restores the original
        # retained key order/count; the original fixture already binds +insert.
    return contract, old, keys, delete_keys


def v6_run(tmp_path, module, monkeypatch, contract, *, deletion_flag=True):
    frozen = v2_bind(tmp_path, module, contract)
    binding_path = Path(contract["input_binding_receipt"]["path"])
    binding = json.loads(binding_path.read_text())
    if deletion_flag is not None:
        binding["approved_deletions"] = deletion_flag
    contract["input_binding_receipt"] = dump(binding_path, binding)
    frozen = dump(Path(frozen["path"]), contract)
    monkeypatch.setattr(module, "compute_formula_features", lambda *a, **k: pytest.fail("accepted generations must not be recomputed"))
    return module.run_same_day_revision_candidate(Path(frozen["path"]), frozen["sha256"])


def test_v6_four_approved_native_absent_rows_removed_from_candidate_only(tmp_path, producer, monkeypatch):
    contract, old, _keys, deletes = v6_fixture(tmp_path, producer)
    source_sha = {role: item["source"]["sha256"] for role, item in contract["roles"].items()}
    receipt = v6_run(tmp_path, producer, monkeypatch, contract)
    for role in ("selector", "backtest"):
        artifact = receipt["artifacts"][role]
        result = pq.read_table(artifact["path"])
        actual_keys = {(str(code), int(day)) for code, day in result.select(["ts_code", "trade_date"]).to_pandas().itertuples(index=False, name=None)}
        assert not actual_keys.intersection(deletes)
        assert artifact["old_rows"] == old[role].num_rows + 4 and artifact["deleted_rows"] == 4
        assert artifact["rows"] == old[role].num_rows + 1
        retained_keys = [(str(code), int(day)) for code, day in old[role].select(["ts_code", "trade_date"]).to_pandas().itertuples(index=False, name=None)]
        expected_keys = retained_keys + [tuple(key) for key in contract["roles"][role]["approved_insert_keys"]["items"]]
        assert artifact["new_key_sha256"] == v2_ordered_key_sha(expected_keys)
        assert artifact["key_transform_sha256"] == contract["roles"][role]["approved_key_transform"]["sha256"]
        assert result.schema == old[role].schema
        assert result.column("untouched_integer").slice(0, old[role].num_rows).equals(old[role].column("untouched_integer"))
        assert result.slice(old[role].num_rows - 2, 2).equals(old[role].slice(old[role].num_rows - 2, 2))
        assert file_sha(contract["roles"][role]["source"]["path"]) == source_sha[role]
        assert file_sha(contract["roles"][role]["pointer"]["path"]) == contract["roles"][role]["pointer"]["sha256"]


@pytest.mark.parametrize("deletion_flag", [None, False])
def test_v6_deletion_needs_explicit_independent_full_input_approval(tmp_path, producer, monkeypatch, deletion_flag):
    contract, _old, _keys, _deletes = v6_fixture(tmp_path, producer)
    with pytest.raises(RuntimeError, match="input binder did not approve"):
        v6_run(tmp_path, producer, monkeypatch, contract, deletion_flag=deletion_flag)
    assert not (tmp_path / "v2_candidate").exists()


@pytest.mark.parametrize("defect", ["missing_reason", "missing_entry", "duplicate_entry", "unlisted_entry", "wrong_policy", "native_absence_identity_drift"])
def test_v6_exact_delete_reason_and_evidence_are_required(tmp_path, producer, monkeypatch, defect):
    contract, _old, _keys, _deletes = v6_fixture(tmp_path, producer)
    entries = contract["roles"]["selector"]["approved_delete_evidence"]
    if defect == "missing_reason":
        entries[0]["reason"] = " "
    elif defect == "missing_entry":
        entries.pop()
    elif defect == "duplicate_entry":
        entries.append(dict(entries[0]))
    elif defect == "unlisted_entry":
        entries[0]["key"] = ["000001.SZ", 20260525]
    elif defect == "wrong_policy":
        entries[0]["policy"] = "AUTOMATIC_MISSING_VALUE_DROP"
    else:
        entries[0]["native_absence_binding"] = {**entries[0]["native_absence_binding"], "sha256": "0" * 64}
    with pytest.raises(RuntimeError):
        v6_run(tmp_path, producer, monkeypatch, contract)
    assert not (tmp_path / "v2_candidate").exists()


@pytest.mark.parametrize("overlap", ["existing_update_keys", "approved_insert_keys"])
def test_v6_deletion_cannot_overlap_update_or_insert(tmp_path, producer, monkeypatch, overlap):
    contract, _old, _keys, _deletes = v6_fixture(tmp_path, producer)
    role = contract["roles"]["selector"]
    role["approved_delete_keys"] = bound([role[overlap]["items"][0]])
    with pytest.raises(RuntimeError, match="key partition"):
        v6_run(tmp_path, producer, monkeypatch, contract)


@pytest.mark.parametrize("defect", ["absent_key", "duplicate_source_key"])
def test_v6_deletion_requires_one_existing_source_row(tmp_path, producer, monkeypatch, defect):
    contract, _old, _keys, deletes = v6_fixture(tmp_path, producer)
    role = contract["roles"]["selector"]
    if defect == "absent_key":
        replacement = [deletes[0][0], 20260525]
        role["approved_delete_keys"] = bound([replacement] + [list(key) for key in deletes[1:]])
        role["approved_delete_evidence"][0]["key"] = replacement
        role["approved_key_transform"] = v6_transform(role)
    else:
        path = Path(role["source"]["path"])
        table = pq.read_table(path)
        table = pa.concat_tables([table, table.slice(table.num_rows - 1, 1)])
        pq.write_table(table, path, row_group_size=2)
        source_keys = [(str(code), int(day)) for code, day in table.select(["ts_code", "trade_date"]).to_pandas().itertuples(index=False, name=None)]
        role["source"] = ref(path)
        role["source_key_sha256"] = v2_ordered_key_sha(source_keys)
        role["expected_old_rows"] += 1
        role["expected_new_rows"] += 1
        role["approved_key_transform"] = v6_transform(role)
    with pytest.raises(RuntimeError, match="unique existing source row|exact update/delete/raw/source-key"):
        v6_run(tmp_path, producer, monkeypatch, contract)
    assert not (tmp_path / "v2_candidate" / "candidate_receipt.json").exists()


@pytest.mark.parametrize("defect", ["wrong_row_count", "wrong_transform_digest", "source_key_mismatch", "source_order_drift"])
def test_v6_deletion_count_and_retained_physical_order_are_bound(tmp_path, producer, monkeypatch, defect):
    contract, _old, _keys, _deletes = v6_fixture(tmp_path, producer)
    role = contract["roles"]["selector"]
    if defect == "wrong_row_count":
        role["expected_new_rows"] += 1
    elif defect == "wrong_transform_digest":
        role["approved_key_transform"]["sha256"] = "0" * 64
    elif defect == "source_key_mismatch":
        role["source_key_sha256"] = "0" * 64
        role["approved_key_transform"] = v6_transform(role)
    else:
        path = Path(role["source"]["path"])
        table = pq.read_table(path)
        table = table.take(pa.array(list(reversed(range(table.num_rows))), type=pa.int64()))
        pq.write_table(table, path)
        role["source"] = ref(path)
        # Keep the independently frozen old physical-key digest and transform.
    with pytest.raises(RuntimeError, match="expected row count|exact frozen key transform|exact update/delete/raw/source-key"):
        v6_run(tmp_path, producer, monkeypatch, contract)
    assert not (tmp_path / "v2_candidate" / "candidate_receipt.json").exists()


def test_v6_undeclared_native_absence_does_not_automatically_drop_old_rows(tmp_path, producer, monkeypatch):
    contract, _old, _keys, deletes = v6_fixture(tmp_path, producer)
    for role in contract["roles"].values():
        del role["approved_delete_keys"]
        del role["approved_delete_evidence"]
        del role["approved_key_transform"]
        table = pq.read_table(role["source"]["path"])
        source_keys = [(str(code), int(day)) for code, day in table.select(["ts_code", "trade_date"]).to_pandas().itertuples(index=False, name=None)]
        role["expected_new_rows"] = role["expected_old_rows"] + role["approved_insert_keys"]["count"]
        role["expected_new_key_sha256"] = v2_ordered_key_sha(source_keys + [tuple(key) for key in role["approved_insert_keys"]["items"]])
    receipt = v6_run(tmp_path, producer, monkeypatch, contract, deletion_flag=None)
    for role in ("selector", "backtest"):
        table = pq.read_table(receipt["artifacts"][role]["path"])
        actual = {(str(code), int(day)) for code, day in table.select(["ts_code", "trade_date"]).to_pandas().itertuples(index=False, name=None)}
        assert set(deletes) <= actual
        assert receipt["artifacts"][role]["deleted_rows"] == 0


@pytest.mark.parametrize("defect", ["missing_independent_verification", "wrong_new_key_digest"])
def test_v6_candidate_computed_digest_cannot_self_approve_deletion_publication(tmp_path, producer, monkeypatch, defect):
    contract, _old, _keys, _deletes = v6_fixture(tmp_path, producer)
    receipt = v6_run(tmp_path, producer, monkeypatch, contract)
    candidate_ref = ref(Path(contract["candidate_dir"]) / "candidate_receipt.json")
    review = {"decision": "PASS_SAME_DAY_PANEL_REVISION", "candidate_receipt_sha256": candidate_ref["sha256"],
              "producer_sha256": receipt["producer_sha256"], "reviewer_identity": "SYNTHETIC_INDEPENDENT_REVIEWER",
              "writer_identity": "SYNTHETIC_WRITER", "approved_delete_transform_verified": True,
              "approved_key_transforms": {role: {name: artifact[name] for name in ("key_transform_sha256", "new_key_sha256", "rows", "deleted_rows")}
                                          for role, artifact in receipt["artifacts"].items()}}
    if defect == "missing_independent_verification":
        del review["approved_delete_transform_verified"]
    else:
        review["approved_key_transforms"]["selector"]["new_key_sha256"] = "0" * 64
    owner = {"decision": "EXCLUSIVE_ORIGINAL_PRODUCER_PUBLISHER_CONFIRMED", "candidate_receipt_sha256": candidate_ref["sha256"],
             "legacy_publishers_excluded": True, "publisher_owner": "SYNTHETIC_OWNER",
             "valid_until": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}
    with pytest.raises(RuntimeError, match="independent review did not verify exact deletion"):
        producer.promote_same_day_revision(candidate_ref, dump(tmp_path / "v6_review.json", review), dump(tmp_path / "v6_owner.json", owner))
    for item in contract["roles"].values():
        assert file_sha(item["pointer"]["path"]) == item["pointer"]["sha256"]


@pytest.mark.parametrize("case", ["approved", "missing_receipt", "after_revision_cutoff", "other_static_field", "missing_revision_cutoff"])
def test_v6_name_observation_after_signal_needs_explicit_reviewed_nonpit_revision_boundary(tmp_path, producer, monkeypatch, case):
    contract, _old, keys = v2_fixture(tmp_path, producer)
    contract["runtime_binding"] = {"revision_observation_date": 20261021}
    path = Path(contract["static_rows"]["path"])
    rows = json.loads(path.read_text())
    row = rows["records"][0]
    row["value"] = "Current name actually observed on revision day"
    row["observed_date"] = 20261021
    row["observation_review_receipt"] = dump(tmp_path / "v6_name_review.json", {
        "status": "SYNTHETIC_CURRENT_REVISION_NON_PIT_NAME_REVIEW", "ts_code": row["ts_code"],
        "name": row["value"], "observed_date": row["observed_date"], "source": row["source"]})
    if case == "missing_receipt":
        del row["observation_review_receipt"]
    elif case == "after_revision_cutoff":
        row["observed_date"] = 20261022
    elif case == "other_static_field":
        row["field"] = "sector"
    elif case == "missing_revision_cutoff":
        del contract["runtime_binding"]["revision_observation_date"]
    contract["static_rows"] = dump(path, rows)
    if case == "approved":
        receipt = v2_run(tmp_path, producer, monkeypatch, contract)
        actual = pd.read_parquet(receipt["artifacts"]["selector"]["path"])
        assert v2_exact_row(actual, keys[1])["name"] == row["value"]
        assert receipt["revision_observation_date"] == row["observed_date"] == 20261021
        assert receipt["name_observation_status"] == "CURRENT_REVISION_NON_PIT"
        assert receipt["historical_name_pit_claimed"] is False
    else:
        with pytest.raises(RuntimeError, match="post-signal name observation needs frozen revision cutoff and independent receipt"):
            v2_run(tmp_path, producer, monkeypatch, contract)
        assert not (tmp_path / "v2_candidate" / "candidate_receipt.json").exists()
