"""Mac candidates for panel-only arithmetic observations; cloud execution forbidden.

All locally generated data here are SYNTHETIC.  Identity-only cases deliberately
do not contain Parquet.  Opt-in differential cases use the frozen original
calculator and real synthetic Parquet in fresh disposable subprocesses.
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
from zoneinfo import ZoneInfo

from v5_shadow import rebound_observation as observation
from v5_shadow.digests import canonical_bytes, sha256_json


BASE = Path(__file__).resolve().parents[1]
SIGNAL, TARGET = "20261007", "20261008"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def panel_request(root):
    root.mkdir(parents=True, exist_ok=True)
    raw = b"SYNTHETIC PANEL IDENTITY ONLY; NOT PARQUET OR PRICES\n"
    relative = f"panels/{SIGNAL}-{sha(raw)[:12]}/hkconnect_vipdoc_daily_panel.parquet"
    paths = {
        "panel": "assets/hk_0_2/" + relative,
        "panel_manifest": "assets/hk_0_2/" + relative.rsplit("/", 1)[0] + "/manifest.json",
    }
    manifest = dict(
        asset_schema_version="v3_shared_data.hk_0_2_panel_asset.v2", panel_max_date=SIGNAL,
        panel_relative=relative, panel_sha256=sha(raw), panel_rows=1, panel_code_count=1,
        manifest_prepared_at="2026-10-07T17:30:00+08:00",
        source_contract="tdx_vipdoc_71_day+verified_zero_trade_repairs",
        research_only=True, production_allowed=False, buy_gate_updated=False, orders_sent=False,
    )
    write_json(root / paths["panel_manifest"], manifest)
    (root / paths["panel"]).write_bytes(raw)
    return dict(
        schema_version="v5.rebound_observation_request.v1", target_date=TARGET,
        signal_date=SIGNAL, data_kind="SYNTHETIC", input_root=str(root.resolve()),
        paths=paths, files={p: sha((root / p).read_bytes()) for p in paths.values()},
    )


class ReboundObservationInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.request = panel_request(self.root / "input")
        self.count = 0

    def reject(self, request):
        self.count += 1
        with self.assertRaises(ValueError):
            observation._request(request)
            observation.prepare_snapshot(
                request, self.root / f"rejected-{self.count}", datetime.now(timezone.utc).isoformat(),
            )

    def test_panel_only_request_requires_no_master(self):
        observation._request(self.request)
        self.assertFalse((self.root / "input/assets/hk_security_master").exists())

    def test_caller_cannot_inject_cutoff_observation_clock_or_master(self):
        for key, value in (
            ("research_cutoff", "2026-09-30T08:00:00+08:00"),
            ("observed_at", "2026-09-30T08:00:00+08:00"),
            ("master_receipt", "invented-receipt.json"),
        ):
            with self.subTest(key=key):
                request = copy.deepcopy(self.request)
                request[key] = value
                self.reject(request)

    def test_missing_roles_and_unbound_sha_are_rejected(self):
        for role in self.request["paths"]:
            with self.subTest(role=role):
                request = copy.deepcopy(self.request)
                del request["paths"][role]
                self.reject(request)
                request = copy.deepcopy(self.request)
                del request["files"][request["paths"][role]]
                self.reject(request)

    def test_date_kind_and_nonpanel_paths_are_rejected(self):
        for key, value in (("target_date", "20260230"), ("signal_date", TARGET),
                           ("data_kind", "RECORDED_INPUT_REPLAY"), ("data_kind", "LIVE")):
            with self.subTest(key=key, value=value):
                request = copy.deepcopy(self.request)
                request[key] = value
                self.reject(request)
        request = copy.deepcopy(self.request)
        request["files"]["assets/hk_security_master/runs/20261007/abc/receipt.json"] = "a" * 64
        self.reject(request)

    def test_recorded_current_input_cannot_request_historical_target(self):
        request = copy.deepcopy(self.request)
        request["data_kind"] = "RECORDED_INPUT_CURRENT"
        today = datetime.now(ZoneInfo("Asia/Hong_Kong"))
        request["target_date"] = (today - timedelta(days=7)).strftime("%Y%m%d")
        request["signal_date"] = (today - timedelta(days=8)).strftime("%Y%m%d")
        output = self.root / "output"
        output.mkdir()
        (output / ".v5-rebound-observation-root").write_bytes(b"v5.rebound-observation-root.v1\n")
        with self.assertRaises(ValueError):
            observation.run_rebound_observation(request, output)
        self.assertFalse((output / "runs").exists())

    def test_bound_byte_tampering_and_symlinks_are_rejected(self):
        for role in self.request["paths"]:
            with self.subTest(role=role):
                path = self.root / "input" / self.request["paths"][role]
                before = path.read_bytes()
                path.write_bytes(before + b"ALTERED")
                self.reject(copy.deepcopy(self.request))
                path.write_bytes(before)
        panel = self.root / "input" / self.request["paths"]["panel"]
        outside = self.root / "outside-panel"
        outside.write_bytes(panel.read_bytes())
        panel.unlink()
        panel.symlink_to(outside)
        self.reject(copy.deepcopy(self.request))

    def test_panel_manifest_semantic_binding_is_required_after_rehash(self):
        for key, value in (("panel_max_date", "20260930"), ("panel_sha256", "0" * 64),
                           ("panel_relative", "panels/other/hkconnect_vipdoc_daily_panel.parquet")):
            with self.subTest(key=key):
                request = copy.deepcopy(self.request)
                relative = request["paths"]["panel_manifest"]
                path = self.root / "input" / relative
                before = path.read_bytes()
                manifest = json.loads(before)
                manifest[key] = value
                write_json(path, manifest)
                request["files"][relative] = sha(path.read_bytes())
                self.reject(request)
                path.write_bytes(before)

    def test_snapshot_only_binds_panel_and_generated_routing(self):
        source = self.root / "input"
        write_json(source / "assets/hk_0_2/panel_latest.json", {"unbound": "wrong"})
        write_json(source / "assets/hk_security_master/latest.json", {"must_not_read": True})
        destination = self.root / "private"
        identity = observation.prepare_snapshot(self.request, destination, datetime.now(timezone.utc).isoformat())
        for relative in self.request["files"]:
            self.assertEqual((destination / relative).read_bytes(), (source / relative).read_bytes())
            self.assertEqual(stat.S_IMODE((destination / relative).stat().st_mode) & 0o222, 0)
        self.assertFalse((destination / "assets/hk_security_master").exists())
        pointer_path = "assets/hk_0_2/panel_latest.json"
        pointer = json.loads((destination / pointer_path).read_bytes())
        self.assertEqual(pointer["manifest_relative"],
                         self.request["paths"]["panel_manifest"].removeprefix("assets/hk_0_2/"))
        self.assertEqual(set(identity["files"]), {*self.request["files"], pointer_path})
        self.assertEqual(identity["snapshot_sha256"], sha256_json(identity["files"]))


# Intentionally independent of the extraction's field list: losing a raw
# arithmetic result or changing an internal boolean must fail this comparison.
PARITY_FIELDS = (
    "close", "prev_close", "day_positive_close_gt_prev_close", "pct_change",
    "current_volume", "close_position_0_low_1_high", "rebound_close_vs_low_pct", "rebound_ge_3pct",
    "recent_3_session_return_pct", "recent_5_session_return_pct", "history_status", "history_unknown_reasons",
    "prior60_session_count", "previous5_session_count", "previous20_session_count", "prior60_session_high",
    "oversold_cutoff_80pct_prior60_high", "previous5_mean_volume", "volume_ratio_5d",
    "previous20_mean_volume_background", "volume_ratio_20d_background", "background20_status", "oversold_flag",
    "volume_flag_5d_ge_1_5", "strict_two_gate_oversold_5dvolume", "near_two_gate_one_missing",
)


def raw_row():
    """Fabricated arithmetic fields, including legacy labels that must not leak."""
    row = {key: None for key in PARITY_FIELDS}
    row.update(
        code="HK.00001", name="SYNTHETIC ONLY", amount_hkd=1234567.89,
        close=7.0, prev_close=9.0, current_volume=200.0, prior60_session_count=60,
        previous5_session_count=5, previous20_session_count=20,
        prior60_session_high=10.0, oversold_cutoff_80pct_prior60_high=8.0,
        previous5_mean_volume=100.0, volume_ratio_5d=2.0,
        volume_ratio_current_to_previous5_mean=2.0, previous20_mean_volume_background=100.0,
        volume_ratio_20d_background=2.0, volume_ratio_current_to_previous20_mean_background=2.0,
        history_status="KNOWN", history_unknown_reasons=None, background20_status="KNOWN",
        oversold_flag=True, oversold_close_le_80pct_prior60_high=True,
        volume_flag_5d_ge_1_5=True, high_volume_ratio_ge_1_5=True,
        strict_two_gate_oversold_5dvolume=True, near_two_gate_one_missing=False,
        classification="STRICT_REBOUND", qualification_status="RESEARCH_ONLY_CANDIDATE",
        connect_eligibility="VERIFIED_TARGET_UNIVERSE", verified_session=int(SIGNAL),
        membership_source={"exchange": "HK_CONNECT"}, amount_unit="HKD", session_kind="FULL_DAY_CLOSE",
        panel_name="SYNTHETIC ONLY", amount_native=1234567.89, low_native=6.0, high_native=8.0,
        missing_prior60_dates=[], missing_previous5_dates=[], duplicate_prior60_dates=[], duplicate_previous5_dates=[],
    )
    return row


def walk_dicts(value):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from walk_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_dicts(item)


class ReboundObservationProjectionTests(unittest.TestCase):
    def test_public_projection_drops_selection_labels_and_false_proof(self):
        source = [raw_row()]
        before = copy.deepcopy(source)
        observed = datetime.now(timezone.utc).isoformat()
        projected = observation.project_rows(source, SIGNAL, observed)
        self.assertEqual(source, before)
        self.assertEqual(len(projected), 1)
        self.assertEqual(projected[0]["code"], source[0]["code"])
        for key in ("native_numbers", "native_comparisons", "arithmetic_pattern"):
            self.assertIn(key, projected[0])
        for node in walk_dicts(projected):
            for forbidden in ("classification", "qualification_status", "connect_eligibility",
                              "membership_source", "verified_session", "amount_hkd",
                              "strict_two_gate_oversold_5dvolume", "near_two_gate_one_missing"):
                self.assertNotIn(forbidden, node)
            for value in node.values():
                if isinstance(value, str):
                    self.assertNotIn(value, ("HKD", "FULL_DAY_CLOSE", "VERIFIED_TARGET_UNIVERSE",
                                             "STRICT_REBOUND", "NEAR_CONDITION", "OWNER_VERIFIED"))

    def test_public_projection_is_detached_and_never_substitutes_zero_for_missing(self):
        source = raw_row()
        source["amount_hkd"] = None
        source["amount_native"] = None
        source["close"] = None
        source["history_status"] = "PARTIAL_UNKNOWN"
        source["history_unknown_reasons"] = "CURRENT_CLOSE_MISSING_OR_INVALID"
        source["strict_two_gate_oversold_5dvolume"] = False
        before = copy.deepcopy(source)
        projected = observation.project_rows([source], SIGNAL, datetime.now(timezone.utc).isoformat())
        self.assertIsNone(projected[0]["native_numbers"]["close_native"])
        self.assertIsNone(projected[0]["native_numbers"]["amount_native"])
        projected[0]["native_numbers"]["close_native"] = 999
        projected[0]["missing_prior60_dates"].append("20260930")
        self.assertEqual(source, before)

    def test_complete_and_incomplete_inputs_are_arithmetic_patterns_only(self):
        for complete, left, right, pattern in (
            (True, True, True, "BOTH_COMPARISONS_TRUE"),
            (True, True, False, "ONE_COMPARISON_TRUE"),
            (True, False, False, "NEITHER_COMPARISON_TRUE"),
            (False, True, None, "INCOMPLETE_INPUT"),
        ):
            with self.subTest(complete=complete, left=left, right=right):
                raw = raw_row()
                raw.update(history_status="KNOWN" if complete else "PARTIAL_UNKNOWN",
                           oversold_flag=left, volume_flag_5d_ge_1_5=right)
                row = observation.project_rows([raw], SIGNAL, datetime.now(timezone.utc).isoformat())[0]
                self.assertEqual(row["arithmetic_pattern"], pattern)
                self.assertEqual(row["scale_status"], "NOT_PROVEN_ENTIRE_SELECTED_HISTORY")
                self.assertEqual(row["finality_status"], "NOT_ATTESTED_BY_PROVIDER")
                self.assertEqual(row["eligibility_status"], "UNVERIFIED")


DIFFERENTIAL_SCRIPT = r"""
import importlib, json, math, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from v5_shadow import rebound_owner as frozen
from v5_shadow import rebound_observation as observation
from fixtures.rebound_factory import publish_fixture
from test_rebound_observation import PARITY_FIELDS, sha, write_json
sources = frozen._sources()
sys.meta_path.insert(0, frozen._Loader(sources))
original = importlib.import_module('v4.manager_research.workspace_plan')
import pandas as pd
root, variant = Path(sys.argv[1]), sys.argv[2]
publish_fixture(root, original)
asset = root / 'assets/hk_0_2'
pointer = json.loads((asset / 'panel_latest.json').read_bytes())
manifest_path = asset / pointer['manifest_relative']
manifest = json.loads(manifest_path.read_bytes())
panel_path = asset / manifest['panel_relative']
frame = pd.read_parquet(panel_path)
day = '20261007'
history_sessions = original.rebound_history_sessions(day)
code = frame['code_norm'] == 'HK.00001'
current = code & (frame['trade_date_compact'] == day)
if variant == 'missing_prior60':
    frame = frame.loc[~(code & (frame['trade_date_compact'] == history_sessions['prior60'][0]))].copy()
elif variant == 'duplicate_history':
    extra = frame.loc[code & (frame['trade_date_compact'] == history_sessions['previous5'][0])]
    frame = pd.concat([frame, extra], ignore_index=True)
elif variant == 'duplicate_current':
    frame = pd.concat([frame, frame.loc[current]], ignore_index=True)
elif variant in ('close_missing', 'trade_missing', 'low_missing', 'amount_missing'):
    frame.loc[current, variant.removesuffix('_missing')] = float('nan')
elif variant == 'previous5_zero':
    frame.loc[code & frame['trade_date_compact'].isin(history_sessions['previous5']), 'trade'] = 0.0
elif variant == 'target_empty':
    frame = frame.loc[frame['trade_date_compact'] != day].copy()
elif variant in ('boundary_equal', 'price_above_boundary', 'volume_below_boundary'):
    frame.loc[current, 'close'] = math.nextafter(8.0, math.inf) if variant == 'price_above_boundary' else 8.0
    frame.loc[current, 'trade'] = math.nextafter(150.0, 0.0) if variant == 'volume_below_boundary' else 150.0
elif variant == 'background20_trade_nan':
    frame.loc[code & (frame['trade_date_compact'] == history_sessions['prior60'][-10]), 'trade'] = float('nan')
elif variant == 'outside_window_duplicate':
    extra = frame.loc[code & (frame['trade_date_compact'] == history_sessions['prior60'][0])].copy()
    extra['trade_date_compact'] = (datetime.strptime(history_sessions['prior60'][0], '%Y%m%d') - timedelta(days=1)).strftime('%Y%m%d')
    frame = pd.concat([frame, extra, extra], ignore_index=True)
frame.to_parquet(panel_path, index=False)
digest = sha(panel_path.read_bytes())
new_directory = panel_path.parent.with_name(day + '-' + digest[:12])
if new_directory != panel_path.parent:
    panel_path.parent.rename(new_directory)
panel_path = new_directory / panel_path.name
manifest_path = new_directory / 'manifest.json'
manifest.update(panel_sha256=digest, panel_relative=str(panel_path.relative_to(asset)), panel_rows=len(frame),
                panel_code_count=int(frame['code_norm'].nunique()))
write_json(manifest_path, manifest)
write_json(asset / 'panel_latest.json', {'manifest_relative': str(manifest_path.relative_to(asset))})
context = original.plan_context('20261008', now=datetime.now(timezone.utc))
direct = original.read_rebound_screen(root, context)
calculate = observation.extract_calculator(original)
extracted = calculate(frame, context, history_sessions, [])
if variant in ('duplicate_current', 'target_empty'):
    expected = 'SCREEN_PANEL_TARGET_DUPLICATE_CODE' if variant == 'duplicate_current' else 'SCREEN_PANEL_TARGET_SESSION_EMPTY'
    assert direct['status'] == 'CANNOT_CONFIRM', direct
    assert extracted['status'] == 'CANNOT_CONFIRM', extracted
    assert expected in direct['gaps'] and expected in extracted['gaps'], (direct['gaps'], extracted['gaps'])
    print(json.dumps({'variant': variant, 'empty_reason': expected}))
else:
    direct_rows = {row['code']: row for group in ('strict', 'near', 'pending', 'excluded', 'screen_unresolved')
                   for row in direct.get(group, [])}
    extracted_rows = {row['code']: row for row in extracted['rows']}
    assert direct_rows and direct_rows.keys() == extracted_rows.keys(), (direct, extracted)
    for stock, expected in direct_rows.items():
        for field in PARITY_FIELDS:
            assert field in extracted_rows[stock], (variant, stock, 'MISSING_FIELD', field)
            assert extracted_rows[stock][field] == expected[field], (variant, stock, field,
                extracted_rows[stock][field], expected[field])
        assert extracted_rows[stock]['amount_native'] == expected['amount_hkd'], (variant, stock, 'amount_native')
    selected = extracted_rows['HK.00001']
    if variant in ('missing_prior60', 'duplicate_history', 'close_missing', 'trade_missing', 'previous5_zero'):
        assert selected['history_status'] == 'PARTIAL_UNKNOWN', selected
        assert selected['strict_two_gate_oversold_5dvolume'] is False, selected
    if variant in ('low_missing', 'amount_missing', 'boundary_equal', 'background20_trade_nan', 'outside_window_duplicate'):
        assert selected['history_status'] == 'KNOWN', selected
        assert selected['strict_two_gate_oversold_5dvolume'] is True, selected
    if variant == 'low_missing':
        assert selected['rebound_close_vs_low_pct'] is None, selected
    if variant == 'amount_missing':
        assert selected['amount_native'] is None, selected
    if variant == 'boundary_equal':
        assert selected['volume_ratio_5d'] == 1.5 and selected['close'] == 8.0, selected
    if variant in ('price_above_boundary', 'volume_below_boundary'):
        assert selected['strict_two_gate_oversold_5dvolume'] is False, selected
        assert selected['near_two_gate_one_missing'] is True, selected
    if variant == 'background20_trade_nan':
        assert selected['previous20_mean_volume_background'] is None, selected
        assert selected['background20_status'] == 'PARTIAL_UNKNOWN', selected
    if variant == 'outside_window_duplicate':
        assert selected['duplicate_prior60_dates'] == [] and selected['duplicate_previous5_dates'] == [], selected
    print(json.dumps({'variant': variant, 'rows': len(extracted_rows), 'fields': len(PARITY_FIELDS)}))
"""


PANEL_ONLY_FIXTURE_SCRIPT = r"""
import importlib, json, shutil, sys
from pathlib import Path
from v5_shadow import rebound_owner as frozen
from fixtures.rebound_factory import publish_fixture
sys.meta_path.insert(0, frozen._Loader(frozen._sources()))
original = importlib.import_module('v4.manager_research.workspace_plan')
fixture, panel_only = Path(sys.argv[1]), Path(sys.argv[2])
publish_fixture(fixture, original)
asset = fixture / 'assets/hk_0_2'
pointer = json.loads((asset / 'panel_latest.json').read_bytes())
manifest_path = asset / pointer['manifest_relative']
manifest = json.loads(manifest_path.read_bytes())
paths = dict(panel_manifest=str(manifest_path.relative_to(fixture)),
             panel='assets/hk_0_2/' + manifest['panel_relative'])
for relative in paths.values():
    destination = panel_only / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(fixture / relative, destination)
assert not (panel_only / 'assets/hk_security_master').exists()
print(json.dumps(paths))
"""


@unittest.skipUnless(os.environ.get("V5_REBOUND_OBSERVATION_ORIGINAL_TESTS") == "1",
                     "Mac opt-in only: original owner needs Python 3.14+ and locked dependencies")
class ReboundObservationOriginalMacCandidates(unittest.TestCase):
    def test_extracted_arithmetic_matches_original_owner_for_every_mutation(self):
        self.assertGreaterEqual(sys.version_info[:2], (3, 14))
        variants = (
            "baseline", "missing_prior60", "duplicate_history", "duplicate_current",
            "close_missing", "trade_missing", "previous5_zero", "low_missing", "amount_missing", "target_empty",
            "boundary_equal", "price_above_boundary", "volume_below_boundary", "background20_trade_nan", "outside_window_duplicate",
        )
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve() / "SYNTHETIC"
                root.mkdir()
                env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(BASE / "src"), str(BASE / "tests"))),
                           PYTHONDONTWRITEBYTECODE="1")
                process = subprocess.run(
                    [sys.executable, "-B", "-c", DIFFERENTIAL_SCRIPT, str(root), variant],
                    capture_output=True, text=True, env=env, timeout=90,
                )
                self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
                result = json.loads(process.stdout)
                self.assertEqual(result["variant"], variant)

    def test_panel_only_original_run_persists_native_observations_without_master(self):
        self.assertGreaterEqual(sys.version_info[:2], (3, 14))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture, source, output = root / "SYNTHETIC-full-fixture", root / "panel-only", root / "output"
            fixture.mkdir()
            source.mkdir()
            output.mkdir()
            (output / ".v5-rebound-observation-root").write_bytes(b"v5.rebound-observation-root.v1\n")
            env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(BASE / "src"), str(BASE / "tests"))),
                       PYTHONDONTWRITEBYTECODE="1")
            builder = subprocess.run(
                [sys.executable, "-B", "-c", PANEL_ONLY_FIXTURE_SCRIPT, str(fixture), str(source)],
                capture_output=True, text=True, env=env, timeout=90,
            )
            self.assertEqual(builder.returncode, 0, builder.stdout + builder.stderr)
            paths = json.loads(builder.stdout)
            request = dict(
                schema_version="v5.rebound_observation_request.v1", target_date=TARGET, signal_date=SIGNAL,
                data_kind="SYNTHETIC", input_root=str(source), paths=paths,
                files={relative: sha((source / relative).read_bytes()) for relative in paths.values()},
            )
            before = copy.deepcopy(request)
            self.assertFalse((source / "assets/hk_security_master").exists())
            result = observation.run_rebound_observation(request, output)
            artifact = observation.read_rebound_observation(output, result["reference"])
            self.assertEqual(artifact, result["readback"])
            self.assertEqual(artifact["computation_status"], "NATIVE_VALUES_OBSERVED", artifact["reason_codes"])
            self.assertEqual(artifact["counts"], dict(observed_rows=4, numeric_input_complete=4, numeric_input_incomplete=0))
            self.assertEqual(artifact["formal_status"], "CANNOT_CONFIRM")
            self.assertIsNone(artifact["eligible_screen"])
            self.assertEqual(artifact["snapshot"]["security_master"], "NOT_BOUND_NOT_SYNTHESIZED")
            self.assertEqual(set(artifact["snapshot"]["files"]), {*paths.values(), "assets/hk_0_2/panel_latest.json"})
            self.assertEqual(artifact["scale_evidence"]["price_scale_consistency"], "NOT_PROVEN")
            self.assertEqual(artifact["scale_evidence"]["volume_scale_consistency"], "NOT_PROVEN")
            self.assertEqual(artifact["finality_status"], "NOT_ATTESTED_BY_PROVIDER")
            self.assertEqual(artifact["eligibility_status"], "UNVERIFIED")
            patterns = [row["arithmetic_pattern"] for row in artifact["rows"]]
            self.assertEqual(patterns.count("BOTH_COMPARISONS_TRUE"), 1)
            self.assertEqual(patterns.count("ONE_COMPARISON_TRUE"), 2)
            self.assertEqual(patterns.count("NEITHER_COMPARISON_TRUE"), 1)
            for row in artifact["rows"]:
                self.assertNotIn("classification", row)
                self.assertNotIn("strict", row)
                self.assertNotIn("near", row)
            self.assertNotIn("research_cutoff", request)
            self.assertNotIn("observed_at", request)
            self.assertLessEqual(datetime.fromisoformat(artifact["started_at"]), datetime.fromisoformat(artifact["observed_at"]))
            self.assertLessEqual(datetime.fromisoformat(artifact["observed_at"]), datetime.fromisoformat(artifact["finished_at"]))
            self.assertEqual(request, before)
            self.assertEqual(request["files"], {p: sha((source / p).read_bytes()) for p in paths.values()})
            self.assertFalse((source / "assets/hk_security_master").exists())
            manager = observation.manager_observation(
                artifact, target_date=TARGET, market_session=SIGNAL,
                research_cutoff=datetime.now(timezone.utc).isoformat(),
            )
            self.assertIsNone(manager["rows"])
            self.assertIsNone(manager["eligible_screen"])
            self.assertIn("OBSERVATION_MANAGER_SYNTHETIC_REJECTED", manager["reason_codes"])
            # Recomputed file hashes must not bless false semantic claims.
            for changed in ("nested_eligibility", "pattern", "scale", "source", "row_label"):
                with self.subTest(semantic_tampering=changed):
                    altered = copy.deepcopy(artifact)
                    if changed == "nested_eligibility":
                        altered["rows"][0]["native_numbers"]["eligible"] = True
                    elif changed == "pattern":
                        altered["rows"][0]["arithmetic_pattern"] = "NEITHER_COMPARISON_TRUE"
                    elif changed == "scale":
                        altered["scale_evidence"]["price_currency"] = "HKD"
                    elif changed == "source":
                        altered["source_identity"]["panel_sha256"] = "0" * 64
                    else:
                        altered["rows"][0]["classification"] = "STRICT_REBOUND"
                    with self.assertRaises(ValueError):
                        observation._validate(altered)
            for name in ("artifact", "manifest", "receipt"):
                with self.subTest(tampered=name):
                    path = output / "runs" / artifact["run_id"] / (name + ".json")
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n")
                    with self.assertRaises(ValueError):
                        observation.read_rebound_observation(output, result["reference"])
                    path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
