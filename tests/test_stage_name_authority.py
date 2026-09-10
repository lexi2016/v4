from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest


def _hk_d1_fixture(root: Path, trade_date: str) -> Path:
    rows = []
    for index in range(100):
        code = f"HK.{index + 1:05d}"
        row = {"code": code, "target_date": trade_date}
        if index == 2:
            row["name"] = "果下科技"
        rows.append(row)
    path = root / trade_date / "hkconnect_d1_top100.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "status": "STRICT_0_2_READY",
                "target_date": trade_date,
                "rows": rows,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _a_name_authority_fixture(
    root: Path,
    *,
    receipt_shape: str = "attempted",
    lane_overrides: dict[str, object] | None = None,
    receipt_overrides: dict[str, object] | None = None,
    selector_columns: tuple[str, ...] = ("trade_date", "ts_code", "name"),
    selector_name: str = "平安银行",
    selector_path: Path | None = None,
    receipt_layout: str = "generic",
) -> tuple[Path, Path, str]:
    """Create an exact-date A pool, receipt, and selector parquet fixture."""
    import pyarrow as pa
    import pyarrow.parquet as parquet

    trade_date = "20260821"
    signal_date = "20260820"
    if receipt_layout == "formal":
        state_root = root / "state"
        candidate_root = state_root / "candidate"
        receipt_root = state_root / "research_panel_daily" / "receipts"
        default_selector_path = state_root / "workspace" / "selector.parquet"
    else:
        candidate_root = root / "candidate"
        receipt_root = root / "receipts"
        default_selector_path = root / "selector.parquet"
    pool_path = candidate_root / "preselection_pools" / trade_date / "a_d1_premarket_pool.json"
    pool_path.parent.mkdir(parents=True)
    pool_path.write_text(
        json.dumps(
            {
                "status": "V192_CANDIDATE_READY",
                "stage_selection_eligible": True,
                "target_date": trade_date,
                "rows": [{"signal_date": signal_date}],
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        ),
        encoding="utf-8",
    )

    selector_path = selector_path or default_selector_path
    selector_path.parent.mkdir(parents=True, exist_ok=True)
    selector_values = {
        "trade_date": [signal_date],
        "ts_code": ["000001.SZ"],
        "name": [selector_name],
    }
    table = pa.table({column: selector_values[column] for column in selector_columns})
    parquet.write_table(table, selector_path)
    selector_sha = hashlib.sha256(selector_path.read_bytes()).hexdigest()
    formula = {
        "status": "READY",
        "target_date": signal_date,
        "selector": str(selector_path),
        "selector_sha256": selector_sha,
    }
    lane = {
        "status": "READY",
        "target_date": signal_date,
        "formula": formula,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    lane.update(lane_overrides or {})
    if receipt_shape == "legacy":
        receipt = {
            "status": "READY",
            "target_date": signal_date,
            "formula": formula,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    else:
        receipt = {
            "status": "ATTEMPTED",
            "target_date": signal_date,
            "lanes": {"A": lane},
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
    receipt.update(receipt_overrides or {})
    receipt_path = receipt_root / f"a-{signal_date}.json"
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    return candidate_root, receipt_root, trade_date


def test_a_name_authority_overrides_code_and_leaves_missing_name_unset(monkeypatch) -> None:
    from stage_center import runner as stage_runner
    from stage_center.acquisition import SourceResult

    monkeypatch.setattr(
        stage_runner,
        "_a_selector_name_map",
        lambda **_kwargs: (
            {"A.000001": "平安银行"},
            ("a_selector_authority=fixture",),
        ),
    )
    source = SourceResult(
        "fixture",
        "READY",
        rows=(
            {"code": "A.000001", "name": "A.000001", "stock_name": "A.000001"},
            {"code": "A.000002", "name": "A.000002", "stock_name": "A.000002"},
        ),
    )

    enriched = stage_runner._attach_a_name_authority(
        source,
        candidate_root=Path("/unused"),
        research_panel_receipt_root=Path("/unused"),
        trade_date="20260820",
    )

    assert enriched.rows[0]["name"] == "平安银行"
    assert enriched.rows[0]["stock_name"] == "平安银行"
    assert enriched.rows[1]["name"] is None
    assert enriched.rows[1]["stock_name"] is None
    assert enriched.status == "PARTIAL_WITH_ROWS"
    assert "NAME_AUTHORITY_CODE_NOT_FOUND" in enriched.cannot_confirm


def test_a_name_authority_accepts_attempted_wrapper_with_ready_a_lane(tmp_path: Path) -> None:
    from stage_center import runner as stage_runner

    candidate_root, receipt_root, trade_date = _a_name_authority_fixture(tmp_path)

    mapping, evidence = stage_runner._a_selector_name_map(
        candidate_root=candidate_root,
        research_panel_receipt_root=receipt_root,
        trade_date=trade_date,
    )

    assert mapping == {"A.000001": "平安银行"}
    assert any(item.startswith("a_research_panel_receipt=") for item in evidence)


def test_a_name_authority_rejects_attempted_outer_wrapper_date_mismatch(tmp_path: Path) -> None:
    from stage_center import runner as stage_runner

    candidate_root, receipt_root, trade_date = _a_name_authority_fixture(tmp_path)
    receipt_path = receipt_root / "a-20260820.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["target_date"] = "20260819"
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(stage_runner.RunnerError, match="receipt target_date mismatch"):
        stage_runner._a_selector_name_map(
            candidate_root=candidate_root,
            research_panel_receipt_root=receipt_root,
            trade_date=trade_date,
        )


@pytest.mark.parametrize("target_date", (None, "20260819"))
def test_a_name_authority_legacy_ready_requires_exact_outer_wrapper_date(
    tmp_path: Path, target_date: str | None
) -> None:
    from stage_center import runner as stage_runner

    candidate_root, receipt_root, trade_date = _a_name_authority_fixture(
        tmp_path, receipt_shape="legacy"
    )
    receipt_path = receipt_root / "a-20260820.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if target_date is None:
        receipt.pop("target_date")
    else:
        receipt["target_date"] = target_date
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(stage_runner.RunnerError, match="receipt target_date mismatch"):
        stage_runner._a_selector_name_map(
            candidate_root=candidate_root,
            research_panel_receipt_root=receipt_root,
            trade_date=trade_date,
        )


@pytest.mark.parametrize("declared_sha", ("0" * 64, "correct"))
def test_a_name_authority_attempted_outer_selector_sha_is_verified(
    tmp_path: Path, declared_sha: str
) -> None:
    from stage_center import runner as stage_runner

    candidate_root, receipt_root, trade_date = _a_name_authority_fixture(tmp_path)
    receipt_path = receipt_root / "a-20260820.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    formula = receipt["lanes"]["A"]["formula"]
    selector_path = Path(formula["selector"])
    actual_sha = hashlib.sha256(selector_path.read_bytes()).hexdigest()
    formula.pop("selector_sha256")
    receipt["lanes"]["A"]["formula"] = formula
    receipt["selector_sha256"] = actual_sha if declared_sha == "correct" else declared_sha
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    if declared_sha == "correct":
        mapping, _evidence = stage_runner._a_selector_name_map(
            candidate_root=candidate_root,
            research_panel_receipt_root=receipt_root,
            trade_date=trade_date,
        )
        assert mapping == {"A.000001": "平安银行"}
    else:
        with pytest.raises(stage_runner.RunnerError, match="SHA mismatch"):
            stage_runner._a_selector_name_map(
                candidate_root=candidate_root,
                research_panel_receipt_root=receipt_root,
                trade_date=trade_date,
            )


def test_a_name_authority_accepts_legacy_ready_receipt(tmp_path: Path) -> None:
    from stage_center import runner as stage_runner

    candidate_root, receipt_root, trade_date = _a_name_authority_fixture(
        tmp_path, receipt_shape="legacy"
    )

    mapping, _evidence = stage_runner._a_selector_name_map(
        candidate_root=candidate_root,
        research_panel_receipt_root=receipt_root,
        trade_date=trade_date,
    )

    assert mapping == {"A.000001": "平安银行"}


def test_a_name_authority_reads_schema_then_exact_filtered_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from stage_center import runner as stage_runner
    import pyarrow.parquet as parquet

    candidate_root, receipt_root, trade_date = _a_name_authority_fixture(tmp_path)
    events: list[object] = []
    original_read_schema = parquet.read_schema
    original_read_table = parquet.read_table

    def counted_read_schema(*args, **kwargs):
        events.append("schema")
        return original_read_schema(*args, **kwargs)

    def counted_read_table(*args, **kwargs):
        events.append(("table", kwargs))
        return original_read_table(*args, **kwargs)

    monkeypatch.setattr(parquet, "read_schema", counted_read_schema)
    monkeypatch.setattr(parquet, "read_table", counted_read_table)

    mapping, _evidence = stage_runner._a_selector_name_map(
        candidate_root=candidate_root,
        research_panel_receipt_root=receipt_root,
        trade_date=trade_date,
    )

    assert mapping == {"A.000001": "平安银行"}
    assert events[0] == "schema"
    assert events[1][0] == "table"
    assert events[1][1]["columns"] == ["trade_date", "ts_code", "name"]
    assert events[1][1]["filters"] == [("trade_date", "=", "20260820")]


def test_a_name_authority_rejects_selector_outside_receipt_authority_root(tmp_path: Path) -> None:
    from stage_center import runner as stage_runner

    candidate_root, receipt_root, trade_date = _a_name_authority_fixture(
        tmp_path,
        selector_path=tmp_path.parent / "selector-outside-authority-root.parquet",
    )

    with pytest.raises(stage_runner.RunnerError, match="root"):
        stage_runner._a_selector_name_map(
            candidate_root=candidate_root,
            research_panel_receipt_root=receipt_root,
            trade_date=trade_date,
        )


@pytest.mark.parametrize("selector_location", ("workspace", "outside"))
def test_a_name_authority_formal_receipt_root_allows_state_workspace_only(
    tmp_path: Path, selector_location: str
) -> None:
    from stage_center import runner as stage_runner

    state_root = tmp_path / "state"
    selector_path = (
        state_root / "workspace" / "selector.parquet"
        if selector_location == "workspace"
        else tmp_path / "outside-state-selector.parquet"
    )
    candidate_root, receipt_root, trade_date = _a_name_authority_fixture(
        tmp_path,
        receipt_layout="formal",
        selector_path=selector_path,
    )

    if selector_location == "workspace":
        mapping, _evidence = stage_runner._a_selector_name_map(
            candidate_root=candidate_root,
            research_panel_receipt_root=receipt_root,
            trade_date=trade_date,
        )
        assert mapping == {"A.000001": "平安银行"}
    else:
        with pytest.raises(stage_runner.RunnerError, match="root"):
            stage_runner._a_selector_name_map(
                candidate_root=candidate_root,
                research_panel_receipt_root=receipt_root,
                trade_date=trade_date,
            )


@pytest.mark.parametrize(
    ("lane_overrides", "receipt_overrides", "selector_columns", "error"),
    [
        ({"status": "PARTIAL"}, None, ("trade_date", "ts_code", "name"), "status"),
        ({"target_date": "20260819"}, None, ("trade_date", "ts_code", "name"), "date"),
        ({"production_allowed": True}, None, ("trade_date", "ts_code", "name"), "safety"),
        (None, {"orders_sent": True}, ("trade_date", "ts_code", "name"), "safety"),
        ({"formula": {"status": "FAILED"}}, None, ("trade_date", "ts_code", "name"), "formula"),
        ({"formula": {"status": "READY", "target_date": "20260819"}}, None, ("trade_date", "ts_code", "name"), "target_date"),
        ({"formula": {"status": "READY", "target_date": "20260820", "selector": "relative.parquet"}}, None, ("trade_date", "ts_code", "name"), "path"),
        ({"formula": {"status": "READY", "target_date": "20260820", "selector": "/missing/selector.parquet"}}, None, ("trade_date", "ts_code", "name"), "missing"),
        ({"formula": {"status": "READY", "target_date": "20260820", "selector": "__REPLACE_SELECTOR__", "selector_sha256": "0" * 64}}, None, ("trade_date", "ts_code", "name"), "SHA"),
        (None, None, ("trade_date", "ts_code"), "schema"),
        (None, None, ("trade_date", "ts_code", "name"), "empty"),
    ],
)
def test_a_name_authority_attempted_wrapper_fails_closed(
    tmp_path: Path,
    lane_overrides: dict[str, object] | None,
    receipt_overrides: dict[str, object] | None,
    selector_columns: tuple[str, ...],
    error: str,
) -> None:
    from stage_center import runner as stage_runner

    candidate_root, receipt_root, trade_date = _a_name_authority_fixture(
        tmp_path,
        lane_overrides=lane_overrides,
        receipt_overrides=receipt_overrides,
        selector_columns=selector_columns,
        selector_name="A.000001" if error == "empty" else "平安银行",
    )
    if lane_overrides and isinstance(lane_overrides.get("formula"), dict):
        receipt_path = receipt_root / "a-20260820.json"
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        formula = dict(receipt["lanes"]["A"]["formula"])
        for key, value in lane_overrides["formula"].items():
            if value == "__REPLACE_SELECTOR__":
                value = str(tmp_path / "selector.parquet")
            elif value == "/missing/selector.parquet":
                value = str(tmp_path / "missing-selector.parquet")
            formula[key] = value
        receipt["lanes"]["A"]["formula"] = formula
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(stage_runner.RunnerError, match=error):
        stage_runner._a_selector_name_map(
            candidate_root=candidate_root,
            research_panel_receipt_root=receipt_root,
            trade_date=trade_date,
        )


def test_hk_name_authority_overrides_code_and_falls_back_when_authority_name_missing(tmp_path: Path) -> None:
    from stage_center import runner as stage_runner
    from stage_center.acquisition import SourceResult

    trade_date = "20260820"
    _hk_d1_fixture(tmp_path, trade_date)
    source = SourceResult(
        "fixture",
        "READY",
        rows=(
            {"code": "HK.00003", "name": "HK.00003", "stock_name": "HK.00003"},
            {"code": "HK.00004"},
        ),
    )

    enriched = stage_runner._attach_hk_authority(
        source,
        d1_root=tmp_path,
        second_root=None,
        trade_date=trade_date,
        stage_id="STAGE_0935_0940",
    )

    assert enriched.rows[0]["name"] == "果下科技"
    assert enriched.rows[0]["stock_name"] == "果下科技"
    assert enriched.rows[1]["name"] == "HK.00004"
    assert enriched.rows[1]["stock_name"] == "HK.00004"
