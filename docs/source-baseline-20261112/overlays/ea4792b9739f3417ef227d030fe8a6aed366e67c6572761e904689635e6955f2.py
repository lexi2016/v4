from pathlib import Path

import pytest


def test_real_create_app_accepts_runtime_binding_arguments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.v4_api import app as api_module

    class UnexpectedStageRunner:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("shared Stage Center mode must not instantiate StageRunner")

    monkeypatch.setattr(api_module, "StageRunner", UnexpectedStageRunner)

    app = api_module.create_app(
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared",
        ledger_root=tmp_path / "dispatcher",
        stage_center_selection_root=tmp_path / "selection",
    )

    assert app.title == "V4"

    # FastAPI's mounted/include-router wrapper does not flatten nested paths
    # into ``app.routes`` in the runtime version used by the release.  Probe
    # the same router factory that create_app registers so this canary tests
    # the actual graph route contract rather than an implementation detail of
    # the wrapper object.
    graph_router = api_module.create_runtime_graph_router(tmp_path / "graph")
    graph_paths = {getattr(route, "path", "") for route in graph_router.routes}
    assert "/api/v4/runtime-graph/snapshot" in graph_paths
