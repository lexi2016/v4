"""Pure isolated regressions; real material is read locally, never embedded.

Run with V4_FIXED_FACT_SAVED_INPUT pointing to the already-saved queue input
to include the required real-body regression. No pipeline or model is imported.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "research/announcement-fact-completeness-20261025/simple_fixed_facts.py"
SPEC = importlib.util.spec_from_file_location("isolated_fixed_facts", SOURCE)
EXTRACTOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(EXTRACTOR)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def unit_map(texts):
    """Reconstruct offsets from given boundaries, never repartition a body."""
    units = []
    cursor = 0
    for uid, text in texts:
        units.append({"source_unit_id": uid, "text": text, "start_cp": cursor,
                      "end_cp": cursor + len(text), "unit_sha256": digest(text.encode())})
        cursor += len(text)
    material = {
        "protocol": "source_units_paragraph_table_v1",
        "boundary_policy": "blank-paragraph-boundaries-with-adjacent-table-blocks-kept-whole-v1",
        "body_sha256": digest("".join(text for _, text in texts).encode()),
        "units": [{key: unit[key] for key in ("source_unit_id", "start_cp", "end_cp", "unit_sha256")}
                  for unit in units],
    }
    return {**material, "units": units, "source_unit_map_sha256": digest(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())}


def extract(text, parts=None):
    mapping = unit_map(parts or [("U000001", text)])
    return EXTRACTOR.extract_fixed_facts(text, mapping), mapping


class FixedFactCompleteness(unittest.TestCase):
    def assert_claims_bound(self, ledger, mapping):
        units = {u["source_unit_id"]: u for u in mapping["units"]}
        for item in ledger["reader_facts"] + ledger["reader_changes"]:
            self.assertEqual(set(item), {"claim", "source_unit_id"})
            self.assertIn(item["claim"], units[item["source_unit_id"]]["text"])
        for record in ledger["records"]:
            for ref in record["source_refs"]:
                unit = units[ref["source_unit_id"]]
                self.assertEqual(ref["source_unit_sha256"], unit["unit_sha256"])
                self.assertEqual((ref["unit_start_cp"], ref["unit_end_cp"]),
                                 (unit["start_cp"], unit["end_cp"]))

    def test_hard_wrap_keeps_complete_proposition_and_exact_span(self):
        text = "2026年10月20日，甲公司面向\n专业投资者发行债券。\n"
        ledger, mapping = extract(text)
        self.assertEqual(ledger["reader_facts"], [{"claim": text.strip(), "source_unit_id": "U000001"}])
        self.assert_claims_bound(ledger, mapping)

    def test_complete_unwrapped_sentence_unchanged(self):
        text = "2026年10月20日，甲公司完成发行。"
        ledger, _ = extract(text)
        self.assertEqual([f["claim"] for f in ledger["reader_facts"]], [text])

    def test_code_label_with_wrapped_narrative_requires_complete_sentence(self):
        for pure in ["股份代號：1776", "（股份代號：1776）", "证券代码：123456，证券简称：测试债",
                     "发行人名称：甲股份有限公司", "发行人名称：Example Co., Ltd."]:
            with self.subTest(pure=pure):
                pure_ledger, pure_mapping = extract(pure)
                self.assertEqual(pure_ledger["reader_facts"], [{"claim": pure, "source_unit_id": "U000001"}])
                self.assert_claims_bound(pure_ledger, pure_mapping)
        text = "股份代號：1776，发行人将于2026年10月21日面向\n专业机构投资者网下发行。"
        ledger, mapping = extract(text)
        self.assertEqual(ledger["reader_facts"], [{"claim": text, "source_unit_id": "U000001"}])
        self.assert_claims_bound(ledger, mapping)

    def test_label_with_truncated_narrative_rejected(self):
        # These share the same structured fast path. Neither an explicit code,
        # company label nor numeric field can certify its narrative suffix.
        for prefix in ["股份代號：1776", "发行人名称：甲股份有限公司", "期初结存 1,000",
                       "回购授权决议获通过的日期：2026年10月21日"]:
            with self.subTest(prefix=prefix):
                text = prefix + "，发行人将于2026年10月21日面向"
                with self.assertRaisesRegex(ValueError, "FIXED_FACT_READER_CLAIM_INCOMPLETE"):
                    extract(text)

    def test_adjacent_sentences_are_separate_and_only_overlap_is_selected(self):
        text = "2026年10月20日，甲公司完成发行。乙公司公布业绩。\n"
        ledger, _ = extract(text)
        claims = [f["claim"] for f in ledger["reader_facts"]]
        self.assertEqual(claims, ["2026年10月20日，甲公司完成发行。", "乙公司公布业绩。"])
        self.assertNotIn(text.strip(), claims)
        other, _ = extract("2026年10月20日，甲公司完成发行。\n乙公司公布业绩。\n")
        self.assertEqual(len(other["reader_facts"]), 1)

    def test_unfinished_source_rejected_not_silently_dropped(self):
        with self.assertRaisesRegex(ValueError, "FIXED_FACT_READER_CLAIM_INCOMPLETE"):
            extract("2026年10月20日，甲公司面向")

    def test_complete_clause_cannot_hide_truncated_remainder(self):
        with self.assertRaisesRegex(ValueError, "FIXED_FACT_READER_CLAIM_INCOMPLETE"):
            extract("2026年10月20日，甲公司完成发行。该公司面向")

    def test_no_cross_unit_stitching(self):
        left = "2026年10月20日，甲公司面向\n"
        right = "专业投资者发行债券。"
        with self.assertRaisesRegex(ValueError, "FIXED_FACT_READER_CLAIM_INCOMPLETE"):
            extract(left + right, [("U000001", left), ("U000002", right)])

    def test_heading_and_table_boundaries_rejected(self):
        for boundary in ["二、其他事项", "风险提示", "项目\t金额", "项目 | 金额", "项目  金额"]:
            with self.subTest(boundary=boundary):
                with self.assertRaisesRegex(ValueError, "FIXED_FACT_READER_CLAIM_AMBIGUOUS_BOUNDARY"):
                    extract("2026年10月20日，甲公司面向\n" + boundary + "\n乙公司完成发行。")

    def test_new_subject_boundary_rejected(self):
        with self.assertRaisesRegex(ValueError, "FIXED_FACT_READER_CLAIM_AMBIGUOUS_BOUNDARY"):
            extract("2026年10月20日，甲公司面向\n另一家公司公布业绩。")

    def test_dates_entities_codes_and_structured_rows_preserved(self):
        text = "甲股份有限公司\n股份代號：1234\n2026年10月20日\n期初结存 1,000\n"
        ledger, mapping = extract(text)
        self.assertEqual([f["claim"] for f in ledger["reader_facts"]],
                         ["甲股份有限公司", "股份代號：1234", "2026年10月20日"])
        self.assertEqual(ledger["reader_changes"], [{"claim": "期初结存 1,000", "source_unit_id": "U000001"}])
        self.assert_claims_bound(ledger, mapping)

    def test_preserve_numeric_qualifications_and_decimal_punctuation(self):
        text = "2026年10月20日，甲公司利率不超过\n1.60%（含），若未获批准则不发行。"
        ledger, mapping = extract(text)
        self.assertEqual(ledger["reader_facts"][0]["claim"], text)
        self.assert_claims_bound(ledger, mapping)

    def test_existing_daily_table_columns_remain_separate(self):
        text = ("交易日 購回股份數目 每股最高購回價 每股最低購回價 付出的價格總額\n"
                "2026年10月20日 100 1.20 1.00 120\n")
        ledger, mapping = extract(text)
        self.assertEqual(len(ledger["reader_facts"]), 1)
        self.assertEqual(ledger["reader_facts"][0]["claim"], text.splitlines()[1])
        self.assertEqual(len(ledger["daily_trade_rows"]), 1)
        values = ledger["daily_trade_rows"][0]["value"]
        self.assertEqual([values[k] for k in ("share_quantity", "maximum_or_single_price", "minimum_price", "total_amount")],
                         ["100", "1.20", "1.00", "120"])
        self.assert_claims_bound(ledger, mapping)

    def test_existing_explicit_date_field_without_sentence_punctuation(self):
        text = "呈交日期：2026年10月20日\n"
        ledger, mapping = extract(text)
        self.assertEqual(ledger["reader_facts"][0]["claim"], text.strip())
        self.assertEqual(ledger["records"][0]["label"], "filing_date")
        self.assertEqual(ledger["records"][0]["value"]["normalized_date"], "2026-10-20")
        self.assert_claims_bound(ledger, mapping)

    def test_reference_notice_stays_with_its_disclosure(self):
        text = "本公司在网站刊发债券公告。该公告仅供参阅。"
        ledger, mapping = extract(text)
        self.assertEqual(ledger["reader_facts"][0]["claim"], text)
        self.assert_claims_bound(ledger, mapping)

    def test_reject_tampered_unit_before_claim_processing(self):
        text = "2026年10月20日，甲公司完成发行。"
        mapping = unit_map([("U000001", text)])
        mapping["units"][0]["text"] += "改"
        with self.assertRaisesRegex(ValueError, "FIXED_FACT_SOURCE_UNIT_SHA_MISMATCH"):
            EXTRACTOR.extract_fixed_facts(text, mapping)

    def test_saved_single_canary(self):
        location = os.environ.get("V4_FIXED_FACT_SAVED_INPUT")
        if not location:
            self.skipTest("Required real regression needs the existing local saved input")
        path = Path(location)
        raw = path.read_bytes()
        self.assertEqual(digest(raw), "ca3e6377c1c5d7c00c2c385e2ebb1417495cdd6e775b820ab83fa084cb270d94")
        saved = json.loads(raw)
        content = next(m["content"] for m in saved["messages"] if m["role"] == "user")
        wire = json.loads(content.split("ARTICLE_DATA_BEGIN\n", 1)[1].rsplit("\nARTICLE_DATA_END", 1)[0])
        mapping = unit_map([(u["source_unit_id"].rsplit("::", 1)[-1], u["text"])
                            for u in wire["article"]["source_units"]])
        self.assertEqual(mapping["source_unit_map_sha256"], saved["source_unit_map_sha256"])
        self.assertEqual(len(mapping["units"]), 25)
        self.assertEqual("".join(u["text"] for u in mapping["units"]), saved["article_body"])
        self.assertEqual(len(saved["article_body"]), 2678)
        baseline = saved["fixed_fact_ledger"]
        ledger = EXTRACTOR.extract_fixed_facts(saved["article_body"], mapping, saved["article_metadata"])
        # Only reader claims and their derived ledger SHA may change.
        for key in baseline:
            if key not in {"reader_facts", "reader_changes", "ledger_sha256"}:
                self.assertEqual(ledger[key], baseline[key], key)
        self.assertEqual(ledger["reader_changes"], baseline["reader_changes"])
        self.assertEqual(ledger["reader_facts"][:5], baseline["reader_facts"][:5])
        self.assertEqual(ledger["reader_facts"][-1], baseline["reader_facts"][-1])
        self.assertEqual(len(ledger["reader_facts"]), len(baseline["reader_facts"]))
        claims = [f["claim"] for f in ledger["reader_facts"] if f["source_unit_id"] == "U000016"]
        self.assertEqual(len(claims), 3)
        for bad in baseline["reader_facts"][5:8]:
            # The third old line straddles two propositions. Both pieces must
            # survive inside separately complete source sentences.
            for piece in filter(None, bad["claim"].split("。")):
                self.assertTrue(any(piece in claim for claim in claims))
            self.assertNotIn(bad["claim"], claims)
        self.assertTrue(all(claim.endswith("。") for claim in claims))
        self.assert_claims_bound(ledger, mapping)
        # Existing saved quotes/locators remain exact against original units.
        validated = json.loads((path.parent / "attempt-0001.validated.json").read_bytes())
        quotes = []
        def visit(value):
            if isinstance(value, dict):
                if "quote" in value and "locator" in value:
                    quotes.append(value)
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
        visit(validated)
        self.assertEqual(len(quotes), 9)
        for citation in quotes:
            match = re.fullmatch(r"article_body\[codepoint:(\d+):(\d+)\]", citation["locator"])
            self.assertIsNotNone(match)
            left, right = map(int, match.groups())
            self.assertEqual(citation["quote"], saved["article_body"][left:right])
            self.assertTrue(any(left == u["start_cp"] and right == u["end_cp"]
                                for u in mapping["units"]))
        self.assertEqual(path.read_bytes(), raw)
        print(json.dumps({"saved_canary": "OFFLINE_CANDIDATE_ONLY",
                          "original_semantic_status": "FAIL_UNCHANGED",
                          "reader_fact_count_before": len(baseline["reader_facts"]),
                          "reader_fact_count_after": len(ledger["reader_facts"]),
                          "recovered_U000016_claims": claims,
                          "records_values_refs_unchanged": True,
                          "existing_quotes_and_locators": "9/9",
                          "candidate_ledger_sha256": ledger["ledger_sha256"]}, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main(verbosity=2)
