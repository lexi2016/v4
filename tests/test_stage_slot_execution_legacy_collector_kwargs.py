from __future__ import annotations

import ast
import inspect
from pathlib import Path
import os
from types import SimpleNamespace
import pytest
from stage_center._runner_parts.row_evidence import __project_raw_rows_body

from stage_center import live_collectors, runner
from stage_center._runner_parts.slot_execution import _signature_supported_kwargs, _optional_temporal_observation_authorization
from stage_center.hk_stage8 import production_natural_collectors


APP_ROOT = Path(os.environ.get("V4_TEST_STAGE_APP_ROOT", str(Path(__file__).resolve().parents[1])))
SLOT_EXECUTION = APP_ROOT / "stage_center" / "_runner_parts" / "slot_execution.py"


def _calls(name: str) -> list[ast.Call]:
    tree = ast.parse(SLOT_EXECUTION.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    ]


def _keyword_names(call: ast.Call) -> set[str]:
    return {item.arg for item in call.keywords if item.arg is not None}


def test_runner_calls_legacy_collector_with_supported_kwargs_and_keeps_natural_root() -> None:
    assert Path(live_collectors.__file__).resolve().is_relative_to(APP_ROOT.resolve())

    ordinary_calls = _calls("production_collectors")
    assert len(ordinary_calls) == 2
    supported = {
        "plan",
        "python_path",
        "shared_root",
        "a_auction_root",
        "hk_auction_root",
        "hk_stage_replay_root",
    }
    for call in ordinary_calls:
        names = _keyword_names(call)
        assert names == supported
        assert any(
            item.arg is None
            and isinstance(item.value, ast.Name)
            and item.value.id == "production_snapshot_root_kwargs"
            for item in call.keywords
        )
        inspect.signature(live_collectors.production_collectors).bind(
            **{name: object() for name in names}
        )

    natural_calls = _calls("production_natural_collectors")
    assert len(natural_calls) == 1
    assert "snapshot_root" in _keyword_names(natural_calls[0])
    assert "snapshot_root" in inspect.signature(production_natural_collectors).parameters


def test_snapshot_root_is_forwarded_only_when_collector_signature_supports_it(tmp_path: Path) -> None:
    raw_root = tmp_path / "raw"
    assert _signature_supported_kwargs(
        runner.__dict__, live_collectors.production_collectors, snapshot_root=raw_root
    ) == ({"snapshot_root": raw_root} if "snapshot_root" in inspect.signature(live_collectors.production_collectors).parameters else {})

    def future_production_collectors(plan, *, snapshot_root):
        return plan, snapshot_root

    assert _signature_supported_kwargs(
        runner.__dict__, future_production_collectors, snapshot_root=raw_root
    ) == {"snapshot_root": raw_root}

    def future_refresh(source, *, snapshot_root, pool_artifact_sha256):
        return source, snapshot_root, pool_artifact_sha256

    assert _signature_supported_kwargs(
        runner.__dict__,
        future_refresh,
        snapshot_root=raw_root,
        pool_artifact_sha256="pool-sha",
    ) == {"snapshot_root": raw_root, "pool_artifact_sha256": "pool-sha"}


def test_0930_hk_minute_route_still_uses_explicit_code_bounded_futu_collector(monkeypatch) -> None:
    plan = SimpleNamespace(
        stage_id="STAGE_0930_0935",
        codes_for=lambda market: ("00700.HK",) if market == "HK_CONNECT" else ("600000.SH",),
    )
    seen: dict[str, object] = {}
    expected = object()

    def collect_hk_minute(stage_plan, *, codes, python_path, shared_root, replay_provider=None, snapshot_root=None):
        seen.update(
            stage_plan=stage_plan,
            codes=codes,
            python_path=python_path,
            shared_root=shared_root,
            replay_provider=replay_provider,
        )
        return expected

    monkeypatch.setattr(live_collectors, "collect_hk_minute", collect_hk_minute)
    collectors = live_collectors.production_collectors(
        plan,
        python_path=Path("/runtime/python"),
        shared_root=Path("/shared/v3"),
        a_auction_root=Path("/roots/a-auction"),
        hk_auction_root=Path("/roots/hk-auction"),
        hk_stage_replay_root=Path("/roots/hk-replay"),
    )

    assert collectors["HK_CONNECT"](plan, "HK_CONNECT") is expected
    assert seen["stage_plan"] is plan
    assert seen["codes"] == ("00700.HK",)
    assert seen["python_path"] == Path("/runtime/python")
    assert seen["shared_root"] == Path("/shared/v3")
    assert seen["replay_provider"] is None


def test_recovery_call_drops_only_unsupported_keywords_and_keeps_pool_sha_gate() -> None:
    recovery_calls = _calls("refresh_hk_active_lanes")
    assert len(recovery_calls) == 1
    names = _keyword_names(recovery_calls[0])
    assert names == {"codes", "python_path", "shared_root", "trade_date", "stage_id", "cutoff_at"}
    assert any(
        item.arg is None
        and isinstance(item.value, ast.Name)
        and item.value.id == "recovery_optional_kwargs"
        for item in recovery_calls[0].keywords
    )
    inspect.signature(live_collectors.refresh_hk_active_lanes).bind(
        object(), **{name: object() for name in names}
    )

    source = SLOT_EXECUTION.read_text(encoding="utf-8")
    assert '"active_snapshot_pool_artifact_sha256"' in source
    assert "current_pool_sha != expected_pool_sha" in source
    assert '"HK_ACTIVE_SNAPSHOT_EVIDENCE_CHANGED"' in source


def test_legacy_missing_observation_hook_grants_no_contract():
    source = SimpleNamespace(status="CANNOT_CONFIRM", rows=({"temporal_cutoff_safe": False},))
    result, contract = _optional_temporal_observation_authorization({}, source, object(), market="HK_CONNECT")
    assert result is source
    assert result.status == "CANNOT_CONFIRM"
    assert contract is None


def test_existing_observation_hook_receives_original_arguments():
    source, plan = object(), object()
    seen = {}
    def hook(received_source, received_plan, **kwargs):
        seen.update(source=received_source, plan=received_plan, **kwargs)
        return received_source, None
    result, contract = _optional_temporal_observation_authorization({"_authorize_hk_0930_tdx_temporal_false_observation": hook}, source, plan, market="HK_CONNECT", historical_backfill=False)
    assert result is source and contract is None
    assert seen == {"source": source, "plan": plan, "market": "HK_CONNECT", "historical_backfill": False}


def test_raw_projection_legacy_and_current_signatures_preserve_cutoff_guard():
    rows = ({"temporal_cutoff_safe": False},)
    def legacy_project(rows, *, trade_date, stage_id, market):
        assert rows[0]["temporal_cutoff_safe"] is False
        return rows
    def current_project(rows, *, trade_date, stage_id, market, research_observation_contract=None):
        return rows, research_observation_contract
    common = dict(trade_date="20261013", stage_id="STAGE_0930_0935", market="HK_CONNECT")
    legacy_kwargs = _signature_supported_kwargs(runner.__dict__, legacy_project, research_observation_contract=None)
    assert legacy_kwargs == {}
    assert legacy_project(rows, **common, **legacy_kwargs) is rows
    current_kwargs = _signature_supported_kwargs(runner.__dict__, current_project, research_observation_contract="existing-contract")
    assert current_project(rows, **common, **current_kwargs) == (rows, "existing-contract")
    calls = _calls("project_raw_rows")
    assert len(calls) == 1
    assert _keyword_names(calls[0]) == {"trade_date", "stage_id", "market"}
    assert any(item.arg is None and isinstance(item.value, ast.Name) and item.value.id == "projection_optional_kwargs" for item in calls[0].keywords)


def test_legacy_validation_keeps_unsafe_row_rejection():
    def legacy_validate(rows, *, trade_date, stage_id, market):
        assert rows == ({"temporal_cutoff_safe": False},)
        return [], ["temporal_cutoff_safe must be true"]
    scope = dict(runner.__dict__, validate_rows=legacy_validate, RAW_FIELDS=("temporal_cutoff_safe",))
    with pytest.raises(runner.RunnerError, match="temporal_cutoff_safe must be true"):
        __project_raw_rows_body(scope, ({"temporal_cutoff_safe": False},), trade_date="20261013", stage_id="STAGE_0930_0935", market="HK_CONNECT")


def _mixed_market_role_audit():
    codes = ["600183", "HK.01888"]
    return {
        "trade_date": "20261013", "slot": "0900",
        "source_manifest": {"trade_date": "20261013", "hourly_slot": "0900", "source_receipts": ["hourly/receipt.json"]},
        "report_entity_audit": {
            "policy_version": "report_subject_scoring.v1", "affected_codes": codes,
            "excluded_evidence_count": 2,
            "excluded_evidence": [{"stock_code": code, "entity_role": "UNMATCHED_REPORT_ATTACHMENT", "evidence_id": code, "research_subject_eligible": False, "source_path": "hourly/receipt.json"} for code in codes],
        },
    }


def test_mixed_market_role_audit_keeps_both_excluded_warnings():
    from domains.research import _report_role_warning_reasons
    assert _report_role_warning_reasons(_mixed_market_role_audit()) == ["REPORT_ROLE_EVIDENCE_EXCLUDED:600183", "REPORT_ROLE_EVIDENCE_EXCLUDED:HK.01888"]


@pytest.mark.parametrize("invalid_code", ["HK.1888", "HK.018888", "01888", "US.01888"])
def test_role_audit_still_rejects_noncanonical_codes(invalid_code):
    from domains.research import _report_role_warning_reasons
    source = _mixed_market_role_audit()
    source["report_entity_audit"]["affected_codes"][1] = invalid_code
    source["report_entity_audit"]["excluded_evidence"][1]["stock_code"] = invalid_code
    with pytest.raises(ValueError, match="REPORT_ROLE_AUDIT_SHAPE_INVALID"):
        _report_role_warning_reasons(source)


