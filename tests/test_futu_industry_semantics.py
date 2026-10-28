from __future__ import annotations

from copy import deepcopy
from datetime import datetime

import pytest

from ops._us_market_digest_parts import futu_boards
from ops._us_market_digest_parts.futu_boards import (
    FUTU_BOARD_MAP,
    _empty_row,
    build_futu_board_snapshot,
    validate_futu_board_snapshot,
)
from contracts.futu_us_boards import FUTU_US_BOARD_REGISTRY


@pytest.fixture(autouse=True)
def _advance_fake_membership_clock_without_waiting(monkeypatch):
    current = {"seconds": 0.0}

    def monotonic():
        current["seconds"] += 31.0
        return current["seconds"]

    monkeypatch.setattr(futu_boards, "_monotonic", monotonic)
    monkeypatch.setattr(futu_boards, "_sleep", lambda _seconds: None)


class _FutuFrame:
    def __init__(self, records):
        self.records = records

    def to_dict(self, _orient="records"):
        return self.records


class _FakeFutuContext:
    def __init__(self, *, plate_valid=True, counts=(15, 5, 0), update_time="2026-10-15 16:00:00"):
        self.plate_valid = plate_valid
        self.counts = counts
        self.update_time = update_time
        self.codes = {
            (item["plate_type"], item["board_name"]): item["board_code"]
            for item in FUTU_US_BOARD_REGISTRY
        }
        self.market_snapshot_codes = []
        self.membership_request_times = []

    def get_plate_list(self, _market, plate_type):
        plate_type = str(plate_type)
        rows = [
            {"code": code, "plate_name": name, "plate_id": code.split(".")[-1]}
            for (kind, name), code in self.codes.items()
            if kind == plate_type
        ]
        return 0, _FutuFrame(rows)

    def get_market_snapshot(self, codes):
        self.market_snapshot_codes.extend(codes)
        rise, fall, equal = self.counts
        return 0, _FutuFrame([
            {
                "code": code,
                "last_price": 1714.89389738,
                "prev_close_price": 1702.967168873,
                "update_time": self.update_time,
                "plate_valid": self.plate_valid,
                "plate_raise_count": rise,
                "plate_fall_count": fall,
                "plate_equal_count": equal,
            }
            for code in codes
        ])

    def get_plate_stock(self, code):
        self.membership_request_times.append(futu_boards._monotonic())
        if code == self.codes[("CONCEPT", "云计算服务商")]:
            return 0, _FutuFrame([{"code": "US.NVDA"}, {"code": "US.MSFT"}])
        return 0, _FutuFrame([{"code": "US.AMD"}])


class _MilitaryCatalogContext(_FakeFutuContext):
    def __init__(self, military_candidates):
        super().__init__()
        self.military_candidates = military_candidates

    def get_plate_list(self, market, plate_type):
        ret, frame = super().get_plate_list(market, plate_type)
        if str(plate_type) != "INDUSTRY":
            return ret, frame
        rows = [
            row for row in frame.records
            if row["plate_name"] != "航空航天与国防"
        ]
        return ret, _FutuFrame(rows + self.military_candidates)


def test_futu_board_map_adds_only_the_confirmed_military_industry():
    expected = (
        ("AI算力", None, None),
        ("CPO", None, None),
        ("半导体", "INDUSTRY", "半导体"),
        ("存储", "CONCEPT", "存储概念"),
        ("数据中心", "CONCEPT", "IDC概念"),
        ("云计算", "CONCEPT", "云计算服务商"),
        ("商业航天", None, None),
        ("卫星", None, None),
        ("机器人", "CONCEPT", "机器人概念股"),
        ("自动驾驶", "CONCEPT", "智能驾驶概念股"),
        ("核电", "CONCEPT", "核电"),
        ("电网", None, None),
        ("军工", "INDUSTRY", "航空航天与国防"),
        ("新能源", None, None),
        ("光伏", "CONCEPT", "光伏太阳能"),
        ("锂电池", "CONCEPT", "锂电池"),
        ("石油", None, None),
        ("天然气", "CONCEPT", "天然气"),
        ("铜/有色", None, None),
        ("黄金", "INDUSTRY", "黄金"),
        ("银行金融", None, None),
        ("生物医药", None, None),
        ("消费", None, None),
        ("稀土", "CONCEPT", "稀土概念"),
    )
    assert tuple(
        (row["label"], row["plate_type"], row["plate_name"])
        for row in FUTU_BOARD_MAP
    ) == expected


def test_military_board_requires_exact_unique_provider_name():
    exact_and_near = _MilitaryCatalogContext([
        {"code": "US.LIST2089", "plate_name": "航空航天与国防"},
        {"code": "US.LIST2999", "plate_name": "航空航天"},
    ])
    snapshot = build_futu_board_snapshot("20261015", quote_context=exact_and_near)
    military = next(row for row in snapshot["rows"] if row["label"] == "军工")
    assert military["status"] == "READY"
    assert military["plate_type"] == "INDUSTRY"
    assert military["expected_board_name"] == military["board_name"] == "航空航天与国防"
    assert military["board_code"] == "US.LIST2089"
    assert "US.LIST2089" in exact_and_near.market_snapshot_codes
    assert len(exact_and_near.membership_request_times) == len(FUTU_US_BOARD_REGISTRY)
    assert sum(row["status"] == "READY" for row in snapshot["rows"]) == 13

    near_only = _MilitaryCatalogContext([
        {"code": "US.LIST2999", "plate_name": "航空航天"},
    ])
    missing = build_futu_board_snapshot("20261015", quote_context=near_only)
    unresolved = next(row for row in missing["rows"] if row["label"] == "军工")
    assert unresolved["status"] == "CANNOT_CONFIRM"
    assert unresolved["board_code"] is None
    assert unresolved["cannot_confirm"] == ["FUTU_BOARD_MATCH_MISSING"]

    duplicate = _MilitaryCatalogContext([
        {"code": "US.LIST2089", "plate_name": "航空航天与国防"},
        {"code": "US.LIST2090", "plate_name": "航空航天与国防"},
    ])
    ambiguous = build_futu_board_snapshot("20261015", quote_context=duplicate)
    unresolved_duplicate = next(row for row in ambiguous["rows"] if row["label"] == "军工")
    assert unresolved_duplicate["status"] == "CANNOT_CONFIRM"
    assert unresolved_duplicate["board_code"] is None
    assert unresolved_duplicate["cannot_confirm"] == ["FUTU_BOARD_MATCH_AMBIGUOUS"]


def test_legacy_unmapped_military_placeholder_remains_cannot_confirm():
    snapshot = build_futu_board_snapshot("20261015", quote_context=_FakeFutuContext())
    original_rows = deepcopy(snapshot["rows"])
    military_index = next(i for i, row in enumerate(snapshot["rows"]) if row["label"] == "军工")
    legacy_row = _empty_row(
        {"label": "军工", "plate_type": None, "plate_name": None},
        "FUTU_BOARD_MATCH_UNCONFIRMED",
    )
    snapshot["rows"][military_index] = legacy_row

    validated = validate_futu_board_snapshot(snapshot, expected_session_date="20261015")

    assert validated["rows"][military_index] == legacy_row
    assert validated["rows"][military_index]["status"] == "CANNOT_CONFIRM"
    assert sum(row["status"] == "READY" for row in validated["rows"]) == 12
    assert all(
        validated["rows"][index] == original_rows[index]
        for index in range(len(original_rows))
        if index != military_index
    )


def test_membership_requests_are_limited_to_ten_per_thirty_seconds(monkeypatch):
    now = {"seconds": 0.0}
    sleeps = []

    def monotonic():
        return now["seconds"]

    def sleep(seconds):
        sleeps.append(seconds)
        now["seconds"] += seconds

    monkeypatch.setattr(futu_boards, "_monotonic", monotonic)
    monkeypatch.setattr(futu_boards, "_sleep", sleep)
    context = _FakeFutuContext()

    snapshot = build_futu_board_snapshot("20261015", quote_context=context)

    request_times = context.membership_request_times
    assert len(request_times) == len(FUTU_US_BOARD_REGISTRY)
    assert request_times[:10] == [0.0] * 10
    assert request_times[10:20] == [30.0] * 10
    assert request_times[20:] == [60.0] * 4
    assert sleeps == [30.0, 30.0]
    for start in set(request_times):
        assert sum(start <= requested_at < start + 30.0 for requested_at in request_times) <= 10
    assert sum(row["status"] == "READY" for row in snapshot["rows"]) == 13
    assert sum(sleeps) == 60.0


def test_exact_futu_board_metrics_are_separate_from_proxy_lane_and_cover_24_labels():
    snapshot = build_futu_board_snapshot("20261015", quote_context=_FakeFutuContext())

    assert len(snapshot["rows"]) == 24
    cloud = next(row for row in snapshot["rows"] if row["label"] == "云计算")
    assert cloud["board_code"] == "US.LIST2540"
    assert cloud["board_name"] == "云计算服务商"
    assert cloud["metric_kind"] == "OFFICIAL_BOARD"
    assert cloud["change_pct"] == 0.70035
    assert (cloud["rise_count"], cloud["fall_count"], cloud["equal_count"]) == (15, 5, 0)
    assert cloud["plate_valid"] is True
    assert cloud["session_date"] == "20261015"
    assert cloud["relation_constituents"] == ["NVDA"]

    # A Futu miss remains a miss even when an ETF proxy happens to have a quote.
    cpo = next(row for row in snapshot["rows"] if row["label"] == "CPO")
    assert cpo["status"] == "CANNOT_CONFIRM"
    assert cpo["change_pct"] is None
    assert cpo["board_code"] is None
    assert cpo["cannot_confirm"] == ["FUTU_BOARD_MATCH_UNCONFIRMED"]


def test_invalid_plate_or_missing_breadth_fields_never_becomes_zero():
    invalid = build_futu_board_snapshot(
        "20261015",
        quote_context=_FakeFutuContext(plate_valid=False, counts=(None, None, None)),
    )
    cloud = next(row for row in invalid["rows"] if row["label"] == "云计算")
    assert cloud["status"] == "CANNOT_CONFIRM"
    assert cloud["plate_valid"] is False
    assert cloud["rise_count"] is cloud["fall_count"] is cloud["equal_count"] is None

    missing = build_futu_board_snapshot(
        "20261015",
        quote_context=_FakeFutuContext(plate_valid=True, counts=(15, None, 0)),
    )
    cloud_missing = next(row for row in missing["rows"] if row["label"] == "云计算")
    assert cloud_missing["status"] == "CANNOT_CONFIRM"
    assert cloud_missing["rise_count"] == 15
    assert cloud_missing["fall_count"] is None
    assert "FUTU_BOARD_BREADTH_FIELDS_MISSING_OR_INVALID" in cloud_missing["cannot_confirm"]


def test_wrong_board_session_is_not_backfilled_or_relabelled():
    snapshot = build_futu_board_snapshot(
        "20261016",
        quote_context=_FakeFutuContext(update_time="2026-10-15 16:00:00"),
    )
    cloud = next(row for row in snapshot["rows"] if row["label"] == "云计算")
    assert cloud["session_date"] == "20261015"
    assert cloud["change_pct"] is None
    assert cloud["status"] == "CANNOT_CONFIRM"
    assert "FUTU_BOARD_SESSION_DATE_MISMATCH" in cloud["cannot_confirm"]


def test_post_close_store_and_api_projection_keep_board_and_proxy_metrics_separate(tmp_path):
    from infrastructure.research_peripheral_store import ResearchPeripheralStore
    from ops.us_market_digest import GLOBAL_INDUSTRY_PROXY_MAP, materialize_us_market_phase
    from apps.api.v35_api.research_lane_router import _project_global_industries

    session_date = "20261015"
    captured_at = "2026-10-15T16:15:00-04:00"

    def fetch_proxy_quotes(_url, _timeout):
        symbols = list(dict.fromkeys(
            symbol
            for mapping in GLOBAL_INDUSTRY_PROXY_MAP
            for symbol in mapping["proxy_symbols"]
        ))
        records = []
        for symbol in symbols:
            fields = [""] * 31
            fields[1:5] = [symbol, symbol, "110", "100"]
            fields[30] = f"{session_date}160000"
            records.append(f'v_us{symbol}="' + "~".join(fields) + '";')
        return "".join(records)

    result = materialize_us_market_phase(
        data_root=tmp_path / "data",
        trade_date=session_date,
        capture_phase="POST_CLOSE",
        fetched_at=captured_at,
        fetch_rss=lambda _url, _timeout: b"<rss><channel></channel></rss>",
        fetch_quotes=fetch_proxy_quotes,
        fetch_futu_boards=lambda date: build_futu_board_snapshot(
            date, quote_context=_FakeFutuContext()
        ),
    )
    assert result["market_snapshot_status"] == "READY"
    store = ResearchPeripheralStore(tmp_path / "data")
    persisted = store.read_exact(session_date, "external_finance")
    assert persisted is not None
    futu = persisted["market_snapshot"]["futu_board_snapshot"]
    assert futu["status"] == "PARTIAL"

    projected = _project_global_industries(store=store, research_date=session_date)
    cloud = next(row for row in projected["rows"] if row["label"] == "云计算")
    assert projected["schema_version"] == "v3_5.global_industries.v2"
    assert projected["status"] == "PARTIAL"
    assert cloud["change_pct"] == 0.70035
    assert cloud["official_board"]["rise_count"] == 15
    assert cloud["official_board"]["fall_count"] == 5
    assert cloud["official_board"]["equal_count"] == 0
    assert cloud["proxy_reference"]["change_pct"] == 10.0
    assert cloud["proxy_reference"]["metric_kind"] == "ETF_REFERENCE"
    assert cloud["official_board"]["relations"][0]["hk_symbol"] == "HK.00992"
    assert projected["a_share_relations"] == []
    assert projected["RESEARCH_ONLY"] is True
    assert projected["production_allowed"] is False
    assert projected["buy_gate_updated"] is False
    assert projected["orders_sent"] is False
    native = projected["native_board_snapshot"]
    assert native["schema_version"] == "v3_5.futu_us_native_board_snapshot.v2"
    assert native["requested_board_count"] == len(FUTU_US_BOARD_REGISTRY)
    assert native["available_board_count"] == len(FUTU_US_BOARD_REGISTRY)
    assert len({row["board_code"] for row in native["rows"]}) == len(FUTU_US_BOARD_REGISTRY)
    assert all("proxy_reference" not in row and "relations" not in row for row in native["rows"])
    assert next(row for row in native["rows"] if row["board_name"] == "云计算服务商")["board_code"] == "US.LIST2540"


def test_us_market_get_keeps_confirmed_futu_boards_visible_when_proxy_quotes_are_separate(
    tmp_path, monkeypatch
):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from apps.api.v35_api.research_lane_router import create_research_lane_router
    from ops.us_market_digest import GLOBAL_INDUSTRY_PROXY_MAP, materialize_us_market_phase

    trade_date = "20261016"
    session_date = "20261015"
    captured_at = "2026-10-16T12:30:00+08:00"

    def fetch_proxy_quotes(_url, _timeout):
        symbols = list(dict.fromkeys(
            symbol
            for mapping in GLOBAL_INDUSTRY_PROXY_MAP
            for symbol in mapping["proxy_symbols"]
        ))
        records = []
        for symbol in symbols:
            fields = [""] * 31
            fields[1:5] = [symbol, symbol, "110", "100"]
            fields[30] = f"{session_date}160000"
            records.append(f'v_us{symbol}="' + "~".join(fields) + '";')
        return "".join(records)

    data_root = tmp_path / "market-data"
    materialize_us_market_phase(
        data_root=data_root,
        trade_date=trade_date,
        capture_phase="POST_CLOSE",
        us_session_date=session_date,
        fetched_at=captured_at,
        now=captured_at,
        allow_late_post_close=True,
        fetch_rss=lambda *_args: b"<rss><channel></channel></rss>",
        fetch_quotes=fetch_proxy_quotes,
        fetch_futu_boards=lambda date: build_futu_board_snapshot(
            date, quote_context=_FakeFutuContext()
        ),
    )

    observed = datetime.fromisoformat("2026-10-16T13:00:00+08:00")
    monkeypatch.setattr(
        "infrastructure.research_lane_source.shanghai_now", lambda: observed
    )
    app = FastAPI()
    app.include_router(create_research_lane_router(
        tmp_path / "research-data", us_market_data_root=data_root
    ))

    response = TestClient(app).get(
        "/api/v3/research/us-market", params={"research_date": trade_date}
    )

    assert response.status_code == 200
    result = response.json()
    cloud = next(row for row in result["rows"] if row["label"] == "云计算")
    assert result["display_status"] == "PARTIAL"
    assert result["freshness"]["state"] == "RECENT_BOUND_CAPTURE"
    assert result["freshness"]["cannot_confirm"] == []
    assert result["futu_board_snapshot"]["status"] == "PARTIAL"
    assert result["available_board_count"] == 13
    assert result["requested_board_count"] == 24
    assert result["native_board_snapshot"]["available_board_count"] == len(FUTU_US_BOARD_REGISTRY)
    assert result["native_display_status"] == "READY"
    assert cloud["change_pct"] == 0.70035
    assert cloud["official_board"]["rise_count"] == 15
    assert cloud["proxy_reference"]["change_pct"] == 10.0
    assert result["quotes"] == []
    assert len(result["proxy_quotes"]) == result["proxy_available_symbol_count"]

    from apps.api.v35_api.research_lane_router import _with_us_market_freshness

    wrong_board_date = deepcopy(result)
    wrong_cloud = next(row for row in wrong_board_date["rows"] if row["label"] == "云计算")
    wrong_cloud["official_board"]["session_date"] = "20261014"
    wrong_date_result = _with_us_market_freshness(wrong_board_date, observed=observed)
    assert wrong_date_result["display_status"] == "CANNOT_CONFIRM"
    assert wrong_date_result["freshness"]["cannot_confirm"] == ["FUTU_BOARD_READY_ROW_IDENTITY_INVALID"]

    pre_close_board = deepcopy(result)
    pre_close_cloud = next(row for row in pre_close_board["rows"] if row["label"] == "云计算")
    pre_close_cloud["official_board"]["update_time"] = "2026-10-15 15:59:59"
    pre_close_result = _with_us_market_freshness(pre_close_board, observed=observed)
    assert pre_close_result["display_status"] == "CANNOT_CONFIRM"
    assert pre_close_result["freshness"]["cannot_confirm"] == ["FUTU_BOARD_UPDATE_BEFORE_SESSION_CLOSE"]

    wrong_native_date = deepcopy(result)
    wrong_native_date["native_board_snapshot"]["rows"][0]["session_date"] = "20261014"
    wrong_native_result = _with_us_market_freshness(wrong_native_date, observed=observed)
    assert wrong_native_result["native_display_status"] == "CANNOT_CONFIRM"
    assert wrong_native_result["native_freshness"]["cannot_confirm"] == ["FUTU_NATIVE_BOARD_SNAPSHOT_INVALID"]

