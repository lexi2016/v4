from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from domains import d1_review_lane_producer as lane
from domains import d1_review_source_producer as source
from infrastructure.formula_generation import read_selector_source_binding
from ops import materialize_d1_review_lanes as materializer
from ops import research_panel_logical as logical
from stage_center.raw_store import RawStore, canonical_sha


DAY = "20261118"
TARGET = "20261119"
RAW_SHA = "a" * 64
RECEIPT_SHA = "c" * 64
SELECTION_MANIFEST_SHA = "d" * 64
SELECTION_RECEIPT_SHA = "e" * 64
SELECTION_ARTIFACT_SHA = "f" * 64
ALGORITHM_SHA = "1" * 64


def test_fupan_only_receipt_hashes_only_emitted_source_files(tmp_path: Path) -> None:
    paths = {key: tmp_path / f"{key}.csv" for key in (
        "anchor_role", "theme_stocks", "prior_plan", "intraday_handoff", "stage7_tail_replay",
    )}
    for key, path in paths.items():
        if key != "stage7_tail_replay":
            path.write_text(key, encoding="utf-8")
    emitted = source._emitted_outputs(paths, fupan_only=True)
    assert set(emitted) == {"anchor_role", "theme_stocks", "prior_plan", "intraday_handoff"}
    with pytest.raises(FileNotFoundError):
        source._emitted_outputs(paths, fupan_only=False)
    paths["stage7_tail_replay"].write_text("", encoding="utf-8")
    assert set(source._emitted_outputs(paths, fupan_only=False)) == set(paths)


def test_920_stock_keeps_beijing_identity_through_stage7_materializers(tmp_path: Path) -> None:
    stage7 = source._build_stage7_tail(
        {"STAGE_1445_1500": {"rows": {"A": [{"code": "920592", "name": "华信永道", "pool_rank": 1}]}}},
        DAY,
    )
    assert stage7[0]["ts_code"] == "920592.BJ"
    replay = tmp_path / "stage7_tail_replay.csv"
    source._write_csv(replay, stage7)
    replay_manifest = tmp_path / "stage7_tail_replay.manifest.json"
    replay_manifest.write_text(json.dumps({"source_role": "real_d1_stage7_tail_replay"}), encoding="utf-8")
    lane_rows, _manifest = lane._build_real_stage7_rows(
        target_date=TARGET,
        signal_date=DAY,
        path=replay,
        manifest_path=replay_manifest,
    )
    assert lane_rows[0]["ts_code"] == "920592.BJ"
    assert lane._market_suffix("920592.BJ") == ".BJ"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _selector_fixture(tmp_path: Path, *, day: str = DAY, logical_panel: bool) -> Path:
    directory = tmp_path / ("logical" if logical_panel else "physical")
    directory.mkdir()
    table = pa.table({
        "trade_date": [int(day) - 1, int(day), int(day)],
        "ts_code": ["600000.SH", "000001.SZ", "600000.SH"],
        "name": ["前一日", "平安银行", "浦发银行"],
        "pct_chg": [0.0, 1.25, -0.5],
        "amount": [100.0, 200.0, 300.0],
    })
    block = directory / "block.parquet"
    pq.write_table(table, block)
    snapshot = directory / "snapshot.json"
    snapshot.write_text(json.dumps({"asof_date": int(day)}), encoding="utf-8")
    panel = directory / "selector.parquet"
    receipt = directory / "generation.json"
    metadata = {
        b"a_share_qfq_contract_v1": json.dumps({
            "asof_date": int(day),
            "generation_id": "a" * 64,
            "input_sha256": "b" * 64,
            "generation_manifest_path": str(receipt),
            "snapshot_file_sha256": _sha(snapshot),
        }).encode(),
    }
    schema = table.schema.with_metadata(metadata)
    if logical_panel:
        panel.write_bytes(logical.anchor_bytes(schema, [logical.descriptor(block)], rows=table.num_rows))
    else:
        pq.write_table(table.replace_schema_metadata(metadata), panel)
    receipt.write_text(json.dumps({
        "status": "CANDIDATE_READY",
        "target_date": int(day),
        "generation_id": "a" * 64,
        "input_sha256": "b" * 64,
        "candidates": {"selector": str(panel)},
        "candidate_sha256": {"selector": _sha(panel)},
        "adjustment_snapshot": {"path": str(snapshot), "sha256": _sha(snapshot)},
    }), encoding="utf-8")
    return panel


@pytest.mark.parametrize("logical_panel", [True, False])
def test_selector_reader_binds_generation_and_reads_exact_day(tmp_path: Path, logical_panel: bool) -> None:
    panel = _selector_fixture(tmp_path, logical_panel=logical_panel)
    rows, bound = materializer._selector_rows(panel, DAY)
    binding = read_selector_source_binding(panel, expected_signal_date=DAY)
    assert len(rows) == 2
    assert {str(row["trade_date"]) for row in rows} == {DAY}
    assert binding["generation_id"] == "a" * 64
    assert binding["signal_date"] == DAY
    assert bound == binding


@pytest.mark.parametrize("logical_panel", [True, False])
def test_selector_reader_fails_closed_if_panel_changes_during_read(tmp_path: Path, monkeypatch, logical_panel: bool) -> None:
    panel = _selector_fixture(tmp_path, logical_panel=logical_panel)
    original_read_table = materializer.parquet.read_table

    def replace_after_read(path, *args, **kwargs):
        table = original_read_table(path, *args, **kwargs)
        Path(path).write_bytes(Path(path).read_bytes() + b"drift")
        return table

    monkeypatch.setattr(materializer.parquet, "read_table", replace_after_read)
    with pytest.raises(ValueError, match="SELECTOR_SOURCE_SHA_CHANGED_DURING_READ"):
        materializer._selector_rows(panel, DAY)


def _stage7_inputs(tmp_path: Path) -> tuple[dict, Path, dict, dict]:
    selection_root = tmp_path / "state" / "stage" / "selection"
    receipt_root = selection_root.parent / "receipts"
    raw_root = selection_root.parent / "raw"
    receipt_path = receipt_root / DAY / "STAGE_1445_1500" / "receipt.json"
    history_path = receipt_path.parent / "attempt_evidence" / "verified" / "RECEIPT.json"
    history_path.parent.mkdir(parents=True)
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.parent.mkdir(parents=True, exist_ok=True)

    selection_binding = {
        "schema_version": "stage_center.runner.selection_binding.v1",
        "trade_date": DAY,
        "stage_id": "STAGE_1445_1500",
        "market": "A_SHARE",
        "artifact_id": "selection-valid",
        "run_id": "run-valid",
        "algorithm_sha256": ALGORITHM_SHA,
        "raw_artifact_sha256": RAW_SHA,
        "selected_rows": 2,
        "manifest_canonical_sha256": SELECTION_MANIFEST_SHA,
        "receipt_canonical_sha256": SELECTION_RECEIPT_SHA,
        "artifact_bytes_sha256": SELECTION_ARTIFACT_SHA,
    }
    a_market = {
        "trade_date": DAY,
        "stage_id": "STAGE_1445_1500",
        "status": "PARTIAL_WITH_ROWS",
        "selection_status": "PARTIAL_WITH_ROWS",
        "artifact_id": "selection-valid",
        "run_id": "run-valid",
        "algorithm_sha256": ALGORITHM_SHA,
        "raw_artifact_sha256": RAW_SHA,
        "selection_manifest_sha256": SELECTION_MANIFEST_SHA,
        "selection_receipt_sha256": SELECTION_RECEIPT_SHA,
        "selection_artifact_sha256": SELECTION_ARTIFACT_SHA,
        "selection_manifest_receipt_verified": True,
        "source_status": "READY",
        "source_rows": 318,
        "selected_rows": 2,
        "rows": [{"code": "000001", "rank": 1}, {"code": "600000", "rank": 2}],
        # A backfill substring in an upstream release-id note is not a run mode.
        "source_evidence": ["natural_stage_observation=true", "v4_research_owner_release_id=v4-d17-official-tail-backfill-20261117-r2-main"],
        # Non-core field gaps keep the selection partial but do not invalidate
        # a fully witnessed Stage7 observation.
        "cannot_confirm": ["MORNING_NEWS_SCORE_MISSING:A.000001"],
        "selection_mode": "NATURAL",
    }
    selection = {"status": "PARTIAL_WITH_ROWS", "trade_date": DAY,
                 "stage_id": "STAGE_1445_1500", "markets": {"A_SHARE": a_market}}
    market_receipt = {
        "trade_date": DAY,
        "stage_id": "STAGE_1445_1500",
        "selection_status": "PARTIAL_WITH_ROWS",
        "artifact_id": "selection-valid",
        "run_id": "run-valid",
        "algorithm_sha256": ALGORITHM_SHA,
        "raw_artifact_sha256": RAW_SHA,
        "selected_rows": 2,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    owner_receipt = {
        "schema_version": "stage_center.runner.receipt.v1",
        "runner": "stage_center",
        "trade_date": DAY,
        "stage_id": "STAGE_1445_1500",
        "node_id": "STAGE_1445_1500",
        "dispatch_mode": "NATURAL",
        "due_status": "DUE",
        "node_outcome": "SETTLED_PARTIAL",
        "write_performed": True,
        "record_time_source": "OWNER_WRITE_CLOCK_UTC",
        "status": "PARTIAL_WITH_ROWS",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "markets": {"A_SHARE": market_receipt},
        "selection_artifacts": {"A_SHARE": selection_binding},
    }
    history_payload = dict(owner_receipt)
    history_bytes = json.dumps(history_payload, sort_keys=True).encode()
    history_path.write_bytes(history_bytes)
    owner_receipt["receipt_history"] = {
        "schema_version": "stage_center.runner.history_ref.v1",
        "relative_path": str(history_path.relative_to(receipt_root)),
        "sha256": hashlib.sha256(history_bytes).hexdigest(),
    }
    receipt_path.write_text(json.dumps(owner_receipt), encoding="utf-8")

    raw_manifest_path = raw_root / "runs" / DAY / "stage7" / "manifest.json"
    raw_manifest_path.parent.mkdir(parents=True)
    raw_manifest = {
        "status": "READY",
        "trade_date": DAY,
        "stage_id": "STAGE_1445_1500",
        "market": "A_SHARE",
        "temporal_cutoff_safe": True,
    }
    raw_manifest_path.write_text(json.dumps(raw_manifest), encoding="utf-8")
    verified = {
        "status": "READY",
        "run_id": "raw-valid",
        "artifact_sha256": RAW_SHA,
        "manifest_sha256": canonical_sha(raw_manifest),
        "receipt_sha256": RECEIPT_SHA,
        "manifest_relative": str(raw_manifest_path.relative_to(raw_root)),
        "row_count": 318,
        "window": "14:45-15:00",
        "cutoff_at": "15:00:00",
        "cannot_confirm": [],
    }
    latest = {"status": "READY", "artifact_sha256": RAW_SHA}
    return selection, selection_root, {"latest": latest, "verified": verified}, owner_receipt


def test_stage7_gate_allows_verified_natural_partial_for_optional_gaps(tmp_path: Path, monkeypatch) -> None:
    selection, selection_root, raw_result, _receipt = _stage7_inputs(tmp_path)
    monkeypatch.setattr(RawStore, "verify_latest", lambda self, *args: raw_result)
    witness = materializer._stage7_observation_witness(selection, DAY, selection_root)
    assert witness["eligible"] is True
    assert witness["status"] == "VERIFIED_NATURAL_STAGE7_OBSERVATION"
    assert witness["selection_status"] == "PARTIAL_WITH_ROWS"
    assert witness["raw_temporal_cutoff_safe"] is True


@pytest.mark.parametrize(
    ("invalid", "expected_reason"),
    [
        ("owner_root", "STAGE7_OWNER_RECEIPT_ROOT_INVALID"),
        ("history_root", "STAGE7_OWNER_HISTORY_RECEIPT_ROOT_INVALID"),
        ("owner_markets", "STAGE7_OWNER_MARKETS_SHAPE_INVALID"),
        ("history_markets", "STAGE7_OWNER_HISTORY_MARKETS_SHAPE_INVALID"),
        ("owner_selection_artifacts", "STAGE7_OWNER_SELECTION_ARTIFACTS_SHAPE_INVALID"),
        ("history_selection_artifacts", "STAGE7_OWNER_HISTORY_SELECTION_ARTIFACTS_SHAPE_INVALID"),
    ],
)
def test_malformed_owner_history_degrades_only_stage7(
    tmp_path: Path, monkeypatch, invalid: str, expected_reason: str,
) -> None:
    selection, selection_root, raw_result, _receipt = _stage7_inputs(tmp_path)
    receipt_root = selection_root.parent / "receipts"
    receipt_path = receipt_root / DAY / "STAGE_1445_1500" / "receipt.json"
    outer = json.loads(receipt_path.read_text(encoding="utf-8"))
    history_ref = outer["receipt_history"]
    history_path = receipt_root / history_ref["relative_path"]
    history = json.loads(history_path.read_text(encoding="utf-8"))

    if invalid == "owner_root":
        receipt_path.write_text("[]", encoding="utf-8")
    elif invalid == "history_root":
        history_path.write_text("[]", encoding="utf-8")
        history_ref["sha256"] = hashlib.sha256(history_path.read_bytes()).hexdigest()
        receipt_path.write_text(json.dumps(outer), encoding="utf-8")
    elif invalid == "owner_markets":
        outer["markets"] = None
        history["markets"] = None
    elif invalid == "history_markets":
        history["markets"] = None
    elif invalid == "owner_selection_artifacts":
        outer["selection_artifacts"] = None
        history["selection_artifacts"] = None
    elif invalid == "history_selection_artifacts":
        history["selection_artifacts"] = None

    if invalid not in {"owner_root", "history_root"}:
        history_bytes = json.dumps(history, sort_keys=True).encode()
        history_path.write_bytes(history_bytes)
        outer["receipt_history"]["sha256"] = hashlib.sha256(history_bytes).hexdigest()
        receipt_path.write_text(json.dumps(outer), encoding="utf-8")

    monkeypatch.setattr(RawStore, "verify_latest", lambda self, *args: raw_result)
    monkeypatch.setattr(
        materializer.StageSelectionConsumer,
        "get",
        lambda self, date, stage_id, markets: (
            selection if stage_id == "STAGE_1445_1500"
            else {"status": "CANNOT_CONFIRM", "trade_date": date, "stage_id": stage_id,
                  "markets": {}, "cannot_confirm": []}
        ),
    )

    # Exercise the caller path: a bad Stage7 witness becomes CANNOT_CONFIRM in
    # the stage payload and does not throw out of the daily lane preparation.
    stage_inputs = materializer._stage_inputs(
        tmp_path / "data", DAY, stage_selection_root=selection_root,
    )
    witness = stage_inputs["STAGE_1445_1500"]["stage7_observation_witness"]
    assert witness["eligible"] is False
    assert expected_reason in witness["cannot_confirm"]
    assert stage_inputs["STAGE_1445_1500"]["status"] == "CANNOT_CONFIRM"


def test_unexpected_stage7_witness_exception_does_not_abort_daily_inputs(tmp_path: Path, monkeypatch) -> None:
    selection, selection_root, _raw_result, _receipt = _stage7_inputs(tmp_path)
    monkeypatch.setattr(
        materializer.StageSelectionConsumer,
        "get",
        lambda self, date, stage_id, markets: (
            selection if stage_id == "STAGE_1445_1500"
            else {"status": "CANNOT_CONFIRM", "trade_date": date, "stage_id": stage_id,
                  "markets": {}, "cannot_confirm": []}
        ),
    )
    monkeypatch.setattr(
        materializer,
        "_stage7_observation_witness",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AttributeError("malformed evidence")),
    )

    stage_inputs = materializer._stage_inputs(
        tmp_path / "data", DAY, stage_selection_root=selection_root,
    )
    witness = stage_inputs["STAGE_1445_1500"]["stage7_observation_witness"]
    assert witness["eligible"] is False
    assert witness["cannot_confirm"] == ["STAGE7_WITNESS_ERROR:AttributeError"]
    assert stage_inputs["STAGE_1445_1500"]["status"] == "CANNOT_CONFIRM"


@pytest.mark.parametrize("invalid", ["membership", "research_evidence", "backfill", "unsafe_raw", "raw_sha", "manifest_sha", "owner_history_gates"])
def test_stage7_gate_fails_closed_on_core_or_unsafe_evidence(tmp_path: Path, monkeypatch, invalid: str) -> None:
    selection, selection_root, raw_result, owner_receipt = _stage7_inputs(tmp_path)
    a_market = selection["markets"]["A_SHARE"]
    if invalid == "membership":
        a_market["cannot_confirm"].append("A_MEMBERSHIP_AUTHORITY_UNKNOWN")
        raw_result["verified"]["cannot_confirm"] = ["A_MEMBERSHIP_AUTHORITY_UNKNOWN"]
    elif invalid == "research_evidence":
        a_market["cannot_confirm"].append("RESEARCH_STAGE_EVIDENCE_MISSING")
    elif invalid == "backfill":
        owner_receipt["dispatch_mode"] = "BACKFILL"
        owner_receipt["receipt_history"].pop("sha256", None)
        # Rebuild the exact immutable history binding for the modified owner receipt.
        history_path = selection_root.parent / "receipts" / DAY / "STAGE_1445_1500" / "attempt_evidence" / "verified" / "RECEIPT.json"
        history_payload = {key: value for key, value in owner_receipt.items() if key != "receipt_history"}
        history_bytes = json.dumps(history_payload, sort_keys=True).encode()
        history_path.write_bytes(history_bytes)
        owner_receipt["receipt_history"] = {
            "schema_version": "stage_center.runner.history_ref.v1",
            "relative_path": str(history_path.relative_to(selection_root.parent / "receipts")),
            "sha256": hashlib.sha256(history_bytes).hexdigest(),
        }
        (selection_root.parent / "receipts" / DAY / "STAGE_1445_1500" / "receipt.json").write_text(
            json.dumps(owner_receipt), encoding="utf-8"
        )
    elif invalid == "unsafe_raw":
        raw_result["verified"]["status"] = "PARTIAL_WITH_ROWS"
        raw_result["latest"]["status"] = "PARTIAL_WITH_ROWS"
        manifest_path = selection_root.parent / "raw" / raw_result["verified"]["manifest_relative"]
        manifest = json.loads(manifest_path.read_text())
        manifest.update(status="PARTIAL_WITH_ROWS", temporal_cutoff_safe=False)
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif invalid == "raw_sha":
        a_market["raw_artifact_sha256"] = "9" * 64
    elif invalid == "manifest_sha":
        manifest_path = selection_root.parent / "raw" / raw_result["verified"]["manifest_relative"]
        manifest = json.loads(manifest_path.read_text())
        manifest["post_verify_mutation"] = True
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    elif invalid == "owner_history_gates":
        receipt_root = selection_root.parent / "receipts"
        receipt_path = receipt_root / DAY / "STAGE_1445_1500" / "receipt.json"
        outer = json.loads(receipt_path.read_text())
        history_ref = outer["receipt_history"]
        history_path = receipt_root / history_ref["relative_path"]
        history = json.loads(history_path.read_text())
        history["due_status"] = "NOT_DUE"
        history_bytes = json.dumps(history, sort_keys=True).encode()
        history_path.write_bytes(history_bytes)
        history_ref["sha256"] = hashlib.sha256(history_bytes).hexdigest()
        receipt_path.write_text(json.dumps(outer), encoding="utf-8")

    monkeypatch.setattr(RawStore, "verify_latest", lambda self, *args: raw_result)
    witness = materializer._stage7_observation_witness(selection, DAY, selection_root)
    assert witness["eligible"] is False
    assert witness["cannot_confirm"]
    if invalid == "manifest_sha":
        assert any("STAGE7_RAW_MANIFEST_SHA_MISMATCH" in item for item in witness["cannot_confirm"])
    if invalid == "owner_history_gates":
        assert any("STAGE7_OWNER_HISTORY_RECEIPT_PAYLOAD_MISMATCH" in item for item in witness["cannot_confirm"])


def _write_lane_source(source_dir: Path, *, partial: bool) -> None:
    source_dir.mkdir(parents=True)
    for name in ("anchor_role.csv", "theme_stocks.csv", "prior_plan.csv", "intraday_handoff.csv"):
        (source_dir / name).write_text("header\n", encoding="utf-8")
    (source_dir / "receipt.json").write_text(json.dumps({
        "status": "PARTIAL" if partial else "READY",
        "lane_scope": "FUPAN_ONLY_STAGE7_NOT_SYNTHESIZED" if partial else None,
        "inputs_sha256": "2" * 64,
        "cannot_confirm": ["STAGE7_NOT_MATERIALIZED"] if partial else [],
        "selector_source_binding": {"generation_id": "a" * 64},
    }), encoding="utf-8")


def _patch_lane_rows(monkeypatch) -> None:
    monkeypatch.setattr(lane, "_build_rows", lambda **_kwargs: [{
        "target_date": TARGET, "trade_date": TARGET, "signal_date": DAY,
        "stock_code": "000001", "ts_code": "000001.SZ", "name": "平安银行",
        "stock_name": "平安银行", "pool_score": 50, "role": "leader",
    }])
    monkeypatch.setattr(lane, "_load_video_fupan_context", lambda *_args: {
        "status": "VIDEO_FUPAN_POOL_NOT_READY", "raw_status": "MISSING",
        "gap_rows": [], "source_paths": [], "cannot_confirm": ["VIDEO_SOURCE_MISSING"],
    })
    monkeypatch.setattr(lane, "_build_video_fupan_rows", lambda **_kwargs: [])
    monkeypatch.setattr(lane, "_merge_fupan_and_video_rows", lambda first, second: first + second)
    monkeypatch.setattr(lane, "_rows_for_lane", lambda rows, *, lane: [dict(row) for row in rows])
    monkeypatch.setattr(lane, "_build_code_maps", lambda _rows: {})


def test_fupan_only_emits_no_stage7_pool_and_reuses_same_receipt(tmp_path: Path, monkeypatch) -> None:
    _patch_lane_rows(monkeypatch)
    source_dir = tmp_path / "sources"
    output_dir = tmp_path / "preselection" / TARGET
    _write_lane_source(source_dir, partial=True)
    first = lane.ensure_preopen_lane_artifacts(
        TARGET, signal_date=DAY, source_dir=source_dir, output_dir=output_dir, fupan_only=True,
    )
    assert first["ok"] is True
    assert first["status"] == "PREOPEN_D1_FUPAN_READY_STAGE7_MISSING"
    assert first["stage7_row_count"] == 0
    assert (output_dir / "fupan.csv").is_file()
    manifest = json.loads((output_dir / "fupan.manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["lane_scope"] == "FUPAN_ONLY_STAGE7_NOT_SYNTHESIZED"
    assert manifest["selector_source_binding"]["generation_id"] == "a" * 64
    assert not (output_dir / "stage7.csv").exists()
    assert not (output_dir / "stage7.manifest.json").exists()
    second = lane.ensure_preopen_lane_artifacts(
        TARGET, signal_date=DAY, source_dir=source_dir, output_dir=output_dir, fupan_only=True,
    )
    assert second["status"] == "PREOPEN_D1_FUPAN_READY_STAGE7_MISSING_EXISTING"
    assert second["stage7_row_count"] == 0


def test_fupan_only_does_not_retain_prior_real_stage7_output(tmp_path: Path, monkeypatch) -> None:
    _patch_lane_rows(monkeypatch)
    source_dir = tmp_path / "sources"
    output_dir = tmp_path / "preselection" / TARGET
    _write_lane_source(source_dir, partial=True)
    output_dir.mkdir(parents=True)
    (output_dir / "stage7.csv").write_text("stock_code\n000001\n", encoding="utf-8")
    (output_dir / "stage7.manifest.json").write_text(json.dumps({
        "source_role": "real_d1_stage7_tail_replay",
        "target_date": TARGET,
        "signal_date": DAY,
    }), encoding="utf-8")
    result = lane.ensure_preopen_lane_artifacts(
        TARGET, signal_date=DAY, source_dir=source_dir, output_dir=output_dir, fupan_only=True,
    )
    assert result["ok"] is False
    assert result["status"] == "FUPAN_ONLY_STAGE7_OUTPUT_CONFLICT"
    assert not (output_dir / "fupan.csv").exists()


def test_strict_stage7_path_remains_available(tmp_path: Path, monkeypatch) -> None:
    _patch_lane_rows(monkeypatch)
    source_dir = tmp_path / "sources"
    output_dir = tmp_path / "preselection" / TARGET
    _write_lane_source(source_dir, partial=False)
    (source_dir / "stage7_tail_replay.csv").write_text("stock_code\n000001\n", encoding="utf-8")
    (source_dir / "stage7_tail_replay.manifest.json").write_text(json.dumps({
        "status": "DATA_PARTIAL_OBSERVE_ONLY", "trade_date": DAY,
        "stage_id": "STAGE_1445_1500", "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }), encoding="utf-8")
    monkeypatch.setattr(lane, "_build_real_stage7_rows", lambda **_kwargs: ([{
        "target_date": TARGET, "trade_date": TARGET, "signal_date": DAY,
        "stock_code": "000001", "ts_code": "000001.SZ", "name": "平安银行",
        "stock_name": "平安银行", "pool_score": 50, "theme": "银行",
        "stage7_group": "观察",
    }], {"status": "DATA_PARTIAL_OBSERVE_ONLY", "trade_date": DAY,
         "stage_id": "STAGE_1445_1500", "production_allowed": False,
         "buy_gate_updated": False, "orders_sent": False}))
    result = lane.ensure_preopen_lane_artifacts(
        TARGET, signal_date=DAY, source_dir=source_dir, output_dir=output_dir,
    )
    assert result["ok"] is True
    assert result["status"] == "PREOPEN_D1_LANES_READY"
    assert result["stage7_source_role"] == "real_d1_stage7_tail_replay"
    assert (output_dir / "stage7.csv").is_file()
    manifest = json.loads((output_dir / "stage7.manifest.json").read_text(encoding="utf-8-sig"))
    assert manifest["source_role"] == "real_d1_stage7_tail_replay"
