from __future__ import annotations

import ast

from pathlib import Path

import pytest

from ops.apply_tech_debt_overlay import (
    CONSTANTS,
    HV_NAMES,
    HV_REWIRE,
    RT_ROUTES,
    NESTED,
    OverlayError,
    _rewrite_app,
    _split_hk_verify,
    _split_routes,
    _split_stage_workbench,
)

APP = '''\
from apps.api.v4_api.baimao_router import create_baimao_router
from pathlib import Path

{constants}
_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE = {("20261016", "STAGE_0925"): {}}
for _row in ():
    _APPROVED_EXACT_STAGE_BACKFILLS[("a", "b", "c", "d")] = {}
_APPROVED_EXACT_STAGE_BACKFILLS[("e", "f", "g", "h")] = {}


def create_app():
    store = object()
    configured_pool_source = None
    resolved_pool_source = Path("/tmp")
    configured_morning_news_root = None
    configured_selection_root = stage_center_selection_root
    _hk_morning_history_observation = lambda *a, **k: {}

    def _stage_projection_status(ctx, part):
        return part

    def _legacy_hk_consumer_rows_match(ctx, rows, bound):
        return rows == bound

    def _legacy_hk_pit_observation(ctx, payload):
        return _legacy_hk_consumer_rows_match(ctx, [], [])

    def _hk_morning_selection_recovery_observation(ctx, payload):
        return ctx.morning_selection_recovery_bindings

    def _hk_display_mode(ctx, markets, rows, reasons, market, date):
        return ("X", reasons)

    def project_shared_selection(ctx, payload, limit=50, *, ordinary_hk_display=False):
        return _hk_display_mode(ctx, {}, [], [], "A", "20261001")

    def route():
        return project_shared_selection({}, 50)

    return route
'''


def _write_app(tmp_path: Path) -> Path:
    constants = "\n".join(f"{name} = {{}}" for name in CONSTANTS)
    app = tmp_path / "app.py"
    app.write_text(APP.replace("{constants}", constants), encoding="utf-8")
    return app


def test_overlay_replaces_constants_and_removes_nested_functions(tmp_path: Path):
    app = _write_app(tmp_path)
    _rewrite_app(app)
    text = app.read_text(encoding="utf-8")

    for name in CONSTANTS:
        assert f"{name} = _evidence_" in text, name
    for name in NESTED:
        assert f"def {name}(" not in text, name
    assert "for _row in ():" not in text
    assert '_APPROVED_EXACT_STAGE_BACKFILLS[("e"' not in text


def test_overlay_inserts_context_after_the_anchor(tmp_path: Path):
    """Regression: the context block must follow the anchor, not replace it."""
    app = _write_app(tmp_path)
    _rewrite_app(app)
    lines = app.read_text(encoding="utf-8").splitlines()
    anchor = lines.index("    configured_selection_root = stage_center_selection_root")
    assert lines[anchor + 1].strip() == "projection_ctx = ProjectionContext("
    assert lines[anchor + 2].strip() == "store=store,"
    assert "morning_selection_recovery_bindings=_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE," in [
        line.strip() for line in lines
    ]


def test_overlay_passes_context_to_the_projection(tmp_path: Path):
    app = _write_app(tmp_path)
    _rewrite_app(app)
    text = app.read_text(encoding="utf-8")
    assert "project_shared_selection(projection_ctx, {}, 50)" in text


def test_overlay_fails_when_an_anchor_is_missing(tmp_path: Path):
    app = tmp_path / "app.py"
    app.write_text("def create_app():\n    pass\n", encoding="utf-8")
    with pytest.raises(OverlayError):
        _rewrite_app(app)


WORKBENCH_APP = '''\
from apps.api.v4_api.projection import ProjectionContext, project_shared_selection


def create_app():
    projection_ctx = ProjectionContext()
    configured_selection_root = None
    approved_research_reader = None
    shared_selection_consumer = None
    stage_runner = None

    @app.get("/api/v4/workbench/stage")
    def stage_workbench(date=None, stage="S", limit=10, market=None, backfill_run_id=None):
        selected = date or "20261001"
        # The optional release-owned binding handles only its exact approved run.
        morning_binding = _HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE.get(
            (selected, stage)
        )
        if market is not None or backfill_run_id is not None:
            if market is None or backfill_run_id is None:
                raise HTTPException(status_code=422, detail="both")
            binding = _APPROVED_EXACT_STAGE_BACKFILLS.get((selected, stage, market, backfill_run_id))
            return project_shared_selection(projection_ctx, binding, limit)
        if shared_selection_consumer is not None:
            payload = shared_selection_consumer.get(selected, stage)
            payload = _quarantine_known_hk_auction_pool_mismatch(payload, selected, stage)
            override = _read_r9_exact_target_hk_override(payload, selected, stage, limit)
            if override is not None:
                return project_shared_selection(projection_ctx, override, limit)
            exact_hk = stage_workbench(
                date=selected,
                stage=stage,
                limit=limit,
                market="HK_CONNECT",
                backfill_run_id=day24_run_id,
            )
            payload = {"exact": exact_hk}
            return project_shared_selection(projection_ctx, payload, limit)
        return stage_runner.read_workbench(selected, stage, limit)
'''


def _write_workbench_app(tmp_path: Path) -> Path:
    app = tmp_path / "app.py"
    app.write_text(WORKBENCH_APP, encoding="utf-8")
    return app


def test_split_moves_the_three_branches_and_delegates(tmp_path: Path):
    app = _write_workbench_app(tmp_path)
    module_path = tmp_path / "stage_workbench.py"
    receipt = _split_stage_workbench(app, None, module_path)

    text = app.read_text(encoding="utf-8")
    assert "morning_binding = " not in text
    assert "return read_stage_workbench(\n            stage_workbench_ctx" in text
    assert "return stage_runner.read_workbench" not in text
    lines = text.splitlines()
    route = lines.index('    @app.get("/api/v4/workbench/stage")')
    assert lines[route - 1] == "    )"
    window = lines[route - 15:route]
    assert "    stage_workbench_ctx = StageWorkbenchContext(" in window
    assert window[0] == "    stage_workbench_ctx = StageWorkbenchContext("
    assert "from apps.api.v4_api.stage_workbench import StageWorkbenchContext, read_stage_workbench" in lines

    module = module_path.read_text(encoding="utf-8")
    compile(module, str(module_path), "exec")
    for name in ("read_stage_workbench", "_research_binding_response",
                 "_exact_backfill_response", "_ordinary_selection_response"):
        assert f"def {name}(" in module
    assert "ctx.projection" in module
    assert "ctx.shared_selection_consumer is not None" in module
    assert "exact_hk = read_stage_workbench(\n" in module
    assert "exact_hk = stage_workbench(" not in module
    assert receipt["module_lines"] == len(module.splitlines())


def test_split_rejects_a_drifted_reviewed_module(tmp_path: Path):
    app = _write_workbench_app(tmp_path)
    reviewed = tmp_path / "reviewed.py"
    reviewed.write_text("# not the generated module\n", encoding="utf-8")
    with pytest.raises(OverlayError, match="differs from the reviewed file"):
        _split_stage_workbench(app, reviewed, tmp_path / "out.py")


def test_split_requires_the_recursive_call(tmp_path: Path):
    app = _write_workbench_app(tmp_path)
    text = app.read_text(encoding="utf-8")
    app.write_text(text.replace(
        '''            exact_hk = stage_workbench(
                date=selected,
                stage=stage,
                limit=limit,
                market="HK_CONNECT",
                backfill_run_id=day24_run_id,
            )
''', ""), encoding="utf-8")
    with pytest.raises(OverlayError, match="recursive self-call"):
        _split_stage_workbench(app, None, tmp_path / "out.py")


HK_VERIFY_APP = '''\
from typing import Any, Mapping

from apps.api.v4_api.stage_workbench import StageWorkbenchContext, read_stage_workbench

_HK_MORNING_SELECTION_RECOVERY_BINDING_BY_DATE_STAGE = {}
_HK_R8_BINDING_BY_DATE_STAGE = {}
_HK_R8_POOL_EVIDENCE = {}
_HK_R9_BINDING_BY_DATE_STAGE = {}
_HK_R9_LEGACY_STALE_LANE_IDENTITIES = {}
_HK_R9_LEGACY_STALE_POOL_CONTRACTS = {}
_HK_R9_POOL_EVIDENCE = {}


def create_app():
    configured_selection_root = None
    shared_selection_consumer = None
    approved_research_reader = None
    stage_runner = None

    def _quarantine_known_hk_auction_pool_mismatch(
        payload: dict, trade_date: str, stage_id: str
    ) -> dict:
        if shared_selection_consumer is None:
            return payload
        return payload

    def _read_exact_target_hk_override(
        payload: dict,
        trade_date: str,
        stage_id: str,
        limit: int,
        binding: Mapping[str, Any],
        *,
        source_label: str,
    ) -> dict:
        exact = stage_workbench(
            date=trade_date,
            stage=stage_id,
            limit=limit,
            market="HK_CONNECT",
            backfill_run_id=binding["backfill_run_id"],
        )
        return {"exact": exact, "pool": _HK_R8_POOL_EVIDENCE, "label": source_label}

    def _read_r8_exact_target_hk_override(payload: dict, trade_date: str, stage_id: str, limit: int):
        return _read_exact_target_hk_override(payload, trade_date, stage_id, limit, {}, source_label="r8")

    def _read_r9_exact_target_hk_override(payload: dict, trade_date: str, stage_id: str, limit: int):
        return _read_exact_target_hk_override(payload, trade_date, stage_id, limit, {}, source_label="r9")

    def _read_hk_morning_selection_recovery_override(payload: dict, trade_date: str, stage_id: str, limit: int):
        if configured_selection_root is None:
            return None
        return {"pool": _HK_R9_POOL_EVIDENCE}

    stage_workbench_ctx = StageWorkbenchContext(
        quarantine_hk_auction_pool_mismatch=_quarantine_known_hk_auction_pool_mismatch,
        hk_morning_override=_read_hk_morning_selection_recovery_override,
        r8_override=_read_r8_exact_target_hk_override,
        r9_override=_read_r9_exact_target_hk_override,
    )

    @app.get("/api/v4/workbench/stage")
    def stage_workbench(date=None, stage="S", limit=10, market=None, backfill_run_id=None):
        selected = date or "20261001"
        return read_stage_workbench(
            stage_workbench_ctx, selected, stage, limit, market, backfill_run_id
        )

    @app.post("/api/v4/workbench/stage/ensure")
    def stage_workbench_ensure():
        return {}
'''


def _write_hk_app(tmp_path: Path) -> Path:
    app = tmp_path / "app.py"
    app.write_text(HK_VERIFY_APP, encoding="utf-8")
    return app


def test_hk_verify_moves_the_readers_and_rewires_the_context(tmp_path: Path):
    app = _write_hk_app(tmp_path)
    module_path = tmp_path / "hk_verify.py"
    receipt = _split_hk_verify(app, None, module_path)

    text = app.read_text(encoding="utf-8")
    for old, _ in HV_NAMES:
        assert f"def {old}(" not in text
        assert f"{old}," not in text
    assert "    hk_verify_ctx = HkVerifyContext(" in text
    assert "from functools import partial" in text
    assert text.count("partial(") == len(HV_REWIRE)
    assert "from apps.api.v4_api.hk_verify import (" in text
    lines = text.splitlines()
    route = lines.index('    @app.get("/api/v4/workbench/stage")')
    assert any(line == "    hk_verify_ctx = HkVerifyContext(" for line in lines[route:])

    module = module_path.read_text(encoding="utf-8")
    compile(module, str(module_path), "exec")
    parsed = ast.parse(module)
    defs = {node.name: node for node in parsed.body if isinstance(node, ast.FunctionDef)}
    for _, new in HV_NAMES:
        assert new in defs, new
        first = defs[new].args.args[0]
        assert first.arg == "ctx" and ast.unparse(first.annotation) == "HkVerifyContext", new
    assert "read_exact_target_hk_override(ctx, payload" in module
    assert "ctx.read_workbench(" in module
    assert "ctx.shared_selection_consumer is None" in module
    assert "ctx.configured_selection_root is None" in module
    assert receipt["hk_module_lines"] == len(module.splitlines())


def test_hk_verify_rejects_a_drifted_reviewed_module(tmp_path: Path):
    app = _write_hk_app(tmp_path)
    reviewed = tmp_path / "reviewed.py"
    reviewed.write_text("# drifted\n", encoding="utf-8")
    with pytest.raises(OverlayError, match="differs from the reviewed file"):
        _split_hk_verify(app, reviewed, tmp_path / "out.py")


def test_hk_verify_requires_complete_rewiring(tmp_path: Path):
    app = _write_hk_app(tmp_path)
    text = app.read_text(encoding="utf-8")
    app.write_text(text.replace("        r9_override=_read_r9_exact_target_hk_override,\n", ""), encoding="utf-8")
    with pytest.raises(OverlayError, match="rewiring incomplete"):
        _split_hk_verify(app, None, tmp_path / "out.py")


ROUTES_HEAD = '''\
from apps.api.v4_api.stage_workbench import StageWorkbenchContext, read_stage_workbench

_TRIVIAL = None


def create_app():
    projection_ctx = object()
    review_store = object()
    research_source = object()
    shared_selection_consumer = None
    stage_runner = None

    def shared_selection_unconfigured(trade_date: str, stage_id: str) -> dict:
        return {"cannot_confirm": ["SHARED_STAGE_CENTER_NOT_CONFIGURED"]}

    def _catalog() -> dict:
        return {"default_date": "20261001"}

    @app.get("/healthz")
    def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/api/v4/stage-center/selection")
    def shared_stage_selection(date=None, stage="S"):
        selected = _strict_date(date) if date is not None else _catalog()["default_date"]
        if shared_selection_consumer is None:
            return shared_selection_unconfigured(selected, stage)
        return projection_ctx
'''

ROUTES_TAIL = '''
    stage_workbench_ctx = StageWorkbenchContext(
        approved_research_reader=None,
    )

    @app.get("/api/v4/workbench/stage")
    def stage_workbench(date=None, stage="S", limit=10, market=None, backfill_run_id=None):
        return read_stage_workbench(
            stage_workbench_ctx, date, stage, limit, market, backfill_run_id
        )
'''


def _routes_app_text() -> str:
    trivial = ""
    for name in RT_ROUTES:
        if name in {"healthz", "shared_stage_selection"}:
            continue
        trivial += '\n    @app.post("/x/' + name + '")\n    def ' + name + '(date=None):\n'
        trivial += '        return {"route": "' + name + '"}\n'
    return ROUTES_HEAD + trivial + ROUTES_TAIL


def _write_routes_app(tmp_path: Path) -> Path:
    app = tmp_path / "app.py"
    app.write_text(_routes_app_text(), encoding="utf-8")
    return app


def test_routes_moves_the_decorators_and_wires_the_context(tmp_path: Path):
    app = _write_routes_app(tmp_path)
    module_path = tmp_path / "routes.py"
    receipt = _split_routes(app, None, module_path)

    text = app.read_text(encoding="utf-8")
    for name in RT_ROUTES:
        assert f"def {name}(" not in text, name
    assert '    @app.get("/healthz")' not in text
    assert "    route_ctx = RouteContext(" in text
    assert "    register_routes(route_ctx)" in text
    assert "from apps.api.v4_api.routes import RouteContext, register_routes" in text
    assert '    @app.get("/api/v4/workbench/stage")' in text
    assert "def stage_workbench(" in text

    module = module_path.read_text(encoding="utf-8")
    compile(module, str(module_path), "exec")
    assert "def unconfigured_selection(" in module
    assert "def shared_selection_unconfigured(" not in module
    assert "def register_routes(ctx: RouteContext) -> None:" in module
    assert "    app = ctx.app" in module
    assert '    @app.get("/healthz")' in module
    assert "ctx.catalog()" in module
    assert "ctx.strict_date(" in module
    assert "ctx.shared_selection_consumer is None" in module
    assert "unconfigured_selection(selected, stage)" in module
    assert receipt["routes_module_lines"] == len(module.splitlines())


def test_routes_rejects_a_drifted_reviewed_module(tmp_path: Path):
    app = _write_routes_app(tmp_path)
    reviewed = tmp_path / "reviewed.py"
    reviewed.write_text("# drifted\n", encoding="utf-8")
    with pytest.raises(OverlayError, match="differs from the reviewed file"):
        _split_routes(app, reviewed, tmp_path / "out.py")


def test_routes_requires_every_anchor(tmp_path: Path):
    app = tmp_path / "app.py"
    app.write_text("def create_app():\n    pass\n", encoding="utf-8")
    with pytest.raises(OverlayError, match="route anchors missing"):
        _split_routes(app, None, tmp_path / "out.py")
