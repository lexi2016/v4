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


@pytest.mark.parametrize("inner", ["WMT", "WMT.N", "WMT.OQ", "WMT.PS", "WMT.AM"])
def test_wire_exchange_qualification_matches_exact_key(inner):
    from v4.manager_workbench.inputs.us_mapping_close_scope import _provider_symbol_conflicts
    assert _provider_symbol_conflicts(f'v_usWMT="200~synthetic~{inner}~";'.encode()) == set()
    assert _provider_symbol_conflicts('v_usBRK.B="200~synthetic~BRK.B.N~";') == set()


@pytest.mark.parametrize("inner", ["KO.N", "OTHER", "WMT.L", "WMT.N.EXTRA", "WMTN", "", "US.WMT.N"])
def test_wire_unknown_exchange_or_different_ticker_stays_quarantined(inner):
    from v4.manager_workbench.inputs.us_mapping_close_scope import _provider_symbol_conflicts
    assert _provider_symbol_conflicts(f'v_usWMT="200~synthetic~{inner}~";') == {"WMT"}
    # Explicit Mapping records keep their existing strict identity contract.
    assert _provider_symbol_conflicts({"WMT": {"symbol": "WMT.N"}}) == {"WMT"}


def test_saved_actual_wire_has_488_valid_and_59_isolated(monkeypatch):
    from collections import Counter
    from ops.us_market_digest import build_us_market_snapshot
    from v4.manager_workbench.inputs.us_universe import build_us_universe_contract
    from infrastructure.research_peripheral_store import _validate_market_snapshot
    path = ROOT / "docs/handoffs/us_mapping_auto_close_20261020/natural_20261020/local_only" / (
        "us-quote-wire-20261019-9a2de44927e53cb8cc12d81f9ebf1e87a4bd18504299ca75c61f048e6e7b5457.bin")
    if not path.exists():
        pytest.skip("Retained actual response stays local; hermetic synthetic wire cases remain portable")
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "9a2de44927e53cb8cc12d81f9ebf1e87a4bd18504299ca75c61f048e6e7b5457"
    monkeypatch.setenv("V4_US_MAPPING_CLOSE_SCOPE_PATH", str(CONFIG))
    monkeypatch.delenv("V4_US_MAPPING_WIRE_DIAGNOSTIC_DIR", raising=False)
    calls = []
    def fetch(*_):
        calls.append(True)
        return raw
    value = build_us_market_snapshot("20261019", captured_at="2026-10-19T21:15:06Z",
        universe_contract=build_us_universe_contract(), fetch_quotes=fetch)
    assert calls == [True]
    _validate_market_snapshot(value)
    assert value["status"] == "READY" and value["available_symbol_count"] == 48
    scope = value["scheduled_quote_scope"]
    assert scope["state"] == "PARTIAL" and scope["available_symbol_count"] == 488
    assert Counter(scope["quote_failures"].values()) == {
        "QUOTE_SESSION_DATE_MISMATCH_CAPTURE": 10, "QUOTE_PREVIOUS_CLOSE_ZERO": 1,
        "QUOTE_PROVIDER_TIMESTAMP_BEFORE_OFFICIAL_CLOSE": 42, "QUOTE_SYMBOL_MISSING": 6}
    observed = {q["symbol"]: q for q in scope["quotes"]}
    for symbol, change in [("WMT", -0.092585), ("KO", -0.511182), ("PG", -1.041732)]:
        assert observed[symbol]["change_pct"] == change


def _publication_hash_fixture(tmp_path, monkeypatch):
    """Isolate only publication hash binding; no real owner or authority IO."""
    import runpy
    import sys
    import infrastructure.data_store as data_store
    import infrastructure.research_peripheral_store as peripheral
    import infrastructure.scheduling.execution_ledger as execution
    helper = ROOT / "docs/handoffs/us_mapping_auto_close_20261020/natural_20261020/publish_prepared_recovery.py"
    module = runpy.run_path(str(helper))
    main = module["main"]
    main.__globals__.update(HERE=tmp_path, WT=tmp_path, BASE=tmp_path / "authority")
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    manifest = candidate_root / "release-manifest.json"
    manifest.write_text('{}')
    hash_file = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    candidate = dict(candidate=str(candidate_root), manifest_sha256=hash_file(manifest),
        original_plist_sha256="1" * 64, proposed_plist_sha256="2" * 64, source_test_sha256={})
    payload = tmp_path / "payload.json"
    payload.write_text('{}')
    recovery = dict(payload_relative="payload.json", payload_sha256=hash_file(payload),
        expected_old_cas_sha256="a" * 64, predicted_receipt_sha256="b" * 64,
        provenance=dict(identity="SAVED_NATURAL_RESPONSE_PROCESSING_RECOVERY",
                        captured_at="2000-01-01T00:00:00Z", processing_at="2000-01-01T01:00:00Z"))
    # Supply the capture field the helper checks independently of schema QA.
    payload.write_text(json.dumps({"market_snapshot": {"captured_at": recovery["provenance"]["captured_at"]}}))
    recovery["payload_sha256"] = hash_file(payload)
    prepared = dict(source_test_sha256={}, publish_helper_sha256=hash_file(helper),
        candidate=candidate["candidate"], candidate_manifest_sha256=candidate["manifest_sha256"],
        original_plist_sha256=candidate["original_plist_sha256"], proposed_plist_sha256=candidate["proposed_plist_sha256"],
        recovery_payload_sha256=recovery["payload_sha256"], expected_old_cas_sha256=recovery["expected_old_cas_sha256"],
        predicted_receipt_sha256=recovery["predicted_receipt_sha256"], failed_receipts_raw_sha256={})
    for slot, run in [("0415", "b69405c9b5214af7a24529ff6e6a9c36"), ("0515", "2f16d9f8bc6e4d7088dea33a05d1035e")]:
        p = tmp_path / "authority/state/dispatcher/receipts/live/20261020" / slot / (run + ".dispatch-receipt.json")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{}')
        prepared["failed_receipts_raw_sha256"][slot] = hash_file(p)
    calls = dict(read=0, publication=0, current="a" * 64)
    class Store:
        def __init__(self, *_):pass
        def read_exact(self, *_):
            calls["read"] += 1
            return {"test_sha": calls["current"]}
        def replace(self, *_a, **_k):
            calls["publication"] += 1
            raise RuntimeError("unexpected publication")
    monkeypatch.setattr(peripheral, "ResearchPeripheralStore", Store)
    monkeypatch.setattr(peripheral, "validate_research_peripheral", lambda *_a, **_k: None)
    monkeypatch.setattr(data_store, "_sha256", lambda value: value["test_sha"])
    monkeypatch.setattr(execution, "ExecutionLedger", lambda *_: SimpleNamespace(verify_receipt_chain=lambda *_a, **_k: (True, [])))
    def seal():
        for name, value in [("WIRE_CANDIDATE.json", candidate), ("WIRE_RECOVERY_PREPARED.json", recovery)]:
            (tmp_path / name).write_text(json.dumps(value))
        prepared["candidate_receipt_sha256"] = hash_file(tmp_path / "WIRE_CANDIDATE.json")
        prepared["recovery_receipt_sha256"] = hash_file(tmp_path / "WIRE_RECOVERY_PREPARED.json")
        (tmp_path / "WIRE_REPAIR_PREPARED.json").write_text(json.dumps(prepared))
        monkeypatch.setattr(sys, "argv", [str(helper), "--expected-prepared-sha", hash_file(tmp_path / "WIRE_REPAIR_PREPARED.json")])
    seal()
    return main, seal, candidate, recovery, prepared, calls


@pytest.mark.parametrize("change", ["candidate_raw", "recovery_raw", "candidate_root", "manifest", "proposal", "old_cas", "new_payload", "predicted_receipt"])
def test_publication_rejects_secondary_receipt_drift_before_owner_read(tmp_path, monkeypatch, change):
    main, seal, candidate, recovery, prepared, calls = _publication_hash_fixture(tmp_path, monkeypatch)
    if change in {"candidate_raw", "recovery_raw"}:
        path = tmp_path / ("WIRE_CANDIDATE.json" if change == "candidate_raw" else "WIRE_RECOVERY_PREPARED.json")
        path.write_bytes(path.read_bytes() + b" ")
    else:
        if change == "candidate_root":candidate["candidate"] = str(tmp_path / "other")
        if change == "manifest":candidate["manifest_sha256"] = "3" * 64
        if change == "proposal":candidate["proposed_plist_sha256"] = "3" * 64
        if change == "old_cas":recovery["expected_old_cas_sha256"] = "5dbf" + "0" * 60
        if change == "new_payload":recovery["payload_sha256"] = "3" * 64
        if change == "predicted_receipt":recovery["predicted_receipt_sha256"] = "3" * 64
        seal()  # Even a hash-linked secondary receipt cannot contradict top-level fields.
    with pytest.raises(AssertionError):main()
    assert calls["read"] == calls["publication"] == 0


def test_publication_ignores_read_text_tamper_and_keeps_frozen_cas(tmp_path, monkeypatch):
    main, _, _, recovery, _, calls = _publication_hash_fixture(tmp_path, monkeypatch)
    real_read = Path.read_text
    attacks = []
    def forged(path, *_a, **_k):
        if path.name == "WIRE_RECOVERY_PREPARED.json":
            attacks.append(True)
            return json.dumps(dict(recovery, expected_old_cas_sha256="5dbf" + "0" * 60))
        return real_read(path, *_a, **_k)
    monkeypatch.setattr(Path, "read_text", forged)
    calls["current"] = "5dbf" + "0" * 60
    with pytest.raises(AssertionError, match="owner drift"):
        main()
    assert attacks == []  # Hashing and parsing use the very same sealed bytes.
    assert calls["read"] == 1 and calls["publication"] == 0
