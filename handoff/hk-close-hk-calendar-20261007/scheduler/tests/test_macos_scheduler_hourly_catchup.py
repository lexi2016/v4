from __future__ import annotations

import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from infrastructure.stage_acquisition_universe_store import (
    StageAcquisitionUniverseStore,
    build_stage_acquisition_universe,
)
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


@pytest.mark.parametrize(
    ("now", "expected_slot", "catchup"),
    (
        (datetime(2026, 8, 19, 4, 15, tzinfo=SHANGHAI), "0415", False),
        (datetime(2026, 8, 19, 4, 19, tzinfo=SHANGHAI), "0415", True),
        (datetime(2026, 1, 16, 5, 15, tzinfo=SHANGHAI), "0515", False),
        (datetime(2026, 1, 16, 5, 19, tzinfo=SHANGHAI), "0515", True),
    ),
)
def test_us_seasonal_slots_are_exact_and_recoverable_after_wake(
    tmp_path, now, expected_slot, catchup
):
    due = scheduler.resolve_due_slot(now=now, ledger_root=tmp_path)

    assert expected_slot in scheduler.ALL_SLOTS
    assert due["slot"] == expected_slot
    assert due["catchup"] is catchup


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


def test_missed_1800_gets_a_chance_before_retryable_1730(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1730",
        run_id="retryable-1730",
        finished_at="2026-08-17T09:00:00Z",
        failure_class="UPSTREAM_NOT_READY",
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 18, 3, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due == {
        "business_date": "20260817",
        "observed_slot": "1803",
        "slot": "1800",
        "catchup": True,
        "lag_minutes": 3,
    }


def test_missed_2040_gets_a_chance_before_retryable_1500(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1500",
        run_id="retryable-1500",
        finished_at="2026-08-17T12:30:00Z",
        failure_class="UPSTREAM_NOT_READY",
    )
    _complete_post_close_slots(
        tmp_path,
        (
            "1555",
            "1605",
            "1608",
            "1700",
            "1710",
            "1720",
            "1730",
            "1800",
            "2000",
            "2030",
        ),
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 20, 43, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )

    assert due == {
        "business_date": "20260817",
        "observed_slot": "2043",
        "slot": "2040",
        "catchup": True,
        "lag_minutes": 3,
    }


def test_missed_1720_and_1730_keep_dependency_order_over_1500_retry(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1500",
        run_id="retryable-1500",
        finished_at="2026-08-17T07:00:00Z",
        failure_class="UPSTREAM_NOT_READY",
    )
    _complete_post_close_slots(
        tmp_path,
        ("1555", "1605", "1608", "1700", "1710"),
    )

    at_1723 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 17, 23, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )
    assert at_1723["slot"] == "1720"
    assert at_1723["catchup"] is True

    _complete_post_close_slots(tmp_path, ("1720",))
    at_1733 = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 17, 33, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
    )
    assert at_1733["slot"] == "1730"
    assert at_1733["catchup"] is True


def test_missed_1720_gets_a_chance_over_retryable_1700(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1700",
        run_id="retryable-1700",
        finished_at="2026-08-17T07:00:00Z",
        failure_class="UPSTREAM_NOT_READY",
    )
    _complete_post_close_slots(tmp_path, ("1500", "1555", "1605", "1608", "1710"))

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 17, 23, tzinfo=SHANGHAI), ledger_root=tmp_path
    )

    assert due["slot"] == "1720"
    assert due["catchup"] is True


def test_missed_1610_is_not_blocked_by_retryable_1500(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1500",
        run_id="retryable-1500",
        finished_at="2026-08-17T07:00:00Z",
        failure_class="UPSTREAM_NOT_READY",
    )
    _complete_post_close_slots(tmp_path, ("1500", "1530", "1555", "1600", "1605"))

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 16, 12, tzinfo=SHANGHAI), ledger_root=tmp_path
    )

    assert due["slot"] == "1610"
    assert due["catchup"] is True


def test_old_1608_receipt_does_not_suppress_the_1610_close_catchup(tmp_path):
    _complete_post_close_slots(tmp_path, ("1500", "1530", "1555", "1605", "1608"))

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 16, 11, tzinfo=SHANGHAI), ledger_root=tmp_path
    )

    assert due["slot"] == "1610"
    assert due["catchup"] is True


def test_retryable_post_close_slots_rotate_by_oldest_attempt_when_all_are_tried(
    tmp_path,
):
    _failed_receipt(
        tmp_path,
        slot="1500",
        run_id="retryable-1500",
        finished_at="2026-08-17T12:00:00Z",
        failure_class="UPSTREAM_NOT_READY",
    )
    _failed_receipt(
        tmp_path,
        slot="1555",
        run_id="retryable-1555",
        finished_at="2026-08-17T11:00:00Z",
        failure_class="UPSTREAM_NOT_READY",
    )
    _complete_post_close_slots(
        tmp_path,
        (
            "1605", "1608", "1700", "1710", "1720", "1730", "1800",
            "2000", "2030", "2040",
        ),
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 20, 43, tzinfo=SHANGHAI), ledger_root=tmp_path
    )

    assert due["slot"] == "1555"
    assert due["catchup"] is True


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


def test_current_identity_backoff_is_not_bypassed_by_older_failure(tmp_path):
    _failed_receipt(
        tmp_path,
        slot="1300",
        run_id="old-release",
        finished_at="2026-08-17T05:00:00Z",
        failure_class="NETWORK",
        release_id="old-release",
        upstream_fingerprint="old-upstream",
    )
    _failed_receipt(
        tmp_path,
        slot="1300",
        run_id="current-release",
        finished_at="2026-08-17T05:21:00Z",
        failure_class="NETWORK",
        release_id="current-release",
        upstream_fingerprint="current-upstream",
        retry_after="2026-08-17T13:30:00Z",
    )

    due = scheduler.resolve_due_slot(
        now=datetime(2026, 8, 17, 13, 23, tzinfo=SHANGHAI),
        ledger_root=tmp_path,
        release_id="current-release",
        upstream_fingerprint="current-upstream",
    )

    assert due["slot"] == "1323"
    assert due["catchup"] is False


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
    monkeypatch.setattr(
        scheduler,
        "run_scheduled_slot",
        lambda **kwargs: calls.append(kwargs["slot"])
        or {
            # The real catalog still contains a NATURAL_DAY hourly workload;
            # dispatcher owns whether the overall terminal result is
            # SUCCEEDED or NON_TRADING_DAY for this date/slot.
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )

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
    assert payload["shared_acquisition"] == {
        "status": "SKIPPED_NON_TRADING_DAY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_main_trading_stage_slot_keeps_candidate_prerequisite_before_dispatch(
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
        or {"status": "CONSUME_ONLY", "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    )
    monkeypatch.setattr(
        scheduler,
        "run_scheduled_slot",
        lambda **kwargs: {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )

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
    assert calls == ["ensure", "consume"]


def test_main_0915_prewarm_ensures_a_candidate_before_hk_auction_without_consuming(
    monkeypatch, tmp_path, capsys
):
    """The opening auction consumes its own lane; it only prewarms A input."""

    calls: list[str] = []
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260824", "0915"))
    monkeypatch.setattr(
        scheduler,
        "ensure_stage_candidate_input",
        lambda **_kwargs: calls.append("ensure")
        or {
            "status": "READY",
            "row_count": 403,
            "run_id": "candidate-run",
            "current_path": str(tmp_path / "current.json"),
            "artifact_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "receipt_sha256": "c" * 64,
            "idempotent": False,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )
    monkeypatch.setattr(
        scheduler,
        "consume_shared_stage_selection",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("09:15 must not consume a stage selection")
        ),
    )

    def run_scheduled_slot(**kwargs):
        calls.append("dispatch")
        assert kwargs["slot"] == "0915"
        return {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "selected_workload_ids": ["hk_auction_0920"],
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
            "--stage-selection-root",
            str(tmp_path / "stage-selection"),
            "--date",
            "20260824",
            "--slot",
            "0915",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert calls == ["ensure", "dispatch"]
    assert payload["status"] == "SUCCEEDED"
    assert payload["selected_workload_ids"] == ["hk_auction_0920"]
    assert payload["shared_acquisition"]["status"] == "READY"
    assert payload["shared_acquisition"]["stage_acquisition_universe"]["row_count"] == 403
    assert payload["shared_acquisition"]["lane"] == "A_SHARE"
    assert payload["shared_acquisition"]["candidate_input_write_performed"] is True
    assert payload["shared_acquisition"]["stage_selection_write_performed"] is False
    assert payload["shared_acquisition"]["selection_consumed"] is False
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_ensure_stage_candidate_input_accepts_valid_superseded_successor(
    tmp_path,
):
    data_root = tmp_path / "data"

    def projection(count):
        rows = [
            {
                "market": "A",
                "symbol": f"A.{index:06d}",
                "pool_id": "a_share_research_recommendation_pool",
                "recommendation_status": "WATCH_ONLY",
            }
            for index in range(1, count + 1)
        ]
        return {
            "ok": True,
            "trade_date": "20260902",
            "a_all_pool_rows": rows,
            "a_all_pool_row_count": count,
            "data_status": "READY_WITH_ROWS",
            "status": "READY",
            "cannot_confirm": [],
            "pools": [
                {
                    "pool_id": "a_share_research_recommendation_pool",
                    "status": "available",
                    "rows": rows,
                }
            ],
        }

    store = StageAcquisitionUniverseStore(data_root)
    store.publish(
        build_stage_acquisition_universe(projection(420), "20260902"),
        run_id="old-420",
    )
    current_sha = hashlib.sha256(
        store.current_path("20260902").read_bytes()
    ).hexdigest()
    successor_artifact = build_stage_acquisition_universe(
        projection(421), "20260902"
    )
    successor = store.publish_successor(
        successor_artifact,
        run_id="new-421",
        expected_current_sha256=current_sha,
        reason="test exact candidate generation",
    )

    result = scheduler.ensure_stage_candidate_input(
        data_root=data_root,
        business_date="20260902",
        universe_materializer=lambda *_args: {
            **successor,
            "artifact": successor_artifact,
        },
    )

    assert result["status"] == "SUPERSEDED"
    assert result["row_count"] == 421
    assert result["run_id"] == "new-421"
    assert result["current_path"] == str(store.current_path("20260902"))


def test_ensure_stage_candidate_input_rejects_materializer_sha_mismatch(
    monkeypatch, tmp_path,
):
    current_path = tmp_path / "data" / "current" / "20260902" / "role" / "current.json"
    current_path.parent.mkdir(parents=True)
    current_path.write_text("{}", encoding="utf-8")
    candidate = type(
        "VerifiedCandidate",
        (),
        {
            "root": tmp_path / "data",
            "current_relative": current_path.relative_to(tmp_path / "data").as_posix(),
            "codes": tuple(f"A.{index:06d}" for index in range(1, 422)),
            "run_id": "new-421",
            "artifact_sha256": "a" * 64,
            "manifest_sha256": "b" * 64,
            "receipt_sha256": "c" * 64,
        },
    )()
    monkeypatch.setattr(scheduler, "read_candidate_input", lambda *_args: candidate)

    with pytest.raises(RuntimeError, match="STAGE_ACQUISITION_UNIVERSE_NOT_READY"):
        scheduler.ensure_stage_candidate_input(
            data_root=tmp_path / "data",
            business_date="20260902",
            universe_materializer=lambda *_args: {
                "status": "SUPERSEDED",
                "row_count": 421,
                "run_id": "new-421",
                "current_path": str(current_path),
                "artifact_sha256": "f" * 64,
                "manifest_sha256": "b" * 64,
                "receipt_sha256": "c" * 64,
                "artifact": {
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                },
            },
        )


def test_ensure_stage_candidate_input_rejects_unreadable_superseded_current(
    tmp_path,
):
    missing_current = tmp_path / "definitely-not-readable" / "current.json"

    with pytest.raises(RuntimeError, match="STAGE_ACQUISITION_UNIVERSE_NOT_READY"):
        scheduler.ensure_stage_candidate_input(
            data_root=tmp_path / "data",
            business_date="20260902",
            universe_materializer=lambda *_args, **_kwargs: {
                "status": "SUPERSEDED",
                "row_count": 421,
                "run_id": "20260902-a-share-successor-421",
                "current_path": str(missing_current),
                "artifact_sha256": "a" * 64,
                "manifest_sha256": "b" * 64,
                "receipt_sha256": "c" * 64,
                "artifact": {
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                },
            },
        )


@pytest.mark.parametrize("status", ["CANNOT_CONFIRM", "FAILED", "NOT_READY"])
def test_ensure_stage_candidate_input_rejects_non_success_statuses(
    tmp_path, status
):
    with pytest.raises(RuntimeError, match="STAGE_ACQUISITION_UNIVERSE_NOT_READY"):
        scheduler.ensure_stage_candidate_input(
            data_root=tmp_path / "data",
            business_date="20260902",
            universe_materializer=lambda *_args, **_kwargs: {
                "status": status,
                "row_count": 421,
                "artifact": {
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                },
            },
        )


def test_main_0915_prewarm_failure_is_lane_local_and_does_not_starve_hk_auction(
    monkeypatch, tmp_path, capsys
):
    calls: list[str] = []
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260824", "0915"))
    monkeypatch.setattr(
        scheduler,
        "ensure_stage_candidate_input",
        lambda **_kwargs: (_ for _ in ()).throw(
            RuntimeError("candidate input unavailable")
        ),
    )
    monkeypatch.setattr(
        scheduler,
        "consume_shared_stage_selection",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("09:15 must not consume a stage selection")
        ),
    )

    def run_scheduled_slot(**kwargs):
        calls.append(kwargs["slot"])
        return {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "selected_workload_ids": ["hk_auction_0920"],
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
            "--stage-selection-root",
            str(tmp_path / "stage-selection"),
            "--date",
            "20260824",
            "--slot",
            "0915",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert calls == ["0915"]
    assert payload["status"] == "SUCCEEDED"
    assert payload["selected_workload_ids"] == ["hk_auction_0920"]
    assert payload["shared_acquisition"]["status"] == "CANNOT_CONFIRM"
    assert payload["shared_acquisition"]["lane"] == "A_SHARE"
    assert payload["shared_acquisition"]["candidate_input_write_performed"] is False
    assert payload["shared_acquisition"]["stage_selection_write_performed"] is False
    assert payload["shared_acquisition"]["selection_consumed"] is False
    assert payload["shared_acquisition"]["producer_called"] is False
    assert payload["production_allowed"] is False
    assert payload["buy_gate_updated"] is False
    assert payload["orders_sent"] is False


def test_main_0915_non_trading_day_skips_candidate_prewarm_and_dispatches_safely(
    monkeypatch, tmp_path, capsys
):
    calls: list[str] = []
    monkeypatch.setattr(scheduler, "current_slot", lambda: ("20260823", "0915"))
    monkeypatch.setattr(
        scheduler,
        "ensure_stage_candidate_input",
        lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("non-trading 09:15 must not materialize candidate input")
        ),
    )
    monkeypatch.setattr(
        scheduler,
        "run_scheduled_slot",
        lambda **kwargs: calls.append(kwargs["slot"])
        or {
            "status": "SUCCEEDED",
            "slot": kwargs["slot"],
            "selected_workload_ids": [],
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        },
    )

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
            "0915",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert calls == ["0915"]
    assert payload["status"] == "SUCCEEDED"
    assert payload["shared_acquisition"] == {
        "status": "SKIPPED_NON_TRADING_DAY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
