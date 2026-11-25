"""Replay the four production counterexamples through candidate entry points."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from hashlib import sha256
import json
import os
import subprocess
import sys
from threading import Event

from fastapi.testclient import TestClient

from v4_core.api.app import create_app

from v4_core.config import V4Config
from v4_core.runner import cli
from v4_core.runner.a_daily_authority import publish_a_daily
from v4_core.runner.state import publish_json, writer_lease
from v4_core.storage.db import V4Store
from v4_core.strategies.top200 import build_daily_top200

from test_v4_r16_authoritative_slots import (
    DAY, NEXT_DAY, a_daily_entry, at, observation_fixture, research_entries, snapshot, write_ref,
)


def _bar(symbol, date, close, pre_close=None):
    return {
        "market": "A", "symbol": symbol, "trade_date": date, "open": close, "high": close,
        "low": close, "close": close, "amount": 10000, "volume": 1000, "pre_close": pre_close,
    }


def test_workbench_materialization_blocks_all_three_authority_quarantines(tmp_path):
    _, blank = snapshot(tmp_path)
    _, inputs = snapshot(tmp_path, a_daily=a_daily_entry(blank.directory))
    cfg = V4Config.from_env(tmp_path / "candidate")
    cfg.ensure_dirs()
    store = V4Store(cfg.db_path)
    with writer_lease(cfg.data_dir, cfg.logs_dir, "quarantine regression") as lease:
        authority = publish_a_daily(cfg.data_dir, store, inputs, lease)
    isolated = {row["symbol"]: row["reason"] for row in authority["quarantine"]}
    assert set(isolated.values()) == {
        "TARGET_DATE_MISSING", "INVALID_BAR:non_positive_ohlc", "SUSPENSION_SOURCE_STALE_REVERIFY_REQUIRED",
    }
    symbols = ["000001.SZ", *isolated]
    for symbol in symbols:
        rows = [{**_bar(symbol, DAY, 11), "asof_date": DAY, "adj_factor": 1.0}]
        store.upsert_qfq_bars(rows)
    scores = cli.materialize_workbench_for_date(store, DAY, selection_groups=dict.fromkeys(symbols, "192"))
    by_code = {row["symbol"]: row for row in scores}
    assert by_code["000001.SZ"]["status"] != "QUARANTINED"
    for code, reason in isolated.items():
        row = by_code[code]
        assert (row["status"], row["score"], row["action"]) == ("QUARANTINED", None, "UNKNOWN")
        assert json.loads(row["detail_json"])["isolation_reasons"] == [reason]
    assert len(store.get_workbench_scores(DAY)) == len(symbols)
    with TestClient(create_app(cfg)) as client:
        response = client.get(f"/api/v4/research/workbench/days/{DAY}")
    assert response.status_code == 200
    http_rows = {row["symbol"]: row for row in response.json()["rows"]}
    good = http_rows["000001.SZ"]
    assert good["eligible_candidate"] is True and good["source_row"]["close"] == 11
    for code in isolated:
        row = http_rows[code]
        assert (row["status"], row["identity_gate"], row["eligible_candidate"]) == (
            "QUARANTINED", "QUARANTINED", False,
        )
        assert {"open", "close", "asof_date", "adj_factor", "volume"}.isdisjoint(row["source_row"])


def test_top200_uses_ex_dividend_reference_and_rejects_unverified_prior(tmp_path):
    # 600519.SH's 2026-06-26 ex-date, CNINFO 1225379934.PDF.
    # Reference ratio is derived from the announced cash dividend (RMB 28.02423).
    previous, target = "2026-06-25", "2026-06-26"
    code, comparator, missing = "600519.SH", "600000.SH", "000001.SZ"
    store = V4Store(tmp_path / "state.sqlite3")
    store.upsert_daily_bars([
        _bar(code, previous, 1212.10), _bar(code, target, 1168.63, 1212.10),
        _bar(comparator, previous, 100), _bar(comparator, target, 98, 100),
        _bar(missing, previous, 100), _bar(missing, target, 120, 100),
    ])
    store.upsert_adj_factors([
        {"market": "A", "symbol": s, "trade_date": d, "adj_factor": f}
        for s, d, f in (
            (code, previous, (1212.10 - 28.02423) / 1212.10), (code, target, 1),
            (comparator, previous, 1), (comparator, target, 1), (missing, target, 1),
        )
    ])
    bare = "000002.SZ"
    store.upsert_daily_bars([{
        **_bar(bare, target, 120, 100), "pre_close_trade_date": previous,
        "pre_close_basis": "STRUCTURED_SESSION_REFERENCE",
    }])
    store.upsert_adj_factors([
        {"market": "A", "symbol": bare, "trade_date": day, "adj_factor": 1}
        for day in (previous, target)
    ])
    ranked = build_daily_top200(store, target)
    assert [row["symbol"] for row in ranked] == [code, comparator]
    assert ranked[0]["pct_chg"] == round((1168.63 / 1184.08 - 1) * 100, 4)
    assert ranked[1]["pct_chg"] == -2
    assert [row["symbol"] for row in store.get_top200(target)] == [code, comparator]


def test_running_window_recovers_dead_or_expired_lease_and_fences_parallel_writer(tmp_path, monkeypatch):
    at_time = at(9, 35)
    exited_process = subprocess.Popen([sys.executable, "-c", "pass"])
    assert exited_process.wait(timeout=5) == 0
    started, release = Event(), Event()

    def running_workload(*args, **kwargs):
        started.set()
        assert release.wait(5)
        return {"status": "CANNOT_CONFIRM"}

    monkeypatch.setattr(cli, "run_slot", running_workload)
    for previous_pid, age, cause in [(exited_process.pid, 1, "PID_EXITED"), (os.getpid(), 601, "LEASE_EXPIRED")]:
        cfg = V4Config.from_env(tmp_path / cause)
        receipt = cfg.logs_dir / "daily_windows" / f"{DAY}_0935.jsonl"
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({
            "trade_date": DAY, "window": "09:35", "schedule_status": "RUNNING", "pid": previous_pid,
            "observed_at": (at_time - timedelta(seconds=age)).isoformat(),
            "heartbeat_at": (at_time - timedelta(seconds=age)).isoformat(),
            "lease_expires_at": (at_time - timedelta(seconds=age) + timedelta(seconds=600)).isoformat(),
            "attempt_id": "abandoned", "lease_token": "abandoned-token",
        }) + "\n")
        started.clear()
        release.clear()
        with ThreadPoolExecutor(max_workers=1) as pool:
            recovery = pool.submit(cli.run_scheduled_window, cfg, at_time)
            try:
                assert started.wait(1)
                assert cli.run_scheduled_window(cfg, at_time)["schedule_status"] == "ALREADY_RUNNING"
            finally:
                release.set()
            completed = recovery.result()
        attempts = [json.loads(line) for line in receipt.read_text().splitlines()]
        assert [row["schedule_status"] for row in attempts] == [
            "RUNNING", "STALE_RUNNING_RECOVERED", "RUNNING", "CANNOT_CONFIRM",
        ]
        assert attempts[1]["stale_reason"] == cause
        assert attempts[1]["stale_attempt_id"] == "abandoned"
        assert attempts[2]["attempt_id"] == completed["attempt_id"] != "abandoned"
        assert attempts[2]["lease_token"] == completed["lease_token"] != "abandoned-token"


    release.set()
    for intermediate_corruption in (False, True):
        cfg = V4Config.from_env(tmp_path / f"torn-{intermediate_corruption}")
        journal = cfg.logs_dir / "daily_windows" / f"{DAY}_0935.jsonl"
        journal.parent.mkdir(parents=True)
        saved = receipt.read_bytes().splitlines(keepends=True)[0]
        previous = json.loads(saved)
        previous["pid"] = exited_process.pid
        saved = (json.dumps(previous) + "\n").encode()
        torn = b'{"schedule_status":"DO'
        original = saved + (torn + b"\n" + saved if intermediate_corruption else torn)
        journal.write_bytes(original)
        if intermediate_corruption:
            blocked = cli.run_scheduled_window(cfg, at(9, 40), resume_window="09:35")
            assert blocked["reason"] == "INVALID_SLOT_JOURNAL"
            assert journal.read_bytes() == original
            continue
        later = cli.run_scheduled_window(cfg, at(9, 40))
        assert later["resumed_prior_windows"][0]["window"] == "09:35"
        records = [json.loads(line) for line in journal.read_bytes().splitlines()]
        assert [row["schedule_status"] for row in records] == [
            "RUNNING", "STALE_RUNNING_RECOVERED", "RUNNING", "CANNOT_CONFIRM",
        ]
        recovered = cfg.logs_dir / "daily_window_recovery" / (
            f"{journal.name}.{sha256(original).hexdigest()}.original"
        )
        assert recovered.read_bytes() == original


def test_evening_partial_can_resume_same_slot_and_finish_once(tmp_path):
    _, blank = snapshot(tmp_path)
    hour = research_entries(blank.directory)["hourly_announcements"]
    raw = json.loads((blank.directory / hour["source"]["path"]).read_bytes())
    raw["cannot_confirm"] = []
    raw["source_manifest"]["natural_execution_verified"] = True
    hour.update(status="READY", source=write_ref(blank.directory, "verified_hour.json", raw))
    root, inputs = snapshot(tmp_path, workloads={"hourly_announcements": hour})
    cfg = V4Config.from_env(tmp_path / "candidate")
    source_file = inputs.directory / hour["source"]["path"]
    late_bytes = source_file.read_bytes()
    index_bytes = (inputs.directory / "inputs.json").read_bytes()
    source_file.unlink()
    missing = cli.run_scheduled_window(cfg, at(19, 0), evidence_dir=root)
    assert missing["schedule_status"] == "CANNOT_CONFIRM"
    assert cli.run_scheduled_window(cfg, at(19, 0, 1), evidence_dir=root)["schedule_status"] == "ALREADY_ATTEMPTED"
    source_file.write_bytes(late_bytes)
    assert (inputs.directory / "inputs.json").read_bytes() == index_bytes
    partial = cli.run_scheduled_window(cfg, at(19, 1), evidence_dir=root)
    assert partial["schedule_status"] == "PARTIAL"
    assert cli.run_scheduled_window(cfg, at(19, 1, 1), evidence_dir=root)["schedule_status"] == "ALREADY_ATTEMPTED"
    hourly_path = cfg.data_dir / "review_inputs" / DAY / "hourly_announcements.json"
    hourly_bytes = hourly_path.read_bytes()
    hourly = {**json.loads(hourly_bytes), "publication_sha256": sha256(hourly_bytes).hexdigest()}
    link = observation_fixture(inputs.directory, hourly, "good")
    publish_json(inputs.directory / "inputs.json", {
        **inputs.payload, **link, "workloads": {**inputs.payload["workloads"], **link["workloads"]},
    })
    resumed = cli.run_scheduled_window(cfg, at(19, 7), evidence_dir=root, resume_window="19:00")
    assert resumed["schedule_status"] == "DONE"
    assert resumed["scheduled_for"] == partial["scheduled_for"]
    obs = resumed["paired_workloads"]["next_day_observation"]
    assert obs["target_date"] == NEXT_DAY and obs["upstream_hourly_publication_sha256"] == hourly["publication_sha256"]
    obs_path = cfg.data_dir / "review_inputs" / DAY / "next_day_observation.json"
    stat = obs_path.stat()
    assert cli.run_scheduled_window(
        cfg, at(19, 8), evidence_dir=root, resume_window="19:00",
    )["schedule_status"] == "ALREADY_ATTEMPTED"
    assert obs_path.stat() == stat and hourly_path.read_bytes() == hourly_bytes
    receipt = cfg.logs_dir / "daily_windows" / f"{DAY}_1900.jsonl"
    assert [json.loads(line)["schedule_status"] for line in receipt.read_text().splitlines()] == [
        "RUNNING", "CANNOT_CONFIRM", "RUNNING", "PARTIAL", "RUNNING", "DONE",
    ]


def test_auction_stage_normalizes_timestamps_to_beijing_before_cutoff():
    from v4_core.runner.main_windows import _raw_cutoff_verified

    source = {"window": "09:15-09:20", "cutoff_at": "09:20:00", "temporal_cutoff_safe": True}
    row = {"bar_time": "09:19:58", "temporal_cutoff_safe": "true"}
    for time, expected in (
        ("09:19:58", True),
        ("09:19:58+08:00", True),
        ("01:19:58+00:00", True),
        ("09:19:58+09:00", False),
        ("09:19:58-08:00", False),
        ("01:20:01+00:00", False),
    ):
        assert _raw_cutoff_verified(
            [{**row, "update_time": f"{DAY}T{time}"}], source, DAY, "STAGE_0925", "HK"
        ) is expected, time


def test_evening_explicit_lanes_can_gain_only_pinned_calendar_without_index_write(tmp_path):
    from test_v4_r16_authoritative_slots import FLAGS
    from v4_core.runner.evidence import DatedInputs
    from v4_core.runner.owner_inputs import read_owner_inputs
    from v4_core.runner.review_inputs import _next_a_session

    _, blank = snapshot(tmp_path)
    directory = blank.directory
    hour = research_entries(directory)["hourly_announcements"]
    source = json.loads((directory / hour["source"]["path"]).read_bytes())
    source["cannot_confirm"] = []
    source["source_manifest"]["natural_execution_verified"] = True
    hour.update(status="READY", source=write_ref(directory, "qualified_hour.json", source))
    candidate = write_ref(directory, "a_owner_pool.json", {
        "schema_version": "v3_5.preselection_pool.v1", "pool_id": "a_d1_premarket_pool",
        "market": "A", "trade_date": NEXT_DAY, "target_date": NEXT_DAY, "signal_date": DAY,
        "status": "V192_CANDIDATE_READY", "source_role": "SHARED_VERIFIED_V192",
        "source_row_count": 1, "stage_selection_eligible": True,
        "rows": [{"market": "A", "ts_code": "000001.SZ", "signal_date": DAY, "target_date": NEXT_DAY,
                  "pool_rank": 1, **FLAGS}], **FLAGS,
    })
    registry = write_ref(directory, "owner_pool_registry.json", {"a_d1_premarket_pool": candidate["sha256"]})
    root, explicit = snapshot(tmp_path, workloads={
        "hourly_announcements": hour, "next_day_observation": {
            "candidate_pool": candidate, "pool_registry": registry, "observed_at": at(19, 1).isoformat(),
        },
    })
    index = explicit.directory / "inputs.json"
    untouched = index.read_bytes()
    owner = tmp_path / "owner"
    owner.mkdir()
    calendar = tmp_path / "market_calendar.json"
    calendar.write_text(json.dumps({
        "year": 2026, "timezone": "Asia/Shanghai", "markets": {"a_share": {"holiday_periods": []}}
    }))
    digest = sha256(calendar.read_bytes()).hexdigest()
    assert read_owner_inputs(explicit, DAY, "evening", owner, calendar, "0" * 64) is explicit
    cfg = V4Config.from_env(tmp_path / "candidate")
    result = cli.run_scheduled_window(
        cfg, at(19, 1), evidence_dir=root, v35_owner_root=owner, a_calendar=calendar, a_calendar_sha256=digest,
    )
    assert result["schedule_status"] == "DONE"
    assert result["paired_workloads"]["next_day_observation"]["target_date"] == NEXT_DAY
    merged = read_owner_inputs(explicit, DAY, "evening", owner, calendar, digest)
    assert _next_a_session(merged) == NEXT_DAY
    assert index.read_bytes() == untouched and DatedInputs.load(root, DAY).sha256 == explicit.sha256
