"""Offline refresh-failure regression; not live source acceptance."""
from domains.stages import StageRunner
from infrastructure.stage_store import StageStore
SAFE = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}

def test_force_refresh_failure_does_not_reuse_old_input(tmp_path):
    store=StageStore(tmp_path/"data")
    payload={"schema_version": "v3_5.stage_input.v1", "trade_date": "20260730",
             "stage_id": "STAGE_0925", "cutoff_reached": True,
             "market_status": {"A": "READY", "HK": "CANNOT_CONFIRM"},
             "rows": {"A": [{"symbol": "A.000001", "last_price": 11,
                               "prev_close_price": 10, "recommendation_status": "WATCH_ONLY"}], "HK": []},
             "source_evidence": [{"path": "fixture.json", "sha256": "a"*64}],
             "recommendation_status": "WATCH_ONLY_BACKTEST_GATED", **SAFE}
    store.import_input(payload)
    _, before_sha=store.read_input("20260730", "STAGE_0925")
    class BrokenRefresh:
        def refresh(self, date, stage):
            raise OSError("offline test: refreshed source unavailable")
    result=StageRunner(store, input_producer=BrokenRefresh()).ensure("20260730", "STAGE_0925", force=True)
    assert result["ok"] is False
    assert "STAGE_INPUT_REFRESH_BLOCKED" in str(result)
    assert store.read_latest("20260730", "STAGE_0925") is None
    assert store.read_input("20260730", "STAGE_0925")[1] == before_sha

