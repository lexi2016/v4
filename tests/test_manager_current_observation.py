"""Read-only request-day HK observation tests bound to the captured 2026-10-02 artifacts."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil

from apps.api.v35_api.manager_workbench_router import ManagerWorkbenchResearchReader
from v4.manager_research import workspace, workspace_plan, workspace_projection


DATE = "20261002"
APP_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "manager_current_observation_20261002"
FIXTURE_SHAS = {
    "close_recapture.json": "3b5a84bbaae7d2b04f758691506f0665878b62bfb7f769f7c1746f13a2c3ec56",
    "close_recapture.receipt.json": "540a7818a50ccf516658bd38f5df14a1abd5c84dc3f73d068d626094bea50994",
    "close_recapture.candidates.json": "548804c308701e694f575deca2a3a361203bfaf3255aac4edca53ac065d4e454",
    "inputs/close_recapture_pytdx.json": "a5b1484f0411529c8accaac0c7eeed56d1b9c35cdf335a009061c601e86ca3e3",
}
SAFETY = {
    "RESEARCH_ONLY": True,
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
    "natural_run": False,
    "observation_market": "HK_SECURITIES",
    "observation_market_state": "FULL_TRADING_DAY",
    "connect_market_state": "NON_TRADING_DAY",
    "official_close_status": "CANNOT_CONFIRM",
    "pool_eligibility_for_observation_market": "CANNOT_CONFIRM",
}


def _seed_state(root: Path) -> Path:
    state_root = root / "manager_auto_research"
    day = state_root / "workbench_research" / DATE
    for rel, expected_sha in FIXTURE_SHAS.items():
        source = FIXTURE_ROOT / rel
        assert hashlib.sha256(source.read_bytes()).hexdigest() == expected_sha, f"fixture SHA changed: {rel}"
        target = day / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return state_root


def _mutate_artifact(state_root: Path, rel: str, mutate) -> None:
    path = state_root / "workbench_research" / DATE / rel
    value = json.loads(path.read_text())
    mutate(value)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def _reseal_candidate_with_late_availability(state_root: Path) -> None:
    day = state_root / "workbench_research" / DATE
    overlay_path = day / "close_recapture.candidates.json"
    overlay = json.loads(overlay_path.read_text())
    overlay["rows"][0]["available_at"] = "2026-10-02T17:55:30+08:00"
    overlay_raw = (json.dumps(overlay, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    overlay_path.write_bytes(overlay_raw)
    overlay_sha = hashlib.sha256(overlay_raw).hexdigest()

    artifact_path = day / "close_recapture.json"
    artifact = json.loads(artifact_path.read_text())
    artifact["candidate_overlay"]["sha256"] = overlay_sha
    artifact_raw = (json.dumps(artifact, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    artifact_path.write_bytes(artifact_raw)

    receipt_path = day / "close_recapture.receipt.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["candidate_overlay_sha256"] = overlay_sha
    receipt["artifact_sha256"] = hashlib.sha256(artifact_raw).hexdigest()
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")


def test_explicit_requested_day_reader_displays_verified_manual_rows_and_default_stays_closed(tmp_path):
    reader = ManagerWorkbenchResearchReader(_seed_state(tmp_path))

    default = reader.read_close_recapture(DATE)
    assert default["status"] == "FAILED"
    assert default["candidate_overlay"]["rows"] == []

    display = reader.read_requested_day_hk_observation(DATE)
    assert display["status"] == "READY"
    assert display["source_trade_date"] == DATE
    assert display["requested_trade_date"] == DATE
    assert display["target_trade_date"] == "20261008"
    assert display["plan_trade_date"] == "20261008"
    assert display["capture_mode"] == "LATE_OBSERVATION"
    assert display["execution_kind"] == "MANUAL_HK_SECURITIES_SESSION_OBSERVATION"
    assert display["observation_type"] == "HK_SECURITIES_SESSION_MINUTE_OBSERVATION"
    assert display["candidate_overlay_verified"] is True
    assert display["snapshot_verified"] is True
    assert display["candidate_overlay"]["count"] == 100
    assert len(display["candidate_overlay"]["rows"]) == 100
    assert display["pool"]["role"] == "HK_CONNECT_D1_TOP100_0_2"
    assert display["pool_eligibility_for_observation_market"] == "CANNOT_CONFIRM"
    for key, expected in SAFETY.items():
        if isinstance(expected, bool):
            assert display[key] is expected
        else:
            assert display[key] == expected


def test_workspace_keeps_20260930_planning_read_separate_from_20261002_display(tmp_path):
    class RecordingReader(ManagerWorkbenchResearchReader):
        calls = []

        def read_close_recapture(self, trade_date):
            self.calls.append(("planning-default", trade_date))
            return super().read_close_recapture(trade_date)

        def read_requested_day_hk_observation(self, trade_date):
            self.calls.append(("requested-day-display", trade_date))
            return super().read_requested_day_hk_observation(trade_date)

    reader = RecordingReader(_seed_state(tmp_path))
    context = workspace_plan.plan_context(
        DATE, now=datetime.fromisoformat("2026-10-02T18:00:00+08:00")
    )
    assert context["plan_trade_date"] == DATE
    assert context["market_session"] == "20260930"

    planning, requested = workspace._read_close_recapture_inputs(reader, DATE, context)
    assert reader.calls == [("planning-default", "20260930"), ("requested-day-display", DATE)]
    assert planning["status"] == "NOT_RUN"
    assert planning["source_trade_date"] == "20260930"
    assert requested["status"] == "READY"
    assert requested["source_trade_date"] == DATE

    result = workspace_projection.build_workspace(
        DATE,
        catalyst={"status": "NOT_RUN", "target_trade_date": DATE, "cards": []},
        close_recapture=planning,
        requested_day_close_recapture=requested,
        plan_context=context,
    )
    displayed = result["close_recapture_evidence"]
    planner_input = result["planning_close_recapture_evidence"]
    assert displayed["source_trade_date"] == DATE
    assert displayed["observation_type"] == "HK_SECURITIES_SESSION_MINUTE_OBSERVATION"
    assert displayed["candidate_overlay"]["count"] == 100
    assert displayed["planner_availability"] == "DISPLAY_ONLY_NOT_PLANNER_INPUT"
    assert displayed["planner_eligible_context"] is False
    assert displayed["formal_recommendation_effect"] == "NONE"
    assert displayed["buy_gate_effect"] == "NONE"
    assert planner_input["source_trade_date"] == "20260930"
    assert planner_input["status"] == "NOT_RUN"
    assert planner_input["planner_eligible_context"] is False
    assert result["summary"]["stock_count"] == 0
    assert result["summary"]["formal_recommendation_count"] == 0
    assert result["focus_symbols"] == []


def test_requested_day_reader_rejects_wrong_date_pit_sha_and_manual_label_mutations(tmp_path):
    state = _seed_state(tmp_path)
    _mutate_artifact(state, "close_recapture.json", lambda value: value.update(source_trade_date="20261001"))
    assert ManagerWorkbenchResearchReader(state).read_requested_day_hk_observation(DATE)["status"] == "FAILED"

    state = _seed_state(tmp_path / "pit")
    _mutate_artifact(state, "close_recapture.json", lambda value: value.update(
        target_trade_date="20260930", plan_trade_date="20260930"))
    assert ManagerWorkbenchResearchReader(state).read_requested_day_hk_observation(DATE)["status"] == "FAILED"

    state = _seed_state(tmp_path / "sha")
    _mutate_artifact(state, "close_recapture.receipt.json", lambda value: value.update(artifact_sha256="0" * 64))
    assert ManagerWorkbenchResearchReader(state).read_requested_day_hk_observation(DATE)["status"] == "FAILED"

    state = _seed_state(tmp_path / "label")
    _mutate_artifact(state, "close_recapture.json", lambda value: value.update(
        observation_type="PYTDX_EXHQ_MINUTE_STAGE_OBSERVATION"))
    reader = ManagerWorkbenchResearchReader(state)
    assert reader.read_requested_day_hk_observation(DATE)["status"] == "FAILED"
    assert reader.read_close_recapture(DATE)["status"] == "FAILED"


def test_requested_day_reader_does_not_reuse_artifact_for_another_day(tmp_path):
    reader = ManagerWorkbenchResearchReader(_seed_state(tmp_path))
    other_date = reader.read_requested_day_hk_observation("20261003")
    assert other_date["status"] == "NOT_RUN"
    assert other_date["source_trade_date"] is None
    assert other_date["requested_trade_date"] == "20261003"
    assert other_date["candidate_overlay"]["rows"] == []


def test_read_only_workspace_service_get_displays_requested_day_without_planning_rows(tmp_path):
    from v4.manager_research import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore

    class EmptyStageReader:
        def read(self, trade_date):
            return {"status": "NOT_RUN", "target_trade_date": trade_date, "rows": []}

    state_root = _seed_state(tmp_path)
    reader = ManagerWorkbenchResearchReader(state_root)
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path / "manager-store"),
        EmptyStageReader(),
        None,
        close_observation_reader=reader,
        catalyst_data_root=tmp_path / "catalysts",
        workspace_ledger_root=tmp_path / "ledger",
        workspace_security_master_root=tmp_path / "security-master",
        workspace_screen_authority_root=tmp_path / "screen-authority",
    )
    try:
        result = service.get_workspace(
            DATE,
            view="dynamic",
            now=datetime.fromisoformat("2026-10-02T18:00:00+08:00"),
        )
    finally:
        service.close()

    displayed = result["close_recapture_evidence"]
    planning = result["planning_close_recapture_evidence"]
    assert displayed["status"] == "READY"
    assert displayed["source_trade_date"] == DATE
    assert displayed["requested_trade_date"] == DATE
    assert displayed["observation_type"] == "HK_SECURITIES_SESSION_MINUTE_OBSERVATION"
    assert displayed["candidate_overlay"]["count"] == 100
    assert displayed["planner_eligible_context"] is False
    assert displayed["formal_recommendation_effect"] == "NONE"
    assert displayed["buy_gate_effect"] == "NONE"
    assert planning["status"] == "NOT_RUN"
    assert planning["source_trade_date"] == "20260930"
    assert result["summary"]["stock_count"] == 0
    assert result["focus_symbols"] == []
    assert result["run_accounting"]["natural_run_verified"] is False


def test_requested_day_display_obeys_workspace_as_of_cutoff(tmp_path):
    from v4.manager_research import ManagerResearchJobService
    from v4.manager_research.store import ManagerResearchStore

    class EmptyStageReader:
        def read(self, trade_date):
            return {"status": "NOT_RUN", "target_trade_date": trade_date, "rows": []}

    state_root = _seed_state(tmp_path)
    service = ManagerResearchJobService(
        ManagerResearchStore(tmp_path / "manager-store"),
        EmptyStageReader(),
        None,
        close_observation_reader=ManagerWorkbenchResearchReader(state_root),
        catalyst_data_root=tmp_path / "catalysts",
        workspace_ledger_root=tmp_path / "ledger",
        workspace_security_master_root=tmp_path / "security-master",
        workspace_screen_authority_root=tmp_path / "screen-authority",
    )
    try:
        early = service.get_workspace(
            DATE,
            view="dynamic",
            now=datetime.fromisoformat("2026-10-02T16:00:00+08:00"),
        )
        after_close = service.get_workspace(
            DATE,
            view="dynamic",
            now=datetime.fromisoformat("2026-10-02T18:00:00+08:00"),
        )
    finally:
        service.close()

    early_display = early["close_recapture_evidence"]
    assert early["read_context"]["as_of"] == "2026-10-02T16:00:00+08:00"
    assert early_display["status"] == "CANNOT_CONFIRM"
    assert early_display["candidate_overlay"]["count"] == 0
    assert early_display["candidate_overlay"]["rows"] == []
    assert early_display["availability_gate"]["status"] == "AFTER_CUTOFF"
    assert early_display["availability_gate"]["source_status"] == "READY"
    assert early_display["availability_gate"]["research_cutoff"] == "2026-10-02T16:00:00+08:00"
    assert early_display["availability_gate"]["available_at"] == "2026-10-02T17:55:22.905209+08:00"
    assert early_display["availability_gate"]["verified_source_row_count"] == 100
    assert early_display["candidate_overlay"]["sha256"] == FIXTURE_SHAS["close_recapture.candidates.json"]
    assert "REQUESTED_DAY_OBSERVATION_AFTER_RESEARCH_CUTOFF" in early_display["cannot_confirm"]
    assert early["planning_close_recapture_evidence"]["source_trade_date"] == "20260930"
    assert early["planning_close_recapture_evidence"]["status"] == "NOT_RUN"

    after_close_display = after_close["close_recapture_evidence"]
    assert after_close["read_context"]["as_of"] == "2026-10-02T18:00:00+08:00"
    assert after_close_display["status"] == "READY"
    assert after_close_display["candidate_overlay"]["count"] == 100
    assert len(after_close_display["candidate_overlay"]["rows"]) == 100
    assert after_close_display["availability_gate"]["status"] == "AVAILABLE_AT_CUTOFF"
    assert after_close["planning_close_recapture_evidence"]["source_trade_date"] == "20260930"
    assert after_close["summary"]["stock_count"] == 0
    assert after_close["focus_symbols"] == []
    assert after_close["run_accounting"]["natural_run_verified"] is False

    late_candidate_state = _seed_state(tmp_path / "late-candidate")
    _reseal_candidate_with_late_availability(late_candidate_state)
    late_candidate = ManagerWorkbenchResearchReader(late_candidate_state).read_requested_day_hk_observation(DATE)
    assert late_candidate["status"] == "FAILED"
    assert late_candidate["candidate_overlay"]["rows"] == []
