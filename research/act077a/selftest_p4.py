"""Synthetic fixtures for the ACT-077A P4 signed-row change."""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from math import isclose

from research.act070a.case_contract import Rejected, case_digest, json_bytes
from research.act077a.p4 import BINDING, P4_FIELDS, WINDOWS, bind_p4


def fixture() -> dict:
    bars = []
    for index in range(1, 36):
        day = (date(2020, 1, 1) + timedelta(days=index - 1)).isoformat()
        bars.append({
            "row_id": f"K01_BAR_{index:02d}", "kind": "CHART_BAR", "status": "OBSERVED_D_ONLY",
            "occurred_date": day, "first_knowable_date": day,
            "source": {"id": "synthetic", "stock_session_index": 100 + index},
            "fields": {"date": day, "open": 10, "close": (11, 9, 10)[index % 3],
                       "low": 8, "high": 12, "volume": index},
        })
    day = bars[-1]["fields"]["date"]
    p4 = [{
        "row_id": f"K01_PRIM_P4_{index}", "kind": "PRIMITIVE", "status": "MISSING_SOURCE",
        "primitive_id": "P4", "fields": {field: "UNKNOWN"}, "source": {"id": "synthetic_unbound"},
        "occurred_date": day, "first_knowable_date": day, "gap_reason": "SEGMENT_DEFINITION_SOURCE_UNBOUND",
    } for index, field in enumerate(P4_FIELDS, start=24)]
    context = {"row_id": "K01_A_CONTEXT", "kind": "A_CONTEXT", "fields": {"p4_segment_binding": "UNBOUND"}}
    case = {"case_id": "K01", "scope": "KB_BENCHMARK", "d": day, "rows": [*bars, *p4, context],
            "chart": {"row_ids": [item["row_id"] for item in bars], "png_sha256": "a" * 64, "svg_sha256": "b" * 64},
            "schema_sha256": "c" * 64, "kb_sha256": "d" * 64,
            "immutable_b2": {"day_eligibility": "FALSE", "formal_b2_event_presence": "ABSENT"}}
    case["input_sha256"] = case_digest(case)
    return case


def values(case: dict) -> dict:
    return {key: value for row in case["rows"] if row.get("primitive_id") == "P4"
            for key, value in row["fields"].items()}


def check_unchanged() -> None:
    base = fixture()
    original = json_bytes(base)
    got = bind_p4(base)
    assert original == json_bytes(base)
    assert got["input_sha256"] == case_digest(got) != base["input_sha256"]
    assert json_bytes(got) == json_bytes(bind_p4(base))
    assert json_bytes({k: v for k, v in base.items() if k not in {"rows", "input_sha256"}}) == json_bytes({
        k: v for k, v in got.items() if k not in {"rows", "input_sha256"}
    })
    unchanged, changed = [], []
    for before, after in zip(base["rows"], got["rows"], strict=True):
        assert before["row_id"] == after["row_id"]
        (unchanged if json_bytes(before) == json_bytes(after) else changed).append(after)
    assert len(unchanged) == 36 and len(changed) == 5
    assert all(row["status"] == "OBSERVED_D_ONLY" and row["occurred_date"] == got["d"] for row in changed)
    got = values(got)
    assert got["registered_segment"]["binding"] == BINDING
    assert got["registered_segment"]["structural_event_binding"] == "UNBOUND"
    windows = got["chronological_candle_volume"]["windows"]
    for size in WINDOWS:
        window = windows[str(size)]
        assert window["bars"][-1]["date"] == base["d"]
        assert [bar["row_id"] for bar in window["bars"]] == [
            row["row_id"] for row in base["rows"][35 - size:35]
        ]
        assert [bar["volume"] for bar in window["bars"]] == list(range(36 - size, 36))
    assert got["up_candle_volume"]["windows"]["5"] == {"count": 1, "sum": 33, "mean": 33}
    assert got["down_candle_volume"]["windows"]["5"] == {"count": 2, "sum": 65, "mean": 32.5}
    assert got["flat_candle_volume"]["windows"]["5"] == {"count": 2, "sum": 67, "mean": 33.5}
    assert isclose(windows["5"]["up_to_down_sum_ratio"]["value"], 33 / 65)
    assert isclose(windows["5"]["up_to_down_mean_ratio"]["value"], 33 / 32.5)
    assert isclose(got["chronological_candle_volume"]["vr5"]["value"], 35 / 33)


def check_uncomputable() -> None:
    base = fixture()
    for row in base["rows"][30:35]:
        row["fields"]["close"] = 11
    base["input_sha256"] = case_digest(base)
    got = values(bind_p4(base))
    assert got["down_candle_volume"]["windows"]["5"] == {"count": 0, "sum": None, "mean": None}
    chronology = got["chronological_candle_volume"]
    assert chronology["windows"]["5"]["up_to_down_sum_ratio"] == {"value": None, "status": "UNCOMPUTABLE"}
    assert chronology["windows"]["5"]["up_to_down_mean_ratio"] == {"value": None, "status": "UNCOMPUTABLE"}
    assert isclose(chronology["vr5"]["value"], 35 / 33)
    base["rows"][30]["fields"].update({"close": 9, "volume": 0})
    base["input_sha256"] = case_digest(base)
    got = values(bind_p4(base))
    assert got["down_candle_volume"]["windows"]["5"] == {"count": 1, "sum": 0, "mean": None}
    chronology = got["chronological_candle_volume"]
    for name in ("up_to_down_sum_ratio", "up_to_down_mean_ratio"):
        assert chronology["windows"]["5"][name] == {"value": None, "status": "UNCOMPUTABLE"}
    assert isclose(chronology["vr5"]["value"], 175 / 134)
    for row in base["rows"][30:35]:
        row["fields"]["volume"] = 0
    base["input_sha256"] = case_digest(base)
    assert values(bind_p4(base))["chronological_candle_volume"]["vr5"]["value"] is None


def check_rejection() -> None:
    base = fixture()
    extra = deepcopy(base)
    extra["rows"].append(deepcopy(extra["rows"][35]))
    future = deepcopy(base)
    future["rows"][34]["fields"]["date"] = "2020-02-05"
    for case, code in ((extra, "INVALID_P4_ROSTER"), (future, "INVALID_D_PREFIX")):
        case["input_sha256"] = case_digest(case)
        try:
            bind_p4(case)
        except Rejected as exc:
            assert exc.code == code
        else:
            raise AssertionError(f"{code} was not enforced")


def main():
    check_unchanged()
    check_uncomputable()
    check_rejection()
    print('{"status":"PASS","checks":3,"p4_rows_changed":5,"model_calls":0,"market_source_opens":0}')


if __name__ == "__main__":
    main()
