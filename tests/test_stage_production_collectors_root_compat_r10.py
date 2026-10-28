from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from stage_center import live_collectors


def _plan(stage_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        stage_id=stage_id,
        codes_for=lambda market: ("00700.HK",) if market == "HK_CONNECT" else ("600000.SH",),
    )


def _runner_collector_kwargs(raw_root: Path) -> dict[str, object]:
    """Match the production_collectors kwargs in slot_execution.py."""
    return {
        "python_path": Path("/opt/v4/bin/python"),
        "shared_root": Path("/srv/v3_shared_data"),
        "snapshot_root": raw_root,
        "a_auction_root": Path("/data/a_auction"),
        "hk_auction_root": Path("/data/hk_auction"),
        "hk_stage_replay_root": Path("/data/hk_replay"),
    }


def test_production_collectors_accepts_runner_kwargs_and_preserves_snapshot_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    plan = _plan("STAGE_0930_0935")
    seen: dict[str, object] = {}
    expected = object()

    def collect_hk_minute(
        stage_plan,
        *,
        codes,
        python_path,
        shared_root,
        snapshot_root,
        replay_provider=None,
    ):
        seen.update(
            stage_plan=stage_plan,
            codes=codes,
            python_path=python_path,
            shared_root=shared_root,
            snapshot_root=snapshot_root,
            replay_provider=replay_provider,
        )
        return expected

    monkeypatch.setattr(live_collectors, "collect_hk_minute", collect_hk_minute)
    collectors = live_collectors.production_collectors(
        plan,
        **_runner_collector_kwargs(raw_root),
    )
    result = collectors["HK_CONNECT"](plan, "HK_CONNECT")

    assert result is expected
    assert seen["stage_plan"] is plan
    assert seen["codes"] == ("00700.HK",)
    assert seen["snapshot_root"] is raw_root


def test_0925_runner_kwargs_keep_exact_auction_collectors(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_root = tmp_path / "raw"
    plan = _plan("STAGE_0925")
    seen: dict[str, dict[str, object]] = {}

    def collect_a_share_auction(stage_plan, *, codes, python_path, shared_root, auction_root):
        seen["A_SHARE"] = {
            "stage_plan": stage_plan,
            "codes": codes,
            "auction_root": auction_root,
        }
        return "a-auction"

    def collect_hk_auction(stage_plan, *, codes, python_path, shared_root, auction_root):
        seen["HK_CONNECT"] = {
            "stage_plan": stage_plan,
            "codes": codes,
            "auction_root": auction_root,
        }
        return "hk-auction"

    monkeypatch.setattr(live_collectors, "collect_a_share_auction", collect_a_share_auction)
    monkeypatch.setattr(live_collectors, "collect_hk_auction", collect_hk_auction)
    collectors = live_collectors.production_collectors(
        plan,
        **_runner_collector_kwargs(raw_root),
    )

    assert set(collectors) == {"A_SHARE", "HK_CONNECT"}
    assert collectors["A_SHARE"](plan, "A_SHARE") == "a-auction"
    assert collectors["HK_CONNECT"](plan, "HK_CONNECT") == "hk-auction"
    assert seen["A_SHARE"]["stage_plan"] is plan
    assert seen["A_SHARE"]["codes"] == ("600000.SH",)
    assert seen["A_SHARE"]["auction_root"] == Path("/data/a_auction")
    assert seen["HK_CONNECT"]["stage_plan"] is plan
    assert seen["HK_CONNECT"]["codes"] == ("00700.HK",)
    assert seen["HK_CONNECT"]["auction_root"] == Path("/data/hk_auction")
