"""Offline contract regressions; fixtures are NOT real market/source evidence."""
from copy import deepcopy
import pytest
from domains.stage_input_producer import StageInputProducer
from domains.stages import StageRunner
from infrastructure.data_store import NativeDataStore
from infrastructure.stage_store import StageStore

SAFE = {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False}

@pytest.mark.parametrize("prefix,count", [("HK.", 100), ("A.", 137)])
def test_quote_response_cannot_enlarge_frozen_candidates(prefix, count):
    width = 5 if prefix == "HK." else 6
    candidates = [{"symbol": f"{prefix}{i:0{width}d}", "pool_rank": i,
                   "signal_date": "20260729", "target_date": "20260730"}
                  for i in range(1, count + 1)]
    original = deepcopy(candidates)
    # A missing quote must leave a hole, not be replaced by an unsolicited symbol.
    quotes = {c["symbol"]: {"symbol": c["symbol"], "last_price": 11, "prev_close_price": 10}
              for c in reversed(candidates) if c["pool_rank"] != 3}
    foreign = f"{prefix}{99999:0{width}d}"
    quotes[foreign] = {"symbol": foreign, "last_price": 99, "prev_close_price": 1}
    a, hk = StageInputProducer._merge_candidates(candidates, quotes)
    result = hk if prefix == "HK." else a
    assert [r["symbol"] for r in result] == [c["symbol"] for c in candidates if c["pool_rank"] != 3]
    assert [r["pool_rank"] for r in result] == [i for i in range(1, count+1) if i != 3]
    assert candidates == original

@pytest.mark.parametrize("prefix", ["HK.", "A."])
def test_incomplete_quote_coverage_never_claims_ready(tmp_path, prefix):
    candidates = [{"symbol": prefix + ("00001" if prefix == "HK." else "000001")},
                  {"symbol": prefix + ("00002" if prefix == "HK." else "000002")}]
    class Provider:
        def snapshot(self, symbols, *, trade_date, stage_id, cutoff_at):
            return {"schema_version": "v3_5.read_only_quote_batch.v1", "trade_date": trade_date,
                    "stage_id": stage_id, "captured_at": "2026-07-30T09:25:00",
                    "temporal_cutoff_safe": True, "source": "OFFLINE_TEST_FIXTURE",
                    "rows": [{"symbol": candidates[0]["symbol"], "last_price": 11, "prev_close_price": 10}], **SAFE}
    native=NativeDataStore(tmp_path/"data")
    store=StageStore(native.root)
    producer=StageInputProducer(native, store, Provider())
    # Isolate pool discovery; production merge, validation and disk store are real.
    producer._stage_candidates=lambda date: (deepcopy(candidates), "CANONICAL_COMPLETE", [], [])
    producer.produce("20260730", "STAGE_0925")
    payload, _=store.read_input("20260730", "STAGE_0925")
    market="HK" if prefix == "HK." else "A"
    assert payload["market_status"][market] == "CANNOT_CONFIRM"
    coverage=payload["source_summary"]["quote_coverage"][market]
    assert coverage == {"requested": 2, "returned": 1, "missing": 1}
    assert all(payload[k] is False for k in SAFE)




def test_canonical_a_candidates_are_not_a_truncated_display_projection(tmp_path):
    a1={"symbol":"A.000001","recommendation_status":"WATCH_ONLY"}
    a2={"symbol":"A.000002","recommendation_status":"WATCH_ONLY"}
    payload={"schema_version":"v3_preselection_pools.v1","trade_date":"20260730",
        "module_id":"unified_preselection_pools","write_policy":"read_only",
        "recommendation_status":"WATCH_ONLY_BACKTEST_GATED", **SAFE,
        "producer_status":"CANONICAL_COMPLETE","data_status":"READY_WITH_ROWS",
        "canonical_main_pool_confirmed":True,"source_lane":"CANONICAL_MAIN",
        "selector_status":"READY","strict_0_2_status":"STRICT_0_2_READY",
        "pools":[{"pool_id":"main","rows":[a1,a2]}],
        "rows":[a1],"unified_rows":[a1],"a_source_only_rows":[a1,a2],
        "a_all_pool_rows":[a1,a2],"cannot_confirm":[]}
    native=NativeDataStore(tmp_path/"data")
    native.import_payload(payload)
    producer=StageInputProducer(native, StageStore(native.root), None)
    candidates,status,_,_=producer._stage_candidates("20260730")
    assert status=="CANONICAL_COMPLETE"
    assert [row["symbol"] for row in candidates] == ["A.000001","A.000002"]
