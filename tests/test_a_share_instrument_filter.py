"""The 2026-10-22 ETF intrusion, exercised at the three real admission seams."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from domains.preselection_materializer import build_hourly_research_pool
from infrastructure.preselection_pool_store import PreselectionPoolStore
from infrastructure.stage_acquisition_universe_contracts import (
    build_strict_stage_acquisition_universe,
    read_strict_a_preselection_snapshot,
    validate_strict_stage_acquisition_artifact,
    validate_artifact_against_snapshot,
)
from stage_center.input_contracts import a_pool_contract
from stage_center.selection import select_a_0925_auction, select_a_live_stage, select_a_stage

DATE = "20261022"
POOL = "a_share_research_recommendation_pool"
ETF_CODES = ("159915", "510300", "510050", "588000", "588080", "159919", "511880", "513100", "180101")
EQUITY_CODES = ("000001", "001001", "002001", "003001", "300750", "301001", "302001", "600519", "601398", "603001", "605001", "688001", "689009", "920735", "430047", "830799", "872392")


class HourlyFixture:
    """Same stock_code/time/article identity shape as the actual hourly archive."""
    def list_slots(self, date, *, mode):
        return ["2200"] if date == "20261021" else []

    def read_exact(self, date, slot, *, mode):
        return {"archive_date": date, "cannot_confirm": [], "articles": [
            {"article_id": f"fixture-{code}", "stock_code": code, "stock_name": "ETF华夏" if code == "510050" else code,
             "published_at": "2026-10-21T22:02:24+08:00", "source_title": "source retained"}
            for code in (*ETF_CODES, *EQUITY_CODES)
        ]}


def _pool(symbols):
    status, producer, role = a_pool_contract(POOL)
    return {"schema_version": "v3_5.preselection_pool.v1", "trade_date": DATE,
            "pool_id": POOL, "display_name": POOL, "market": "A", "status": status,
            "producer_id": producer, "source_role": role, "source_path": "fixture/hourly.json", "source_sha256": "a" * 64,
            "rows": [{"symbol": f"A.{code}", "market": "A", "pool_id": POOL} for code in symbols],
            "cannot_confirm": [], "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


def _market_rows():
    # 510050 was actually ranked #5 with amount177071250 and no prev_close.
    return [{"code": f"A.{code}", "time": "2026-10-22 09:25:00", "trade_date": DATE,
             "price": 28.75, "amount_yuan": 177071250.0, "complete": True,
             "formal_eligible": False, "qmt": {"open": 28.75, "lastPrice": 28.75, "amount": 177071250.0}}
            for code in ("510050", "159915", "510300", "000001", "688001", "689009", "920735")]


def test_hourly_research_stock_pool_excludes_real_etfs():
    pool = build_hourly_research_pool(Path("unused"), DATE, store=HourlyFixture())
    assert {row["code"] for row in pool["rows"]} == set(EQUITY_CODES)
    assert pool["source_sha256"] and pool["source_path"] == "research/hourly/live/20261021/2200.json"


def test_strict_mixed_pool_keeps_equities_and_physical_evidence(tmp_path):
    store = PreselectionPoolStore(tmp_path)
    store.materialize(_pool((*ETF_CODES, *EQUITY_CODES)))
    before = (tmp_path / f"preselection_pools/{DATE}/{POOL}.json").read_bytes()
    snapshot = read_strict_a_preselection_snapshot(tmp_path, DATE)
    assert snapshot.ready
    assert set(snapshot.codes) == {f"A.{code}" for code in EQUITY_CODES}
    artifact = build_strict_stage_acquisition_universe(snapshot)
    assert validate_strict_stage_acquisition_artifact(artifact) == DATE
    assert (tmp_path / f"preselection_pools/{DATE}/{POOL}.json").read_bytes() == before
    assert any("POOL_NOT_AVAILABLE" in reason for reason in snapshot.diagnostic_reasons)


@pytest.mark.parametrize("route", ["auction", "live", "bars"])
def test_all_a_routes_filter_before_ranking_and_preserve_research_safety(route):
    rows = _market_rows()
    before = copy.deepcopy(rows)
    kwargs = {"requested_rows": len(rows), "source_evidence": ["raw_source_sha256=" + "b" * 64]}
    if route == "auction":
        result = select_a_0925_auction(rows, DATE, "b" * 64, **kwargs)
    elif route == "live":
        result = select_a_live_stage(rows, DATE, "STAGE_0935_0940", "b" * 64, **kwargs)
    else:
        result = select_a_stage(rows, DATE, "STAGE_0935_0940", "b" * 64, **kwargs)
    assert {r["code"] for r in result["rows"]} == {"A.000001", "A.688001", "A.689009", "A.920735"}
    assert result["raw_artifact_sha256"] == "b" * 64
    assert result["requested_rows"] == len(rows)
    assert rows == before
    assert all(result[field] is False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))


@pytest.mark.parametrize("code", EQUITY_CODES)
def test_equity_code_family_compatibility_is_not_a_listing_claim(code):
    from contracts.a_share_instruments import a_share_instrument_rejection
    assert a_share_instrument_rejection(f"A.{code}") is None
    # An ETF word in descriptive text must not reject a legitimate stock.
    assert a_share_instrument_rejection(code, {"stock_name": "ETF技术服务公司"}) is None


@pytest.mark.parametrize("code", (*ETF_CODES, "113001", "123001", "204001", "900901", "200002", "787001", "889001", "HK.00001", "prefix600519suffix", "6005190"))
def test_non_equity_families_and_nonexact_code_are_rejected(code):
    from contracts.a_share_instruments import a_share_instrument_rejection
    assert a_share_instrument_rejection(code)


@pytest.mark.parametrize("row", [
    {"ts_code": "000001.SH"}, {"code": "000001.SH"},
    {"security_type": "INDEX"}, {"instrument_type": "ETF"}, {"stock_type": "fund"},
])
def test_explicit_metadata_vetoes_ambiguous_code_family(row):
    from contracts.a_share_instruments import a_share_instrument_rejection
    assert a_share_instrument_rejection("A.000001", row)


def test_exclusions_are_traced_and_all_nonstock_pool_cannot_become_ready(tmp_path):
    pool = build_hourly_research_pool(Path("unused"), DATE, store=HourlyFixture())
    assert {r["symbol"] for r in pool["instrument_filter"]["excluded_articles"]} == {f"A.{c}" for c in ETF_CODES}
    store = PreselectionPoolStore(tmp_path)
    store.materialize(_pool(ETF_CODES))
    snapshot = read_strict_a_preselection_snapshot(tmp_path, DATE)
    assert not snapshot.ready and not snapshot.codes
    assert any("NON_STOCK_INSTRUMENT_EXCLUDED:A.510050" in reason for reason in snapshot.diagnostic_reasons)


def test_strict_publication_rejects_preexisting_etf_candidate(tmp_path):
    from infrastructure.stage_acquisition_universe_contracts import StageAcquisitionContractError
    store = PreselectionPoolStore(tmp_path)
    store.materialize(_pool(["000001"]))
    snapshot = read_strict_a_preselection_snapshot(tmp_path, DATE)
    artifact = build_strict_stage_acquisition_universe(snapshot)
    artifact["codes"] = ["A.510050"]
    artifact["code_sources"] = {"A.510050": [POOL]}
    with pytest.raises(StageAcquisitionContractError, match="non-stock instrument"):
        validate_artifact_against_snapshot(artifact, snapshot)


def test_metadata_filter_keeps_valid_row_in_same_pool_and_hk_cannot_leak(tmp_path):
    pool = _pool(["000001", "600519"])
    pool["rows"][0]["security_type"] = "INDEX"
    store = PreselectionPoolStore(tmp_path)
    store.materialize(pool)
    snapshot = read_strict_a_preselection_snapshot(tmp_path, DATE)
    assert snapshot.codes == ("A.600519",)
    result = select_a_0925_auction([*_market_rows(), {"code": "HK.00001", "time": "09:25"}], DATE, "b" * 64)
    assert all(row["code"].startswith("A.") for row in result["rows"])
    assert any("non_stock_instrument_excluded=A.510050" in item for item in result["source_evidence"])


def test_existing_bse_legacy_suffix_does_not_erase_equity_contribution(tmp_path):
    pool = _pool(["920641", "920394"])
    for row in pool["rows"]:
        row["ts_code"] = row["symbol"][2:] + ".SZ"
    store = PreselectionPoolStore(tmp_path)
    store.materialize(pool)
    assert set(read_strict_a_preselection_snapshot(tmp_path, DATE).codes) == {"A.920641", "A.920394"}


def test_hourly_code_parser_does_not_promote_embedded_six_digits():
    class Store(HourlyFixture):
        def read_exact(self, date, slot, *, mode):
            payload = super().read_exact(date, slot, mode=mode)
            payload["articles"] = [dict(payload["articles"][0], stock_code="5100500", article_id="bad-etf"),
                                   dict(payload["articles"][1], stock_code="6005190", article_id="bad-stock")]
            return payload
    assert not build_hourly_research_pool(Path("unused"), DATE, store=Store())["rows"]


def _legacy_current(tmp_path, monkeypatch, *, include_etf=True):
    """Create a real immutable pre-fix committed chain, never a forged marker."""
    from infrastructure.stage_acquisition_universe_commit import EvidenceIdentity, StageAcquisitionUniverseCommit
    from infrastructure._stage_acquisition_universe_contracts_parts import rows_metadata, snapshot_aggregation, snapshot_provenance
    store = PreselectionPoolStore(tmp_path)
    store.materialize(_pool((["510050"] if include_etf else []) + ["000001", "600519"]))
    with monkeypatch.context() as legacy:
        for module in (rows_metadata, snapshot_aggregation, snapshot_provenance):
            legacy.setattr(module, "a_share_instrument_rejection", lambda *_: None)
        artifact = build_strict_stage_acquisition_universe(read_strict_a_preselection_snapshot(tmp_path, DATE))
        chain = StageAcquisitionUniverseCommit(tmp_path).publish(artifact, identity=EvidenceIdentity(
            owner_id="V3_5_STAGE_CENTER", producer_id="ops.materialize_stage_acquisition_universe",
            release_id="fixture", lane_id="A_SHARE_STAGE_ACQUISITION"))
    return chain


def test_ordinary_preparation_reuses_verified_legacy_input_without_write(tmp_path, monkeypatch):
    from ops.materialize_stage_acquisition_universe import materialize_stage_acquisition_universe
    from stage_center.candidate_input import read_candidate_input
    chain = _legacy_current(tmp_path, monkeypatch)
    before = chain["current_path"].read_bytes()
    result = materialize_stage_acquisition_universe(tmp_path, DATE, release_id="fixture")
    assert result["idempotent"] and result["row_count"] == 3
    assert result["instrument_filter_reuse"]["eligible_stock_rows"] == 2
    assert result["instrument_filter_reuse"]["excluded_codes"] == ["A.510050"]
    assert chain["current_path"].read_bytes() == before
    assert len(read_candidate_input(tmp_path, DATE).codes) == 3
    assert all(r["code"] not in {"A.510050", "A.159915", "A.510300"} for r in select_a_0925_auction(_market_rows(), DATE, "b" * 64)["rows"])


@pytest.mark.parametrize("change", ["add", "remove", "reorder", "source", "healthy", "corrupt"])
def test_preparation_compatibility_never_swallows_unrelated_conflicts(tmp_path, monkeypatch, change):
    import ops.materialize_stage_acquisition_universe as module
    from infrastructure.stage_acquisition_universe_commit import StageAcquisitionUniverseCommit, StrictCommitError
    chain = _legacy_current(tmp_path, monkeypatch, include_etf=change != "healthy")
    fresh = module.build_artifact(tmp_path, DATE)
    if change == "add":
        fresh["codes"].append("A.000002")
    elif change == "remove":
        fresh["codes"].pop()
    elif change == "reorder":
        fresh["codes"].reverse()
    elif change == "source":
        fresh["code_sources"]["A.000001"] = ["a_d1_premarket_pool"]
    elif change == "corrupt":
        chain["current_path"].write_bytes(b"{}")
    monkeypatch.setattr(module, "build_artifact", lambda *a, **k: fresh)
    # The publication boundary reports a conflict; the fallback still must
    # verify the actual immutable chain and reject every equity difference.
    def conflict(*args, **kwargs):
        raise StrictCommitError("strict exact-date current conflict")
    monkeypatch.setattr(StageAcquisitionUniverseCommit, "publish", conflict)
    with pytest.raises(StrictCommitError):
        module.materialize_stage_acquisition_universe(tmp_path, DATE, release_id="fixture")


def test_explicit_successor_still_rejects_shrinking_filter_update(tmp_path, monkeypatch):
    from ops.materialize_stage_acquisition_universe import materialize_stage_acquisition_universe
    from infrastructure.stage_acquisition_universe_commit import StrictCommitError
    chain = _legacy_current(tmp_path, monkeypatch)
    with pytest.raises(StrictCommitError, match="retain the prior candidate order"):
        materialize_stage_acquisition_universe(tmp_path, DATE, release_id="fixture",
            expected_current_sha256=chain["current_bytes_sha256"], successor_reason="filter")


def test_new_clean_current_is_idempotent_and_contains_only_stocks(tmp_path):
    from ops.materialize_stage_acquisition_universe import materialize_stage_acquisition_universe
    PreselectionPoolStore(tmp_path).materialize(_pool(["510050", "000001", "600519"]))
    first = materialize_stage_acquisition_universe(tmp_path, DATE, release_id="fixture")
    second = materialize_stage_acquisition_universe(tmp_path, DATE, release_id="fixture")
    assert first["row_count"] == second["row_count"] == 2 and second["idempotent"]
    assert "instrument_filter_reuse" not in second


def test_same_day_physical_filter_refresh_preserves_legacy_read_and_prep(tmp_path, monkeypatch):
    from infrastructure.data_store import _canonical_bytes, _sha256
    from infrastructure.stage_acquisition_universe_commit import StageAcquisitionUniverseCommit
    from ops.materialize_stage_acquisition_universe import materialize_stage_acquisition_universe
    chain = _legacy_current(tmp_path, monkeypatch)
    current_bytes = chain["current_path"].read_bytes()
    store = PreselectionPoolStore(tmp_path)
    replacement = _pool(["000001", "600519"])
    # Ordinary owner materialization never overwrites a historical ready pool.
    with pytest.raises(ValueError, match="conflicting preselection-pool materialization"):
        store.materialize(replacement)
    # Simulate a supported external revision in this isolated fixture only;
    # the old committed candidate remains a valid frozen snapshot afterwards.
    relative, receipt_relative = store._relative(DATE, POOL)
    digest = _sha256(replacement)
    manifest_path = tmp_path / f"preselection_pools/{DATE}/manifest.json"
    manifest = __import__("json").loads(manifest_path.read_text())
    manifest[POOL] = digest
    (tmp_path / relative).write_bytes(_canonical_bytes(replacement))
    (tmp_path / receipt_relative).write_bytes(_canonical_bytes(store._receipt(
        trade_date=DATE, pool_id=POOL, artifact_path=relative, artifact_sha256=digest, payload=replacement)))
    manifest_path.write_bytes(_canonical_bytes(manifest))
    assert StageAcquisitionUniverseCommit(tmp_path).read_current(DATE)["artifact"]["row_count"] == 3
    result = materialize_stage_acquisition_universe(tmp_path, DATE, release_id="fixture")
    assert result["instrument_filter_reuse"]["eligible_stock_rows"] == 2
    assert chain["current_path"].read_bytes() == current_bytes
