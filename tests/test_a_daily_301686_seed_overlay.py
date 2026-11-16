"""Synthetic tests for the evidence-derived close checks in the R3 overlay."""
from copy import deepcopy
from datetime import date, timedelta
from hashlib import sha256
import json
import math
from pathlib import Path
import struct

import pytest

from ops._a_share_daily_sync_parts import progress


PATCH = (
    Path(__file__).resolve().parents[1]
    / "docs/handoffs/a_daily_301686_seed_20261116/CANDIDATE_OVERLAY.patch"
)
SESSIONS = (20260922, 20260923, 20260924, 20260928, 20260929)
CODEC = struct.Struct("<IIIIIfII")


def write_reference(path, value):
    raw = value if isinstance(value, bytes) else json.dumps(value).encode()
    path.write_bytes(raw)
    return {"path": str(path), "sha256": sha256(raw).hexdigest()}


@pytest.fixture
def helper(bound_prefix):
    delta = PATCH.read_text()
    start = delta.index("+_CHINEXT_LISTING_NOTICE =")
    end = delta.index("\n def _explain_historical_seed_pair", start)
    source = "\n".join(line[1:] for line in delta[start:end].splitlines() if line.startswith("+"))
    namespace = {
        "Path": Path, "hashlib": __import__("hashlib"), "math": math,
        "_evidence_bytes": progress._evidence_bytes, "_evidence_json": progress._evidence_json,
        "_v4_global": lambda scope, name: scope[name],
    }
    exec(compile(source, str(PATCH), "exec"), namespace)
    assert namespace["_CHINEXT_LISTING_NOTICE"][1] == "2e405725f04d6e4ad0cd4ef15d24993c1f3f5f1cc30850e22cf4e4081663e87d"
    spec = bound_prefix[3]
    namespace["_CHINEXT_LISTING_NOTICE"] = (spec["listing_notice_url"], spec["listing_notice"]["sha256"])
    return namespace["_explain_exact_chinext_seed"]


@pytest.fixture
def bound_prefix(tmp_path):
    source = tmp_path.resolve() / "sz/lday/sz301686.day"
    source.parent.mkdir(parents=True)
    sessions = [*SESSIONS, *(int((date(2026, 9, 30) + timedelta(days=i)).strftime("%Y%m%d")) for i in range(27))]
    closes = [1000, 610, 620, 630, 615, *([620] * 27)]
    raw = b"".join(CODEC.pack(d, c, c + 10, c - 10, c, 5000.0, 100, 0)
                   for d, c in zip(sessions, closes, strict=True))
    native = write_reference(source, raw)
    bars = [dict(trade_date=d, open=c / 100, high=(c + 10) / 100, low=(c - 10) / 100, close=c / 100)
            for d, c in zip(sessions, closes, strict=True)]
    series = []
    for i, d in enumerate(SESSIONS):
        previous = 5.0 if i == 0 else closes[i - 1] / 100
        c = closes[i]
        cod, md1 = bytearray(150), bytearray(512)
        cod[:6] = b"301686"
        struct.pack_into("<H", cod, 32, i)
        struct.pack_into("<5d", md1, 4, previous, c / 100, (c + 10) / 100, (c - 10) / 100, c / 100)
        record = raw[i * 32:(i + 1) * 32]
        series.append(dict(date=d, url=f"https://www.tdx.com.cn/products/data/data/g4day/{d}.zip",
            official_pre_close=previous, official_cod_record_hex=cod.hex(), official_md1_record_hex=md1.hex(),
            official_lineage=dict(source_kind="TDX_OFFICIAL_G4DAY", code="301686", market=0, target_date=d,
                cod_member={"name": f"sz{str(d)[2:]}.cod"}, md1_member={"name": f"sz{str(d)[2:]}.md1"}, seq=i),
            raw_local_ohlc_cents=[c, c + 10, c - 10, c], raw_local_record_sha256=sha256(record).hexdigest()))
    proof = dict(status="EXACT_OFFICIAL_FIRST_FIVE_RAW_CLOSES_VERIFIED", symbol="301686.SZ",
        formal_data_written=False, series=series, native=native,
        calendar=write_reference(tmp_path / "calendar.synthetic", b"synthetic calendar"),
        calendar_adapter=write_reference(tmp_path / "adapter.synthetic", b"synthetic adapter"))
    spec = dict(symbol="301686.SZ", listing_date=SESSIONS[0], native_prefix_bytes=len(raw),
        listing_notice=write_reference(tmp_path / "synthetic.pdf.stub", b"%PDF-synthetic test only"),
        listing_notice_url="https://disc.static.szse.cn/download/disc/synthetic-case.pdf",
        first_five=write_reference(tmp_path / "proof.synthetic", proof))
    return source, raw, bars, spec, proof


def run(helper, source, bars, spec, closes=(10.0, 6.1)):
    context = {"records": []}
    scope = {"DAY_STRUCT": CODEC, "day_int": lambda row: row["trade_date"]}
    result = helper(scope, context, {"descriptor_sha256": "0" * 64, "coverage": 20261023}, spec,
                    "301686.SZ", *SESSIONS[:2], *closes, bars, source)
    assert len(context["records"]) == 1
    return result, context["records"][0]


def test_synthetic_bound_first_pair_and_exact_future_append(helper, bound_prefix):
    path, raw, bars, spec, _ = bound_prefix
    # Later unchanged native bytes remain the original caller's responsibility.
    appended = CODEC.pack(20261116, 640, 650, 630, 640, 5000.0, 100, 0)
    path.write_bytes(raw + appended)
    result, record = run(helper, path, bars, spec)
    assert result and record["status"] == "EXPLAINED_EXACT_SZSE_CHINEXT_IPO_BOUNDARY"
    assert len(record["first_five_native_row_sha256"]) == 5
    assert path.read_bytes() == raw + appended


@pytest.mark.parametrize("fault,expected", [
    ("descriptor_date", "chinext_exact_seed_identity_conflict"),
    ("wrong_source_path", "chinext_exact_seed_source_path"),
    ("prefix_bytes", "chinext_exact_seed_native_prefix_drift"),
    ("proof_checksum", "reference_sha256_mismatch"),
    ("wrong_close", "chinext_exact_seed_boundary_close_conflict"),
    ("repinned_fake_pdf", "chinext_exact_seed_listing_document"),
    ("repinned_official_host_url", "chinext_exact_seed_listing_document"),
    ("repinned_market", "chinext_exact_seed_retained_record_identity"),
    ("repinned_day", "chinext_exact_seed_first_five_scope"),
    ("repinned_source", "chinext_exact_seed_retained_record_identity"),
])
def test_synthetic_evidence_fails_closed(helper, bound_prefix, fault, expected):
    source, raw, bars, spec, proof = bound_prefix
    closes = (10.0, 6.1)
    if fault == "descriptor_date":
        spec["listing_date"] = 20260921
    elif fault == "wrong_source_path":
        source = source.with_name("sz301687.day")
        source.write_bytes(raw)
    elif fault == "prefix_bytes":
        source.write_bytes(raw[:28] + b"\x01" + raw[29:])
    elif fault == "proof_checksum":
        spec["first_five"]["sha256"] = "f" * 64
    elif fault == "wrong_close":
        closes = (10.0, 6.0)
    elif fault == "repinned_fake_pdf":
        spec["listing_notice"] = write_reference(source.parent / "forged.pdf.stub", b"%PDF-synthetic wrong document")
    elif fault == "repinned_official_host_url":
        spec["listing_notice_url"] = "https://disc.static.szse.cn/download/disc/synthetic-other-document.pdf"
    else:
        changed = deepcopy(proof)
        if fault == "repinned_market":
            changed["series"][1]["official_lineage"]["market"] = 1
        elif fault == "repinned_day":
            changed["series"][1]["date"] = 20260925
        else:
            changed["series"][1]["url"] = "https://example.invalid/record.zip"
        spec["first_five"] = write_reference(source.parent / "alternative.synthetic", changed)
    result, row = run(helper, source, bars, spec, closes=closes)
    assert not result and row["reason"] == expected
