"""Check the exact Main patch against installed D24 evidence, with writes stubbed."""
from contextlib import nullcontext
from datetime import datetime
import hashlib
import importlib
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
SOURCE = json.loads((ROOT / "base_source_manifest.json").read_bytes())
APP = Path(SOURCE["active_code_root_at_capture"])
DAY = "20261124"
NEXT_DAY = "20261125"
LIVE = SimpleNamespace(value="LIVE")
REPLAY = SimpleNamespace(value="REPLAY")
POLICY = ("V4_RESEARCH_RETENTION_POLICY", "V4_RESEARCH_RETENTION_POLICY_SHA256")


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def request(date, mode=LIVE):
    return SimpleNamespace(business_date=date, target_date=date, slot="1610", mode=mode)


def moment(date):
    return datetime.strptime(date + "1611", "%Y%m%d%H%M").replace(tzinfo=ZoneInfo("Asia/Shanghai"))


class PhysicalADaily(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        overlay = Path(temporary.name).resolve()
        patch_path = ROOT / SOURCE["patch_name"]
        assert digest(patch_path) == SOURCE["patch_sha256"]
        assert digest(APP.parent / "startup-manifest.json") == SOURCE["active_release_manifest_sha256"]
        assert digest(APP / "release-manifest.json") == SOURCE["active_app_manifest_sha256"]
        for rel, identity in SOURCE["files"].items():
            if identity["before_sha256"]:
                assert digest(APP / rel) == identity["before_sha256"]
                path = overlay / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(APP / rel, path)
        subprocess.run(["git", "apply", str(patch_path)], cwd=overlay, check=True)
        for rel, identity in SOURCE["files"].items():
            assert digest(overlay / rel) == identity["after_sha256"]
        sys.path.insert(0, str(APP))
        import infrastructure.scheduling
        import ops
        infrastructure.scheduling.__path__ = [str(overlay / "infrastructure/scheduling"), *infrastructure.scheduling.__path__]
        ops.__path__ = [str(overlay / "ops"), *ops.__path__]
        for module in ("infrastructure.scheduling.executor_registry",
                       "infrastructure.scheduling.executor_registry_review",
                       "ops.research_a_daily_physical", "ops.macos_research_panel_daily_authority"):
            sys.modules.pop(module, None)
        cls.review = importlib.import_module("infrastructure.scheduling.executor_registry_review")
        cls.physical = importlib.import_module("ops.research_a_daily_physical")
        cls.authority = importlib.import_module("ops.macos_research_panel_daily_authority")
        cls.registry = importlib.import_module("infrastructure.scheduling.executor_registry")
        assert Path(cls.registry.__file__).is_relative_to(overlay)
        assert Path(cls.review.__file__).is_relative_to(overlay)
        assert Path(cls.physical.__file__).is_relative_to(overlay)
        assert Path(cls.authority.__file__).is_relative_to(overlay)
        plist = Path.home() / "Library/LaunchAgents/com.lexi.v4.scheduler.plist"
        cls.environment = plistlib.loads(plist.read_bytes())["EnvironmentVariables"]
        cls.receipt_path = Path(cls.environment["V4_RESEARCH_PANEL_RECEIPT_ROOT"]) / f"a-{DAY}.json"
        cls.receipt = json.loads(cls.receipt_path.read_bytes())
        cls.data = Path(cls.environment["V4_RESEARCH_PANEL_A_DATA_ROOT"])

    def setUp(self):
        environment = patch.dict(os.environ, self.environment)
        environment.start()
        self.addCleanup(environment.stop)
        self.executor = object.__new__(self.registry.FixedExecutorRegistry)
        self.executor._active_workload_id = None
        self.executor.hk_0_2_python_executable = Path(self.environment["V4_RESEARCH_PANEL_HK_PYTHON_EXECUTABLE"])

    def test_first_start_exact_floor_and_a_child_environment(self):
        from ops.macos_research_panel_daily_common import SnapshotGateError

        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            "V4_RESEARCH_PANEL_RECEIPT_ROOT": str(Path(temp).resolve()),
        }), patch.object(self.registry, "shanghai_now", return_value=moment(NEXT_DAY)):
            def capture(module, args, *, env=None, **_kwargs):
                self.assertEqual(module, "ops.macos_research_panel_daily")
                self.assertEqual(args[args.index("--lane") + 1], "A")
                self.assertEqual(args[args.index("--date") + 1], NEXT_DAY)
                self.assertIsNotNone(env)
                self.assertTrue(all(key not in env for key in POLICY))
                self.assertEqual(env[self.physical.MODE_ENV], "1")
                self.assertEqual(env["V4_STORAGE_PAIR_ROOT"], self.environment["V4_STORAGE_PAIR_ROOT"])
                raise RuntimeError("SAFE_OWNER_INTERCEPT")

            dispatch = {"test": "safe-owner-intercept"}
            with patch.dict(self.executor._research_panel_daily.__func__.__globals__, {
                "_natural_dispatch_context": lambda _request: (dispatch, None),
            }), \
                    patch.object(self.executor, "_run", side_effect=capture) as child, \
                    patch.object(self.physical.shutil, "disk_usage") as space:
                space.return_value.free = self.physical.MIN_FREE_BYTES - 1
                with self.assertRaises(self.registry.WorkloadExecutionError) as low:
                    self.executor._run_a_daily(request(NEXT_DAY))
                self.assertIn("A_DAILY_PHYSICAL_SPACE_MINIMUM", low.exception.result["reason"])
                child.assert_not_called()
                space.return_value.free = self.physical.MIN_FREE_BYTES
                with self.assertRaisesRegex(RuntimeError, "SAFE_OWNER_INTERCEPT"):
                    self.executor._run_a_daily(request(NEXT_DAY))
                child.assert_called_once()
                self.assertNotIn(self.physical.MODE_ENV, os.environ)
                self.assertTrue(all(os.environ[key] == self.environment[key] for key in POLICY))

        with patch.dict(os.environ, {self.physical.MODE_ENV: "1"}):
            with self.assertRaisesRegex(SnapshotGateError, "STORAGE_POLICY_CONFLICT"):
                self.physical.physical_mode()
        with patch.object(self.executor, "_run_a_daily_source", return_value={"status": "SUCCEEDED"}) as replay:
            self.executor._run_a_daily(request(NEXT_DAY, REPLAY))
            replay.assert_called_once()
            self.assertTrue(all(os.environ[key] == self.environment[key] for key in POLICY))

    def test_real_d24_partial_and_ready_branch_reuse_without_download(self):
        from ops import macos_research_panel_daily_receipts as receipts
        from ops import research_panel_formula_groups_daily as groups
        from ops import research_panel_top200 as top200
        from ops import research_storage_governance as governance

        operations = []
        original_validate = receipts.validate_a_receipt

        def check_only(function, *args, **kwargs):
            self.assertTrue(self.physical.physical_mode())
            self.assertTrue(all(key not in os.environ for key in POLICY))
            if function is not top200.complete_daily_derivatives:
                self.fail(f"D24 chart recovery wanted {function.__name__}: {sys.exception()}")
            operations.append("Top200")
            return {"status": "SAFE_TOP200_INTERCEPT"}

        def check_groups(date):
            self.assertEqual(date, DAY)
            self.assertTrue(self.physical.physical_mode())
            operations.append("groups")
            return {"status": "SAFE_GROUPS_INTERCEPT"}

        for expected in ("PARTIAL_WITH_ROWS", "READY"):
            def validated(receipt, date, **bindings):
                status = original_validate(receipt, date, **bindings)
                self.assertEqual(status, "PARTIAL_WITH_ROWS")
                return expected

            with self.subTest(expected=expected), \
                    patch.object(self.registry, "shanghai_now", return_value=moment(DAY)), \
                    patch.object(self.executor, "_research_panel_daily", side_effect=AssertionError("provider")), \
                    patch.object(receipts, "validate_a_receipt", side_effect=validated), \
                    patch.object(governance, "governed_product", side_effect=check_only), \
                    patch.object(groups, "complete_daily_formula_groups", side_effect=check_groups):
                try:
                    result = self.executor._run_a_daily(request(DAY))
                except self.registry.WorkloadExecutionError as error:
                    self.fail(error.result.get("original_chart_leaf") or error.result)
                self.assertEqual(result["lane_status"], expected)
                self.assertTrue(result["migration_reuse"])
                self.assertFalse(result["provider_invoked"])
                self.assertFalse(result["source_recomputed"])
                self.assertTrue(result["original_chart_leaf"]["reused"])
                self.assertEqual(result["original_chart_leaf"]["numeric_recomputed"], False)
                self.assertEqual(result["row_count"], self.receipt["row_count"])
                self.assertEqual(result["source_receipt_sha256"], digest(self.receipt_path))
        self.assertEqual(operations, ["Top200", "groups", "Top200", "groups"])

    def test_actual_d24_large_dated_receipt_ref(self):
        bound = {}
        receipt, error = self.registry._read_exact_dated_receipt("ops.macos_research_panel_daily", [
            "--date", DAY, "--lane", "A", "--receipt-root", str(self.receipt_path.parent),
        ], receipt_reference=bound)
        self.assertIsNone(error)
        self.assertGreater(self.receipt_path.stat().st_size, 8 * 1024**2)
        self.assertEqual(receipt["status"], "PARTIAL")
        self.assertEqual(bound, {"path": str(self.receipt_path), "sha256": digest(self.receipt_path)})

    def test_actual_d24_pair_and_original_qfq_receipts(self):
        from ops import research_panel_qfq as qfq
        from ops import research_storage_pair as pair

        formula = self.receipt["formula"]
        qfq_result = json.loads((Path(formula["run_dir"]) / "stage_status.json").read_bytes())
        paths = {role: Path(self.receipt[role]) for role in ("selector", "backtest")}
        current = json.loads((Path(os.environ["V4_STORAGE_PAIR_ROOT"]) / "current.json").read_bytes())["current"]
        manifest = json.loads(Path(current["path"]).read_bytes())
        dispatch = {"dispatcher_pid": os.getppid()}
        provider = {
            "schema": "v4.natural_source_provider_invocation.v1", "status": "PASS", "exit_code": 0,
            "target_date": DAY, "provider_task_name": "tdxpy_daily_vipdoc_sync_v1",
            "provider_run_id": DAY + "-" + "b" * 16 + "-1",
            "dispatch": dispatch, "parent_dispatcher_pid": os.getppid(),
            "producer_process": {"pid": os.getpid(), "started": "TEST"},
        }

        def no_compute(**kwargs):
            self.assertTrue(kwargs["refresh_inputs"])
            self.assertEqual(kwargs["storage_layout"], "arrow_blocks_v1")
            self.assertTrue(kwargs["publish"])
            self.assertEqual(kwargs["target"], int(DAY))
            self.assertTrue(self.physical.physical_mode())
            return dict(qfq_result)

        with self.physical.scheduled_storage(), patch.object(qfq, "run_daily_rebuild", side_effect=no_compute), \
                patch.object(qfq, "publication_lock", return_value=nullcontext()) as locked, \
                patch.object(pair, "publish_configured", return_value=manifest) as publish, \
                patch.object(self.authority, "_natural_dispatch_context", return_value=(dispatch, None)), \
                patch.dict(os.environ, {self.authority._NATURAL_PROVIDER_INVOCATION_ENV: json.dumps(provider)}):
            v = self.environment
            result = self.authority.run_windows_a_formula_authority(
                v["V4_RESEARCH_PANEL_A_FORMULA_SCRIPT"], tdx_root=v["V4_RESEARCH_PANEL_A_TDX_ROOT"],
                data_root=self.data, selector_pointer=v["V4_RESEARCH_PANEL_A_SELECTOR_POINTER"],
                backtest_pointer=v["V4_RESEARCH_PANEL_A_BACKTEST_POINTER"],
                selector_seed=None, backtest_seed=None, contract_csv=v["V4_RESEARCH_PANEL_A_CONTRACT_CSV"],
                canonical_formula_path=v["V4_RESEARCH_PANEL_A_CANONICAL_FORMULA"],
                return_root=v["V4_RESEARCH_PANEL_A_RETURN_ROOT"], target_date=DAY,
            )
            locked.assert_called_once_with(self.data)
            publish.assert_called_once_with(paths)
            self.assertEqual(result["paired_publication"], current)
            self.assertEqual(result["natural_execution"]["pair"], current)
            readback = {
                **self.receipt, "formula": result, "sync": {
                    **self.receipt["sync"], "provider_invocation": provider, "natural_dispatch_context": dispatch,
                },
            }
            self.assertTrue(self.review._verified_natural_receipt(readback, dispatch, DAY))
            result["natural_execution"]["ready_receipt"]["sha256"] = "0" * 64
            self.assertFalse(self.review._verified_natural_receipt(readback, dispatch, DAY))


if __name__ == "__main__":
    unittest.main()
