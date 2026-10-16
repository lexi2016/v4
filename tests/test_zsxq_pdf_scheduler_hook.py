import json
from pathlib import Path
from types import SimpleNamespace


def _pdf_hook():
    try:
        from infrastructure.scheduling.executor_registry_research import _zsxq_pdf_post_success
    except ImportError:
        from infrastructure.scheduling._executor_registry_parts.research_jobs import _zsxq_pdf_post_success
    return _zsxq_pdf_post_success


def test_pdf_hook_runs_only_after_main_success_and_preserves_hourly_status(tmp_path: Path):
    source_status = tmp_path / "research_module/runtime_outputs/zsxq_hourly/20261016/1000"
    source_status.mkdir(parents=True)
    (source_status / "v35_zsxq_hourly_status_20261016_1000.json").write_text(
        json.dumps(
            {
                "trade_date": "20261016",
                "slot": "1000",
                "latest_run_id": "20261016_100000_000000000001",
                "fetch_ok": True,
                "status": "READY",
            }
        ),
        encoding="utf-8",
    )

    calls = []

    class Registry:
        data_root = tmp_path

        def _run(self, module, args, *, timeout_seconds=None):
            calls.append((module, args, timeout_seconds))
            return {
                "status": "SUCCEEDED",
                "stdout": json.dumps(
                    {
                        "schema_version": "v4.zsxq_pdf_batch_receipt.v1",
                        "status": "PARTIAL",
                        "processed_document_count": 0,
                        "pdf_reference_count": 3,
                        "done_total": 2,
                        "partial_total": 0,
                        "failed_total": 0,
                        "pending_total": 1,
                    }
                ),
            }

    request = SimpleNamespace(business_date="20261016", slot="1000")
    hook = _pdf_hook()
    failed_main = {"status": "FAILED", "exit_code": 2}
    assert hook(Registry(), request, failed_main) is failed_main
    assert calls == []

    hourly_result = {"status": "SUCCEEDED", "exit_code": 0}
    result = hook(Registry(), request, hourly_result)
    assert result["status"] == "SUCCEEDED"
    assert result["exit_code"] == 0
    assert result["pdf_ingestion"]["status"] == "PARTIAL"
    assert result["pdf_ingestion"]["pending_total"] == 1
    assert result["pdf_ingestion"]["queued_document_count"] == 3
    assert result["pdf_ingestion"]["mode"] == "ENQUEUE_ONLY_BACKGROUND_DRAIN"
    assert result["pdf_ingestion"]["production_allowed"] is False
    assert calls[0][0] == "ops.run_zsxq_hourly_delta"
    assert "--pdf-only" in calls[0][1]
    assert "--pdf-enqueue-only" in calls[0][1]
    assert calls[0][1][calls[0][1].index("--pdf-limit") + 1] == "1"
    assert calls[0][1][calls[0][1].index("--pdf-time-budget-seconds") + 1] == "180"
    assert calls[0][2] == 290
