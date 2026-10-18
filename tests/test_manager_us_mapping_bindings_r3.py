import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from infrastructure.research_peripheral_store import ResearchPeripheralStore
from ops.materialize_research_peripherals import build_external_finance_payload
from ops.us_market_digest import build_us_market_snapshot
from v4.manager_workbench.contracts import Phase, RunContext
from v4.manager_workbench.engines.us_mapping import run_us_mapping
from v4.manager_workbench.inputs.native import NativeAdapters
from v4.manager_workbench.inputs import source_bindings
from v4.manager_workbench.inputs.us_universe import (
    LEGACY_US_SYMBOLS,
    build_legacy_us_universe_contract,
    build_us_universe_contract,
)


def _write(root: Path, relative: str, value: dict) -> str:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def test_source_binding_carries_configured_quote_scope_and_proposal_sources(tmp_path, monkeypatch):
    install_root = tmp_path / "com.lexi.v4.local"
    app_root = install_root / "releases" / "isolated-test" / "app"
    app_root.mkdir(parents=True)
    config_value = {"source_bindings": {"_extra": {"us_universe_extra_symbols": ["TSLA"]}}}
    config_path = install_root / "config" / "manager-workbench-v7.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(json.dumps(config_value), encoding="utf-8")
    monkeypatch.delenv("V4_MANAGER_WORKBENCH_CONFIG_PATH", raising=False)
    monkeypatch.setenv("V35_APP_ROOT", str(app_root))
    contract = build_us_universe_contract(["TSLA"])
    requested_urls = []
    quote_snapshot = build_us_market_snapshot(
        "20261016",
        capture_phase="POST_CLOSE",
        captured_at="2026-10-16T16:18:00-04:00",
        fetch_quotes=lambda url, _timeout: (requested_urls.append(url) or {
            symbol: dict(last=101.0, previous_close=100.0, session_date="20261016", session_time="16:00:00")
            for symbol in contract["symbols"] if symbol not in {"META", "PDD"}
        }),
    )
    assert len(requested_urls) == 1
    assert "usTSLA" in requested_urls[0]
    assert quote_snapshot["requested_symbol_count"] == 49
    assert len(quote_snapshot["quotes"]) == 47
    assert len(quote_snapshot["rows"]) == 24
    quote_root = tmp_path / "quotes"
    payload = build_external_finance_payload(
        "20261017",
        fetched_at="2026-10-17T07:00:00Z",
        subscriptions=(),
    )
    payload["market_snapshot"] = quote_snapshot
    payload["market_snapshot_status"] = quote_snapshot["status"]
    if quote_snapshot["status"] != "READY":
        payload["status"] = "CANNOT_CONFIRM"
    payload["us_session_captures"] = [dict(
        us_session_date="20261016",
        capture_phase="POST_CLOSE",
        session_timezone="America/New_York",
        capture_window_start="2026-10-16T16:15:00-04:00",
        capture_window_end="2026-10-16T16:20:00-04:00",
        capture_id="isolated-test-capture-20261016-post-close",
        run_id="isolated-test-run",
        captured_at="2026-10-16T16:18:00-04:00",
        capture_origin="ORIGINAL_TIME_CAPTURE",
        original_time_capture=True,
    )]
    store = ResearchPeripheralStore(quote_root)
    published = store.publish(payload)
    assert store.read_exact("20261017", "external_finance")["market_snapshot"] == quote_snapshot
    quote_relative = published["payload_path"]

    relation_root = tmp_path / "relations"
    evidence_relative = "legacy/evidence.json"
    review_relative = "legacy/review.json"
    evidence = {"schema_version": "frozen", "relations": [], "symbol_assessments": []}
    evidence["artifact_sha256"] = source_bindings.owner_digest(evidence)
    evidence_sha = _write(relation_root, evidence_relative, evidence)
    review = {
        "status": "PASS",
        "evidence_file_sha256": evidence_sha,
        "declared_artifact_sha256": evidence["artifact_sha256"],
        "recomputed_artifact_sha256": evidence["artifact_sha256"],
        "reviewer_identity": "isolated-test-reviewer",
        "reviewed_at": "2026-10-13T07:00:00Z",
        "reviewed_pairs": [],
        "reviewed_symbol_assessments": [],
        "safety": {"production_allowed": False},
    }
    _write(relation_root, review_relative, review)
    config = SimpleNamespace(
        us_root=quote_root,
        relation_root=relation_root,
        relation_evidence_relative=evidence_relative,
        relation_review_relative=review_relative,
        source_bindings={},
    )
    context = SimpleNamespace(
        source_sessions={"us": "20261016"},
        cutoff="2026-10-20T09:00:00+08:00",
        target_date="20261020",
    )
    monkeypatch.setattr(source_bindings, "priority_review", lambda *_: [])
    monkeypatch.setattr(source_bindings, "reviewed_seed", lambda *_: ([], []))
    monkeypatch.setattr(source_bindings, "us_factor_exposure", lambda *_: (None, [], None))
    monkeypatch.setattr(source_bindings, "hk_industry_classification", lambda *_: {"checked_files": []}, raising=False)

    pin = source_bindings.us_mapping(config, context)

    proposals = [card for card in pin["relation_projection"]["cards"] if card.get("status") == "PROPOSED"]
    assert pin["universe_version"] == "US_MAPPING_UNIVERSE_CONTRACT_V3"
    assert len(pin["configured_symbols"]) == 49
    assert pin["configured_symbols"][-1] == "TSLA"
    assert len(proposals) == 22
    registry_path = Path(source_bindings.__file__).resolve().parents[1] / "data" / "us_mapping_business_relations_20261014_v3.json"
    registry = json.loads(registry_path.read_text())
    assert registry["source_asof"] is None
    assert registry["pit_status"] == "PIT_UNCONFIRMED"
    assert registry["strict_selection_eligible"] is False
    assert all(source.get("supports") for relation in registry["relations"] for source in relation["sources"])
    assert not any("edgar/data/1526520/" in source["url"] for relation in registry["relations"] for source in relation["sources"])
    tcom_peer = next(relation for relation in registry["relations"]
        if relation.get("us_symbol") == "TCOM" and relation.get("hk_symbol") == "HK.00780")
    assert "annual reports" in tcom_peer["reason"]
    assert "20-F" not in tcom_peer["reason"]
    assert any(source["url"] == "https://www1.hkexnews.hk/listedco/listconews/sehk/2026/0428/2026042803041.pdf"
        for source in tcom_peer["sources"])
    assert all(card["pit_status"] == "PIT_UNCONFIRMED" for card in proposals)
    assert all(card["strict_selection_supported"] is False for card in proposals)
    assert all(card["relation_source_refs"] and card["relation_source_refs"][0]["url"].startswith("https://")
        for card in proposals)
    assert pin["relation_projection"]["strict_selection_eligible"] is False
    assert pin["source_gaps_by_symbol"]["META"] == ["QUOTE_SYMBOL_MISSING:META"]
    assert pin["source_gaps_by_symbol"]["PDD"] == ["QUOTE_SYMBOL_MISSING:PDD"]

    by_symbol = {}
    for card in proposals:
        by_symbol.setdefault(card["us_symbol"], set()).add(card["hk_symbol"])
    assert {"HK.00700", "HK.01024"}.issubset(by_symbol["META"])
    assert {"HK.00700", "HK.01024"}.issubset(by_symbol["GOOG"])
    assert {"HK.03690", "HK.09618"}.issubset(by_symbol["DASH"])
    assert {"HK.03690", "HK.09618"}.issubset(by_symbol["UBER"])
    assert {"HK.09961", "HK.00780"}.issubset(by_symbol["BKNG"])
    assert {"HK.09961", "HK.00780"}.issubset(by_symbol["EXPE"])
    assert {"HK.09961", "HK.00780"}.issubset(by_symbol["TCOM"])

    runtime_config = SimpleNamespace(
        source_bindings={"us_mapping": {"20261014": pin}},
        dynamic_source_bindings=False,
        capture_root=None,
    )
    adapter = NativeAdapters(runtime_config)
    monkeypatch.setattr(adapter, "membership", lambda *_: (set(), None, []))
    runtime_context = RunContext(
        target_date="20261014",
        phase=Phase.MANUAL,
        trigger="MANUAL",
        cutoff="2026-10-14T09:00:00+08:00",
        source_sessions={"us": "20261012"},
        rules_version="TEST_NO_FACTOR",
    )
    prepared = adapter.prepare_context(runtime_context)
    native_batch = adapter.us_mapping(prepared)
    assert len(native_batch.records) == 49
    assert native_batch.coverage.scope_count == 49
    assert sum(len(record["relations"]) for record in native_batch.records) == 22
    native_by_symbol = {record["us_symbol"]: record for record in native_batch.records}
    assert native_by_symbol["META"]["quote_missing_reason"] == "QUOTE_SYMBOL_MISSING:META"
    assert native_by_symbol["META"]["relations"][0]["status"] == "PROPOSED"
    assert native_by_symbol["META"]["relations"][0]["pit_status"] == "PIT_UNCONFIRMED"
    assert native_by_symbol["PDD"]["quote_missing_reason"] == "QUOTE_SYMBOL_MISSING:PDD"
    assert native_by_symbol["PDD"]["unmapped_disposition"]["status"] == "CANNOT_CONFIRM"

    engine_context = native_batch.context.model_dump(mode="python")
    engine_batch = native_batch.model_dump(mode="python")
    result = run_us_mapping(engine_context, engine_batch)
    assert len(result["rows"]) == 57
    assert all(row["decision"] != "SELECTED" for row in result["rows"])
    assert sum(row["reason"] == "US_RELATION_PROPOSED_PIT_UNCONFIRMED" for row in result["rows"]) == 20
    meta = next(row for row in result["rows"] if row.get("us_symbol") == "META")
    assert meta["reason"] == "QUOTE_SYMBOL_MISSING:META"
    assert meta["quote_missing_reason"] == "QUOTE_SYMBOL_MISSING:META"
    assert meta["decision"] == "UNASSESSED"
    assert meta["relation_status"] == "PROPOSED"
    assert meta["relation_pit_status"] == "PIT_UNCONFIRMED"
    assert "US_RELATION_PROPOSED_PIT_UNCONFIRMED" in meta["diagnostic_gaps"]
    assert {"OBSERVATION_ONLY", "NOT_STRICT_SELECTION", "PIT_UNCONFIRMED"}.issubset(set(meta["conditions"]))
    pdd = next(row for row in result["rows"] if row.get("us_symbol") == "PDD")
    assert pdd["reason"] == "QUOTE_SYMBOL_MISSING:PDD"
    assert pdd["quote_missing_reason"] == "QUOTE_SYMBOL_MISSING:PDD"
    assert "QUOTE_SYMBOL_MISSING:PDD" in pdd["diagnostic_gaps"]
    assert pdd["unmapped_disposition"]["status"] == "CANNOT_CONFIRM"
    assert pdd["unmapped_disposition"]["reason"] == "No HK target relationship is established in this proposal registry."
    assert {"OBSERVATION_ONLY", "NOT_STRICT_SELECTION"}.issubset(set(pdd["conditions"]))
    tsla = next(row for row in result["rows"] if row.get("us_symbol") == "TSLA")
    assert tsla["decision"] == "UNASSESSED"
    assert tsla["reason"] == "US_RELATION_UNMAPPED_CANNOT_CONFIRM"
    assert tsla["unmapped_disposition"]["status"] == "CANNOT_CONFIRM"
    assert "No HK target relationship is established for this configured US symbol." == tsla["unmapped_disposition"]["reason"]
    assert {"OBSERVATION_ONLY", "NOT_STRICT_SELECTION"}.issubset(set(tsla["conditions"]))

    # Exact legacy 33-symbol owner payload remains accepted without requiring the
    # version field that the active fixed-33 release did not emit.
    legacy_snapshot = build_us_market_snapshot(
        "20261012", capture_phase="POST_CLOSE", captured_at="2026-10-12T16:18:00-04:00",
        fetch_quotes=lambda _url, _timeout: {
            symbol: dict(last=101.0, previous_close=100.0, session_date="20261012", session_time="16:00:00")
            for symbol in contract["symbols"]
        },
    )
    legacy_snapshot["quotes"] = [quote for quote in legacy_snapshot["quotes"]
        if quote.get("symbol") in set(LEGACY_US_SYMBOLS)]
    legacy_snapshot.pop("universe_contract")
    legacy_snapshot["requested_symbol_count"] = 33
    legacy_snapshot["available_symbol_count"] = 33
    legacy_payload = build_external_finance_payload(
        "20261012", fetched_at="2026-10-13T07:00:00Z", subscriptions=(),
    )
    legacy_payload["market_snapshot"] = legacy_snapshot
    legacy_payload["market_snapshot_status"] = legacy_snapshot["status"]
    legacy_payload["us_session_captures"] = payload["us_session_captures"]
    legacy_store = ResearchPeripheralStore(tmp_path / "legacy-quotes")
    legacy_store.publish(legacy_payload)
    legacy_config = SimpleNamespace(
        us_root=tmp_path / "legacy-quotes", relation_root=relation_root,
        relation_evidence_relative=evidence_relative, relation_review_relative=review_relative,
        source_bindings={},
    )
    legacy_pin = source_bindings.us_mapping(legacy_config, context)
    legacy_contract = build_legacy_us_universe_contract()
    assert legacy_pin["universe_version"] == "US_MAPPING_UNIVERSE_CONTRACT_V2"
    assert legacy_pin["configured_symbols"] == legacy_contract["symbols"]
    assert not [card for card in legacy_pin["relation_projection"]["cards"] if card.get("status") == "PROPOSED"]
    legacy_pin.pop("universe_version")
    legacy_pin.pop("universe_contract")
    legacy_runtime_config = SimpleNamespace(
        source_bindings={"us_mapping": {"20261014": legacy_pin}},
        dynamic_source_bindings=False, capture_root=None,
    )
    legacy_adapter = NativeAdapters(legacy_runtime_config)
    monkeypatch.setattr(legacy_adapter, "membership", lambda *_: (set(), None, []))
    legacy_context = RunContext(
        target_date="20261014", phase=Phase.MANUAL, trigger="MANUAL",
        cutoff="2026-10-14T09:00:00+08:00", source_sessions={"us": "20261012"},
        rules_version="TEST_NO_FACTOR",
    )
    legacy_native = legacy_adapter.us_mapping(legacy_adapter.prepare_context(legacy_context))
    assert len(legacy_native.records) == 33
    assert legacy_native.coverage.scope_count == 33
    assert legacy_native.universe_ref == "us:US_MAPPING_UNIVERSE_CONTRACT_V2:20261014"
    assert "US_FIXED_33_QUOTES" in {ref.role for ref in legacy_native.evidence_refs}
    legacy_result = run_us_mapping(legacy_native.context.model_dump(mode="python"), legacy_native.model_dump(mode="python"))
    assert legacy_result["coverage"]["scope_count"] == 33
    assert not any(row["decision"] == "SELECTED" for row in legacy_result["rows"])


def test_us_mapping_receipt_fails_closed_on_producer_identity_and_allows_standard_receipt(tmp_path, monkeypatch):
    quote_root = tmp_path / "quotes"
    snapshot = build_us_market_snapshot(
        "20261016",
        capture_phase="POST_CLOSE",
        captured_at="2026-10-16T16:18:00-04:00",
        fetch_quotes=lambda _url, _timeout: {
            symbol: dict(last=101.0, previous_close=100.0, session_date="20261016", session_time="16:00:00")
            for symbol in LEGACY_US_SYMBOLS
        },
    )
    payload = build_external_finance_payload(
        "20261017", fetched_at="2026-10-17T07:00:00Z", subscriptions=(),
    )
    payload["market_snapshot"] = snapshot
    payload["market_snapshot_status"] = snapshot["status"]
    payload["us_session_captures"] = [dict(
        us_session_date="20261016",
        capture_phase="POST_CLOSE",
        session_timezone="America/New_York",
        capture_window_start="2026-10-16T16:15:00-04:00",
        capture_window_end="2026-10-16T16:20:00-04:00",
        capture_id="receipt-contract-test-20261016-post-close",
        run_id="receipt-contract-test-run",
        captured_at="2026-10-16T16:18:00-04:00",
        capture_origin="ORIGINAL_TIME_CAPTURE",
        original_time_capture=True,
    )]
    published = ResearchPeripheralStore(quote_root).publish(payload)
    quote_relative = published["payload_path"]
    receipt_relative = "receipts/research/peripherals/20261017/external_finance.json"
    receipt_path = quote_root / receipt_relative
    original_receipt_bytes = receipt_path.read_bytes()
    original_receipt = json.loads(original_receipt_bytes)
    # Normal producer receipts bind the payload and trade date; this optional
    # field is emitted only by the producer's late-capture contract.
    assert "us_session_date" not in original_receipt

    relation_root = tmp_path / "relations"
    evidence_relative, review_relative = "relations.json", "review.json"
    evidence = {"schema_version": "frozen", "relations": [], "symbol_assessments": []}
    evidence["artifact_sha256"] = source_bindings.owner_digest(evidence)
    evidence_sha = _write(relation_root, evidence_relative, evidence)
    review = {
        "status": "PASS", "evidence_file_sha256": evidence_sha,
        "declared_artifact_sha256": evidence["artifact_sha256"],
        "recomputed_artifact_sha256": evidence["artifact_sha256"],
        "reviewer_identity": "receipt-contract-reviewer", "reviewed_at": "2026-10-13T07:00:00Z",
        "reviewed_pairs": [], "reviewed_symbol_assessments": [],
        "safety": {"production_allowed": False},
    }
    _write(relation_root, review_relative, review)
    config = SimpleNamespace(
        us_root=quote_root, relation_root=relation_root,
        relation_evidence_relative=evidence_relative, relation_review_relative=review_relative,
        source_bindings={},
    )
    context = SimpleNamespace(
        source_sessions={"us": "20261016"}, cutoff="2026-10-20T09:00:00+08:00",
        target_date="20261020",
    )
    monkeypatch.setattr(source_bindings, "priority_review", lambda *_: [])
    monkeypatch.setattr(source_bindings, "reviewed_seed", lambda *_: ([], []))
    monkeypatch.setattr(source_bindings, "us_factor_exposure", lambda *_: (None, [], None))

    pin = source_bindings.us_mapping(config, context)
    assert pin["quote_relative"] == quote_relative
    assert pin["quote_sha256"] == hashlib.sha256((quote_root / quote_relative).read_bytes()).hexdigest()
    assert pin["owner_receipt_relative"] == receipt_relative
    assert pin["owner_receipt_sha256"] == hashlib.sha256(original_receipt_bytes).hexdigest()

    mutations = (
        lambda value: value.pop("trade_date"),
        lambda value: value.update(source="ai_news"),
        lambda value: value.update(payload_path="research/peripherals/20261016/external_finance.json"),
        lambda value: value.update(schema_version="v3_5.unknown_receipt.v1"),
        lambda value: value.update(payload_sha256="0" * 64),
        lambda value: value.update(market_snapshot_schema_version="v3_5.unknown_snapshot.v1"),
    )
    for mutation in mutations:
        tampered = dict(original_receipt)
        mutation(tampered)
        receipt_path.write_text(json.dumps(tampered, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        with pytest.raises(ValueError, match="US_OWNER_SESSION_ARTIFACT_NOT_FOUND"):
            source_bindings.us_mapping(config, context)
