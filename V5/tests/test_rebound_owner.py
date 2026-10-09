"""Mac candidate tests for the isolated rebound owner; never cloud product runs.

The boundary cases use synthetic bytes and do not contact a provider.  The
original owner integration cases additionally need the frozen Python 3.14+
runtime and locked dependencies.  Do not interpret their fixtures as real
prices, membership evidence, unit attestations, or close-finality evidence.
"""
import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from v5_shadow.digests import canonical_bytes, sha256_json
from v5_shadow import rebound_owner as owner


BASE = Path(__file__).resolve().parents[1]
SIGNAL = "20261007"
TARGET = "20261008"
GROUPS = ("cards", "strict", "near", "pending", "excluded", "screen_unresolved")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_file(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def request_for(root):
    """Only identity/metadata validation uses these deliberately non-Parquet bytes."""
    root.mkdir(parents=True, exist_ok=True)
    panel = b"SYNTHETIC IDENTITY BYTES, NOT MARKET DATA\n"
    panel_rel = f"panels/{SIGNAL}-{digest(panel)[:12]}/hkconnect_vipdoc_daily_panel.parquet"
    master_rel = f"runs/{SIGNAL}/{'a' * 24}"
    paths = {
        "panel_manifest": "assets/hk_0_2/" + panel_rel.rsplit("/", 1)[0] + "/manifest.json",
        "panel": "assets/hk_0_2/" + panel_rel,
        "master_manifest": "assets/hk_security_master/" + master_rel + "/manifest.json",
        "master_artifact": "assets/hk_security_master/" + master_rel + "/artifact.csv",
        "master_receipt": "assets/hk_security_master/" + master_rel + "/receipt.json",
    }
    safety = dict(production_allowed=False, buy_gate_updated=False, orders_sent=False)
    artifact = b"code,name\nHK.00001,SYNTHETIC ONLY\n"
    panel_manifest = dict(
        asset_schema_version="v3_shared_data.hk_0_2_panel_asset.v2",
        panel_max_date=SIGNAL, panel_relative=panel_rel, panel_sha256=digest(panel),
        panel_code_count=1, panel_rows=1,
        source_contract="tdx_vipdoc_71_day+verified_zero_trade_repairs",
        manifest_prepared_at="2026-10-07T17:30:00+08:00", research_only=True,
        **safety,
    )
    master_manifest = dict(
        schema_version="v3_shared_data.hk_security_master_manifest.v1",
        trade_date=SIGNAL, run_id="a" * 24, captured_at="2026-10-07T17:00:00+08:00",
        row_count=1, universe_codes_sha256="b" * 64,
        artifact_relative=master_rel + "/artifact.csv", artifact_sha256=digest(artifact),
        stage_valuation_policy="OUTSTANDING_SHARES_X_CUTOFF_LAST_PRICE",
        valuation_eligibility_field="circular_market_val", later_snapshot_price_allowed=False,
        **safety,
    )
    master_receipt = dict(
        schema_version="v3_shared_data.hk_security_master_receipt.v1", status="READY",
        trade_date=SIGNAL, run_id="a" * 24, artifact_sha256=digest(artifact),
        manifest_sha256=sha256_json(master_manifest), **safety,
    )
    for role, value in (("panel_manifest", panel_manifest),
                        ("master_manifest", master_manifest),
                        ("master_receipt", master_receipt)):
        json_file(root / paths[role], value)
    (root / paths["panel"]).write_bytes(panel)
    (root / paths["master_artifact"]).write_bytes(artifact)
    return dict(
        schema_version="v5.rebound_owner_request.v1", target_date=TARGET,
        signal_date=SIGNAL, research_cutoff=datetime.now(timezone.utc).isoformat(),
        data_kind="SYNTHETIC", input_root=str(root.resolve()), paths=paths,
        files={relative: digest((root / relative).read_bytes()) for relative in paths.values()},
    )


def legacy_screen():
    def row(code, classification):
        return dict(
            code=code, classification=classification, close=7.25,
            prior60_high=10.5, oversold_cutoff_80pct_prior60_high=8.4,
            volume=200.0, volume_ratio_5d=2.0, amount_hkd=1234567.89,
            connect_eligibility="VERIFIED_TARGET_UNIVERSE", verified_session=int(SIGNAL),
            source={"currency": "HKD", "session_kind": "FULL_DAY_CLOSE"},
        )
    strict = row("HK.00001", "STRICT_REBOUND_SCREEN")
    near = row("HK.00002", "NEAR_REBOUND_SCREEN")
    return dict(
        schema_version="v4.manager_research.rebound_v3_screen.v1",
        rule_version="20260923_REBOUND_TWO_GATE_V1", target_trade_date=TARGET,
        verified_session=SIGNAL, status="READY_WITH_GAPS", main_screen_ready=True,
        authority=dict(
            amount_unit="HKD", price_basis="RAW", session_kind="FULL_DAY_CLOSE",
            panel_witness=dict(price_currency="HKD", amount_unit="HKD",
                               session_kind="FULL_DAY_CLOSE", verified_session=SIGNAL),
        ),
        strict=[strict], near=[near], cards=[copy.deepcopy(strict), copy.deepcopy(near)],
        pending=[row("HK.00003", "PENDING")], excluded=[row("HK.00004", "EXCLUDED")],
        screen_unresolved=[row("HK.00005", "UNRESOLVED")],
        coverage=dict(input_candidate_count=5, strict_count=1, near_count=1,
                      history_pending_count=1, excluded_count=1,
                      screen_unresolved_count=1, row_accounted_count=5),
        input_identity="c" * 64, decision_identity="d" * 64,
        gaps=["SCREEN_HISTORY_OR_VOLUME_INCOMPLETE:HK.00003"],
        RESEARCH_ONLY=True, production_allowed=False, buy_gate_updated=False, orders_sent=False,
    )


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


class ReboundOwnerRequestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.request = request_for(self.root / "input")
        self.rejected_count = 0

    def reject(self, request):
        self.rejected_count += 1
        with self.assertRaises(ValueError):
            owner._request(request)
            owner.prepare_snapshot(request, self.root / f"rejected-{self.rejected_count}")

    def test_synthetic_and_recorded_replay_contracts_are_accepted(self):
        for kind in ("SYNTHETIC", "RECORDED_INPUT_REPLAY"):
            with self.subTest(kind=kind):
                request = copy.deepcopy(self.request)
                request["data_kind"] = kind
                owner._request(request)

    def test_missing_each_required_role_is_rejected(self):
        for role in self.request["paths"]:
            with self.subTest(role=role):
                request = copy.deepcopy(self.request)
                del request["paths"][role]
                self.reject(request)

    def test_missing_receipt_digest_is_rejected(self):
        request = copy.deepcopy(self.request)
        del request["files"][request["paths"]["master_receipt"]]
        self.reject(request)

    def test_dates_schema_and_data_kind_fail_closed(self):
        cases = (
            ("schema_version", "v5.rebound_owner_request.v0"),
            ("data_kind", "LIVE"), ("target_date", "2026-10-08"),
            ("target_date", "20260230"), ("signal_date", "20261009"),
            ("signal_date", TARGET),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value):
                request = copy.deepcopy(self.request)
                request[key] = value
                self.reject(request)

    def test_naive_invalid_and_future_cutoffs_are_rejected(self):
        for cutoff in ("2026-10-08T09:00:00", "not-a-timestamp",
                       (datetime.now(timezone.utc) + timedelta(days=2)).isoformat()):
            with self.subTest(cutoff=cutoff):
                request = copy.deepcopy(self.request)
                request["research_cutoff"] = cutoff
                self.reject(request)

    def test_relative_and_missing_input_roots_are_rejected(self):
        for root in ("relative-input", str(self.root / "absent")):
            with self.subTest(root=root):
                request = copy.deepcopy(self.request)
                request["input_root"] = root
                self.reject(request)

    def test_traversal_and_absolute_paths_are_rejected(self):
        for relative in ("../panel.parquet", str(self.root / "panel.parquet")):
            with self.subTest(relative=relative):
                request = copy.deepcopy(self.request)
                original = request["paths"]["panel"]
                request["paths"]["panel"] = relative
                request["files"][relative] = request["files"].pop(original)
                self.reject(request)

    def test_changed_bound_bytes_are_rejected(self):
        for role in self.request["paths"]:
            with self.subTest(role=role):
                path = Path(self.request["input_root"]) / self.request["paths"][role]
                before = path.read_bytes()
                path.write_bytes(before + b"\nCHANGED")
                self.reject(copy.deepcopy(self.request))
                path.write_bytes(before)

    def test_symlink_bound_file_and_input_root_are_rejected(self):
        source = Path(self.request["input_root"])
        panel = source / self.request["paths"]["panel"]
        outside = self.root / "outside-panel"
        outside.write_bytes(panel.read_bytes())
        panel.unlink()
        panel.symlink_to(outside)
        self.reject(copy.deepcopy(self.request))
        panel.unlink()
        panel.write_bytes(outside.read_bytes())
        link = self.root / "input-link"
        link.symlink_to(source, target_is_directory=True)
        request = copy.deepcopy(self.request)
        request["input_root"] = str(link)
        self.reject(request)

    def test_mismatched_manifest_dates_are_rejected_even_with_updated_raw_sha(self):
        for role, key in (("panel_manifest", "panel_max_date"),
                          ("master_manifest", "trade_date"),
                          ("master_receipt", "trade_date")):
            with self.subTest(role=role):
                request = copy.deepcopy(self.request)
                path = Path(request["input_root"]) / request["paths"][role]
                before = path.read_bytes()
                changed = json.loads(before)
                changed[key] = "20260930"
                json_file(path, changed)
                request["files"][request["paths"][role]] = digest(path.read_bytes())
                self.reject(request)
                path.write_bytes(before)

    def test_owner_availability_after_cutoff_is_rejected_with_other_hashes_valid(self):
        for role, key, reason in (("panel_manifest", "manifest_prepared_at", "REBOUND_PANEL_AFTER_CUTOFF"),
                                  ("master_manifest", "captured_at", "REBOUND_MASTER_AFTER_CUTOFF")):
            with self.subTest(role=role):
                request = copy.deepcopy(self.request)
                source = Path(request["input_root"])
                path = source / request["paths"][role]
                receipt_path = source / request["paths"]["master_receipt"]
                before, receipt_before = path.read_bytes(), receipt_path.read_bytes()
                changed = json.loads(before)
                changed[key] = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
                json_file(path, changed)
                request["files"][request["paths"][role]] = digest(path.read_bytes())
                if role == "master_manifest":
                    receipt = json.loads(receipt_before)
                    receipt["manifest_sha256"] = sha256_json(changed)
                    json_file(receipt_path, receipt)
                    request["files"][request["paths"]["master_receipt"]] = digest(receipt_path.read_bytes())
                with self.assertRaisesRegex(ValueError, reason):
                    owner.prepare_snapshot(request, self.root / ("late-" + role))
                path.write_bytes(before)
                receipt_path.write_bytes(receipt_before)

    def test_snapshot_copies_only_bound_bytes_and_builds_explicit_routing(self):
        source = Path(self.request["input_root"])
        source_before = {relative: (source / relative).read_bytes()
                         for relative in self.request["files"]}
        json_file(source / "assets/hk_0_2/panel_latest.json", {"poisoned": True})
        json_file(source / "assets/hk_security_master/latest.json", {"poisoned": True})
        (source / "unbound-secret.txt").write_text("DO NOT COPY")
        destination = self.root / "private-snapshot"
        identity = owner.prepare_snapshot(self.request, destination)
        self.assertIsInstance(identity, dict)
        self.assertEqual(identity["snapshot_sha256"], sha256_json(identity["files"]))
        self.assertEqual(identity["source_file_sha256"], self.request["files"])
        self.assertIs(identity["owner_origin_verified"], False)
        self.assertIs(identity["owner_read_lease_verified"], False)
        self.assertFalse((destination / "unbound-secret.txt").exists())
        for relative, before in source_before.items():
            with self.subTest(relative=relative):
                self.assertEqual((source / relative).read_bytes(), before)
                copied = destination / relative
                self.assertEqual(copied.read_bytes(), before)
                self.assertEqual(stat.S_IMODE(copied.stat().st_mode) & 0o222, 0)
        panel_pointer = json.loads((destination / "assets/hk_0_2/panel_latest.json").read_bytes())
        self.assertEqual(panel_pointer["manifest_relative"],
                         self.request["paths"]["panel_manifest"].removeprefix("assets/hk_0_2/"))
        master_pointer = json.loads((destination / "assets/hk_security_master/latest.json").read_bytes())
        self.assertEqual(set(master_pointer["entries"]), {SIGNAL})
        entry = master_pointer["entries"][SIGNAL]
        for key, role in (("manifest_relative", "master_manifest"),
                          ("receipt_relative", "master_receipt")):
            self.assertEqual(entry[key], self.request["paths"][role].removeprefix("assets/hk_security_master/"))

    def test_private_snapshot_is_independent_and_tampering_breaks_readback_identity(self):
        destination = self.root / "private-snapshot"
        identity = owner.prepare_snapshot(self.request, destination)
        relative = self.request["paths"]["panel"]
        private = destination / relative
        before = private.read_bytes()
        (Path(self.request["input_root"]) / relative).write_bytes(b"LATER SOURCE REVISION")
        self.assertEqual(private.read_bytes(), before)
        owner._verify_private(destination, identity)
        private.chmod(0o600)
        private.write_bytes(before + b"TAMPER")
        with self.assertRaises(ValueError):
            owner._verify_private(destination, identity)


class ReboundOwnerProjectionTests(unittest.TestCase):
    def projection(self, legacy=None):
        return owner.research_projection(
            legacy if legacy is not None else legacy_screen(),
            dict(unit_status="NOT_PROVEN", finality_status="NOT_ATTESTED"),
        )

    def test_projection_is_detached_and_preserves_grouping_and_algorithm_numbers(self):
        legacy = legacy_screen()
        before = copy.deepcopy(legacy)
        result = self.projection(legacy)
        self.assertEqual(legacy, before)
        self.assertEqual(result["coverage"], before["coverage"])
        for group in GROUPS:
            self.assertEqual([row["code"] for row in result[group]],
                             [row["code"] for row in before[group]])
            for projected, original in zip(result[group], before[group]):
                for key in ("classification", "close", "prior60_high",
                            "oversold_cutoff_80pct_prior60_high", "volume", "volume_ratio_5d"):
                    self.assertEqual(projected[key], original[key])
                self.assertEqual(projected["amount_native"], original["amount_hkd"])
                self.assertEqual(projected["observed_session"], original["verified_session"])
        result["strict"][0]["close"] = 999
        result["coverage"]["strict_count"] = 999
        self.assertEqual(legacy, before)

    def test_unproven_research_projection_removes_verified_unit_and_finality_claims_recursively(self):
        result = self.projection()
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assertIs(result["main_screen_ready"], False)
        self.assertEqual(result["observed_session"], SIGNAL)
        for node in walk(result):
            self.assertNotIn("amount_hkd", node)
            self.assertNotIn("verified_session", node)
            for key in ("currency", "price_currency", "amount_unit"):
                if key in node:
                    self.assertNotEqual(node[key], "HKD")
            if "session_kind" in node:
                self.assertNotEqual(node["session_kind"], "FULL_DAY_CLOSE")
            if "connect_eligibility" in node:
                self.assertEqual(node["connect_eligibility"], "UNVERIFIED")

    def test_gaps_and_empty_unknown_source_are_not_replaced_with_zeros(self):
        result = self.projection()
        self.assertIn("SCREEN_HISTORY_OR_VOLUME_INCOMPLETE:HK.00003", result["gaps"])
        legacy = legacy_screen()
        legacy.update(status="CANNOT_CONFIRM", main_screen_ready=False,
                      authority=None, input_identity=None, coverage={})
        for group in GROUPS:
            legacy[group] = []
        result = self.projection(legacy)
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assertIsNone(result["input_identity"])
        self.assertEqual(result["coverage"], {})


class ReboundOwnerPersistenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.request = request_for(self.root / "input")
        self.output = self.root / "output"
        self.output.mkdir()
        (self.output / ".v5-rebound-owner-root").write_bytes(b"v5.rebound-owner-root.v1\n")
        snapshot = owner.prepare_snapshot(self.request, self.root / "snapshot")
        legacy = legacy_screen()
        # Fabricated contract-only artifact: no original owner execution or
        # dependency attestation is claimed by this fixture.
        self.artifact = dict(
            schema_version="v5.rebound_owner.v1", run_id="1" * 32,
            request=self.request, request_sha256=sha256_json(self.request),
            source_capsule_sha256=owner.PIN,
            started_at=self.request["research_cutoff"],
            finished_at=datetime.now(timezone.utc).isoformat(),
            execution_kind="SYNTHETIC_TEST", snapshot=snapshot,
            snapshot_sha256=snapshot["snapshot_sha256"],
            implementation_identity=owner._identity(),
            context={"market_session": SIGNAL, "plan_trade_date": TARGET},
            formal_status="CANNOT_CONFIRM", computation_status="READY_WITH_GAPS",
            reason_codes=list(owner.BLOCKERS), dependencies={"status": "MATCH"},
            legacy_diagnostic={"status": "UNTRUSTED_LEGACY_ASSERTIONS", "payload": legacy},
            research_observation=owner.research_projection(legacy, {}),
            research_only=True, production_allowed=False, buy_gate_updated=False,
            orders_sent=False, natural_verified=False, formal_eligibility_verified=False,
        )

    def publish(self):
        reference = owner._publish(self.output, self.artifact)
        run = self.output / "runs" / reference["run_id"]
        return reference, run

    def test_committed_trio_roundtrips_and_reference_binds_every_file(self):
        reference, run = self.publish()
        self.assertEqual(set(reference), {"run_id", "artifact_sha256", "manifest_sha256", "receipt_sha256"})
        for name in ("artifact", "manifest", "receipt"):
            self.assertEqual(digest((run / (name + ".json")).read_bytes()), reference[name + "_sha256"])
        result = owner.read_rebound_owner(self.output, reference)
        self.assertEqual(result, self.artifact)
        result["research_observation"]["strict"].clear()
        self.assertEqual(owner.read_rebound_owner(self.output, reference), self.artifact)

    def test_raw_tampering_each_trio_member_is_rejected(self):
        reference, run = self.publish()
        for name in ("artifact", "manifest", "receipt"):
            with self.subTest(name=name):
                path = run / (name + ".json")
                before = path.read_bytes()
                path.write_bytes(before + b"\n")
                with self.assertRaises(ValueError):
                    owner.read_rebound_owner(self.output, reference)
                path.write_bytes(before)

    def test_receipt_identity_tampering_cannot_pass_with_rehashed_reference(self):
        reference, run = self.publish()
        path = run / "receipt.json"
        receipt = json.loads(path.read_bytes())
        receipt["run_id"] = "2" * 32
        json_file(path, receipt)
        reference["receipt_sha256"] = digest(path.read_bytes())
        with self.assertRaises(ValueError):
            owner.read_rebound_owner(self.output, reference)

    def test_manifest_request_binding_cannot_pass_with_rehashed_manifest_and_receipt(self):
        reference, run = self.publish()
        manifest_path, receipt_path = run / "manifest.json", run / "receipt.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["request_sha256"] = "0" * 64
        json_file(manifest_path, manifest)
        reference["manifest_sha256"] = digest(manifest_path.read_bytes())
        receipt = json.loads(receipt_path.read_bytes())
        receipt["manifest_sha256"] = reference["manifest_sha256"]
        json_file(receipt_path, receipt)
        reference["receipt_sha256"] = digest(receipt_path.read_bytes())
        with self.assertRaises(ValueError):
            owner.read_rebound_owner(self.output, reference)

    def test_formal_promotion_cannot_pass_even_when_all_three_file_hashes_are_rebound(self):
        reference, run = self.publish()
        artifact_path, manifest_path, receipt_path = (run / (name + ".json")
                                                       for name in ("artifact", "manifest", "receipt"))
        artifact = json.loads(artifact_path.read_bytes())
        artifact["formal_status"] = "OWNER_VERIFIED"
        artifact["formal_eligibility_verified"] = True
        json_file(artifact_path, artifact)
        reference["artifact_sha256"] = digest(artifact_path.read_bytes())
        manifest = json.loads(manifest_path.read_bytes())
        manifest["artifact_sha256"] = reference["artifact_sha256"]
        json_file(manifest_path, manifest)
        reference["manifest_sha256"] = digest(manifest_path.read_bytes())
        receipt = json.loads(receipt_path.read_bytes())
        receipt["artifact_sha256"] = reference["artifact_sha256"]
        receipt["manifest_sha256"] = reference["manifest_sha256"]
        json_file(receipt_path, receipt)
        reference["receipt_sha256"] = digest(receipt_path.read_bytes())
        with self.assertRaises(ValueError):
            owner.read_rebound_owner(self.output, reference)

    def test_missing_or_symlinked_receipt_is_never_a_committed_run(self):
        reference, run = self.publish()
        path = run / "receipt.json"
        outside = self.root / "outside-receipt.json"
        outside.write_bytes(path.read_bytes())
        path.unlink()
        with self.assertRaises((ValueError, OSError)):
            owner.read_rebound_owner(self.output, reference)
        path.symlink_to(outside)
        with self.assertRaises((ValueError, OSError)):
            owner.read_rebound_owner(self.output, reference)

    def test_unmarked_output_is_rejected_before_publication(self):
        marker = self.output / ".v5-rebound-owner-root"
        for content in (b"", b"v4-owner-root\n"):
            with self.subTest(content=content):
                marker.write_bytes(content)
                with self.assertRaises((ValueError, OSError)):
                    owner.run_rebound_owner(self.request, self.output)
                self.assertFalse((self.output / "runs").exists())

    def test_missing_proof_can_never_make_manager_screen_eligible(self):
        # Simulate the recorded-input contract; these bytes remain synthetic
        # unit-test material and are never passed to the original algorithm.
        self.artifact["request"]["data_kind"] = "RECORDED_INPUT_REPLAY"
        self.artifact["request_sha256"] = sha256_json(self.artifact["request"])
        self.artifact["execution_kind"] = "MANUAL_RECORDED_INPUT_REPLAY"
        reference, _ = self.publish()
        artifact = owner.read_rebound_owner(self.output, reference)
        result = owner.manager_projection(
            artifact, target_date=TARGET, market_session=SIGNAL,
            research_cutoff=datetime.now(timezone.utc).isoformat(),
        )
        self.assertEqual(result["status"], "CANNOT_CONFIRM")
        self.assertIsNone(result["eligible_screen"])
        self.assertIs(result["formal_eligibility_verified"], False)
        self.assertIs(result["natural_verified"], False)
        self.assertIs(result["orders_sent"], False)
        self.assertEqual(result["research_observation"], self.artifact["research_observation"])
        result["research_observation"]["strict"].clear()
        self.assertEqual(artifact, self.artifact)

    def test_manager_never_admits_synthetic_observations(self):
        result = owner.manager_projection(
            self.artifact, target_date=TARGET, market_session=SIGNAL,
            research_cutoff=datetime.now(timezone.utc).isoformat(),
        )
        self.assertIsNone(result["eligible_screen"])
        self.assertIsNone(result["research_observation"])
        self.assertEqual(result["data_kind"], "SYNTHETIC")
        self.assertIn("REBOUND_MANAGER_SYNTHETIC_NOT_ADMITTED", result["reason_codes"])

    def test_conflicting_snapshot_and_context_identities_are_rejected(self):
        for key in ("snapshot_sha256", "context"):
            with self.subTest(key=key):
                artifact = copy.deepcopy(self.artifact)
                if key == "snapshot_sha256":
                    artifact[key] = "0" * 64
                else:
                    artifact[key]["market_session"] = "20260930"
                with self.assertRaises(ValueError):
                    owner._validate_artifact(artifact)

    def test_manager_rejects_target_and_session_mismatches(self):
        for target, signal in (("20261009", SIGNAL), (TARGET, "20260930")):
            with self.subTest(target=target, signal=signal):
                result = owner.manager_projection(
                    self.artifact, target_date=target, market_session=signal,
                    research_cutoff=datetime.now(timezone.utc).isoformat(),
                )
                self.assertIsNone(result["eligible_screen"])
                self.assertIsNone(result["research_observation"])
                self.assertIn("REBOUND_MANAGER_DATE_MISMATCH", result["reason_codes"])

    def test_manager_rejects_artifacts_or_requests_after_its_cutoff(self):
        for key in ("request", "finished_at"):
            with self.subTest(key=key):
                artifact = copy.deepcopy(self.artifact)
                if key == "request":
                    cutoff = datetime.fromisoformat(artifact["request"]["research_cutoff"]) - timedelta(seconds=1)
                else:
                    cutoff = datetime.fromisoformat(artifact["started_at"])
                result = owner.manager_projection(
                    artifact, target_date=TARGET, market_session=SIGNAL,
                    research_cutoff=cutoff.isoformat(),
                )
                self.assertIsNone(result["eligible_screen"])
                self.assertIsNone(result["research_observation"])
                self.assertIn("REBOUND_MANAGER_AFTER_CUTOFF", result["reason_codes"])


ORIGINAL_FIXTURE_SCRIPT = """
import importlib, json, sys
from pathlib import Path
from v5_shadow import rebound_owner as owner
from fixtures.rebound_factory import publish_fixture
sources = owner._sources()
sys.meta_path.insert(0, owner._Loader(sources))
original = importlib.import_module('v4.manager_research.workspace_plan')
root = Path(sys.argv[1])
publish_fixture(root, original)
panel_asset = root / 'assets/hk_0_2'
panel_latest = json.loads((panel_asset / 'panel_latest.json').read_bytes())
panel_manifest = panel_asset / panel_latest['manifest_relative']
panel = json.loads(panel_manifest.read_bytes())
master_asset = root / 'assets/hk_security_master'
entry = json.loads((master_asset / 'latest.json').read_bytes())['entries']['20261007']
master_manifest = master_asset / entry['manifest_relative']
master = json.loads(master_manifest.read_bytes())
paths = dict(panel_manifest=panel_manifest, panel=panel_asset / panel['panel_relative'],
             master_manifest=master_manifest, master_artifact=master_asset / master['artifact_relative'],
             master_receipt=master_asset / entry['receipt_relative'])
print(json.dumps({role: str(path.relative_to(root)) for role, path in paths.items()}))
"""


@unittest.skipUnless(os.environ.get("V5_REBOUND_OWNER_ORIGINAL_TESTS") == "1",
                     "Mac original-owner test requires explicit opt-in and Python 3.14+ locked runtime")
class ReboundOriginalOwnerMacCandidates(unittest.TestCase):
    def test_original_owner_groups_survive_unverified_research_projection_and_readback(self):
        self.assertGreaterEqual(sys.version_info[:2], (3, 14))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source, output = root / "synthetic-owner", root / "output"
            source.mkdir()
            output.mkdir()
            (output / ".v5-rebound-owner-root").write_bytes(b"v5.rebound-owner-root.v1\n")
            env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(BASE / "src"), str(BASE / "tests"))),
                       PYTHONDONTWRITEBYTECODE="1")
            fixture = subprocess.run(
                [sys.executable, "-B", "-c", ORIGINAL_FIXTURE_SCRIPT, str(source)],
                capture_output=True, text=True, env=env, timeout=90,
            )
            self.assertEqual(fixture.returncode, 0, fixture.stderr)
            paths = json.loads(fixture.stdout)
            request = dict(
                schema_version="v5.rebound_owner_request.v1", target_date=TARGET, signal_date=SIGNAL,
                research_cutoff=datetime.now(timezone.utc).isoformat(), data_kind="SYNTHETIC",
                input_root=str(source.resolve()), paths=paths,
                files={relative: digest((source / relative).read_bytes()) for relative in paths.values()},
            )
            source_before = dict(request["files"])
            result = owner.run_rebound_owner(request, output)
            artifact = owner.read_rebound_owner(output, result["reference"])
            self.assertEqual(artifact, result["readback"])
            self.assertIn(artifact["computation_status"], ("READY", "READY_WITH_GAPS"), artifact["reason_codes"])
            self.assertEqual(artifact["formal_status"], "CANNOT_CONFIRM")
            projected = artifact["research_observation"]
            original = artifact["legacy_diagnostic"]["payload"]
            self.assertEqual(projected["coverage"], original["coverage"])
            self.assertEqual(projected["coverage"]["strict_count"], 1)
            self.assertEqual(projected["coverage"]["near_count"], 2)
            self.assertEqual(projected["coverage"]["excluded_count"], 1)
            for group in GROUPS:
                self.assertEqual([r["code"] for r in projected[group]], [r["code"] for r in original[group]])
            for node in walk(projected):
                self.assertNotIn("amount_hkd", node)
                self.assertNotIn("verified_session", node)
            self.assertIs(projected["main_screen_ready"], False)
            self.assertEqual(source_before, {p: digest((source / p).read_bytes()) for p in source_before})
            manager = owner.manager_projection(
                artifact, target_date=TARGET, market_session=SIGNAL,
                research_cutoff=datetime.now(timezone.utc).isoformat(),
            )
            self.assertIsNone(manager["eligible_screen"])
            self.assertIsNone(manager["research_observation"])
            self.assertIn("REBOUND_MANAGER_SYNTHETIC_NOT_ADMITTED", manager["reason_codes"])


if __name__ == "__main__":
    unittest.main()
