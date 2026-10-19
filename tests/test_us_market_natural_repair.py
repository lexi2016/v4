"""Hermetic protocol repair and the exceptional existing-slot recovery gate."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.data_store import _sha256
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from infrastructure.scheduling.executor_registry import FixedExecutorRegistry
from infrastructure.scheduling._executor_registry_parts.us_digest import parse_us_market_result
from ops.us_market_digest import build_us_market_phase_payload
from ops.run_us_market_slot import _failed_close_retry_context, _request_for_slot
from v4.manager_workbench.inputs.us_mapping_close_scope import digest

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "docs/handoffs/us_mapping_auto_close_20261020/quote_scope.json"
PREFIX = "2026-10-20 04:15:07 | OpenD connect ready\n2026-10-20 04:16:08 | Disconnected\n"


def owner(tmp_path, monkeypatch):
    monkeypatch.setenv("V4_US_MAPPING_CLOSE_SCOPE_PATH", str(CONFIG))
    monkeypatch.delenv("V4_US_MAPPING_WIRE_DIAGNOSTIC_DIR", raising=False)
    config = tmp_path / "owner-config.json"
    config.write_text(json.dumps({"source_bindings": {}}))
    monkeypatch.setenv("V4_MANAGER_WORKBENCH_CONFIG_PATH", str(config))
    symbols = json.loads(CONFIG.read_text())["symbols"]
    # A deliberately unverified inner symbol leaves the main48 parser alone.
    quotes = {"v_us" + s: dict(symbol="UNVERIFIED", last=101, previous_close=100,
                              session_date="20261019", session_time="16:00:01") for s in symbols}
    payload = build_us_market_phase_payload("20261020", us_session_date="20261019",
        capture_phase="POST_CLOSE", fetched_at="2026-10-19T20:15:02Z",
        capture_id="synthetic-natural", run_id="synthetic-natural",
        fetch_rss=lambda *_a, **_k: b"<rss><channel></channel></rss>",
        fetch_quotes=lambda *_a, **_k: quotes, now="2026-10-19T20:15:02Z")
    capture = payload["us_session_captures"][0]
    store = ResearchPeripheralStore(tmp_path)
    output = dict(status=payload["status"], source="external_finance", trade_date="20261020",
        target_trade_date="20261020", source_session_date="20261019", capture_us_session_date="20261019",
        capture_phase="POST_CLOSE", capture_id=capture["capture_id"], capture_run_id=capture["run_id"],
        capture_captured_at=capture["captured_at"], capture_capture_origin="ORIGINAL_TIME_CAPTURE",
        capture_origin="ORIGINAL_TIME_CAPTURE", capture_original_time=True, original_time_capture=True,
        late=False, reused=False, replaced=False, market_snapshot_status="READY",
        payload_path=store._relative("20261020", "external_finance"),
        receipt_path=store._receipt_relative("20261020", "external_finance"),
        payload_sha256=_sha256(payload), production_allowed=False, buy_gate_updated=False, orders_sent=False)
    return store, payload, output


class Ledger:
    """Only the ledger boundary is injected; the owner chain is real on disk."""
    def __init__(self, output):
        self.valid = True
        self.failed = dict(status="FAILED", business_date="20261020", scheduled_date="20261020",
            target_date="20261020", mode="LIVE", failure_class="CONTRACT", slot="0415",
            production_allowed=False, buy_gate_updated=False, orders_sent=False,
            selected_workload_ids=["us_market_digest"], run_id="synthetic-dispatch",
            receipt_path="receipts/live/20261020/0415/synthetic-dispatch.dispatch-receipt.json",
            ledger_sha256="a" * 64, workload_results=[dict(status="FAILED", failure_class="CONTRACT",
                reason="US_MARKET_CAPTURE_INVALID_RESULT", exit_code=0, modules=["ops.us_market_digest"],
                capture_phase="POST_CLOSE", us_session_date="20261019", production_allowed=False,
                buy_gate_updated=False, orders_sent=False, stdout=PREFIX + json.dumps(output))])
        self.extra = []

    def list_receipts(self, *_a, **_k):
        return [self.failed, *self.extra]

    def verify_receipt_chain(self, *_a, **_k):
        return self.valid, []

    def receipt_relative(self, request, *, run_id):
        return f"receipts/live/{request.business_date}/{request.slot}/{run_id}.dispatch-receipt.json"


def test_protocol_accepts_unique_object_with_sdk_text():
    assert parse_us_market_result(PREFIX + '{"status":"READY"}') == {"status": "READY"}
    assert parse_us_market_result('{\n "status":"READY"\n}') == {"status": "READY"}


@pytest.mark.parametrize("text", ["", "SDK only", "[]", '{}\n{}', '{}\n[]',
    '{"status":"READY","status":"READY"}', '{"status":NaN}', '{broken}\n{}'])
def test_protocol_rejects_missing_ambiguous_or_invalid_objects(text):
    with pytest.raises(ValueError):
        parse_us_market_result(text)


def test_actual_executor_keeps_owner_verification_after_noisy_stdout(tmp_path, monkeypatch):
    store, payload, output = owner(tmp_path, monkeypatch)
    registry = FixedExecutorRegistry(data_root=tmp_path, repo_root=ROOT)
    calls = []
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        store.publish(payload)
        return dict(status="SUCCEEDED", exit_code=0, stdout=PREFIX + json.dumps(output), stderr="")
    monkeypatch.setattr(registry, "_run", run)
    result = registry._us_market_digest(_request_for_slot(business_date="20261020", slot="0415"))
    assert len(calls) == 1
    assert result["receipt_verified"] and result["new_capture_verified"]
    assert result["data_update_status"] == "EXACT_NEW_CAPTURE_VERIFIED"


def test_exact_published_protocol_failure_arms_one_existing_fallback(tmp_path, monkeypatch):
    store, payload, output = owner(tmp_path, monkeypatch)
    store.publish(payload)
    ledger = Ledger(output)
    before = deepcopy(ledger.failed)
    result = _failed_close_retry_context(ledger=ledger, business_date="20261020", retry_slot="0515", data_root=tmp_path)
    assert result["failed_slot"] == "0415" and result["retry_slot"] == "0515"
    assert result["us_session_date"] == "20261019"
    assert ledger.failed == before
    ledger.extra.append({"slot": "0515"})
    assert _failed_close_retry_context(ledger=ledger, business_date="20261020", retry_slot="0515", data_root=tmp_path) is None


@pytest.mark.parametrize("change", ["chain", "reason", "ambiguous", "pure_json", "sha", "session", "late", "missing_owner", "tampered_receipt", "available_quote", "unknown_gap", "safety", "window"])
def test_recovery_rejects_other_contract_or_broken_owner(tmp_path, monkeypatch, change):
    store, payload, output = owner(tmp_path, monkeypatch)
    if change in {"available_quote", "unknown_gap"}:
        scope = payload["market_snapshot"]["scheduled_quote_scope"]
        if change == "available_quote":scope["available_symbol_count"] = 1
        else:scope["quote_failures"]["WMT"] = "OTHER_FAILURE"
        scope.pop("record_sha256");scope["record_sha256"] = digest(scope)
        output["payload_sha256"] = _sha256(payload)
    if change == "window":output["capture_captured_at"] = "2026-10-19T21:15:02Z"
    if change == "sha":output["payload_sha256"] = "b" * 64
    if change == "session":output["source_session_date"] = "20261016"
    if change == "late":output["late"] = True
    if change == "safety":output["orders_sent"] = True
    if change != "missing_owner":store.publish(payload)
    ledger = Ledger(output)
    row = ledger.failed["workload_results"][0]
    if change == "chain":ledger.valid = False
    if change == "reason":row["reason"] = "UNRELATED_CONTRACT"
    if change == "ambiguous":row["stdout"] += '\n{"status":"READY"}'
    if change == "pure_json":row["stdout"] = json.dumps(output)
    if change == "tampered_receipt":
        (tmp_path / store._receipt_relative("20261020", "external_finance")).write_text('{}')
    assert _failed_close_retry_context(ledger=ledger, business_date="20261020", retry_slot="0515", data_root=tmp_path) is None


def test_original_natural_artifact_is_not_reused_as_late(tmp_path, monkeypatch):
    from ops.us_market_digest import materialize_us_market_phase
    store, payload, _ = owner(tmp_path, monkeypatch)
    store.publish(payload)
    calls = []
    def stop_before_network(*_a, **_k):
        calls.append(True)
        raise RuntimeError("synthetic provider seam reached")
    # The existing publisher proceeds past natural/late reuse to collection.
    monkeypatch.setattr("ops.us_market_digest.build_us_market_phase_payload", stop_before_network)
    with pytest.raises(RuntimeError, match="synthetic provider"):
        materialize_us_market_phase(data_root=tmp_path, trade_date="20261020", capture_phase="POST_CLOSE",
            us_session_date="20261019", allow_late_post_close=True, now="2026-10-19T21:15:02Z")
    assert calls == [True]
