"""Mac-only candidate tests for recovery planning and native byte inspection.

Planner fixtures mock observation validation explicitly and are SYNTHETIC;
their date lists exercise window membership, not an exchange-calendar claim.
Native fixtures are real packed <IfffffII bytes in disposable directories.
No collector, panel publisher, or original product test runs in the cloud.
"""
import copy
import hashlib
import math
import os
import struct
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from v5_shadow import rebound_recovery as recovery
from v5_shadow.digests import canonical_bytes, sha256_json


NATIVE = struct.Struct("<IfffffII")
SIGNAL, TARGET = "20261008", "20261009"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def synthetic_artifact():
    days = [(date(2026, 10, 8) - timedelta(days=i)).strftime("%Y%m%d") for i in range(60, 0, -1)]
    return dict(
        schema_version="SYNTHETIC_PLANNER_FIXTURE_NOT_COMMITTED_OBSERVATION",
        run_id="1" * 32, computation_status="NATIVE_VALUES_OBSERVED",
        request=dict(target_date=TARGET, signal_date=SIGNAL, data_kind="SYNTHETIC"),
        history_sessions=dict(prior60=days, previous5=days[-5:], calendar_sha256="c" * 64),
        source_identity=dict(panel_sha256="a" * 64, panel_manifest_sha256="b" * 64),
        rows=[dict(
            code="HK.00001", numeric_input_status="PARTIAL_UNKNOWN",
            missing_prior60_dates=[days[0], days[-5]], missing_previous5_dates=[days[-5], days[-4]],
            duplicate_prior60_dates=[days[-1]], duplicate_previous5_dates=[days[-1]],
            input_gaps=["PRIOR_60_SESSIONS_INCOMPLETE:58", "PREVIOUS_5_FULL_SESSION_DATES_MISSING:2"],
        )],
    )


def synthetic_plan(artifact=None):
    artifact = synthetic_artifact() if artifact is None else artifact
    with patch.object(recovery.observation, "_validate") as validate:
        plan = recovery.build_recovery_plan(artifact)
        validate.assert_called_once_with(artifact)
    return plan


def reseal_plan(plan):
    plan["plan_sha256"] = sha256_json({k: v for k, v in plan.items() if k != "plan_sha256"})
    return plan


def native_record(day, *, opening=10.0, high=12.0, low=8.0, close=11.0,
                  amount=123.5, trade=7, position=2):
    return NATIVE.pack(int(day), opening, high, low, close, amount, trade, position)


class ReboundRecoveryPlannerCandidates(unittest.TestCase):
    def test_real_observation_validator_is_called_and_rejection_is_propagated(self):
        fixture = synthetic_artifact()
        with patch.object(recovery.observation, "_validate", side_effect=ValueError("SYNTHETIC_REJECTED")) as validate:
            with self.assertRaisesRegex(ValueError, "SYNTHETIC_REJECTED"):
                recovery.build_recovery_plan(fixture)
            validate.assert_called_once_with(fixture)

    def test_missing_and_duplicate_dates_merge_only_the_required_core_fields(self):
        fixture = synthetic_artifact()
        before = copy.deepcopy(fixture)
        days = fixture["history_sessions"]["prior60"]
        plan = synthetic_plan(fixture)
        self.assertEqual(plan["cells"], [
            dict(code="HK.00001", date=days[0], fields=["high"], reason="MISSING_ROW"),
            dict(code="HK.00001", date=days[-5], fields=["high", "trade"], reason="MISSING_ROW"),
            dict(code="HK.00001", date=days[-4], fields=["trade"], reason="MISSING_ROW"),
        ])
        self.assertEqual(plan["duplicate_cells"], [
            dict(code="HK.00001", date=days[-1], fields=["high", "trade"], reason="DUPLICATE_PANEL_DATE"),
        ])
        self.assertEqual(plan["counts"], dict(observed_codes=1, missing_code_dates=3,
            missing_core_values=4, duplicate_code_dates=1, incomplete_codes=1))
        self.assertEqual(fixture, before)
        plan["history_sessions"]["prior60"].clear()
        self.assertEqual(fixture, before)

    def test_plan_seals_source_identity_and_retains_exact_calendar(self):
        fixture = synthetic_artifact()
        plan = synthetic_plan(fixture)
        self.assertEqual(plan["source_artifact_sha256"], sha256_json(fixture))
        self.assertEqual(plan["history_sessions"], fixture["history_sessions"])
        self.assertEqual(plan["source_run_id"], fixture["run_id"])
        self.assertEqual(plan["calendar_sha256"], "c" * 64)
        self.assertEqual(plan["plan_sha256"], sha256_json({k: v for k, v in plan.items() if k != "plan_sha256"}))
        self.assertEqual(plan["repair_owner"], "EXISTING_HK_0_2_PANEL_OWNER")
        self.assertFalse(plan["append_updater_can_repair_internal_gaps"])
        self.assertEqual(plan["collection"]["status"], "HOLD")
        self.assertEqual(plan["collection"]["requests_authorized"], 0)

    def test_window_lengths_duplicates_and_membership_fail_closed(self):
        for mutation in ("short60", "duplicate60", "short5", "duplicate5", "outside5"):
            with self.subTest(mutation=mutation):
                fixture = synthetic_artifact()
                history = fixture["history_sessions"]
                if mutation == "short60":
                    history["prior60"].pop(0)
                elif mutation == "duplicate60":
                    history["prior60"][0] = history["prior60"][1]
                elif mutation == "short5":
                    history["previous5"].pop(0)
                elif mutation == "duplicate5":
                    history["previous5"][0] = history["previous5"][1]
                else:
                    history["previous5"][0] = "20250101"
                with self.assertRaises(ValueError):
                    synthetic_plan(fixture)

    def test_invalid_signal_equal_signal_and_future_history_dates_are_rejected(self):
        for bad_date in ("20260230", SIGNAL, "20261009"):
            with self.subTest(bad_date=bad_date):
                fixture = synthetic_artifact()
                fixture["history_sessions"]["prior60"][0] = bad_date
                with self.assertRaises(ValueError):
                    synthetic_plan(fixture)
        fixture = synthetic_artifact()
        fixture["request"]["signal_date"] = "2026-10-08"
        with self.assertRaises(ValueError):
            synthetic_plan(fixture)

    def test_missing_and_duplicate_gap_dates_cannot_escape_their_own_window(self):
        for field in ("missing_prior60_dates", "missing_previous5_dates",
                      "duplicate_prior60_dates", "duplicate_previous5_dates"):
            with self.subTest(field=field):
                fixture = synthetic_artifact()
                fixture["rows"][0][field] = ["20250101"]
                with self.assertRaises(ValueError):
                    synthetic_plan(fixture)

    def test_optional_gaps_do_not_create_core_recovery_cells(self):
        fixture = synthetic_artifact()
        row = fixture["rows"][0]
        for field in ("missing_prior60_dates", "missing_previous5_dates",
                      "duplicate_prior60_dates", "duplicate_previous5_dates"):
            row[field] = []
        row.update(numeric_input_status="KNOWN", input_gaps=[
            "PREVIOUS_20_SESSIONS_INCOMPLETE:19", "AMOUNT_MISSING", "PRE_CLOSE_MISSING", "LOW_MISSING",
        ])
        plan = synthetic_plan(fixture)
        self.assertEqual(plan["cells"], [])
        self.assertEqual(plan["duplicate_cells"], [])
        self.assertEqual(plan["unlocalized_numeric_gaps"], [])
        self.assertIn("AMOUNT", plan["requirements"]["observations_only"])
        self.assertIn("20_RECORD_VOLUME", plan["requirements"]["observations_only"])

    def test_unlocalized_core_gaps_are_not_assigned_fabricated_dates(self):
        fixture = synthetic_artifact()
        row = fixture["rows"][0]
        for field in ("missing_prior60_dates", "missing_previous5_dates",
                      "duplicate_prior60_dates", "duplicate_previous5_dates"):
            row[field] = []
        gaps = ["CURRENT_CLOSE_MISSING_OR_INVALID", "CURRENT_VOLUME_MISSING_OR_INVALID",
                "PRIOR_60_VALID_HIGHS_INCOMPLETE:59", "PREVIOUS_5_MEAN_VOLUME_ZERO"]
        row["input_gaps"] = gaps
        plan = synthetic_plan(fixture)
        self.assertEqual(plan["cells"], [])
        self.assertEqual(plan["unlocalized_numeric_gaps"][0]["reasons"], gaps)
        self.assertEqual(plan["unlocalized_numeric_gaps"][0]["code"], "HK.00001")
        plan["unlocalized_numeric_gaps"][0]["reasons"].append("MUTATION")
        self.assertNotIn("MUTATION", row["input_gaps"])

    def test_failed_observation_does_not_become_an_empty_recovery_success(self):
        fixture = synthetic_artifact()
        fixture["computation_status"] = "CANNOT_CONFIRM"
        with self.assertRaisesRegex(ValueError, "RECOVERY_OBSERVATION_REQUIRED"):
            synthetic_plan(fixture)


class ReboundNativeAuditCandidates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        fixture = synthetic_artifact()
        day = fixture["history_sessions"]["previous5"][0]
        fixture["rows"][0].update(missing_prior60_dates=[day], missing_previous5_dates=[day],
            duplicate_prior60_dates=[], duplicate_previous5_dates=[])
        self.day = day
        self.plan = synthetic_plan(fixture)
        self.relative = "vipdoc/ds/lday/71#00001.day"
        self.path = self.root / self.relative
        self.path.parent.mkdir(parents=True)

    def request(self, raw):
        self.path.write_bytes(raw)
        return dict(schema_version="v5.rebound_native_audit_request.v1", input_root=str(self.root),
                    files={self.relative: sha(raw)})

    def audit(self, raw):
        return recovery.audit_vipdoc_candidates(self.plan, self.request(raw))

    def test_exact_native_bytes_offsets_values_and_hashes_are_retained(self):
        ignored = native_record("20250101", trade=123)
        chosen = native_record(self.day, opening=10.25, high=12.5, low=8.5, close=11.75,
                               amount=123456.5, trade=123456789, position=987)
        raw = ignored + chosen
        request = self.request(raw)
        before = copy.deepcopy(request)
        audit = recovery.audit_vipdoc_candidates(self.plan, request)
        row = audit["rows"][0]
        self.assertEqual(row["status"], "EXACT_NATIVE_ROW")
        self.assertEqual(row["match_count"], 1)
        self.assertEqual(row["candidate"]["record_offset"], NATIVE.size)
        self.assertEqual(row["candidate"]["record_sha256"], sha(chosen))
        self.assertEqual(row["candidate"]["file_sha256"], sha(raw))
        self.assertEqual(row["candidate"]["values"], dict(open=10.25, high=12.5, low=8.5,
            close=11.75, amount=123456.5, trade=123456789, position=987))
        self.assertEqual(audit["input_files"][self.relative], dict(sha256=sha(raw), bytes=len(raw)))
        self.assertEqual(audit["input_files_sha256"], sha256_json(audit["input_files"]))
        self.assertEqual(audit["audit_sha256"], sha256_json({k: v for k, v in audit.items() if k != "audit_sha256"}))
        self.assertEqual(request, before)
        self.assertEqual(self.path.read_bytes(), raw)

    def test_missing_native_date_stays_absent_without_zero_fill(self):
        audit = self.audit(native_record("20250101"))
        row = audit["rows"][0]
        self.assertEqual(row["status"], "NOT_PRESENT")
        self.assertEqual(row["match_count"], 0)
        self.assertIsNone(row["candidate"])

    def test_unbound_native_files_are_not_discovered_or_read(self):
        request = self.request(native_record(self.day))
        unbound = self.path.with_name("71#00002.day")
        unbound.write_bytes(b"UNBOUND INVALID RECORDS MUST BE IGNORED")
        audit = recovery.audit_vipdoc_candidates(self.plan, request)
        self.assertEqual(set(audit["input_files"]), {self.relative})
        self.assertEqual(audit["rows"][0]["status"], "EXACT_NATIVE_ROW")
        self.assertEqual(unbound.read_bytes(), b"UNBOUND INVALID RECORDS MUST BE IGNORED")

    def test_duplicate_native_dates_never_pick_first_last_or_best_record(self):
        for records in (
            (native_record(self.day, high=12), native_record(self.day, high=99)),
            (native_record(self.day, high=99), native_record(self.day, high=12)),
        ):
            with self.subTest(first_high=NATIVE.unpack(records[0])[2]):
                row = self.audit(b"".join(records))["rows"][0]
                self.assertEqual(row["status"], "DUPLICATE_NATIVE_DATE")
                self.assertEqual(row["match_count"], 2)
                self.assertIsNone(row["candidate"])

    def test_invalid_ohlc_preserves_byte_identity_but_not_values(self):
        for changes in (dict(opening=0), dict(high=-1), dict(low=math.nan), dict(close=math.inf),
                        dict(high=10), dict(low=11), dict(close=7)):
            with self.subTest(changes=changes):
                raw = native_record(self.day, **changes)
                row = self.audit(raw)["rows"][0]
                self.assertEqual(row["status"], "INVALID_NATIVE_VALUE")
                self.assertEqual(row["candidate"]["record_sha256"], sha(raw))
                self.assertNotIn("values", row["candidate"])

    def test_zero_trade_is_a_real_zero_and_never_upscaled(self):
        row = self.audit(native_record(self.day, trade=0))["rows"][0]
        self.assertEqual(row["status"], "EXACT_NATIVE_ROW")
        self.assertEqual(row["candidate"]["values"]["trade"], 0)

    def test_nonfinite_optional_amount_does_not_discard_core_native_row(self):
        for amount in (math.nan, math.inf, -math.inf):
            with self.subTest(amount=amount):
                audit = self.audit(native_record(self.day, amount=amount))
                row = audit["rows"][0]
                self.assertEqual(row["status"], "EXACT_NATIVE_ROW")
                self.assertIsNone(row["candidate"]["values"]["amount"])
                canonical_bytes(audit)

    def test_audit_has_no_conversion_collection_publication_or_formal_proof(self):
        audit = self.audit(native_record(self.day))
        self.assertEqual(audit["scale_applied"], 1)
        self.assertIs(audit["conversion_applied"], False)
        self.assertIsNone(audit["volume_unit"])
        self.assertEqual(audit["price_basis"], "NOT_PROVEN")
        self.assertEqual(audit["finality_status"], "NOT_PROVEN")
        self.assertIs(audit["usable_for_formal_selection"], False)
        for key in ("collection_performed", "panel_published", "production_allowed", "buy_gate_updated",
                    "orders_sent", "formal_eligibility_verified", "natural_verified"):
            self.assertIs(audit[key], False)
        self.assertEqual(sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()),
                         [self.relative])

    def test_bad_schema_extra_request_fields_and_file_count_are_rejected(self):
        base = self.request(native_record(self.day))
        mutations = []
        request = copy.deepcopy(base)
        request["schema_version"] = "v5.rebound_native_audit_request.v0"
        mutations.append(request)
        request = copy.deepcopy(base)
        request["provider"] = "UNREQUESTED"
        mutations.append(request)
        request = copy.deepcopy(base)
        request["files"] = {}
        mutations.append(request)
        request = copy.deepcopy(base)
        request["files"] = {f"vipdoc/ds/lday/71#{i:05d}.day": "a" * 64 for i in range(2001)}
        mutations.append(request)
        for request in mutations:
            with self.subTest(fields=list(request), count=len(request["files"])):
                with self.assertRaises(ValueError):
                    recovery.audit_vipdoc_candidates(self.plan, request)

    def test_traversal_absolute_wrong_market_and_unrequested_codes_are_rejected(self):
        raw = native_record(self.day)
        for relative in ("../71#00001.day", str(self.path), "vipdoc/sh/lday/sh000001.day",
                         "vipdoc/ds/lday/71#00002.day", "vipdoc/ds/lday/71#1.day"):
            with self.subTest(relative=relative):
                request = self.request(raw)
                request["files"] = {relative: sha(raw)}
                with self.assertRaises(ValueError):
                    recovery.audit_vipdoc_candidates(self.plan, request)

    def test_wrong_sha_and_trailing_record_bytes_are_rejected(self):
        request = self.request(native_record(self.day))
        request["files"][self.relative] = "0" * 64
        with self.assertRaisesRegex(ValueError, "RECOVERY_NATIVE_SHA"):
            recovery.audit_vipdoc_candidates(self.plan, request)
        request = self.request(native_record(self.day) + b"\0")
        with self.assertRaisesRegex(ValueError, "RECOVERY_NATIVE_TRAILING_BYTES"):
            recovery.audit_vipdoc_candidates(self.plan, request)

    def test_symlinked_file_and_root_are_rejected(self):
        raw = native_record(self.day)
        request = self.request(raw)
        outside = self.root / "outside.day"
        outside.write_bytes(raw)
        self.path.unlink()
        self.path.symlink_to(outside)
        with self.assertRaises((ValueError, OSError)):
            recovery.audit_vipdoc_candidates(self.plan, request)
        self.path.unlink()
        self.path.write_bytes(raw)
        link = self.root / "input-link"
        link.symlink_to(self.root, target_is_directory=True)
        request["input_root"] = str(link)
        with self.assertRaises((ValueError, OSError)):
            recovery.audit_vipdoc_candidates(self.plan, request)

    def test_same_descriptor_change_during_read_is_rejected(self):
        request = self.request(native_record(self.day))
        original_read = os.read
        mutated = False

        def mutate_after_first_read(fd, size):
            nonlocal mutated
            block = original_read(fd, size)
            if block and not mutated:
                mutated = True
                with self.path.open("ab") as stream:
                    stream.write(native_record("20250101"))
            return block

        with patch("v5_shadow.rebound_recovery.os.read", side_effect=mutate_after_first_read):
            with self.assertRaisesRegex(ValueError, "MODULE_RECORD_CHANGED"):
                recovery.audit_vipdoc_candidates(self.plan, request)
        self.assertTrue(mutated)

    def test_tampered_plan_and_rehashed_invalid_cell_contracts_are_rejected(self):
        request = self.request(native_record(self.day))
        plan = copy.deepcopy(self.plan)
        plan["source_run_id"] = "2" * 32
        with self.assertRaises(ValueError):
            recovery.audit_vipdoc_candidates(plan, request)
        for changes in (dict(fields=["amount"]), dict(fields=[]), dict(reason="ASSUMED"),
                        dict(date=SIGNAL), dict(code="US.00001")):
            with self.subTest(changes=changes):
                plan = copy.deepcopy(self.plan)
                plan["cells"][0].update(changes)
                reseal_plan(plan)
                with self.assertRaises(ValueError):
                    recovery.audit_vipdoc_candidates(plan, request)

    def test_rehashed_plan_cannot_move_high_or_trade_outside_its_exact_window(self):
        request = self.request(native_record(self.day))
        cases = (
            ("20250101", ["high"]),
            (self.plan["history_sessions"]["prior60"][0], ["trade"]),
            (self.plan["history_sessions"]["prior60"][0], ["high", "trade"]),
        )
        for day, fields in cases:
            with self.subTest(day=day, fields=fields):
                plan = copy.deepcopy(self.plan)
                plan["cells"][0].update(date=day, fields=fields)
                reseal_plan(plan)
                with self.assertRaisesRegex(ValueError, "RECOVERY_CELL_CONTRACT"):
                    recovery.audit_vipdoc_candidates(plan, request)

    def test_rehashed_plan_still_requires_valid_exact_sixty_and_five_date_windows(self):
        request = self.request(native_record(self.day))
        for mutation in ("short60", "duplicate5", "outside5", "future60"):
            with self.subTest(mutation=mutation):
                plan = copy.deepcopy(self.plan)
                history = plan["history_sessions"]
                if mutation == "short60":
                    history["prior60"].pop(0)
                elif mutation == "duplicate5":
                    history["previous5"][0] = history["previous5"][1]
                elif mutation == "outside5":
                    history["previous5"][0] = "20250101"
                else:
                    history["prior60"][0] = SIGNAL
                reseal_plan(plan)
                with self.assertRaisesRegex(ValueError, "RECOVERY_CALENDAR_WINDOWS"):
                    recovery.audit_vipdoc_candidates(plan, request)


if __name__ == "__main__":
    unittest.main()
