from hashlib import sha256
import json

import pytest

import seven_p0_reads as reads

MANAGER_PREFIX = reads.MANAGER + "/days/20261127/recommendations/"


@pytest.mark.parametrize("lane", ["US_MAPPING", "OVERSOLD"])
def test_manager_missing_plan_is_a_valid_safe_envelope(lane):
    payload = reads.manager_payload(MANAGER_PREFIX + lane, {})
    assert payload["schema_version"] == "v4.manager_workbench.v1"
    assert payload["state"] == "CANNOT_CONFIRM"
    assert payload["data"]["snapshot"] is None and payload["data"]["counts"] is None
    assert payload["gaps"] and all(payload[key] is value for key, value in reads.SAFETY.items())
    assert reads.manager_payload(MANAGER_PREFIX + "UNKNOWN", {}) is None
    assert reads.manager_payload(reads.MANAGER + "/announcement-flash/update", {}) is None


def test_sop_requires_exact_source_bytes(tmp_path, monkeypatch):
    source = tmp_path / "content_projection" / "p0_single_stock_repair.md"
    source.parent.mkdir()
    data = tmp_path / "home" / "data"
    api = reads.SevenP0Reads(None, data, None)
    assert api.sop()["status"] == "CANNOT_CONFIRM"
    body = "# 单股修复 SOP\n".encode()
    monkeypatch.setattr(reads, "SOP_SHA", sha256(body).hexdigest())
    source.write_bytes(body)
    payload = api.sop()
    assert payload["content"].encode() == body
    assert payload["schema_version"] == "v4.research.single_stock_repair_sop.v1"
    assert payload["source"]["sha256"] == sha256(body).hexdigest()
    assert payload["status"] == "READY"
    source.write_bytes(body + b"changed")
    assert api.sop()["status"] == "CANNOT_CONFIRM"
    assert api.sop()["content"] is None


def test_top200_is_exact_and_does_not_invent_stage_hits(tmp_path, monkeypatch):
    rows = [{"trade_date": "2026-11-27", "rank": 1, "symbol": "002001.SZ",
             "name": "same-day", "pct_chg": 9.2}]
    source = {
        "schema": "R21_EXACT_DAY_ACCEPTED_UNIVERSE_TOP200_V1", "source_date": "2026-11-27",
        "data_date": "20261127", "status": "PARTIAL_DESCRIPTIVE", "generation": "g",
        "natural_verified": False, "canonical_daily_product": False, "historical_PIT": False,
        "top200": rows, "count": 1, "coverage_scope": "test", "accepted": 1, **reads.SAFETY,
    }
    directory = tmp_path / "daily_e2e_20261127"
    directory.mkdir()
    raw = json.dumps(source).encode()
    (directory / "R21_D27_TOP200_VERIFIED.json").write_bytes(raw)
    monkeypatch.setattr(reads, "TOP200_SOURCES", {"20261127": sha256(raw).hexdigest()})

    class Store:
        returned = rows

        def get_top200(self, date):
            assert date == "2026-11-27"
            return self.returned

    class Preselection:
        proof = {}

    store = Store()
    api = reads.SevenP0Reads(store, tmp_path / "home" / "data", Preselection())
    for request in ("20261127", "2026-11-27"):
        payload = api.top200(request)
        assert payload["requested_date"] == request
        assert payload["dates"][0]["date"] == request and payload["rows"] == rows
        assert payload["dates"][0]["stocks"][0]["pool_hit"] is None
        assert payload["dates"][0]["stocks"][0]["stage_coverage_known"] is False
        assert payload["dates"][0]["seven_stage"]["status"] == "CANNOT_CONFIRM"
    assert api.top200("20261128")["dates"] == []
    assert api.top200("20261131") is None
    store.returned = []
    assert api.top200("20261127")["status"] == "CANNOT_CONFIRM"
