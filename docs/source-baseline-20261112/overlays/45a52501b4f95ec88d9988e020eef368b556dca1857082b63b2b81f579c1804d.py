import csv
import hashlib
import io
import json
from dataclasses import replace
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from apps.api.v4_api import research_router as research_router_module
from apps.api.v4_api.research_router import create_research_router
from domains.zero_to_history_high_position import (
    ASOF,
    EXPECTED_SYMBOLS,
    FIELD,
    FORMULA,
    HISTORY_SCOPE,
    METRIC_KIND,
    METRIC_TYPE,
    PRICE_BASIS,
    SOURCE_GENERATION,
    Position25Provider,
)


CSV_FIELDS = [
    "symbol",
    "name_asof_20261023",
    "asof",
    "metric_type",
    "formula",
    "zero_floor",
    "close_D",
    "available_history_high",
    "history_high_date",
    "position_pct",
    "status",
    "history_start",
    "prefix_rows",
    "original_empirical_close_percentile_status",
    "price_basis",
    "price_asof",
    "source_generation",
]
PREFILTER_FIELDS = [
    "symbol",
    "asof",
    "source_qualification",
    "history_start",
    "actual_last_date",
    "available_prefix_bars",
    "exact_D_rows",
    "close_D",
    "price_basis",
    "price_asof",
    "historical_PIT",
    "percentile_all_available_authorized_prefix_complete",
    "percentile_all_available_authorized_prefix_start",
    "percentile_all_available_authorized_prefix_end",
    "percentile_all_available_authorized_prefix_status",
    "source_generation",
]


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_csv(path: Path, rows: list[dict[str, str]], fields: list[str]) -> bytes:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    raw = output.getvalue().encode("utf-8")
    path.write_bytes(raw)
    return raw


def _prefilter_row(
    symbol: str,
    *,
    asof: str = ASOF,
    basis: str = PRICE_BASIS,
    generation: str = SOURCE_GENERATION,
    close: str = "1",
) -> dict[str, str]:
    return {
        "symbol": symbol,
        "asof": asof,
        "source_qualification": "CURRENT_PRODUCER_ACCEPTED_FOR_REQUESTED_RESEARCH",
        "history_start": "20100101",
        "actual_last_date": ASOF,
        "available_prefix_bars": "100",
        "exact_D_rows": "1",
        "close_D": close,
        "price_basis": basis,
        "price_asof": ASOF,
        "historical_PIT": "False",
        "percentile_all_available_authorized_prefix_complete": "True",
        "percentile_all_available_authorized_prefix_start": "20100101",
        "percentile_all_available_authorized_prefix_end": ASOF,
        "percentile_all_available_authorized_prefix_status": "UNCHANGED",
        "source_generation": generation,
    }


def _fixture_provider(tmp_path: Path, *, zero_symbol: str | None = None):
    source_root = tmp_path / "source"
    source_root.mkdir()
    csv_text = io.StringIO(newline="")
    writer = csv.DictWriter(csv_text, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    expected_values = {}
    for index, symbol in enumerate(EXPECTED_SYMBOLS):
        value = 0.0 if symbol == zero_symbol else float(index + 1)
        expected_values[symbol] = value
        writer.writerow(
            {
                "symbol": symbol,
                "name_asof_20261023": f"样本{index + 1}",
                "asof": ASOF,
                "metric_type": METRIC_TYPE,
                "formula": FORMULA,
                "zero_floor": "0",
                "close_D": "1",
                "available_history_high": "2",
                "history_high_date": "20200101",
                "position_pct": str(value),
                "status": "VALID_USER_DEFINED_RANGE_POSITION",
                "history_start": "20100101",
                "prefix_rows": "100",
                "original_empirical_close_percentile_status": "UNCHANGED",
                "price_basis": PRICE_BASIS,
                "price_asof": ASOF,
                "source_generation": SOURCE_GENERATION,
            }
        )
    positions_bytes = ("\ufeff" + csv_text.getvalue()).encode("utf-8")
    positions_path = source_root / "25_ZERO_FLOOR_HIGH_POSITION.csv"
    positions_path.write_bytes(positions_bytes)

    receipt_bytes = json.dumps(
        {
            "status": "25_USER_DEFINED_RANGE_POSITIONS_CALCULATED",
            "asof": ASOF,
            "source_generation": SOURCE_GENERATION,
            "rows": len(EXPECTED_SYMBOLS),
            "valid": len(EXPECTED_SYMBOLS),
            "metric": "ZERO_TO_PREFIX_HIGH_POSITION; not empirical count percentile",
            "output_sha256": _sha(positions_bytes),
            "source_panel": "fixture-panel",
            "declared_source_panel_sha256": "a" * 64,
            "panel_rehashed": False,
            "original_prices_or_percentiles_modified": False,
            "no_future_rows": True,
        },
        sort_keys=True,
    ).encode("utf-8")
    receipt_path = source_root / "ZERO_FLOOR_POSITION_RECEIPT.json"
    receipt_path.write_bytes(receipt_bytes)

    evidence_bytes = json.dumps(
        {
            "binding": {
                "source_generation": SOURCE_GENERATION,
                "panel": "fixture-panel",
                "panel_declared_sha256": "a" * 64,
                "basis": {"price_basis": PRICE_BASIS, "asof_date": int(ASOF)},
                "historical_PIT": False,
            }
        },
        sort_keys=True,
    ).encode("utf-8")
    evidence_path = source_root / "EVIDENCE.json"
    evidence_path.write_bytes(evidence_bytes)

    findings_rows = [
        {"symbol": symbol, "source_generation": SOURCE_GENERATION}
        for symbol in EXPECTED_SYMBOLS
    ]
    findings_path = source_root / "25_STOCKS_FULL_PREFIX_PRICE_FINDINGS.csv"
    findings_bytes = _write_csv(findings_path, findings_rows, ["symbol", "source_generation"])

    prefilter_rows = [_prefilter_row(symbol, close="1") for symbol in EXPECTED_SYMBOLS]
    prefilter_rows.extend(
        _prefilter_row(f"OUTSIDE-{index + 1:03d}", close="2")
        for index in range(216 - len(EXPECTED_SYMBOLS))
    )
    prefilter_path = source_root / "ALL216_PREFILTER.csv"
    prefilter_bytes = _write_csv(prefilter_path, prefilter_rows, PREFILTER_FIELDS)
    review_bytes = json.dumps(
        {"verdict": "REVIEWED/PASS", "counts": {"prefix_percentile_unknown": 25}},
        sort_keys=True,
    ).encode("utf-8")
    review_path = source_root / "FINAL_REVIEW.json"
    review_path.write_bytes(review_bytes)
    summary_bytes = json.dumps(
        {
            "all216_csv_sha256": _sha(prefilter_bytes),
            "asof": ASOF,
            "universe_rows": 216,
            "binding": {
                "source_generation": SOURCE_GENERATION,
                "basis": {"price_basis": PRICE_BASIS, "asof_date": int(ASOF)},
            },
        },
        sort_keys=True,
    ).encode("utf-8")
    summary_path = source_root / "SUMMARY.json"
    summary_path.write_bytes(summary_bytes)

    entries = {
        "positions_csv": {"path": str(positions_path), "sha256": _sha(positions_bytes)},
        "receipt": {"path": str(receipt_path), "sha256": _sha(receipt_bytes)},
        "evidence": {"path": str(evidence_path), "sha256": _sha(evidence_bytes)},
        "findings_csv": {"path": str(findings_path), "sha256": _sha(findings_bytes)},
        "prefilter": {"path": str(prefilter_path), "sha256": _sha(prefilter_bytes)},
        "prefilter_review": {"path": str(review_path), "sha256": _sha(review_bytes)},
        "prefilter_summary": {"path": str(summary_path), "sha256": _sha(summary_bytes)},
    }
    binding = {
        "schema": "zge-zero-to-prefix-high-position-binding/1",
        "asof": ASOF,
        "price_asof": ASOF,
        "price_basis": PRICE_BASIS,
        "source_generation": SOURCE_GENERATION,
        "metric_type": METRIC_TYPE,
        "metric_kind": METRIC_KIND,
        "field": FIELD,
        "formula": FORMULA,
        "zero_floor": 0,
        "history_scope": HISTORY_SCOPE,
        "expected_rows": len(EXPECTED_SYMBOLS),
        "expected_symbols": list(EXPECTED_SYMBOLS),
        "expected_prefilter_rows": 216,
        "expected_prefilter_unique_symbols": 216,
        "expected_prefilter_generation": SOURCE_GENERATION,
        "expected_prefilter_asof": ASOF,
        "expected_prefilter_price_basis": PRICE_BASIS,
        "accepted_prefix_unknown_count": 25,
        **entries,
    }
    bindings_bytes = json.dumps(
        {"zero_to_history_high_position": binding},
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    bindings_path = source_root / "SOURCE_BINDINGS.json"
    bindings_path.write_bytes(bindings_bytes)

    provider = Position25Provider(
        bindings_path=bindings_path,
        bindings_sha256=_sha(bindings_bytes),
        positions_sha256=entries["positions_csv"]["sha256"],
        receipt_sha256=entries["receipt"]["sha256"],
        evidence_sha256=entries["evidence"]["sha256"],
        findings_sha256=entries["findings_csv"]["sha256"],
        prefilter_sha256=entries["prefilter"]["sha256"],
        prefilter_review_sha256=entries["prefilter_review"]["sha256"],
        prefilter_summary_sha256=entries["prefilter_summary"]["sha256"],
    )
    paths = {
        "positions": positions_path,
        "bindings": bindings_path,
        "prefilter": prefilter_path,
        "prefilter_review": review_path,
        "prefilter_summary": summary_path,
    }
    return provider, paths, expected_values, prefilter_rows


def _rebind_prefilter(provider: Position25Provider, paths: dict[str, Path], rows: list[dict[str, str]]):
    prefilter_bytes = _write_csv(paths["prefilter"], rows, PREFILTER_FIELDS)
    summary = json.loads(paths["prefilter_summary"].read_text(encoding="utf-8"))
    summary["all216_csv_sha256"] = _sha(prefilter_bytes)
    summary_bytes = json.dumps(summary, sort_keys=True).encode("utf-8")
    paths["prefilter_summary"].write_bytes(summary_bytes)

    bindings = json.loads(paths["bindings"].read_text(encoding="utf-8"))
    spec = bindings["zero_to_history_high_position"]
    spec["prefilter"]["sha256"] = _sha(prefilter_bytes)
    spec["prefilter_summary"]["sha256"] = _sha(summary_bytes)
    bindings_bytes = json.dumps(bindings, ensure_ascii=False, sort_keys=True).encode("utf-8")
    paths["bindings"].write_bytes(bindings_bytes)

    return replace(
        provider,
        bindings_sha256=_sha(bindings_bytes),
        prefilter_sha256=_sha(prefilter_bytes),
        prefilter_summary_sha256=_sha(summary_bytes),
    )


def test_all_25_bound_symbols_return_only_the_frozen_field(tmp_path):
    provider, _, expected, _ = _fixture_provider(tmp_path)

    assert len(EXPECTED_SYMBOLS) == 25
    for symbol in EXPECTED_SYMBOLS:
        body = provider.get(symbol, ASOF)
        assert body["status"] == "READY"
        assert body["ts_code"] == symbol
        assert body["asof"] == ASOF
        assert body[FIELD] == expected[symbol]
        assert body["basis"] == "QFQ_ASOF"
        assert body["formula"] == FORMULA
        assert body["metric_kind"] == METRIC_KIND
        assert body["history_scope"] == HISTORY_SCOPE
        assert "not empirical CDF" in body["metric_kind"]
        assert "不是经验分位" in body["summary"]
        assert "未认证为上市全历史" in body["summary"]
        assert body["source"]["generation"] == SOURCE_GENERATION
        assert body["source"]["asof"] == ASOF
        assert "original_empirical_close_percentile_status" not in body
        assert "stock_pool" not in body
        assert body["write_policy"] == "read_only"
        assert body["production_allowed"] is False
        assert body["buy_gate_updated"] is False
        assert body["orders_sent"] is False


def test_unsupported_symbol_and_date_fail_closed(tmp_path):
    provider, _, _, _ = _fixture_provider(tmp_path)

    other_symbol = provider.get("000001.SZ", ASOF)
    other_date = provider.get("002833.SZ", "20261027")

    assert other_symbol["status"] == "CANNOT_CONFIRM"
    assert other_symbol[FIELD] is None
    assert other_symbol["cannot_confirm"] == ["TS_CODE_NOT_IN_FROZEN_25_STOCK_COHORT"]
    assert other_date["status"] == "CANNOT_CONFIRM"
    assert other_date[FIELD] is None
    assert other_date["cannot_confirm"] == ["UNSUPPORTED_ASOF:20261027"]


def test_source_sha_mismatch_fails_closed(tmp_path):
    provider, paths, _, _ = _fixture_provider(tmp_path)
    positions_path = paths["positions"]
    positions_path.write_bytes(positions_path.read_bytes() + b"\n")

    body = provider.get("002833.SZ", ASOF)

    assert body["status"] == "CANNOT_CONFIRM"
    assert body[FIELD] is None
    assert body["cannot_confirm"] == ["POSITION25_SOURCE_SHA256_MISMATCH:positions_csv"]


def test_binding_sha_mismatch_fails_closed(tmp_path):
    provider, paths, _, _ = _fixture_provider(tmp_path)
    bindings_path = paths["bindings"]
    bindings_path.write_bytes(bindings_path.read_bytes() + b" ")

    body = provider.get("002833.SZ", ASOF)

    assert body["status"] == "CANNOT_CONFIRM"
    assert body[FIELD] is None
    assert body["cannot_confirm"] == ["POSITION25_SOURCE_SHA256_MISMATCH:SOURCE_BINDINGS.json"]


def test_zero_is_a_valid_bound_position_value(tmp_path):
    provider, _, _, _ = _fixture_provider(tmp_path, zero_symbol="000156.SZ")

    body = provider.get("000156.SZ", ASOF)

    assert body["status"] == "READY"
    assert body[FIELD] == 0.0
    assert body["basis"] == "QFQ_ASOF"


@pytest.mark.parametrize("source_key", ["prefilter", "prefilter_review", "prefilter_summary"])
def test_bound_prefilter_sources_missing_fail_closed(tmp_path, source_key):
    provider, paths, _, _ = _fixture_provider(tmp_path)
    paths[source_key].unlink()

    body = provider.get("002833.SZ", ASOF)

    assert body["status"] == "CANNOT_CONFIRM"
    assert body[FIELD] is None
    if source_key == "prefilter":
        assert body["cannot_confirm"] == ["SOURCE_SHA_MISMATCH"]
    else:
        assert body["cannot_confirm"] == ["POSITION25_PREFILTER_REJECTED:SOURCE_BINDING_REJECTED"]


@pytest.mark.parametrize("source_key", ["prefilter", "prefilter_review", "prefilter_summary"])
def test_bound_prefilter_sources_sha_drift_fail_closed(tmp_path, source_key):
    provider, paths, _, _ = _fixture_provider(tmp_path)
    paths[source_key].write_bytes(paths[source_key].read_bytes() + b" ")

    body = provider.get("002833.SZ", ASOF)

    assert body["status"] == "CANNOT_CONFIRM"
    assert body[FIELD] is None
    if source_key == "prefilter":
        assert body["cannot_confirm"] == ["SOURCE_SHA_MISMATCH"]
    else:
        assert body["cannot_confirm"] == ["POSITION25_PREFILTER_REJECTED:SOURCE_BINDING_REJECTED"]


def test_bound_prefilter_duplicate_symbol_fails_closed_with_valid_hashes(tmp_path):
    provider, paths, _, rows = _fixture_provider(tmp_path)
    changed = [row.copy() for row in rows]
    changed[-1]["symbol"] = changed[-2]["symbol"]
    provider = _rebind_prefilter(provider, paths, changed)

    body = provider.get("002833.SZ", ASOF)

    assert body["status"] == "CANNOT_CONFIRM"
    assert body[FIELD] is None
    assert body["cannot_confirm"] == ["POSITION25_PREFILTER_REJECTED:SOURCE_BINDING_REJECTED"]


@pytest.mark.parametrize(
    ("field", "value"),
    [("asof", "20261022"), ("price_basis", "RAW"), ("source_generation", "other-generation")],
)
def test_bound_prefilter_context_conflict_fails_closed_with_valid_hashes(tmp_path, field, value):
    provider, paths, _, rows = _fixture_provider(tmp_path)
    changed = [row.copy() for row in rows]
    changed[-1][field] = value
    provider = _rebind_prefilter(provider, paths, changed)

    body = provider.get("002833.SZ", ASOF)

    assert body["status"] == "CANNOT_CONFIRM"
    assert body[FIELD] is None
    assert body["cannot_confirm"] == ["POSITION25_PREFILTER_REJECTED:SOURCE_BINDING_REJECTED"]


def test_requested_prefilter_row_must_match_frozen_position_row(tmp_path):
    provider, paths, _, rows = _fixture_provider(tmp_path)
    changed = [row.copy() for row in rows]
    requested = next(row for row in changed if row["symbol"] == "002833.SZ")
    requested["close_D"] = "1.000001"
    provider = _rebind_prefilter(provider, paths, changed)

    body = provider.get("002833.SZ", ASOF)

    assert body["status"] == "CANNOT_CONFIRM"
    assert body[FIELD] is None
    assert body["cannot_confirm"] == ["POSITION25_PREFILTER_REJECTED:CLOSE_D_MISMATCH"]


def test_default_provider_reuses_the_actual_bound_prefilter_semantics():
    body = Position25Provider().get("002833.SZ", ASOF)

    assert body["status"] == "READY"
    assert body[FIELD] == 70.58115430705608


def test_research_route_exposes_one_exact_read_only_position_row(tmp_path):
    provider, paths, expected, _ = _fixture_provider(tmp_path)
    app = FastAPI()
    app.include_router(create_research_router(tmp_path, position25_provider=provider))
    client = TestClient(app)

    response = client.get(
        "/api/v4/research/zero-to-history-high-position",
        params={"ts_code": "002833.SZ", "asof": ASOF},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "READY"
    assert body["ts_code"] == "002833.SZ"
    assert body["asof"] == ASOF
    assert body[FIELD] == expected["002833.SZ"]
    assert body["source"]["sha256"] == provider.positions_sha256
    assert body["source"]["generation"] == SOURCE_GENERATION
    assert body["source"]["asof"] == ASOF
    assert body["write_policy"] == "read_only"
    assert body["RESEARCH_ONLY"] is True
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False

    unsupported_symbol = client.get(
        "/api/v4/research/zero-to-history-high-position",
        params={"ts_code": "000001.SZ", "asof": ASOF},
    ).json()
    unsupported_date = client.get(
        "/api/v4/research/zero-to-history-high-position",
        params={"ts_code": "002833.SZ", "asof": "20261027"},
    ).json()
    assert unsupported_symbol["status"] == "CANNOT_CONFIRM"
    assert unsupported_symbol[FIELD] is None
    assert unsupported_date["status"] == "CANNOT_CONFIRM"
    assert unsupported_date[FIELD] is None

    paths["prefilter"].unlink()
    missing_prefilter = client.get(
        "/api/v4/research/zero-to-history-high-position",
        params={"ts_code": "002833.SZ", "asof": ASOF},
    ).json()
    assert missing_prefilter["status"] == "CANNOT_CONFIRM"
    assert missing_prefilter[FIELD] is None


def test_single_stock_repair_sop_route_reads_fixed_plain_text_source_without_cache(tmp_path, monkeypatch):
    sop_path = tmp_path / "SOP_SINGLE_STOCK_REPAIR.md"
    content = "# 固定 SOP\n<script>文本必须按原文显示</script>\n"
    raw = content.encode("utf-8")
    sop_path.write_bytes(raw)
    monkeypatch.setattr(research_router_module, "SINGLE_STOCK_REPAIR_SOP_PATH", sop_path)

    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    client = TestClient(app)
    response = client.get(
        "/api/v4/research/single-stock-repair-sop",
        params={"path": str(tmp_path / "unapproved.md")},
    )

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "READY"
    assert body["content"] == content
    assert body["source"]["path"] == str(sop_path)
    assert body["source"]["sha256"] == _sha(raw)
    assert body["source"]["size_bytes"] == len(raw)
    assert response.headers["cache-control"] == "no-store, no-cache, must-revalidate"
    assert response.headers["pragma"] == "no-cache"
    assert body["write_policy"] == "read_only"
    assert body["production_allowed"] is False
    assert body["buy_gate_updated"] is False
    assert body["orders_sent"] is False


def test_single_stock_repair_sop_route_fails_closed_when_fixed_source_is_missing(tmp_path, monkeypatch):
    missing_path = tmp_path / "missing" / "SOP_SINGLE_STOCK_REPAIR.md"
    monkeypatch.setattr(research_router_module, "SINGLE_STOCK_REPAIR_SOP_PATH", missing_path)

    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    body = TestClient(app).get("/api/v4/research/single-stock-repair-sop").json()

    assert body["status"] == "CANNOT_CONFIRM"
    assert body["content"] is None
    assert body["source"]["path"] == str(missing_path)
    assert body["cannot_confirm"] == ["SOP_SOURCE_READ_FAILED"]


def test_single_stock_repair_sop_route_fails_closed_when_fixed_source_is_unreadable(tmp_path, monkeypatch):
    unreadable_path = tmp_path / "SOP_SINGLE_STOCK_REPAIR.md"
    original_read_bytes = Path.read_bytes

    def read_bytes(path: Path) -> bytes:
        if path == unreadable_path:
            raise PermissionError("SOP source is not readable")
        return original_read_bytes(path)

    monkeypatch.setattr(research_router_module, "SINGLE_STOCK_REPAIR_SOP_PATH", unreadable_path)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)

    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    response = TestClient(app).get("/api/v4/research/single-stock-repair-sop")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "CANNOT_CONFIRM"
    assert body["content"] is None
    assert body["source"]["path"] == str(unreadable_path)
    assert body["source"]["sha256"] is None
    assert body["cannot_confirm"] == ["SOP_SOURCE_READ_FAILED"]
