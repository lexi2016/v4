import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

HELPER = Path(__file__).resolve().parents[1] / "docs/handoffs/a_daily_dashboard_closure_20261029/serve_daily_dashboard_demo.py"
spec = importlib.util.spec_from_file_location("isolated_demo_binding_test", HELPER)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class ExplicitDemoReadBindingTests(unittest.TestCase):
    def test_explicit_static_and_report_roots_reach_readers(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            panel, reports = root / "static-overlay", root / "reports"
            panel.mkdir()
            reports.mkdir()
            (panel / "calendar.js").write_text("// existing recovered asset")
            with patch.object(demo, "create_research_router", return_value=APIRouter()) as product_router, \
                 patch.object(demo, "create_research_lane_router", return_value=APIRouter()) as report_router:
                app = demo.create_demo_app(root / "product", root / "runtime", panel_root=panel, report_data_root=reports)
            response = TestClient(app).get("/research-panel/calendar.js")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.text, "// existing recovered asset")
            product_router.assert_called_once_with(root / "runtime/consumer", shared_data_root=root / "product")
            report_router.assert_called_once_with(reports, a_share_daily_root=root / "product")

    def test_default_roots_remain_local_and_temporary(self):
        with tempfile.TemporaryDirectory() as td:
            runtime = Path(td).resolve()
            with patch.object(demo, "create_research_router", return_value=APIRouter()), \
                 patch.object(demo, "create_research_lane_router", return_value=APIRouter()) as report_router:
                app = demo.create_demo_app(runtime / "product", runtime)
            report_router.assert_called_once_with(runtime / "lane", a_share_daily_root=runtime / "product")
            mount = next(route for route in app.routes if getattr(route, "path", None) == "/research-panel")
            self.assertEqual(Path(mount.app.directory), demo.PROJECT_ROOT / "research-panel")

    def test_cli_passes_explicit_existing_roots_without_starting_service(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            source, panel, reports = root / "product", root / "panel", root / "reports"
            index = source / "daily_products/a_share/index.json"
            index.parent.mkdir(parents=True)
            index.write_text("{}")
            panel.mkdir()
            reports.mkdir()
            args = [str(HELPER), "--daily-product-root", str(source), "--panel-root", str(panel),
                    "--report-data-root", str(reports), "--port", "0"]
            with patch.object(demo.sys, "argv", args), patch.object(demo, "create_demo_app", return_value=FastAPI()) as create, \
                 patch.object(demo.uvicorn, "run") as serve:
                demo.main()
            self.assertEqual(create.call_args.kwargs, {"panel_root": panel, "report_data_root": reports})
            self.assertEqual(serve.call_args.kwargs["host"], "127.0.0.1")
