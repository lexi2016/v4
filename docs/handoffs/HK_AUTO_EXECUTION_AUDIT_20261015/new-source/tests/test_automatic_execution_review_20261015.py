"""Canary contract for automatic natural-HK execution readback publication."""
from __future__ import annotations

from datetime import datetime
import hashlib
import csv
import io
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from infrastructure.owned_io import SafeRoot
from ops._run_stage_center_nodes_parts import stage_dispatch
from ops.verify_stage_execution import VerificationError, verify_and_publish
from stage_center.execution_evidence import read_stage_execution
from stage_center.raw_store import RawStore, RAW_FIELDS
from stage_center.scheduler import evaluate_due
from stage_center.selection import SelectionStore, select_hk_four_lane


DATE = "20261014"
STAGE = "STAGE_0945_1030"
SHANGHAI = ZoneInfo("Asia/Shanghai")
SAFETY = {"RESEARCH_ONLY": True, "production_allowed": False,
          "buy_gate_updated": False, "orders_sent": False}


@pytest.fixture(autouse=True)
def _configured_api_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv("V35_DATA_ROOT", str(tmp_path / "d1-owner"))
    monkeypatch.delenv("V35_PRESELECTION_SOURCE_ROOT", raising=False)
    monkeypatch.delenv("V35_MORNING_NEWS_DATA_ROOT", raising=False)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _fixture(tmp_path: Path, *, capture_at="2026-10-14T10:29:00+08:00",
             bar_end="10:29:00", source_mutator=None):
    receipt_root = tmp_path / "receipts"
    raw_root = tmp_path / "raw"
    selection_root = tmp_path / "selection"
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    from stage_center.hk_stage8.snapshot import _snapshot_codes_sha, _snapshot_rows_sha
    from upstreams.v3_shared_data.scripts.live_acquisition.futu_minute import aggregate_futu_minute_window_rows
    codes = [f"HK.{index:05d}" for index in range(1, 101)]
    d1_root = tmp_path / "d1-owner"
    d1_rows = [{"code": code, "symbol": code, "market": "HK", "pool_id": "hkconnect_d1_top100",
        "pool_rank": index, "trade_date": DATE, "target_date": DATE, "signal_date": "20261013",
        "recommendation_status": "WATCH_ONLY", **{key: False for key in ("production_allowed", "buy_gate_updated", "orders_sent")}}
        for index, code in enumerate(codes, 1)]
    d1_payload = {"schema_version": "v3_5.preselection_pool.v1", "trade_date": DATE, "target_date": DATE,
        "signal_date": "20261013", "pool_id": "hkconnect_d1_top100", "display_name": "HK Top100",
        "market": "HK", "status": "STRICT_0_2_READY", "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2", "source_path": "fixture/source.csv", "source_sha256": "1" * 64,
        "source_run_id": "source-run", "source_manifest_sha256": "2" * 64, "source_receipt_sha256": "3" * 64,
        "stage_selection_eligible": True, "rows": d1_rows, "cannot_confirm": [],
        **{key: False for key in ("production_allowed", "buy_gate_updated", "orders_sent")}}
    PreselectionPoolStore(d1_root).materialize(d1_payload)
    d1_path = d1_root / "preselection_pools" / DATE / "hkconnect_d1_top100.json"
    d1_raw = d1_path.read_bytes()
    provider_rows = [{"code": "HK.00001", "name": "Fixture", "time_key": f"2026-10-14 {bar_end}",
        "open": 10.5, "close": 11.0, "high": 11.0, "low": 10.5, "last_close": 10.0,
        "turnover": 1_000_000.0, "volume": 100_000.0}]
    capture = {"trade_date": DATE, "stage_id": STAGE, "market": "HK_CONNECT", "adjustment": "NONE",
        "codes": codes, "captured_at": capture_at, "rows": provider_rows, "errors": [], "no_data_codes": codes[1:]}
    snapshot_rows = [{"code": code, "prev_close_price": 10.0, "last_price": 11.0, "turnover": 30_000_000.0,
        "volume_ratio": 1.5, "update_time": "2026-10-14 10:29:00"} for code in codes]
    snapshot = {"schema_version": "stage_center.hk_active_snapshot.v2", "trade_date": DATE, "stage_id": STAGE,
        "market": "HK_CONNECT", "source_role": "FUTU_HKCONNECT_FULL_SCAN", "pool_artifact_sha256": _sha(d1_raw),
        "codes": codes, "codes_sha256": _snapshot_codes_sha(codes), "requested_rows": 100, "returned_rows": 100,
        "full_coverage": True, "rows": snapshot_rows, "snapshot_sha256": _snapshot_rows_sha(snapshot_rows),
        "provider_started_at": "2026-10-14T10:29:00+08:00", "provider_finished_at": "2026-10-14T10:29:30+08:00",
        "captured_at": "2026-10-14T10:29:30+08:00", "cutoff_at": "2026-10-14T10:30:00", "temporal_cutoff_safe": True,
        **{key: False for key in ("production_allowed", "buy_gate_updated", "orders_sent")}}
    original_provider_rows = json.loads(json.dumps(provider_rows))
    if source_mutator:
        source_mutator(capture, snapshot, d1_payload)
    capture_raw = _canonical(capture) + b"\n"
    capture_sha = _sha(capture_raw)
    source_files = {"minute_capture": raw_root / ".futu_minute_captures" / DATE / STAGE / f"{capture_sha}.json",
                    "active_snapshot": raw_root / ".hk_active_snapshots_v2" / DATE / STAGE / "snapshot.json", "hk_d1": d1_path}
    for path, raw in ((source_files["minute_capture"], capture_raw), (source_files["active_snapshot"], _canonical(snapshot))):
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(raw)
    if source_mutator and d1_payload != json.loads(d1_raw):
        # A malformed D1 file deliberately fails the authoritative trio reader.
        d1_path.write_bytes(_canonical(d1_payload))
        d1_raw = d1_path.read_bytes()
    source_evidence = ["route=shared_futu_hkconnect_minute",
        f"futu_capture_path={source_files['minute_capture']}", f"futu_capture_sha256={capture_sha}",
        f"futu_captured_at={capture_at}", f"futu_provider_rows_sha256={_sha(_canonical(capture['rows']))}", "futu_adjustment=NONE",
        f"active_snapshot_path={source_files['active_snapshot']}", f"active_snapshot_sha256={snapshot['snapshot_sha256']}",
        "active_snapshot_source=PERSISTED_EXACT_STAGE", "active_snapshot_cutoff=10:30:00",
        "active_snapshot_temporal_cutoff_safe=true", "active_snapshot_provider_finished_at=2026-10-14T10:29:30+08:00",
        f"hk_d1_json={d1_path}", f"hk_d1_sha256={_sha(d1_raw)}", "hk_d1_membership=exact_date_top100"]
    # The owner aggregate intentionally remains the valid original result for
    # tamper cases, so self-consistent source hashes cannot mask wrong content.
    raw_row = aggregate_futu_minute_window_rows(DATE, STAGE, original_provider_rows)[0] if bar_end == "10:29:00" else {
        "batch_index": 1, "code": "HK.00001", "name": "Fixture", "update_time": f"2026-10-14 {bar_end}",
        "last_price": 11.0, "open_price": 10.5, "high_price": 11.0, "low_price": 10.5, "prev_close_price": 10.0,
        "turnover": 1_000_000.0, "volume": 100_000.0, "bid_price": "", "ask_price": "", "bid_vol": "", "ask_vol": "",
        "window_start": "2026-10-14 09:46:00", "window_end": f"2026-10-14 {bar_end}", "bar_count": 1, "temporal_cutoff_safe": True}
    return _publish_stage_fixture(tmp_path, STAGE, [raw_row], source_evidence, d1_root, source_files)


def _publish_stage_fixture(tmp_path, STAGE, raw_rows, source_evidence, d1_root, source_files):
    from stage_center.contracts import STAGE_BY_ID
    from datetime import timedelta
    raw_root, selection_root, receipt_root = (tmp_path / key for key in ("raw", "selection", "receipts"))
    stage = STAGE_BY_ID[STAGE]
    assert all(set(row).issuperset(RAW_FIELDS) for row in raw_rows)
    raw_result = RawStore(raw_root).publish(
        trade_date=DATE, stage_id=STAGE, market="HK_CONNECT", source_id="fixture_futu",
        source_status="READY", rows=[{field: row[field] for field in RAW_FIELDS} for row in raw_rows], source_evidence=source_evidence,
        requested_rows=100, window=stage.hk_window or stage.window, cutoff_at=stage.cutoff,
    )
    envelope = select_hk_four_lane(
        [{**row, "volume_ratio": 1.5} for row in raw_rows],
        DATE, STAGE, raw_result["artifact_sha256"], source_evidence=source_evidence, requested_rows=100,
    )
    selection_store = SelectionStore(selection_root)
    selection_store.publish(envelope, market="HK_CONNECT")
    lane = selection_store.read_verified(DATE, STAGE, "HK_CONNECT")
    lane = {**lane, "status": lane["selection_status"], "market": "HK_CONNECT"}
    verified = selection_store._verify_run(DATE, STAGE, "HK_CONNECT", lane["run_id"])
    prefix = Path(verified["artifact_relative"]).parent
    paths = {
        "artifact_relative": verified["artifact_relative"],
        "manifest_relative": (prefix / "manifest.json").as_posix(),
        "receipt_relative": (prefix / "receipt.json").as_posix(),
    }
    selection_raw = {key: SafeRoot(selection_root).read_bytes(path) for key, path in paths.items()}
    selection_binding = {
        "schema_version": "stage_center.runner.selection_binding.v1",
        "trade_date": DATE, "stage_id": STAGE, "market": "HK_CONNECT",
        **{key: lane[key] for key in (
            "run_id", "artifact_id", "algorithm_sha256", "raw_artifact_sha256", "selected_rows")},
        **paths,
        "artifact_bytes_sha256": _sha(selection_raw["artifact_relative"]),
        "manifest_bytes_sha256": _sha(selection_raw["manifest_relative"]),
        "receipt_bytes_sha256": _sha(selection_raw["receipt_relative"]),
        "manifest_canonical_sha256": _sha(_canonical(json.loads(selection_raw["manifest_relative"]))),
        "receipt_canonical_sha256": _sha(_canonical(json.loads(selection_raw["receipt_relative"]))),
    }
    attempt_id = "a" * 32
    attempt_relative = f"{DATE}/{STAGE}/attempt_evidence/{attempt_id}/001_START.json"
    scheduled = datetime.strptime(f"{DATE} {stage.cutoff}", "%Y%m%d %H:%M:%S").replace(tzinfo=SHANGHAI)
    attempt = {
        "schema": "stage.attempt_diagnostic.v1", "event": "START", "attempt_id": attempt_id,
        "trade_date": DATE, "stage_id": STAGE, "attempt_number": 1,
        "evaluated_at": (scheduled + timedelta(seconds=2)).isoformat(),
        "observed_at": (scheduled + timedelta(seconds=4)).isoformat(),
    }
    SafeRoot(receipt_root).write_bytes(attempt_relative, _canonical(attempt), require_absent=True)
    receipt = {
        "schema_version": "stage_center.runner.receipt.v1", "runner": "stage_center",
        "trade_date": DATE, "stage_id": STAGE, "dispatch_mode": "NATURAL", "due_status": "DUE",
        "node_attempt_count": 1, **SAFETY,
        "recorded_at": (scheduled + timedelta(seconds=5)).astimezone(ZoneInfo("UTC")).isoformat(),
        "record_time_source": "OWNER_WRITE_CLOCK_UTC",
        "attempt_diagnostic": {"attempt_id": attempt_id,
                                "relative_paths": [f"attempt_evidence/{attempt_id}/001_START.json"]},
        "selection_artifacts": {"HK_CONNECT": selection_binding},
        "markets": {"HK_CONNECT": lane},
    }
    history_raw = _canonical(receipt)
    history_sha = _sha(history_raw)
    history_relative = f"{DATE}/{STAGE}/attempt_evidence/recorded-{history_sha}/RECEIPT.json"
    SafeRoot(receipt_root).write_bytes(history_relative, history_raw, require_absent=True)
    receipt["receipt_history"] = {"schema_version": "stage_center.runner.history_ref.v1",
                                  "relative_path": history_relative, "sha256": history_sha}
    receipt_raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
    receipt_relative = f"{DATE}/{STAGE}/receipt.json"
    SafeRoot(receipt_root).write_bytes(receipt_relative, receipt_raw, require_absent=True)
    return {
        "receipt_root": receipt_root, "raw_root": raw_root, "selection_root": selection_root, "hk_d1_root": d1_root,
        "selection_store": selection_store, "lane": lane, "receipt": receipt,
        "receipt_raw": receipt_raw, "receipt_relative": receipt_relative,
        "source_evidence": source_evidence, "source_files": source_files,
        "attempt": attempt, "attempt_id": attempt_id, "stage_id": STAGE,
    }


def _verify(fixture):
    return verify_and_publish(
        trade_date=DATE, stage_id=fixture.get("stage_id", STAGE),
        receipt_root=fixture["receipt_root"], raw_root=fixture["raw_root"],
        selection_root=fixture["selection_root"], hk_d1_root=fixture["hk_d1_root"],
        preselection_source_root=fixture.get("preselection_source_root"),
        hk_second_filter_root=fixture.get("hk_second_filter_root"),
        shared_research_root=fixture.get("shared_research_root"),
        expected_receipt_sha256=_sha(fixture["receipt_raw"]),
    )


def _other_stage_fixture(tmp_path, stage_id):
    """Production-shaped synthetic sources for the other minute/RT_DATA slots."""
    from datetime import timedelta
    from stage_center.contracts import HK_SNAPSHOT_SCHEDULE
    from stage_center.hk_stage8.snapshot import _snapshot_rows_sha
    from stage_center.hk_stage8.rtdata import _persist_stage8_rtdata_capture, _stage8_aggregate_rtdata_rows
    from upstreams.v3_shared_data.scripts.live_acquisition.futu_minute import aggregate_futu_minute_window_rows
    base = _fixture(tmp_path)
    capture = json.loads(base["source_files"]["minute_capture"].read_bytes())
    snapshot = json.loads(base["source_files"]["active_snapshot"].read_bytes())
    start, _end, cutoff = HK_SNAPSHOT_SCHEDULE[stage_id]
    started = datetime.fromisoformat(f"2026-10-14T{start}").replace(tzinfo=SHANGHAI)
    finished = started + timedelta(seconds=10)
    snapshot.update(stage_id=stage_id, cutoff_at=f"2026-10-14T{cutoff}",
        provider_started_at=started.isoformat(), provider_finished_at=finished.isoformat(), captured_at=finished.isoformat())
    for row in snapshot["rows"]:
        row["update_time"] = started.strftime("%Y-%m-%d %H:%M:%S")
    snapshot["snapshot_sha256"] = _snapshot_rows_sha(snapshot["rows"])
    snapshot_path = base["raw_root"] / ".hk_active_snapshots_v2" / DATE / stage_id / "snapshot.json"
    snapshot_path.parent.mkdir(parents=True); snapshot_path.write_bytes(_canonical(snapshot))
    d1 = [item for item in base["source_evidence"] if item.startswith("hk_d1_")]
    if stage_id == "STAGE_1545_1555":
        row = {"code": "HK.00001", "time": "2026-10-14 15:50:00", "cur_price": 11.0,
               "turnover": 1_000_000.0, "volume": 100_000.0, "last_close": 10.0, "name": "Fixture"}
        raw_rows = [_stage8_aggregate_rtdata_rows([(datetime(2026, 10, 14, 15, 50), row)],
            code=row["code"], active_snapshot_row=snapshot["rows"][0], trade_date=DATE, batch_index=1)]
        evidence = ["route=hk_connect_stage8_natural_rtd_data", "stage8_source=FUTU_RTDATA_NATURAL",
            f"stage8_active_snapshot_sha256={snapshot['snapshot_sha256']}",
            f"stage8_rtdata_raw_row_sha256={row['code']}:{_sha(_canonical([row]))}",
            *_persist_stage8_rtdata_capture(base["raw_root"], trade_date=DATE, stage_id=stage_id,
                codes=capture["codes"], fetched={"rows": [row], "missing_codes": capture["codes"][1:]},
                provider_started_at="2026-10-14T15:55:05+08:00", provider_finished_at="2026-10-14T15:55:06+08:00"), *d1]
    else:
        last = datetime.fromisoformat(f"2026-10-14T{cutoff}") - timedelta(minutes=1)
        last = last.replace(second=0)
        capture.update(stage_id=stage_id, captured_at=finished.isoformat())
        capture["rows"][0]["time_key"] = last.strftime("%Y-%m-%d %H:%M:%S")
        raw = _canonical(capture) + b"\n"
        path = base["raw_root"] / ".futu_minute_captures" / DATE / stage_id / (_sha(raw) + ".json")
        path.parent.mkdir(parents=True); path.write_bytes(raw)
        raw_rows = aggregate_futu_minute_window_rows(DATE, stage_id, capture["rows"])
        evidence = ["route=shared_futu_hkconnect_minute", f"futu_capture_path={path}",
            f"futu_capture_sha256={_sha(raw)}", f"futu_captured_at={capture['captured_at']}",
            f"futu_provider_rows_sha256={_sha(_canonical(capture['rows']))}", "futu_adjustment=NONE", *d1]
    evidence += [f"active_snapshot_path={snapshot_path}", f"active_snapshot_sha256={snapshot['snapshot_sha256']}",
        f"active_snapshot_cutoff={cutoff}", "active_snapshot_temporal_cutoff_safe=true"]
    return _publish_stage_fixture(tmp_path, stage_id, raw_rows, evidence, base["hk_d1_root"],
        {**base["source_files"], "active_snapshot": snapshot_path})


@pytest.mark.parametrize("stage_id", ["STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945", "STAGE_1300_1315", "STAGE_1445_1500", "STAGE_1545_1555"])
def test_other_minute_and_rtdata_stage_sources_publish_and_read(tmp_path, stage_id):
    fixture = _other_stage_fixture(tmp_path, stage_id)
    assert _verify(fixture)["status"] == "PUBLISHED"
    current = read_stage_execution(fixture["receipt_root"], DATE, stage_id,
        {"HK_CONNECT": fixture["lane"]}, selection_store=fixture["selection_store"])
    assert current["operating_execution_by_market"]["HK_CONNECT"]["execution_verified"] is True


def test_d1_configured_secondary_root_is_verified_without_arbitrary_path_access(tmp_path, monkeypatch):
    fixture = _fixture(tmp_path)
    primary = tmp_path / "primary-data"; primary.mkdir()
    fixture["preselection_source_root"] = fixture["hk_d1_root"]
    fixture["hk_d1_root"] = primary
    monkeypatch.setenv("V35_DATA_ROOT", str(primary))
    monkeypatch.setenv("V35_PRESELECTION_SOURCE_ROOT", str(fixture["preselection_source_root"]))
    assert _verify(fixture)["status"] == "PUBLISHED"
    current = read_stage_execution(fixture["receipt_root"], DATE, STAGE,
        {"HK_CONNECT": fixture["lane"]}, selection_store=fixture["selection_store"])
    assert current["operating_execution_by_market"]["HK_CONNECT"]["execution_verified"] is True


def _auction_fixture(tmp_path):
    from ops.run_hkconnect_0915_0920_capture import _csv_bytes, _restore_source_hash_numeric_types
    from domains.opening_second_filter import build_v11_opening_second_filter
    from shared_data.hk_auction_0920 import build_second_filter_rows
    from shared_data.consumer import read_verified_latest
    from stage_center._live_collectors_parts.hk_auction import _collect_hk_auction_body
    import stage_center.live_collectors as live
    base = _fixture(tmp_path)
    shared_root = tmp_path / "shared-authority"
    latest = {"schema_version": "v3_shared_data.latest.v1", "entries": {}}
    safety = {key: False for key in ("production_allowed", "buy_gate_updated", "orders_sent")}
    def shared_run(role, rows, **fields):
        run_id = "fixture-" + role.lower().replace("_", "-")
        directory = shared_root / "runs" / DATE / role / run_id
        directory.mkdir(parents=True)
        stream = io.StringIO(); writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
        raw = stream.getvalue().encode("utf-8-sig")
        artifact_relative = (directory / "artifact.csv").relative_to(shared_root).as_posix()
        (directory / "artifact.csv").write_bytes(raw)
        manifest = {"schema_version": "v3_shared_data.manifest.v1", "trade_date": DATE,
            "market": "HK_CONNECT", "stage_id": "STAGE_0925", "row_count": len(rows),
            "artifact_relative": artifact_relative, "artifact_sha256": _sha(raw),
            "temporal_cutoff_safe": True, **fields}
        (directory / "manifest.json").write_bytes(_canonical(manifest))
        receipt = {"schema_version": "v3_shared_data.receipt.v1", "owner": "fixture-only",
            "run_id": run_id, "role": role, "status": "READY", "artifact_sha256": _sha(raw),
            "manifest_sha256": _sha(_canonical(manifest)), **safety}
        (directory / "receipt.json").write_bytes(_canonical(receipt))
        latest["entries"][DATE + "/" + role] = {"run_id": run_id, "owner": "fixture-only"}
        (shared_root / "latest.json").write_bytes(_canonical(latest))
        return read_verified_latest(shared_root, DATE, role)
    preselect = [{"code": f"HK.{index:05d}", "name": f"Fixture {index}",
                  "preselect_rank": str(index), "preselect_lane": "D1_PRESELECT", "preselect_score": str(1000-index)}
                 for index in range(1, 101)]
    shared_d1 = shared_run("HK_CONNECT_D1_TOP100_0_2", preselect)
    reference = [{"trade_date": DATE, "bar_time": "09:19:59", "code": f"HK.{index:05d}",
        "name": f"Fixture {index}", "target_date": DATE, "signal_date": "20261013",
        "stage1_ref_score": str(100-index), "stage1_ref_label": "PREOPEN_REF_PRIORITY",
        "reference_scope": "SIGNAL_INPUT_CUTOFF_SAFE_091959", "auction_ref_gap_pct": "1.0",
        "first_to_last_ref_pct": "0.1", "visible_depth_hkd": "2000000", "bid_ask_imbalance": "0.2", "spread_pct": "0.5",
        "last_price": str(10 + index/10), "prev_close_price": "10.0", "bid_price": "10.0", "ask_price": "10.1",
        "bid_vol": "1000", "ask_vol": "900", "turnover": str(1_000_000+index),
        "update_time": "2026-10-14 09:19:59", "collector_wall_time": "2026-10-14 09:19:59"}
        for index in range(1, 51)]
    frozen = build_second_filter_rows(preselect, _restore_source_hash_numeric_types(reference))
    frozen_sha = _sha(_canonical({"contract": "old_v3_rule_guardrail_with_hardcap_and_0920_reference_layer", "trade_date": DATE, "rows": frozen}))
    shared = shared_run("HK_CONNECT_AUCTION_REFERENCE_STAGE_0925", reference, cutoff_at="09:19:59",
        provenance={"signal_date": "20261013", "d1_pool_sha256": shared_d1.verification["artifact_sha256"], "source_output_sha256": frozen_sha})
    projected = build_v11_opening_second_filter(preselect, reference, trade_date=DATE, signal_date="20261013",
        source_evidence={"d1_pool_sha256": shared_d1.verification["artifact_sha256"],
                         "auction_source_sha256": shared.verification["artifact_sha256"], "source_output_sha256": frozen_sha})
    second_root = base["hk_d1_root"] / "opening_second_filter"
    path = second_root / DATE / f"hkconnect_0920_auction_second_filter_{DATE}.csv"
    path.parent.mkdir(parents=True); raw = _csv_bytes(projected["rows"]); path.write_bytes(raw)
    acceptance = {"schema_version": "hkconnect_0920_auction_second_filter.v3", "status": "AUCTION_SECOND_FILTER_READY",
        "target_date": DATE, "signal_date": "20261013", "row_count": 20, "required_row_count": 20,
        "signal_cutoff": "09:19:59", "publication_time": "09:20:00", "csv_sha256": _sha(raw),
        "d1_artifact_sha256": shared_d1.verification["artifact_sha256"], "d1_run_id": shared_d1.verification["run_id"],
        "source_output_sha256": frozen_sha, "temporal_cutoff_safe": True, **safety,
        **{"shared_" + field: shared.verification[field] for field in ("run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256")}}
    path.with_suffix(".acceptance.json").write_bytes(_canonical(acceptance))
    result = _collect_hk_auction_body(live.__dict__, SimpleNamespace(trade_date=DATE, stage_id="STAGE_0925"),
        codes=tuple(row["code"] for row in preselect), python_path=None, shared_root=None,
        auction_root=path, process_runner=None, replay_provider=None)
    evidence = [*result.source_evidence, *[item for item in base["source_evidence"] if item.startswith("hk_d1_")]]
    fixture = _publish_stage_fixture(tmp_path, "STAGE_0925", list(result.rows), evidence,
        base["hk_d1_root"], {**base["source_files"], "auction_csv": path})
    fixture.update(hk_second_filter_root=second_root, shared_research_root=shared_root)
    return fixture


def test_auction_top20_real_trios_publish_and_reader_rechecks(tmp_path, monkeypatch):
    fixture = _auction_fixture(tmp_path)
    monkeypatch.setenv("V35_MORNING_NEWS_DATA_ROOT", str(fixture["shared_research_root"]))
    assert _verify(fixture)["status"] == "PUBLISHED"
    current = read_stage_execution(fixture["receipt_root"], DATE, "STAGE_0925",
        {"HK_CONNECT": fixture["lane"]}, selection_store=fixture["selection_store"])
    assert current["operating_execution_by_market"]["HK_CONNECT"]["execution_verified"] is True
    directory = fixture["receipt_root"] / "independent_execution_reviews" / DATE / "STAGE_0925"
    inputs = json.loads((directory / "attestation.json").read_bytes())["execution_inputs"]
    assert inputs["source_reconciliation"]["raw_rows"] == 20
    fixture["source_files"]["auction_csv"].write_bytes(b"tampered")
    current = read_stage_execution(fixture["receipt_root"], DATE, "STAGE_0925",
        {"HK_CONNECT": fixture["lane"]}, selection_store=fixture["selection_store"])
    assert current["operating_execution_by_market"]["HK_CONNECT"]["execution_verified"] is False


def test_automatic_review_canary_publishes_reader_compatible_evidence(tmp_path):
    fixture = _fixture(tmp_path)
    result = _verify(fixture)
    assert result["status"] == "PUBLISHED"
    assert result["pit_status"] == "CANNOT_CONFIRM"
    directory = fixture["receipt_root"] / "independent_execution_reviews" / DATE / STAGE
    attestation = json.loads((directory / "attestation.json").read_text())
    assert attestation["reviewer_identity_or_role"] == "AUTOMATED_INDEPENDENT_EXECUTION_VERIFIER"
    assert attestation["scope_semantics"] == "SCHEDULER_AND_ARTIFACT_OPERATION_FACTS_ONLY"
    assert attestation["markets"]["HK_CONNECT"]["operation_status"] == "VERIFIED"
    assert attestation["markets"]["HK_CONNECT"]["formal_eligibility_status"] == "CANNOT_CONFIRM"
    assert attestation["execution_inputs"]["d1_pool_time_binding"]["source_signal_date"] == "20261013"
    assert attestation["execution_inputs"]["d1_pool_time_binding"]["sha256"] == _sha(
        fixture["source_files"]["hk_d1"].read_bytes()
    )
    current = read_stage_execution(
        fixture["receipt_root"], DATE, STAGE, {"HK_CONNECT": fixture["lane"]},
        selection_store=fixture["selection_store"],
    )
    assert current["independent_execution_review"]["status"] == "VERIFIED_FOR_EXPLICIT_SCOPE"
    assert current["operating_execution_by_market"]["HK_CONNECT"]["execution_verified"] is True
    assert current["operating_execution_by_market"]["HK_CONNECT"]["natural_verified"] is True
    # This stage also contains A_SHARE; HK-only attestation must not promote the aggregate.
    assert current["execution_verified"] is False
    assert current["natural_verified"] is False


def test_cli_subprocess_publishes_canary(tmp_path):
    fixture = _fixture(tmp_path)
    script = Path(__file__).parents[1] / "ops" / "verify_stage_execution.py"
    completed = subprocess.run(
        [sys.executable, str(script), "--date", DATE, "--stage", STAGE,
         "--root", str(fixture["receipt_root"]), "--raw-root", str(fixture["raw_root"]),
         "--selection-root", str(fixture["selection_root"]),
         "--expected-receipt-sha256", _sha(fixture["receipt_raw"]), "--hk-d1-root", str(fixture["hk_d1_root"])],
        cwd=Path(__file__).parents[1], capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    assert json.loads(completed.stdout)["status"] == "PUBLISHED"


def test_late_capture_keeps_operation_verified_and_pit_unconfirmed(tmp_path):
    fixture = _fixture(tmp_path, capture_at="2026-10-14T10:30:03+08:00")
    result = _verify(fixture)
    assert result["status"] == "PUBLISHED"
    assert result["pit_status"] == "CANNOT_CONFIRM"
    assert "SOURCE_CAPTURE_AT_OR_AFTER_STAGE_CUTOFF" in result["pit_cannot_confirm"]
    current = read_stage_execution(
        fixture["receipt_root"], DATE, STAGE, {"HK_CONNECT": fixture["lane"]},
        selection_store=fixture["selection_store"],
    )
    assert current["independent_execution_review"]["status"] == "VERIFIED_FOR_EXPLICIT_SCOPE"
    assert current["operating_execution_by_market"]["HK_CONNECT"]["natural_verified"] is True


def test_duplicate_input_sha_is_idempotent(tmp_path):
    fixture = _fixture(tmp_path)
    first = _verify(fixture)
    attestation_path = fixture["receipt_root"] / "independent_execution_reviews" / DATE / STAGE / "attestation.json"
    before = attestation_path.read_bytes()
    second = _verify(fixture)
    assert first["status"] == "PUBLISHED"
    assert second["status"] == "IDEMPOTENT_EXISTING"
    assert attestation_path.read_bytes() == before


def test_missing_safety_flag_is_rejected_without_success(tmp_path):
    fixture = _fixture(tmp_path)
    receipt = dict(fixture["receipt"], orders_sent=True)
    receipt_raw = json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
    (fixture["receipt_root"] / fixture["receipt_relative"]).write_bytes(receipt_raw)
    with pytest.raises(VerificationError, match="CURRENT_RECEIPT_SAFETY_FLAGS_INCOMPLETE"):
        verify_and_publish(
            trade_date=DATE, stage_id=STAGE, receipt_root=fixture["receipt_root"],
            raw_root=fixture["raw_root"], selection_root=fixture["selection_root"],
            expected_receipt_sha256=_sha(receipt_raw),
        )
    assert not (fixture["receipt_root"] / "independent_execution_reviews" / DATE / STAGE / "index.json").exists()


def test_hash_mismatch_is_rejected(tmp_path):
    fixture = _fixture(tmp_path)
    with pytest.raises(VerificationError, match="EXPECTED_RECEIPT_SHA_MISMATCH"):
        verify_and_publish(
            trade_date=DATE, stage_id=STAGE, receipt_root=fixture["receipt_root"],
            raw_root=fixture["raw_root"], selection_root=fixture["selection_root"],
            expected_receipt_sha256="0" * 64,
        )


def test_raw_window_overrun_is_rejected(tmp_path):
    fixture = _fixture(tmp_path, bar_end="10:31:00")
    with pytest.raises(VerificationError, match="CURRENT_HK_RAW_ARTIFACT_NOT_OBSERVABLE"):
        _verify(fixture)
    assert not (fixture["receipt_root"] / "independent_execution_reviews" / DATE / STAGE / "index.json").exists()


def test_natural_hook_invokes_subprocess_once_and_skips_recovery(tmp_path, monkeypatch):
    receipt_path = tmp_path / "receipts" / DATE / STAGE / "receipt.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_bytes(b"natural receipt")
    roots = SimpleNamespace(receipt_root=receipt_path.parents[2],
                            raw_root=tmp_path / "raw", selection_root=tmp_path / "selection", hk_d1_root=tmp_path / "d1")
    for path in (roots.raw_root, roots.selection_root):
        path.mkdir()
    runner = SimpleNamespace(config=roots, _receipt_path=lambda *_: receipt_path)
    calls = []
    monkeypatch.setattr(stage_dispatch.subprocess, "run", lambda *args, **kwargs: (calls.append((args, kwargs)) or SimpleNamespace(returncode=0)))
    scope = {
        "STAGE_BY_ID": __import__("stage_center.contracts", fromlist=["STAGE_BY_ID"]).STAGE_BY_ID,
        "Path": Path,
        "__file__": str(Path(__file__).parents[1] / "ops" / "run_stage_center_nodes.py"),
    }
    persisted = {"dispatch_mode": "NATURAL", "due_status": "DUE",
                 "markets": {"HK_CONNECT": {}}}
    stage_dispatch._maybe_publish_automatic_execution_review(
        scope, runner, DATE, STAGE, mode="NATURAL", persisted=persisted,
    )
    stage_dispatch._maybe_publish_automatic_execution_review(
        scope, runner, DATE, STAGE, mode="RECOVERY", persisted=persisted,
    )
    stage_dispatch._maybe_publish_automatic_execution_review(
        scope, runner, DATE, STAGE, mode="NATURAL",
        persisted={"dispatch_mode": "NATURAL", "due_status": "LATE_CATCHUP_REPLAY"},
    )
    stage_dispatch._maybe_publish_automatic_execution_review(
        scope, runner, DATE, STAGE, mode="NATURAL",
        persisted={**persisted, "execution_origin": "MANUAL_REPLAY"},
    )
    stage_dispatch._maybe_publish_automatic_execution_review(
        scope, runner, DATE, STAGE, mode="NATURAL",
        persisted={**persisted, "same_day_late_observation_recovery": True},
    )
    stage_dispatch._maybe_publish_automatic_execution_review(
        scope, runner, DATE, STAGE, mode="NATURAL",
        persisted={**persisted, "mode": "BACKFILL"},
    )
    stage_dispatch._maybe_publish_automatic_execution_review(
        scope, runner, DATE, STAGE, mode="NATURAL",
        persisted={**persisted, "markets": {"HK_CONNECT": {"selection_mode": "BACKFILL"}}},
    )
    assert len(calls) == 1
    command = calls[0][0][0]
    assert "--date" in command and DATE in command
    assert "--stage" in command and STAGE in command
    assert "--expected-receipt-sha256" in command
    assert calls[0][1]["check"] is False


@pytest.mark.parametrize("mutation", ["capture_member", "capture_values", "snapshot_date", "snapshot_stage", "d1_future", "invalid_schema"])
def test_hash_consistent_bad_source_content_is_rejected(tmp_path, mutation):
    def mutate(capture, snapshot, d1):
        if mutation == "capture_member":
            capture["rows"][0]["code"] = "HK.99999"
            capture["rows"][0]["time_key"] = "2026-10-14 10:31:00"
        elif mutation == "capture_values":
            capture["rows"][0]["close"] = 10.8
        elif mutation == "snapshot_date":
            snapshot["trade_date"] = "20261015"
        elif mutation == "snapshot_stage":
            snapshot["stage_id"] = "WRONG_STAGE"
        elif mutation == "d1_future":
            d1["signal_date"] = "20261015"
            d1["rows"][0]["code"] = "HK.99999"
        else:
            capture["market"] = "INVALID"; snapshot["schema_version"] = "INVALID"; d1["schema_version"] = "INVALID"
    fixture = _fixture(tmp_path, source_mutator=mutate)
    with pytest.raises(VerificationError):
        _verify(fixture)
    assert not (fixture["receipt_root"] / "independent_execution_reviews" / DATE / STAGE / "index.json").exists()


def test_provider_buffer_after_cutoff_is_filtered_and_not_used_in_raw(tmp_path):
    def mutate(capture, _snapshot, _d1):
        capture["rows"].append({**capture["rows"][0], "time_key": "2026-10-14 10:31:00", "close": 99.0, "high": 99.0})
    fixture = _fixture(tmp_path, source_mutator=mutate)
    assert _verify(fixture)["status"] == "PUBLISHED"


def test_explicit_v2_loader_cannot_redirect_the_snapshot_path(tmp_path, monkeypatch):
    import stage_center.hk_stage8.snapshot as snapshot_module
    fixture = _fixture(tmp_path)
    original = snapshot_module.load_hk_active_snapshot
    def redirected(*args, **kwargs):
        value = original(*args, **kwargs)
        return {**value, "snapshot_path": str(fixture["raw_root"] / "unrelated.json")}
    monkeypatch.setattr(snapshot_module, "load_hk_active_snapshot", redirected)
    with pytest.raises(VerificationError, match="CURRENT_HK_SNAPSHOT_PATH_SCOPE_MISMATCH"):
        _verify(fixture)


def test_complete_automatic_reader_never_writes_unlinks_locks_or_repairs(tmp_path, monkeypatch):
    import os
    import fcntl
    from infrastructure.preselection_pool_store import PreselectionPoolStore
    fixture = _fixture(tmp_path)
    _verify(fixture)
    def refused(*_args, **_kwargs):
        raise AssertionError("read-only verification attempted a mutation or lock")
    monkeypatch.setattr(SafeRoot, "write_bytes", refused)
    monkeypatch.setattr(SafeRoot, "kernel_lock", refused)
    monkeypatch.setattr(Path, "write_bytes", refused)
    monkeypatch.setattr(Path, "write_text", refused)
    monkeypatch.setattr(Path, "mkdir", refused)
    monkeypatch.setattr(Path, "unlink", refused)
    monkeypatch.setattr(os, "unlink", refused)
    monkeypatch.setattr(os, "mkdir", refused)
    monkeypatch.setattr(os, "rmdir", refused)
    monkeypatch.setattr(os, "rename", refused)
    monkeypatch.setattr(os, "replace", refused)
    monkeypatch.setattr(fcntl, "flock", refused)
    monkeypatch.setattr(subprocess, "run", refused)
    monkeypatch.setattr(PreselectionPoolStore, "read_pool_snapshot", refused)
    monkeypatch.setattr(PreselectionPoolStore, "_reconcile_pending_commit_read_unlocked", refused)
    original_open = os.open
    def readonly_open(path, flags, *args, **kwargs):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            refused()
        return original_open(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", readonly_open)
    current = read_stage_execution(fixture["receipt_root"], DATE, STAGE,
        {"HK_CONNECT": fixture["lane"]}, selection_store=fixture["selection_store"])
    assert current["independent_execution_review"]["status"] == "VERIFIED_FOR_EXPLICIT_SCOPE"
    assert current["operating_execution_by_market"]["HK_CONNECT"]["execution_verified"] is True


@pytest.mark.parametrize("marker", ["pending", "import"])
def test_readonly_d1_refuses_pending_without_recovery_or_marker_changes(tmp_path, marker):
    fixture = _fixture(tmp_path)
    path = (fixture["hk_d1_root"] / "preselection_pending_commits" / DATE / "hkconnect_d1_top100.json"
            if marker == "pending" else fixture["hk_d1_root"] / ".import.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fixture pending owner state")
    with pytest.raises(VerificationError, match="CURRENT_HK_D1_PENDING_OR_IMPORT_IN_PROGRESS"):
        _verify(fixture)
    assert path.read_bytes() == b"fixture pending owner state"


@pytest.mark.parametrize("failure", ["timeout", "startup", "nonzero"])
def test_hook_failure_is_nonfatal_and_persists_rejection(tmp_path, monkeypatch, failure):
    fixture = _fixture(tmp_path)
    receipt_path = fixture["receipt_root"] / fixture["receipt_relative"]
    runner = SimpleNamespace(config=SimpleNamespace(
        receipt_root=fixture["receipt_root"], raw_root=fixture["raw_root"],
        selection_root=fixture["selection_root"], hk_d1_root=fixture["hk_d1_root"]),
        _receipt_path=lambda *_: receipt_path)
    def run(*_args, **_kwargs):
        if failure == "timeout":
            raise subprocess.TimeoutExpired("verifier", 30)
        if failure == "startup":
            raise FileNotFoundError("fixture missing executable")
        return SimpleNamespace(returncode=2)
    monkeypatch.setattr(stage_dispatch.subprocess, "run", run)
    scope = {"STAGE_BY_ID": __import__("stage_center.contracts", fromlist=["STAGE_BY_ID"]).STAGE_BY_ID,
             "Path": Path, "__file__": str(Path(__file__).parents[1] / "ops/run_stage_center_nodes.py")}
    stage_dispatch._maybe_publish_automatic_execution_review(scope, runner, DATE, STAGE,
        mode="NATURAL", persisted=fixture["receipt"])
    rejection = fixture["receipt_root"] / "independent_execution_reviews/rejections" / DATE / STAGE / (_sha(fixture["receipt_raw"]) + ".json")
    assert json.loads(rejection.read_text())["reason"].startswith("SIDECAR_")
    assert receipt_path.read_bytes() == fixture["receipt_raw"]
    assert not (fixture["receipt_root"] / "independent_execution_reviews" / DATE / STAGE / "index.json").exists()

