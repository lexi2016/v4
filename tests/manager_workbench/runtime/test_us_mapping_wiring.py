"""Boundary canaries for the approved single-day wiring repair only."""
from copy import deepcopy
from types import SimpleNamespace
import hashlib
import json

import pytest

from v4.manager_workbench.contracts import RunContext
from v4.manager_workbench.engines.common import US_FACTOR_RULES_VERSION
from v4.manager_workbench.engines.us_mapping import run_us_mapping
from v4.manager_workbench.inputs.native import NativeAdapters
from v4.manager_workbench.inputs.us_universe import build_us_universe_contract
from v4.manager_workbench.inputs.validation import owner_digest

SHA = "a" * 64


def daily_batch(change="1.5"):
    universe = build_us_universe_contract()
    context = dict(target_date="20261020", phase="NEXT_DAY", cutoff="2026-10-20T05:44:13+08:00",
        source_sessions={"us": "20261019", "hk_price": "20261016"},
        rules_version=US_FACTOR_RULES_VERSION, scope_refs={})
    universe_ref = "us:" + universe["version"] + ":20261020"
    context["scope_refs"]["US_MAPPING"] = dict(universe_ref=universe_ref,
        configured_symbols=universe["symbols"], source_session="20261019",
        verification="VERIFIED", calendar_verified=True, sha256=SHA,
        universe_version=universe["version"], universe_contract=universe)
    contract = dict(schema_version="v4.manager_workbench.us_mapping_daily_run_contract.v1",
        state="VERIFIED", gaps=[], mode="NEXT_DAY", target_hk_date="20261020",
        us_source_session="20261019", cutoff=context["cutoff"],
        universe=dict(version=universe["version"], symbol_count=48,
            contract_sha256=universe["contract_sha256"], symbols_sha256=SHA),
        owners=dict(quote=dict(owner="quote-owner", artifact_sha256=SHA,
            receipt_sha256=SHA, manifest_sha256=SHA, available_at="2026-10-19T21:15:06Z"),
            connect=dict(target_eligibility="CANNOT_CONFIRM")))
    contract["contract_sha256"] = owner_digest(contract)
    context["scope_refs"]["US_MAPPING_RUN_CONTRACT_V1"] = contract
    membership = dict(status="VERIFIED", market="HK_CONNECT",
        owner="FUTU_HKCONNECT_PLATE_MEMBERSHIP", target_month="202610", source_date="20261012",
        artifact_sha256=SHA, codes=["HK.00001"],
        codes_sha256=owner_digest(dict(market="HK_CONNECT", codes=["HK.00001"])))
    records = [dict(record_role="SOURCE_CANDIDATE", us_symbol=symbol, source_session="20261019",
        owner="quote-owner", source_sha256=SHA, available_at="2026-10-19T21:15:06Z",
        positive_change_required=True, relations=[],
        evidence_ids=["source"], quote=dict(symbol=symbol, session_date="20261019", previous_close="100", last=str(100 + float(change)),
            change_pct=change)) for symbol in universe["symbols"]]
    nvda = next(record for record in records if record["us_symbol"] == "NVDA")
    nvda["relations"] = [dict(target_symbol="HK.00001", target_name="test issuer",
        relation_type="NAMED_TECHNOLOGY_INTEGRATION_CUSTOMER", status="REVIEWED",
        sha256=SHA, review_owner="reviewer", available_at="2026-10-13T12:36:18Z",
        published_at="2024-03-18T12:00:00Z", research_priority="PRIORITY")]
    records[0]["us_factor_payload"] = {"single_day_mapping_payload": {"monthly_membership": membership}}
    return context, dict(records=records, universe_ref=universe_ref, input_sha256=SHA,
        coverage=dict(scope_count=48, observed_count=48), gaps=[],evidence_refs=[dict(evidence_id="source",owner="quote-owner",role="US_MAPPING_SOURCE",
            verification="VERIFIED",sha256=SHA,available_at="2026-10-19T21:15:06Z")])


def mapping(context, batch, monkeypatch):
    monkeypatch.setattr("v4.manager_workbench.engines.us_mapping.run_us_factor",
        lambda *_: ([], {"industry_summary": {"source_status": "UNAVAILABLE"}}))
    result = run_us_mapping(context, batch)
    holder = next(row for row in result["rows"] if "us_factor_summary" in row)
    return result, holder["us_factor_summary"]["single_day_mapping"]


@pytest.mark.parametrize("change,decision,strict", [("1.5", "BENEFIT", "PENDING"), ("-1.5", "RISK", "REJECTED"), ("0.5", "OBSERVATION", "REJECTED")])
def test_real_lane_projection_preserves_sources_and_monthly_research_with_formal_unknown(monkeypatch, change, decision, strict):
    context, batch = daily_batch(change)
    result, daily = mapping(context, batch, monkeypatch)
    source = next(row for row in result["rows"] if row.get("us_symbol") == "NVDA")
    assert source["owner"] == "quote-owner"
    assert source["source_sha256"] == SHA and source["source_session"] == "20261019"
    assert source["diagnostic_gaps"] == ["CONNECT_MEMBERSHIP_UNKNOWN"]
    assert daily["rows"][0]["decision"] == decision
    assert daily["formal_target_eligibility"] == "CANNOT_CONFIRM"
    assert daily["strict_v1_status"] == "EXECUTED"
    assert daily["rows"][0]["strict_decision"] == strict
    assert daily["strict_selection"]["evaluation_complete"] is False
    assert daily["RESEARCH_ONLY"] and not any(daily[key] for key in
        ("production_allowed", "buy_gate_updated", "orders_sent"))


def test_catalog_display_rows_do_not_alias_source_relations_or_become_legacy_c_paths(monkeypatch):
    context, batch = daily_batch()
    batch["records"].append(dict(record_role="CATALOG_OBSERVATION", source_status="CATALOG_OBSERVATION",
        us_symbol=None, relations=[dict(target_symbol="HK.00001", relation_type="CATALOG_OBSERVATION_ONLY",
        status="CANNOT_CONFIRM", catalog_relation_id="R1", catalog_relation=dict(relation_id="R1",
            hk_code="00001", source_record={"关系编号": "R1", "code": "00001", "type": "BUSINESS_PEER",
            "asset_code": "NVDA", "fact": "dated comparison"}, recovery_v2r1={"closure_status": "OPEN"}))]))
    result, daily = mapping(context, batch, monkeypatch)
    assert len([r for r in result["rows"] if r.get("record_role") == "CATALOG_OBSERVATION"]) == 1
    paths=result["selection"]["candidates"][0]["paths"]
    catalog_paths=[p for p in paths if any(ref.get("ref")=="R1" for ref in p["source_refs"])]
    assert len(catalog_paths)==1 and catalog_paths[0]["scope"]=="pending"
    assert "RECOVERY_SCOPE_OPEN" in catalog_paths[0]["reasons"]
    assert all(p.get("relation_type") != "CATALOG_OBSERVATION_ONLY" for p in paths)
    assert daily["rows"][0]["decision"] == "BENEFIT"


@pytest.mark.parametrize("fault", ["source", "publication", "review"])
def test_missing_real_evidence_stays_blocked(monkeypatch, fault):
    context, batch = daily_batch()
    source = next(r for r in batch["records"] if r["us_symbol"] == "NVDA")
    relation = source["relations"][0]
    if fault == "source":
        source["source_sha256"] = None
    elif fault == "publication":
        relation["published_at"] = None
        relation["publication_time_gaps"] = ["RELATION_SOURCE_PUBLICATION_TIME_UNKNOWN"]
    else:
        relation["status"] = "PROPOSED"
    _, daily = mapping(context, batch, monkeypatch)
    assert daily["rows"][0]["decision"] == "UNASSESSED"
    assert daily["rows"][0]["reasons"]


def master_adapter(tmp_path):
    root = tmp_path / "shared"
    root.mkdir()
    raw = b"code\nHK.00001\n"
    (root / "master.csv").write_bytes(raw)
    manifest = dict(schema_version="v3_shared_data.hk_security_master_manifest.v1",
        trade_date="20261016", artifact_relative="master.csv", row_count=1,
        production_allowed=False, orders_sent=False,
        artifact_sha256=hashlib.sha256(raw).hexdigest(), captured_at="2026-10-16T17:30:19+08:00")
    data = json.dumps(manifest).encode()
    (root / "manifest.json").write_bytes(data)
    pin = dict(manifest_relative="manifest.json", manifest_sha256=hashlib.sha256(data).hexdigest(),
        artifact_relative="master.csv")
    config = SimpleNamespace(shared_root=root, source_bindings={}, dynamic_source_bindings=True)
    adapter = NativeAdapters(config)
    context = RunContext(target_date="20261020", phase="NEXT_DAY", trigger="SCHEDULED",
        cutoff="2026-10-20T05:44:13+08:00", source_sessions={"us": "20261019", "hk_price": "20261016"},
        rules_version=US_FACTOR_RULES_VERSION, scope_refs={"owner_bindings": {"us_mapping": {"frozen": SHA}}})
    return adapter, context, pin


def test_exact_master_binding_is_added_to_partial_context_without_refreshing_frozen_pins(tmp_path, monkeypatch):
    adapter, context, pin = master_adapter(tmp_path)
    prior = deepcopy(context.scope_refs["owner_bindings"]["us_mapping"])
    calls = []
    def resolve(config, ctx):
        calls.append(ctx.source_sessions["hk_price"])
        return pin
    monkeypatch.setattr("v4.manager_workbench.inputs.source_bindings.security_master", resolve)
    identity, refs = adapter._security_master_identity(context)
    assert identity["status"] == "READY"
    assert identity["source_date"] == "20261016" and identity["master_codes"] == ["HK.00001"]
    assert calls == ["20261016"] and refs
    assert context.scope_refs["owner_bindings"]["us_mapping"] == prior
    assert context.scope_refs["owner_bindings"]["security_master"] == pin
    adapter._security_master_identity(context)
    assert calls == ["20261016"]


def test_missing_master_records_gap_and_stays_unavailable(tmp_path, monkeypatch):
    adapter, context, _ = master_adapter(tmp_path)
    def missing(*_):
        raise ValueError("EXACT_DATE_MASTER_MISSING")
    monkeypatch.setattr("v4.manager_workbench.inputs.source_bindings.security_master", missing)
    identity, _ = adapter._security_master_identity(context)
    assert identity["status"] == "UNAVAILABLE"
    assert "security_master" not in context.scope_refs["owner_bindings"]
    assert context.scope_refs["owner_binding_gaps"]["security_master"] == "EXACT_DATE_MASTER_MISSING"


def test_existing_master_pin_is_never_replaced(tmp_path, monkeypatch):
    adapter, context, pin = master_adapter(tmp_path)
    context.scope_refs["owner_bindings"]["security_master"] = pin
    monkeypatch.setattr("v4.manager_workbench.inputs.source_bindings.security_master",
        lambda *_: pytest.fail("existing pin must not be refreshed"))
    identity, _ = adapter._security_master_identity(context)
    assert identity["status"] == "READY"
    assert context.scope_refs["owner_bindings"]["security_master"] == pin


@pytest.mark.parametrize("fault", ["artifact_sha", "capture_time", "date"])
def test_master_binding_keeps_real_sha_time_and_date_guards(tmp_path, monkeypatch, fault):
    adapter, context, pin = master_adapter(tmp_path)
    root = adapter.config.shared_root
    manifest = json.loads((root / "manifest.json").read_bytes())
    if fault == "artifact_sha":
        (root / "master.csv").write_bytes(b"code\nHK.00002\n")
    else:
        manifest["captured_at" if fault == "capture_time" else "trade_date"] = (
            "2026-10-20T06:00:00+08:00" if fault == "capture_time" else "20261015")
        raw = json.dumps(manifest).encode()
        (root / "manifest.json").write_bytes(raw)
        pin["manifest_sha256"] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr("v4.manager_workbench.inputs.source_bindings.security_master", lambda *_: pin)
    identity, refs = adapter._security_master_identity(context)
    assert identity["status"] == "UNAVAILABLE" and refs == []
