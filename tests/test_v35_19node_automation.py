from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from contracts.close_timeline import (
    CLOSE_TIMELINE,
    CLOSE_TIMELINE_SLOT_TO_NODE,
    visible_timeline_owners,
)
from contracts.runtime_tasks import DispatchMode, DispatchRequest
from infrastructure.scheduling.catalog import load_workload_catalog
from infrastructure.scheduling.execution_ledger import ExecutionLedger
from domains.task_status import build_task_status
from domains.a_share_review import build_a_share_review
from domains import d1_review_source_producer as d1_source
from infrastructure.a_share_review_store import AShareReviewStore
from ops import collect_hourly_research_input as hourly_input
from ops import daily_materialize
from ops import materialize_d1_review_lanes as d1_lanes
from ops import run_scheduled_slot
from ops import run_v35_close_review_node as close_node
from ops import run_v35_macos_scheduler as macos_scheduler
from ops import run_stage_center_milestone


def test_every_visible_timeline_point_has_one_exact_owner_and_slot_mapping() -> None:
    catalog = load_workload_catalog()
    owners = visible_timeline_owners(catalog)

    assert len(CLOSE_TIMELINE) == 19
    assert len(owners) == 19
    assert len({row["owner_id"] for row in owners}) == 19
    assert [row["planned_slot"] for row in CLOSE_TIMELINE[8:]] == [
        "1608", "1500", "1555", "1605", "2030", "2040", "2050",
        "2105", "2108", "2110", "2115",
    ]
    assert CLOSE_TIMELINE_SLOT_TO_NODE == {
        "1608": "hk_connect_close_review",
        "1500": "FUPAN_CLOSE_MATERIALS",
        "1555": "FUPAN_REVIEW_START",
        "1605": "FUPAN_A_SHARE_STRUCTURE",
        "2030": "FUPAN_VIDEO_CHECK",
        "2040": "FUPAN_VIDEO_DOWNLOAD_ASR",
        "2050": "FUPAN_STOCKDICT",
        "2105": "FUPAN_VIDEO_TABLE_OCR_ALIGN",
        "2108": "FUPAN_VIDEO_GAP",
        "2110": "FUPAN_V3_PUBLISH",
        "2115": "FUPAN_8771_VERIFY",
    }
    assert next(row for row in catalog.workloads if row.workload_id == "a_share_close_review").slots == (
        "1605", "1710"
    )
    workloads = {row.workload_id: row for row in catalog.workloads}
    assert (workloads["fupan_close_materials"].market_scope.value, workloads["fupan_close_materials"].run_policy.value) == ("A_SHARE", "A_SHARE_TRADE_DAY")
    assert (workloads["fupan_review_start"].market_scope.value, workloads["fupan_review_start"].run_policy.value) == ("HK_CONNECT", "HK_CONNECT_TRADE_DAY")


def test_post_close_slot_allowlist_and_next_target_date_are_frozen() -> None:
    expected = {"2040", "2050", "2105", "2108", "2110", "2115"}
    assert expected.issubset(set(run_scheduled_slot.ALL_SLOTS))
    assert run_scheduled_slot.compute_dates(
        business_date="20260818", slot="2140"
    )["target_date"] == "20260819"


def test_same_day_post_close_catchup_uses_earliest_unclaimed_fixed_node(
    tmp_path: Path,
) -> None:
    for slot in ("1500", "1555", "1605", "1608", "1700", "1710", "1720", "1730", "1800"):
        receipt = tmp_path / "receipts" / "live" / "20260818" / slot / "prior.dispatch-receipt.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps({"status": "SUCCEEDED", "finished_at": "2026-08-18T13:31:00Z"}),
            encoding="utf-8",
        )
    first = macos_scheduler.resolve_due_slot(
        now=datetime(2026, 8, 18, 21, 30), ledger_root=tmp_path
    )
    assert first["slot"] == "2030"
    receipt = tmp_path / "receipts" / "live" / "20260818" / "2030" / "run.dispatch-receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"status": "SUCCEEDED", "finished_at": "2026-08-18T13:31:00Z"}),
        encoding="utf-8",
    )
    second = macos_scheduler.resolve_due_slot(
        now=datetime(2026, 8, 18, 21, 31), ledger_root=tmp_path
    )
    assert second["slot"] == "2040"


def test_exact_late_post_close_tick_recovers_an_earlier_gap_first(tmp_path: Path) -> None:
    for slot in ("1500", "1555", "1605", "1608", "1700", "1710", "1720", "1730", "1800"):
        receipt = tmp_path / "receipts" / "live" / "20260818" / slot / "prior.dispatch-receipt.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps({"status": "SUCCEEDED", "finished_at": "2026-08-18T13:31:00Z"}),
            encoding="utf-8",
        )
    due = macos_scheduler.resolve_due_slot(
        now=datetime(2026, 8, 18, 21, 5), ledger_root=tmp_path
    )
    assert due["slot"] == "2030"
    assert due["catchup"] is True


def test_close_review_probe_is_bound_to_v35_8873() -> None:
    assert close_node.DEFAULT_LOOPBACK_BASE == "http://127.0.0.1:8873"
    assert close_node._validate_loopback_url("http://127.0.0.1:8873") is True
    assert close_node._validate_loopback_url("http://127.0.0.1:8872") is False


def test_launchers_forward_explicit_stage_root_and_default_to_8873() -> None:
    app_root = Path(__file__).parents[1]
    api_launcher = (app_root / "ops" / "launch_v35_macos.sh").read_text(encoding="utf-8")
    scheduler_launcher = (app_root / "ops" / "launch_v35_macos_scheduler.sh").read_text(encoding="utf-8")
    assert 'port="${V35_PORT:-8873}"' in api_launcher
    assert "--stage-selection-root" in api_launcher
    assert "--stage-selection-root" in scheduler_launcher
    assert 'V35_STAGE_CENTER_SELECTION_ROOT:?V35_STAGE_CENTER_SELECTION_ROOT is required' in scheduler_launcher


def test_release_shared_data_link_is_relative_and_does_not_follow_current_release() -> None:
    link = Path(__file__).parents[1] / "v3_shared_data"
    assert link.is_symlink()
    assert link.readlink() == Path("upstreams/v3_shared_data")


def test_scheduler_consume_only_reads_the_explicit_stage_selection_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[tuple[str, str, Path]] = []

    class FakeConsumer:
        def __init__(self, root: Path) -> None:
            self.root = Path(root)

        def get(self, business_date: str, stage_id: str) -> dict:
            observed.append((business_date, stage_id, self.root))
            return {
                "status": "READY",
                "trade_date": business_date,
                "stage_id": stage_id,
                "artifact_id": "artifact-1",
                "run_id": "run-1",
                "markets": {},
                "write_performed": False,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    monkeypatch.setattr(macos_scheduler, "StageSelectionConsumer", FakeConsumer)
    result = macos_scheduler.consume_shared_stage_selection(
        business_date="20260818",
        slot="1500",
        selection_root=tmp_path / "selection",
        stage_acquisition_universe=None,
    )

    assert observed == [("20260818", "STAGE_1445_1500", tmp_path / "selection")]
    assert result["status"] == "CONSUME_ONLY"
    assert result["selection_status"] == "READY"
    assert result["write_performed"] is False


def test_d1_stage_input_bridge_uses_explicit_stage_selection_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    requested: list[str] = []

    class FakeConsumer:
        def __init__(self, root: Path) -> None:
            assert Path(root) == tmp_path / "selection"

        def get(self, trade_date: str, stage_id: str, *, markets=None) -> dict:
            assert trade_date == "20260818"
            requested.append(stage_id)
            return {
                "status": "READY",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": {"A_SHARE": {"rows": [], "run_id": "source-run-7", "artifact_id": "source-artifact-7"}},
                "artifact_id": "artifact-7",
                "run_id": "run-7",
                "write_performed": False,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    monkeypatch.setattr(d1_lanes, "StageSelectionConsumer", FakeConsumer)
    result = d1_lanes._stage_inputs(
        tmp_path / "data", "20260818", stage_selection_root=tmp_path / "selection"
    )
    assert requested == [
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
    ]
    assert result["STAGE_1445_1500"]["selection_status"] == "READY"
    assert result["STAGE_1445_1500"]["artifact_id"] == "source-artifact-7"
    assert result["STAGE_1445_1500"]["run_id"] == "source-run-7"


def test_d1_stage_bridge_preserves_a_market_gaps_through_stage7_source_projection() -> None:
    gaps = [
        "PyTDX HQ exact-date/window coverage incomplete: completed=32/32",
        "PyTDX HQ batch coverage incomplete: completed=179/179",
    ]
    selection = {
        "status": "PARTIAL_WITH_ROWS",
        "trade_date": "20260911",
        "stage_id": "STAGE_1445_1500",
        "cannot_confirm": ["TOP_LEVEL_GAP", gaps[0]],
        "markets": {
            "A_SHARE": {
                "status": "PARTIAL_WITH_ROWS",
                "selection_status": "PARTIAL_WITH_ROWS",
                "run_id": "run-a",
                "artifact_id": "artifact-a",
                "requested_rows": 179,
                "source_rows": 176,
                "selected_rows": 10,
                "coverage_ratio": 0.055866,
                "missing_symbols": ["A.000660"],
                "rows": [{"code": "A.600000", "rank": 1}],
                "cannot_confirm": gaps,
            }
        },
    }

    payload = d1_lanes._stage_selection_payload(
        selection, "20260911", "STAGE_1445_1500"
    )
    assert payload["selection_status"] == "PARTIAL_WITH_ROWS"
    assert payload["cannot_confirm"] == ["TOP_LEVEL_GAP", *gaps]
    assert payload["market_status"] == {"A_SHARE": "PARTIAL_WITH_ROWS"}
    assert payload["source_summary"]["cannot_confirm"] == ["TOP_LEVEL_GAP", *gaps]
    assert payload["source_summary"]["quote_coverage"]["A_SHARE"] == {
        "coverage_ratio": 0.055866,
        "missing_symbols": ["A.000660"],
        "requested_rows": 179,
        "selected_rows": 10,
        "source_rows": 176,
    }

    stage_inputs = {
        stage_id: {**payload, "stage_id": stage_id}
        for stage_id in (
            "STAGE_0940_0945",
            "STAGE_0945_1030",
            "STAGE_1300_1315",
            "STAGE_1445_1500",
        )
    }
    projected = d1_source._stage7_source_evidence(stage_inputs)
    assert projected["source_summary_cannot_confirm"] == ["TOP_LEVEL_GAP", *gaps]
    assert projected["market_status"] == {"A_SHARE": "PARTIAL_WITH_ROWS"}
    assert projected["quote_coverage"]["A_SHARE"]["source_rows"] == 176
    assert projected["cannot_confirm"] == [
        "TOP_LEVEL_GAP",
        *gaps,
        "STAGE7_MARKET_STATUS:A_SHARE=PARTIAL_WITH_ROWS",
    ]


def test_d1_stage7_manifest_retains_market_gap_and_partial_status(
    tmp_path: Path,
) -> None:
    gap = "PyTDX HQ batch coverage incomplete: completed=179/179"
    stage_payload = {
        "schema_version": "v3_5.stage_input_from_stage_center.v1",
        "trade_date": "20260911",
        "stage_id": "STAGE_1445_1500",
        "selection_status": "PARTIAL_WITH_ROWS",
        "rows": {"A": [{"code": "A.600000", "pool_rank": 1, "pool_score": 1}], "HK": []},
        "source_summary": {
            "quote_coverage": {
                "A_SHARE": {
                    "coverage_ratio": 0.055866,
                    "missing_symbols": ["A.000660"],
                    "requested_rows": 179,
                    "selected_rows": 10,
                    "source_rows": 176,
                }
            },
            "cannot_confirm": [gap],
        },
        "market_status": {"A_SHARE": "PARTIAL_WITH_ROWS"},
        "cannot_confirm": [gap],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    stage_inputs = {
        stage_id: {**stage_payload, "stage_id": stage_id}
        for stage_id in (
            "STAGE_0940_0945",
            "STAGE_0945_1030",
            "STAGE_1300_1315",
            "STAGE_1445_1500",
        )
    }
    plate = {
        "result": "success",
        "html": (
            "<div class='list-group-item ztitem'><b>测试主题</b>"
            "<table><tr style='row'><td>测试股</td><td>600000</td>"
            "<td>10.0</td><td>1.0%</td></tr></table></div>"
        ),
    }

    result = d1_source.materialize_d1_review_sources(
        trade_date="20260911",
        public_files={"plate.json": json.dumps(plate).encode("utf-8")},
        public_manifest_sha256="public-manifest-sha",
        selector_rows=[
            {
                "trade_date": "20260911",
                "ts_code": "600000.SH",
                "name": "测试股",
                "pct_chg": 1.0,
                "amount": 100_000_000,
            }
        ],
        selector_sha256="selector-sha",
        stage_inputs=stage_inputs,
        output_dir=tmp_path / "d1-source",
    )

    manifest = json.loads(
        (tmp_path / "d1-source" / "stage7_tail_replay.manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["status"] == "READY"
    assert result["trade_date"] == "20260911"
    assert result["counts"]["stage7_tail_replay"] == 1
    assert manifest["market_status"] == {"A_SHARE": "PARTIAL_WITH_ROWS"}
    assert manifest["quote_coverage"]["A_SHARE"]["source_rows"] == 176
    assert gap in manifest["source_summary_cannot_confirm"]
    assert gap in manifest["cannot_confirm"]
    assert "STAGE7_MARKET_STATUS:A_SHARE=PARTIAL_WITH_ROWS" in manifest["cannot_confirm"]
    for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
        assert result[flag] is False
        assert manifest[flag] is False


def test_d1_stage_input_local_empty_uses_explicit_stage_selection_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stage_root = tmp_path / "data" / "stage_inputs" / "20260818"
    stage_root.mkdir(parents=True)
    (stage_root / "STAGE_1445_1500.json").write_text(
        json.dumps({
            "schema_version": "v3_5.stage_input.v1",
            "trade_date": "20260818",
            "stage_id": "STAGE_1445_1500",
            "rows": {"A": [], "HK": []},
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }),
        encoding="utf-8",
    )
    observed: list[str] = []

    class FakeConsumer:
        def __init__(self, root: Path) -> None:
            assert Path(root) == tmp_path / "selection"

        def get(self, trade_date: str, stage_id: str, *, markets=None) -> dict:
            observed.append(stage_id)
            return {
                "status": "PARTIAL_WITH_ROWS",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": {"A_SHARE": {"rows": [{"code": "000001", "rank": 1, "run_id": "run-a"}]}},
                "artifact_id": "artifact-shared",
                "run_id": "run-shared",
                "cannot_confirm": [],
            }

    monkeypatch.setattr(d1_lanes, "StageSelectionConsumer", FakeConsumer)
    result = d1_lanes._stage_inputs(
        tmp_path / "data", "20260818", stage_selection_root=tmp_path / "selection"
    )

    assert result["STAGE_1445_1500"]["selection_status"] == "PARTIAL_WITH_ROWS"
    assert result["STAGE_1445_1500"]["run_id"] == "run-shared"
    assert observed == [
        "STAGE_0940_0945",
        "STAGE_0945_1030",
        "STAGE_1300_1315",
        "STAGE_1445_1500",
    ]


def test_d1_stage_input_valid_local_rows_take_precedence_over_shared_selection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    stage_root = tmp_path / "data" / "stage_inputs" / "20260818"
    stage_root.mkdir(parents=True)
    native = {
        "schema_version": "v3_5.stage_input.v1",
        "trade_date": "20260818",
        "stage_id": "STAGE_1445_1500",
        "rows": {"A": [{"code": "000002", "rank": 1}], "HK": []},
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    (stage_root / "STAGE_1445_1500.json").write_text(json.dumps(native), encoding="utf-8")

    class FakeConsumer:
        def __init__(self, root: Path) -> None:
            pass

        def get(self, trade_date: str, stage_id: str, *, markets=None) -> dict:
            if stage_id == "STAGE_1445_1500":
                raise AssertionError("valid native stage input must take precedence")
            return {
                "status": "PARTIAL_WITH_ROWS",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": {"A_SHARE": {"rows": [{"code": "000003", "rank": 1}]}},
                "artifact_id": "artifact-shared",
                "run_id": "run-shared",
                "cannot_confirm": [],
            }

    monkeypatch.setattr(d1_lanes, "StageSelectionConsumer", FakeConsumer)
    result = d1_lanes._stage_inputs(
        tmp_path / "data", "20260818", stage_selection_root=tmp_path / "selection"
    )
    assert result["STAGE_1445_1500"]["rows"]["A"][0]["code"] == "000002"


def test_stage_center_milestone_keeps_a_partial_status_and_reads_only_a_market(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[tuple[str, ...] | None] = []

    class FakeConsumer:
        def __init__(self, root: Path) -> None:
            assert Path(root) == tmp_path / "selection"

        def get(self, trade_date: str, stage_id: str, *, markets=None) -> dict:
            assert trade_date == "20260818"
            assert stage_id == "STAGE_1445_1500"
            observed.append(tuple(markets or ()))
            return {
                "status": "PARTIAL_WITH_ROWS",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": {"A_SHARE": {"rows": [{"code": "000001"}]}},
                "artifact_id": "artifact-a",
                "run_id": "run-a",
                "cannot_confirm": ["HK_CONNECT_SELECTION_MISSING"],
            }

    monkeypatch.setattr(run_stage_center_milestone, "StageSelectionConsumer", FakeConsumer)
    result = run_stage_center_milestone.run_milestone(
        node="FUPAN_CLOSE_MATERIALS",
        date="20260818",
        data_root=tmp_path / "data",
        selection_root=tmp_path / "selection",
    )
    assert observed == [("A_SHARE",)]
    assert result["status"] == "PARTIAL_WITH_ROWS"
    assert result["source_write_performed"] is False
    assert result["receipt_write_performed"] is True


def test_daily_materialize_verifies_all_eight_stage_envelopes_without_producing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    observed: list[str] = []

    class FakeConsumer:
        def __init__(self, root: Path) -> None:
            assert Path(root) == tmp_path / "selection"

        def get(self, trade_date: str, stage_id: str, *, markets=None) -> dict:
            observed.append(stage_id)
            return {
                "status": "READY",
                "trade_date": trade_date,
                "stage_id": stage_id,
                "markets": {},
                "artifact_id": f"artifact-{stage_id}",
                "run_id": "run-8",
                "write_performed": False,
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }

    monkeypatch.setattr(daily_materialize, "StageSelectionConsumer", FakeConsumer)
    monkeypatch.setattr(
        daily_materialize,
        "_run_module",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("daily consume-only path must not run stage producer")
        ),
    )
    context = daily_materialize.DailyContext(
        business_date="20260818",
        target_date="20260819",
        data_root=tmp_path / "data",
        shared_data_root=tmp_path / "shared",
        selector_data_root=tmp_path / "selector",
        stage_selection_root=tmp_path / "selection",
    )

    result = daily_materialize._materialize_stages(context)

    assert result["status"] == "SUCCEEDED"
    assert observed == list(daily_materialize.FROZEN_STAGE_IDS)
    assert all(item["write_performed"] is False for item in result["stages"].values())


def test_hourly_same_slot_reuses_exact_existing_payload_when_only_timestamps_differ(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "incoming" / "1000.json"
    existing = {
        "source_manifest": {"generated_at": "2026-08-18T10:00:00+08:00", "published_at": "2026-08-18T09:59:00+08:00"},
        "stock_research_timeline": [{"stock_code": "000001", "crawl_time": "2026-08-18T10:00:00+08:00", "title": "same"}],
        "hourly_research": {"latest_slot": "1000", "row_count": 1},
    }
    changed_timestamps = {
        "source_manifest": {"generated_at": "2026-08-18T10:00:59+08:00", "published_at": "2026-08-18T09:59:00+08:00"},
        "stock_research_timeline": [{"stock_code": "000001", "crawl_time": "2026-08-18T10:00:59+08:00", "title": "same"}],
        "hourly_research": {"latest_slot": "1000", "row_count": 1},
    }
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(existing, sort_keys=True), encoding="utf-8")

    reused = hourly_input._atomic_json(destination, changed_timestamps)

    assert reused == destination
    assert json.loads(destination.read_text(encoding="utf-8")) == existing


def test_hourly_same_slot_rejects_materially_different_rows_and_source_times(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "incoming" / "1000.json"
    existing = {
        "source_manifest": {"published_at": "2026-08-18T09:59:00+08:00"},
        "stock_research_timeline": [{"stock_code": "000001", "source_published_at": "2026-08-18T09:30:00+08:00", "title": "same"}],
    }
    changed = {
        "source_manifest": {"published_at": "2026-08-18T09:59:00+08:00"},
        "stock_research_timeline": [{"stock_code": "000002", "source_published_at": "2026-08-18T09:31:00+08:00", "title": "different"}],
    }
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(existing, sort_keys=True), encoding="utf-8")
    with pytest.raises(ValueError, match="conflicting hourly research input"):
        hourly_input._atomic_json(destination, changed)


def test_zsxq_topic_url_requires_exactly_seventeen_ascii_digits() -> None:
    assert hourly_input._zsxq_topic_url("12345678901234567") == (
        "https://wx.zsxq.com/dweb2/index/topic_detail/12345678901234567"
    )
    assert hourly_input._zsxq_topic_url("1234567890123456") == ""
    assert hourly_input._zsxq_topic_url("123456789012345678") == ""
    assert hourly_input._zsxq_topic_url("1234567890123456x") == ""
    assert hourly_input._zsxq_topic_url("１２３４５６７８９０１２３４５６７") == ""


def test_zsxq_rows_preserve_audit_ids_and_keep_invalid_topic_url_local(
    tmp_path: Path,
) -> None:
    data_root = tmp_path.resolve()
    business_date = "20260818"
    slot = "1000"
    summary_path = data_root / "summary.json"
    summary_path.write_text(
        json.dumps(
            {
                "effective_topics": [
                    {
                        "topic_id": "12345678901234567",
                        "group_id": "28888888888888888",
                        "create_time": "2026-08-18T09:30:00+08:00",
                        "title": "有效话题",
                        "content_head": "有效内容",
                        "companies": [{"code": "000001", "name": "平安银行"}],
                    },
                    {
                        "topic_id": "bad-topic-id",
                        "group_id": "29999999999999999",
                        "create_time": "2026-08-18T09:31:00+08:00",
                        "title": "无效话题",
                        "content_head": "无效内容",
                        "companies": [{"code": "000002", "name": "万科A"}],
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    status_path = (
        data_root
        / "research_module"
        / "runtime_outputs"
        / "zsxq_hourly"
        / business_date
        / slot
        / f"v35_zsxq_hourly_status_{business_date}_{slot}.json"
    )
    status_path.parent.mkdir(parents=True)
    status_path.write_text(
        json.dumps(
            {
                "slot": slot,
                "status": "READY",
                "fetch_ok": True,
                "fetched_at": "2026-08-18T10:00:00+08:00",
                "paths": {"summary": str(summary_path)},
                "cannot_confirm": ["SHARED_BOUNDARY"],
            }
        ),
        encoding="utf-8",
    )

    rows, gaps = hourly_input._zsxq_rows(data_root, business_date, slot)

    assert gaps == ["SHARED_BOUNDARY"]
    valid, invalid = rows
    assert valid["topic_id"] == "12345678901234567"
    assert valid["group_id"] == "28888888888888888"
    assert valid["url"].endswith("/12345678901234567")
    assert valid["source_cannot_confirm"] == ["SHARED_BOUNDARY"]
    assert invalid["topic_id"] == "bad-topic-id"
    assert invalid["group_id"] == "29999999999999999"
    assert invalid["url"] == ""
    assert invalid["source_cannot_confirm"] == ["SHARED_BOUNDARY", "URL_REQUIRED"]
    assert gaps == ["SHARED_BOUNDARY"]


def test_task_status_exposes_nineteen_timeline_rows_with_truthful_receipt_fields(
    tmp_path: Path,
) -> None:
    status = build_task_status(
        load_workload_catalog(),
        ExecutionLedger(tmp_path / "ledger"),
        "20260818",
        now=datetime(2026, 8, 18, 23, 0),
    )

    rows = status["timeline_nodes"]
    assert len(rows) == 19
    assert [row["position"] for row in rows] == list(range(1, 20))
    assert all(row["production_allowed"] is False for row in rows)
    assert all("planned_slot" in row and "reason" in row for row in rows)
    assert rows[-1]["label"].endswith("8873 页面与接口验收")


def test_task_status_marks_future_same_day_close_nodes_pending_not_due(
    tmp_path: Path,
) -> None:
    status = build_task_status(
        load_workload_catalog(),
        ExecutionLedger(tmp_path / "ledger"),
        "20260819",
        now=datetime(2026, 8, 19, 14, 0),
    )
    assert all(row["status"] == "PENDING_NOT_DUE" for row in status["timeline_nodes"][8:])
    assert all(row["freshness"] == "NOT_DUE" for row in status["timeline_nodes"][8:])


def test_task_status_uses_verified_native_a_review_artifact_after_live_claim_gap(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    review = build_a_share_review(
        "20260818",
        big_picture=[],
        mainlines=[],
        core_stocks=[],
        observation_pool=[],
        trigger_rows=[],
        quality_gate_rows=[],
        source_sha256="a" * 64,
        source_role="V3_5_NATIVE_CLOSE_MODEL",
    )
    AShareReviewStore(data_root).import_review(review)

    status = build_task_status(
        load_workload_catalog(),
        ExecutionLedger(tmp_path / "ledger"),
        "20260818",
        now=datetime(2026, 8, 18, 23, 0),
        data_root=data_root,
    )
    row = next(item for item in status["timeline_nodes"] if item["position"] == 12)

    assert row["status"] == "BACKFILLED_ARTIFACT_READY"
    assert row["reason"] == "EXACT_DATE_A_SHARE_REVIEW_VERIFIED"
    assert row["result_code"] == "BACKFILLED_ARTIFACT_READY"
    assert row["receipt_path"] == "a_share_reviews/receipts/20260818.json"
    assert row["freshness"] == "CURRENT"


def test_task_status_rejects_missing_or_tampered_a_review_artifact_fallback(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    review = build_a_share_review(
        "20260818",
        big_picture=[],
        mainlines=[],
        core_stocks=[],
        observation_pool=[],
        trigger_rows=[],
        quality_gate_rows=[],
        source_sha256="b" * 64,
        source_role="V3_5_NATIVE_CLOSE_MODEL",
    )
    AShareReviewStore(data_root).import_review(review)
    (data_root / "a_share_reviews" / "20260818.json").write_text("{}", encoding="utf-8")

    status = build_task_status(
        load_workload_catalog(),
        ExecutionLedger(tmp_path / "ledger"),
        "20260818",
        now=datetime(2026, 8, 18, 23, 0),
        data_root=data_root,
    )
    row = next(item for item in status["timeline_nodes"] if item["position"] == 12)

    assert row["status"] == "CANNOT_CONFIRM"
    assert row["receipt_path"] is None
    assert row["reason"] == "A_SHARE_REVIEW_ARTIFACT_INVALID"


def test_task_status_keeps_future_a_review_pending_even_when_artifact_exists(
    tmp_path: Path,
) -> None:
    data_root = tmp_path / "data"
    review = build_a_share_review(
        "20260819",
        big_picture=[],
        mainlines=[],
        core_stocks=[],
        observation_pool=[],
        trigger_rows=[],
        quality_gate_rows=[],
        source_sha256="c" * 64,
        source_role="V3_5_NATIVE_CLOSE_MODEL",
    )
    AShareReviewStore(data_root).import_review(review)

    status = build_task_status(
        load_workload_catalog(),
        ExecutionLedger(tmp_path / "ledger"),
        "20260819",
        now=datetime(2026, 8, 19, 14, 0),
        data_root=data_root,
    )
    row = next(item for item in status["timeline_nodes"] if item["position"] == 12)

    assert row["status"] == "PENDING_NOT_DUE"
    assert row["freshness"] == "NOT_DUE"
