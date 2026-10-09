"""Portable filesystem tests; synthetic source manifests, no Mac or services."""
from __future__ import annotations

from copy import deepcopy
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))
import stage_patch
import current_research
import same_run_probe


def sha(data):
    return hashlib.sha256(data).hexdigest()


class DeploymentToolsTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        self.package.mkdir()
        self.source = self.root / "active"
        self.source.mkdir()
        self.candidate = self.root / "candidate"
        self.role = {"files": []}
        for name, before, after in (("a.py", b"old a\n", b"new a\n"),
                                    ("parts/b.py", b"old b\n", b"new b\n"),
                                    ("new.py", None, b"new module\n")):
            source = self.source / name
            source.parent.mkdir(parents=True, exist_ok=True)
            if before is not None:
                source.write_bytes(before)
            after_path = self.package / "after" / name
            after_path.parent.mkdir(parents=True, exist_ok=True)
            after_path.write_bytes(after)
            self.role["files"].append({
                "relative_path": name,
                "accepted_before_sha256": [sha(before) if before is not None else None],
                "after_sha256": sha(after), "after_path": f"after/{name}"})
        self.manifest = {"roles": {"actual_stage": self.role}}
        (self.package / "SOURCE_MAP.json").write_text(json.dumps(self.manifest))
        self.original_package = stage_patch.PACKAGE
        stage_patch.PACKAGE = self.package
        self.addCleanup(setattr, stage_patch, "PACKAGE", self.original_package)

    def prepare(self):
        return stage_patch.prepare(self.source, self.candidate, self.role)

    def configure_args(self):
        source_config = self.root / "source_config.json"
        source_config.write_text(json.dumps({
            "raw_root": str(self.root / "existing-data" / "raw"),
            "selection_root": str(self.root / "existing-data" / "selection"),
            "receipt_root": str(self.root / "existing-data" / "receipts"),
            "a_candidate_root": str(self.root / "inputs" / "a"),
            "hk_d1_root": str(self.root / "inputs" / "strict-hk"),
            "hk_master_path": str(self.root / "inputs" / "master.json"),
            "a_0925_recovery_authorization": None,
            "backfill_run_id": None,
            "unrelated_options": {"threshold": 17},
            "safety": {"extra_observation": "keep"}}))
        return SimpleNamespace(source_config=source_config, candidate_root=self.candidate,
                               output_root=self.root / "canary-output",
                               hk_research_root=self.root / "inputs" / "research-hk")

    def test_one_wrong_preimage_rejects_all_before_creating_candidate(self):
        (self.source / "parts/b.py").write_bytes(b"local dirty b\n")
        result = self.prepare()
        self.assertEqual(result["status"], "MISMATCH")
        self.assertFalse(self.candidate.exists())
        self.assertEqual((self.source / "a.py").read_bytes(), b"old a\n")
        self.assertFalse((self.source / "new.py").exists())

    def test_corrupt_supplied_after_rejected_before_creating_candidate(self):
        (self.package / "after/parts/b.py").write_bytes(b"corrupted package after\n")
        with self.assertRaisesRegex(ValueError, "after SHA mismatch"):
            self.prepare()
        self.assertFalse(self.candidate.exists())
        self.assertEqual((self.source / "a.py").read_bytes(), b"old a\n")

    def test_symlink_ancestor_cannot_hide_candidate_inside_active_source(self):
        alias = self.root / "alias"
        alias.symlink_to(self.source, target_is_directory=True)
        with patch.object(stage_patch.shutil, "copytree", side_effect=AssertionError("copy before isolation check")):
            with self.assertRaisesRegex(ValueError, "separate"):
                stage_patch.prepare(self.source, alias / "nested", self.role)
        self.assertFalse((self.source / "nested").exists())

    def test_prepare_changes_only_independent_candidate_and_records_role(self):
        result = self.prepare()
        self.assertEqual(result["status"], "MATCH")
        self.assertEqual((self.source / "a.py").read_bytes(), b"old a\n")
        self.assertFalse((self.source / "new.py").exists())
        self.assertEqual((self.candidate / "a.py").read_bytes(), b"new a\n")
        marker = json.loads((self.candidate / "V4_CANARY_IDENTITY.json").read_text())
        self.assertEqual(marker["role"], "actual_stage")
        self.assertEqual(marker["source_map_sha256"], sha((self.package / "SOURCE_MAP.json").read_bytes()))

    def test_copied_marker_symlink_cannot_overwrite_external_file(self):
        sentinel = self.root / "outside-receipt.json"
        sentinel.write_bytes(b"external owner receipt\n")
        (self.source / "V4_CANARY_IDENTITY.json").symlink_to(sentinel)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.prepare()
        self.assertEqual(sentinel.read_bytes(), b"external owner receipt\n")

    def test_all_copied_preimages_checked_before_any_patch_write(self):
        copytree = stage_patch.shutil.copytree

        def changed_during_copy(source, target, *args, **kwargs):
            result = copytree(source, target, *args, **kwargs)
            if Path(target) == self.candidate:
                (Path(target) / "parts/b.py").write_bytes(b"changed while copying\n")
            return result

        with patch.object(stage_patch.shutil, "copytree", side_effect=changed_during_copy):
            with self.assertRaisesRegex(ValueError, "source changed during copy"):
                self.prepare()
        self.assertEqual((self.candidate / "a.py").read_bytes(), b"old a\n")
        self.assertFalse((self.candidate / "V4_CANARY_IDENTITY.json").exists())

    def test_config_keeps_all_source_inputs_and_only_changes_roots_and_safety(self):
        self.prepare()
        args = self.configure_args()
        before_bytes = args.source_config.read_bytes()
        before = json.loads(before_bytes)
        report = current_research.configure(args)
        actual = json.loads(Path(report["config"]).read_text())
        expected = deepcopy(before)
        for key, name in (("raw_root", "raw"), ("selection_root", "selection"), ("receipt_root", "receipts")):
            expected[key] = str(args.output_root / "stage" / name)
        expected["hk_current_day_research_root"] = str(args.hk_research_root)
        expected["safety"].update(current_research.FLAGS)
        expected.update(current_research.FLAGS)
        self.assertEqual(actual, expected)
        self.assertEqual(args.source_config.read_bytes(), before_bytes)
        self.assertFalse(args.hk_research_root.exists())

    def test_config_rejects_output_nested_in_active_input_root_before_mkdir(self):
        self.prepare()
        args = self.configure_args()
        args.output_root = self.root / "inputs" / "a" / "run-output"
        with self.assertRaisesRegex(ValueError, "separate"):
            current_research.configure(args)
        self.assertFalse(args.output_root.exists())

    def test_config_rejects_modified_candidate_after_before_mkdir(self):
        self.prepare()
        args = self.configure_args()
        (self.candidate / "parts/b.py").write_bytes(b"post-prepare damage\n")
        with self.assertRaisesRegex(ValueError, "after|SHA|identity"):
            current_research.configure(args)
        self.assertFalse(args.output_root.exists())

    def test_run_rejects_modified_candidate_before_importing_application(self):
        self.prepare()
        args = self.configure_args()
        report = current_research.configure(args)
        (self.candidate / "parts/b.py").write_bytes(b"post-configure damage\n")
        run_args = SimpleNamespace(candidate_root=self.candidate, config=Path(report["config"]),
                                   trade_date="20261009", stage="STAGE_1545_1555")
        with self.assertRaisesRegex(ValueError, "after|SHA|identity"):
            current_research.run(run_args)

    def test_report_writer_never_overwrites_existing_owner_receipt(self):
        receipt = self.root / "owner.json"
        receipt.write_bytes(b"immutable owner evidence\n")
        with self.assertRaisesRegex(ValueError, "exist|new"):
            stage_patch.write_new_report(receipt, "would overwrite\n")
        self.assertEqual(receipt.read_bytes(), b"immutable owner evidence\n")

    def test_malformed_http_projection_is_a_reported_issue(self):
        issues = same_run_probe.projection_issues([], {}, "HK_CONNECT", "exact_run")
        self.assertTrue(any("OBJECT" in issue for issue in issues))

    def projection(self):
        selected = {"trade_date": "20261009", "stage_id": "STAGE_1545_1555", "market": "HK_CONNECT",
                    "run_id": "run-synthetic-test", "artifact_id": "synthetic-selection",
                    "algorithm_sha256": sha(b"synthetic algorithm"), "raw_artifact_sha256": sha(b"synthetic quotes"),
                    "selected_rows": 10, "input_mode": "CURRENT_DAY_RESEARCH_ONLY",
                    "runtime_source_identity": {"source_set_sha256": sha(b"synthetic code")},
                    "hk_current_day_research": {"input_binding_sha256": sha(b"synthetic input")}}
        payload = {**stage_patch.FLAGS, "execution_evidence": {
            "natural_verified": False, "attempt_mode": "MANUAL_CURRENT_DAY_RESEARCH",
            "selection_results": {"HK_CONNECT": deepcopy(selected)},
            "selection_artifact_bindings": {"HK_CONNECT": {"status": "BOUND_TO_VERIFIED_SELECTION_TRIO"}},
            "selection_source_bindings": {"HK_CONNECT": {"status": "SELECTION_SOURCE_IDENTITY_BOUND_TO_TRIO_AND_OWNER_HISTORY"}},
            "input_binding_status": {"HK_CONNECT": {"status": "RESEARCH_INPUT_BOUND_TO_SELECTION_AND_OWNER_HISTORY"}}}}
        return selected, payload

    def test_same_identity_projection_with_bound_research_receipt_is_accepted(self):
        selected, payload = self.projection()
        self.assertEqual(same_run_probe.projection_issues(payload, selected, "HK_CONNECT", "exact_run"), [])

    def test_same_run_id_cannot_conceal_wrong_date_source_or_natural_label(self):
        selected, payload = self.projection()
        evidence = payload["execution_evidence"]
        summary = evidence["selection_results"]["HK_CONNECT"]
        summary["trade_date"] = "20261008"
        summary["runtime_source_identity"]["source_set_sha256"] = sha(b"other code")
        summary["hk_current_day_research"]["input_binding_sha256"] = sha(b"other input")
        evidence["natural_verified"] = True
        evidence["selection_artifact_bindings"]["HK_CONNECT"]["status"] = "MISSING"
        issues = same_run_probe.projection_issues(payload, selected, "HK_CONNECT", "page_default")
        for marker in ("trade_date", "runtime_source_identity", "hk_current_day_research", "NATURAL", "NOT_BOUND"):
            self.assertTrue(any(marker in issue for issue in issues), (marker, issues))

    def test_a_same_run_also_requires_owner_input_binding(self):
        selected, payload = self.projection()
        selected["market"] = "A_SHARE"
        selected.pop("input_mode")
        selected.pop("hk_current_day_research")
        evidence = payload["execution_evidence"]
        evidence["selection_results"] = {"A_SHARE": deepcopy(selected)}
        evidence["selection_artifact_bindings"] = {"A_SHARE": {"status": "BOUND_TO_VERIFIED_SELECTION_TRIO"}}
        evidence["selection_source_bindings"] = {"A_SHARE": {"status": "SELECTION_SOURCE_IDENTITY_BOUND_TO_TRIO_AND_OWNER_HISTORY"}}
        evidence["input_binding_status"] = {"A_SHARE": {"status": "OWNER_DECLARED_INPUT_BOUND_TO_SELECTION"}}
        self.assertEqual(same_run_probe.projection_issues(payload, selected, "A_SHARE", "exact_run"), [])
        evidence["input_binding_status"]["A_SHARE"]["status"] = "A_INPUT_BINDING_CONFLICT"
        self.assertIn("exact_run:A_INPUT_NOT_BOUND_TO_SELECTION_AND_OWNER",
                      same_run_probe.projection_issues(payload, selected, "A_SHARE", "exact_run"))

    def test_matching_summary_source_cannot_conceal_conflicting_owner_source_binding(self):
        selected, payload = self.projection()
        payload["execution_evidence"]["selection_source_bindings"]["HK_CONNECT"]["status"] = "SELECTION_SOURCE_IDENTITY_CONFLICT"
        self.assertIn("exact_run:SOURCE_IDENTITY_NOT_BOUND_TO_SELECTION_AND_OWNER",
                      same_run_probe.projection_issues(payload, selected, "HK_CONNECT", "exact_run"))

    def test_valid_http_cannot_conceal_conflicting_local_projection(self):
        selected, http = self.projection()
        local = deepcopy(http)
        local["execution_evidence"]["selection_source_bindings"]["HK_CONNECT"]["status"] = "SELECTION_SOURCE_IDENTITY_CONFLICT"
        consumer = SimpleNamespace(store=SimpleNamespace(read_verified=lambda *args: deepcopy(selected)),
                                   get=lambda *args, **kwargs: local)
        module = ModuleType("stage_center.consumer")
        module.StageSelectionConsumer = lambda *args, **kwargs: consumer
        args = SimpleNamespace(api_root=self.root, selection_root=self.root / "selection", receipt_root=self.root / "receipts",
                               base_url="http://synthetic.invalid", date="20261009", stage="STAGE_1545_1555",
                               market="HK_CONNECT", run_id=None)
        http_bytes = json.dumps(http).encode()
        with patch.dict(sys.modules, {"stage_center": ModuleType("stage_center"), "stage_center.consumer": module}):
            with patch.object(same_run_probe, "urlopen", side_effect=lambda *args, **kwargs: BytesIO(http_bytes)):
                result = same_run_probe.probe(args)
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assertEqual(result["issues"], ["local:SOURCE_IDENTITY_NOT_BOUND_TO_SELECTION_AND_OWNER"])


if __name__ == "__main__":
    unittest.main()
