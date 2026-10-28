import os
import struct
import unittest
from unittest.mock import patch

from ops import a_share_daily_sync as sync
from ops._a_share_daily_sync_parts.tdx_mac_adapter import MacDailyBarsCmd, MacDailyHqAPI


def command():
    cmd = MacDailyBarsCmd(None)
    cmd.setParams(9, 1, "600176", 0, 20)
    return cmd


def payload(records, *, market=1, code=b"600176", period=4, flag=1, start=0, count=None):
    header = struct.pack("<H22sHBHI", market, code, period, flag,
                         len(records) if count is None else count, start)
    return header + b"".join(struct.pack("<II7f", *row) for row in records)


def bar(date, close=10.0):
    return (date, 0, 10.0, max(11.0, close), min(9.0, close), close, 7000.0, 700.0, 1000.0)


class MacDailyProtocolTests(unittest.TestCase):
    def test_request_is_unadjusted_daily_mac_for_exact_identity(self):
        raw = command().send_pkg
        self.assertEqual(struct.unpack_from("<BIBHH", raw), (0x1C, 0, 1, 48, 48))
        self.assertEqual(struct.unpack_from("<H", raw, 10)[0], 0x122E)
        self.assertEqual(struct.unpack_from("<H22sHHIHH", raw, 12),
                         (1, b"600176" + b"\0" * 16, 4, 1, 0, 20, 0))

    def test_daily_units_and_original_day_codec(self):
        rows = command().parseResponse(payload([bar(20261022), bar(20261023, 10.5)]) + b"metadata")
        self.assertEqual([sync.day_int(row) for row in rows], [20261022, 20261023])
        self.assertEqual(rows[1]["vol"], 7.0)  # shares / 100 -> existing producer lots
        self.assertEqual(rows[1]["amount"], 7000.0)
        packed = sync.DAY_STRUCT.unpack(sync.pack_hq_bar(rows[1]))
        self.assertEqual(packed[4], 1050)
        self.assertEqual(packed[5:7], (7000.0, 700))

    def test_short_old_response_and_truncated_record_are_rejected(self):
        for raw in (b"\x20\x03", payload([bar(20261023)], count=2),
                    payload([bar(20261023)])[:-1], payload([], count=21)):
            with self.subTest(length=len(raw)), self.assertRaises(struct.error):
                command().parseResponse(raw)

    def test_response_identity_is_bound_to_request(self):
        for delta in ({"market": 0}, {"code": b"000001"}, {"period": 9},
                      {"flag": 0}, {"start": 1}):
            with self.subTest(delta=delta), self.assertRaises(struct.error):
                command().parseResponse(payload([bar(20261023)], **delta))

    def test_invalid_date_and_nonfinite_record_are_not_silently_skipped(self):
        for row in (bar(20260230), bar(19890101), bar(20261023, float("nan"))):
            with self.subTest(row=row), self.assertRaises(struct.error):
                command().parseResponse(payload([row]))

    def test_empty_identity_bound_response_stays_empty(self):
        self.assertEqual(command().parseResponse(payload([])), [])

    def test_existing_content_guards_remain_in_force(self):
        target = sync.DailyTarget("600176", 1, sync.Path("unused.day"))
        cases = [([bar(20261022)], 10.0, sync.TARGET_DATE_MISSING),
                 ([bar(20261023), bar(20261023)], 10.0, sync.DUPLICATE_DATE),
                 ([bar(20261023), bar(20261022)], 10.0, sync.NON_MONOTONIC_DATE),
                 ([bar(20261023), bar(20261024)], 10.0, sync.OUT_OF_SCOPE_AFTER_TARGET_DATE),
                 ([bar(20261023, 20.0)], 10.0, sync.CROSS_DAY_CLOSE_RATIO)]
        for records, previous, expected in cases:
            api = type("API", (), {"get_security_bars": lambda self, *args: command().parseResponse(payload(records))})()
            with self.subTest(expected=expected):
                rows, reason = sync._fetch_valid_target_bars(api, target, 20261023, previous, 20, 20261022)
                self.assertEqual((rows, reason), ([], expected))

    def test_factory_requires_explicit_protocol_and_keeps_sdk_errors(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIs(type(sync._runtime_api_factory("unused", 7709)), sync.TdxHq_API)
        with patch.dict(os.environ, {"V35_A_SYNC_TDX_PROTOCOL": "mac"}):
            api = sync._runtime_api_factory("unused", 7709)
            self.assertIs(type(api), MacDailyHqAPI)
            self.assertFalse(api.auto_retry)
            self.assertTrue(api.raise_exception)
            with patch.object(MacDailyBarsCmd, "call_api", side_effect=struct.error("short body")):
                with self.assertRaises(Exception) as error:
                    api.get_security_bars(9, 1, "600176", 0, 20)
            self.assertEqual(sync._protocol_response_details(error.exception)["original_exception_module"], "struct")
        with patch.dict(os.environ, {"V35_A_SYNC_TDX_PROTOCOL": "unknown"}), self.assertRaises(ValueError):
            sync._runtime_api_factory("unused", 7709)


if __name__ == "__main__":
    unittest.main()
