"""A-share quote observations through actual collectors and production builder.

Only the external quote API, its subprocess transport, and market clock may
be simulated. SourceResult, the builder, and both final selectors are real.
The mutation caught by the first test is deleting prev_close_price from the
auction builder's source-row mapping.
"""
from __future__ import annotations

import csv
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import os
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

from infrastructure import tdx_minute_replay_provider as replay
from stage_center.acquisition import AcquisitionPlan, SourceResult, build_plan
from stage_center.candidate_input import CandidateInput
from stage_center.contracts import STAGE_BY_ID
from stage_center.live_collectors import collect_a_share_auction, collect_a_share_hq_minute, production_selection_builders
import stage_center.selection as selection

from research_fixture import publish_research_fixture


DATE = "20261009"
ALGORITHM_SHA = "eee20b08b50a693dd673f93937ef4eedc63e909295820a0141ce5e728a3754d2"
MISSING = object()
LIVE_STAGES = (
    "STAGE_0930_0935", "STAGE_0935_0940", "STAGE_0940_0945",
    "STAGE_0945_1030", "STAGE_1300_1315", "STAGE_1445_1500",
)


def make_plan(root: Path, stage: str, codes: tuple[str, ...]) -> AcquisitionPlan:
    candidate = CandidateInput(
        root=root, trade_date=DATE, current_relative="current.json",
        current_sha256="a" * 64, run_id="synthetic-a-pipeline",
        codes=codes, artifact_sha256="b" * 64, manifest_sha256="c" * 64,
        receipt_sha256="d" * 64, source_projection_sha256="e" * 64,
        source_evidence=("fixture=SYNTHETIC_EXTERNAL_INPUT",),
    )
    return build_plan(root, DATE, stage, candidate=candidate)


def through_builder(source: SourceResult, plan: AcquisitionPlan, *, research_root=None, trace=None):
    """Supply only the raw publication descriptor; retain business transforms."""
    raw = {
        "artifact_sha256": hashlib.sha256(json.dumps(source.rows, sort_keys=True, default=str).encode()).hexdigest(),
        "status": source.status,
        "requested_rows": source.requested_rows,
        "missing_symbols": source.missing_symbols,
        "cannot_confirm": source.cannot_confirm,
        "source_evidence": source.source_evidence,
        "cutoff_at": STAGE_BY_ID[plan.stage_id].cutoff,
    }
    builders = production_selection_builders(plan.stage_id, research_root=research_root)
    if trace is None:
        return builders["A_SHARE"](source, plan, raw)
    previous_profile = sys.getprofile()

    def observe(frame, event, arg):
        # Observe the real call boundary. No business function is replaced.
        if event == "call" and frame.f_code.co_name in {
            "_select_a_0925_auction_body", "_select_a_live_stage_body",
        }:
            trace["selector_body"] = frame.f_code.co_name
            trace["mapped_rows"] = copy.deepcopy(frame.f_locals["rows"])
        if previous_profile is not None:
            previous_profile(frame, event, arg)

    sys.setprofile(observe)
    try:
        return builders["A_SHARE"](source, plan, raw)
    finally:
        sys.setprofile(previous_profile)


def auction_file(root: Path, raw_rows: list[dict]):
    path = root / "generated_stages" / DATE / f"generated_stage1_0925_auction_{DATE}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in raw_rows for key in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(raw_rows)


def csv_row(previous=100, last=100, *, code="A.000001", amount=10_000_000):
    row = {
        "code": code, "name": "synthetic", "last_time": "2026-10-09 09:25:00",
        "last_close": last, "first_open": last,
        "amount_in_window": amount, "volume": 100_000,
    }
    if previous is not MISSING:
        row["prev_close_price"] = previous
    return row


def collect_csv(root: Path, raw_rows: list[dict], *, codes=None, trace=None):
    codes = tuple(codes or (row["code"] for row in raw_rows))
    plan = make_plan(root, "STAGE_0925", codes)
    auction_file(root, raw_rows)
    source = collect_a_share_auction(
        plan, codes=plan.codes_for("A_SHARE"), python_path=sys.executable,
        shared_root=root, auction_root=root,
    )
    assert isinstance(source, SourceResult)
    return source, through_builder(source, plan, trace=trace)


def assert_safety(envelope):
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert envelope[flag] is False
    assert all(row["action_level"] in {"NO_BUY", "WATCH_ONLY"} for row in envelope["rows"])
    assert envelope["algorithm_sha256"] == ALGORITHM_SHA
    assert len(envelope["rows"]) <= 10


@pytest.mark.parametrize("last,expected", [(102, 2), (100, 0), (95, -5)])
def test_auction_csv_previous_close_survives_source_builder_and_final_row(tmp_path, last, expected):
    trace = {}
    source, envelope = collect_csv(tmp_path, [csv_row(100, last)], trace=trace)
    assert source.rows[0]["prev_close_price"] == 100
    row = envelope["rows"][0]
    assert row["code"] == source.rows[0]["code"]
    assert row["prev_close_price"] == source.rows[0]["prev_close_price"]
    assert row["current_change_pct"] == expected
    assert row["qmt_gap_pct"] == expected
    assert row["current_change_pct_missing_reason"] is None
    assert trace["mapped_rows"][0]["prev_close_price"] == source.rows[0]["prev_close_price"]
    assert_safety(envelope)


@pytest.mark.parametrize("previous,normalized,reason", [
    (MISSING, None, "PREV_CLOSE_PRICE_MISSING"),
    (None, None, "PREV_CLOSE_PRICE_MISSING"),
    ("", None, "PREV_CLOSE_PRICE_MISSING"),
    (0, 0, "PREV_CLOSE_PRICE_INVALID"),
    (-5, -5, "PREV_CLOSE_PRICE_INVALID"),
    ("bad", None, "PREV_CLOSE_PRICE_MISSING"),
    ("NaN", None, "PREV_CLOSE_PRICE_MISSING"),
    ("inf", None, "PREV_CLOSE_PRICE_MISSING"),
    (True, None, "PREV_CLOSE_PRICE_MISSING"),
])
def test_auction_invalid_or_absent_source_baseline_stays_nullable(tmp_path, previous, normalized, reason):
    source, envelope = collect_csv(tmp_path, [csv_row(previous)])
    # The unchanged collector normalizes non-numeric wire input to None.
    # The final reason describes this observed SourceResult boundary.
    assert source.rows[0]["prev_close_price"] == normalized
    row = envelope["rows"][0]
    assert row["prev_close_price"] is None
    assert row["current_change_pct"] is None
    assert row["qmt_gap_pct"] is None
    assert row["current_change_pct_missing_reason"] == reason
    json.dumps(envelope, allow_nan=False)
    assert_safety(envelope)


def test_auction_csv_last_close_is_match_price_not_previous_close_alias(tmp_path):
    source, envelope = collect_csv(tmp_path, [csv_row(MISSING, last=109)])
    assert source.rows[0]["last_price"] == 109
    assert source.rows[0]["prev_close_price"] is None
    assert envelope["rows"][0]["current_change_pct"] is None
    assert envelope["rows"][0]["current_change_pct_missing_reason"] == "PREV_CLOSE_PRICE_MISSING"


def test_auction_recovered_source_drives_the_unchanged_bounded_formula(tmp_path):
    _, envelope = collect_csv(tmp_path, [csv_row(100, last=102)])
    # Frozen V3: 50 + 2 * 10 + (10m / 100m) * 2.5 = 70.25.
    assert envelope["rows"][0]["score"] == 70.25
    assert envelope["rows"][0]["stage_score"] == 70.25
    assert_safety(envelope)


class FixedMarketClock(datetime):
    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 10, 9, 9, 25, 3, tzinfo=ZoneInfo("Asia/Shanghai"))
        return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)


class AuctionWireApi:
    """Only external pytdx methods; all production provider code executes."""
    def __init__(self, records):
        self.records = records
        self.requested_codes = []

    def get_transaction_data(self, market, code, offset, count):
        self.requested_codes.append(code)
        record = self.records.get(code)
        if record is None:
            return []
        return [{"time": "09:25", "price": record["last"], "vol": record.get("volume", 100_000)}]

    def get_security_bars(self, category, market, code, start, count):
        previous = self.records[code].get("previous")
        if previous is None:
            return []
        return [
            {"year": 2026, "month": 10, "day": 8, "close": previous},
            {"year": 2026, "month": 10, "day": 9, "close": 999},
        ]

    def disconnect(self):
        pass


def collect_replay(root, monkeypatch, codes, records):
    monkeypatch.setattr(replay, "datetime", FixedMarketClock)
    api = AuctionWireApi(records)
    provider = replay.TdxMinuteReplayProvider(api_factory=lambda: api)
    plan = make_plan(root, "STAGE_0925", codes)
    source = collect_a_share_auction(
        plan, codes=plan.codes_for("A_SHARE"), python_path=sys.executable,
        shared_root=root, auction_root=root, replay_provider=provider,
    )
    return api, source, through_builder(source, plan)


def test_real_auction_replay_previous_day_bar_reaches_selected_row(tmp_path, monkeypatch):
    api, source, envelope = collect_replay(
        tmp_path, monkeypatch, ("A.000001",), {"000001": {"previous": 100, "last": 100}},
    )
    assert api.requested_codes == ["000001"]
    assert source.rows[0]["prev_close_price"] == 100
    assert source.rows[0]["source_method"] == "pytdx.hq.get_transaction_data"
    assert envelope["rows"][0]["prev_close_price"] == 100
    assert envelope["rows"][0]["current_change_pct"] == 0
    assert_safety(envelope)


def test_auction_216_requests_205_quotes_keep_missing_codes_and_after_200_winner(tmp_path, monkeypatch):
    codes = tuple(f"A.{index:06d}" for index in range(1, 217))
    records = {code[2:]: {"previous": 100, "last": 100} for code in codes[:205]}
    records[codes[204][2:]] = {"previous": 100, "last": 105}
    api, source, envelope = collect_replay(tmp_path, monkeypatch, codes, records)
    assert len(api.requested_codes) == source.requested_rows == envelope["requested_rows"] == 216
    assert len(source.rows) == envelope["source_rows"] == 205
    assert source.status == envelope["selection_status"] == "PARTIAL_WITH_ROWS"
    assert source.missing_symbols == codes[205:]
    assert envelope["missing_symbols"] == list(codes[205:])
    assert all(code in " ".join(envelope["cannot_confirm"]) for code in codes[205:])
    assert envelope["selected_rows"] == 10
    assert envelope["rows"][0]["code"] == codes[204]
    assert envelope["rows"][0]["prev_close_price"] == 100
    assert envelope["rows"][0]["current_change_pct"] == 5
    assert_safety(envelope)


FAKE_HQ_API = '''"""Synthetic pytdx network boundary, used only in offline tests."""
import json
import os
from pathlib import Path

class TdxHq_API:
    def __init__(self, **kwargs):
        self.wire = json.loads(Path(os.environ["A_QUOTE_WIRE_FIXTURE"]).read_text())

    def connect(self, host, port, **kwargs):
        return True

    def get_history_minute_time_data(self, market, code, trade_date):
        return self.wire.get(code, [])

    def disconnect(self):
        pass
'''


def quote_process_runner(root: Path, wire_by_code):
    """Run the actual production probe in a real child with a fake wire API."""
    fake_root = root / "synthetic_wire"
    package = fake_root / "pytdx"
    config = package / "config"
    config.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (config / "__init__.py").write_text("")
    (config / "hosts.py").write_text("hq_hosts = [('synthetic', '127.0.0.1', 0)]\n")
    (package / "hq.py").write_text(FAKE_HQ_API)
    wire_path = fake_root / "wire.json"
    wire_path.write_text(json.dumps(wire_by_code))
    calls = []

    def run(command, **kwargs):
        request = json.loads(kwargs["input"])
        calls.append(request)
        # The full production _PYTDX_HQ_PROBE stays byte-for-byte intact.
        assert command[1] == "-c"
        assert "get_history_minute_time_data" in command[2]
        env = dict(kwargs["env"])
        env["PYTHONPATH"] = str(fake_root) + os.pathsep + env.get("PYTHONPATH", "")
        env["A_QUOTE_WIRE_FIXTURE"] = str(wire_path)
        kwargs["env"] = env
        return subprocess.run(command, **kwargs)

    return run, calls


def minute_wire(previous=100, *, alias="last_close", last=100, amount=1_000_000):
    rows = []
    for index in range(240):
        row = {"price": last, "vol": 100_000, "amount": amount}
        if previous is not MISSING:
            row[alias] = previous
        rows.append(row)
    return rows


def collect_minute(root, stage, codes, wire, *, trace=None):
    plan = make_plan(root, stage, codes)
    runner, calls = quote_process_runner(root, wire)
    app = Path(selection.__file__).resolve().parent.parent
    source = collect_a_share_hq_minute(
        plan, codes=plan.codes_for("A_SHARE"), python_path=sys.executable,
        shared_root=app / "upstreams/v3_shared_data", process_runner=runner,
    )
    assert isinstance(source, SourceResult)
    research_root = root / "synthetic_research"
    publish_research_fixture(research_root, DATE, codes)
    return calls, source, through_builder(source, plan, research_root=research_root, trace=trace)


@pytest.mark.parametrize("stage", LIVE_STAGES)
@pytest.mark.parametrize("alias", ["last_close", "prev_close", "pre_close"])
def test_real_minute_probe_alias_to_source_qmt_to_final_true_zero(tmp_path, stage, alias):
    trace = {}
    calls, source, envelope = collect_minute(
        tmp_path, stage, ("A.000001",), {"000001": minute_wire(100, alias=alias, last=100)},
        trace=trace,
    )
    assert [code for call in calls for code in call["codes"]] == ["SZ.000001"]
    assert source.rows[0]["prev_close_price"] == 100
    assert source.rows[0]["last_price"] == 100
    row = envelope["rows"][0]
    assert row["code"] == source.rows[0]["code"]
    assert row["prev_close_price"] == 100
    assert row["current_change_pct"] == row["qmt_gap_pct"] == 0
    assert row["current_change_pct_missing_reason"] is None
    assert trace["mapped_rows"][0]["qmt"]["lastClose"] == source.rows[0]["prev_close_price"]
    assert trace["mapped_rows"][0]["qmt"]["lastPrice"] == source.rows[0]["last_price"]
    assert_safety(envelope)


@pytest.mark.parametrize("previous,reason", [
    (MISSING, "PREV_CLOSE_PRICE_MISSING"),
    (None, "PREV_CLOSE_PRICE_MISSING"),
    ("", "PREV_CLOSE_PRICE_MISSING"),
    (0, "PREV_CLOSE_PRICE_INVALID"),
    (-5, "PREV_CLOSE_PRICE_INVALID"),
    ("bad", "PREV_CLOSE_PRICE_MISSING"),
    ("NaN", "PREV_CLOSE_PRICE_INVALID"),
    ("inf", "PREV_CLOSE_PRICE_INVALID"),
])
def test_minute_source_missing_or_invalid_baseline_does_not_become_day_zero(tmp_path, previous, reason):
    _, source, envelope = collect_minute(
        tmp_path, LIVE_STAGES[0], ("A.000001",), {"000001": minute_wire(previous, last=100)},
    )
    row = envelope["rows"][0]
    assert row["prev_close_price"] is None
    assert row["current_change_pct"] is None
    assert row["qmt_gap_pct"] is None
    assert row["current_change_pct_missing_reason"] == reason
    json.dumps(envelope, allow_nan=False)
    assert_safety(envelope)


def test_minute_source_known_alias_precedence_does_not_replace_zero_with_other_alias(tmp_path):
    wire = minute_wire(0, alias="last_close")
    for row in wire:
        row["prev_close"] = 100
    _, source, envelope = collect_minute(tmp_path, LIVE_STAGES[0], ("A.000001",), {"000001": wire})
    assert source.rows[0]["prev_close_price"] == 0
    assert envelope["rows"][0]["prev_close_price"] is None
    assert envelope["rows"][0]["current_change_pct_missing_reason"] == "PREV_CLOSE_PRICE_INVALID"


@pytest.mark.parametrize("previous", [True, False])
def test_minute_boolean_previous_close_never_becomes_a_numeric_day_baseline(tmp_path, previous):
    _, source, envelope = collect_minute(
        tmp_path, LIVE_STAGES[0], ("A.000001",), {"000001": minute_wire(previous)},
    )
    # A boolean is malformed quote data, including True (float(True) == 1).
    assert source.rows[0]["prev_close_price"] is None
    assert envelope["rows"][0]["prev_close_price"] is None
    assert envelope["rows"][0]["current_change_pct"] is None
    assert envelope["rows"][0]["current_change_pct_missing_reason"] == "PREV_CLOSE_PRICE_MISSING"
    assert_safety(envelope)


@pytest.mark.parametrize("stage", LIVE_STAGES)
def test_minute_216_requests_206_quotes_keep_top10_without_200_input_cap(tmp_path, stage):
    codes = tuple(f"A.{index:06d}" for index in range(1, 217))
    wire = {code[2:]: minute_wire(100) for code in codes[:206]}
    wire[codes[205][2:]] = minute_wire(100, last=105, amount=100_000_000)
    calls, source, envelope = collect_minute(tmp_path, stage, codes, wire)
    requested = [code for call in calls for code in call["codes"]]
    assert requested == ["SZ." + code[2:] for code in codes]
    assert source.requested_rows == envelope["requested_rows"] == 216
    assert len(source.rows) == envelope["source_rows"] == 206
    assert source.status == envelope["selection_status"] == "PARTIAL_WITH_ROWS"
    assert source.missing_symbols == tuple("SZ." + code[2:] for code in codes[206:])
    assert envelope["missing_symbols"] == list(source.missing_symbols)
    assert len(source.missing_symbols) == 10
    assert envelope["selected_rows"] == 10
    assert envelope["rows"][0]["code"] == "SZ.000206"
    assert envelope["rows"][0]["prev_close_price"] == 100
    assert envelope["rows"][0]["current_change_pct"] == 5
    assert_safety(envelope)


def test_formula_sort_limit_and_existing_null_projection_bytes_are_frozen():
    app = Path(selection.__file__).resolve().parent.parent
    manifest = json.loads((Path(__file__).resolve().parents[1] / "BASELINE_A_SHA.json").read_text())
    immutable = {
        "stage_center/selection.py", "stage_center/contracts.py",
        "stage_center/_selection_parts/market_quality.py",
        "stage_center/_selection_parts/selection_envelope.py",
        "stage_center/_selection_parts/a_auction.py", "stage_center/_selection_parts/a_live.py",
    }
    for entry in manifest["files"]:
        if entry["path"] in immutable:
            assert hashlib.sha256((app / entry["path"]).read_bytes()).hexdigest() == entry["sha256"], entry["path"]
