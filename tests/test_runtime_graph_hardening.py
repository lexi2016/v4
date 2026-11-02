from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tests.test_research_panel_runtime_graph import _fixtures, _sha, _write_json


def _publish_kwargs(fixtures: dict[str, Path], *, data_root: Path) -> dict[str, object]:
    return {
        "business_date": "20260821",
        "data_root": data_root,
        "producer_receipt_root": fixtures["producer"],
        "selector_pointer": fixtures["selector_pointer"],
        "backtest_pointer": fixtures["backtest_pointer"],
        "close_review_path": fixtures["close_review"],
        "close_review_receipt_path": fixtures["close_receipt"],
    }


def test_publisher_rejects_output_root_with_desktop_or_symlink_ancestor(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    with pytest.raises(ValueError, match="PATH_UNSAFE"):
        publish_research_panel_status(**_publish_kwargs(fixtures, data_root=Path("/Users/lexi/Desktop/research-data")))

    real = tmp_path / "real-data"
    real.mkdir()
    linked = tmp_path / "linked-data"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError, match="PATH_UNSAFE"):
        publish_research_panel_status(**_publish_kwargs(fixtures, data_root=linked))


@pytest.mark.parametrize(
    "data_root",
    [Path("/tmp/test-runtime-graph-output"), Path("/var/folders/test-runtime-graph-output")],
)
def test_output_roots_must_not_use_system_temporary_directories(
    tmp_path: Path, data_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ops import publish_research_panel_runtime_receipt as publisher

    # Isolate the root policy from the separate ancestor-symlink policy.  /tmp
    # is itself a symlink on macOS, so this makes the test exercise the hard
    # output-root boundary rather than pass for the wrong reason.
    monkeypatch.setattr(publisher, "_assert_no_symlink_ancestors", lambda _path: None)
    with pytest.raises(ValueError, match="PATH_UNSAFE"):
        publisher._allowed_data_root(data_root)


def test_input_root_allows_application_support_state_siblings_but_not_other_apps() -> None:
    from ops import publish_research_panel_runtime_receipt as publisher

    app_root = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local")
    input_paths = (
        app_root / "state/research_panel_daily/receipts",
        app_root / "state/workspace/数据",
    )
    for path in input_paths:
        assert publisher._allowed_input_path(path) == path

    with pytest.raises(ValueError, match="PATH_UNSAFE"):
        publisher._allowed_data_root(input_paths[0])
    with pytest.raises(ValueError, match="PATH_UNSAFE"):
        publisher._allowed_input_path(
            Path("/Users/lexi/Library/Application Support/com.lexi.other/state/data")
        )


def test_publisher_rejects_symlinked_pointer_leaf(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    pointer_target = fixtures["selector_pointer"].read_text(encoding="utf-8")
    symlink_target = tmp_path / "selector-pointer-target"
    symlink_target.write_text(pointer_target, encoding="utf-8")
    fixtures["selector_pointer"].unlink()
    fixtures["selector_pointer"].symlink_to(symlink_target)

    result = publish_research_panel_status(**_publish_kwargs(fixtures, data_root=tmp_path / "data"))

    assert result["lanes"]["A"]["status"] == "CANNOT_CONFIRM"
    assert "POINTER_UNAVAILABLE" in result["lanes"]["A"]["reason"]


@pytest.mark.parametrize(
    "field,value",
    [("row_count", -1), ("row_count", float("nan")), ("coverage_rate", -0.1), ("coverage_rate", 1.1), ("coverage_rate", float("inf"))],
)
def test_publisher_rejects_non_finite_or_out_of_range_numeric_receipt_fields(
    tmp_path: Path, field: str, value: object
) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    source = fixtures["producer"] / "a-20260821.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload[field] = value
    _write_json(source, payload)

    result = publish_research_panel_status(**_publish_kwargs(fixtures, data_root=tmp_path / "data"))

    assert result["lanes"]["A"]["status"] == "CANNOT_CONFIRM"
    assert "NUMERIC" in result["lanes"]["A"]["reason"]


def test_a_receipt_projects_row_count_only_from_verifiable_authority_fields(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    source = fixtures["producer"] / "a-20260821.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload.pop("row_count")
    payload["formula"] = {"authority": {"selector_increment_rows": 7}}
    payload["sync"]["target_date_file_count"] = 2
    _write_json(source, payload)

    result = publish_research_panel_status(**_publish_kwargs(fixtures, data_root=tmp_path / "data"))

    lane = result["lanes"]["A"]
    assert lane["row_count"] == 7
    assert lane["row_count_source"] == "formula.authority.selector_increment_rows"
    assert lane["row_count_authority_file_count"] == 2

    payload.pop("formula")
    payload["sync"].pop("target_date_file_count")
    _write_json(source, payload)
    fallback = publish_research_panel_status(**_publish_kwargs(fixtures, data_root=tmp_path / "data-fallback"))
    assert fallback["lanes"]["A"]["row_count"] == 0
    assert "ROW_COUNT_UNAVAILABLE" in fallback["lanes"]["A"]["reason"]


def test_a_empty_producer_sha_keeps_verified_partial_without_fabricating_artifact(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    source = fixtures["producer"] / "a-20260821.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["sha256"] = ""
    _write_json(source, payload)

    result = publish_research_panel_status(**_publish_kwargs(fixtures, data_root=tmp_path / "data"))

    lane = result["lanes"]["A"]
    assert lane["status"] == "PARTIAL"
    assert "REBUILD_REQUIRED" in lane["reason"]
    assert len(lane["source_receipt_sha256"]) == 64


def test_a_missing_coverage_is_explicitly_unavailable_not_fabricated(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    source = fixtures["producer"] / "a-20260821.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload.pop("coverage_rate")
    payload.pop("row_count")
    payload["sha256"] = ""
    payload["formula"] = {"authority": {"selector_increment_rows": 7}}
    payload["sync"]["target_date_file_count"] = 2
    _write_json(source, payload)

    result = publish_research_panel_status(**_publish_kwargs(fixtures, data_root=tmp_path / "data"))

    lane = result["lanes"]["A"]
    assert lane["status"] == "PARTIAL"
    assert lane["row_count"] == 7
    assert lane["coverage_rate"] == 0.0
    assert "COVERAGE_UNAVAILABLE" in lane["reason"]


def test_hk_authority_dates_and_hashes_are_validated_without_fabricating_artifact(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    source = fixtures["producer"] / "hk-20260821.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["authority"] = {
        "through_date": "20260820",
        "target_date": "20260821",
        "date": "20260821",
        "panel_sha256": "not-a-sha",
    }
    _write_json(source, payload)

    result = publish_research_panel_status(**_publish_kwargs(fixtures, data_root=tmp_path / "data"))

    lane = result["lanes"]["HK"]
    assert lane["status"] == "CANNOT_CONFIRM"
    assert "HK_AUTHORITY" in lane["reason"]
    assert "producer_artifact_sha256" not in lane


def test_same_canonical_receipt_is_a_noop_and_failed_retry_cannot_downgrade_ready(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    kwargs = _publish_kwargs(fixtures, data_root=tmp_path / "data")
    first = publish_research_panel_status(**kwargs)
    output = Path(first["paths"]["HK"])
    before = output.read_bytes()

    same = publish_research_panel_status(**kwargs)
    assert same["lanes"]["HK"]["no_op"] is True
    assert output.read_bytes() == before

    stale = json.loads(fixtures["close_review"].read_text(encoding="utf-8"))
    stale["trade_date"] = "20260820"
    _write_json(fixtures["close_review"], stale)
    rejected = publish_research_panel_status(**kwargs)
    lane = rejected["lanes"]["HK"]
    assert lane["degradation_rejected"] is True
    assert lane["attempt_status"] == "CANNOT_CONFIRM"
    assert lane["effective_status"] == "READY"
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "READY"


def test_upgrade_requires_matching_explicit_supersedes_sha256(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    stale = json.loads(fixtures["close_review"].read_text(encoding="utf-8"))
    stale["trade_date"] = "20260820"
    _write_json(fixtures["close_review"], stale)
    kwargs = _publish_kwargs(fixtures, data_root=tmp_path / "data")
    cannot = publish_research_panel_status(**kwargs)
    old_sha = cannot["lanes"]["HK"]["canonical_sha256"]

    current = json.loads(fixtures["close_review"].read_text(encoding="utf-8"))
    current["trade_date"] = "20260821"
    _write_json(fixtures["close_review"], current)
    _write_json(
        fixtures["close_receipt"],
        {
            "schema_version": "v3_import_receipt.v1",
            "payload_path": fixtures["close_review"].name,
            "source_sha256": _sha(fixtures["close_review"]),
            "trade_date": "20260821",
        },
    )

    missing = publish_research_panel_status(**kwargs)
    assert missing["lanes"]["HK"]["supersession_rejected"] is True
    upgraded = publish_research_panel_status(**kwargs, supersedes_sha256={"HK": old_sha})
    assert upgraded["lanes"]["HK"]["status"] == "READY"
    assert upgraded["lanes"]["HK"]["supersedes_sha256"] == old_sha


def test_same_level_different_provenance_is_rejected(tmp_path: Path) -> None:
    from ops.publish_research_panel_runtime_receipt import publish_research_panel_status

    fixtures = _fixtures(tmp_path)
    kwargs = _publish_kwargs(fixtures, data_root=tmp_path / "data")
    first = publish_research_panel_status(**kwargs)
    old = Path(first["paths"]["HK"]).read_bytes()
    source = fixtures["producer"] / "hk-20260821.json"
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["sha256"] = "c" * 64
    _write_json(source, payload)

    conflict = publish_research_panel_status(**kwargs)
    lane = conflict["lanes"]["HK"]
    assert lane["conflict_rejected"] is True
    assert lane["attempt_status"] == "READY"
    assert Path(first["paths"]["HK"]).read_bytes() == old


def test_next_target_date_is_market_specific_across_asymmetric_holidays() -> None:
    from infrastructure.runtime_graph.service import _next_market_trade_date, _target_date_for_node

    assert _next_market_trade_date("20260630", "a_share") == "20260701"
    assert _next_market_trade_date("20260630", "hk_connect") == "20260702"
    assert _next_market_trade_date("20260925", "a_share") == "20260928"
    assert _next_market_trade_date("20260925", "hk_connect") == "20260929"
    assert _target_date_for_node("ashare_v193_slot_selector_premarket", "20260925") == "20260928"
    assert _target_date_for_node("hkconnect_d1_top100_prob_active", "20260925") == "20260929"
