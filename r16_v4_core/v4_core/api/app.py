"""Pure V4 modular FastAPI app on port 8873 with 4-domain consolidated routers & cold-start SSE replay."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from v4_core.api.routes_research import build_research_router
from v4_core.api.routes_review import build_review_router
from v4_core.api.routes_sse import EventBus, build_sse_router
from v4_core.api.routes_stage import build_stage_router
from v4_core.api.routes_top200 import build_top200_router
from v4_core.api.routes_workbench import build_workbench_router
from v4_core.config import V4Config
from v4_core.storage.db import V4Store

DEFAULT_WORKBENCH_HTML = """<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>V4 Research Workbench</title></head>
<body>
  <h1>V4 Research Workbench</h1>
  <p>Endpoints: /api/v4/research/workbench/days/{source_date}, /top200, /events</p>
</body>
</html>"""


def _read_html_or_default(path: Path | None, fallback: str) -> str:
    if path and path.exists():
        return path.read_text(encoding="utf-8")
    return fallback


def create_app(
    config: V4Config | None = None,
    bus: EventBus | None = None,
    web_dist: Path | None = None,
    research_panel_root: Path | None = None,
) -> FastAPI:
    cfg = config or V4Config.from_env()
    cfg.ensure_dirs()
    store = V4Store(cfg.db_path)
    event_bus = bus or EventBus(store=store)
    if event_bus.store is None:
        event_bus.store = store

    dist_dir = web_dist
    if dist_dir is None and os.environ.get("V4_WEB_DIST"):
        dist_dir = Path(os.environ["V4_WEB_DIST"])
    panel_dir = research_panel_root
    if panel_dir is None and os.environ.get("V4_RESEARCH_PANEL_ROOT"):
        panel_dir = Path(os.environ["V4_RESEARCH_PANEL_ROOT"])

    app = FastAPI(title="V4 Core Research API", version="4.0.0")
    app.state.config = cfg
    app.state.store = store
    app.state.event_bus = event_bus

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "mode": "v4_core_single_root", "version": "4.0.0", "port": cfg.api_port}

    # Three UI entrypoints remain frozen and untouched
    @app.get("/research-panel/workbench.html", response_class=HTMLResponse)
    def research_panel_workbench_page(source_date: str | None = None, observation_date: str | None = None):
        html = _read_html_or_default(panel_dir / "workbench.html" if panel_dir else None, DEFAULT_WORKBENCH_HTML)
        return HTMLResponse(content=html, headers={"Cache-Control": "no-store"})

    @app.get("/", response_class=HTMLResponse)
    def root_page():
        html = _read_html_or_default(
            dist_dir / "index.html" if dist_dir else None,
            "<!doctype html><html><head><meta charset='utf-8'><title>V4</title></head><body><h1>V4 Core 8873</h1></body></html>",
        )
        return HTMLResponse(content=html, headers={"Cache-Control": "no-cache"})

    @app.get("/manager-selection/", response_class=HTMLResponse)
    @app.get("/manager-selection/index.html", response_class=HTMLResponse)
    def manager_selection_page():
        html = _read_html_or_default(
            dist_dir / "manager-selection" / "index.html" if dist_dir else None,
            "<!doctype html><html><head><meta charset='utf-8'><title>经理工作台</title></head><body><h1>经理工作台</h1></body></html>",
        )
        return HTMLResponse(content=html, headers={"Cache-Control": "no-cache"})

    @app.get("/daily-research-command/", response_class=HTMLResponse)
    @app.get("/daily-research-command/index.html", response_class=HTMLResponse)
    def daily_research_command_page():
        html = _read_html_or_default(
            dist_dir / "daily-research-command" / "index.html" if dist_dir else None,
            "<!doctype html><html><head><meta charset='utf-8'><title>全天研究指挥台</title></head><body><h1>全天研究指挥台</h1></body></html>",
        )
        return HTMLResponse(content=html, headers={"Cache-Control": "no-cache"})

    # Four consolidated pure-V4 domain routers (92 kept URLs; pure V4 namespace only; 6 pruned routes excluded)
    app.include_router(build_workbench_router(store))
    app.include_router(build_top200_router(store))
    app.include_router(build_sse_router(event_bus, store=store))
    app.include_router(build_stage_router(store))
    app.include_router(build_research_router(store))
    app.include_router(build_review_router(store))

    if panel_dir and panel_dir.is_dir():
        app.mount("/research-panel", StaticFiles(directory=panel_dir), name="research-panel")

    if dist_dir and (dist_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist_dir / "assets"), name="assets")

    return app
