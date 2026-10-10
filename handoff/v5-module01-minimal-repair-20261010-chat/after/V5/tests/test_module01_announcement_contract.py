"""Original-owner announcement contracts for the first V5 delivery module.

All inputs are synthetic and created by the target owner. These tests are
regressions for existing equivalent behavior, not a Mac 392-decision receipt.
"""
import copy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from module01_owner_fixture import create_manager_fixture, PUBLICATION, TARGET, SYNTHETIC_REASON
from v5_shadow.announcement_analysis_api import response_record
from v5_shadow.announcement_bridge import run_announcement_bridge
from v5_shadow.announcement_offline_reader import APP, PIN, sources
from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow.manager_plan import run_manager_plan


class Module01AnnouncementContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="module01-synthetic-announcements-")
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name).resolve()
        cls.fixture = create_manager_fixture(cls.root)

    def copied_bridge(self, root):
        request = copy.deepcopy(self.fixture["announcement_request"])
        for root_key, files_key, name in (("manager_root", "manager_files", "manager"),
                                          ("materials_root", "material_files", "materials")):
            dest = Path(root) / name
            dest.mkdir()
            for relative in request[files_key]:
                path = dest / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((Path(request[root_key]) / relative).read_bytes())
            request[root_key] = str(dest)
        return request

    def source_snapshot(self):
        return {group: {name: (Path(binding["root"]) / name).read_bytes() for name in binding["files"]}
                for group, binding in self.fixture["request"]["inputs"].items()}

    def announcement(self, payload):
        channels = {row["channel"]: row for row in payload["daily_channels"]["channels"]}
        return channels["ANNOUNCEMENT"]

    def test_original_owner_keeps_decisions_separate_from_selected_stocks(self):
        selection = self.fixture["owner_readback"]["analysis"]["stock_selection"]
        self.assertEqual(selection["status"], "VERIFIED")
        self.assertEqual(len(selection["article_decisions"]), 4)
        self.assertEqual(selection["stock_count"], 4)
        self.assertEqual(selection["selected_stock_count"], 1)
        self.assertEqual(selection["conditional_watch_count"], 1)
        self.assertEqual(selection["not_selected_stock_count"], 1)
        self.assertEqual(selection["not_assessed_stock_count"], 1)
        self.assertEqual(self.fixture["consumption"]["status"], "CONSUMED")
        self.assertFalse(self.fixture["provenance"]["real_392_reused"])

    def test_bridge_runs_original_catalog_and_handoff_readers_without_input_changes(self):
        before = self.source_snapshot()
        result = run_announcement_bridge(copy.deepcopy(self.fixture["announcement_request"]))
        self.assertEqual(result["payload"]["analysis"], self.fixture["owner_readback"]["analysis"])
        self.assertEqual(result["catalog"]["readback"]["derivation"], "REPARSED_FROM_SHARED_MATERIAL_STORE")
        self.assertEqual(result["payload"]["consumption_validation"]["validation_status"], "VERIFIED")
        self.assertFalse(result["payload"]["consumption_validation"]["consumed"])
        self.assertEqual(result["payload"]["consumption_validation"]["cutoff_status"], "NOT_REQUESTED")
        self.assertTrue(any(name.endswith("/reader_output.json") for name in result["original_reader_accesses"]["manager"]))
        self.assertTrue(any(name.startswith("blobs/") for name in result["original_reader_accesses"]["materials"]))
        self.assertFalse(result["natural_verified"])
        self.assertFalse(result["source_origin_verified"])
        self.assertEqual(self.source_snapshot(), before)

    def test_healthy_announcement_survives_missing_us_connect_and_rebound_inputs(self):
        before = self.source_snapshot()
        request = copy.deepcopy(self.fixture["request"])
        request["now"] = datetime.now(timezone.utc).isoformat()
        result = run_manager_plan(request)
        payload = result["payload"]
        self.assertEqual(result["readback"]["status"], "MATCHED")
        self.assertEqual(payload["us_market_attention"]["status"], "INPUT_MISSING")
        channels = {row["channel"]: row for row in payload["daily_channels"]["channels"]}
        announcement = channels["ANNOUNCEMENT"]
        self.assertEqual(announcement["candidate_count"], 1)
        self.assertEqual(announcement["watch_count"], 1)
        self.assertEqual(announcement["pending_count"], 1)
        self.assertEqual(announcement["status"], "PARTIAL")
        self.assertEqual({row["symbol"] for row in announcement["rows"]}, {"HK.00001", "HK.00002"})
        self.assertEqual(channels["HK_CONNECT"]["status"], "CANNOT_CONFIRM")
        self.assertEqual(channels["OVERSOLD"]["status"], "CANNOT_CONFIRM")
        self.assertTrue(channels["HK_CONNECT"]["gaps"])
        self.assertTrue(channels["OVERSOLD"]["gaps"])
        for row in announcement["rows"]:
            self.assertIn(SYNTHETIC_REASON, row["reason"])
            self.assertTrue(row["source_refs"])
            self.assertEqual(row["data_date"], PUBLICATION.replace("-", ""))
            self.assertEqual(row["target_trade_date"], TARGET)
            self.assertEqual(row["product_sha256"], self.fixture["consumption"]["product_sha256"])
        for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
            self.assertIs(payload[key], False)
        self.assertFalse(result["natural_verified"])
        self.assertEqual(self.source_snapshot(), before)
        request.update(action="read", now=datetime.now(timezone.utc).isoformat())
        reread = run_manager_plan(request)
        self.assertEqual(reread["payload"]["plan_product"]["run_id"], result["readback"]["run_id"])
        self.assertTrue(reread["payload"]["plan_product"]["consumed"])
        self.assertEqual(self.announcement(reread["payload"])["rows"], announcement["rows"])

    def test_resealed_outer_material_pin_cannot_hide_changed_original_source(self):
        with tempfile.TemporaryDirectory(prefix="module01-source-tamper-") as tmp:
            request = self.copied_bridge(tmp)
            source = self.fixture["owner_readback"]["analysis"]["records"][0]["listing_source"]["source_ref"]
            name = "blobs/" + source["blob_sha256"]
            path = Path(request["materials_root"]) / name
            raw = path.read_bytes() + b" changed original source"
            path.write_bytes(raw)
            request["material_files"][name] = hashlib.sha256(raw).hexdigest()
            with self.assertRaises(ValueError):
                run_announcement_bridge(request)

    def test_resealed_outer_body_pin_still_fails_original_handoff_verification(self):
        with tempfile.TemporaryDirectory(prefix="module01-body-tamper-") as tmp:
            request = self.copied_bridge(tmp)
            name = next(name for name in request["manager_files"] if "/body_batch/bodies/" in name)
            path = Path(request["manager_root"]) / name
            raw = path.read_bytes() + b" "
            path.write_bytes(raw)
            request["manager_files"][name] = hashlib.sha256(raw).hexdigest()
            result = run_announcement_bridge(request)
            consumption = result["payload"]["consumption_validation"]
            self.assertEqual(consumption["validation_status"], "CANNOT_CONFIRM")
            self.assertEqual(consumption["failure_stage"], "REGISTERED_HANDOFF")
            self.assertFalse(consumption["consumed"])
            self.assertEqual(consumption["research_references"], [])

    def test_resealed_owner_receipt_cannot_borrow_another_parent(self):
        with tempfile.TemporaryDirectory(prefix="module01-receipt-tamper-") as tmp:
            request = self.copied_bridge(tmp)
            name = next(name for name in request["manager_files"] if name.endswith("/owner_import_receipt.v1.json"))
            path = Path(request["manager_root"]) / name
            receipt = json.loads(path.read_bytes())
            receipt["parent_task_id"] = "synthetic-different-parent"
            receipt["sha256"] = sha256_json({key: value for key, value in receipt.items() if key != "sha256"})
            raw = canonical_bytes(receipt)
            path.write_bytes(raw)
            request["manager_files"][name] = hashlib.sha256(raw).hexdigest()
            with self.assertRaisesRegex(ValueError, "PARENT_BINDING"):
                run_announcement_bridge(request)

    def test_missing_registered_handoff_never_becomes_verified_consumption(self):
        with tempfile.TemporaryDirectory(prefix="module01-handoff-missing-") as tmp:
            request = self.copied_bridge(tmp)
            for name in list(request["manager_files"]):
                if name.startswith("announcement_agent_runs/"):
                    del request["manager_files"][name]
            result = run_announcement_bridge(request)
            self.assertEqual(result["payload"]["analysis"]["status"], "VERIFIED")
            consumption = result["payload"]["consumption_validation"]
            self.assertEqual(consumption["validation_status"], "CANNOT_CONFIRM")
            self.assertFalse(consumption["consumed"])
            self.assertEqual(consumption["research_references"], [])

    def test_actual_analysis_dto_rejects_wrong_date_or_default_relabel(self):
        result = dict(analysis=copy.deepcopy(self.fixture["owner_readback"]), request_sha256="a" * 64)
        config = dict(module_id="announcements", release_id="module01-synthetic")
        record = response_record(result, config, {"date": TARGET, "publication_date": PUBLICATION})
        self.assertEqual(record["payload"], self.fixture["owner_readback"])
        with self.assertRaisesRegex(ValueError, "QUERY_DATE_MISMATCH"):
            response_record(result, config, {"date": TARGET, "publication_date": "2026-10-07"})
        with self.assertRaisesRegex(ValueError, "QUERY_BASIS_MISMATCH"):
            response_record(result, config, {"date": TARGET})

    def test_original_owner_source_pin_rejects_a_changed_capsule_file(self):
        with tempfile.TemporaryDirectory(prefix="module01-capsule-tamper-") as tmp:
            copy_root = Path(tmp) / "capsule"
            shutil.copytree(APP, copy_root)
            path = copy_root / "v4/manager_research/announcement_analysis.py"
            path.write_bytes(path.read_bytes() + b"\n# synthetic tamper\n")
            with self.assertRaisesRegex(ValueError, "OFFLINE_MANAGER_APP_BYTES"):
                sources(copy_root, PIN)


if __name__ == "__main__":
    unittest.main()
