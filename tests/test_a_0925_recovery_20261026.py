"""Frozen regressions: 09:25 data-capable host and original-budget A-only retry."""
from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import infrastructure.tdx_minute_replay_provider as provider
import ops.run_stage_center_nodes as nodes
from ops._run_stage_center_nodes_parts import stage_dispatch as dispatch
from stage_center.scheduler import DueDecision


TZ = ZoneInfo("Asia/Shanghai")
NOW = datetime(2026, 10, 26, 11, 30, tzinfo=TZ)
FLAGS = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)


def test_auction_host_rejects_connected_empty_and_bar_only_endpoints(monkeypatch):
    import pytdx.config.hosts
    import pytdx.hq

    apis = []
    class API:
        def __init__(self, **kwargs):
            self.index = len(apis)
            self.closed = False
            self.calls = []
            apis.append(self)
        def connect(self, host, port, **kwargs):
            return True
        def get_security_bars(self, *args):
            self.calls.append(("bars", args))
            return [] if self.index == 0 else [{"close": 10}]
        def get_transaction_data(self, *args):
            self.calls.append(("current", args))
            return [] if self.index < 2 else [{"time": "11:29", "price": 10, "vol": 1}]
        def get_history_transaction_data(self, *args):
            raise AssertionError("same-day must use the current transaction method")
        def disconnect(self):
            self.closed = True
    monkeypatch.setattr(pytdx.config.hosts, "hq_hosts", [(str(i), str(i), 7709) for i in range(3)])
    monkeypatch.setattr(pytdx.hq, "TdxHq_API", API)
    api = provider._connected_api(transaction_probe=("20261026", True))
    assert api is apis[2]
    assert [a.closed for a in apis] == [True, True, False]
    assert ("current", (0, "000001", 0, 1800)) in apis[1].calls


def test_later_minute_connection_does_not_add_auction_probes(monkeypatch):
    import pytdx.config.hosts
    import pytdx.hq
    class API:
        def __init__(self, **kwargs): pass
        def connect(self, *args, **kwargs): return True
        def get_security_bars(self, *args): raise AssertionError("later stage changed")
    monkeypatch.setattr(pytdx.config.hosts, "hq_hosts", [("fixture", "1", 7709)])
    monkeypatch.setattr(pytdx.hq, "TdxHq_API", API)
    assert isinstance(provider._connected_api(), API)


def _prior():
    return dict(schema_version="stage_center.runner.receipt.v1", RESEARCH_ONLY=True,
        trade_date="20261026", stage_id="STAGE_0925", node_id="STAGE_0925",
        status="PARTIAL_WITH_ROWS", due_status="DUE", dispatch_mode="NATURAL",
        node_outcome="SETTLED_PARTIAL", node_attempt_count=1, retry_exhausted=False,
        write_performed=True, recorded_at="2026-10-26T01:25:27+00:00",
        candidate_current_sha256="c" * 64, candidate_run_id="frozen-candidate",
        markets={"A_SHARE": dict(market="A_SHARE", status="CANNOT_CONFIRM",
            source_status="CANNOT_CONFIRM", selection_status="CANNOT_CONFIRM",
            selected_rows=0, write_performed=False,
            cannot_confirm=["PYTDX_0925_REPLAY_ERROR:AuctionReplayError:pytdx returned no exact 09:25 auction transactions"]),
            "HK_CONNECT": dict(market="HK_CONNECT", selection_status="PARTIAL_WITH_ROWS",
                selected_rows=10, run_id="frozen-hk", rows=[{"sentinel": "unchanged"}])}, **FLAGS)


class Runner:
    def __init__(self, path, *, fail=False):
        self.path, self.fail = path, fail
        self.config = SimpleNamespace(receipt_root=path.parents[2], raw_root=path.parents[3]/"raw")
        self.calls = []
    def _receipt_path(self, *args): return self.path
    def due_decisions(self, trade_date, evaluated_at, **kwargs):
        return [DueDecision(stage_id="STAGE_0925", trade_date=trade_date,
            status="LATE_CATCHUP_REPLAY", scheduled_at=NOW.replace(hour=9, minute=25, second=5),
            idempotency_key="fixture", calendar={})]
    def _write_receipt(self, payload, trade_date, stage_id):
        result = dict(payload)
        if hasattr(self, "_execution_scope"):
            result = self._execution_scope.merge(result, trade_date, stage_id)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(result))
        return result
    def _run_one(self, decision):
        assert self._execution_scope.markets == ("A_SHARE",)
        reservation = json.loads(self.path.read_text())
        assert reservation["node_attempt_count"] == self._execution_scope.attempt_count
        assert reservation["execution_pending"] is True
        self.calls.append(decision)
        if self.fail:
            raise RuntimeError("fixture provider failure")
        return self._write_receipt(dict(status="PARTIAL_WITH_ROWS", write_performed=True,
            markets={"A_SHARE": dict(market="A_SHARE", selection_status="PARTIAL_WITH_ROWS",
                selected_rows=10, rows=[dict(trade_status="WATCH_ONLY")])}, **FLAGS),
            "20261026", "STAGE_0925")


def _setup(monkeypatch, tmp_path, *, prior=None, fail=False):
    prior = deepcopy(prior or _prior())
    config = dict(receipt_root=str(tmp_path/"receipts"), candidate_acquisition_root=str(tmp_path/"candidate"),
        node_max_attempts=3, node_retry_backoff_seconds=60, safety=FLAGS)
    path = tmp_path/"receipts"/"20261026"/"STAGE_0925"/"receipt.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(prior))
    runner = Runner(path, fail=fail)
    monkeypatch.setattr(nodes, "_calendar_gate", lambda *a, **k: dict(status="ELIGIBLE"))
    monkeypatch.setattr(nodes, "_rearm_wall_now", lambda: NOW)
    from stage_center import candidate_input
    monkeypatch.setattr(candidate_input, "read_candidate_input", lambda *a, **k:
        SimpleNamespace(current_sha256="c"*64, run_id="frozen-candidate", codes=("A.000001",)))
    return config, runner, prior


def _run(config, runner, *, now=NOW, mode="RECOVERY"):
    return nodes._dispatch_stage(config, "20261026", "STAGE_0925", now,
        mode=mode, runner=runner, precaptures=None)


def test_actual_dispatch_recovers_only_a_preserves_hk_and_stops_after_success(monkeypatch, tmp_path):
    config, runner, prior = _setup(monkeypatch, tmp_path)
    result = _run(config, runner)
    assert len(runner.calls) == 1
    assert result["node_attempt_count"] == 2
    assert result["markets"]["HK_CONNECT"] == prior["markets"]["HK_CONNECT"]
    assert result["execution_origin"] == "A_ORIGINAL_BUDGET_RECOVERY"
    assert result["dispatch_mode"] == "RECOVERY" and result["real_time_success"] is False
    assert list(runner.path.parent.glob("attempt_evidence/preserved-*/PRIOR_RECEIPT.json"))
    again = _run(config, runner)
    assert again["status"] == "SKIPPED_ALREADY_SETTLED"
    assert len(runner.calls) == 1


def test_actual_dispatch_crash_consumes_same_budget_and_keeps_hk(monkeypatch, tmp_path):
    config, runner, prior = _setup(monkeypatch, tmp_path, fail=True)
    result = _run(config, runner)
    assert result["node_attempt_count"] == 2
    assert result["markets"]["HK_CONNECT"] == prior["markets"]["HK_CONNECT"]
    assert result["node_outcome"] == "TRANSIENT"
    assert _run(config, runner)["status"] == "SKIPPED_RETRY_BACKOFF"
    later = NOW + timedelta(seconds=61)
    monkeypatch.setattr(nodes, "_rearm_wall_now", lambda: later)
    result = _run(config, runner, now=later)
    assert result["node_attempt_count"] == 3 and result["retry_exhausted"] is True
    assert _run(config, runner, now=later)["status"] == "SKIPPED_RETRY_EXHAUSTED"
    assert len(runner.calls) == 2


@pytest.mark.parametrize("mutation", ["candidate", "date", "budget", "positive", "safety", "issue11", "backoff", "malformed_reason"])
def test_recovery_gate_rejects_wrong_scope(monkeypatch, tmp_path, mutation):
    config, runner, prior = _setup(monkeypatch, tmp_path)
    if mutation == "candidate": prior["candidate_run_id"] = "changed"
    if mutation == "date": monkeypatch.setattr(nodes, "_rearm_wall_now", lambda: NOW+timedelta(days=1))
    if mutation == "budget": prior["node_attempt_count"] = 3
    if mutation == "positive": prior["markets"]["A_SHARE"]["selected_rows"] = 1
    if mutation == "safety": config["safety"] = {**FLAGS, "orders_sent": True}
    if mutation == "issue11": config["a_0925_recovery_authorization"] = {}
    if mutation == "backoff": prior["retry_after"] = (NOW+timedelta(seconds=30)).isoformat()
    if mutation == "malformed_reason": prior["markets"]["A_SHARE"]["cannot_confirm"] = None
    runner.path.write_text(json.dumps(prior))
    _run(config, runner)
    assert not runner.calls


def test_normal_node_selection_admits_only_eligible_settled_a_recovery(monkeypatch, tmp_path):
    config, runner, prior = _setup(monkeypatch, tmp_path)
    candidates = nodes._node_candidates("20261026", NOW, explicit_node=None, config=config)
    assert "STAGE_0925" in [n.node_id for n in candidates]


def test_failed_scoped_continuation_cannot_fall_back_to_both_markets(monkeypatch, tmp_path):
    config, runner, prior = _setup(monkeypatch, tmp_path, fail=True)
    _run(config, runner)
    failed = json.loads(runner.path.read_text())
    failed["candidate_run_id"] = "drift"
    runner.path.write_text(json.dumps(failed))
    later = NOW+timedelta(seconds=61)
    monkeypatch.setattr(nodes, "_rearm_wall_now", lambda: later)
    assert _run(config, runner, now=later)["status"] == "CANNOT_CONFIRM"
    assert len(runner.calls) == 1


def test_later_stage_and_old_issue11_cannot_use_new_recovery_gate(monkeypatch, tmp_path):
    config, runner, prior = _setup(monkeypatch, tmp_path)
    for date, stage in [("20261026", "STAGE_0930_0935"), ("20260930", "STAGE_0925")]:
        assert not dispatch._a_0925_original_budget_recovery(vars(nodes), config, prior,
            mode="RECOVERY", trade_date=date, stage_id=stage, evaluated_at=NOW,
            attempt_count=1, max_attempts=3)


def test_original_runner_pins_scoped_a_input_before_collection(monkeypatch, tmp_path):
    import stage_center.runner as runner_module
    from stage_center.candidate_input import CandidateInputError
    from stage_center._runner_parts.slot_execution import _StageCenterRunner__run_one_body
    calls = []
    def read(root, date, **kwargs):
        calls.append(kwargs)
        raise CandidateInputError("current.json SHA mismatch")
    monkeypatch.setattr(runner_module, "read_candidate_input", read)
    self = SimpleNamespace(config=SimpleNamespace(candidate_acquisition_root=tmp_path),
        _execution_scope=SimpleNamespace(markets=("A_SHARE",), prior=_prior(),
            origin="A_ORIGINAL_BUDGET_RECOVERY"),
        _write_receipt=lambda payload, *args: payload)
    decision = SimpleNamespace(trade_date="20261026", stage_id="STAGE_0925", status="LATE_CATCHUP_REPLAY")
    result = _StageCenterRunner__run_one_body(vars(runner_module), self, decision,
        historical_backfill=False, backfill_run_id=None, historical_markets=None)
    assert calls == [{"expected_current_sha256": "c"*64}]
    assert result["status"] == "CANNOT_CONFIRM" and result["write_performed"] is False
