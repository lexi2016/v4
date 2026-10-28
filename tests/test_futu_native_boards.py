from __future__ import annotations

from copy import deepcopy

import pytest

from contracts.futu_us_boards import (
    FUTU_US_BOARD_REGISTRY,
    FUTU_US_BOARD_REGISTRY_SHA256,
    FUTU_US_BOARD_REGISTRY_VERSION,
    validate_futu_us_board_snapshot,
)
from ops._us_market_digest_parts.futu_boards import (
    FUTU_BOARD_MAP,
    _canonical_sha256,
    _empty_row,
    build_futu_board_snapshot,
    validate_futu_board_snapshot,
)


ADDED_NATIVE_BOARDS = (
    ("CONCEPT", "US.LIST2136", "人工智能"),
    ("CONCEPT", "US.LIST2548", "AI芯片"),
    ("CONCEPT", "US.LIST23979", "光通信"),
    ("CONCEPT", "US.LIST2556", "太空概念"),
    ("INDUSTRY", "US.LIST2472", "受监管电力"),
    ("CONCEPT", "US.LIST2572", "可再生能源"),
    ("INDUSTRY", "US.LIST2224", "综合油气"),
    ("INDUSTRY", "US.LIST2510", "铜"),
    ("INDUSTRY", "US.LIST2481", "多元化银行"),
    ("INDUSTRY", "US.LIST2069", "生物技术"),
    ("INDUSTRY", "US.LIST2003", "家庭和个人用品"),
)


class _Frame:
    def __init__(self, records):
        self.records = records

    def to_dict(self, _orient="records"):
        return self.records


class _NativeFutuContext:
    def __init__(
        self,
        *,
        missing_snapshot_code: str | None = None,
        duplicate_snapshot_code: str | None = None,
        failed_membership_code: str | None = None,
        missing_membership_payload_code: str | None = None,
        empty_membership_code: str | None = None,
        empty_membership_list_code: str | None = None,
    ):
        self.missing_snapshot_code = missing_snapshot_code
        self.duplicate_snapshot_code = duplicate_snapshot_code
        self.failed_membership_code = failed_membership_code
        self.missing_membership_payload_code = missing_membership_payload_code
        self.empty_membership_code = empty_membership_code
        self.empty_membership_list_code = empty_membership_list_code
        self.snapshot_codes: list[str] = []
        self.membership_codes: list[str] = []

    def get_plate_list(self, _market, plate_type):
        return 0, _Frame([
            {"code": item["board_code"], "plate_name": item["board_name"]}
            for item in FUTU_US_BOARD_REGISTRY
            if item["plate_type"] == str(plate_type)
        ])

    def get_market_snapshot(self, codes):
        self.snapshot_codes.extend(codes)
        records = [
            {
                "code": code,
                "last_price": 101.0,
                "prev_close_price": 100.0,
                "update_time": "2026-10-15 16:00:00",
                "plate_valid": True,
                "plate_raise_count": 10,
                "plate_fall_count": 8,
                "plate_equal_count": 1,
            }
            for code in codes
            if code != self.missing_snapshot_code
        ]
        if self.duplicate_snapshot_code is not None:
            duplicate = next(
                record for record in records
                if record["code"] == self.duplicate_snapshot_code
            )
            records.append(dict(duplicate))
        return 0, _Frame(records)

    def get_plate_stock(self, code):
        self.membership_codes.append(code)
        if code == self.failed_membership_code:
            return -1, _Frame([])
        if code == self.missing_membership_payload_code:
            return 0, None
        if code == self.empty_membership_code:
            return 0, _Frame([])
        if code == self.empty_membership_list_code:
            return 0, []
        return 0, _Frame([{"code": "US.AAPL"}, {"code": "US.MSFT"}])


@pytest.fixture(autouse=True)
def _disable_rate_limit_sleep(monkeypatch):
    now = {"seconds": 0.0}
    monkeypatch.setattr("ops._us_market_digest_parts.futu_boards._monotonic", lambda: now["seconds"])
    monkeypatch.setattr(
        "ops._us_market_digest_parts.futu_boards._sleep",
        lambda seconds: now.__setitem__("seconds", now["seconds"] + seconds),
    )


def test_registry_is_frozen_exact_and_keeps_existing_mapped_board_identity():
    assert len(FUTU_US_BOARD_REGISTRY) == 24
    assert len({item["board_code"] for item in FUTU_US_BOARD_REGISTRY}) == len(FUTU_US_BOARD_REGISTRY)
    assert len({(item["plate_type"], item["board_name"]) for item in FUTU_US_BOARD_REGISTRY}) == len(FUTU_US_BOARD_REGISTRY)
    expected_sha = _canonical_sha256({
        "registry_version": FUTU_US_BOARD_REGISTRY_VERSION,
        "boards": [dict(row) for row in FUTU_US_BOARD_REGISTRY],
    })
    assert FUTU_US_BOARD_REGISTRY_SHA256 == expected_sha

    added = tuple(
        (item["plate_type"], item["board_code"], item["board_name"])
        for item in FUTU_US_BOARD_REGISTRY
        if item["board_code"] in {code for _kind, code, _name in ADDED_NATIVE_BOARDS}
    )
    assert added == ADDED_NATIVE_BOARDS

    for mapping in (item for item in FUTU_BOARD_MAP if item["plate_name"] is not None):
        matches = [
            item for item in FUTU_US_BOARD_REGISTRY
            if item["plate_type"] == mapping["plate_type"] and item["board_name"] == mapping["plate_name"]
        ]
        assert len(matches) == 1
    old_theme_aliases = {"AI算力", "CPO", "商业航天", "卫星", "电网", "新能源", "石油", "铜/有色", "银行金融", "生物医药", "消费"}
    assert old_theme_aliases.isdisjoint({item["board_name"] for item in FUTU_US_BOARD_REGISTRY})


def test_native_capture_is_deduplicated_and_quote_and_membership_failures_are_separate():
    missing_snapshot_code = "US.LIST2510"
    failed_membership_code = "US.LIST2136"
    context = _NativeFutuContext(
        missing_snapshot_code=missing_snapshot_code,
        failed_membership_code=failed_membership_code,
    )

    captured = build_futu_board_snapshot("20261015", quote_context=context)
    native = validate_futu_us_board_snapshot(
        captured["native_board_snapshot"], expected_session_date="20261015"
    )

    assert len(captured["rows"]) == len(FUTU_BOARD_MAP) == 24
    assert sum(row["status"] == "READY" for row in captured["rows"]) == 13
    assert len(context.snapshot_codes) == len(FUTU_US_BOARD_REGISTRY)
    assert len(context.snapshot_codes) == len(set(context.snapshot_codes))
    assert context.snapshot_codes == [item["board_code"] for item in FUTU_US_BOARD_REGISTRY]
    assert len(context.membership_codes) == len(FUTU_US_BOARD_REGISTRY)
    assert len(set(context.membership_codes)) == len(FUTU_US_BOARD_REGISTRY)

    quote_gap = next(row for row in native["rows"] if row["board_code"] == missing_snapshot_code)
    assert quote_gap["status"] == "CANNOT_CONFIRM"
    assert quote_gap["cannot_confirm"] == ["FUTU_BOARD_SNAPSHOT_NOT_RETURNED"]
    assert quote_gap["membership_status"] == "READY"
    assert quote_gap["change_pct"] is None

    membership_gap = next(row for row in native["rows"] if row["board_code"] == failed_membership_code)
    assert membership_gap["status"] == "READY"
    assert membership_gap["change_pct"] == 1.0
    assert membership_gap["membership_status"] == "CANNOT_CONFIRM"
    assert membership_gap["membership_cannot_confirm"] == ["FUTU_BOARD_MEMBERSHIP_FAILED:-1"]
    assert native["status"] == "PARTIAL"
    assert native["available_board_count"] == len(FUTU_US_BOARD_REGISTRY) - 1
    assert all("proxy_reference" not in row and "relation_constituents" not in row for row in native["rows"])


def test_missing_membership_payload_is_unconfirmed_but_valid_empty_payload_is_ready():
    missing_code = "US.LIST2136"
    empty_code = "US.LIST2548"
    empty_list_code = "US.LIST23979"
    captured = build_futu_board_snapshot(
        "20261015",
        quote_context=_NativeFutuContext(
            missing_membership_payload_code=missing_code,
            empty_membership_code=empty_code,
            empty_membership_list_code=empty_list_code,
        ),
    )
    native = captured["native_board_snapshot"]
    missing = next(row for row in native["rows"] if row["board_code"] == missing_code)
    empty = next(row for row in native["rows"] if row["board_code"] == empty_code)
    empty_list = next(row for row in native["rows"] if row["board_code"] == empty_list_code)

    assert missing["membership_status"] == "CANNOT_CONFIRM"
    assert missing["membership_cannot_confirm"] == [
        "FUTU_BOARD_MEMBERSHIP_FAILED:MALFORMED_PAYLOAD"
    ]
    assert missing["member_count"] is None
    assert empty["membership_status"] == "READY"
    assert empty["membership_cannot_confirm"] == []
    assert empty["member_count"] == 0
    assert len(empty["membership_sha256"]) == 64
    assert empty_list["membership_status"] == "READY"
    assert empty_list["member_count"] == 0
    assert len(empty_list["membership_sha256"]) == 64


def test_native_quote_hash_preserves_duplicate_provider_rows():
    code = FUTU_US_BOARD_REGISTRY[0]["board_code"]
    clean = build_futu_board_snapshot("20261015", quote_context=_NativeFutuContext())
    duplicated = build_futu_board_snapshot(
        "20261015",
        quote_context=_NativeFutuContext(duplicate_snapshot_code=code),
    )

    clean_native = clean["native_board_snapshot"]
    duplicate_native = duplicated["native_board_snapshot"]
    clean_row = next(row for row in clean_native["rows"] if row["board_code"] == code)
    duplicate_row = next(row for row in duplicate_native["rows"] if row["board_code"] == code)

    assert clean_row["status"] == "READY"
    assert duplicate_row["status"] == "CANNOT_CONFIRM"
    assert clean_row["source_response_sha256"] != duplicate_row["source_response_sha256"]
    assert clean_native["source_response_sha256"] != duplicate_native["source_response_sha256"]
    assert duplicate_native["rows"][0]["cannot_confirm"] == [
        "FUTU_BOARD_SNAPSHOT_AMBIGUOUS"
    ]


def test_native_validation_rejects_registry_drift_date_or_wrong_arithmetic():
    captured = build_futu_board_snapshot("20261015", quote_context=_NativeFutuContext())
    native = captured["native_board_snapshot"]

    wrong_identity = deepcopy(native)
    wrong_identity["rows"][0]["board_name"] = "半导体设备与材料"
    with pytest.raises(ValueError, match="identity"):
        validate_futu_us_board_snapshot(wrong_identity, expected_session_date="20261015")

    with pytest.raises(ValueError, match="session date"):
        validate_futu_us_board_snapshot(native, expected_session_date="20261016")

    wrong_math = deepcopy(native)
    wrong_math["rows"][0]["change_pct"] = 2.0
    with pytest.raises(ValueError, match="arithmetic|READY"):
        validate_futu_us_board_snapshot(wrong_math, expected_session_date="20261015")


def test_legacy_v1_rows_keep_their_24_theme_contract_and_12_ready_placeholder_read():
    captured = build_futu_board_snapshot("20261015", quote_context=_NativeFutuContext())
    legacy = deepcopy(captured)
    legacy.pop("native_board_snapshot")
    military_index = next(index for index, row in enumerate(legacy["rows"]) if row["label"] == "军工")
    legacy["rows"][military_index] = _empty_row(
        {"label": "军工", "plate_type": None, "plate_name": None},
        "FUTU_BOARD_MATCH_UNCONFIRMED",
    )

    checked = validate_futu_board_snapshot(legacy, expected_session_date="20261015")
    assert len(checked["rows"]) == 24
    assert sum(row["status"] == "READY" for row in checked["rows"]) == 12
    assert checked["rows"][military_index]["board_name"] is None
    assert checked["rows"][military_index]["status"] == "CANNOT_CONFIRM"
