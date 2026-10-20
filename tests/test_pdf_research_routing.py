"""Focused routing contracts; existing classifier accuracy is outside this suite."""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("pdf_routing", Path(__file__).parents[1] / "ops/build_pdf_research_routing.py")
routing = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(routing)


def row(docid="d", material="券商/研究机构研究"):
    return {"document_id": docid, "primary_type_candidate": material,
        "classification_state": "FORM_CANDIDATE", "ocr_status_asof": "READY",
        "classification_status": "RULE_CANDIDATE_NOT_SEMANTICALLY_ACCEPTED",
        "classification_evidence": {"page_number": 1, "page_text_sha256": "p", "excerpt": "-3.1% 1,400亿元 +0.5%"},
        "source_references": {"pages": [{"page_number": 1, "text_sha256": "p"}]},
        "route_candidate": "SAVE", "report_date": {"value": None, "status": "UNKNOWN"},
        "original_institution_candidate": None, "verified_stock_codes": [], "page_count": 2,
        "pdf_sha256": docid, "frozen_page_input_sha256": "input", "frozen_page_input_path": "unused",
        "original_pdf_path": "/original/原件.pdf", "existing_analysis_status": "UNKNOWN_NOT_READ"}


class RoutingTests(unittest.TestCase):
    def route(self, source, **kwargs):
        return routing.route_one(source, kwargs.get("authorized", set()), kwargs.get("reuse", {}),
                                 kwargs.get("packages", {}), kwargs.get("relations", {}))

    def test_unknown_date_publisher_and_codes_are_preserved_without_global_block(self):
        source = row()
        actual = self.route(source)
        self.assertEqual(actual["route"], "SAVE")
        self.assertEqual(actual["original_metadata"], source)
        self.assertIsNone(actual["original_metadata"]["report_date"]["value"])
        self.assertEqual(actual["blocking_fields"], [])
        self.assertEqual(len(actual["restricted_uses"]), 3)
        self.assertIn("待具体任务触发", actual["route_reason"])

    def test_meeting_and_short_event_are_fact_cards_never_automatic_execution(self):
        for material in ["调研/会议记录", "新闻/资讯解读"]:
            actual = self.route(row(material=material))
            self.assertEqual(actual["route"], "LIGHT_EXTRACTION")
            self.assertFalse(actual["model_execution_authorized"])
            self.assertFalse(actual["model_execution_performed_by_routing"])

    def test_long_news_and_tutorial_remain_searchable_without_invented_question(self):
        for material in ["新闻/资讯解读", "教程/方法/其他"]:
            source = row(material=material)
            source["page_count"] = 60
            actual = self.route(source)
            self.assertEqual(actual["route"], "SAVE")
            self.assertEqual(actual["research_questions"], [])

    def test_bad_quality_precedes_package_and_reuse_and_names_block(self):
        for key, value in [("ocr_status_asof", "QUARANTINED"), ("ocr_status_asof", "FAILED"),
                           ("classification_state", "READY_QUALITY_REVIEW"), ("classification_state", "READY_FORM_REVIEW")]:
            source = row()
            source[key] = value
            actual = self.route(source, reuse={"d": {}}, packages={"d": [{"question": "q"}]})
            self.assertEqual(actual["route"], "REVIEW")
            self.assertIn(key + "=" + value, actual["blocking_fields"])

    def test_duplicate_candidate_cannot_be_promoted_to_valid_reuse(self):
        source = row()
        source["route_candidate"] = "REUSE_CANDIDATE"
        actual = self.route(source, relations={"d": [{"confirmed": False, "relation": "REPOST_OR_VERSION_CANDIDATE"}]})
        self.assertEqual(actual["route"], "REVIEW")
        self.assertFalse(actual["existing_result"]["valid_result_binding"])
        self.assertFalse(actual["duplicate_relations"][0]["confirmed"])

    def test_reuse_and_package_priority_preserves_failed_original_status(self):
        binding = {"status": "REPORT_WITH_ERRATUM_PASS", "original_model_report_status": "REPORT_CONTENT_FAIL"}
        actual = self.route(row(), reuse={"d": binding}, packages={"d": [{"question": "q"}]})
        self.assertEqual(actual["route"], "REUSE")
        self.assertEqual(actual["existing_result"], binding)
        self.assertEqual(self.route(row(), packages={"d": [{"question": "q"}]})["route"], "DEEP_RESEARCH")

    def test_authorization_is_membership_only_and_not_derived_from_route(self):
        for material in ["调研/会议记录", "券商/研究机构研究", "教程/方法/其他"]:
            source = row(material=material)
            self.assertFalse(self.route(source)["model_execution_authorized"])
            self.assertTrue(self.route(source, authorized={"d"})["model_execution_authorized"])
            self.assertEqual(self.route(source)["semantic_verification"], "NOT_ESTABLISHED_BY_ROUTING")

    def test_source_numbers_paths_and_unknown_metadata_survive_json_and_csv(self):
        source = row()
        actual = self.route(source)
        with tempfile.TemporaryDirectory() as temp:
            payload = {"statistics": {"route_counts": {"SAVE": 1}, "document_count": 1, "unique_ids": 1, "old_to_new_route_counts": {"SAVE -> SAVE": 1}}, "documents": [actual]}
            routing.write_outputs(payload, temp)
            reloaded = routing.read(Path(temp) / "routing.json")
            self.assertEqual(reloaded["documents"][0]["original_metadata"], source)
            for text in ["-3.1%", "1,400亿元", "+0.5%", "/original/原件.pdf"]:
                self.assertIn(text, (Path(temp) / "routing.csv").read_text(encoding="utf-8-sig"))

    def test_package_requires_original_page_excerpt_and_explicit_question_link(self):
        with tempfile.TemporaryDirectory() as temp:
            source = row()
            page = Path(temp) / "page.json"
            page.write_text(json.dumps({"pages": [{"page_number": 1, "text": "原文 -3.1% 1,400亿元 +0.5%"}]}))
            source.update(frozen_page_input_path=str(page), frozen_page_input_sha256=routing.sha(page))
            item = {"document_id": "d", "evidence": source["classification_evidence"], "question_link": "作者提供需求变化数字，作为待验证证据"}
            package = {"package_id": "p", "kind": "industry", "question": "需求变化数字是否支持作者判断？", "documents": [item]}
            self.assertIn("d", routing.package_bindings([package], {"d": source}))
            broken = copy.deepcopy(package)
            broken["documents"][0]["evidence"]["excerpt"] = "标题猜测的新数字"
            with self.assertRaisesRegex(ValueError, "EXCERPT_NOT_IN_ORIGINAL_PAGE"):
                routing.package_bindings([broken], {"d": source})
            del item["question_link"]
            with self.assertRaisesRegex(ValueError, "REQUIRES_PAGE_EVIDENCE"):
                routing.package_bindings([package], {"d": source})

    def test_input_sha_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "source"
            path.write_text("unchanged 1,400亿元")
            ref = {"path": str(path), "sha256": routing.sha(path)}
            path.write_text("drift 1400亿元")
            with self.assertRaisesRegex(ValueError, "INPUT_DRIFT"):
                routing.checked_ref(ref)

    def test_reuse_checks_receipt_input_report_and_review_status(self):
        source = row()
        ref = lambda name: {"path": name, "sha256": name}
        handoff = {"document_id": "d", "prepared_source": {"document_id": "d", "page_input": ref("input"), "prepared_receipt": ref("prepared")},
            "page_input": ref("input"), "report": ref("report"), "receipt": ref("receipt"), "display_report": ref("display"),
            "original_model_report_content_review": {"status": "REPORT_CONTENT_FAIL", "receipt": ref("original_review")},
            "display_combination_content_review": {"receipt": ref("review")}, "erratum_delivery": {"display": ref("display")}}
        review = {"status": "REPORT_WITH_ERRATUM_PASS", "display": ref("display"), "source_pdf": {"path": "pdf", "sha256": "d"}, "original_model_report": ref("report")}
        receipt = {"document_id": "d", "pdf_sha256": "d", "page_input": ref("input"), "prepared_text_page_input_sha256": "input", "report": ref("report")}
        objects = {"review": review, "receipt": receipt, "original_review": {"status": "REPORT_CONTENT_FAIL"}}
        with patch.object(routing, "checked_ref"), patch.object(routing, "read", side_effect=lambda path: objects[path]):
            self.assertEqual(routing.accepted_first_reuse(handoff, {"d": source})["d"]["original_model_report_status"], "REPORT_CONTENT_FAIL")
            receipt["page_input"] = ref("different_input")
            with self.assertRaisesRegex(ValueError, "REUSE_RESULT_OR_REVIEW_BINDING"):
                routing.accepted_first_reuse(handoff, {"d": source})
            receipt["page_input"] = ref("input")
            receipt["report"] = ref("different_report")
            with self.assertRaisesRegex(ValueError, "REUSE_RESULT_OR_REVIEW_BINDING"):
                routing.accepted_first_reuse(handoff, {"d": source})
            receipt["report"] = ref("report")
            review["status"] = "REPORT_CONTENT_FAIL"
            with self.assertRaisesRegex(ValueError, "REUSE_RESULT_OR_REVIEW_BINDING"):
                routing.accepted_first_reuse(handoff, {"d": source})

    def test_full_2209_identity_reconciliation_routes_and_frozen17_boundary(self):
        """Synthetic full-size manifest tests completeness, not population semantics."""
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sources = [row(str(index)) for index in range(2209)]
            manifest = root / "manifest.json"
            manifest.write_text(json.dumps({"documents": [{"document_id": r["document_id"]} for r in sources]}))
            manifest_ref = {"path": str(manifest), "sha256": routing.sha(manifest)}
            (root / "ledger.json").write_text(json.dumps({"documents": sources, "final_prepared_manifest": manifest_ref}))
            (root / "statistics.json").write_text("{}")
            (root / "all-relations.json").write_text(json.dumps({"exact_normalized_text_groups": [], "repost_or_version_candidates": []}))
            binding = {"artifacts": {name: {"sha256": routing.sha(root / name)} for name in ["ledger.json", "statistics.json", "all-relations.json"]}}
            (root / "BUILD.json").write_text(json.dumps(binding))
            selected = {"documents": [{"document_id": str(i), "page_input": {"sha256": "input"}} for i in range(18)], "canary_document_id": "0", "prepared_text_manifest_sha256": manifest_ref["sha256"]}
            (root / "selection.json").write_text(json.dumps(selected))
            (root / "handoff.json").write_text("{}")
            args = [root, root / "selection.json", root / "handoff.json", routing.sha(root / "BUILD.json"), manifest_ref["sha256"]]
            with patch.object(routing, "accepted_first_reuse", return_value={"0": {"status": "REPORT_WITH_ERRATUM_PASS"}}):
                result = routing.build(*args)
                self.assertEqual(len(result["documents"]), 2209)
                self.assertEqual(len({r["document_id"] for r in result["documents"]}), 2209)
                self.assertEqual(sum(result["statistics"]["route_counts"].values()), 2209)
                self.assertEqual({r["document_id"] for r in result["documents"] if r["model_execution_authorized"]}, {str(i) for i in range(1, 18)})
                self.assertTrue(all(r["route"] in routing.ROUTES for r in result["documents"]))
                sources[-1]["document_id"] = "0"
                (root / "ledger.json").write_text(json.dumps({"documents": sources, "final_prepared_manifest": manifest_ref}))
                binding["artifacts"]["ledger.json"]["sha256"] = routing.sha(root / "ledger.json")
                (root / "BUILD.json").write_text(json.dumps(binding))
                args[3] = routing.sha(root / "BUILD.json")
                with self.assertRaisesRegex(ValueError, "RECONCILIATION_FAIL"):
                    routing.build(*args)


if __name__ == "__main__":
    unittest.main()
