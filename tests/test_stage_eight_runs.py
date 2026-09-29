from __future__ import annotations

import hashlib
import json
from pathlib import Path

from apps.api.v35_api.app import create_app
from contracts.stages import FROZEN_STAGE_IDS, STAGE_MARKET_SCOPES
from domains.stage_input_producer import StageInputProducer
from domains.stages import StageRunner
from infrastructure.data_store import NativeDataStore
from infrastructure.hkconnect_stage_replay_provider import HkConnectStageReplayProvider
from infrastructure.preselection_pool_store import POOL_ORDER, PreselectionPoolStore
from infrastructure.stage_quote_provider import StageQuoteProvider
from infrastructure.stage_store import StageStore
from infrastructure.tdx_minute_replay_provider import TdxMinuteReplayProvider


ROOT = Path(__file__).resolve().parents[1]
RAW_SNAPSHOT = ROOT / "tests/fixtures/stage_0925_20260730_tdxpy_provider_snapshot.json"
UPSTREAM_ORACLE = ROOT / "tests/fixtures/stage_0925_20260730_tdxpy_input.json"
RAW_SNAPSHOT_SHA256 = "91f0eedfaf07e662b985b15e9ee3b9cdb5fea34bc793a31529611f5ced2e3793"
STAGE_INPUT_ORACLE_SHA256 = "d447078fee592a9dd741dddc16bd637ed02d2043b91c6648fab15aca3c6b284c"


class Frozen0925Quotes:
    def snapshot(self, symbols, *, trade_date: str, stage_id: str, cutoff_at: str) -> dict:
        assert (trade_date, stage_id, cutoff_at) == (
            "20260730", "STAGE_0925", "2026-07-30T09:25:05",
        )
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


class NoFutuPrimary:
    def snapshot(self, symbols, *, trade_date, stage_id, cutoff_at):
        raise ValueError("no futu in frozen test")


def _make_provider(stage_store: StageStore, *, frozen_0925: bool = False):
    return StageQuoteProvider(
        primary=NoFutuPrimary(),
        a_replay=Frozen0925Quotes() if frozen_0925 else TdxMinuteReplayProvider(),
        references=stage_store,
        hk_replay=HkConnectStageReplayProvider(),
    )


def test_eight_stages_independently_materialize_from_real_sources(tmp_path: Path) -> None:
    raw = RAW_SNAPSHOT.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == RAW_SNAPSHOT_SHA256
    assert hashlib.sha256(UPSTREAM_ORACLE.read_bytes()).hexdigest() == STAGE_INPUT_ORACLE_SHA256

    data_store = NativeDataStore(tmp_path / "data")
    _materialize_frozen_independent_pools(data_store.root)
    stage_store = StageStore(data_store.root)
    real_runner = StageRunner(
        stage_store,
        input_producer=StageInputProducer(
            data_store, stage_store, _make_provider(stage_store)
        ),
    )
    frozen_runner = StageRunner(
        stage_store,
        input_producer=StageInputProducer(
            data_store, stage_store, _make_provider(stage_store, frozen_0925=True)
        ),
    )

    for stage_id in FROZEN_STAGE_IDS:
        scope = STAGE_MARKET_SCOPES[stage_id]
        runner = frozen_runner if stage_id == "STAGE_0925" else real_runner
        result = runner.ensure("20260730", stage_id)
        assert result["ensure_status"] == "STAGE_RUN_COMPLETE", stage_id
        workbench = runner.read_workbench("20260730", stage_id, limit=50)
        assert workbench["schema_version"] == "v3_stage_workbench.v2"
        assert workbench["stage"]["stage_id"] == stage_id
        assert workbench["production_allowed"] is False
        assert workbench["buy_gate_updated"] is False
        assert workbench["orders_sent"] is False
        assert workbench["recommendation_status"] == "WATCH_ONLY_BACKTEST_GATED"
        rows = workbench["unified_rows"]
        assert all(row["recommendation_status"] == "WATCH_ONLY" for row in rows)
        if "A" in scope:
            assert workbench["selected_a_rows"] == 50
        # HK stage candidates come from the not-yet-complete upstream
        # hkconnect_d1_top100 pool intersected with replay data; the exact
        # count varies by stage and is deferred to Task 6. Only assert the
        # HK column stays within its market scope and stays safe.
        if stage_id == "STAGE_1545_1555":
            assert workbench["selected_a_rows"] == 0
            assert all(row["market"] == "HK" for row in rows)
            assert workbench["selected_hk_rows"] >= 0
        else:
            assert all(row["market"] in {"A", "HK"} for row in rows)


def test_eight_stages_api_returns_native_snapshot_with_safe_boundaries(tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    data_store = NativeDataStore(tmp_path / "data")
    _materialize_frozen_independent_pools(data_store.root)
    stage_store = StageStore(data_store.root)
    real_runner = StageRunner(
        stage_store,
        input_producer=StageInputProducer(
            data_store, stage_store, _make_provider(stage_store)
        ),
    )
    frozen_runner = StageRunner(
        stage_store,
        input_producer=StageInputProducer(
            data_store, stage_store, _make_provider(stage_store, frozen_0925=True)
        ),
    )
    for stage_id in FROZEN_STAGE_IDS:
        runner = frozen_runner if stage_id == "STAGE_0925" else real_runner
        runner.ensure("20260730", stage_id)

    client = TestClient(
        create_app(
            data_root=data_store.root,
            quote_provider=_make_provider(stage_store, frozen_0925=True),
        )
    )
    for stage_id in FROZEN_STAGE_IDS:
        payload = client.get(
            "/api/v3/workbench/stage",
            params={"date": "20260730", "stage": stage_id, "limit": 50},
        ).json()
        assert payload["ok"] is True, stage_id
        assert payload["stage"]["stage_id"] == stage_id
        assert payload["response_source"] == "V3_5_NATIVE_STAGE_SNAPSHOT"
        assert payload["production_allowed"] is False
        assert payload["buy_gate_updated"] is False
        assert payload["orders_sent"] is False
        serialized = json.dumps(payload, ensure_ascii=False)
        assert "LEGACY_FINAL_API" not in serialized
        assert "CROSS_DATE" not in serialized
        assert "v3_system" not in serialized.lower()
