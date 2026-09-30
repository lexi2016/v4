from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil

from fastapi import FastAPI
from fastapi.testclient import TestClient

from apps.api.v35_api.review_router import (
    _read_hk_prefix_research_asset,
    create_review_router,
)


ASSET_ROOT = Path(
    "/Users/lexi/Documents/Codex/2026-09-12/"
    "referenced-chatgpt-conversation-this-is-an/outputs/ZGE_HISTORY_V4_20260914/fixed_result"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime_binding(asset_root: Path, destination: Path) -> Path:
    manifest = json.loads((asset_root / "source_manifest.json").read_text(encoding="utf-8"))
    files = {
        "receipt": "receipt.json",
        "source_manifest": "source_manifest.json",
        "anonymous_index": "anonymous_prefix_index.csv",
        "results_mapping": "identity/results_mapping.csv",
        "frozen_binding": "identity/frozen_group_binding.json",
        "matched_verdict": "identity/frozen_matched_verdict.csv",
        "field_isolation": "tests/field_isolation.json",
        "future_isolation": "tests/future_isolation.json",
        "past_positive_control": "tests/past_positive_control.json",
        "replay_log": "review/replay_96_reference_review_20260914.log",
        "source_window_replay_log": "review/source_window_replay_review_20260914.log",
        "pair_metrics": "pair_metrics.csv",
        "summary_by_event_type": "summary_by_event_type.csv",
        "terminal_contract_gate": "tests/terminal_contract_gate.json",
        "metrics_contract": "tests/metrics_contract.json",
        "raw_window_reuse": "tests/raw_window_reuse.json",
        "corrected_metric_contract_log": "review/corrected_metric_contract_review_20260914.log",
    }
    binding = {
        "schema_version": "v4.hk_prefix_research.runtime_binding.v1",
        "asset_id": "ZGE_HISTORY_V4_20260914",
        "run_id": manifest["run_id"],
        "root": str(asset_root),
        "files": {
            key: {"path": relative, "sha256": _sha256(asset_root / relative)}
            for key, relative in files.items()
        },
        "source_sha256": manifest["source"]["sha256"],
        "source_manifest_declared_sha256": manifest["source"]["manifest_sha256"],
        "calendar_receipt_sha256": manifest["calendar"]["receipt_sha256"],
        "binding_sha256": manifest["binding"]["sha256"],
        "matched_verdict_sha256": manifest["binding"]["matched_verdict_sha256"],
        "research_only": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    destination.write_text(json.dumps(binding, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return destination


def _panel_app(asset_root: Path, binding: Path) -> FastAPI:
    app = FastAPI()
    app.include_router(
        create_review_router(
            Path("/tmp/hk-prefix-panel-test-data"),
            historical_prefix_root=asset_root,
            historical_prefix_binding_path=binding,
        )
    )
    return app


def test_fixed_history_projection_returns_terminal_coverage_surface_without_old_rates(tmp_path) -> None:
    if not ASSET_ROOT.is_dir():
        import pytest

        pytest.skip("fixed ZGE history asset is not present in this checkout")
    binding = _runtime_binding(ASSET_ROOT, tmp_path / "hk-prefix-binding.json")

    payload = _read_hk_prefix_research_asset(
        "20260911", root_value=ASSET_ROOT, binding_value=binding
    )

    assert payload["status"] == "READY"
    assert payload["export"]["series_count"] == 96
    assert payload["export"]["rows_per_series"] == 60
    assert payload["export"]["state_distribution"]["WARMUP"] == 11
    assert payload["export"]["state_distribution"]["NO_ACTIVE_SETUP"] == 71
    assert payload["export"]["unknown_series_count"] == 18
    assert payload["export"]["complete_terminal_pairs"] == 16
    assert payload["export"]["required_complete_pairs"] == 18
    assert payload["export"]["coverage_status"] == "NOT_SUPPORTED"
    assert payload["export"]["coverage_fraction"] == "16/24"
    assert payload["review"]["comparison_status"] == "NOT_SUPPORTED_TERMINAL_COVERAGE"
    assert payload["review"]["manual_review_status"] == "NOT_REVIEWED"
    assert payload["review"]["no_alpha_claim"] is True
    assert "positive_lower_rate" not in json.dumps(payload, ensure_ascii=False)


def test_review_endpoint_exposes_historical_surface_on_existing_review_route(tmp_path) -> None:
    if not ASSET_ROOT.is_dir():
        import pytest

        pytest.skip("fixed ZGE history asset is not present in this checkout")
    binding = _runtime_binding(ASSET_ROOT, tmp_path / "hk-prefix-binding.json")

    response = TestClient(_panel_app(ASSET_ROOT, binding)).get("/api/v3/review?date=20260911")

    assert response.status_code == 200
    history = response.json()["hk_prefix_research"]
    assert history["status"] == "READY"
    assert history["binding"]["groups"] == 24
    assert history["binding"]["controls"] == 72
    assert history["acceptance"]["future_isolation"] == "PASS"
    assert history["export"]["coverage_fraction"] == "16/24"
    assert history["review"]["conclusion_status"] == "NOT_SUPPORTED"


def test_missing_runtime_binding_is_typed_cannot_confirm(tmp_path) -> None:
    payload = _read_hk_prefix_research_asset("20260911", root_value=tmp_path / "missing")

    assert payload["status"] == "CANNOT_CONFIRM"
    assert payload["export"] is None
    assert payload["cannot_confirm"] == ["HK_PREFIX_RESEARCH_BINDING_NOT_CONFIGURED"]


def test_fixed_binding_rejects_changed_identity_mapping(tmp_path) -> None:
    if not ASSET_ROOT.is_dir():
        import pytest

        pytest.skip("fixed ZGE history asset is not present in this checkout")
    copied = tmp_path / "asset"
    shutil.copytree(ASSET_ROOT, copied)
    binding = _runtime_binding(copied, tmp_path / "hk-prefix-binding.json")
    with (copied / "identity/results_mapping.csv").open("a", encoding="utf-8", newline="") as handle:
        handle.write("\n")

    payload = _read_hk_prefix_research_asset(
        "20260911", root_value=copied, binding_value=binding
    )

    assert payload["status"] == "CANNOT_CONFIRM"
    assert payload["export"] is None
    assert payload["cannot_confirm"] == ["HK_PREFIX_RESEARCH_EVIDENCE_DIGEST_MISMATCH"]
