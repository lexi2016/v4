"""Daily-only TDX MAC command on the existing pytdx connection.

Protocol reference: clong365/easy_tdx (MIT), revision
4820b4a0496899ece0b8ca4d7f4d66a5159da7f8, SymbolBarCmd/build_mac_request.
Unlike its general-purpose decoder, this adapter rejects a truncated record
set or a mismatched identity instead of clipping/skipping provider records.
The producer's date, OHLC, field-signature and continuity guards still apply.

Copyright (c) 2025-present easy-tdx contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
from __future__ import annotations

import math
import struct
from datetime import datetime

from pytdx.base_socket_client import update_last_ack_time
from pytdx.hq import TdxHq_API
from pytdx.parser.base import BaseParser


class MacDailyBarsCmd(BaseParser):
    """Unadjusted daily bars only; volume is mapped from shares to lots."""

    def setParams(self, category, market, code, start, count):
        if category != 9 or market not in (0, 1, 2):
            raise ValueError("TDX_MAC_DAILY_ONLY")
        if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
            raise ValueError("TDX_MAC_SYMBOL_INVALID")
        if not isinstance(start, int) or not isinstance(count, int) or not 0 <= start <= 0xFFFFFFFF or not 1 <= count <= 700:
            raise ValueError("TDX_MAC_RANGE_INVALID")
        self.market, self.code, self.start, self.count = market, code, start, count
        # Period.DAILY=4, Adjust.NONE=0. No authentication or account commands.
        body = struct.pack("<H22sHHIHHbbbbH4s", market, code.encode("ascii"), 4, 1,
                           start, count, 0, 1, 1, 0, 1, 0, b"")
        inner = struct.pack("<H", 0x122E) + body
        self.send_pkg = struct.pack("<BIBHH", 0x1C, 0, 1, len(inner), len(inner)) + inner

    def parseResponse(self, body_buf):
        body = bytes(body_buf)
        if len(body) < 33:
            raise struct.error("TDX_MAC_DAILY_HEADER_TRUNCATED")
        market, code, period, flag, count, start = struct.unpack_from("<H22sHBHI", body)
        if (market, code.rstrip(b"\0"), period, flag, start) != (
            self.market, self.code.encode("ascii"), 4, 1, self.start
        ):
            raise struct.error("TDX_MAC_DAILY_IDENTITY_MISMATCH")
        if count > self.count or len(body) < 33 + count * 36:
            raise struct.error("TDX_MAC_DAILY_RECORDS_TRUNCATED_OR_EXCESS")
        # Real replies may append company/quote metadata after the declared
        # records. It is not interpreted as another bar or used for prices.
        rows = []
        for index in range(count):
            ymd, time_num, open_, high, low, close, amount, shares, _float_shares = struct.unpack_from(
                "<II7f", body, 33 + index * 36
            )
            if not 19900101 <= ymd <= 20991231 or time_num != 0:
                raise struct.error("TDX_MAC_DAILY_DATE_INVALID")
            year, month, day = ymd // 10000, ymd // 100 % 100, ymd % 100
            try:
                dt = datetime(year, month, day)
            except ValueError as error:
                raise struct.error("TDX_MAC_DAILY_DATE_INVALID") from error
            if not all(math.isfinite(value) for value in (open_, high, low, close, amount, shares)):
                raise struct.error("TDX_MAC_DAILY_NONFINITE_FIELD")
            rows.append({"year": year, "month": month, "day": day, "hour": 0, "minute": 0,
                         "datetime": dt.strftime("%Y-%m-%d %H:%M"), "open": open_, "high": high,
                         "low": low, "close": close, "amount": amount, "vol": shares / 100.0})
        return rows


class MacDailyHqAPI(TdxHq_API):
    """Keep the original transport, setup, timeouts and SDK error envelope."""

    @update_last_ack_time
    def get_security_bars(self, category, market, code, start, count):
        cmd = MacDailyBarsCmd(self.client, lock=self.lock)
        cmd.setParams(category, market, code, start, count)
        return cmd.call_api()
