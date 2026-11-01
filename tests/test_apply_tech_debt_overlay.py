from __future__ import annotations

from pathlib import Path

import pytest

from ops.apply_tech_debt_overlay import CONSTANTS, NESTED, OverlayError, _rewrite_app

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
