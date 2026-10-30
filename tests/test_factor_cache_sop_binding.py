"""Pinned SOP consumer bindings; synthetic bytes, no provider or network."""
import copy
import json
from pathlib import Path

import pytest

from ops import research_panel_factor_cache as fc


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))
    return dict(path=str(path), sha256=fc.sha(path))


@pytest.fixture
def bindings(tmp_path, monkeypatch):
    originals = json.loads(fc._LIFECYCLE_ASSET_PATH.read_text())["verified_delistings"]
    codes = set(fc._CONTROLLER_ARTIFACTS) | {"601198.SH", "601059.SH"}
    facts = {f["ts_code"]: copy.deepcopy(f) for f in originals if f["ts_code"] in codes}
    approved = dict(schema="controller_relayed_lineage_fact_set.v1", consumer_independent_review="PENDING",
                    delisting_facts={}, quality_caveats={}, bound_primary_artifacts={})
    brokers = dict(facts=[])
    rows = {}
    for code, fact in facts.items():
        source = tmp_path / (code + ".source")
        source.write_bytes(("original evidence " + code).encode())
        source_ref = dict(path=str(source), sha256=fc.sha(source), url="https://example.invalid/" + code)
        if code in fc._CONTROLLER_ARTIFACTS:
            quality = fact["source_quality"]
            source_ref["source_quality"] = quality
            caveat = quality != "PRIMARY_SOURCE_BYTES_CAPTURED"
            fact["issuer_or_broker_mirror_refs" if caveat else "official_source_refs"] = [source_ref]
            approved["delisting_facts"][code] = fact["delisting_effective_date"]
            if caveat:
                approved["quality_caveats"][code] = quality
            approved["bound_primary_artifacts"][fc._CONTROLLER_ARTIFACTS[code]] = source_ref
        else:
            fact["official_source_refs"] = [source_ref]
            brokers["facts"].append(dict(ts_code=code, effective_delisting_date=fact["delisting_effective_date"],
                status="OFFICIAL_DELISTING_CONFIRMED", retry_policy_for_this_workflow="DO_NOT_FETCH_CURRENT_BARS_ON_OR_AFTER_EFFECTIVE_DATE",
                raw_or_qfq_price_changes=False, historical_rows="RETAIN", silent_code_remap=False,
                source_path=str(source), source_sha256=source_ref["sha256"], source_url=source_ref["url"]))
        raw = tmp_path / (code[-2:].lower() + code[:6] + ".day")
        raw.write_bytes(("retained historical raw " + code).encode())
        rows[code] = dict(symbol=code[:6], market={"SZ": 0, "SH": 1, "BJ": 2}[code[-2:]],
            path=str(raw), source_sha256_before=fc.sha(raw), source_sha256_after=fc.sha(raw),
            classification="QUARANTINED", quarantine=True, target_date_ready=False,
            lifecycle_skip=True, reason_code=fc._LIFECYCLE_REASON, records_written=0, lifecycle_fact=fact)
    controller_ref = save(tmp_path / "controller.json", approved)
    brokers_ref = save(tmp_path / "brokers.json", brokers)
    monkeypatch.setattr(fc, "_CONTROLLER_FACT_SET_SHA", controller_ref["sha256"])
    monkeypatch.setattr(fc, "_TWO_BROKERS_SHA", brokers_ref["sha256"])
    for code, fact in facts.items():
        fact["accepted_case_result_ref"] = controller_ref if code in fc._CONTROLLER_ARTIFACTS else brokers_ref
    asset_ref = save(tmp_path / "lifecycle.json", dict(verified_delistings=list(facts.values())))
    monkeypatch.setattr(fc, "_LIFECYCLE_ASSET_PATH", Path(asset_ref["path"]))
    monkeypatch.setattr(fc, "_LIFECYCLE_ASSET_SHA", asset_ref["sha256"])
    for row in rows.values():
        row["lifecycle_asset_sha256"] = asset_ref["sha256"]
    return rows


@pytest.mark.parametrize("code", ["000016.SZ", "688287.SH", "833994.BJ", "832317.BJ", "833874.BJ",
                                  "920680.BJ", "920305.BJ", "601198.SH", "601059.SH", "600193.SH"])
def test_exact_original_bound_facts_skip_without_admission(bindings, code):
    row = bindings[code]
    before = copy.deepcopy(row)
    result = fc._verified_sop_skip(code, row, 20261030, None)
    assert result["status"] == "SOP_SKIPPED" and result["classification"] == "QUARANTINED"
    assert result["provider_invoked"] is False and result["queried_at"] is None
    assert result["original_sync_row"] == before == row
    assert fc.sha(Path(row["path"])) == row["source_sha256_before"]
    if code in fc._CONTROLLER_ARTIFACTS:
        fact = result["original_sync_row"]["lifecycle_fact"]
        assert fact["accepted_review_literal"] == fc._CONTROLLER_PENDING_LITERAL
        assert fact["price_chain_admitted"] is False and fact["historical_PIT"] is False
        if code in {"920680.BJ", "920305.BJ", "600193.SH"}:
            assert "MIRROR_CAVEAT" in result["proof_route"]
            assert fact["source_quality"] != "PRIMARY_SOURCE_BYTES_CAPTURED"


@pytest.mark.parametrize("bad", ["raw_bytes", "raw_sha", "asset_bytes", "asset_sha", "approval_bytes",
    "approval_sha", "source_bytes", "source_sha", "stock", "market", "raw_identity", "effective",
    "event", "price_admission", "literal", "pending_promoted", "primary_ref", "old_market"])
def test_new_controller_binding_rejects_drift(bindings, bad):
    row = bindings["000016.SZ"]
    fact = row["lifecycle_fact"]
    if bad == "raw_bytes": Path(row["path"]).write_bytes(b"drift")
    if bad == "raw_sha": row["source_sha256_after"] = "0" * 64
    if bad == "asset_bytes": fc._LIFECYCLE_ASSET_PATH.write_text("{}")
    if bad == "asset_sha": row["lifecycle_asset_sha256"] = "0" * 64
    if bad == "approval_bytes": Path(fact["accepted_case_result_ref"]["path"]).write_text("{}")
    if bad == "approval_sha": fact["accepted_case_result_ref"]["sha256"] = "0" * 64
    if bad == "source_bytes": Path(fact["official_source_refs"][0]["path"]).write_bytes(b"drift")
    if bad == "source_sha": fact["official_source_refs"][0]["sha256"] = "0" * 64
    if bad == "stock": fact["ts_code"] = "200016.SZ"
    if bad == "market": row["market"] = 1
    if bad == "raw_identity": row["path"] = bindings["688287.SH"]["path"]
    if bad == "effective": fact["delisting_effective_date"] = "20261022"
    if bad == "event": fact["event_type"] = "SUSPENSION"
    if bad == "price_admission": fact["price_chain_admitted"] = True
    if bad == "literal": fact["accepted_review_literal"] = "PASS"
    if bad == "pending_promoted": fact["source_quality"] = "PASS"
    if bad == "primary_ref": fact["official_source_refs"] = bindings["688287.SH"]["lifecycle_fact"]["official_source_refs"]
    if bad == "old_market": fact["old_market_only"] = False
    assert fc._verified_sop_skip("000016.SZ", row, 20261030, None) is None


def test_effective_day_is_permanent_nonadmission_boundary(bindings):
    row = bindings["000016.SZ"]
    assert fc._verified_sop_skip("000016.SZ", row, 20261022, None) is None
    assert fc._verified_sop_skip("000016.SZ", row, 20261023, None)["status"] == "SOP_SKIPPED"
    assert fc._verified_sop_skip("000016.SZ", row, 20261030, None)["status"] == "SOP_SKIPPED"
    assert fc._verified_sop_skip("200016.SZ", row, 20261030, None) is None


@pytest.mark.parametrize("code", ["920680.BJ", "920305.BJ"])
def test_mirror_cannot_be_promoted_to_primary(bindings, code):
    row = bindings[code]
    row["lifecycle_fact"]["source_quality"] = "PRIMARY_SOURCE_BYTES_CAPTURED"
    assert fc._verified_sop_skip(code, row, 20261030, None) is None


@pytest.mark.parametrize("code", ["601198.SH", "601059.SH"])
@pytest.mark.parametrize("bad", ["approval_sha", "source_bytes", "effective", "stock"])
def test_broker_binding_rejects_drift(bindings, code, bad):
    row = bindings[code]
    fact = row["lifecycle_fact"]
    if bad == "approval_sha": fact["accepted_case_result_ref"]["sha256"] = "0" * 64
    if bad == "source_bytes": Path(fact["official_source_refs"][0]["path"]).write_bytes(b"drift")
    if bad == "effective": fact["delisting_effective_date"] = "20261018"
    if bad == "stock": fact["ts_code"] = "601000.SH"
    assert fc._verified_sop_skip(code, row, 20261030, None) is None
