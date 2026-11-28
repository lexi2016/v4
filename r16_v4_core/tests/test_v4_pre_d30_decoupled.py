from hashlib import sha256
import gzip
import json

from fastapi.testclient import TestClient
import pytest

from v4_core.decoupled.manager_history import create_manager_app, compact_projection
from v4_core.decoupled.static_projection import read_member
from v4_core.decoupled.wechat_archive import MENTION_TOKEN


class ManagerFixture:
    day = "20261127"
    version = {"run_id": "saved", "generated_at": "2026-11-27T07:00:00+08:00"}
    choices = [
        {"symbol":"HK.00001","name":"甲","row_id":"OVERSOLD:2","decision":"SELECTED"},
        {"symbol":"HK.00002","name":"乙","row_id":"OVERSOLD:4","decision":"CONDITIONAL_WATCH"},
    ]
    unassessed = {"symbol":"HK.00003","name":"丙","row_id":"OVERSOLD:5","decision":"UNASSESSED"}

    def versions(self, day):
        return [self.version], []

    def resolve(self, day, phase, run_id):
        return {"oversold":"oversold"}, {
            "api_version": self.version,
            "snapshot": {"run_id":"saved","context":{"target_date":self.day,"phase":"INTRADAY"}},
        }

    def member(self, ref, limit=None):
        return {
            "saved_selection": False, "industry_default": False, "decisions": {"UNASSESSED": [self.unassessed]}, "stocks": self.choices,
            "selection":{"lane_state":"PARTIAL","counts":{"selected":1},
                         "recommendation_projection":{"lane":"OVERSOLD"}},
            "default_summary":None, "gaps":[],
        }


def test_oversold_default_projection_unchanged_nested_ui_contract():
    client = TestClient(create_manager_app(ManagerFixture()))
    url = "/api/v4/manager-workbench/days/20261127/recommendations/OVERSOLD"
    value = client.get(url, params={"offset":1,"limit":1}).json()
    assert {key: value[key] for key in ("schema_version","RESEARCH_ONLY","production_allowed","buy_gate_updated","orders_sent")} == {
        "schema_version":"v4.manager_workbench.v1","RESEARCH_ONLY":True,"production_allowed":False,
        "buy_gate_updated":False,"orders_sent":False,
    }
    data = value["data"]
    assert data["snapshot"]["context"] == {"target_date":"20261127","phase":"INTRADAY"}
    assert data["recommendation_projection"]["lane"] == "OVERSOLD"
    assert data["pagination"] == {"total":2,"offset":1,"limit":1}
    assert data["stocks"][0]["row_id"] == "OVERSOLD:4"
    assert client.get(url, params={"q":"丙","decision":"UNASSESSED"}).json()["data"]["stocks"] == [ManagerFixture.unassessed]
    assert client.get(url, params={"q":"甲"}).json()["data"]["stocks"] == ManagerFixture.choices[:1]


def test_diagnostics_reuses_saved_symbol_and_relationship_pagination():
    body = {"stocks":[{"symbol":"HK.00001","decision":"SELECTED","focus_decision":{"decision":"SELECTED"},
                       "relationships":[1,2,3],"relationship_pagination":{"total":3}}]}
    result = compact_projection(body, "", "SELECTED", "HK.00001", 0, 1, 1, 1)
    assert result["stocks"][0]["relationships"] == [2]
    assert result["stocks"][0]["relationship_pagination"] == {"total":3,"offset":1,"limit":1}
    assert body["stocks"][0]["relationships"] == [1,2,3]


def test_snapshot_digest_is_checked_after_same_path_replacement(tmp_path):
    member = tmp_path / "main.json.gz"
    data = gzip.compress(json.dumps({"observed": True}).encode(), mtime=0)
    member.write_bytes(data)
    digest = sha256(data).hexdigest()
    assert read_member(tmp_path, member.name, digest, 2048) == {"observed":True}
    member.write_bytes(gzip.compress(json.dumps({"observed": False}).encode(), mtime=0))
    with pytest.raises(ValueError, match="SHA_MISMATCH"):
        read_member(tmp_path, member.name, digest, 2048)
    with pytest.raises(ValueError, match="MEMBER_INVALID"):
        read_member(tmp_path, "../main.json.gz", digest, 2048)


def test_accepted_cjk_wechat_issuer_names_in_independent_parser():
    assert MENTION_TOKEN.fullmatch("ISSUER_汇川技术")
    assert not MENTION_TOKEN.fullmatch("ABC_汇川技术")
