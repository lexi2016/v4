from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import unittest
from contextlib import contextmanager
from unittest.mock import patch


ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_MANAGER_OWNER_INPUT_INTEGRATION_MAC_20261010_R1")
SCRIPT = ROOT / "tools/deployment/fused_publication_adapter.py"
SPEC = importlib.util.spec_from_file_location("fused_publication_adapter_test", SCRIPT)
assert SPEC and SPEC.loader
adapter = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(adapter)


def _input_documents():
    stage = json.loads(adapter.STAGE_MANIFEST_PATH.read_text())
    fusion = json.loads(adapter.FUSION_RECEIPT.read_text())
    acceptance = json.loads(adapter.ACCEPTANCE_RECEIPT.read_text())
    fusion_plan = json.loads(adapter.FUSION_PLAN.read_text())
    r2 = json.loads(adapter.R2_DELTA_PATH.read_text())
    r1 = json.loads(adapter.R1_DELTA_PATH.read_text())
    return stage, fusion, acceptance, fusion_plan, r2, r1


class FusedPublicationAdapterTests(unittest.TestCase):
    def test_reviewed_stage_and_manager_source_sets_are_exact(self):
        stage, fusion, acceptance, _, r2, r1 = _input_documents()
        stage_paths, manager_paths = adapter._stage_manager_source_sets(stage, fusion, r2, r1, acceptance)
        self.assertEqual(stage_paths, set(adapter.EXPECTED_STAGE_REVIEWED_PATHS))
        self.assertEqual(len(manager_paths), 16)
        self.assertIn("v4/manager_research/workspace.py", manager_paths)
        self.assertIn("v4/manager_research/connect_selection.py", manager_paths)

    def test_r1_workspace_override_uses_final_after_sha(self):
        stage, fusion, acceptance, _, r2, r1 = _input_documents()
        _, manager_paths = adapter._stage_manager_source_sets(stage, fusion, r2, r1, acceptance)
        self.assertIn("v4/manager_research/workspace.py", manager_paths)
        r1_workspace = next(row for row in r1["changed_paths"]
                            if row["path"] == "v4/manager_research/workspace.py")
        final_workspace = next(row for row in fusion["source_changes_vs_stage_base"]
                               if row["path"] == "v4/manager_research/workspace.py")
        intermediate_workspace = next(row for row in fusion["source_operations"]
                                      if row["path"] == "v4/manager_research/workspace.py")
        self.assertEqual(final_workspace["after"]["sha256"], r1_workspace["after_sha256"])
        self.assertNotEqual(intermediate_workspace["after_sha256"], final_workspace["after"]["sha256"])

    def test_unreviewed_stage_path_fails_closed(self):
        stage, fusion, acceptance, _, r2, r1 = _input_documents()
        changed = copy.deepcopy(stage)
        changed["api_integration"]["delta_entries"].append({"path": "stage_center/extra.py"})
        with self.assertRaisesRegex(ValueError, "STAGE_SOURCE_PATH_SET_MISMATCH"):
            adapter._stage_manager_source_sets(changed, fusion, r2, r1, acceptance)

    def test_manager_path_expansion_fails_closed(self):
        stage, fusion, acceptance, _, r2, r1 = _input_documents()
        changed = copy.deepcopy(fusion)
        changed["source_changes_vs_stage_base"].append({"path": "v4/manager_research/unreviewed.py"})
        with self.assertRaisesRegex(ValueError, "FUSION_FINAL_SOURCE_PATH_SET_MISMATCH"):
            adapter._stage_manager_source_sets(stage, changed, r2, r1, acceptance)

    def test_stage_r5_rebase_keeps_stage_sources_as_base_and_limits_delta(self):
        stage, fusion, acceptance, fusion_plan, r2, r1 = _input_documents()
        wrapper, publisher, guard = adapter._load_runtime()
        _, _, owners = adapter._validate_receipts(
            writer=publisher,
            guard=guard,
            stage_manifest=stage,
            fusion_receipt=fusion,
            acceptance=acceptance,
            fusion_plan=fusion_plan,
            r2_delta=r2,
            r1_delta=r1,
        )
        active = guard.read_active_release(publisher.ACTIVE_API_PLIST)
        delta, integration = adapter._composite_delta(publisher, guard, active, owners)
        self.assertEqual(delta["base"]["release_id"], "stage-research-r4-20261009")
        self.assertEqual(delta["base"]["release_manifest_sha256"], adapter.CURRENT_STAGE_MANIFEST_SHA256)
        self.assertEqual(delta["stage_reviewed_source_path_count"], 9)
        self.assertEqual(delta["stage_source_count"], 0)
        self.assertEqual(delta["manager_source_count"], 16)
        self.assertEqual(delta["rebuilt_static_count"], 3)
        self.assertEqual(len(delta["entries"]), 19)
        self.assertEqual(delta["stage_reviewed_source_paths_preserved"], sorted(adapter.EXPECTED_STAGE_REVIEWED_PATHS))
        self.assertEqual(integration["module_source_paths"]["stage"], [])
        self.assertEqual(integration["preserved_module_source_paths"]["stage"], sorted(adapter.EXPECTED_STAGE_REVIEWED_PATHS))
        self.assertEqual(integration["delta_paths"], sorted(row["path"] for row in delta["entries"]))

    def test_execute_enters_locked_preflight_before_any_operation_write(self):
        plan_raw = adapter.PLAN_PATH.read_bytes()
        plan = json.loads(plan_raw)
        plan_sha = adapter._sha(plan_raw)
        active_path = Path(plan["before"]["active_api_plist_path"])
        active_sha_before = adapter._sha(active_path.read_bytes())
        operation_root = Path(plan["operation_root"])
        operations_before = sorted(p.name for p in operation_root.iterdir()) if operation_root.exists() else []
        wrapper, publisher, guard = adapter._load_runtime()
        lease = object()
        preflight_calls = []

        class StopBeforeMutation(Exception):
            pass

        @contextmanager
        def fake_lock():
            yield lease

        def stop_at_preflight(received_plan, received_path, received_sha, *, lease=None):
            preflight_calls.append((received_plan, received_path, received_sha, lease))
            raise StopBeforeMutation("preflight boundary reached; no publication mutation")

        review_path = adapter.ROOT / "review/fused_publication_plan_review.json"
        with patch.object(adapter, "_load_runtime", return_value=(wrapper, publisher, guard)), \
                patch.object(adapter, "_require_review") as review_check, \
                patch.object(publisher, "_switch_lock", fake_lock), \
                patch.object(wrapper, "_preflight", side_effect=stop_at_preflight) as preflight:
            with self.assertRaisesRegex(StopBeforeMutation, "preflight boundary reached"):
                adapter.execute(
                    plan_sha=plan_sha,
                    current_sha=plan["before"]["active_api_plist_sha256"],
                    staged_sha=plan["target"]["staged_api_plist_sha256"],
                    review_path=review_path,
                    review_sha="0" * 64,
                    confirmation=adapter.CONFIRM_EXECUTE,
                )

        review_check.assert_called_once()
        preflight.assert_called_once()
        self.assertEqual(len(preflight_calls), 1)
        received_plan, received_path, received_sha, received_lease = preflight_calls[0]
        self.assertEqual(received_plan["target"]["release_id"], plan["target"]["release_id"])
        self.assertEqual(received_path, adapter.PLAN_PATH)
        self.assertEqual(received_sha, plan_sha)
        self.assertIs(received_lease, lease)
        self.assertEqual(adapter._sha(active_path.read_bytes()), active_sha_before)
        operations_after = sorted(p.name for p in operation_root.iterdir()) if operation_root.exists() else []
        self.assertEqual(operations_after, operations_before)


if __name__ == "__main__":
    unittest.main()
