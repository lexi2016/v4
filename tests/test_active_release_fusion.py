from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_frontend_keeps_active_release_runtime_and_timeline_surface() -> None:
    app = (ROOT / "apps/web/src/App.vue").read_text()
    task_view = (ROOT / "apps/web/src/views/TaskStatusView.vue").read_text()

    # The active release owns the 19-node page surface and runtime/task
    # timeline consumer.  A date-only branch must not replace that surface.
    assert 'import { loadTaskStatus } from "./api/runtime";' in app
    assert 'import type { TimelineNodeStatus } from "./contracts/runtime";' in app
    assert 'position: 19' in app
    assert "loadTimelineStatus" in app
    assert "图谱待确认任务" in task_view


def test_api_and_scheduler_fusion_keep_active_runtime_contracts() -> None:
    api = (ROOT / "apps/api/v35_api/app.py").read_text()
    dispatcher = (ROOT / "infrastructure/scheduling/dispatcher.py").read_text()
    runner = (ROOT / "ops/run_dispatcher.py").read_text()

    assert "shared_data_root" in api
    assert "stage_center_selection_root" in api
    assert "create_runtime_graph_router" in api
    assert "ledger_root" in api
    assert "failure_class" in dispatcher
    assert "retry_after" in dispatcher
    assert "DispatchMode" in runner
