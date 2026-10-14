from __future__ import annotations

import hashlib
import unittest

import batch_runner as runner
import simple_fixed_facts as fixed_facts


def body_with_units(text: str) -> tuple[str, dict]:
    body_sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, runner.build_source_unit_map(text, body_sha)


class SimpleFixedFactsTests(unittest.TestCase):
    def test_daily_trade_columns_and_single_current_change_keep_their_distinct_semantics(self) -> None:
        body, unit_map = body_with_units(
            """公司名稱：示例發行人有限公司
證券代號：01234
A. 已發行股份或庫存股份變動
已發行股份（不包括庫存股份）數目 庫存股份數目 已發行股份總數
於下列日期開始時的結存 2026年10月12日 1,000,000 2,000 1,002,000
1). 購回股份（股份被持作庫存股份） -100 0.01 % 100 HKD 1.25
變動日期 2026年10月13日
3. 已發行股份數目變動的百分比參照期初結存計算。

交易日 購回股份數目 購回方式 每股最高購回價 每股最低購回價 付出的價格總額
1). 2026年10月13日 100 於本交易所進行 HKD 1.30 HKD 1.20 HKD 125
"""
        )
        ledger = fixed_facts.extract_fixed_facts(body, unit_map)
        transaction = next(item for item in ledger["records"] if item["kind"] == "share_transaction_row")
        daily = ledger["daily_trade_rows"][0]["value"]
        ratio = next(item for item in ledger["calculations"] if item["kind"] == "current_change_percentage")

        self.assertEqual(transaction["value"]["status"], "TREASURY_HOLDING")
        self.assertEqual(transaction["value"]["share_quantity_token"], "-100")
        self.assertEqual(transaction["value"]["reported_percentage_token"], "0.01")
        self.assertEqual(transaction["value"]["reported_price_token"], "1.25")
        self.assertEqual(transaction["value"]["event_date"], "2026年10月13日")
        self.assertEqual(len(transaction["source_refs"]), 2)
        self.assertEqual(ratio["status"], "VERIFIED_AT_REPORTED_PRECISION")
        self.assertEqual(ratio["opening_denominator"], "1000000")
        self.assertEqual(ratio["calculated_percentage_at_reported_precision"], "0.01")
        self.assertEqual(
            (daily["share_quantity"], daily["maximum_or_single_price"], daily["minimum_price"], daily["total_amount"]),
            ("100", "1.30", "1.20", "125"),
        )
        self.assertEqual(ledger["body_sha256"], unit_map["body_sha256"])
        unit_ids = {unit["source_unit_id"] for unit in unit_map["units"]}
        for item in ledger["reader_facts"] + ledger["reader_changes"]:
            self.assertIn(item["source_unit_id"], unit_ids)

    def test_authorization_ratio_uses_only_resolution_date_issued_share_note(self) -> None:
        body, unit_map = body_with_units(
            """購回授權的決議獲通過的日期：2026年5月11日
發行人可根據購回授權購回股份的總數：1000000
根據購回授權購回股份的數目：(a) 250
佔購回授權決議獲通過當日的已發行股份數目的百分比：0.02 %
(a) x 100 / 購回授權決議獲通過當日的已發行股份數目

備註：截至購回授權決議獲通過的日期，發行人已發行股份總數為1,250,000股。
"""
        )
        ledger = fixed_facts.extract_fixed_facts(body, unit_map)
        calc = next(item for item in ledger["calculations"] if item["kind"] == "explicit_cumulative_authorization_ratio")
        self.assertEqual(calc["status"], "VERIFIED_AT_REPORTED_PRECISION")
        self.assertEqual(calc["numerator"], "250")
        self.assertEqual(calc["denominator"], "1250000")
        self.assertEqual(calc["authorization_resolution_date"], "2026年5月11日")
        self.assertEqual(calc["calculated_percentage_at_reported_precision"], "0.02")

    def test_authorization_cap_is_never_substituted_for_missing_denominator(self) -> None:
        body, unit_map = body_with_units(
            """購回授權的決議獲通過的日期：2026年5月11日
發行人可根據購回授權購回股份的總數：108000000
根據購回授權購回股份的數目：(a) 250000
佔購回授權決議獲通過當日的已發行股份數目的百分比：0.02 %
(a) x 100 / 購回授權決議獲通過當日的已發行股份數目
"""
        )
        ledger = fixed_facts.extract_fixed_facts(body, unit_map)
        calc = next(item for item in ledger["calculations"] if item["kind"] == "explicit_cumulative_authorization_ratio")
        self.assertEqual(calc["status"], "CANNOT_CONFIRM")
        self.assertIn("resolution_date_issued_share_denominator", calc["missing_or_unbound_inputs"])
        self.assertEqual(next(item for item in ledger["records"] if item["kind"] == "authorization_share_cap")["value"], "108000000")
        self.assertEqual(
            next(item for item in ledger["records"] if item["kind"] == "authorization_share_cap")["scope"],
            "authorization_cap_not_share_denominator",
        )
        self.assertNotIn("denominator", calc)

    def test_reference_only_text_leaves_underlying_event_status_unconfirmed(self) -> None:
        body, unit_map = body_with_units("茲載列另一份公告，僅供參閱。\n")
        ledger = fixed_facts.extract_fixed_facts(body, unit_map)
        record = next(item for item in ledger["records"] if item["kind"] == "reference_only_notice")
        self.assertEqual(record["value"]["underlying_transaction_status"], "CANNOT_CONFIRM")
        self.assertIn(
            {"field": "underlying_event_from_reference_only_notice", "status": "CANNOT_CONFIRM", "reason": "REFERENCE_ONLY_TEXT_DOES_NOT_ESTABLISH_EVENT_COMPLETION"},
            ledger["unknowns"],
        )

    def test_dated_but_unvalued_pending_row_never_becomes_zero(self) -> None:
        body, unit_map = body_with_units("B. 擬註銷但尚未註銷\n變動日期 2026年10月12日\n")
        ledger = fixed_facts.extract_fixed_facts(body, unit_map)
        record = next(item for item in ledger["records"] if item["kind"] == "share_transaction_date_without_values")
        self.assertEqual(record["value"]["transaction_status"], "CANNOT_CONFIRM")
        self.assertIsNone(record["value"]["share_quantity"])
        self.assertIsNone(record["value"]["percentage"])
        self.assertIsNone(record["value"]["price"])
        self.assertEqual(ledger["unknowns"][0]["status"], "CANNOT_CONFIRM")
        self.assertFalse(any(item["kind"] == "share_transaction_row" for item in ledger["records"]))

    def test_source_unit_map_must_cover_the_exact_hashed_body(self) -> None:
        body, unit_map = body_with_units("A full article body.\n")
        unit_map["body_sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "FIXED_FACT_SOURCE_UNIT_MAP_IDENTITY_INVALID"):
            fixed_facts.extract_fixed_facts(body, unit_map)


if __name__ == "__main__":
    unittest.main()
