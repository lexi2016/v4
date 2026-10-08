"""Independent source-identity probes against exact candidate router/service."""
from pathlib import Path
import sys

import pytest

from infrastructure.preselection_pool_store import PreselectionPoolStore
from test_issue30_preselection_module import _client, _corrupt_manifest, _hashes
from test_preselection_source_root_20261008 import DATE, _pool_artifact


@pytest.mark.parametrize("damage", ["unknown_explicit_market", "conflicting_hk_symbol"])
def test_sha_recovery_does_not_promote_inconsistent_market_identity(tmp_path, damage):
    client, source = _client(tmp_path, ["A.000001"])
    invalid = _pool_artifact("a_share_research_recommendation_pool", [{"symbol": "A.000020"}])
    if damage == "unknown_explicit_market":
        invalid["rows"][0]["market"] = "US"
    else:
        invalid["rows"][0]["symbol"] = "HK.00700"
        invalid["rows"][0]["code"] = "000020"
    PreselectionPoolStore(source).materialize(invalid)
    _corrupt_manifest(source)
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert _hashes(source) == before
    assert payload["data_status"] == "DATA_BLOCKED_EMPTY", payload
    assert payload["a_all_pool_row_count"] == 0
    assert payload.get("source_quarantine_recovery", {}).get("applied") is not True


def test_consistent_a_code_aliases_survive_sha_quarantine(tmp_path):
    client, source = _client(tmp_path, ["A.000001"])
    good = _pool_artifact("a_share_research_recommendation_pool", [{
        "symbol": "A.000020", "code": "000020", "ts_code": "000020.SZ",
    }])
    PreselectionPoolStore(source).materialize(good)
    _corrupt_manifest(source)
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert _hashes(source) == before
    assert payload["data_status"] == "PARTIAL_WITH_ROWS"
    assert payload["a_all_pool_row_count"] == 1
    assert payload["a_all_pool_rows"][0]["symbol"] == "A.000020"


def test_inconsistent_pool_is_quarantined_without_blocking_another_valid_a_pool(tmp_path):
    client, source = _client(tmp_path, ["A.000001"])
    invalid = _pool_artifact("a_share_research_recommendation_pool", [{"symbol": "A.000020"}])
    invalid["rows"][0]["market"] = "US"
    pools = PreselectionPoolStore(source)
    pools.materialize(invalid)
    pools.materialize(_pool_artifact("a_share_baimao_research_map", [{"symbol": "A.000030"}]))
    _corrupt_manifest(source)
    before = _hashes(source)
    payload = client.get("/api/v3/preselection-pools", params={"date": DATE}).json()
    assert _hashes(source) == before
    assert payload["data_status"] == "PARTIAL_WITH_ROWS"
    assert payload["a_all_pool_row_count"] == 1
    assert [row["symbol"] for row in payload["a_all_pool_rows"]] == ["A.000030"]
    assert payload["source_quarantine_recovery"]["quarantined_pools"]["a_share_research_recommendation_pool"] == "a_row_market_or_date_unconfirmed"
