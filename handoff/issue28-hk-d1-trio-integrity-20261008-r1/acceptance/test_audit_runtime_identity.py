"""Controlled smoke checks for the read-only inventory; no V4 imports."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


AGENT_ROOT = Path(__file__).resolve().parent
BASELINE = Path(os.environ.get("ISSUE28_HK_PROBLEM_ROOT", str(AGENT_ROOT.parent / "baseline")))
SCRIPT = AGENT_ROOT / "audit_runtime_identity.py"
RELATIVE = "stage_center/_runner_parts/hk_input_validation.py"
BEFORE = "92e8fb2be06e6530c33f3cf2f5b44f29b0bcf7875e6a5902260f8be4c814f735"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def regular_files(root):
    return {str(path.relative_to(root)): digest(path.read_bytes())
            for path in root.rglob("*") if path.is_file() and not path.is_symlink()}


class ReadOnlyAuditSmoke(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="issue28-identity-smoke-")
        # macOS tempfile may spell /private/var through the /var alias. Resolve
        # only this newly created fixture root; owner-path checks stay strict.
        self.root = Path(self.temp.name).resolve()
        self.problem = self.root / "problem"
        shutil.copytree(BASELINE / "evidence", self.problem / "evidence")
        for owner in ("canonical", "actual_stage_owner", "api_runtime"):
            shutil.copytree(BASELINE / "source" / owner, self.root / owner)
        self.receipts = self.root / "receipts"
        receipt_path = self.receipts / "20261008" / "STAGE_0930_0935" / "receipt.json"
        receipt_path.parent.mkdir(parents=True)
        receipt = {
            "schema_version": "stage_center.runner.receipt.v1", "trade_date": "20261008",
            "stage_id": "STAGE_0930_0935", "status": "PARTIAL_WITH_ROWS", "node_outcome": "SETTLED_PARTIAL",
            "write_performed": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
            "markets": {"HK_CONNECT": {"status": "CANNOT_CONFIRM", "selected_rows": 0, "write_performed": False,
                                         "cannot_confirm": ["HK D1 split-date eligibility provenance missing"],
                                         "rows": [{"symbol": "PRIVATE_ROW_CANARY", "name": "PRIVATE_NAME_CANARY"}]}},
        }
        receipt_path.write_text(json.dumps(receipt))
        config = {
            "release_id": "20261003-hk-binding-wrapper-r3", "receipt_root": str(self.receipts),
            "safety": {"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
            "secret": "PRIVATE_CONFIG_CANARY",
        }
        (self.root / "actual_stage_owner" / "stage_center_tick_config.json").write_text(json.dumps(config))
        self.args = [sys.executable, "-B", str(SCRIPT), "--problem-root", str(self.problem),
                     "--stage-root", str(self.root / "actual_stage_owner"),
                     "--canonical-root", str(self.root / "canonical"),
                     "--api-root", str(self.root / "api_runtime"), "--receipt-root", str(self.receipts)]

    def tearDown(self):
        self.temp.cleanup()

    def invoke(self, *extra):
        before = regular_files(self.root)
        output = subprocess.run([*self.args, *extra], text=True, capture_output=True, check=False, timeout=15)
        self.assertEqual(output.stderr, "")
        self.assertEqual(before, regular_files(self.root), "audit changed a fixture file")
        return output.returncode, json.loads(output.stdout), output.stdout

    def test_before_identity_redaction_and_missing_snapshot_stay_unconfirmed(self):
        code, value, raw = self.invoke()
        self.assertEqual(code, 3)  # Full current API app bytes are not in the problem package.
        hk = [item for item in value["sources"] if item["path"] == RELATIVE]
        self.assertEqual(len(hk), 2)
        self.assertTrue(all(item["status"] == "MATCHES_BEFORE" for item in hk))
        self.assertEqual(value["source_identity_status"], "CANNOT_CONFIRM")
        self.assertEqual(value["runtime_recovery_status"], "CANNOT_CONFIRM")
        self.assertEqual(value["receipt"]["summary"]["HK_CONNECT"]["frozen_provenance_missing_reason_observed"], True)
        self.assertFalse(value["receipt"]["matches_frozen_receipt_sha256"])
        for canary in ("PRIVATE_ROW_CANARY", "PRIVATE_NAME_CANARY", "PRIVATE_CONFIG_CANARY"):
            self.assertNotIn(canary, raw)

    def test_both_owner_candidate_after_manifest_is_an_identity_observation(self):
        files = []
        for owner in ("canonical", "actual_stage_owner"):
            path = self.root / owner / RELATIVE
            path.write_bytes(path.read_bytes() + b"\n# isolated smoke candidate only\n")
            files.append({"owner": owner, "path": RELATIVE, "before_sha256": BEFORE,
                          "after_sha256": digest(path.read_bytes())})
        manifest = self.root / "candidate_identity.json"
        manifest.write_text(json.dumps({"schema_version": "issue28.hk_stage_candidate_identity.v1", "files": files}))
        code, value, _ = self.invoke("--candidate-manifest", str(manifest))
        self.assertEqual(code, 3)
        self.assertTrue(all(item["status"] == "MATCHES_AFTER" for item in value["sources"] if item["path"] == RELATIVE))
        self.assertEqual(value["runtime_recovery_status"], "CANNOT_CONFIRM")

    def test_nonallowlisted_candidate_path_is_rejected(self):
        manifest = self.root / "candidate_identity.json"
        manifest.write_text(json.dumps({"schema_version": "issue28.hk_stage_candidate_identity.v1", "files": [
            {"owner": "actual_stage_owner", "path": "../outside.py", "before_sha256": BEFORE, "after_sha256": "0" * 64}
        ]}))
        code, value, _ = self.invoke("--candidate-manifest", str(manifest))
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "INPUT_REJECTED")

    def test_changed_frozen_evidence_is_rejected(self):
        path = self.problem / "evidence" / "source_identity.json"
        path.write_bytes(path.read_bytes() + b"\n")
        code, value, _ = self.invoke()
        self.assertEqual(code, 2)
        self.assertEqual(value["status"], "INPUT_REJECTED")

    def test_symlink_owner_file_is_rejected_without_following_it(self):
        path = self.root / "actual_stage_owner" / RELATIVE
        other = self.root / "not_an_owner.py"
        path.rename(other)
        path.symlink_to(other)
        code, value, _ = self.invoke()
        self.assertEqual(code, 3)
        item = next(item for item in value["sources"] if item["owner"] == "actual_stage_owner" and item["path"] == RELATIVE)
        self.assertEqual(item["status"], "UNREADABLE_OR_UNSTABLE")
        self.assertNotIn("sha256", item)


if __name__ == "__main__":
    unittest.main(verbosity=2)
