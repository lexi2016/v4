from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ops import run_v35_macos_scheduler as scheduler


SHANGHAI = ZoneInfo("Asia/Shanghai")


def _complete_post_close_slots(root, slots):
    for slot in slots:
        receipt = root / "receipts" / "live" / "20260817" / slot / "prior.dispatch-receipt.json"
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(
            json.dumps({"status": "SUCCEEDED", "finished_at": "2026-08-17T13:40:00Z"}),
            encoding="utf-8",
        )


def test_due_slot_uses_exact_current_slot_without_catchup(tmp_path):
    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 14, 0, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due == {
        "business_date": "20260817",
        "observed_slot": "1400",
        "slot": "1400",
        "catchup": False,
        "lag_minutes": 0,
    }


def test_due_slot_recovers_the_latest_missing_hour_after_wake(tmp_path):
    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 13, 23, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due == {
        "business_date": "20260817",
        "observed_slot": "1323",
        "slot": "1300",
        "catchup": True,
        "lag_minutes": 23,
    }


def test_due_slot_keeps_1130_catchup_inside_its_eight_minute_window(tmp_path):
    exact = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 11, 30, 0, tzinfo=SHANGHAI),
        ledger_root=tmp_path / "exact",
    )
    at_five = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 11, 35, 0, tzinfo=SHANGHAI),
        ledger_root=tmp_path / "five",
    )
    at_eight = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 11, 38, 59, tzinfo=SHANGHAI),
        ledger_root=tmp_path / "eight",
    )
    after_deadline = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 11, 39, 0, tzinfo=SHANGHAI),
        ledger_root=tmp_path / "after",
    )

    assert exact["slot"] == "1130" and exact["catchup"] is False
    assert at_five["slot"] == "1130" and at_five["lag_minutes"] == 5
    assert at_eight["slot"] == "1130" and at_eight["lag_minutes"] == 8
    assert after_deadline["slot"] != "1130"
    assert after_deadline["slot"] == "1100"


def test_due_slot_does_not_repeat_an_hour_with_an_existing_claim(tmp_path):
    claim = tmp_path / "claims" / "live" / "20260817" / "1300" / "dispatch.claim.json"
    claim.parent.mkdir(parents=True)
    claim.write_text(json.dumps({"slot": "1300"}), encoding="utf-8")

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 13, 23, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due["slot"] == "1323"
    assert due["catchup"] is False


def test_due_slot_keeps_current_hourly_slot_fair_when_1500_retry_is_ready(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1500",
        run_id="retryable-1500",
        finished_at="2026-08-17T07:55:00Z",
        failure_class="UPSTREAM_NOT_READY",
    )

    at_1600 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 16, 0, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )
    at_1700 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 17, 0, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert at_1600["slot"] == "1600"
    assert at_1600["catchup"] is False
    assert at_1700["slot"] == "1700"
    assert at_1700["catchup"] is False


def test_due_slot_keeps_exact_hk_research_panel_slot_fair_when_1500_retry_is_ready(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1500",
        run_id="retryable-1500",
        finished_at="2026-08-17T08:55:00Z",
        failure_class="UPSTREAM_NOT_READY",
    )
    _complete_post_close_slots(tmp_path, ("1700",))

    at_1720 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 17, 20, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert at_1720["slot"] == "1720"
    assert at_1720["catchup"] is False


def test_due_slot_recovers_research_panel_lanes_in_dependency_order(tmp_path):
    _complete_post_close_slots(tmp_path, ("1500", "1555", "1605", "1608", "1710"))
    at_1725 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 17, 25, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )
    assert at_1725["slot"] == "1700"
    assert at_1725["catchup"] is True

    _complete_post_close_slots(tmp_path, ("1700",))
    after_a = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 17, 25, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )
    assert after_a["slot"] == "1720"
    assert after_a["catchup"] is True

    _complete_post_close_slots(tmp_path, ("1720",))
    after_hk = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 17, 35, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )
    assert after_hk["slot"] == "1730"
    assert after_hk["catchup"] is True


def test_due_slot_prioritizes_missing_2140_critical_review_after_wake_until_midnight(tmp_path):
    _complete_post_close_slots(
        tmp_path,
        ("1500", "1555", "1605", "1608", "1700", "1710", "1720", "1730", "1800", "2030", "2040", "2050", "2105", "2108", "2110", "2115"),
    )
    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 22, 3, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due == {
        "business_date": "20260817",
        "observed_slot": "2203",
        "slot": "2140",
        "catchup": True,
        "lag_minutes": 23,
    }

    late_due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 23, 59, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )
    assert late_due["slot"] == "2140"
    assert late_due["catchup"] is True


def test_due_slot_critical_2140_receipt_unblocks_later_hourly_slot(tmp_path):
    _complete_post_close_slots(
        tmp_path,
        ("1500", "1555", "1605", "1608", "1700", "1710", "1720", "1730", "1800", "2030", "2040", "2050", "2105", "2108", "2110", "2115"),
    )
    receipt = tmp_path / "receipts" / "live" / "20260817" / "2140" / "ok.dispatch-receipt.json"
    receipt.parent.mkdir(parents=True)
    receipt.write_text(
        json.dumps({"status": "SUCCEEDED", "finished_at": "2026-08-17T13:40:00Z"}),
        encoding="utf-8",
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 22, 3, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due["slot"] == "2200"
    assert due["catchup"] is True


def test_due_slot_at_2140_is_exact_critical_slot(tmp_path):
    _complete_post_close_slots(
        tmp_path,
        ("1500", "1555", "1605", "1608", "1700", "1710", "1720", "1730", "1800", "2030", "2040", "2050", "2105", "2108", "2110", "2115"),
    )
    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 21, 40, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )
    assert due["slot"] == "2140"
    assert due["catchup"] is False


def test_due_slot_never_backfills_an_hour_older_than_the_fixed_window(tmp_path):
    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 14, 5, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
        catchup_window_minutes=4,
    )

    assert due["slot"] == "1405"
    assert due["catchup"] is False


def _failed_receipt_for_date(
    root, *, business_date: str, slot: str, run_id: str, finished_at: str, **extra
):
    path = (
        root
        / "receipts"
        / "live"
        / business_date
        / slot
        / f"{run_id}.dispatch-receipt.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": "FAILED", "finished_at": finished_at, "run_id": run_id, **extra}
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.mark.parametrize(
    ("failure_class", "attempt_state", "blocked"),
    (
        ("INTRADAY_REQUEST_ATTEMPTED", "REQUEST_ATTEMPTED", True),
        ("INTRADAY_ATTEMPT_UNKNOWN", "ATTEMPT_UNKNOWN", True),
        ("INTRADAY_NO_REQUEST", "FAILED_NO_REQUEST", False),
    ),
)
def test_intraday_attempt_state_controls_retry_before_release_reset(
    tmp_path, failure_class, attempt_state, blocked
):
    _failed_receipt_for_date(
        tmp_path,
        business_date="20260824",
        slot="0925",
        run_id="intraday-attempt",
        finished_at="2026-08-24T00:00:00Z",
        failure_class=failure_class,
        release_id="old-release",
        upstream_fingerprint="old-upstream",
        workload_results=[
            {
                "workload_id": "v4_intraday_research",
                "status": "FAILED",
                "failure_class": failure_class,
                "attempt_state": attempt_state,
            }
        ],
    )

    result = scheduler._slot_blocks_retry(
        tmp_path,
        "20260824",
        "0925",
        moment=datetime(2026, 8, 24, 9, 30, tzinfo=SHANGHAI),
        release_id="new-release",
        upstream_fingerprint="new-upstream",
    )
    assert result is blocked


def test_intraday_child_attempt_state_overrides_aggregate_no_request(tmp_path):
    _failed_receipt_for_date(
        tmp_path,
        business_date="20260914",
        slot="0925",
        run_id="contradictory-intraday-attempt",
        finished_at="2026-09-14T01:25:00Z",
        failure_class="INTRADAY_NO_REQUEST",
        workload_results=[
            {
                "workload_id": "v4_intraday_research",
                "status": "FAILED",
                "failure_class": "INTRADAY_NO_REQUEST",
                "attempt_state": "REQUEST_ATTEMPTED",
            }
        ],
    )

    assert scheduler._intraday_attempt_outcome(
        [
            {
                "failure_class": "INTRADAY_NO_REQUEST",
                "workload_results": [
                    {
                        "workload_id": "v4_intraday_research",
                        "status": "FAILED",
                        "failure_class": "INTRADAY_NO_REQUEST",
                        "attempt_state": "REQUEST_ATTEMPTED",
                    }
                ],
            }
        ]
    ) == "BLOCK"
    assert scheduler._slot_blocks_retry(
        tmp_path,
        "20260914",
        "0925",
        moment=datetime(2026, 9, 14, 9, 31, tzinfo=SHANGHAI),
    ) is True


@pytest.mark.parametrize(
    ("intraday_status", "attempt_state"),
    (("SUCCEEDED", ""), ("SUCCEEDED", "REQUEST_ATTEMPTED"), ("ALREADY_EXISTS", "")),
)
def test_successful_intraday_child_does_not_block_stage_retry(
    tmp_path, intraday_status, attempt_state
):
    _failed_receipt_for_date(
        tmp_path,
        business_date="20260824",
        slot="1500",
        run_id=f"stage-sibling-{intraday_status.lower()}",
        finished_at="2026-09-14T04:02:59Z",
        failure_class="UPSTREAM_NOT_READY",
        workload_results=[
            {
                "workload_id": "v4_intraday_research",
                "status": intraday_status,
                "attempt_state": attempt_state,
            },
            {
                "workload_id": "fupan_close_materials",
                "status": "FAILED",
                "failure_class": "UPSTREAM_NOT_READY",
                "attempt_state": "STAGE_GATE_FAILED",
            },
        ],
    )

    assert scheduler._slot_blocks_retry(
        tmp_path,
        "20260824",
        "1500",
        moment=datetime(2026, 9, 14, 13, 0, tzinfo=SHANGHAI),
    ) is False


@pytest.mark.parametrize(
    ("status", "attempt_state", "failure_class"),
    (
        ("FAILED", "REQUEST_IN_FLIGHT", "INTRADAY_ATTEMPT_UNKNOWN"),
        ("FAILED", "ATTEMPT_UNKNOWN", "INTRADAY_ATTEMPT_UNKNOWN"),
        ("", "", ""),
        ("SUCCEEDED", "REQUEST_IN_FLIGHT", ""),
        ("SUCCEEDED", "", "INTRADAY_ATTEMPT_UNKNOWN"),
    ),
)
def test_intraday_failed_or_malformed_child_blocks_stage_retry(
    status, attempt_state, failure_class
):
    result = scheduler._intraday_attempt_outcome(
        [
            {
                "failure_class": "UPSTREAM_NOT_READY",
                "workload_results": [
                    {
                        "workload_id": "v4_intraday_research",
                        "status": status,
                        "attempt_state": attempt_state,
                        "failure_class": failure_class,
                    },
                    {
                        "workload_id": "fupan_close_materials",
                        "status": "FAILED",
                        "failure_class": "UPSTREAM_NOT_READY",
                    },
                ],
            }
        ]
    )
    assert result == "BLOCK"


def test_0830_and_0840_have_independent_catchup_owners(tmp_path):
    at_0832 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 8, 32, tzinfo=SHANGHAI),
        ledger_root=tmp_path / "0830",
    )
    at_0842 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 8, 42, tzinfo=SHANGHAI),
        ledger_root=tmp_path / "0840",
    )

    assert at_0832 == {
        "business_date": "20260824",
        "observed_slot": "0832",
        "slot": "0830",
        "catchup": True,
        "lag_minutes": 2,
    }
    assert at_0842 == {
        "business_date": "20260824",
        "observed_slot": "0842",
        "slot": "0840",
        "catchup": True,
        "lag_minutes": 2,
    }


def test_0830_and_0840_claims_and_success_receipts_prevent_duplicate_catchup(
    tmp_path,
):
    for marker in ("claim", "success"):
        for slot, hour, minute in (("0830", 8, 32), ("0840", 8, 42)):
            ledger_root = tmp_path / marker / slot
            marker_root = ledger_root / (
                "claims" if marker == "claim" else "receipts"
            ) / "live" / "20260824" / slot
            marker_root.mkdir(parents=True, exist_ok=True)
            if marker == "claim":
                (marker_root / "dispatch.claim.json").write_text(
                    json.dumps({"slot": slot}), encoding="utf-8"
                )
            else:
                (marker_root / "success.dispatch-receipt.json").write_text(
                    json.dumps(
                        {
                            "status": "SUCCEEDED",
                            "finished_at": "2026-08-24T01:00:00Z",
                        }
                    ),
                    encoding="utf-8",
                )

            due = scheduler.resolve_due_slot(
                now=datetime(2026, 8, 24, hour, minute, tzinfo=SHANGHAI),
                ledger_root=ledger_root,
            )

            assert due["slot"] != slot
            assert due["catchup"] is True


def test_morning_stage_catchups_are_not_starved_by_a_retryable_0901(tmp_path):
    _failed_receipt_for_date(
        tmp_path,
        business_date="20260824",
        slot="0901",
        run_id="retryable-0901",
        finished_at="2026-08-24T00:00:00Z",
        failure_class="NETWORK",
    )

    at_0918 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 9, 18, tzinfo=SHANGHAI), ledger_root=tmp_path
    )
    assert at_0918["slot"] == "0915"
    assert at_0918["catchup"] is True
    assert at_0918["lag_minutes"] == 3

    after_0915_cutoff = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 9, 23, tzinfo=SHANGHAI), ledger_root=tmp_path
    )
    assert after_0915_cutoff["slot"] == "0901"
    assert after_0915_cutoff["slot"] != "0915"

    at_0928 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 9, 28, tzinfo=SHANGHAI), ledger_root=tmp_path
    )
    assert at_0928["slot"] == "0925"
    assert at_0928["catchup"] is True
    assert at_0928["lag_minutes"] == 3

    at_0943 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 9, 43, tzinfo=SHANGHAI), ledger_root=tmp_path
    )
    assert at_0943["slot"] == "0940"
    assert at_0943["catchup"] is True
    assert at_0943["lag_minutes"] == 3


def test_exact_0925_wins_over_an_older_0901_retry(tmp_path):
    _failed_receipt_for_date(
        tmp_path,
        business_date="20260824",
        slot="0901",
        run_id="retryable-0901",
        finished_at="2026-08-24T00:00:00Z",
        failure_class="NETWORK",
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 9, 25, tzinfo=SHANGHAI), ledger_root=tmp_path
    )

    assert due == {
        "business_date": "20260824",
        "observed_slot": "0925",
        "slot": "0925",
        "catchup": False,
        "lag_minutes": 0,
    }


def test_0915_catchup_has_a_hard_091959_deadline(tmp_path):
    before_cutoff = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 9, 19, 59, tzinfo=SHANGHAI), ledger_root=tmp_path
    )
    assert before_cutoff["slot"] == "0915"
    assert before_cutoff["catchup"] is True

    after_cutoff = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 9, 20, 0, tzinfo=SHANGHAI), ledger_root=tmp_path
    )
    assert after_cutoff["slot"] != "0915"


def test_morning_stage_catchup_claim_and_success_receipts_are_deduplicated(tmp_path):
    _failed_receipt_for_date(
        tmp_path,
        business_date="20260824",
        slot="0901",
        run_id="retryable-0901",
        finished_at="2026-08-24T00:00:00Z",
        failure_class="NETWORK",
    )
    claim = tmp_path / "claims" / "live" / "20260824" / "0925" / "dispatch.claim.json"
    claim.parent.mkdir(parents=True, exist_ok=True)
    claim.write_text(json.dumps({"slot": "0925"}), encoding="utf-8")

    claimed = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 9, 28, tzinfo=SHANGHAI), ledger_root=tmp_path
    )
    assert claimed["slot"] == "0901"

    claim.unlink()
    receipt = (
        tmp_path
        / "receipts"
        / "live"
        / "20260824"
        / "0925"
        / "success.dispatch-receipt.json"
    )
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(
        json.dumps({"status": "SUCCEEDED", "finished_at": "2026-08-24T01:25:00Z"}),
        encoding="utf-8",
    )

    succeeded = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 24, 9, 28, tzinfo=SHANGHAI), ledger_root=tmp_path
    )
    assert succeeded["slot"] == "0901"


def _failed_receipt(root, *, slot: str, run_id: str, finished_at: str, **extra):
    path = root / "receipts" / "live" / "20260817" / slot / f"{run_id}.dispatch-receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"status": "FAILED", "finished_at": finished_at, "run_id": run_id, **extra}
    path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )


def test_due_slot_retries_a_failed_hour_after_backoff_when_network_recovers(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1300",
        run_id="failed-1",
        finished_at="2026-08-17T05:10:00Z",
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 13, 23, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due["slot"] == "1300"
    assert due["catchup"] is True


def test_due_slot_waits_for_failed_hour_retry_backoff(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1300",
        run_id="failed-1",
        finished_at="2026-08-17T05:21:30Z",
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 13, 23, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due["slot"] == "1323"
    assert due["catchup"] is False


def test_due_slot_caps_automatic_failed_hour_retries(tmp_path):
    for index in range(3):
        _failed_receipt(
            tmp_path,
            slot="1300",
            run_id=f"failed-{index}",
            finished_at=f"2026-08-17T05:0{index}:00Z",
        )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 13, 23, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due["slot"] == "1323"
    assert due["catchup"] is False


def test_due_slot_legacy_cap_resets_for_new_release(tmp_path):
    for index in range(3):
        _failed_receipt(
            tmp_path,
            slot="1300",
            run_id=f"legacy-{index}",
            finished_at=f"2026-08-17T05:0{index}:00Z",
        )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 13, 23, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
        release_id="20260820T104322Z-v35-coordinated-recurrence",
    )

    assert due["slot"] == "1300"
    assert due["catchup"] is True


def test_due_slot_typed_retryable_is_not_permanently_capped(tmp_path):
    for index in range(4):
        _failed_receipt(
            tmp_path,
            slot="1300",
            run_id=f"network-{index}",
            finished_at=f"2026-08-17T05:0{index}:00Z",
            failure_class="NETWORK",
            release_id="20260820T104322Z-v35-coordinated-recurrence",
            upstream_fingerprint="upstream-v1",
        )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 13, 23, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
        release_id="20260820T104322Z-v35-coordinated-recurrence",
        upstream_fingerprint="upstream-v1",
    )

    assert due["slot"] == "1300"
    assert due["catchup"] is True


def test_main_dispatches_the_resolved_catchup_slot_and_emits_observation(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.setenv("V35_RELEASE_ID", "20260820T104322Z-v35-coordinated-recurrence")
    monkeypatch.setenv("V35_UPSTREAM_FINGERPRINT", "upstream-v1")
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260817", "1323"))
    resolved_kwargs = {}

    def resolve_due_slot(**kwargs):
        resolved_kwargs.update(kwargs)
        return {
            "business_date": "20260817",
            "observed_slot": "1323",
            "slot": "1300",
            "catchup": True,
            "lag_minutes": 23,
        }

    monkeypatch.setattr(
        scheduler,
        "resolve_due_slot",
        resolve_due_slot,
    )
    monkeypatch.setattr(
        scheduler,
        "compute_dates",
        lambda **_kwargs: {
            "business_date": "20260817",
            "scheduled_date": "20260817",
            "target_date": "20260817",
        },
    )
    observed = {}

    def run_scheduled_slot(**kwargs):
        observed.update(kwargs)
        return {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(scheduler, "run_scheduled_slot", run_scheduled_slot)

    assert scheduler.main(
        [
            "--data-root",
            str(tmp_path / "data"),
            "--ledger-root",
            str(tmp_path / "ledger"),
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert resolved_kwargs["release_id"] == "20260820T104322Z-v35-coordinated-recurrence"
    assert resolved_kwargs["upstream_fingerprint"] == "upstream-v1"
    assert observed["slot"] == "1300"
    assert payload["observed_slot"] == "1323"
    assert payload["catchup"] == {
        "applied": True,
        "lag_minutes": 23,
        "scheduled_slot": "1300",
    }


def test_main_non_trading_stage_slot_skips_candidate_prerequisite_and_delegates_to_dispatcher(
    monkeypatch, tmp_path, capsys
):
    """A weekend stage slot must reach the dispatcher without materializing inputs."""

    calls: list[str] = []
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260823", "1500"))
    monkeypatch.setattr(
        scheduler,
        "ensure_stage_candidate_input",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-trading stage slots must not materialize candidate input")
        ),
    )
    def fake_run(**kwargs):
        from contracts.runtime_tasks import DispatchMode, DispatchRequest
        from infrastructure.scheduling.catalog import load_workload_catalog

        calls.append(kwargs["slot"])
        workload = next(
            item for item in load_workload_catalog().workloads
            if item.workload_id == "fupan_close_materials"
        )
        request = DispatchRequest("20260823", "20260823", "20260823", "1500", DispatchMode.LIVE)
        kwargs["workload_guard"](workload, request, None)
        return {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(scheduler, "run_scheduled_slot", fake_run)

    assert scheduler.main(
        [
            "--data-root",
            str(tmp_path / "data"),
            "--ledger-root",
            str(tmp_path / "ledger"),
            "--stage-selection-root",
            str(tmp_path / "stage-selection"),
            "--date",
            "20260823",
            "--slot",
            "1500",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SUCCEEDED"
    assert payload["slot"] == "1500"
    assert calls == ["1500"]
    assert payload["shared_acquisition"]["status"] == "SKIPPED_NON_TRADING_DAY"
    assert payload["shared_acquisition"]["stage_workload_id"] == "fupan_close_materials"
    assert payload["shared_acquisition"]["production_allowed"] is False
    assert payload["shared_acquisition"]["buy_gate_updated"] is False
    assert payload["shared_acquisition"]["orders_sent"] is False
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_main_trading_stage_slot_lazily_gates_selected_stage_after_independent_work(
    monkeypatch, tmp_path, capsys
):
    calls: list[str] = []
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260824", "1500"))
    monkeypatch.setattr(
        scheduler,
        "ensure_stage_candidate_input",
        lambda **_kwargs: calls.append("ensure")
        or {
            "status": "READY",
            "row_count": 1,
            "run_id": "candidate-run",
            "current_path": str(tmp_path / "current.json"),
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )
    monkeypatch.setattr(
        scheduler,
        "consume_shared_stage_selection",
        lambda **_kwargs: calls.append("consume")
        or {
            "status": "CONSUME_ONLY",
            "selection_status": "READY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )
    def fake_run(**kwargs):
        from contracts.runtime_tasks import DispatchMode, DispatchRequest
        from infrastructure.scheduling.catalog import load_workload_catalog

        workloads = {
            item.workload_id: item for item in load_workload_catalog().workloads
        }
        request = DispatchRequest("20260824", "20260824", "20260824", "1500", DispatchMode.LIVE)
        calls.append("intraday")
        assert kwargs["workload_guard"](workloads["v4_intraday_research"], request, None) is None
        calls.append("stage")
        gate = kwargs["workload_guard"](workloads["fupan_close_materials"], request, None)
        assert gate["selection_status"] == "READY"
        assert kwargs["workload_guard"](workloads["fupan_close_materials"], request, None) == gate
        return {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(scheduler, "run_scheduled_slot", fake_run)

    assert scheduler.main(
        [
            "--data-root",
            str(tmp_path / "data"),
            "--ledger-root",
            str(tmp_path / "ledger"),
            "--stage-selection-root",
            str(tmp_path / "stage-selection"),
            "--date",
            "20260824",
            "--slot",
            "1500",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "SUCCEEDED"
    assert calls == ["intraday", "stage", "ensure", "consume"]


def test_main_does_not_gate_disabled_stage_slot_before_dispatch(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260824", "0925"))
    monkeypatch.setattr(
        scheduler,
        "ensure_stage_candidate_input",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("disabled stage workload must not run a pre-dispatch gate")
        ),
    )
    seen = {}

    def fake_run(**kwargs):
        seen["workload_guard"] = kwargs["workload_guard"]
        return {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }

    monkeypatch.setattr(scheduler, "run_scheduled_slot", fake_run)
    assert scheduler.main(
        [
            "--data-root",
            str(tmp_path / "data"),
            "--ledger-root",
            str(tmp_path / "ledger"),
            "--stage-selection-root",
            str(tmp_path / "stage-selection"),
            "--date",
            "20260824",
            "--slot",
            "0925",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert callable(seen["workload_guard"])
    assert payload["shared_acquisition"]["status"] == "NOT_STAGE_WORKLOAD_SELECTED"
