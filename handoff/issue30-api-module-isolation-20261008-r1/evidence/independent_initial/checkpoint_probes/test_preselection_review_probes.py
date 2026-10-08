"""Independent source-identity probes against exact candidate router/service."""
from pathlib import Path
import sys

import pytest

SCOPE = Path(__file__).resolve().parents[1] / "preselection_scope"
sys.path.insert(0, str(SCOPE / "tests"))

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
