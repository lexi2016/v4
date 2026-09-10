from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app
from domains.stage_input_producer import StageInputProducer
from domains.stages import StageRunner
from infrastructure.data_store import NativeDataStore, _sha256
from infrastructure.preselection_pool_store import POOL_ORDER, PreselectionPoolStore
from infrastructure.stage_store import StageStore


ROOT = Path(__file__).resolve().parents[1]
RAW_SNAPSHOT = ROOT / "tests/fixtures/stage_0925_20260730_tdxpy_provider_snapshot.json"
UPSTREAM_ORACLE = ROOT / "tests/fixtures/stage_0925_20260730_tdxpy_input.json"
RAW_SNAPSHOT_SHA256 = "91f0eedfaf07e662b985b15e9ee3b9cdb5fea34bc793a31529611f5ced2e3793"
STAGE_INPUT_ORACLE_SHA256 = "d447078fee592a9dd741dddc16bd637ed02d2043b91c6648fab15aca3c6b284c"
EXPECTED_A_SELECTED_SYMBOLS = (
    "A.605068", "A.603221", "A.605179", "A.000428", "A.002827",
    "A.300981", "A.003032", "A.605388", "A.002882", "A.002558",
    "A.603163", "A.601003", "A.002903", "A.002517", "A.000636",
    "A.000668", "A.002298", "A.603719", "A.002432", "A.603559",
    "A.002141", "A.002674", "A.605188", "A.603556", "A.600236",
    "A.600722", "A.003043", "A.600578", "A.600733", "A.002045",
    "A.002979", "A.002945", "A.002937", "A.603407", "A.002396",
    "A.002791", "A.002563", "A.603801", "A.600521", "A.603127",
    "A.605296", "A.300765", "A.603233", "A.002668", "A.603399",
    "A.002552", "A.000779", "A.688382", "A.002550", "A.600228",
)


class Frozen0925Quotes:
    def __init__(self) -> None:
        self.requested_symbols: tuple[str, ...] = ()

    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str) -> dict:
        assert (trade_date, stage_id, cutoff_at) == (
            "20260730",
            "STAGE_0925",
            "2026-07-30T09:25:05",
        )
        self.requested_symbols = tuple(symbols)
        return json.loads(RAW_SNAPSHOT.read_text(encoding="utf-8"))


def _materialize_frozen_independent_pools(root: Path) -> None:
    oracle = json.loads(UPSTREAM_ORACLE.read_text(encoding="utf-8"))
    rows_by_pool = {pool_id: [] for pool_id in POOL_ORDER}
    upstream_fields = (
        "symbol", "market", "pool_id", "pool_rank", "pool_score", "signal_date",
        "source_label", "source_trace_sha256", "stock_name", "target_date",
    )
    for market in ("A", "HK"):
        for row in oracle["rows"][market]:
            rows_by_pool[row["pool_id"]].append(
                {field: row[field] for field in upstream_fields if field in row}
            )
    rows_by_pool["a_d1_premarket_pool"].append(
        {
            "symbol": "A.300333", "market": "A", "pool_id": "a_d1_premarket_pool",
            "pool_rank": 999, "pool_score": 0.0, "signal_date": "20260729",
            "source_label": "frozen upstream missing quote", "source_trace_sha256": "0" * 64,
            "stock_name": "A.300333", "target_date": "20260730",
        }
    )
    store = PreselectionPoolStore(root)
    for pool_id in POOL_ORDER:
        rows = rows_by_pool[pool_id]
        store.materialize(
            {
                "schema_version": "v3_5.preselection_pool.v1", "trade_date": "20260730",
                "pool_id": pool_id, "display_name": pool_id,
                "market": "HK" if pool_id == "hkconnect_d1_top100" else "A",
                "status": "available" if rows else "CANNOT_CONFIRM", "producer_id": "FROZEN_TEST",
                "source_role": "UPSTREAM_PRODUCER_ARTIFACT" if rows else "EXPECTED_MISSING",
                "source_path": f"fixtures/{pool_id}.json" if rows else "",
                "source_sha256": hashlib.sha256(pool_id.encode()).hexdigest(), "rows": rows,
                "cannot_confirm": [] if rows else ["EXPECTED_MISSING"],
                "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            }
        )


def test_0925_independent_upstream_to_native_stage_parity(tmp_path: Path) -> None:
    raw = RAW_SNAPSHOT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RAW_SNAPSHOT_SHA256
    snapshot = json.loads(raw)
    assert snapshot["schema_version"] == "v3_5.read_only_quote_batch.v1"
    assert (snapshot["trade_date"], snapshot["stage_id"], snapshot["captured_at"]) == (
        "20260730", "STAGE_0925", "2026-07-30T09:25:05",
    )
    assert snapshot["temporal_cutoff_safe"] is True
    a_snapshot_rows = [row for row in snapshot["rows"] if row["symbol"].startswith("A.")]
    assert len(a_snapshot_rows) == 146
    assert {row["source_method"] for row in a_snapshot_rows} == {
        "pytdx.hq.get_history_transaction_data"
    }
    assert "A.300333" not in {row["symbol"] for row in a_snapshot_rows}
    assert hashlib.sha256(UPSTREAM_ORACLE.read_bytes()).hexdigest() == STAGE_INPUT_ORACLE_SHA256

    data_store = NativeDataStore(tmp_path / "data")
    _materialize_frozen_independent_pools(data_store.root)
    stage_store = StageStore(data_store.root)
    quote_provider = Frozen0925Quotes()
    produced = StageInputProducer(data_store, stage_store, quote_provider).produce(
        "20260730", "STAGE_0925"
    )
    stage_input, _input_sha = stage_store.read_input("20260730", "STAGE_0925")

    assert (produced["a_rows"], produced["hk_rows"]) == (146, 10)
    assert stage_input["source_summary"]["requested_A"] == 147
    requested_a_symbols = {
        symbol for symbol in quote_provider.requested_symbols if symbol.startswith("A.")
    }
    snapshot_a_symbols = {row["symbol"] for row in a_snapshot_rows}
    assert requested_a_symbols - snapshot_a_symbols == {"A.300333"}
    assert stage_input["market_status"] == {"A": "CANNOT_CONFIRM", "HK": "CANNOT_CONFIRM"}
    assert stage_input["source_evidence"][-1] == {
        "path": f"stage_sources/20260730/STAGE_0925/{RAW_SNAPSHOT_SHA256}.json",
        "sha256": RAW_SNAPSHOT_SHA256,
    }
    assert "PYTDX_0925_AUCTION_ROWS_MISSING: A.300333" in stage_input["source_summary"]["cannot_confirm"]
    assert "HK_STAGE_ROWS_FROM_LOCAL_MIGRATED_REFERENCE" in stage_input["source_summary"]["cannot_confirm"]

    result = StageRunner(stage_store).ensure("20260730", "STAGE_0925")
    assert result["ensure_status"] == "STAGE_RUN_COMPLETE"
    published = stage_store.read_latest("20260730", "STAGE_0925")
    assert published is not None
    assert published["manifest"]["artifact_sha256"] == published["artifact_sha256"]
    assert published["receipt"]["artifact_sha256"] == published["artifact_sha256"]
    assert published["receipt"]["manifest_sha256"] == published["manifest_sha256"]
    assert _sha256(published["artifact"]) == published["artifact_sha256"]
    workbench = StageRunner(stage_store).read_workbench("20260730", "STAGE_0925", limit=50)
    assert workbench["markets"]["A"]["candidate_count"] == 50
    assert workbench["selected_a_rows"] == 50
    assert tuple(row["symbol"] for row in workbench["stage_groups"][0]["rows"]) == (
        EXPECTED_A_SELECTED_SYMBOLS
    )

    response = TestClient(
        create_app(data_root=data_store.root, quote_provider=Frozen0925Quotes())
    ).get("/api/v3/workbench/stage?date=20260730&stage=STAGE_0925&limit=50")
    assert response.status_code == 200
    payload = response.json()
    assert payload["response_source"] == "V3_5_NATIVE_STAGE_SNAPSHOT"
    assert payload["markets"]["A"]["requested_rows"] == 147
    assert payload["markets"]["A"]["source_rows"] == 146
    assert payload["markets"]["A"]["candidate_count"] == 50
    assert payload["selected_a_rows"] == 50
    assert len(payload["stage_groups"][0]["rows"]) == 50
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "LEGACY_FINAL_API" not in serialized
    assert "FUTU" not in serialized
    assert "1MIN_REPLAY" not in serialized
    assert "CROSS_DATE" not in serialized
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False
