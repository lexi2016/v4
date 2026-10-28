"""Synthetic false-positive boundaries; these fixtures certify no actual stage."""
import json
from pathlib import Path
from copy import deepcopy
import subprocess
import sys
import tempfile
import unittest

from acceptance.a_chain_stage_acceptance import check_a_chain


ROOT = Path(__file__).resolve().parents[1]
OWNED_DOCS = ROOT / "docs/handoffs/v4_a_chain_completion_20261028"
STAGE = "STAGE_0930_0935"
DATE = "20261028"


def synthetic_capture(stage=STAGE, *, count=10):
    identity = dict(artifact_id="synthetic-selection-1", run_id="synthetic-run-1",
        algorithm_sha256="9" * 64, raw_artifact_sha256="a" * 64)
    prefix = f"selection_runs/{DATE}/A_SHARE_SELECTION_{stage}/{identity['run_id']}"
    rows = [dict(code=f"A.{index:06d}", score=42.0, news_quality_score=None,
        research_quality_score=None, research_bonus=None) for index in range(1, count + 1)]
    return dict(schema_version="stage_center.selection_consumer.v1", synthetic=True,
        trade_date=DATE, stage_id=stage, selected_a_rows=count, http_status=200,
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False,
        cannot_confirm=["SYNTHETIC_RESEARCH_QUALITY_MISSING"],
        markets={"A": dict(**identity, market="A_SHARE", rows=rows, selected_rows=count,
            status="PARTIAL_WITH_ROWS", selection_status="PARTIAL_WITH_ROWS", source_status="CANNOT_CONFIRM",
            selection_artifact_sha256="b" * 64, selection_manifest_sha256="e" * 64, selection_receipt_sha256="f" * 64,
            selection_manifest_receipt_verified=True, cannot_confirm=["SYNTHETIC_FORMAL_OVERLAY_MISSING"])},
        execution_evidence=dict(trade_date=DATE, stage_id=stage, execution_verified=False, natural_verified=False,
            markets={"A_SHARE": dict(declared_identity=dict(identity), selected_rows=count, status=None)},
            selection_artifact_bindings={"A_SHARE": dict(run_id=identity["run_id"],
                status="BOUND_TO_VERIFIED_SELECTION_TRIO",
                artifact_relative=prefix + "/artifact.csv", manifest_relative=prefix + "/manifest.json", receipt_relative=prefix + "/receipt.json",
                artifact_bytes_sha256="b" * 64, manifest_bytes_sha256="c" * 64, receipt_bytes_sha256="d" * 64,
                manifest_canonical_sha256="e" * 64, receipt_canonical_sha256="f" * 64,
                execution_verified=False, natural_verified=False)}))


def inspect(payload, stage=STAGE):
    return next(row for row in check_a_chain(DATE, {stage: payload})["stages"] if row["stage_id"] == stage)


def synthetic_ready_capture():
    capture = synthetic_capture()
    capture["cannot_confirm"] = []
    market = capture["markets"]["A"]
    market.update(status="READY", selection_status="READY", source_status="READY", cannot_confirm=[])
    for row in market["rows"]:
        row.update(news_quality_score=1.0, research_quality_score=2.0, research_bonus=0.075)
    return capture


class OfflineAcceptanceTests(unittest.TestCase):
    def test_owning_v1_actual_layout_without_repeated_binding_scope_is_accepted(self):
        capture = synthetic_capture()
        binding = capture["execution_evidence"]["selection_artifact_bindings"]["A_SHARE"]
        self.assertNotIn("artifact_id", binding)
        self.assertNotIn("raw_artifact_sha256", binding)
        self.assertNotIn("trade_date", capture["markets"]["A"])
        report = inspect(capture)
        self.assertTrue(report["row_contract_verified"], report["validation_errors"])
        self.assertEqual(report["business_status"], "BUSINESS_PARTIAL")
        self.assertFalse(report["actual_stage_pass"])
        self.assertFalse(report["natural_verified"])

    def test_owning_v1_outer_optional_scope_and_raw_identity_conflicts_fail(self):
        for change in ("outer_date", "outer_stage", "missing_outer_date", "optional_api_market", "optional_outer_market", "optional_market_stage", "optional_lane_market",
                       "nested_raw", "optional_binding_raw", "missing_nested_identity"):
            with self.subTest(change=change):
                capture = synthetic_capture()
                execution = capture["execution_evidence"]
                lane = execution["markets"]["A_SHARE"]
                binding = execution["selection_artifact_bindings"]["A_SHARE"]
                if change == "outer_date": execution["trade_date"] = "20261027"
                if change == "outer_stage": execution["stage_id"] = "STAGE_0945_1030"
                if change == "missing_outer_date": del execution["trade_date"]
                if change == "optional_api_market": capture["market"] = "HK_CONNECT"
                if change == "optional_outer_market": execution["market"] = "HK_CONNECT"
                if change == "optional_market_stage": capture["markets"]["A"]["stage_id"] = "STAGE_0945_1030"
                if change == "optional_lane_market": lane["market"] = "HK_CONNECT"
                if change == "nested_raw": lane["declared_identity"]["raw_artifact_sha256"] = "8" * 64
                if change == "optional_binding_raw": binding["raw_artifact_sha256"] = "8" * 64
                if change == "missing_nested_identity": del lane["declared_identity"]
                self.assertFalse(inspect(capture)["row_contract_verified"])

    def test_owning_v1_trio_paths_bind_exact_scope_and_safe_run(self):
        original = synthetic_capture()
        prefix = f"selection_runs/{DATE}/A_SHARE_SELECTION_{STAGE}/synthetic-run-1"
        for path in ("/" + prefix + "/artifact.csv", prefix + "/../artifact.csv",
                     prefix.replace(DATE, "20261027") + "/artifact.csv",
                     prefix.replace("A_SHARE_SELECTION", "HK_CONNECT_SELECTION") + "/artifact.csv",
                     prefix.replace(STAGE, "STAGE_0945_1030") + "/artifact.csv",
                     prefix.replace("synthetic-run-1", "other-run") + "/artifact.csv"):
            with self.subTest(path=path):
                capture = deepcopy(original)
                capture["execution_evidence"]["selection_artifact_bindings"]["A_SHARE"]["artifact_relative"] = path
                self.assertFalse(inspect(capture)["row_contract_verified"])
        capture = deepcopy(original)
        capture["markets"]["A"]["run_id"] = "../escape"
        capture["execution_evidence"]["markets"]["A_SHARE"]["declared_identity"]["run_id"] = "../escape"
        capture["execution_evidence"]["selection_artifact_bindings"]["A_SHARE"]["run_id"] = "../escape"
        self.assertFalse(inspect(capture)["row_contract_verified"])

    def test_owning_v1_canonical_json_hash_is_distinct_from_file_bytes_hash(self):
        capture = synthetic_capture()
        binding = capture["execution_evidence"]["selection_artifact_bindings"]["A_SHARE"]
        self.assertNotEqual(binding["manifest_bytes_sha256"], binding["manifest_canonical_sha256"])
        self.assertTrue(inspect(capture)["row_contract_verified"])
        for field, value in (("selection_manifest_sha256", binding["manifest_bytes_sha256"]),
                             ("selection_receipt_sha256", binding["receipt_bytes_sha256"]),
                             ("selection_artifact_sha256", "8" * 64)):
            with self.subTest(field=field):
                changed = deepcopy(capture)
                changed["markets"]["A"][field] = value
                self.assertFalse(inspect(changed)["row_contract_verified"])

    def test_review_r1_declared_execution_count_requires_exact_integer_match(self):
        for count in (99, "10", 10.0, True, None):
            with self.subTest(count=count):
                capture = synthetic_capture()
                capture["execution_evidence"]["markets"]["A_SHARE"]["selected_rows"] = count
                report = inspect(capture)
                self.assertFalse(report["row_contract_verified"])
                self.assertIn("EXECUTION_ROW_COUNT_MISMATCH", report["validation_errors"])
        capture = synthetic_capture()
        capture["execution_evidence"]["markets"]["A_SHARE"]["selected_rows"] = 10
        self.assertTrue(inspect(capture)["row_contract_verified"])

    def test_review_r1_declared_row_status_gaps_override_ready_market_summary(self):
        for field, value in (("source_status", "CANNOT_CONFIRM"), ("status", "PARTIAL"),
                             ("selection_status", "UNKNOWN"), ("source_health", "READY_WITH_GAPS"),
                             ("status", None)):
            with self.subTest(field=field, value=value):
                capture = synthetic_ready_capture()
                capture["markets"]["A"]["rows"][0][field] = value
                report = inspect(capture)
                self.assertTrue(report["row_contract_verified"])
                self.assertEqual(report["business_status"], "BUSINESS_PARTIAL")
                self.assertTrue(any(f"A_ROW_0_{field.upper()}_NOT_READY:" in gap for gap in report["business_gaps"]))
                declaration = report["row_status_declarations"][0]
                self.assertEqual(declaration["field"], field)
                self.assertEqual(declaration["value"], value)

    def test_review_r1_ready_row_declarations_do_not_add_false_business_gaps(self):
        capture = synthetic_ready_capture()
        capture["markets"]["A"]["rows"][0].update(status="READY", source_status="READY")
        report = inspect(capture)
        self.assertEqual(report["business_status"], "DECLARED_READY_ONLY")
        self.assertEqual(report["business_gaps"], [])
        self.assertFalse(report["actual_stage_pass"])

    def test_hk_ten_and_http200_and_hourly_reader_pass_cannot_pass_a(self):
        capture = synthetic_capture(count=0)
        capture["markets"] = {"HK": dict(rows=[dict(code=f"HK.{i:05d}") for i in range(10)], status="READY")}
        capture["hourly_reader_pass"] = True
        capture["status"] = "PARTIAL_WITH_ROWS"
        report = inspect(capture)
        self.assertEqual(report["observed_a_rows"], 0)
        self.assertFalse(report["row_contract_verified"])
        self.assertFalse(report["actual_stage_pass"])

    def test_verified_ten_rows_with_gaps_are_present_but_business_partial(self):
        report = inspect(synthetic_capture())
        self.assertEqual(report["row_materialization"], "ROW_RESULT_PRESENT_VERIFIED")
        self.assertEqual(report["business_status"], "BUSINESS_PARTIAL")
        self.assertIn("SYNTHETIC_RESEARCH_QUALITY_MISSING", report["business_gaps"])
        self.assertIn("SYNTHETIC_FORMAL_OVERLAY_MISSING", report["business_gaps"])
        self.assertEqual(len(report["declared_gaps"]), 2)
        self.assertEqual(report["natural_status"], "CANNOT_CONFIRM")
        self.assertFalse(report["natural_verified"])

    def test_wrong_date_raw_identity_trio_or_safety_cannot_pass(self):
        cases = []
        wrong_date = synthetic_capture(); wrong_date["trade_date"] = "20261027"; cases.append(wrong_date)
        wrong_stage = synthetic_capture(); wrong_stage["stage_id"] = "STAGE_0945_1030"; cases.append(wrong_stage)
        wrong_market_date = synthetic_capture(); wrong_market_date["markets"]["A"]["trade_date"] = "20261027"; cases.append(wrong_market_date)
        wrong_raw = synthetic_capture(); wrong_raw["execution_evidence"]["markets"]["A_SHARE"]["raw_artifact_sha256"] = "e" * 64; cases.append(wrong_raw)
        missing_trio = synthetic_capture(); del missing_trio["execution_evidence"]["selection_artifact_bindings"]["A_SHARE"]["receipt_bytes_sha256"]; cases.append(missing_trio)
        unsafe = synthetic_capture(); unsafe["orders_sent"] = True; cases.append(unsafe)
        unsafe_row = synthetic_capture(); unsafe_row["markets"]["A"]["rows"][0]["production_allowed"] = True; cases.append(unsafe_row)
        malformed_raw = synthetic_capture(); malformed_raw["markets"]["A"]["raw_artifact_sha256"] = "invalid"; cases.append(malformed_raw)
        conflict_trio = synthetic_capture(); conflict_trio["markets"]["A"]["artifact_bytes_sha256"] = "e" * 64; cases.append(conflict_trio)
        for index, capture in enumerate(cases):
            with self.subTest(case=index):
                report = inspect(capture)
                self.assertFalse(report["row_contract_verified"])
                self.assertTrue(report["validation_errors"])
                self.assertFalse(report["actual_stage_pass"])

    def test_duplicate_overcap_and_wrong_a_code_are_rejected(self):
        duplicate = synthetic_capture(); duplicate["markets"]["A"]["rows"][1]["code"] = "A.000001"
        overcap = synthetic_capture(count=11)
        hk_code = synthetic_capture(); hk_code["markets"]["A"]["rows"][0]["code"] = "HK.00068"
        for capture in (duplicate, overcap, hk_code):
            with self.subTest(capture=capture["markets"]["A"]["rows"][0]["code"]):
                self.assertFalse(inspect(capture)["row_contract_verified"])

    def test_historical_or_late_ten_rows_never_become_natural(self):
        for field, value in (("due_status", "HISTORICAL_BACKFILL"), ("mode", "LATE_CATCHUP_REPLAY"),
                             ("capture_mode", "AFTERFACT"), ("captured_at", "2026-10-28T20:31:42+08:00")):
            with self.subTest(field=field):
                capture = synthetic_capture()
                capture[field] = value
                capture["execution_evidence"].update(execution_verified=True, natural_verified=True)
                report = inspect(capture)
                self.assertTrue(report["row_contract_verified"])
                self.assertEqual(report["natural_status"], "RECOVERY_ONLY")
                self.assertFalse(report["natural_verified"])

    def test_0925_true_flags_without_native_receipt_proof_do_not_pass_natural(self):
        capture = synthetic_capture("STAGE_0925")
        capture["execution_evidence"].update(execution_verified=True, natural_verified=True)
        capture["captured_at"] = "2026-10-28T09:25:01+08:00"
        report = inspect(capture, "STAGE_0925")
        self.assertTrue(report["row_contract_verified"])
        self.assertFalse(report["natural_verified"])
        self.assertIn("NATIVE_0925_RAW_MANIFEST_AND_CAPTURE_WINDOW_RECEIPT_BINDING_REQUIRED", report["natural_gaps"])

    def test_unknown_schema_shapes_and_unknown_timestamp_fail_closed(self):
        unknown = synthetic_capture(); unknown["schema_version"] = "unknown.v9"
        malformed = synthetic_capture(); malformed["cannot_confirm"] = "lost gaps must not be ignored"
        for capture in (unknown, malformed, ["not an API object"]):
            self.assertFalse(inspect(capture)["row_contract_verified"])
        capture = synthetic_capture(); capture["captured_at"] = "2026-10-28 09:35:01"
        report = inspect(capture)
        self.assertTrue(any("TIMESTAMP_UNKNOWN_OR_WITHOUT_TIMEZONE" in gap for gap in report["natural_gaps"]))
        self.assertFalse(report["natural_verified"])

    def test_conflicting_natural_declarations_are_retained_and_never_upgraded(self):
        capture = synthetic_capture()
        capture["natural_verified"] = False
        capture["execution_evidence"]["natural_verified"] = True
        report = inspect(capture)
        values = {entry["path"]: entry["value"] for entry in report["execution_natural_declarations"]}
        self.assertIs(values["$.natural_verified"], False)
        self.assertIs(values["$.execution_evidence.natural_verified"], True)
        self.assertFalse(report["natural_verified"])

    def test_1555_is_na_and_missing_other_seven_stages_remain_unknown(self):
        report = check_a_chain(DATE, {})
        self.assertEqual(report["applicable_a_stage_count"], 7)
        self.assertEqual(report["row_contract_verified_count"], 0)
        self.assertEqual(report["natural_verified_count"], 0)
        self.assertEqual(report["stages"][-1]["applicability"], "NOT_APPLICABLE")
        self.assertEqual(report["stages"][-1]["reason"], "HK_ONLY_BY_CONTRACT")
        self.assertFalse(report["actual_live_certification"])

    def test_cli_writes_explicit_offline_report_without_fetching_missing_inputs(self):
        with tempfile.TemporaryDirectory(prefix="checker-test-", dir=OWNED_DOCS) as directory:
            directory = Path(directory)
            (directory / f"{STAGE}.json").write_text(json.dumps(synthetic_capture()))
            output = directory / "report.json"
            completed = subprocess.run([sys.executable, str(ROOT / "acceptance/a_chain_stage_acceptance.py"),
                "--trade-date", DATE, "--input-dir", str(directory), "--output-json", str(output)],
                capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text())
            self.assertEqual(result["row_contract_verified_count"], 1)
            self.assertEqual(result["overall_status"], "CANNOT_CONFIRM")
            self.assertFalse(result["actual_live_certification"])
            self.assertEqual(len(result["capture_files"]), 7)

    def test_cli_invalid_json_retains_source_hash_and_missing_stage_status(self):
        with tempfile.TemporaryDirectory(prefix="checker-test-", dir=OWNED_DOCS) as directory:
            directory = Path(directory)
            (directory / f"{STAGE}.json").write_text('{"unexpected": NaN}')
            output = directory / "report.json"
            completed = subprocess.run([sys.executable, str(ROOT / "acceptance/a_chain_stage_acceptance.py"),
                "--trade-date", DATE, "--input-dir", str(directory), "--output-json", str(output)],
                capture_output=True, text=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text())
            source = next(item for item in result["capture_files"] if item["stage_id"] == STAGE)
            self.assertEqual(len(source["sha256"]), 64)
            self.assertIn("NONFINITE_JSON_CONSTANT", source["error"])
            self.assertEqual(result["row_contract_verified_count"], 0)


if __name__ == "__main__":
    unittest.main()
