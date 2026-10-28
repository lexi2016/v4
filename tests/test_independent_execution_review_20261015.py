"""Fail-closed independent execution review reader contract."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import importlib.util
from pathlib import Path
from pathlib import PurePosixPath
from zoneinfo import ZoneInfo

import pytest

from stage_center.execution_evidence import read_stage_execution
from stage_center.scheduler import evaluate_due
from infrastructure.owned_io import SafeRoot


def _automatic_fixture(tmp_path, monkeypatch):
    path = Path(__file__).with_name("test_automatic_execution_review_20261015.py")
    spec = importlib.util.spec_from_file_location("automatic_fixture_for_reader", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    fixture = module._fixture(tmp_path)
    monkeypatch.setenv("V35_DATA_ROOT", str(fixture["hk_d1_root"]))
    monkeypatch.delenv("V35_PRESELECTION_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("V35_MORNING_NEWS_DATA_ROOT", raising=False)
    module._verify(fixture)
    return module, fixture


@pytest.mark.parametrize("changed", ["snapshot", "d1", "wrong_root", "wrong_code_sha", "extra_inputs"])
def test_automatic_reader_revalidates_extra_sources_and_local_code(tmp_path, monkeypatch, changed):
    module, fixture = _automatic_fixture(tmp_path, monkeypatch)
    directory = fixture["receipt_root"] / "independent_execution_reviews" / module.DATE / module.STAGE
    if changed in {"snapshot", "d1"}:
        key = "active_snapshot" if changed == "snapshot" else "hk_d1"
        path = fixture["source_files"][key]
        value = json.loads(path.read_bytes())
        value["trade_date"] = "20990101"
        path.write_bytes(_canonical(value))
    elif changed == "wrong_root":
        other_root = tmp_path / "unrelated-data"
        other_root.mkdir()
        monkeypatch.setenv("V35_DATA_ROOT", str(other_root))
    else:
        path = directory / "attestation.json"
        attestation = json.loads(path.read_bytes())
        if changed == "wrong_code_sha":
            attestation["reviewer_verifier_code_sha256"] = "0" * 64
        else:
            attestation["execution_inputs"]["source_reconciliation"]["source_rows"] = 999
        raw = _canonical(attestation)
        path.write_bytes(raw)
        index_path = directory / "index.json"
        index = json.loads(index_path.read_bytes()); index["attestation_sha256"] = _sha(raw)
        index_path.write_bytes(_canonical(index))
    current = read_stage_execution(fixture["receipt_root"], module.DATE, module.STAGE,
        {"HK_CONNECT": fixture["lane"]}, selection_store=fixture["selection_store"])
    assert current["independent_execution_review"]["status"] == "CANNOT_CONFIRM"
    assert current["operating_execution_by_market"]["HK_CONNECT"]["execution_verified"] is False


def test_automatic_readonly_validator_never_publishes_or_writes(tmp_path, monkeypatch):
    module, fixture = _automatic_fixture(tmp_path, monkeypatch)
    from ops.verify_stage_execution import validate_execution_inputs
    before = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
              for path in tmp_path.rglob("*") if path.is_file()}
    validate_execution_inputs(trade_date=module.DATE, stage_id=module.STAGE,
        receipt_root=fixture["receipt_root"], raw_root=fixture["raw_root"],
        selection_root=fixture["selection_root"], hk_d1_root=fixture["hk_d1_root"],
        expected_receipt_sha256=_sha(fixture["receipt_raw"]))
    after = {str(path): (path.read_bytes(), path.stat().st_mtime_ns)
             for path in tmp_path.rglob("*") if path.is_file()}
    assert before == after


DATE = "20261014"
ORDINARY_STAGE = "STAGE_0945_1030"
HK_ONLY_STAGE = "STAGE_1545_1555"
SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _write_test_receipt(payload, receipt_root, selection_store, trade_date, stage_id):
    """Create fixture-only owner-history and selection references in tmp_path."""
    result = dict(payload)
    result.pop("receipt_history", None)
    result["recorded_at"] = "2026-10-14T03:00:00+00:00"
    result["record_time_source"] = "OWNER_WRITE_CLOCK_UTC"
    result["selection_artifacts"] = {}
    for market, lane in (result.get("markets") or {}).items():
        verified = selection_store._verify_run(trade_date, stage_id, market, lane["run_id"])
        parent = PurePosixPath(verified["artifact_relative"]).parent
        paths = {
            "artifact_relative": verified["artifact_relative"],
            "manifest_relative": str(parent / "manifest.json"),
            "receipt_relative": str(parent / "receipt.json"),
        }
        raw = {key: SafeRoot(selection_store.root).read_bytes(path) for key, path in paths.items()}
        hashes = {
            "artifact_bytes_sha256": _sha(raw["artifact_relative"]),
            "manifest_bytes_sha256": _sha(raw["manifest_relative"]),
            "receipt_bytes_sha256": _sha(raw["receipt_relative"]),
            "manifest_canonical_sha256": _sha(_canonical(json.loads(raw["manifest_relative"]))),
            "receipt_canonical_sha256": _sha(_canonical(json.loads(raw["receipt_relative"]))),
        }
        result["selection_artifacts"][market] = {
            "schema_version": "stage_center.runner.selection_binding.v1",
            **{key: lane[key] for key in ("run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256", "selected_rows")},
            **paths, **hashes, "trade_date": trade_date, "stage_id": stage_id, "market": market,
        }
    history_raw = _canonical(result)
    history_sha = _sha(history_raw)
    history_relative = f"{trade_date}/{stage_id}/attempt_evidence/recorded-{history_sha}/RECEIPT.json"
    SafeRoot(receipt_root).write_bytes(history_relative, history_raw, require_absent=True)
    result["receipt_history"] = {
        "schema_version": "stage_center.runner.history_ref.v1",
        "relative_path": history_relative,
        "sha256": history_sha,
    }
    return result


def _fixture(tmp_path: Path, *, stage_id: str = ORDINARY_STAGE,
             dispatch_mode: str = "NATURAL", execution_origin: str | None = None,
             mode: str | None = None, attempt_count: int = 1):
    from stage_center.selection import SelectionStore, select_hk_four_lane

    source_path = tmp_path / "source" / "minute-input.csv"
    source_path.parent.mkdir(parents=True)
    source_raw = b"fixture-only source bytes\n"
    source_path.write_bytes(source_raw)
    source_sha = _sha(source_raw)
    cutoff = "2026-10-14T10:30:00+08:00" if stage_id == ORDINARY_STAGE else "2026-10-14T15:55:05+08:00"
    semantics = "only observations in the scheduled stage window; exclude observations at or after cutoff"
    evidence = [
        "route=fixture_minute_source",
        f"source_path={source_path}",
        f"source_sha256={source_sha}",
        f"source_cutoff={cutoff}",
        f"source_temporal_semantics={semantics}",
    ]
    selection_store = SelectionStore(tmp_path / "selection")
    result = select_hk_four_lane(
        [dict(code="HK.00001", last_price=11, prev_close_price=10,
              turnover=1_000_000, volume_ratio=1.5)],
        DATE, stage_id, source_sha, source_evidence=evidence,
    )
    selection_store.publish(result, market="HK_CONNECT")
    lane = selection_store.read_verified(DATE, stage_id, "HK_CONNECT")
    lane["status"] = lane["selection_status"]

    if stage_id == ORDINARY_STAGE:
        evaluated_at = "2026-10-14T10:30:02.100000+08:00"
        observed_at = "2026-10-14T10:30:04.200000+08:00"
    else:
        evaluated_at = "2026-10-14T15:55:05.100000+08:00"
        observed_at = "2026-10-14T15:55:08.200000+08:00"
    attempt_id = "a" * 32
    attempt_relative = f"{DATE}/{stage_id}/attempt_evidence/{attempt_id}/001_START.json"
    attempt_path = tmp_path / "receipts" / attempt_relative
    attempt_path.parent.mkdir(parents=True)
    attempt = {
        "schema": "stage.attempt_diagnostic.v1", "event": "START",
        "attempt_id": attempt_id, "trade_date": DATE, "stage_id": stage_id,
        "attempt_number": 1, "evaluated_at": evaluated_at, "observed_at": observed_at,
    }
    attempt_raw = json.dumps(attempt, sort_keys=True).encode("utf-8")
    attempt_path.write_bytes(attempt_raw)

    payload = {
        "schema_version": "stage_center.runner.receipt.v1",
        "runner": "stage_center",
        "trade_date": DATE, "stage_id": stage_id,
        "dispatch_mode": dispatch_mode, "due_status": "DUE",
        "execution_origin": execution_origin,
        "mode": mode,
        "node_attempt_count": attempt_count,
        "attempt_diagnostic": {
            "schema": "stage.attempt_diagnostic_summary.v1",
            "attempt_id": attempt_id,
            "relative_paths": [f"attempt_evidence/{attempt_id}/001_START.json"],
        },
        "status": "PARTIAL_WITH_ROWS",
        **SAFETY,
        "markets": {"HK_CONNECT": lane},
    }
    receipt_root = tmp_path / "receipts"
    receipt = _write_test_receipt(payload, receipt_root, selection_store, DATE, stage_id)
    receipt_path = receipt_root / DATE / stage_id / "receipt.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    receipt_path.write_bytes(receipt_raw)
    context = {"HK_CONNECT": lane}
    baseline = read_stage_execution(
        receipt_root, DATE, stage_id, context,
        selection_store=selection_store,
    )
    return {
        "root": receipt_root,
        "selection_store": selection_store,
        "lane": lane,
        "source_path": source_path,
        "source_sha": source_sha,
        "source_cutoff": cutoff,
        "source_semantics": semantics,
        "source_evidence": evidence,
        "attempt": attempt,
        "attempt_raw": attempt_raw,
        "attempt_relative": attempt_relative,
        "attempt_id": attempt_id,
        "receipt": receipt,
        "payload": payload,
        "context": context,
        "baseline": baseline,
        "stage_id": stage_id,
    }


def _review_artifact(fixture, scope_markets=("HK_CONNECT",)):
    stage_id = fixture["stage_id"]
    receipt = fixture["receipt"]
    attempt = fixture["attempt"]
    evaluated = datetime.fromisoformat(attempt["evaluated_at"]).astimezone(ZoneInfo("Asia/Shanghai"))
    observed = datetime.fromisoformat(attempt["observed_at"]).astimezone(ZoneInfo("Asia/Shanghai"))
    due = evaluate_due(stage_id, DATE, evaluated)
    scope = list(scope_markets)
    lane = fixture["lane"]
    source_entries = list(lane["source_evidence"])
    source = {
        "identity": "fixture_minute_source",
        "path": str(fixture["source_path"]),
        "sha256": fixture["source_sha"],
        "cutoff": fixture["source_cutoff"],
        "temporal_semantics": fixture["source_semantics"],
        "evidence_entries": fixture["source_evidence"],
    }
    selection = fixture["baseline"]["selection_artifact_bindings"]["HK_CONNECT"]
    selection = {key: selection[key] for key in (
        "artifact_relative", "manifest_relative", "receipt_relative", "run_id",
        "artifact_bytes_sha256", "manifest_bytes_sha256", "receipt_bytes_sha256",
        "manifest_canonical_sha256", "receipt_canonical_sha256",
    )}
    attestation = {
        "schema_version": "stage_center.independent_execution_review.v1",
        "trade_date": DATE, "stage_id": stage_id, "runner": "stage_center",
        "scope_markets": scope,
        "reviewer_identity_or_role": "independent-reviewer-fixture",
        "reviewer_verifier_code_sha256": "c" * 64,
        "reviewed_at_utc": "2026-10-14T04:00:00Z",
        "runner_receipt": {
            "relative_path": f"{DATE}/{stage_id}/receipt.json",
            "sha256": fixture["baseline"]["observed_sha256"],
        },
        "owner_history": {
            "relative_path": receipt["receipt_history"]["relative_path"],
            "sha256": receipt["receipt_history"]["sha256"],
        },
        "markets": {
            "HK_CONNECT": {
                "selection": selection,
                "source_binding": {
                    "source_evidence_sha256": _sha(_canonical(source_entries)),
                    "sources": [source],
                },
            },
        },
        "dispatch": {
            "mode": receipt["dispatch_mode"], "due_status": receipt["due_status"],
            "attempt_id": fixture["attempt_id"], "attempt_count": 1,
            "attempt_relative_path": fixture["attempt_relative"],
            "attempt_sha256": _sha(fixture["attempt_raw"]),
            "scheduled_at_local": due.scheduled_at.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
            "evaluated_at_local": evaluated.isoformat(),
            "observed_at_local": observed.isoformat(),
        },
        "safety": dict(SAFETY),
    }
    return attestation


def _publish_review(fixture, attestation):
    directory = fixture["root"] / "independent_execution_reviews" / DATE / fixture["stage_id"]
    directory.mkdir(parents=True)
    attestation_raw = json.dumps(attestation, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (directory / "attestation.json").write_bytes(attestation_raw)
    index = {
        "schema_version": "stage_center.independent_execution_review_index.v1",
        "trade_date": DATE, "stage_id": fixture["stage_id"],
        "attestation_relative_path": f"independent_execution_reviews/{DATE}/{fixture['stage_id']}/attestation.json",
        "attestation_sha256": _sha(attestation_raw),
    }
    (directory / "index.json").write_bytes(json.dumps(index, sort_keys=True, separators=(",", ":")).encode())


def _read(fixture):
    return read_stage_execution(
        fixture["root"], DATE, fixture["stage_id"], fixture["context"],
        selection_store=fixture["selection_store"],
    )


def test_missing_independent_index_keeps_natural_and_execution_false(tmp_path):
    fixture = _fixture(tmp_path)
    result = fixture["baseline"]
    assert result["execution_verified"] is False
    assert result["natural_verified"] is False
    assert result["independent_execution_review"]["status"] == "CANNOT_CONFIRM"
    assert "NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING" in result["cannot_confirm"]
    assert result["operating_execution_by_market"]["HK_CONNECT"]["natural_verified"] is False


def test_hk_only_review_is_scoped_and_does_not_promote_ordinary_stage_aggregate(tmp_path):
    fixture = _fixture(tmp_path, stage_id=ORDINARY_STAGE)
    _publish_review(fixture, _review_artifact(fixture, ("HK_CONNECT",)))
    result = _read(fixture)
    assert result["operating_execution_by_market"]["HK_CONNECT"]["natural_verified"] is True
    assert result["operating_execution_by_market"]["HK_CONNECT"]["scope_markets"] == ["HK_CONNECT"]
    assert result["operating_execution_by_market"]["A_SHARE"]["natural_verified"] is False
    assert result["execution_verified"] is False
    assert result["natural_verified"] is False
    assert "AGGREGATE_EXECUTION_SCOPE_NOT_COVERED" in result["cannot_confirm"]


def test_single_market_stage_can_verify_its_complete_natural_scope(tmp_path):
    fixture = _fixture(tmp_path, stage_id=HK_ONLY_STAGE)
    _publish_review(fixture, _review_artifact(fixture, ("HK_CONNECT",)))
    result = _read(fixture)
    assert result["execution_verified"] is True
    assert result["natural_verified"] is True
    assert result["status"] == "INDEPENDENT_NATURAL_EXECUTION_VERIFIED"
    assert "NO_INDEPENDENT_RUN_RECEIPT_SHA_BINDING" not in result["cannot_confirm"]


def test_missing_receipt_research_only_flag_fails_closed_even_with_hk_only_review(tmp_path):
    fixture = _fixture(tmp_path)
    receipt = dict(fixture["receipt"])
    receipt.pop("RESEARCH_ONLY")

    archived = {key: value for key, value in receipt.items() if key != "receipt_history"}
    history_raw = _canonical(archived)
    history_sha = _sha(history_raw)
    history_relative = f"{DATE}/{fixture['stage_id']}/attempt_evidence/recorded-{history_sha}/RECEIPT.json"
    SafeRoot(fixture["root"]).write_bytes(history_relative, history_raw, require_absent=True)
    receipt["receipt_history"] = {
        "schema_version": "stage_center.runner.history_ref.v1",
        "relative_path": history_relative,
        "sha256": history_sha,
    }
    receipt_path = fixture["root"] / DATE / fixture["stage_id"] / "receipt.json"
    receipt_path.write_bytes(json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n")
    fixture["receipt"] = receipt
    fixture["baseline"] = read_stage_execution(
        fixture["root"], DATE, fixture["stage_id"], fixture["context"],
        selection_store=fixture["selection_store"],
    )

    _publish_review(fixture, _review_artifact(fixture, ("HK_CONNECT",)))
    result = _read(fixture)

    assert result["operating_execution_by_market"]["HK_CONNECT"]["natural_verified"] is False
    assert result["independent_execution_review"]["status"] == "CANNOT_CONFIRM"
    assert "CURRENT_RECEIPT_RESEARCH_ONLY_MISSING" in result["independent_execution_review"]["cannot_confirm"]


@pytest.mark.parametrize(("mutation", "reason"), [
    ("receipt_sha", "INDEPENDENT_RUNNER_RECEIPT_SHA_MISMATCH"),
    ("date", "INDEPENDENT_REVIEW_IDENTITY_MISMATCH"),
    ("market", "INDEPENDENT_REVIEW_MARKET_BINDINGS_MISMATCH"),
    ("history_sha", "INDEPENDENT_OWNER_HISTORY_SHA_MISMATCH"),
    ("source_sha", "SOURCE_SHA_NOT_IN_CURRENT_SELECTION_EVIDENCE"),
    ("clock", "INDEPENDENT_DISPATCH_OR_CLOCK_BINDING_MISMATCH"),
    ("safety", "INDEPENDENT_REVIEW_SAFETY_FLAGS_INVALID"),
])
def test_invalid_review_bindings_fail_closed(tmp_path, mutation, reason):
    fixture = _fixture(tmp_path)
    attestation = _review_artifact(fixture)
    if mutation == "receipt_sha":
        attestation["runner_receipt"]["sha256"] = "f" * 64
    elif mutation == "date":
        attestation["trade_date"] = "20261013"
    elif mutation == "market":
        attestation["scope_markets"] = ["A_SHARE"]
    elif mutation == "history_sha":
        attestation["owner_history"]["sha256"] = "e" * 64
    elif mutation == "source_sha":
        attestation["markets"]["HK_CONNECT"]["source_binding"]["sources"][0]["sha256"] = "f" * 64
    elif mutation == "clock":
        attestation["dispatch"]["observed_at_local"] = "2026-10-14T10:31:04.200000+08:00"
    elif mutation == "safety":
        attestation["safety"]["production_allowed"] = True
    _publish_review(fixture, attestation)
    result = _read(fixture)
    assert result["execution_verified"] is False
    assert result["natural_verified"] is False
    assert reason in result["independent_execution_review"]["cannot_confirm"]


@pytest.mark.parametrize(("dispatch_mode", "execution_origin", "mode", "attempt_count"), [
    ("MANUAL", None, None, 1),
    ("NATURAL", "HISTORICAL_BACKFILL", None, 1),
    ("NATURAL", None, "BACKFILL", 1),
    ("NATURAL", None, None, 2),
])
def test_manual_replay_backfill_or_repeated_attempt_cannot_verify_natural(
    tmp_path, dispatch_mode, execution_origin, mode, attempt_count,
):
    fixture = _fixture(tmp_path, dispatch_mode=dispatch_mode,
                       execution_origin=execution_origin, mode=mode,
                       attempt_count=attempt_count)
    _publish_review(fixture, _review_artifact(fixture))
    result = _read(fixture)
    assert result["execution_verified"] is False
    assert result["natural_verified"] is False
    assert "CURRENT_RUN_NOT_SINGLE_ATTEMPT_NATURAL_DUE" in result["independent_execution_review"]["cannot_confirm"]


def test_source_bytes_changed_after_review_fail_closed(tmp_path):
    fixture = _fixture(tmp_path)
    _publish_review(fixture, _review_artifact(fixture))
    fixture["source_path"].write_bytes(b"changed after independent review")
    result = _read(fixture)
    assert result["execution_verified"] is False
    assert result["natural_verified"] is False
    assert "CURRENT_SOURCE_BYTES_SHA_MISMATCH" in result["independent_execution_review"]["cannot_confirm"]


def test_attestation_path_is_date_and_stage_derived_and_symlinks_fail_closed(tmp_path):
    fixture = _fixture(tmp_path)
    directory = fixture["root"] / "independent_execution_reviews" / DATE / fixture["stage_id"]
    directory.mkdir(parents=True)
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    (directory / "index.json").symlink_to(outside)
    result = _read(fixture)
    assert result["execution_verified"] is False
    assert result["natural_verified"] is False
    assert "INDEPENDENT_REVIEW_PATH_OR_SIZE_REFUSED" in result["independent_execution_review"]["cannot_confirm"]


@pytest.mark.parametrize("case", ["reviewed_R2", "current_R3", "unknown_code", "wrong_code", "changed_input", "changed_source_bytes", "failed_proof", "changed_local_code"])
def test_reviewed_R2_record_compatibility_keeps_all_current_validation(tmp_path, monkeypatch, case):
    module, fixture = _automatic_fixture(tmp_path, monkeypatch)
    from ops import verify_stage_execution as verifier
    directory = fixture["receipt_root"] / "independent_execution_reviews" / module.DATE / module.STAGE
    path = directory / "attestation.json"; attestation = json.loads(path.read_bytes())
    assert _sha(Path(verifier.__file__).read_bytes()) == "32872ffd4f99ca774252d238d38033c39b3dd0ab9b449a69c2dd35fddc556fc5"
    if case != "current_R3":
        attestation["reviewer_verifier_code_sha256"] = "49a36c3725b8ee2546bc0fdc2044790386da152044053cb10c0750d199f0a7ae"
    if case == "unknown_code": attestation["reviewer_verifier_code_sha256"] = "1" * 64
    elif case == "wrong_code": attestation["reviewer_verifier_code_sha256"] = "not-a-sha"
    elif case == "changed_input": attestation["execution_inputs"]["source_reconciliation"]["source_rows"] = 999
    elif case == "failed_proof": attestation["markets"]["HK_CONNECT"]["operation_status"] = "CANNOT_CONFIRM"
    raw = _canonical(attestation);path.write_bytes(raw)
    index_path = directory / "index.json"; index = json.loads(index_path.read_bytes());index["attestation_sha256"] = _sha(raw);index_path.write_bytes(_canonical(index))
    if case == "changed_source_bytes":
        snapshot_path = fixture["source_files"]["active_snapshot"]
        snapshot = json.loads(snapshot_path.read_bytes()); snapshot["trade_date"] = "20990101"
        snapshot_path.write_bytes(_canonical(snapshot))
    if case == "changed_local_code":
        original = Path.read_bytes; verifier_path = Path(verifier.__file__).resolve()
        monkeypatch.setattr(Path, "read_bytes", lambda self: b"changed local verifier" if self.resolve() == verifier_path else original(self))
    current = read_stage_execution(fixture["receipt_root"], module.DATE, module.STAGE,
        {"HK_CONNECT": fixture["lane"]}, selection_store=fixture["selection_store"])
    verified = current["operating_execution_by_market"]["HK_CONNECT"]["execution_verified"]
    assert verified is (case in {"reviewed_R2", "current_R3"})
    assert current["execution_verified"] is False  # HK scope never promotes mixed A/HK aggregate
    assert current["natural_verified"] is False
    if not verified:
        assert current["independent_execution_review"]["status"] == "CANNOT_CONFIRM"
