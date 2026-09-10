from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _set_pointed_artifact_dates(pointer: Path, dates: list[str]) -> None:
    artifact = Path(pointer.read_text(encoding="utf-8").strip())
    _write_json(artifact, {"rows": [{"trade_date": value} for value in dates]})


def _fixtures(tmp_path: Path) -> dict[str, Path]:
    date = "20260821"
    producer = tmp_path / "producer-receipts"
    selector_artifact = tmp_path / "selector-20260821.json"
    backtest_artifact = tmp_path / "backtest-20260821.json"
    selector_pointer = tmp_path / "selector.current"
    backtest_pointer = tmp_path / "backtest.current"
    _write_json(selector_artifact, {"trade_date": date, "rows": [{"symbol": "A.600000"}]})
    _write_json(backtest_artifact, {"trade_date": date, "rows": [{"symbol": "A.600000"}]})
    selector_pointer.write_text(str(selector_artifact), encoding="utf-8")
    backtest_pointer.write_text(str(backtest_artifact), encoding="utf-8")
    _write_json(
        producer / f"a-{date}.json",
        {
            "schema_version": "v3.macos.research_panel_receipt.v1",
            "lane": "A",
            "target_date": date,
            "status": "READY",
            "row_count": 58,
            "coverage_rate": 1.0,
            "sha256": "a" * 64,
            "sync": {
                "authority_status": "REBUILD_REQUIRED",
                "quarantined_rebuild_symbols": 2,
                "rebuild_candidates_promoted": False,
            },
            **SAFETY,
        },
    )
    _write_json(
        producer / f"hk-{date}.json",
        {
            "schema_version": "v3.macos.research_panel_receipt.v1",
            "lane": "HK",
            "target_date": date,
            "status": "READY",
            "row_count": 100,
            "coverage_rate": 1.0,
            "sha256": "b" * 64,
            **SAFETY,
        },
    )
    close_review = tmp_path / "close-review.json"
    _write_json(
        close_review,
        {
            "schema_version": "v3_5.close_review.v1",
            "trade_date": date,
            "status": "MODEL_REVIEW_READY",
            **SAFETY,
        },
    )
    close_receipt = tmp_path / "close-review.receipt.json"
    _write_json(
        close_receipt,
        {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": close_review.name,
            "source_sha256": _sha(close_review),
            "trade_date": date,
        },
    )
    return {
        "date": Path(date),
        "producer": producer,
        "selector_pointer": selector_pointer,
        "backtest_pointer": backtest_pointer,
        "close_review": close_review,
        "close_receipt": close_receipt,
    }


def test_publisher_projects_exact_receipts_without_payload_copy(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    result = publish_research_panel_status(
        business_date="20260821",
        data_root=tmp_path / "data",
        producer_receipt_root=fixtures["producer"],
        selector_pointer=fixtures["selector_pointer"],
        backtest_pointer=fixtures["backtest_pointer"],
        close_review_path=fixtures["close_review"],
        close_review_receipt_path=fixtures["close_receipt"],
    )

    assert result["business_date"] == "20260821"
    assert result["lanes"]["A"]["status"] == "PARTIAL"
    assert "REBUILD_REQUIRED" in result["lanes"]["A"]["reason"]
    assert result["lanes"]["HK"]["status"] == "READY"
    for lane in ("ashare_research_panel", "hkconnect_research_panel"):
        path = tmp_path / "data" / "runtime_graph" / "evidence" / "research_panel_status" / "20260821" / f"{lane}.json"
        assert path.is_file()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["business_date"] == "20260821"
        assert "rows" not in payload
        assert all(payload[name] is False for name in SAFETY)
    assert not list((tmp_path / "data").rglob("*.tmp"))


def test_publisher_rejects_stale_hk_close_review_as_cannot_confirm(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    stale = json.loads(fixtures["close_review"].read_text(encoding="utf-8"))
    stale["trade_date"] = "20260820"
    _write_json(fixtures["close_review"], stale)
    result = publish_research_panel_status(
        business_date="20260821",
        data_root=tmp_path / "data",
        producer_receipt_root=fixtures["producer"],
        selector_pointer=fixtures["selector_pointer"],
        backtest_pointer=fixtures["backtest_pointer"],
        close_review_path=fixtures["close_review"],
        close_review_receipt_path=fixtures["close_receipt"],
    )

    assert result["lanes"]["HK"]["status"] == "CANNOT_CONFIRM"
    assert "DATE" in result["lanes"]["HK"]["reason"]


def test_publisher_accepts_historical_pointer_dates_through_target(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    for pointer in (fixtures["selector_pointer"], fixtures["backtest_pointer"]):
        _set_pointed_artifact_dates(pointer, ["20190101", "20200102", "20260821"])

    result = publish_research_panel_status(
        business_date="20260821",
        data_root=tmp_path / "data",
        producer_receipt_root=fixtures["producer"],
        selector_pointer=fixtures["selector_pointer"],
        backtest_pointer=fixtures["backtest_pointer"],
        close_review_path=fixtures["close_review"],
        close_review_receipt_path=fixtures["close_receipt"],
    )

    assert result["lanes"]["A"]["status"] == "PARTIAL"
    assert "REBUILD_REQUIRED" in result["lanes"]["A"]["reason"]


@pytest.mark.parametrize(
    ("dates", "reason"),
    [
        (["20190101", "20260820"], "POINTER_DATE_BEFORE_TARGET"),
        (["20190101", "20260822"], "POINTER_DATE_AFTER_TARGET"),
    ],
)
def test_publisher_rejects_pointer_without_exact_target_max(
    tmp_path: Path, dates: list[str], reason: str
) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    for pointer in (fixtures["selector_pointer"], fixtures["backtest_pointer"]):
        _set_pointed_artifact_dates(pointer, dates)

    result = publish_research_panel_status(
        business_date="20260821",
        data_root=tmp_path / "data",
        producer_receipt_root=fixtures["producer"],
        selector_pointer=fixtures["selector_pointer"],
        backtest_pointer=fixtures["backtest_pointer"],
        close_review_path=fixtures["close_review"],
        close_review_receipt_path=fixtures["close_receipt"],
    )

    assert result["lanes"]["A"]["status"] == "CANNOT_CONFIRM"
    assert reason in result["lanes"]["A"]["reason"]
    assert "count=2" in result["lanes"]["A"]["reason"]


def test_runtime_graph_bindings_declare_only_the_two_research_panel_receipts() -> None:
    from infrastructure.runtime_graph.bindings import load_v35_evidence_bindings

    bindings = load_v35_evidence_bindings()
    for node_id, filename in (
        ("ashare_research_panel", "ashare_research_panel.json"),
        ("hkconnect_research_panel", "hkconnect_research_panel.json"),
    ):
        binding = bindings[node_id]
        assert binding["expected_outputs"] == [
            f"{{data_root}}/runtime_graph/evidence/research_panel_status/{{date}}/{filename}"
        ]
        assert {source["kind"] for source in binding["status_sources"]} == {"v35_artifact"}
        assert binding["status_sources"][0]["path"].endswith(f"/{filename}")
        assert all("page_receipt" not in json.dumps(binding) for _ in (0,))


def test_runtime_graph_service_and_api_router_initialize_with_panel_bindings(tmp_path: Path) -> None:
    from apps.api.v35_api.runtime_graph_router import create_runtime_graph_router
    from infrastructure.runtime_graph.service import RuntimeGraphService

    service = RuntimeGraphService(tmp_path / "service-data")
    assert {"ashare_research_panel", "hkconnect_research_panel"}.issubset(
        service.allowed_node_ids
    )

    router = create_runtime_graph_router(tmp_path / "api-data")
    assert {getattr(route, "path", "") for route in router.routes} >= {
        "/api/v3/runtime-graph/snapshot",
        "/api/v3/runtime-graph/status",
    }


def test_collector_entrypoints_are_posix_and_bound_to_8873() -> None:
    import inspect

    from infrastructure.runtime_graph.http_client import validate_api_base
    from ops import collect_runtime_graph as collector
    from ops import run_v3_5_runtime_graph_collector as runner

    assert collector.DEFAULT_API_BASE == "http://127.0.0.1:8873"
    assert runner.DEFAULT_API_BASE == "http://127.0.0.1:8873"
    assert validate_api_base(collector.DEFAULT_API_BASE) == collector.DEFAULT_API_BASE
    with pytest.raises(ValueError, match="API_BASE_UNSAFE"):
        validate_api_base("http://127.0.0.1:8872")
    command = runner._child_command(
        business_date="20260821",
        data_root=Path("/tmp/v35-runtime-data"),
        api_base=runner.DEFAULT_API_BASE,
    )
    assert runner.DEFAULT_API_BASE in command
    assert "shell=True" not in inspect.getsource(runner)
    assert "8872" not in Path(collector.__file__).read_text(encoding="utf-8")
    assert "8872" not in Path(runner.__file__).read_text(encoding="utf-8")
