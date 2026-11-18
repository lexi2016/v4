import hashlib
import json

import pytest

from research.p515_prospective_readiness.source_seams import (
    verify_reader_projection,
    verify_top200,
)


D = "20261127"


def pin(obj, records, key):
    raw = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode()
    records[key] = hashlib.sha256(raw).hexdigest()
    return raw


def top_fixture():
    ids = dict(generation="a"*64, input_sha256="b"*64, top200_numeric_manifest_sha256="c"*64,
               top200_artifact_sha256="d"*64)
    doc = dict(schema="V4_A_SHARE_TOP200_V1", data_date=D, status="PARTIAL_DESCRIPTIVE",
               source_generation=ids["generation"], input_sha256=ids["input_sha256"],
               numeric_manifest={"sha256": ids["top200_numeric_manifest_sha256"]},
               artifact={"sha256": ids["top200_artifact_sha256"]}, top200_count=200,
               top200=[dict(rank=i+1, symbol=f"{i:06d}.SZ", source_date="2026-11-27") for i in range(200)])
    return ids, doc


def test_top200_roster_and_drift_rejected():
    ids, doc = top_fixture()
    raw = pin(doc, ids, "top200_raw_sha256")
    assert len(verify_top200(raw, D, ids)) == 200
    with pytest.raises(ValueError, match="SHA mismatch"):
        verify_top200(raw+b" ", D, ids)
    doc["top200"][-1]["source_date"] = "2026-11-28"
    with pytest.raises(ValueError, match="TOP200_RANK_OR_ROW_SOURCE"):
        verify_top200(pin(doc, ids, "top200_raw_sha256"), D, ids)
    doc["top200"][-1]["source_date"] = "2026-11-27"
    doc["top200"][-1]["symbol"] = doc["top200"][0]["symbol"]
    with pytest.raises(ValueError, match="TOP200_DUPLICATE"):
        verify_top200(pin(doc, ids, "top200_raw_sha256"), D, ids)


def test_projection_rejects_future_and_out_of_pool_row():
    ids, _ = top_fixture()
    ids.update(panel_manifest_sha256="e"*64, reader_sha256="f"*64, adjustment_snapshot_sha256="1"*64)
    roster = ((1, "000001.SZ"),)
    doc = dict(**ids, format="P515_D_ONLY_READER_PROJECTION_V1", D=D, price_basis="QFQ_ASOF",
               volume_basis="QFQ_EVENT_VOLUME", price_adjustment_asof=D,
               query=dict(start=D,end=D,ts_codes=["000001.SZ"],
                          columns=["ts_code","trade_date","open","high","low","close","volume"]),
               rows=[dict(ts_code="000001.SZ",trade_date=D,open=1,high=2,low=1,close=1,volume=100)])
    raw = pin(doc, ids, "reader_projection_sha256")
    assert verify_reader_projection(raw, D, ids, roster, [D])["D_bar_codes"] == ("000001.SZ",)
    doc["rows"][0]["trade_date"] = "20261130"
    raw = pin(doc, ids, "reader_projection_sha256")
    with pytest.raises(ValueError, match="READER_PROJECTION_ROW_OR_DUPLICATE"):
        verify_reader_projection(raw, D, ids, roster, [D])
    doc["rows"][0].update(trade_date=D, ts_code="000002.SZ")
    with pytest.raises(ValueError, match="READER_PROJECTION_ROW_OR_DUPLICATE"):
        verify_reader_projection(pin(doc, ids, "reader_projection_sha256"), D, ids, roster, [D])
