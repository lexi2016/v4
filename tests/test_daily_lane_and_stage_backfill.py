from __future__ import annotations

import json
from pathlib import Path


def test_daily_lane_a_does_not_call_or_write_hk(tmp_path: Path) -> None:
    from ops import macos_research_panel_daily as daily

    calls: list[str] = []
    result = daily.run_lanes(
        target_date="20260819",
        receipt_root=tmp_path,
        a_runner=lambda target: calls.append(f"A:{target}") or {"status": "READY", "target_date": target},
        hk_runner=lambda target: calls.append(f"HK:{target}") or {"status": "READY", "target_date": target},
        lane="A",
    )

    assert calls == ["A:20260819"]
    assert result["requested_lane"] == "A"
    assert result["lanes"]["A"]["status"] == "READY"
    assert result["lanes"]["A"]["runner_called"] is True
    assert result["lanes"]["HK"]["status"] == "NOT_REQUESTED"
    assert result["lanes"]["HK"]["receipt_written"] is False
    assert (tmp_path / "a-20260819.json").is_file()
    assert not (tmp_path / "hk-20260819.json").exists()


def test_daily_lane_all_retains_both_requested_lanes(tmp_path: Path) -> None:
    from ops import macos_research_panel_daily as daily

    result = daily.run_lanes(
        target_date="20260819",
        receipt_root=tmp_path,
        a_runner=lambda target: {"status": "READY", "target_date": target},
        hk_runner=lambda target: {"status": "READY", "target_date": target},
    )

    assert result["requested_lane"] == "ALL"
    assert result["overall_status"] == "READY"
    assert {name for name, payload in result["lanes"].items() if payload["runner_called"]} == {"A", "HK"}


def test_stage_wrapper_requires_historical_backfill_for_past_request(tmp_path: Path, capsys) -> None:
    from ops import run_stage_center_tick as wrapper

    rc = wrapper.main(
        [
            "--config",
            str(tmp_path / "not-used.json"),
            "--trade-date",
            "20260819",
            "--evaluated-at",
            "2026-08-19T09:00:00+08:00",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert rc == 3
    assert output["status"] == "CANNOT_CONFIRM"
    assert output["error"] == "HISTORICAL_BACKFILL_FLAG_REQUIRED"


def test_stage_wrapper_passes_historical_backfill_to_runner(monkeypatch, tmp_path: Path, capsys) -> None:
    from ops import run_stage_center_tick as wrapper

    config = {key: str(tmp_path / key) for key in wrapper.ALL_ROOTS}
    config["python_path"] = str(tmp_path / "python")
    seen: dict[str, object] = {}

    monkeypatch.setattr(wrapper, "_load", lambda _path: config)
    monkeypatch.setattr(wrapper, "_preflight_roots", lambda payload, _date: payload)
    monkeypatch.setattr(
        wrapper,
        "_run_universe_preflight",
        lambda _payload, trade_date: {"status": "READY", "ok": True, "trade_date": trade_date, **wrapper.SAFETY_FLAGS},
    )

    class FakeRunner:
        def __init__(self, _config):
            pass

        def tick(self, trade_date, evaluated_at, *, stage_id=None, historical_backfill=False):
            seen.update(
                trade_date=trade_date,
                evaluated_at=evaluated_at,
                stage_id=stage_id,
                historical_backfill=historical_backfill,
            )
            return {"status": "CANNOT_CONFIRM", "trade_date": trade_date, **wrapper.SAFETY_FLAGS}

    monkeypatch.setattr("stage_center.runner.StageCenterRunner", FakeRunner)
    monkeypatch.setattr("stage_center.runner.build_production_config", lambda **kwargs: kwargs)

    rc = wrapper.main(
        [
            "--config",
            str(tmp_path / "config.json"),
            "--trade-date",
            "20260819",
            "--evaluated-at",
            "2026-08-19T09:00:00+08:00",
            "--stage-id",
            "STAGE_0925",
            "--historical-backfill",
        ]
    )

    json.loads(capsys.readouterr().out)
    assert rc == 3
    assert seen["trade_date"] == "20260819"
    assert seen["stage_id"] == "STAGE_0925"
    assert seen["historical_backfill"] is True


def test_acquisition_plan_carries_historical_backfill(tmp_path: Path) -> None:
    from stage_center.acquisition import build_plan
    from stage_center.candidate_input import CandidateInput

    candidate = CandidateInput(
        root=tmp_path,
        trade_date="20260819",
        current_relative="",
        current_sha256="",
        run_id="candidate",
        codes=("A.000001",),
        artifact_sha256="",
        manifest_sha256="",
        receipt_sha256="",
        source_projection_sha256="a" * 64,
        source_evidence=(),
    )
    plan = build_plan(
        tmp_path,
        "20260819",
        "STAGE_0925",
        candidate=candidate,
        historical_backfill=True,
    )

    assert plan.historical_backfill is True
