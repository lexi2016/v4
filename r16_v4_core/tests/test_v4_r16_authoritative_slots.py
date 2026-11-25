"""R16 regressions with bounded synthetic fixtures and real file/SQLite boundaries."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from contextlib import contextmanager

from fastapi.testclient import TestClient
import pytest

from v4_core.api.app import create_app
from v4_core.config import V4Config
from v4_core.ingest.a_share_tdx import TDX_DAY_STRUCT
from v4_core.runner import a_daily_authority
from v4_core.runner.a_daily_authority import publish_a_daily, read_a_daily_publication, validate_a_daily
from v4_core.runner.cache_lanes import read_hk_cache, read_stage7, write_hk_cache
from v4_core.runner.cli import BEIJING, run_scheduled_window
from v4_core.runner.evidence import DatedInputs, EvidenceError
from v4_core.runner.review_inputs import lane_or_gap, read_materialized_a_daily, read_materialized_hk_close
from v4_core.runner.slots import run_slot_4_a_share_daily, run_slot_6_review_and_maint
from v4_core.runner.schedule import MAIN_STAGES, folded_readbacks
from v4_core.runner.state import ConcurrentHistoryChange, file_identity, publish_json, writer_lease
from v4_core.storage.db import V4Store

DAY = "2026-11-25"
NEXT_DAY = "2026-11-26"
FLAGS = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def at(hour, minute, second=0):
    return datetime(2026, 11, 25, hour, minute, second, tzinfo=BEIJING)


def write_ref(directory, name, value):
    data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
    path = directory / name
    path.write_bytes(data)
    return {"path": name, "sha256": sha256(data).hexdigest()}


def snapshot(tmp_path, **payload):
    root = tmp_path / "inputs"
    day_dir = root / DAY
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "inputs.json").write_text(json.dumps({
        "schema": "v4_core.r16_inputs.v1", "trade_date": DAY, **payload,
    }))
    return root, DatedInputs.load(root, DAY)


def a_daily_entry(directory, *, target_close=1110):
    code = "000001.SZ"
    single = {"market": "A", "symbol": code, "trade_date": DAY, "open": 11.0, "high": 11.2,
              "low": 10.8, "close": target_close / 100, "volume": 1000, "amount": 11100.0, "pre_close": 10.9}
    expected = {
        "000002.SZ": ("TARGET_DATE_MISSING", {"latest_trade_date": "2026-11-24"}),
        "600000.SH": ("INVALID_BAR:non_positive_ohlc", {"bar": {key: 0.0 for key in ("open", "high", "low", "close")}}),
        "688000.SH": ("SUSPENSION_SOURCE_STALE_REVERIFY_REQUIRED", {
            "suspension_source_date": "2026-10-27", "current_suspension_verified": False,
        }),
    }
    source_root = directory / "tdx"
    native = source_root / "vipdoc" / "sz" / "lday" / "sz000001.day"
    native.parent.mkdir(parents=True, exist_ok=True)
    native_bytes = (
        TDX_DAY_STRUCT.pack(20261124, 1080, 1100, 1070, 1090, 10900.0, 1000, 0)
        + TDX_DAY_STRUCT.pack(20261125, 1100, 1120, 1080, target_close, 11100.0, 1000, 0)
    )
    native.write_bytes(native_bytes)
    native_sha = sha256(native_bytes).hexdigest()
    raw_sha = "1" * 64
    authority = write_ref(directory, "authority.json", {
        "target_date": DAY, "authority_status": "REBUILD_REQUIRED",
        "files": [{"relative_path": "vipdoc/sz/lday/sz000001.day", "sha256": native_sha}], **FLAGS,
    })
    unresolved, reconciled = [], [{
        "symbol": "000001", "market": 0, "target_date_ready": True, "source_sha256_after": native_sha,
    }]
    for item, (reason, _) in expected.items():
        short, exchange = item.split(".")
        base = {"symbol": short, "market": int(exchange == "SH"), "reason_code": reason.split(":")[0]}
        unresolved.append(base)
        reconciled.append({**base, "failure_type": reason.lower(), "source_sha256_after": raw_sha})
    coverage = write_ref(directory, "coverage.json", {
        "target_date": DAY, "status": "PARTIAL", "target_count": 4, "accepted_count": 1,
        "accepted_target_date_file_count": 1, "reconciliation": {"symbols": reconciled},
        "scope_eligibility": {"eligible_target_count": 4, "unresolved_eligible_count": 3, "unresolved_eligible": unresolved},
    })
    quarantine = []
    for item, (reason, extra) in expected.items():
        ref = write_ref(directory, item + ".json", {
            "trade_date": DAY, "market": "A", "symbol": item, "reason": reason,
            "source_sha256": raw_sha, "coverage_receipt_sha256": coverage["sha256"],
            "classification_status": "CANNOT_CONFIRM", **extra,
        })
        quarantine.append({"symbol": item, "reason": reason, "evidence": ref})
    return {
        "native_source_root": str(source_root), "observed_at": at(16, 45).isoformat(), "bars": write_ref(directory, "a_bars.json", [single]),
        "authority": authority, "coverage_receipt": coverage, "accepted_symbols": [code], "quarantine": quarantine,
        "factors": write_ref(directory, "factors.json", [
            {"market": "A", "symbol": code, "trade_date": DAY, "adj_factor": 1.0},
        ]),
    }


def stage7_entry(directory):
    artifact = write_ref(directory, "stage.csv", (
        b"trade_date,code,name,bar_time,window_start,window_end,temporal_cutoff_safe,buy_signal\n"
        b"20261125,SZ.000001,Sample,14:59:00,14:45:00,14:59:00,True,True\n"
    ))
    manifest_body = {
        "trade_date": DAY, "role": "A_SHARE_1MIN_STAGE_1445_1500", "stage_id": "STAGE_1445_1500",
        "market": "A_SHARE", "temporal_cutoff_safe": True, "status": "READY", "run_id": "fixture-stage",
        "row_count": 1, "artifact_sha256": artifact["sha256"], **FLAGS,
    }
    canonical = json.dumps(manifest_body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    receipt = write_ref(directory, "stage_receipt.json", {
        **manifest_body, "manifest_sha256": sha256(canonical).hexdigest(), "cutoff_at": "15:00:00",
    })
    return {"source_date": DAY, "target_date": NEXT_DAY, "observed_at": at(15, 2, 25).isoformat(),
            "artifact": artifact, "manifest": write_ref(directory, "stage_manifest.json", canonical + b"\n"),
            "receipt": receipt}


def hk_cache_entry(directory, *, available_at=None):
    artifact = write_ref(directory, "hk.csv", (
        b"trade_date,signal_date,code_norm,rank,score_prob_active,history_resolution_identity\n"
        b"20261126,20261125,HK.00700,1,0.8,history-identity\n"
    ))
    finished = (available_at or at(17, 35)).isoformat()
    manifest = write_ref(directory, "hk_manifest.json", {
        "trade_date": NEXT_DAY, "signal_date": DAY, "provenance": {"signal_date": DAY},
        "market": "HK_CONNECT", "stage_id": "D1_PREMARKET", "temporal_cutoff_safe": True,
        "captured_at": finished, "cutoff_at": "17:30:00", "row_count": 1, "artifact_sha256": artifact["sha256"],
    })
    receipt = write_ref(directory, "hk_receipt.json", {
        "trade_date": NEXT_DAY, "role": "HK_CONNECT_D1_TOP100_0_2", "stage_id": "D1_PREMARKET",
        "status": "READY", "run_id": "fixture-hk", "finished_at": finished, "manifest_sha256": manifest["sha256"],
        "artifact_sha256": artifact["sha256"], **FLAGS,
    })
    return {"source_date": DAY, "target_date": NEXT_DAY, "artifact": artifact, "manifest": manifest, "receipt": receipt}


def research_entries(directory):
    close = write_ref(directory, "close.json", {
        "trade_date": DAY, "status": "READY", "same_date_row_count": 21, "rows": [
            {"code": f"HK.{i:05d}", "trade_date": DAY, "close": 100 + i, "pre_close": 100, "amount": 1}
            for i in range(1, 22)
        ], **FLAGS,
    })
    model = write_ref(directory, "model.json", {
        "trade_date": DAY, "target_date": DAY, "signal_date": "2026-11-24", "market": "HK",
        "status": "STRICT_0_2_READY", "pool_id": "hkconnect_d1_top100", "source_row_count": 100,
        "rows": [
            {"code": f"HK.{i:05d}", "trade_date": DAY, "market": "HK", "rank": i}
            for i in range(1, 101)
        ], **FLAGS,
    })
    timeline = {"trade_date": DAY, "stock_code": "000001.SZ", "source_title": "fixture",
                "url": "https://example.invalid/fixture", "event_time": at(18, 59).isoformat()}
    hour = write_ref(directory, "hour.json", {
        "trade_date": DAY, "slot": "1900", "default_status": "RESEARCH_ONLY", "write_policy": "read_only",
        "buy_gate_effect": "none", "live_order_effect": "none", "source_manifest": {
            "trade_date": DAY, "hourly_slot": "1900", "generated_at": at(19, 0, 12).isoformat(),
            "natural_execution_verified": False,
        },
        "stock_research_timeline": [timeline, {**timeline, "evidence_sentence": "longer"}],
        "stock_research_daily": [{"stock_code": "000001.SZ", "trade_date": DAY, "research_score": 2.8}],
        "research_pool_bridge": [{"stock_code": "000001.SZ", "trade_date": DAY, "stage_overlap": True}],
        "cannot_confirm": [{"reason": "NO_SOURCE_EVIDENCE"}],
    })
    return {
        "hk_close": {"status": "MODEL_REVIEW_PARTIAL_STAGE_EVIDENCE", "observed_at": at(16, 47).isoformat(),
                     "close_snapshot": close, "model_pool": model,
                     "close_snapshot_receipt": write_ref(directory, "close_receipt.json", {
                         "trade_date": DAY, "source_sha256": close["sha256"],
                     })},
        "hourly_announcements": {"status": "PARTIAL_WITH_ROWS", "observed_at": at(19, 0, 13).isoformat(),
                                 "source": hour},
    }


def test_p03_a_partial_day_publishes_only_checked_symbols_and_fsyncs_receipts(tmp_path):
    _, blank = snapshot(tmp_path)
    entry = a_daily_entry(blank.directory)
    _, inputs = snapshot(tmp_path, a_daily=entry)
    cfg = V4Config.from_env(tmp_path / "sandbox")
    store = V4Store(cfg.db_path)
    with writer_lease(cfg.data_dir, cfg.logs_dir, "a-fixture") as lease:
        result = publish_a_daily(cfg.data_dir, store, inputs, lease)
    assert (result["status"], result["accepted_count"], result["eligible_count"], result["quarantined_count"]) == (
        "PARTIAL", 1, 4, 3,
    )
    assert {row["symbol"] for row in store.get_date_bars("A", DAY)} == {"000001.SZ"}
    assert {item["halt_or_delist_status"] for item in result["quarantine"]} == {"CANNOT_CONFIRM"}
    with store.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM quarantine_events").fetchone()[0] == 3
    checkpoint = cfg.data_dir / "history" / "checkpoint.json"
    delta = cfg.data_dir / "history" / result["history_delta_path"]
    assert sha256(checkpoint.read_bytes()).hexdigest() == result["history_checkpoint_sha256"]
    assert json.loads(checkpoint.read_bytes())["delta"]["sha256"] == sha256(delta.read_bytes()).hexdigest()
    assert read_a_daily_publication(cfg.data_dir / "history", store, inputs, result)["accepted_count"] == 1
    entry["quarantine"][0]["reason"] = "HALTED"
    _, tampered = snapshot(tmp_path, a_daily=entry)
    with pytest.raises(EvidenceError, match="A_QUARANTINE_NOT_IN_AUTHORITY"):
        validate_a_daily(tampered)


def test_p03_history_assertion_records_actual_disk_drift_and_owner(tmp_path):
    cfg = V4Config.from_env(tmp_path)
    path = cfg.data_dir / "history" / "checkpoint.json"
    publish_json(path, {"generation": 1})
    before = file_identity(path)
    with writer_lease(cfg.data_dir, cfg.logs_dir, "history-oracle") as lease:
        subprocess.run([sys.executable, "-B", "-c",
                        "from pathlib import Path; import sys; Path(sys.argv[1]).write_text('actual drift')",
                        str(path)], check=True)
        after = file_identity(path)
        assert before != after
        with pytest.raises(ConcurrentHistoryChange, match="changed before replace"):
            publish_json(path, {"generation": 2}, lease=lease, expected=before)
    [receipt] = list((cfg.logs_dir / "writer_assertions").iterdir())
    evidence = json.loads(receipt.read_bytes())
    assert evidence["before"] == before and evidence["after"] == after
    assert {"dev", "ino", "size", "mtime_ns", "ctime_ns"} == before.keys()
    assert evidence["pid"] == os.getpid() and evidence["ppid"] == os.getppid()
    assert evidence["lock_owner"] == lease.owner and "ConcurrentHistoryChange" in evidence["stack"]
    assert path.read_text() == "actual drift" and list(path.parent.glob("*.tmp")) == []


def test_p03_hk_writer_reader_require_both_original_shas(tmp_path):
    _, blank = snapshot(tmp_path)
    entry = hk_cache_entry(blank.directory)
    _, inputs = snapshot(tmp_path, hk_cache=entry)
    data = tmp_path / "sandbox"
    with pytest.raises(EvidenceError, match="HK_CACHE_EVIDENCE_AFTER_READBACK"):
        write_hk_cache(data, inputs, asof=at(17, 30))
    written = write_hk_cache(data, inputs, asof=at(17, 35))
    read, rows = read_hk_cache(data, DAY, NEXT_DAY, expected_entry=entry, asof=at(18, 0))
    assert read == written and len(rows) == 1
    assert read["source_manifest_sha256"] == entry["manifest"]["sha256"]
    assert read["source_receipt_sha256"] == entry["receipt"]["sha256"]
    cache = data / "hk_cache" / f"{DAY}.json"
    original = json.loads(cache.read_bytes())
    for key in ("source_manifest_sha256", "source_receipt_sha256"):
        publish_json(cache, {name: value for name, value in original.items() if name != key})
        with pytest.raises(EvidenceError, match="IDENTITY_MISMATCH"):
            read_hk_cache(data, DAY, NEXT_DAY, expected_entry=entry)
        publish_json(cache, {**original, key: "0" * 64})
        with pytest.raises(EvidenceError, match="IDENTITY_MISMATCH"):
            read_hk_cache(data, DAY, NEXT_DAY, expected_entry=entry)


def run_with_progressing_clock(cfg, start, root):
    current = start

    def advance(seconds):
        nonlocal current
        current += timedelta(seconds=seconds)

    return run_scheduled_window(cfg, start, evidence_dir=root, completion_clock=lambda: current,
                                wait_for_deadlines=True, poll_sleep=advance, sse_notifier=lambda *_: False)


def test_p02_research_lanes_keep_asof_and_stage7_share_one_readback(tmp_path, monkeypatch):
    monkeypatch.setenv("V4_MIN_FREE_GIB", "0")
    _, blank = snapshot(tmp_path)
    root, inputs = snapshot(tmp_path, stage7=stage7_entry(blank.directory), a_daily=a_daily_entry(blank.directory),
                       workloads=research_entries(blank.directory))
    cfg = V4Config.from_env(tmp_path / "sandbox")
    early = run_scheduled_window(cfg, at(15, 0), completion_clock=lambda: at(15, 2), evidence_dir=root)
    assert early["paired_workloads"]["stage7_formal"]["reason"].startswith("STAGE7_EVIDENCE_AFTER_READBACK")
    late = run_scheduled_window(cfg, at(15, 40), evidence_dir=root)
    assert late["schedule_status"] == "READY" and late["workload"]["row_count"] == 1
    result, rows = read_stage7(cfg.data_dir, DAY, NEXT_DAY)
    assert late["workload"]["formal_rows_sha256"] == result["formal_rows_sha256"]
    assert rows[0]["source_merge_role"] == "SOURCE_ONLY" and rows[0]["stage_selection_eligible"] is False
    assert "buy_signal" not in rows[0]
    [registry] = list((cfg.data_dir / "stage_raw").iterdir())
    assert json.loads(registry.read_bytes())["formal_rows"] == rows
    store = V4Store(cfg.db_path)
    store.upsert_workbench_selections([{"trade_date": DAY, "symbol": "000001.SZ", "selection_group": "192"}])
    paired = run_with_progressing_clock(cfg, at(16, 10), root)
    assert paired["evidence_observed_through"] == at(16, 47).isoformat()
    assert paired["schedule_status"] == "PARTIAL" and paired["workload"]["accepted_count"] == 1
    close = paired["paired_workloads"]["hk_connect_close_review"]
    assert close["status"] == "PARTIAL" and close["source_mode"] == "NATIVE_INPUT_MATERIALIZATION"
    assert (close["model_rows"], close["close_top20"], close["model_hit_count"]) == (100, 20, 20)
    assert read_materialized_hk_close(cfg, inputs, at(21, 15)) == close
    a_landed = read_materialized_a_daily(cfg, store, inputs, at(21, 15))
    assert a_landed["counts"] == {"bars": 1, "top200": 1, "workbench": 1}
    assert a_landed["source_status"] == "PARTIAL"
    evening = run_with_progressing_clock(cfg, at(19, 0), root)
    assert evening["evidence_observed_through"] == at(19, 0, 15).isoformat()
    assert evening["workload"]["article_count"] == evening["workload"]["stock_pool_count"] == 1
    assert evening["workload"]["source_mode"] == "NATIVE_INPUT_MATERIALIZATION"
    assert evening["paired_workloads"]["next_day_observation"]["status"] == "CANNOT_CONFIRM"
    appended = {**inputs.payload, "workloads": {
        **inputs.payload["workloads"], "next_day_observation": {"status": "SOURCE_NOT_AVAILABLE"},
    }}
    index_path = inputs.directory / "inputs.json"
    publish_json(index_path, appended)
    refreshed = DatedInputs.load(root, DAY)
    assert refreshed.sha256 != inputs.sha256
    assert read_materialized_hk_close(cfg, refreshed, at(21, 15)) == close
    assert read_materialized_a_daily(cfg, store, refreshed, at(21, 15)) == a_landed
    assert read_stage7(cfg.data_dir, DAY, NEXT_DAY)[0] == result
    review = run_scheduled_window(cfg, at(21, 15), evidence_dir=root)
    assert review["schedule_status"] == "CANNOT_CONFIRM" and "fupan" in review["workload"]["detail"]["cannot_confirm"]
    assert review["workload"]["detail"]["inputs"]["stage7"]["registry_sha256"] == result["registry_sha256"]
    assert review["workload"]["detail"]["inputs"]["hk_close"]["publication_sha256"] == close["publication_sha256"]
    saved_review = store.get_review_record(DAY)
    assert saved_review["status"] == "CANNOT_CONFIRM"
    assert run_slot_6_review_and_maint(cfg, DAY)["execution_ref"] is None
    assert store.get_review_record(DAY) == saved_review
    assert review["workload"]["detail"]["inputs"]["a_share_daily"]["history_delta_sha256"] == a_landed["history_delta_sha256"]
    with store.connect() as connection:
        connection.execute("DELETE FROM top200_daily WHERE trade_date=?", (DAY,))
    with pytest.raises(EvidenceError, match="DOWNSTREAM_PUBLICATION_COUNTS_MISMATCH"):
        read_materialized_a_daily(cfg, store, inputs, at(21, 15))
    stage_out = cfg.data_dir / "review_inputs" / DAY
    close_path = stage_out / "hk_close.json"
    close_file = json.loads(close_path.read_bytes())
    assert close_file["rows"]["close_top20"][0]["code"] == "HK.00021"
    assert len(close_file["rows"]["model_rows"]) == 100
    article = json.loads((stage_out / "hourly_announcements.json").read_bytes())["rows"]["articles"][0]
    assert article["duplicate_evidence_count"] == 2 and article["evidence_sentence"] == "longer"
    with TestClient(create_app(cfg)) as client:
        response = client.get("/api/v4/workbench/stage", params={
            "date": NEXT_DAY, "source_date": DAY, "stage": "STAGE_1445_1500", "limit": 0,
        }).json()
        assert response["selected_total_rows"] == 0 and response["source_pool"]["rows"] == rows

    # Updating each relevant entry invalidates only its own prior binding.
    for lane, read, reason in (
        ("stage7", lambda current: read_stage7(cfg.data_dir, DAY, NEXT_DAY), "STAGE7_INPUT_REGISTRY_SHA_MISMATCH"),
        ("a_daily", lambda current: read_a_daily_publication(
            cfg.data_dir / "history", store, current, paired["workload"],
        ), "A_1610_HISTORY_SHA_OR_IDENTITY_MISMATCH"),
        ("hk_close", lambda current: read_materialized_hk_close(cfg, current, at(21, 15)),
         "HK_CLOSE_1610_ARTIFACT_SHA_OR_IDENTITY_MISMATCH"),
    ):
        mutated = json.loads(json.dumps(appended))
        parent = mutated["workloads"] if lane == "hk_close" else mutated
        parent[lane]["observed_at"] = at(17, 0).isoformat()
        publish_json(index_path, mutated)
        with pytest.raises(EvidenceError, match=reason):
            read(DatedInputs.load(root, DAY))
    publish_json(index_path, appended)
    close_file["rows"]["close_top20"][0]["code"] = "HK.99999"
    publish_json(close_path, close_file)
    with pytest.raises(EvidenceError, match="ARTIFACT_SHA_OR_IDENTITY_MISMATCH"):
        read_materialized_hk_close(cfg, inputs, at(21, 15))


def test_p02_folded_deadlines_cannot_reuse_a_late_preparation(tmp_path):
    _, blank = snapshot(tmp_path)
    points = {}
    for time, name, observed in [("09:34", "prepare_opening_inputs", at(9, 36)),
                                 ("09:37", "opening_visibility_deadline", at(9, 36, 40))]:
        artifact = write_ref(blank.directory, time + ".data", b"isolated upstream evidence")
        receipt = write_ref(blank.directory, time + ".json", {
            "trade_date": DAY, "stage_id": "STAGE_0930_0935", "status": "READY", "task": name,
            "observed_at": observed.isoformat(), "artifact_sha256": artifact["sha256"], **FLAGS,
        })
        points[time] = {"artifact": artifact, "receipt": receipt, "observed_at": observed.isoformat()}
    root, inputs = snapshot(tmp_path, main_tasks=points)
    stage = MAIN_STAGES[(9, 35)]
    assert folded_readbacks(inputs, stage, at(9, 35))["09:37"]["status"] == "PENDING"
    cfg = V4Config.from_env(tmp_path / "sandbox")
    observed = run_scheduled_window(cfg, at(9, 35), completion_clock=lambda: at(9, 37), evidence_dir=root)
    folded = observed["paired_workloads"]["folded_tasks"]
    assert folded["09:34"]["reason"] == "FOLDED_TASK_EVIDENCE_OUTSIDE_VALIDITY"
    assert folded["09:37"]["status"] == "READY"


def test_p02_external_publications_cannot_replace_required_native_inputs(tmp_path):
    _, blank = snapshot(tmp_path)
    stale_ref = write_ref(blank.directory, "reference.json", {"status": "READY"})
    root, _ = snapshot(tmp_path, workloads={
        "hk_close": {"status": "READY", "observed_at": at(16, 10).isoformat(),
                     "artifact": stale_ref, "receipt": stale_ref},
        "hourly_announcements": {"status": "READY", "observed_at": at(19, 0).isoformat(),
                                 "artifact": stale_ref, "receipt": stale_ref},
    })
    cfg = V4Config.from_env(tmp_path / "sandbox")
    close = run_scheduled_window(cfg, at(16, 10), evidence_dir=root)
    hourly = run_scheduled_window(cfg, at(19, 0), evidence_dir=root)
    assert close["paired_workloads"]["hk_connect_close_review"]["reason"] == "HK_CLOSE_NATIVE_SOURCES_UNBOUND"
    assert hourly["workload"]["reason"] == "HOURLY_NATIVE_SOURCE_UNBOUND"
    assert not (cfg.data_dir / "review_inputs").exists()



def test_p03_native_exact_prices_reject_rehashed_projection(tmp_path):
    _, blank = snapshot(tmp_path)
    entry = a_daily_entry(blank.directory)
    path = blank.directory / entry["bars"]["path"]
    rows = json.loads(path.read_bytes())
    rows[0]["close"] = 11.15
    entry["bars"] = write_ref(blank.directory, path.name, rows)
    _, tampered = snapshot(tmp_path, a_daily=entry)
    with pytest.raises(EvidenceError, match="A_PROJECTED_BAR_DIFFERS_FROM_NATIVE_SOURCE:000001.SZ"):
        validate_a_daily(tampered)


@pytest.mark.parametrize("failure", ["drift", "commit"])
def test_p03_official_history_failure_preserves_prior_publication(tmp_path, monkeypatch, failure):
    _, blank = snapshot(tmp_path)
    initial_entry = a_daily_entry(blank.directory)
    _, initial = snapshot(tmp_path, a_daily=initial_entry)
    cfg = V4Config.from_env(tmp_path / "sandbox")
    store = V4Store(cfg.db_path)
    history = cfg.data_dir / "history"
    checkpoint = history / "checkpoint.json"
    with writer_lease(cfg.data_dir, cfg.logs_dir, "initial") as lease:
        prior = publish_a_daily(cfg.data_dir, store, initial, lease)
    old_pointer = checkpoint.read_bytes()
    old_delta = (history / prior["history_delta_path"]).read_bytes()
    initial_rows = store.get_date_bars("A", DAY)

    updated_entry = a_daily_entry(blank.directory, target_close=1112)
    # A distinct quarantine evidence ledger would create another record if the SQL transaction leaked.
    first = updated_entry["quarantine"][0]
    evidence = json.loads((blank.directory / first["evidence"]["path"]).read_bytes())
    first["evidence"] = write_ref(blank.directory, "new-fault-witness.json", {**evidence, "witness": "retry"})
    _, updated = snapshot(tmp_path, a_daily=updated_entry)

    if failure == "drift":
        original_publish = a_daily_authority.publish_bytes
        def drift_publish(path, data, **kwargs):
            if path == checkpoint:
                subprocess.run([sys.executable, "-B", "-c",
                                "from pathlib import Path; import sys; p=Path(sys.argv[1]); p.write_bytes(p.read_bytes())",
                                str(path)], check=True)
            return original_publish(path, data, **kwargs)
        monkeypatch.setattr(a_daily_authority, "publish_bytes", drift_publish)
        expected = ConcurrentHistoryChange
    else:
        original_connect = store.connect
        with original_connect() as conn:
            conn.execute("CREATE TABLE parents (id INTEGER PRIMARY KEY)")
            conn.execute("CREATE TABLE children (parent INTEGER REFERENCES parents(id) DEFERRABLE INITIALLY DEFERRED)")
        @contextmanager
        def missing_parent():
            with original_connect() as conn:
                conn.execute("PRAGMA foreign_keys=ON")
                yield conn
                conn.execute("INSERT INTO children VALUES (1)")
        monkeypatch.setattr(store, "connect", missing_parent)
        expected = sqlite3.IntegrityError

    with writer_lease(cfg.data_dir, cfg.logs_dir, "failing-revision") as lease:
        with pytest.raises(expected):
            publish_a_daily(cfg.data_dir, store, updated, lease)
    monkeypatch.undo()
    assert checkpoint.read_bytes() == old_pointer
    assert (history / prior["history_delta_path"]).read_bytes() == old_delta
    assert store.get_date_bars("A", DAY) == initial_rows
    with store.connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM quarantine_events").fetchone()[0] == 3
    assert read_a_daily_publication(history, store, initial, prior)["accepted_count"] == 1
    if failure == "drift":
        [receipt] = list((cfg.logs_dir / "writer_assertions").iterdir())
        evidence = json.loads(receipt.read_bytes())
        assert evidence["before"] != evidence["after"]
        assert set(evidence["before"]) == set(evidence["after"]) == {"dev", "ino", "size", "mtime_ns", "ctime_ns"}



def test_review_core_rejects_nonzero_manual_a_counts_without_1610_binding(tmp_path, monkeypatch):
    monkeypatch.setenv("V4_MIN_FREE_GIB", "0")
    root, _ = snapshot(tmp_path)
    cfg = V4Config.from_env(tmp_path / "sandbox")
    store = V4Store(cfg.db_path)
    store.upsert_daily_bars([{"trade_date": DAY, "market": "A", "symbol": "000001.SZ",
                             "open": 10.0, "close": 11.0, "high": 11.0, "low": 10.0,
                             "volume": 100, "amount": 1100.0, "pre_close": 10.0}])
    store.upsert_adj_factors([{"trade_date": DAY, "market": "A", "symbol": "000001.SZ", "adj_factor": 1.0}])
    store.upsert_workbench_selections([{"trade_date": DAY, "symbol": "000001.SZ", "selection_group": "192"}])
    assert run_slot_4_a_share_daily(cfg, DAY, sse_notifier=lambda *_: False)["workbench_count"] == 1
    assert len(store.get_top200(DAY)) == 1 and len(store.get_date_bars("A", DAY)) == 1
    review = run_scheduled_window(cfg, at(21, 15), evidence_dir=root)
    a_gate = review["workload"]["detail"]["inputs"]["a_share_daily"]
    assert a_gate["status"] == "CANNOT_CONFIRM" and a_gate["reason"] == "DAILY_1610_WINDOW_RECEIPT_UNAVAILABLE"


def test_scheduled_writer_waits_inside_1730_without_relaxing_launch_grace(tmp_path):
    _, blank = snapshot(tmp_path)
    entry = hk_cache_entry(blank.directory)
    root = blank.directory.parent
    cfg = V4Config.from_env(tmp_path / "sandbox")
    clock = at(17, 30)
    sleeps = []

    def wait(seconds):
        nonlocal clock
        sleeps.append(seconds)
        clock += timedelta(seconds=seconds)
        if clock == at(17, 34):
            publish_json(blank.directory / "inputs.json", {**blank.payload, "hk_cache": entry})

    writer = run_scheduled_window(cfg, at(17, 30), completion_clock=lambda: clock,
                                  wait_for_deadlines=True, poll_sleep=wait, evidence_dir=root)
    assert writer["schedule_status"] == "READY" and sum(sleeps) == 300
    assert writer["scheduled_for"] == at(17, 30).isoformat()
    assert writer["evidence_observed_through"] == at(17, 35).isoformat()
    assert run_scheduled_window(cfg, at(17, 32, 1), evidence_dir=root)["schedule_status"] == "NO_DUE_WORKLOADS"
    reader = run_scheduled_window(cfg, at(18, 0), evidence_dir=root)
    assert reader["schedule_status"] == "READY" and reader["workload"]["row_count"] == 1


def observation_fixture(day_dir, hourly, field):
    calendar = write_ref(day_dir, "calendar.json", {
        "schema": "v4_core.a_session_binding.v1", "market": "A", "status": "READY", "source_date": DAY,
        "target_date": NEXT_DAY, "source_identity": "scoped-a-calendar-fixture",
        "sessions": [{"trade_date": day, "is_session": True} for day in (DAY, NEXT_DAY)],
    })
    calendar_receipt = write_ref(day_dir, "calendar_receipt.json", {
        "schema": "v4_core.a_session_binding_receipt.v1", "market": "A", "status": "READY", "source_date": DAY,
        "target_date": NEXT_DAY, "source_identity": "scoped-a-calendar-fixture", "calendar_sha256": calendar["sha256"],
    })
    shared = {
        "trade_date": DAY, "target_date": "2026-12-15" if field == "target" else NEXT_DAY,
        "role": "NEXT_DAY_OBSERVATION_EDITION", "status": "READY", "run_id": "obs-fixture",
        "upstream_hourly_publication_sha256": "6" * 64 if field == "upstream_sha" else hourly["publication_sha256"],
        "finished_at": (at(19, 0, 1) if field == "finished" else at(19, 1)).isoformat(), **FLAGS,
    }
    artifact = write_ref(day_dir, "observation.json", {**shared, "rows": [{"fixture": True}]})
    manifest = write_ref(day_dir, "observation_manifest.json", {**shared, "row_count": 1,
                                                            "artifact_sha256": artifact["sha256"]})
    receipt = write_ref(day_dir, "observation_receipt.json", {
        **shared, "row_count": 1, "artifact_sha256": artifact["sha256"], "manifest_sha256": manifest["sha256"],
    })
    payload = {"workloads": {"next_day_observation": {
        "observed_at": at(19, 2).isoformat(), "status": "READY",
        "artifact": artifact, "manifest": manifest, "receipt": receipt,
    }}}
    if field != "no_calendar":
        payload["next_a_session"] = {"calendar": calendar, "receipt": calendar_receipt}
    return payload


@pytest.mark.parametrize(("field", "expected"), [
    ("good", None),
    ("upstream_sha", "OBSERVATION_HOURLY_PUBLICATION_SHA_MISMATCH"),
    ("finished", "OBSERVATION_COMPLETION_TIME_MISMATCH"),
    ("target", "OBSERVATION_TARGET_DATE_MISMATCH"),
    ("no_calendar", "NEXT_A_SESSION_EVIDENCE_UNAVAILABLE"),
])
def test_observation_requires_hourly_publication_time_and_next_a_session(tmp_path, field, expected):
    _, blank = snapshot(tmp_path)
    hourly = {"publication_sha256": "7" * 64, "status": "READY", "observed_at": at(19, 0, 15).isoformat()}
    payload = observation_fixture(blank.directory, hourly, field)
    _, inputs = snapshot(tmp_path, **payload)
    cfg = V4Config.from_env(tmp_path / "sandbox")
    result = lane_or_gap(cfg, inputs, "next_day_observation", at(19, 2), hourly=hourly)
    if expected is None:
        assert result["status"] == "READY" and result["row_count"] == 1
    else:
        assert result["status"] == "CANNOT_CONFIRM" and result["reason"] == expected
        assert not cfg.data_dir.exists()



def test_scheduler_wake_after_deadline_does_not_admit_after_deadline_evidence(tmp_path):
    _, blank = snapshot(tmp_path)
    root, _ = snapshot(tmp_path, hk_cache=hk_cache_entry(blank.directory, available_at=at(17, 45, 3)))
    cfg = V4Config.from_env(tmp_path / "sandbox")
    current = at(17, 44, 59)

    def oversleep(seconds):
        nonlocal current
        current += timedelta(seconds=seconds + 5)

    result = run_scheduled_window(cfg, at(17, 30), evidence_dir=root, completion_clock=lambda: current,
                                  wait_for_deadlines=True, poll_sleep=oversleep)
    assert current == at(17, 45, 5)
    assert result["evidence_observed_through"] == at(17, 45).isoformat()
    assert result["workload"]["reason"] == "HK_CACHE_EVIDENCE_AFTER_READBACK"
    assert not (cfg.data_dir / "hk_cache").exists()



def test_evening_waits_for_observation_linked_to_the_actual_hourly_disk_sha(tmp_path):
    _, blank = snapshot(tmp_path)
    hour = research_entries(blank.directory)["hourly_announcements"]
    raw = json.loads((blank.directory / hour["source"]["path"]).read_bytes())
    raw["cannot_confirm"] = []
    raw["source_manifest"]["natural_execution_verified"] = True
    hour["source"] = write_ref(blank.directory, "verified_hour.json", raw)
    hour["status"] = "READY"
    root, initial = snapshot(tmp_path, workloads={"hourly_announcements": hour})
    cfg = V4Config.from_env(tmp_path / "sandbox")
    lane_dir = cfg.data_dir / "review_inputs" / DAY
    hour_path = lane_dir / "hourly_announcements.json"
    obs_path = lane_dir / "next_day_observation.json"
    clock = at(19, 0)
    immutable = None

    def advance(seconds):
        nonlocal clock, immutable
        clock += timedelta(seconds=seconds)
        if clock in {at(19, 1, 30), at(19, 2)}:
            assert hour_path.is_file() and not obs_path.exists()
            digest = sha256(hour_path.read_bytes()).hexdigest()
            if immutable is None:
                immutable = (digest, file_identity(hour_path))
            assert immutable == (digest, file_identity(hour_path))
            hourly = {**json.loads(hour_path.read_bytes()), "publication_sha256": digest}
            link = observation_fixture(initial.directory, hourly,
                                       "upstream_sha" if clock == at(19, 1, 30) else "good")
            publish_json(initial.directory / "inputs.json", {
                **initial.payload, **link,
                "workloads": {**initial.payload["workloads"], **link["workloads"]},
            })

    result = run_scheduled_window(cfg, at(19, 0), evidence_dir=root, completion_clock=lambda: clock,
                                  wait_for_deadlines=True, poll_sleep=advance)
    assert result["schedule_status"] == "DONE" and result["evidence_observed_through"] == at(19, 2).isoformat()
    assert immutable == (result["workload"]["publication_sha256"], file_identity(hour_path))
    observation = result["paired_workloads"]["next_day_observation"]
    assert observation["upstream_hourly_publication_sha256"] == immutable[0]
    assert observation["target_date"] == NEXT_DAY and observation["publication_sha256"] == sha256(obs_path.read_bytes()).hexdigest()
    receipts = (cfg.logs_dir / "daily_windows" / f"{DAY}_1900.jsonl").read_text().splitlines()
    assert [json.loads(line)["schedule_status"] for line in receipts] == ["RUNNING", "DONE"]


def test_p03_abrupt_exit_after_active_pointer_replace_preserves_committed_authority(tmp_path):
    root, blank = snapshot(tmp_path)
    first_entry = a_daily_entry(blank.directory)
    _, initial = snapshot(tmp_path, a_daily=first_entry)
    home = tmp_path / "sandbox"
    cfg = V4Config.from_env(home)
    store = V4Store(cfg.db_path)
    history = cfg.data_dir / "history"
    with writer_lease(cfg.data_dir, cfg.logs_dir, "first") as lease:
        prior = publish_a_daily(cfg.data_dir, store, initial, lease)
    old_rows = store.get_date_bars("A", DAY)
    old_pointer = (history / "checkpoint.json").read_bytes()
    _, updated = snapshot(tmp_path, a_daily=a_daily_entry(blank.directory, target_close=1113))
    child_source = """
import os, sys
from pathlib import Path
from v4_core.config import V4Config
from v4_core.runner import a_daily_authority as a
from v4_core.runner.evidence import DatedInputs
from v4_core.runner.state import writer_lease
from v4_core.storage.db import V4Store
home, root, day = sys.argv[1:]
cfg = V4Config.from_env(Path(home))
source = DatedInputs.load(Path(root), day)
original = a.publish_bytes
def crash_after_pointer(path, content, **options):
    result = original(path, content, **options)
    if path.name == "checkpoint.json":
        os._exit(79)
    return result
a.publish_bytes = crash_after_pointer
with writer_lease(cfg.data_dir, cfg.logs_dir, "abrupt-fixture") as lease:
    a.publish_a_daily(cfg.data_dir, V4Store(cfg.db_path), source, lease)
"""
    result = subprocess.run([sys.executable, "-B", "-c", child_source, str(home), str(root), DAY], check=False)
    assert result.returncode == 79
    active = (history / "checkpoint.json").read_bytes()
    assert active != old_pointer and (history / prior["history_checkpoint_path"]).read_bytes() == old_pointer
    assert store.get_date_bars("A", DAY) == old_rows
    assert read_a_daily_publication(history, store, initial, prior)["accepted_count"] == 1
    staged = json.loads(active)
    delta = json.loads((history / staged["delta"]["path"]).read_bytes())
    staged_sha = sha256(active).hexdigest()
    with pytest.raises(EvidenceError, match="A_1610_SQLITE_PUBLICATION_UNCOMMITTED"):
        read_a_daily_publication(history, store, updated, {
            **delta, "history_delta_path": staged["delta"]["path"], "history_delta_sha256": staged["delta"]["sha256"],
            "history_checkpoint_path": f"checkpoints/{DAY}-{staged_sha}.json", "history_checkpoint_sha256": staged_sha,
        })
    with writer_lease(cfg.data_dir, cfg.logs_dir, "retry") as lease:
        retried = publish_a_daily(cfg.data_dir, store, updated, lease)
    assert retried["history_checkpoint_sha256"] == staged_sha
    assert read_a_daily_publication(history, store, updated, retried)["accepted_count"] == 1
