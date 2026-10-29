"""Serve a temporary loopback-only dashboard/API demo over an existing D29 product.

This harness mounts existing V4 read-only routers and panel assets. Explicit
roots can bind recovered static files and an existing report index; defaults
retain project assets and an empty temporary report root. No index is built.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import socket
import sys
import tempfile

PROJECT_ROOT = Path(__file__).resolve().parents[3]
HANDOFF_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from apps.api.v4_api.research_lane_router import create_research_lane_router
from apps.api.v4_api.research_router import create_research_router


def create_demo_app(source_root: Path, runtime_root: Path, *, panel_root: Path | None = None,
                    report_data_root: Path | None = None) -> FastAPI:
    app = FastAPI(title="Isolated D29 dashboard demo", docs_url=None, redoc_url=None)
    app.include_router(
        create_research_router(
            runtime_root / "consumer",
            shared_data_root=source_root,
        )
    )
    app.include_router(
        create_research_lane_router(
            report_data_root if report_data_root is not None else runtime_root / "lane",
            a_share_daily_root=source_root,
        )
    )
    app.mount(
        "/research-panel",
        StaticFiles(directory=panel_root if panel_root is not None else PROJECT_ROOT / "research-panel"),
        name="research-panel",
    )

    @app.get("/dashboard-demo")
    def dashboard_demo() -> FileResponse:
        return FileResponse(HANDOFF_ROOT / "daily-dashboard-demo.html")

    return app


def _existing_directory(value: str) -> Path:
    try:
        path = Path(value).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("not a directory")
        return path
    except (OSError, ValueError) as error:
        raise argparse.ArgumentTypeError(f"existing directory required: {value}") from error


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily-product-root", required=True, type=Path)
    parser.add_argument("--panel-root", type=_existing_directory, help="Read-only static asset directory")
    parser.add_argument("--report-data-root", type=_existing_directory, help="Read-only existing report data directory")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    source_root = args.daily_product_root.expanduser().resolve(strict=True)
    if not (source_root / "daily_products" / "a_share" / "index.json").is_file():
        parser.error("--daily-product-root must contain daily_products/a_share/index.json")
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")

    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", args.port))
        port = reservation.getsockname()[1]

    with tempfile.TemporaryDirectory(prefix="v4-d29-dashboard-demo-") as temporary:
        app = create_demo_app(source_root, Path(temporary), panel_root=args.panel_root, report_data_root=args.report_data_root)
        print("Loopback-only isolated demo: http://127.0.0.1:" + str(port) + "/dashboard-demo", flush=True)
        print("Read-only panel root: " + str(args.panel_root or PROJECT_ROOT / "research-panel"), flush=True)
        print("Read-only report data root: " + str(args.report_data_root or Path(temporary) / "lane"), flush=True)
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
        )


if __name__ == "__main__":
    main()

