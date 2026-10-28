from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.data_store import _sha256
from infrastructure.shared_morning_news_reader import SharedMorningNewsReader
from ops.run_stage_center_nodes import _build_runner, _load_config
from ops import run_stage_center_tick
from stage_center import live_collectors, research_context, selection
from stage_center import runner as stage_runner_module
from stage_center.acquisition import SourceResult
from stage_center.runner import (
    RunnerError,
    _attach_stage_research_roots,
    _validate_exact_selection_inputs,
    build_production_config,
)


APP_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = APP_ROOT / "stage_center_tick_config.json"
R6_CONFIG_PATH = Path(
    "/Users/lexi/Desktop/学习/agents调试/v4_migration_execution_20260924/"
    "stage/r6/builds/20260925-v4-stage-source-r6/release-final-r2/app/"
    "stage_center_tick_config.json"
)
PRODUCER_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/"
    "workspace/v3_shared_data/.runtime/data"
)
HOURLY_ROOT = Path("/Users/lexi/Library/Application Support/com.lexi.v35.local/state/data")
TRADE_DATE = "20260924"
KNOWN_20260924_PAYLOAD_SHA = "a65b4a4d2745d121384da898960acb5778124772dffabeb1013def4985372f86"


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def _write_exact_date_artifact(
    root: Path,
    trade_date: str = TRADE_DATE,
    *,
    bad_pointer_sha: bool = False,
) -> None:
    relative_root = f"morning_news/runs/{trade_date}"
    payload_relative = f"{relative_root}/payload.json"
    manifest_relative = f"{relative_root}/manifest.json"
    receipt_relative = f"{relative_root}/receipt.json"
    payload = {
        "schema_version": "v3_shared_data.morning_news.v1",
        "trade_date": trade_date,
        "source_role": "JIUYANGONGSHE_MORNING_NEWS",
        "articles": [],
        "article_count": 0,
        "stock_mentions": [],
        "mention_count": 0,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    payload_sha = _sha256(payload)
    manifest = {"trade_date": trade_date, "payload_sha256": payload_sha}
    receipt = {
        "trade_date": trade_date,
        "manifest_sha256": _sha256(manifest),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    entry = {
        "payload_relative": payload_relative,
        "manifest_relative": manifest_relative,
        "receipt_relative": receipt_relative,
        "payload_sha256": "0" * 64 if bad_pointer_sha else payload_sha,
    }
    _write_json(root / payload_relative, payload)
    _write_json(root / manifest_relative, manifest)
    _write_json(root / receipt_relative, receipt)
    _write_json(
        root / "morning_news/latest.json",
        {
            "schema_version": "v3_shared_data.morning_news_latest.v1",
            "entries": {trade_date: entry},
        },
    )


def test_stage_config_and_runner_bind_hourly_and_morning_roots_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _load_config(CONFIG_PATH)
    stage_runner = _build_runner(config)
    assert stage_runner.config.v4_research_data_root == HOURLY_ROOT
    assert stage_runner.config.v4_morning_news_root == PRODUCER_ROOT

    builder_raw = {
        "status": "READY",
        "artifact_sha256": "f" * 64,
        "requested_rows": 0,
        "missing_symbols": [],
        "cannot_confirm": [],
        "source_evidence": [],
        "cutoff_at": "09:35:05",
    }
    _attach_stage_research_roots(
        builder_raw,
        stage_runner.config,
        "STAGE_0930_0935",
        market="A_SHARE",
    )

    seen: dict[str, object] = {}

    def read_context(root: Path | str, *, trade_date: str, stage_cutoff: str, morning_root=None):
        seen.update(
            root=Path(root),
            morning_root=Path(morning_root),
            trade_date=trade_date,
            stage_cutoff=stage_cutoff,
        )
        return SimpleNamespace(by_code={}, source_evidence=(), cannot_confirm=())

    def select_stage(rows, trade_date, stage_id, raw_sha, **kwargs):
        return {
            "raw_artifact_sha256": raw_sha,
            "algorithm_sha256": "a" * 64,
            "rows": [],
        }

    monkeypatch.setattr(research_context, "load_research_context", read_context)
    monkeypatch.setattr(selection, "select_a_live_stage", select_stage)
    monkeypatch.setattr(selection, "_selection_identity_ids", lambda *args: ("artifact", "run"))
    plan = SimpleNamespace(trade_date=TRADE_DATE, stage_id="STAGE_0930_0935")
    source = SourceResult(source_id="fixture", status="READY", requested_rows=0, rows=())
    live_collectors.production_selection_builders(plan.stage_id)["A_SHARE"](
        source, plan, builder_raw
    )

    assert seen == {
        "root": HOURLY_ROOT,
        "morning_root": PRODUCER_ROOT,
        "trade_date": TRADE_DATE,
        "stage_cutoff": "09:35:05",
    }
    assert builder_raw["_v4_research_data_root"] != builder_raw["_v4_morning_news_root"]


def test_missing_morning_root_blocks_production_research_lane() -> None:
    config = build_production_config(
        candidate_acquisition_root="/tmp/candidate",
        raw_root="/tmp/raw",
        selection_root="/tmp/selection",
        receipt_root="/tmp/receipt",
        v4_research_data_root="/tmp/hourly",
    )
    with pytest.raises(RunnerError, match="V4 morning-news root is required"):
        _validate_exact_selection_inputs(
            config,
            TRADE_DATE,
            "STAGE_0930_0935",
            market="A_SHARE",
        )
    with pytest.raises(RunnerError, match="V4 morning-news root is required"):
        _attach_stage_research_roots(
            {},
            config,
            "STAGE_0930_0935",
            market="A_SHARE",
        )


def test_morning_reader_rejects_wrong_date_and_bad_payload_sha(tmp_path: Path) -> None:
    exact_root = tmp_path / "exact"
    _write_exact_date_artifact(exact_root)
    reader = SharedMorningNewsReader(exact_root)
    assert reader.read("20260925") is None

    bad_sha_root = tmp_path / "bad-sha"
    _write_exact_date_artifact(bad_sha_root, bad_pointer_sha=True)
    with pytest.raises(ValueError, match="evidence failed verification"):
        SharedMorningNewsReader(bad_sha_root).read(TRADE_DATE)


def test_missing_root_and_zero_mentions_remain_cannot_confirm(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("V3_SHARED_DATA_SOURCE_ROOT", raising=False)
    missing_scores, missing_gaps, _ = research_context._morning_scores(
        tmp_path / "missing-root", trade_date=TRADE_DATE
    )
    assert missing_scores == {}
    assert "MORNING_NEWS_EXACT_DATE_MISSING" in missing_gaps

    empty_root = tmp_path / "zero-mentions"
    _write_exact_date_artifact(empty_root)
    reader = SharedMorningNewsReader(empty_root)
    assert reader._shared_contract() is not None
    payload = reader.read(TRADE_DATE)
    assert payload is not None
    assert payload["mention_count"] == 0
    assert payload["stock_mentions"] == []
    assert payload["stock_mentions_materialization"] == "STOCK_MENTIONS_CANDIDATE_REGISTRY_MISSING"
    assert "STOCK_MENTIONS_CANDIDATE_REGISTRY_MISSING" in payload["cannot_confirm"]


def test_20260924_authoritative_readback_uses_configured_root_without_promoting_empty_parser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("V3_SHARED_DATA_SOURCE_ROOT", raising=False)
    config = _load_config(CONFIG_PATH)
    root = Path(config["v4_morning_news_root"])
    reader = SharedMorningNewsReader(root)
    assert reader._shared_contract() is not None

    latest = json.loads((root / "morning_news/latest.json").read_text(encoding="utf-8"))
    entry = latest["entries"][TRADE_DATE]
    assert entry["payload_sha256"] == KNOWN_20260924_PAYLOAD_SHA
    payload = reader.read(TRADE_DATE)
    assert payload is not None
    assert payload["trade_date"] == TRADE_DATE
    assert payload["source_role"] == "JIUYANGONGSHE_MORNING_NEWS"
    assert payload["article_count"] == len(payload["articles"]) == 3
    assert payload["mention_count"] == len(payload["stock_mentions"]) == 0
    assert "STOCK_MENTIONS_CANDIDATE_REGISTRY_MISSING" in payload["cannot_confirm"]
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False

    missing_scores, missing_gaps, _ = research_context._morning_scores(
        root, trade_date="20260925"
    )
    assert missing_scores == {}
    assert "MORNING_NEWS_EXACT_DATE_MISSING" in missing_gaps


def test_legacy_node_config_without_morning_root_only_blocks_a_research_lane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = json.loads(R6_CONFIG_PATH.read_text(encoding="utf-8"))
    assert "v4_morning_news_root" not in payload

    config = _load_config(R6_CONFIG_PATH)
    stage_runner = _build_runner(config)
    assert stage_runner.config.v4_morning_news_root is None

    with pytest.raises(RunnerError, match="V4 morning-news root is required"):
        _validate_exact_selection_inputs(
            stage_runner.config,
            TRADE_DATE,
            "STAGE_0930_0935",
            market="A_SHARE",
        )

    monkeypatch.setattr(
        stage_runner_module,
        "_validate_formal_input",
        lambda *args, **kwargs: (Path("/tmp/formal.csv"), Path("/tmp/formal.json"), "b" * 64),
    )
    monkeypatch.setattr(
        stage_runner_module,
        "_a_selector_name_map",
        lambda **kwargs: ({}, ("a_name_overlay=READY",)),
    )
    a_nonresearch_evidence = _validate_exact_selection_inputs(
        stage_runner.config,
        TRADE_DATE,
        "STAGE_0925",
        market="A_SHARE",
    )
    assert not any("v4_morning_news_root" in item for item in a_nonresearch_evidence)

    monkeypatch.setattr(
        stage_runner_module,
        "_validate_hk_d1",
        lambda *args, **kwargs: (Path("/tmp/hk-d1.json"), "c" * 64),
    )
    hk_research_evidence = _validate_exact_selection_inputs(
        stage_runner.config,
        TRADE_DATE,
        "STAGE_0930_0935",
        market="HK_CONNECT",
    )
    assert any(item.startswith("hk_d1_json=") for item in hk_research_evidence)
    assert not any("v4_morning_news_root" in item for item in hk_research_evidence)


def test_standalone_tick_wrapper_passes_configured_morning_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = {key: str(tmp_path / key) for key in run_stage_center_tick.ALL_ROOTS}
    config["v4_morning_news_root"] = str(PRODUCER_ROOT)
    seen: dict[str, object] = {}

    monkeypatch.setattr(run_stage_center_tick, "_load", lambda _path: config)
    monkeypatch.setattr(
        run_stage_center_tick,
        "_calendar_gate",
        lambda _trade_date: {"status": "ELIGIBLE"},
    )
    monkeypatch.setattr(run_stage_center_tick, "_preflight_roots", lambda value, _date: value)

    def build_config(**kwargs):
        seen["kwargs"] = kwargs
        return SimpleNamespace(**kwargs)

    class FakeRunner:
        def __init__(self, runner_config):
            seen["runner_config"] = runner_config

        def tick(self, *args, **kwargs):
            seen["tick"] = (args, kwargs)
            return {"status": "READY", **run_stage_center_tick.SAFETY_FLAGS}

    monkeypatch.setattr(stage_runner_module, "build_production_config", build_config)
    monkeypatch.setattr(stage_runner_module, "StageCenterRunner", FakeRunner)

    exit_code = run_stage_center_tick.main(
        [
            "--config",
            str(CONFIG_PATH),
            "--stage-id",
            "STAGE_0930_0935",
            "--trade-date",
            TRADE_DATE,
            "--evaluated-at",
            "2026-09-24T09:35:05+08:00",
            "--historical-backfill",
        ]
    )

    assert exit_code == 0
    assert seen["kwargs"]["v4_morning_news_root"] == PRODUCER_ROOT
    assert seen["kwargs"]["v4_research_data_root"] == Path(config["v4_research_data_root"])
    assert seen["kwargs"]["v4_morning_news_root"] != seen["kwargs"]["v4_research_data_root"]
    assert json.loads(capsys.readouterr().out)["status"] == "READY"


def test_standalone_tick_wrapper_accepts_legacy_config_for_nonresearch_lane(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy_payload = json.loads(R6_CONFIG_PATH.read_text(encoding="utf-8"))
    assert "v4_morning_news_root" not in legacy_payload
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        run_stage_center_tick,
        "_calendar_gate",
        lambda _trade_date: {"status": "ELIGIBLE"},
    )
    monkeypatch.setattr(run_stage_center_tick, "_preflight_roots", lambda value, _date: value)

    def build_config(**kwargs):
        seen["kwargs"] = kwargs
        return SimpleNamespace(**kwargs)

    class FakeRunner:
        def __init__(self, runner_config):
            seen["runner_config"] = runner_config

        def tick(self, *args, **kwargs):
            seen["tick"] = (args, kwargs)
            return {"status": "READY", **run_stage_center_tick.SAFETY_FLAGS}

    monkeypatch.setattr(stage_runner_module, "build_production_config", build_config)
    monkeypatch.setattr(stage_runner_module, "StageCenterRunner", FakeRunner)

    exit_code = run_stage_center_tick.main(
        [
            "--config",
            str(R6_CONFIG_PATH),
            "--stage-id",
            "STAGE_0925",
            "--trade-date",
            TRADE_DATE,
            "--evaluated-at",
            "2026-09-24T09:25:05+08:00",
            "--historical-backfill",
        ]
    )

    assert exit_code == 0
    assert "v4_morning_news_root" not in seen["kwargs"]
    assert seen["tick"][1]["stage_id"] == "STAGE_0925"
    assert json.loads(capsys.readouterr().out)["status"] == "READY"
