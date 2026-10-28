"""Regression evidence for the bounded 2026-10-12 HK cutoff recovery."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


RELEASE_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "hk-0920-auto-stage-20261011-r1/app"
)
OVERLAY_APP = Path(
    "/Users/lexi/Desktop/学习/agents调试/V4_HK_CUTOFF_RECOVERY_20261012/overlay/app"
)
TRADE_DATE = "20261012"
STAGE_ID = "STAGE_0930_0935"
REASONS = [
    "PyTDX ExHQ batch coverage incomplete: completed=100/100",
    "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",
]


def _original_receipt() -> dict:
    return {
        "schema_version": "stage_center.runner.receipt.v1",
        "runner": "stage_center",
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "node_id": STAGE_ID,
        "status": "PARTIAL_WITH_ROWS",
        "due_status": "DUE",
        "dispatch_mode": "NATURAL",
        "node_outcome": "SETTLED_PARTIAL",
        "node_attempt_count": 1,
        "write_performed": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "candidate_run_id": "a-current-run-sentinel",
        "candidate_current_sha256": "a" * 64,
        "markets": {
            "A_SHARE": {
                "market": "A_SHARE",
                "status": "READY",
                "selection_status": "READY",
                "selected_rows": 7,
                "artifact_id": "a-selection-sentinel",
            },
            "HK_CONNECT": {
                "market": "HK_CONNECT",
                "status": "CANNOT_CONFIRM",
                "source_status": "CANNOT_CONFIRM",
                "selection_status": "CANNOT_CONFIRM",
                "selected_rows": 0,
                "write_performed": False,
                "cannot_confirm": REASONS,
            },
        },
    }


def _run_isolated(script: str, tmp_path: Path, *, overlay: bool, canonical: bool = False) -> None:
    import os

    roots = [str(RELEASE_APP)]
    if overlay:
        roots.insert(0, str(OVERLAY_APP))
    if canonical:
        roots.insert(0, str(Path(__file__).resolve().parents[1]))
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(roots)}
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, (
        f"isolated candidate check failed\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )


def test_release_base_reproduces_automatic_skip_for_settled_partial(tmp_path: Path) -> None:
    payload = json.dumps(_original_receipt(), separators=(",", ":"))
    _run_isolated(
        f"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import ops.run_stage_center_nodes as entry

date = {TRADE_DATE!r}
stage = {STAGE_ID!r}
now = datetime(2026, 10, 12, 9, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
node = entry.NODE_BY_ID[stage]
entry.NODES = (node,)
entry.NODE_BY_ID = {{stage: node}}
config = {{"receipt_root": Path({str(tmp_path / 'receipts')!r})}}
path = entry._receipt_path(config, date, stage)
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(json.loads({payload!r})), encoding="utf-8")
selected = entry._node_candidates(date, now, explicit_node=None, config=config)
assert all(node.stage_id != stage for node in selected), selected
""",
        tmp_path,
        overlay=False,
    )


def test_overlay_run_nodes_recovers_hk_only_and_preserves_a_receipt_and_artifact(
    tmp_path: Path,
) -> None:
    payload = json.dumps(_original_receipt(), separators=(",", ":"))
    _run_isolated(
        f"""
import copy, json, hashlib
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import ops.run_stage_center_nodes as entry

date = {TRADE_DATE!r}
stage = {STAGE_ID!r}
shanghai = ZoneInfo("Asia/Shanghai")
evaluated = datetime(2026, 10, 12, 9, 55, tzinfo=shanghai)
original_bytes = json.dumps(json.loads({payload!r}), ensure_ascii=False, sort_keys=True).encode()
original = json.loads(original_bytes)
receipt_root = Path({str(tmp_path / 'receipts')!r})
config = {{
    "receipt_root": receipt_root,
    "node_max_attempts": 3,
    "node_max_nodes_per_run": 10,
    "node_retry_backoff_seconds": 60,
    "safety": {{"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}},
}}
node = entry.NODE_BY_ID[stage]
entry.NODES = (node,)
entry.NODE_BY_ID = {{stage: node}}
receipt_path = entry._receipt_path(config, date, stage)
receipt_path.parent.mkdir(parents=True, exist_ok=True)
receipt_path.write_bytes(original_bytes)
a_artifact = Path({str(tmp_path / 'a-selection.json')!r})
a_artifact.write_bytes(b"A artifact sentinel\\n")

class Deadline:
    def pending_receipt_marker(self, path): return path.with_name(path.name + ".pending")
    def checkpoint(self, *args, **kwargs): pass
    def due(self, *args, **kwargs): pass
    def event(self, *args, **kwargs): pass
    def complete_receipt(self, path, result, *, rewrite): return result

entry._deadline = Deadline()
entry._calendar_gate = lambda trade_date, *, markets: {{"status": "ELIGIBLE", "trade_date": trade_date}}
entry._bounded_wait_until = lambda target, current, **kwargs: (current, 0.0)
entry._rearm_wall_now = lambda: evaluated + timedelta(minutes=5)
import stage_center.hk_0925_auto_substitute as substitute
substitute.maybe_publish_0925_substitute = lambda *args, **kwargs: {{"status": "NOT_REQUESTED"}}

class FakeRunner:
    def __init__(self):
        self.config = SimpleNamespace(receipt_root=receipt_root, backfill_run_id=None)
        self.state = {{"calls": 0, "decision": None}}
    def _receipt_path(self, trade_date, stage_id):
        return receipt_root / trade_date / stage_id / "receipt.json"
    def due_decisions(self, trade_date, evaluated_at, *, historical_backfill=False):
        scheduled = datetime(2026, 10, 12, 9, 35, tzinfo=shanghai)
        return [SimpleNamespace(status="LATE_CATCHUP_REPLAY", trade_date=trade_date,
                                stage_id=stage, scheduled_at=scheduled)]
    def _write_receipt(self, payload, trade_date, stage_id):
        result = {{"schema_version": "stage_center.runner.receipt.v1", "runner": "stage_center",
                  **payload, "trade_date": trade_date, "stage_id": stage_id, **entry.SAFETY_FLAGS}}
        scope = getattr(self, "_execution_scope", None)
        if scope is not None:
            result = scope.merge(result, trade_date, stage_id)
        path = self._receipt_path(trade_date, stage_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        return result
    def _run_one(self, decision):
        self.state["calls"] += 1
        self.state["decision"] = decision
        scope = self._execution_scope
        assert scope.markets == ("HK_CONNECT",)
        assert scope.prior["markets"]["A_SHARE"] == original["markets"]["A_SHARE"]
        assert decision.same_day_late_observation_recovery is True
        return {{
            "status": "PARTIAL_WITH_ROWS", "write_performed": True,
            "markets": {{"HK_CONNECT": {{
                "market": "HK_CONNECT", "status": "PARTIAL_WITH_ROWS",
                "selection_status": "PARTIAL_WITH_ROWS", "selected_rows": 1,
                "source_id": "pytdx_exhq", "write_performed": True,
                "source_evidence": ["active_snapshot_degraded_to_pytdx_observation=true"],
            }}}},
        }}

runner = FakeRunner()
result = entry.run_nodes(config, trade_date=date, evaluated_at=evaluated,
                         explicit_node=None, runner=runner, sleep=lambda _seconds: None)
assert runner.state["calls"] == 1, result
assert result["recovery"] is True, result
assert result["nodes"][0]["dispatch_mode"] == "RECOVERY", result
assert runner.state["decision"].same_day_late_observation_recovery is True
final = json.loads(receipt_path.read_text(encoding="utf-8"))
assert final["node_attempt_count"] == 2, final
assert final["execution_origin"] == "HK_ORIGINAL_BUDGET_RECOVERY", final
assert final["execution_markets"] == ["HK_CONNECT"], final
assert final["markets"]["A_SHARE"] == original["markets"]["A_SHARE"], final
assert final["candidate_run_id"] == original["candidate_run_id"], final
assert final["candidate_current_sha256"] == original["candidate_current_sha256"], final
assert a_artifact.read_bytes() == b"A artifact sentinel\\n"
digest = hashlib.sha256(original_bytes).hexdigest()
archive = receipt_path.parent / "attempt_evidence" / f"preserved-{{digest}}" / "PRIOR_RECEIPT.json"
assert archive.read_bytes() == original_bytes
""",
        tmp_path,
        overlay=True,
    )


def test_overlay_rejects_unknown_reason_exhaustion_and_keeps_observation_partial(
    tmp_path: Path,
) -> None:
    payload = json.dumps(_original_receipt(), separators=(",", ":"))
    _run_isolated(
        f"""
import copy, json
from pathlib import Path
from types import SimpleNamespace
import ops._run_stage_center_nodes_parts.stage_dispatch as dispatch
import ops.run_stage_center_nodes as entry
from stage_center.acquisition import SourceResult
import stage_center._live_collectors_parts.hk_minute as hk_minute
import stage_center.live_collectors as live_collectors

original = json.loads({payload!r})
shape = dispatch._same_day_hk_0930_0935_cutoff_recovery_shape
args = dict(mode="RECOVERY", trade_date="20261012", stage_id="STAGE_0930_0935",
            attempt_count=1, max_attempts=3)
assert shape(original, **args)
unknown = copy.deepcopy(original)
unknown["markets"]["HK_CONNECT"]["cannot_confirm"] = ["UNKNOWN_CAUSE"]
assert not shape(unknown, **args)
assert not shape(original, **{{**args, "trade_date": "20261013"}})
assert not shape(original, **{{**args, "attempt_count": 3}})
healthy = copy.deepcopy(original)
healthy["markets"]["HK_CONNECT"].update(status="READY", source_status="READY",
    selection_status="READY", selected_rows=1, write_performed=True, cannot_confirm=[])
assert not shape(healthy, **args)

continued = copy.deepcopy(original)
continued.update(status="CANNOT_CONFIRM", dispatch_mode="RECOVERY", node_outcome="TRANSIENT",
    node_attempt_count=2, execution_origin="HK_ORIGINAL_BUDGET_RECOVERY",
    execution_markets=["HK_CONNECT"], execution_pending=True,
    partial_commit_possible=True, write_performed=False)
continuation_args = {{**args, "attempt_count": 2}}
assert dispatch._continued_hk_0930_0935_recovery(continued, **continuation_args)
deadline = copy.deepcopy(continued)
deadline.update(status="PARTIAL_COMMIT_RETRY_REQUIRED", execution_pending=False,
    partial_commit_possible=True, write_performed=True,
    first_failed_layer="END_TO_END_DEADLINE", deadline_status="EXCEEDED",
    error="END_TO_END_5S_EXCEEDED_AFTER_RECEIPT_DURABILITY")
assert dispatch._continued_hk_0930_0935_recovery(deadline, **continuation_args)

unknown = copy.deepcopy(continued)
unknown.update(execution_pending=False, first_failed_layer="SCOPED_EXECUTION",
    error="RuntimeError:unknown provider failure")
unknown["markets"]["HK_CONNECT"]["cannot_confirm"] = ["RuntimeError:unknown provider failure"]
assert not dispatch._continued_hk_0930_0935_recovery(unknown, **continuation_args)
unknown_layer = copy.deepcopy(continued)
unknown_layer.update(execution_pending=False, first_failed_layer="COLLECTION_OR_PUBLICATION")
assert not dispatch._continued_hk_0930_0935_recovery(unknown_layer, **continuation_args)

auto_root = Path({str(tmp_path / 'auto-receipts')!r})
auto_config = {{
    "receipt_root": auto_root, "node_max_attempts": 3, "node_max_nodes_per_run": 10,
    "node_retry_backoff_seconds": 60,
    "safety": {{"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}},
}}
auto_path = entry._receipt_path(auto_config, "20261012", "STAGE_0930_0935")
auto_path.parent.mkdir(parents=True, exist_ok=True)
auto_path.write_text(json.dumps(unknown), encoding="utf-8")
unknown_bytes = auto_path.read_bytes()
now = __import__("datetime").datetime(2026, 10, 12, 9, 55, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai"))
node = entry.NODE_BY_ID["STAGE_0930_0935"]
entry.NODES = (node,)
entry.NODE_BY_ID = {{"STAGE_0930_0935": node}}
entry._calendar_gate = lambda trade_date, *, markets: {{"status": "ELIGIBLE", "trade_date": trade_date}}
entry._bounded_wait_until = lambda target, current, **kwargs: (current, 0.0)
entry._rearm_wall_now = lambda: now + __import__("datetime").timedelta(minutes=1)
class Deadline:
    def pending_receipt_marker(self, path): return path.with_name(path.name + ".pending")
    def checkpoint(self, *args, **kwargs): pass
    def due(self, *args, **kwargs): pass
    def event(self, *args, **kwargs): pass
    def complete_receipt(self, path, result, *, rewrite): return result
entry._deadline = Deadline()
import stage_center.hk_0925_auto_substitute as substitute
substitute.maybe_publish_0925_substitute = lambda *args, **kwargs: {{"status": "NOT_REQUESTED"}}
class FakeRunner:
    def __init__(self):
        self.config = SimpleNamespace(receipt_root=auto_root, backfill_run_id=None)
        self.calls = 0
    def _receipt_path(self, trade_date, stage_id):
        return auto_root / trade_date / stage_id / "receipt.json"
    def due_decisions(self, trade_date, evaluated_at, *, historical_backfill=False):
        return [SimpleNamespace(status="LATE_CATCHUP_REPLAY", trade_date=trade_date,
            stage_id="STAGE_0930_0935",
            scheduled_at=__import__("datetime").datetime(2026, 10, 12, 9, 35, tzinfo=evaluated_at.tzinfo))]
    def _run_one(self, decision):
        self.calls += 1
        raise AssertionError("invalid continuation must be rejected before provider execution")
runner = FakeRunner()
automatic = entry.run_nodes(auto_config, trade_date="20261012", evaluated_at=now,
    explicit_node=None, runner=runner, sleep=lambda _seconds: None)
assert automatic["nodes"][0]["first_failed_layer"] == "HK_RECOVERY_CONTINUATION_RECEIPT_INVALID", automatic
assert automatic["nodes"][0]["write_performed"] is False, automatic
assert runner.calls == 0
assert auto_path.read_bytes() == unknown_bytes

row = {{"code": "00700", "update_time": "2026-10-12 09:34:59", "last_price": 321.0}}
source = SourceResult(source_id="pytdx_exhq", status="PARTIAL_WITH_ROWS", rows=(row,),
    cannot_confirm=("PyTDX ExHQ batch coverage incomplete: completed=100/100",),
    requested_rows=1, source_evidence=("exhq_artifact_sha256=" + "a" * 64,))
live_collectors._shared_scripts_root = lambda value: Path(value)
live_collectors._scoped_process_runner = lambda _root, process_runner: process_runner
live_collectors._futu_hkconnect_active_snapshot = lambda *args, **kwargs: (
    {{}}, ("active_snapshot_temporal_cutoff_safe=false",),
    ("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",),
)
recovered = hk_minute._refresh_hk_active_lanes_body(
    vars(live_collectors), source, codes=("00700",), python_path="/fixture/python",
    shared_root=Path({str(tmp_path)!r}), process_runner=object(),
    trade_date="20261012", stage_id="STAGE_0930_0935", cutoff_at="09:35:00",
    same_day_late_observation_recovery=True,
)
assert recovered.status == "PARTIAL_WITH_ROWS"
assert recovered.source_id == "pytdx_exhq"
assert recovered.rows == source.rows
assert recovered.rows[0]["update_time"] == "2026-10-12 09:34:59"
assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in recovered.cannot_confirm
assert "active_snapshot_degraded_to_pytdx_observation=true" in recovered.source_evidence
assert "LIVE_HKCONNECT_GAINER" not in str(recovered.rows)
selection = live_collectors.production_selection_builders("STAGE_0930_0935")["HK_CONNECT"](
    recovered, SimpleNamespace(trade_date="20261012", stage_id="STAGE_0930_0935"),
    {{"artifact_sha256": "b" * 64, "status": recovered.status, "requested_rows": 1,
      "missing_symbols": (), "cannot_confirm": recovered.cannot_confirm,
      "source_evidence": recovered.source_evidence, "cutoff_at": "09:35:00"}},
)
assert selection["selection_status"] == "PARTIAL_WITH_ROWS"
assert selection["selected_rows"] == 1
assert selection["rows"][0]["action_level"] == "NO_BUY"
assert selection["rows"][0]["formal_eligible"] is False
assert selection["rows"][0]["source_last_bar_time"] == row["update_time"]
assert "active_snapshot_degraded_to_pytdx_observation=true" in selection["source_evidence"]
assert "hk_selection_mode=TDXPY_EXHQ_D1_TOP100_OBSERVATION" in selection["source_evidence"]
assert "LIVE_HKCONNECT_GAINER" not in str(selection["rows"])
""",
        tmp_path,
        overlay=True,
    )


def test_canonical_collector_keeps_cutoff_unsafe_exhq_rows_watch_only(tmp_path: Path) -> None:
    _run_isolated(
        f"""
from pathlib import Path
from types import SimpleNamespace
from stage_center.acquisition import SourceResult
from stage_center import live_collectors
from stage_center._live_collectors_parts import hk_minute
import stage_center.hk_stage8 as hk_stage8

row = {{"code": "HK.00376", "update_time": "2026-10-12 09:35:00",
        "open_price": 1.0, "last_price": 1.1, "high_price": 1.2, "low_price": 0.9}}
source = SourceResult(source_id="pytdx_exhq", status="PARTIAL_WITH_ROWS", rows=(row,),
    cannot_confirm=("PyTDX ExHQ batch coverage incomplete: completed=100/100",),
    requested_rows=1, source_evidence=("exhq_artifact_sha256=" + "a" * 64,))
hk_stage8.load_hk_active_snapshot = lambda *args, **kwargs: {{
    "status": "CANNOT_CONFIRM",
    "cannot_confirm": ("HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE",),
    "source_evidence": ("active_snapshot_temporal_cutoff_safe=false",),
}}
recovered = hk_minute._refresh_hk_active_lanes_body(
    vars(live_collectors), source, codes=("HK.00376",), python_path="/fixture/python",
    shared_root=Path({str(tmp_path)!r}), snapshot_root=Path({str(tmp_path / 'snapshot')!r}),
    process_runner=object(), trade_date="20261012", stage_id="STAGE_0930_0935",
    cutoff_at="09:35:05", pool_artifact_sha256="b" * 64,
    same_day_late_observation_recovery=True,
)
assert recovered.status == "PARTIAL_WITH_ROWS"
assert recovered.source_id == "pytdx_exhq"
assert recovered.rows == source.rows
assert recovered.rows[0]["update_time"] == "2026-10-12 09:35:00"
assert "HK_ACTIVE_SNAPSHOT_TEMPORAL_CUTOFF_UNSAFE" in recovered.cannot_confirm
assert "active_snapshot_degraded_to_pytdx_observation=true" in recovered.source_evidence
assert "observation_trade_status=WATCH_ONLY" in recovered.source_evidence
assert "LIVE_HKCONNECT_GAINER" not in str(recovered.rows)
selection = live_collectors.production_selection_builders("STAGE_0930_0935")["HK_CONNECT"](
    recovered, SimpleNamespace(trade_date="20261012", stage_id="STAGE_0930_0935"),
    {{"artifact_sha256": "c" * 64, "status": recovered.status, "requested_rows": 1,
      "missing_symbols": (), "cannot_confirm": recovered.cannot_confirm,
      "source_evidence": recovered.source_evidence, "cutoff_at": "09:35:05"}},
)
assert selection["selection_status"] == "PARTIAL_WITH_ROWS"
assert selection["selected_rows"] == 1
assert selection["rows"][0]["action_level"] == "NO_BUY"
assert selection["rows"][0]["formal_eligible"] is False
assert selection["rows"][0]["source_last_bar_time"] == row["update_time"]
assert "observation_trade_status=WATCH_ONLY" in selection["source_evidence"]
assert "LIVE_HKCONNECT_GAINER" not in str(selection["rows"])
""",
        tmp_path,
        overlay=False,
        canonical=True,
    )


def test_canonical_candidate_fails_closed_without_scoped_runner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from ops import run_stage_center_nodes as entry
    from ops._run_stage_center_nodes_parts import stage_dispatch

    receipt = _original_receipt()
    receipt_path = tmp_path / "receipt.json"
    monkeypatch.setattr(entry, "_calendar_gate", lambda trade_date, *, markets: {"status": "ELIGIBLE"})
    monkeypatch.setattr(entry, "_read_receipt", lambda *args: receipt)
    monkeypatch.setattr(entry, "_receipt_path", lambda *args: receipt_path)

    class Runner:
        calls = 0
        def _run_one(self, _decision):
            self.calls += 1
            raise AssertionError("the canonical candidate must not execute without scoped recovery support")

    runner = Runner()
    result = stage_dispatch.__dispatch_stage_body(
        vars(entry),
        {"node_max_attempts": 3, "node_retry_backoff_seconds": 60,
         "safety": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}},
        TRADE_DATE,
        STAGE_ID,
        __import__("datetime").datetime(2026, 10, 12, 9, 55, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")),
        mode="RECOVERY",
        runner=runner,
        precaptures=None,
    )
    assert result["status"] == "CANNOT_CONFIRM"
    assert result["first_failed_layer"] == "HK_ONLY_SCOPED_RECOVERY_CAPABILITY_UNAVAILABLE"
    assert result["write_performed"] is False
    assert runner.calls == 0
    assert not receipt_path.exists()

    receipt.update(
        status="CANNOT_CONFIRM", dispatch_mode="RECOVERY", node_outcome="TRANSIENT",
        node_attempt_count=2, execution_origin="HK_ORIGINAL_BUDGET_RECOVERY",
        execution_markets=["HK_CONNECT"], execution_pending=False,
        first_failed_layer="SCOPED_EXECUTION", error="RuntimeError:unknown provider failure",
        write_performed=False,
    )
    receipt["markets"]["HK_CONNECT"].update(
        status="CANNOT_CONFIRM", source_status="CANNOT_CONFIRM",
        selection_status="CANNOT_CONFIRM", selected_rows=0, write_performed=False,
        cannot_confirm=["RuntimeError:unknown provider failure"],
    )
    rejected = stage_dispatch.__dispatch_stage_body(
        vars(entry),
        {"node_max_attempts": 3, "node_retry_backoff_seconds": 60,
         "safety": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}},
        TRADE_DATE,
        STAGE_ID,
        __import__("datetime").datetime(2026, 10, 12, 9, 55, tzinfo=__import__("zoneinfo").ZoneInfo("Asia/Shanghai")),
        mode="RECOVERY",
        runner=runner,
        precaptures=None,
    )
    assert rejected["status"] == "CANNOT_CONFIRM"
    assert rejected["first_failed_layer"] == "HK_RECOVERY_CONTINUATION_RECEIPT_INVALID"
    assert rejected["write_performed"] is False
    assert rejected["recovery_rejected"] is True
    assert runner.calls == 0
    assert not receipt_path.exists()
