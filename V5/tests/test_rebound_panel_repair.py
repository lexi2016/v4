"""Mac candidate tests; NEVER executed as cloud product validation.

Synthetic tests use the pinned original parser/enrichment AST verbatim, but
explicitly stub owner identity and model loading. They do not prove the real
model bundle exists. Real-owner tests use a fresh process and opt in with
V5_REBOUND_REPAIR_ORIGINAL_TESTS=1. The private real-asset preparation test also
requires V5_REBOUND_REPAIR_REAL_INPUT to name a locally prepared binding JSON.
Neither real test writes the original owner assets or imports a fake model.
"""
import ast
import copy
import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from v5_shadow import rebound_panel_repair as repair
from v5_shadow.digests import canonical_bytes, sha256_json


BASE = Path(__file__).resolve().parents[1]
ORIGINAL = BASE / "vendor/hk_preselection_baseline/upstreams/v3_shared_data/shared_data/hk_0_2.py"
ORIGINAL_SHA = "27da90f0e623e45fa1a27af7dcc3b6e5e1ff2320bae1c61bd903ed82050beb89"
NATIVE = struct.Struct("<IfffffII")
THROUGH = "20261008"
NATIVE_PATH = "vipdoc/ds/lday/71#00001.day"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def native(day, *, opening=10.0, high=20.0, low=5.0, close=11.0,
           amount=1234.5, trade=17, position=3):
    return NATIVE.pack(int(day), opening, high, low, close, amount, trade, position)


class SyntheticStoreError(ValueError):
    """Only the original helper exception class is replaced in AST tests."""


def original_helpers_with_synthetic_orchestration():
    raw = ORIGINAL.read_bytes()
    if digest(raw) != ORIGINAL_SHA:
        raise AssertionError("SYNTHETIC_TEST_ORIGINAL_SOURCE_SHA_CHANGED")
    names = {"_compact_date", "_normalize_code", "_read_vipdoc_increment", "_enrich_vipdoc_increment"}
    constants = {"_VIPDOC_DAY_STRUCT", "_MAX_CROSS_DAY_CLOSE_RATIO", "_MAX_PRE_CLOSE_GAP_CALENDAR_DAYS"}
    selected = []
    for node in ast.parse(raw).body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in constants for t in node.targets):
            selected.append(node)
    module = types.ModuleType("SYNTHETIC_AST_HELPERS_NOT_VERIFIED_OWNER")
    module.__file__ = str(ORIGINAL)
    module.__dict__.update(Path=Path, struct=struct, datetime=datetime, math=math,
                           Any=object, StoreError=SyntheticStoreError)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(ORIGINAL), "exec"), module.__dict__)
    if not names <= set(module.__dict__):
        raise AssertionError("SYNTHETIC_TEST_ORIGINAL_HELPERS_MISSING")
    module.sha256_file = lambda path: digest(Path(path).read_bytes())
    module.update_hk_0_2_panel_from_vipdoc = Mock(name="SYNTHETIC_normal_owner_delegate")
    return module


class SyntheticRepairFixture:
    """Real parquet/native bytes; model checks are deliberately mocked."""

    def __init__(self, root):
        import pandas as pd
        self.root = root
        self.asset = root / "SYNTHETIC_owned_assets"
        self.tdx = root / "SYNTHETIC_native_capture"
        self.capture_root = root / "SYNTHETIC_capture_binding"
        self.asset.mkdir(); self.tdx.mkdir(); self.capture_root.mkdir()
        self.module = original_helpers_with_synthetic_orchestration()
        self.module.load_frozen_hk_0_2_assets = Mock(name="SYNTHETIC_model_loader", side_effect=self.current_assets)
        self.panel_relative = "panels/20261008-synthetic-parent/hkconnect_vipdoc_daily_panel.parquet"
        self.manifest_relative = "panels/20261008-synthetic-parent/manifest.json"
        rows = []
        for code, day, close in (("HK.00001", "20260928", 10.0),
                                 ("HK.00001", "20260930", 12.0),
                                 ("HK.00001", "20261002", 14.0),
                                 ("HK.00001", THROUGH, 16.0),
                                 ("HK.00002", "20260928", 100.0),
                                 ("HK.00002", THROUGH, 110.0)):
            rows.append(dict(code_norm=code, trade_date_compact=day, open=close, high=close+2,
                low=close-2, close=close, amount=456.0, trade=23, pre_close=999.0,
                continuity_segment_id=7, continuity_break="ORIGINAL_UNCHANGED",
                pct_chg=987.0, amplitude_pct=654.0, intraday_high_pct=321.0,
                original_only="KEEP:"+code+":"+day))
        self.frame = pd.DataFrame(rows)
        self.request = dict(schema_version="v5.hk02_internal_gap_request.v1", through_date=THROUGH,
            parent_manifest_relative=self.manifest_relative, parent_panel_relative=self.panel_relative,
            keys=[dict(code="HK.00001", date="20260929"), dict(code="HK.00001", date="20261005")],
            native_files={})
        self.bind_parent(self.frame)
        self.bind_native(native("20260927") + native("20260929", close=11.0)
                         + native("20261009") + native("20261005", close=13.0))

    def bind_parent(self, frame):
        self.frame = frame
        path = self.asset / self.panel_relative
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.to_parquet(path, index=False)
        manifest = dict(asset_schema_version="v3_shared_data.hk_0_2_panel_asset.v2",
            source_contract="SYNTHETIC_PARENT_NOT_FINANCIAL_ATTESTATION",
            panel_relative=self.panel_relative, panel_sha256=digest(path.read_bytes()),
            panel_max_date=THROUGH, panel_rows=len(frame), panel_code_count=int(frame.code_norm.nunique()))
        write_json(self.asset / self.manifest_relative, manifest)
        write_json(self.asset / "panel_latest.json", dict(manifest_relative=self.manifest_relative))
        self.request.update(parent_panel_sha256=manifest["panel_sha256"],
            parent_manifest_sha256=digest((self.asset / self.manifest_relative).read_bytes()),
            parent_pointer_sha256=digest((self.asset / "panel_latest.json").read_bytes()))

    def bind_native(self, raw):
        path = self.tdx / NATIVE_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        self.request["native_files"] = {NATIVE_PATH: digest(raw)}
        self.authorize_synthetic_request()

    def authorize_synthetic_request(self, **capture_changes):
        now = datetime.now(timezone.utc)
        evidence = dict(schema_version="v5.hk02_native_capture_binding.v1",
            native_files=copy.deepcopy(self.request["native_files"]),
            repair_keys_sha256=sha256_json(self.request["keys"]), native_layout="<IfffffII",
            scale_applied=1, conversion_applied=False, clock_basis="ACTUAL_CAPTURE_NOT_BAR_LABEL",
            capture_started_at=(now-timedelta(seconds=2)).isoformat(),
            capture_finished_at=(now-timedelta(seconds=1)).isoformat())
        evidence.update(capture_changes)
        write_json(self.capture_root / "capture.json", evidence)
        self.authority = repair.OwnerRepairAuthority(asset_root=self.asset,
            approved_request_sha256=sha256_json(self.request), capture_root=self.capture_root,
            capture_relative="capture.json", capture_sha256=digest((self.capture_root / "capture.json").read_bytes()))

    def bind_synthetic_raw_fetch_record(self):
        from v5_shadow import rebound_raw_repair
        now = datetime.now(timezone.utc)
        source_rows = [dict(datetime=day, open=10.0, high=20.0, low=5.0, close=close,
                            trade=trade, amount=None)
                       for day, close, trade in (("2026-09-29 15:00", 11.0, 45276),
                                                 ("2026-10-05 15:00", 13.0, 38090))]
        query = dict(category=4, market=71, code="00001", start=0, count=6,
                     requested_sessions=[row["date"] for row in self.request["keys"]])
        record = dict(code="HK.00001", status="READY", error_code=None, request=query,
            request_sha256=sha256_json(query), source_rows=source_rows,
            response_sha256=sha256_json(source_rows), returned_count=len(source_rows),
            request_started_at=(now-timedelta(seconds=3)).isoformat(),
            response_acquired_at=(now-timedelta(seconds=2)).isoformat(),
            request_finished_at=(now-timedelta(seconds=1)).isoformat(),
            # Derived cached bars deliberately differ; only original source_rows
            # may enter the unchanged decoder. This is an explicit synthetic trap.
            bars=[dict(row, trade=row["trade"]*100) for row in source_rows], missing_sessions=[])
        relative = "raw/SYNTHETIC_original_fetch_record.json"
        write_json(self.tdx / relative, dict(fixture_kind="SYNTHETIC_NOT_PROVIDER_CAPTURE", records=[record]))
        self.request.pop("native_files")
        self.request.update(schema_version="v5.hk02_pytdx_raw_repair_request.v1",
            sources=[dict(relative=relative, sha256=digest((self.tdx / relative).read_bytes()),
                          record_pointer="/records/0")])
        capture = dict(schema_version="v5.hk02_pytdx_capture_binding.v1",
            raw_sources_sha256=sha256_json(self.request["sources"]),
            decoder_source_sha256=rebound_raw_repair.DECODER_SHA,
            repair_keys_sha256=sha256_json(self.request["keys"]), scale_applied=1,
            conversion_applied=False, clock_basis="ACTUAL_CAPTURE_NOT_BAR_LABEL",
            capture_started_at=record["request_started_at"], capture_finished_at=record["request_finished_at"])
        write_json(self.capture_root / "capture.json", capture)
        self.authority = repair.OwnerRepairAuthority(asset_root=self.asset,
            approved_request_sha256=sha256_json(self.request), capture_root=self.capture_root,
            capture_relative="capture.json", capture_sha256=digest((self.capture_root / "capture.json").read_bytes()))
        return record

    def current_assets(self, asset_root):
        asset_root = Path(asset_root)
        pointer = json.loads((asset_root / "panel_latest.json").read_bytes())
        manifest = json.loads((asset_root / pointer["manifest_relative"]).read_bytes())
        return types.SimpleNamespace(panel_path=asset_root / manifest["panel_relative"], panel_manifest=manifest)

    def prepare(self):
        return repair.prepare_internal_gap_repair(self.module, self.asset, tdx_root=self.tdx,
            request=self.request, authority=self.authority)

    def publish(self):
        return repair.update_hk_0_2_panel_from_vipdoc(self.module, self.asset, tdx_root=self.tdx,
            through_date=THROUGH, repair=self.request, authority=self.authority)

    def bound_files(self, result):
        manifest = json.loads((self.asset / result["manifest_relative"]).read_bytes())
        names = (result["manifest_relative"], manifest["panel_relative"], result["receipt_relative"],
                 self.manifest_relative, self.panel_relative)
        return {name: digest((self.asset / name).read_bytes()) for name in names}

    def witness(self, result, expected=None, cutoff=None):
        return repair.read_repaired_panel_witness(self.asset, result["manifest_relative"],
            expected_files=self.bound_files(result) if expected is None else expected,
            cutoff=datetime.now(timezone.utc).isoformat() if cutoff is None else cutoff)


class ReboundPanelRepairSyntheticCandidates(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.fx = SyntheticRepairFixture(Path(self.temporary.name).resolve())
        self.verification = patch.object(repair, "_verify_owner", return_value=None)
        self.verify = self.verification.start()
        self.addCleanup(self.verification.stop)

    def test_normal_update_delegates_original_arguments_return_and_exception(self):
        original = self.fx.module.update_hk_0_2_panel_from_vipdoc
        sentinel = object(); original.return_value = sentinel
        actual = repair.update_hk_0_2_panel_from_vipdoc(self.fx.module, self.fx.asset,
            tdx_root=self.fx.tdx, through_date=THROUGH, minimum_code_count=500)
        self.assertIs(actual, sentinel)
        original.assert_called_once_with(self.fx.asset, tdx_root=self.fx.tdx,
            through_date=THROUGH, minimum_code_count=500)
        self.fx.module.load_frozen_hk_0_2_assets.assert_not_called()
        original.side_effect = SyntheticStoreError("ORIGINAL_FAILURE")
        with self.assertRaisesRegex(SyntheticStoreError, "ORIGINAL_FAILURE"):
            repair.update_hk_0_2_panel_from_vipdoc(self.fx.module, self.fx.asset,
                tdx_root=self.fx.tdx, through_date=THROUGH)

    def test_pure_prepare_preserves_all_old_values_and_noncontiguous_prefixes(self):
        import pandas as pd
        original_files = {str(p): p.read_bytes() for root in (self.fx.asset, self.fx.tdx, self.fx.capture_root)
                          for p in root.rglob("*") if p.is_file()}
        request_before = copy.deepcopy(self.fx.request)
        built = self.fx.prepare()
        old, frame = built["existing"], built["frame"]
        pd.testing.assert_frame_equal(frame.iloc[:len(old)][old.columns].reset_index(drop=True), old, check_dtype=False)
        additions = frame.iloc[len(old):].set_index("trade_date_compact")
        self.assertEqual(set(additions.index), {"20260929", "20261005"})
        self.assertEqual(additions.loc["20260929", "pre_close"], 10.0)
        self.assertEqual(additions.loc["20261005", "pre_close"], 14.0)
        self.assertEqual(additions.loc["20261005", "continuity_segment_id"], 7)
        self.assertAlmostEqual(additions.loc["20261005", "pct_chg"], (13.0/14.0-1)*100)
        self.assertNotIn(16.0, additions.pre_close.tolist())
        self.assertEqual(self.fx.request, request_before)
        self.assertEqual(original_files, {str(p): p.read_bytes() for root in (self.fx.asset, self.fx.tdx, self.fx.capture_root)
                                         for p in root.rglob("*") if p.is_file()})
        self.assertGreaterEqual(self.fx.module.load_frozen_hk_0_2_assets.call_count, 2)
        self.assertEqual(built["lineage"]["scale_applied"], 1)
        self.assertFalse(built["lineage"]["conversion_applied"])
        self.assertFalse(built["lineage"]["successor_derived_fields_recomputed"])
        self.assertEqual(built["lineage"]["price_basis"], "NOT_PROVEN")
        self.assertIsNone(built["lineage"]["volume_unit"])

    def test_internal_prior60_key_and_consecutive_gaps_use_prior_addition(self):
        first = "20260929"; second = "20260930"
        self.fx.bind_parent(self.fx.frame.loc[self.fx.frame.trade_date_compact != second].copy())
        self.fx.request["keys"] = [dict(code="HK.00001", date=first), dict(code="HK.00001", date=second)]
        self.fx.bind_native(native(first, close=11) + native(second, close=12))
        built = self.fx.prepare()
        additions = built["frame"].iloc[len(built["existing"]):].set_index("trade_date_compact")
        self.assertEqual(additions.loc[first, "pre_close"], 10)
        self.assertEqual(additions.loc[second, "pre_close"], 11)
        self.assertTrue(set(additions.index) <= set(repair._history_window(THROUGH)["prior60"]))

    def test_repair_keys_must_be_unique_dates_in_original_hk_prior60(self):
        for day in (THROUGH, "20261009", "20250102", "20261001", "20261004"):
            with self.subTest(day=day):
                request = copy.deepcopy(self.fx.request)
                request["keys"][0]["date"] = day
                with self.assertRaisesRegex(ValueError, "REPAIR_KEY_NOT_INTERNAL_OR_DUPLICATE"):
                    repair._request(request, THROUGH)
        request = copy.deepcopy(self.fx.request)
        request["keys"].append(dict(request["keys"][0]))
        with self.assertRaisesRegex(ValueError, "REPAIR_KEY_NOT_INTERNAL_OR_DUPLICATE"):
            repair._request(request, THROUGH)

    def test_native_record_offsets_are_bound_and_unrequested_rows_are_excluded(self):
        built = self.fx.prepare()
        rows = built["lineage"]["row_evidence"]
        raw = (self.fx.tdx / NATIVE_PATH).read_bytes()
        self.assertEqual([r["record_offset"] for r in rows], [NATIVE.size, 3*NATIVE.size])
        for row in rows:
            offset = row["record_offset"]
            self.assertEqual(row["raw_file"], NATIVE_PATH)
            self.assertEqual(row["raw_file_sha256"], digest(raw))
            self.assertEqual(row["record_sha256"], digest(raw[offset:offset+NATIVE.size]))
        self.assertEqual(built["lineage"]["added_rows"], 2)
        self.assertFalse(built["lineage"]["production_allowed"])

    def test_duplicate_native_date_does_not_take_last(self):
        raw = (self.fx.tdx / NATIVE_PATH).read_bytes()
        self.fx.bind_native(raw + native("20260929", close=18))
        with self.assertRaisesRegex(ValueError, "REPAIR_NATIVE_DUPLICATE_DATE"):
            self.fx.prepare()

    def test_duplicate_parent_and_existing_requested_key_never_overwrite(self):
        import pandas as pd
        original = self.fx.frame.copy()
        self.fx.bind_parent(pd.concat([original, original.iloc[[0]]], ignore_index=True))
        self.fx.authorize_synthetic_request()
        with self.assertRaisesRegex(ValueError, "REPAIR_PARENT_DUPLICATES"):
            self.fx.prepare()
        self.fx.bind_parent(original)
        self.fx.request["keys"][0]["date"] = "20260928"
        self.fx.authorize_synthetic_request()
        before = (self.fx.asset / self.fx.panel_relative).read_bytes()
        with self.assertRaisesRegex(ValueError, "REPAIR_EXISTING_KEY_NOT_OVERWRITTEN"):
            self.fx.prepare()
        self.assertEqual((self.fx.asset / self.fx.panel_relative).read_bytes(), before)

    def test_original_model_loader_failure_propagates_before_native_parsing(self):
        self.fx.module.load_frozen_hk_0_2_assets.side_effect = SyntheticStoreError("REAL_MODEL_ASSETS_MISSING")
        with patch.object(self.fx.module, "_read_vipdoc_increment", wraps=self.fx.module._read_vipdoc_increment) as parser:
            with self.assertRaisesRegex(SyntheticStoreError, "REAL_MODEL_ASSETS_MISSING"):
                self.fx.prepare()
            parser.assert_not_called()
        self.fx.module.load_frozen_hk_0_2_assets.assert_called_once_with(self.fx.asset)

    def test_native_sha_trailing_bytes_and_missing_exact_key_fail_closed(self):
        original = (self.fx.tdx / NATIVE_PATH).read_bytes()
        (self.fx.tdx / NATIVE_PATH).write_bytes(original + native("20260926"))
        with self.assertRaisesRegex(ValueError, "REPAIR_NATIVE_SHA_OR_RECORD_LENGTH"):
            self.fx.prepare()
        self.fx.bind_native(original + b"x")
        with self.assertRaisesRegex(ValueError, "REPAIR_NATIVE_SHA_OR_RECORD_LENGTH"):
            self.fx.prepare()
        self.fx.bind_native(native("20260929"))
        with self.assertRaisesRegex(ValueError, "REPAIR_NATIVE_EXACT_KEYS_MISSING"):
            self.fx.prepare()

    def test_invalid_ohlc_is_rejected_but_zero_trade_and_nan_optional_amount_survive(self):
        for changes in (dict(opening=30), dict(close=30), dict(high=float("nan")), dict(low=-1), dict(close=float("inf"))):
            with self.subTest(changes=changes):
                self.fx.bind_native(native("20260929", **changes) + native("20261005", close=13))
                with self.assertRaisesRegex(ValueError, "REPAIR_(NATIVE_OHLC_INVALID|ORIGINAL_READER_REJECTED_ROWS)"):
                    self.fx.prepare()
        self.fx.bind_native(native("20260929", trade=0, amount=float("nan")) + native("20261005", close=13))
        built = self.fx.prepare()
        added = built["frame"].iloc[len(built["existing"])]
        self.assertEqual(added["trade"], 0)
        self.assertTrue(math.isnan(added["amount"]))

    def test_symlink_and_request_path_scope_are_rejected(self):
        native_path = self.fx.tdx / NATIVE_PATH
        original = native_path.read_bytes()
        outside = self.fx.root / "outside.day"; outside.write_bytes(original)
        native_path.unlink(); native_path.symlink_to(outside)
        with self.assertRaises((ValueError, OSError)):
            self.fx.prepare()
        native_path.unlink(); native_path.write_bytes(original)
        self.fx.request["native_files"]["vipdoc/ds/lday/71#00002.day"] = digest(original)
        self.fx.authorize_synthetic_request()
        with self.assertRaisesRegex(ValueError, "REPAIR_NATIVE_FILE_SCOPE"):
            self.fx.prepare()
        self.fx.request["native_files"].pop("vipdoc/ds/lday/71#00002.day")
        self.fx.request["parent_manifest_relative"] = "../manifest.json"
        self.fx.authorize_synthetic_request()
        with self.assertRaisesRegex(ValueError, "REPAIR_PARENT_PATH"):
            self.fx.prepare()

    def test_capture_requires_deployment_authority_exact_request_and_actual_clock(self):
        with self.assertRaisesRegex(ValueError, "REPAIR_DEPLOYMENT_AUTHORITY_REQUIRED"):
            repair.prepare_internal_gap_repair(self.fx.module, self.fx.asset, tdx_root=self.fx.tdx,
                request=self.fx.request, authority=None)
        self.fx.request["keys"].reverse()
        with self.assertRaisesRegex(ValueError, "REPAIR_UNAPPROVED_REQUEST"):
            self.fx.prepare()
        future = (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        self.fx.authorize_synthetic_request(capture_finished_at=future)
        with self.assertRaisesRegex(ValueError, "REPAIR_CAPTURE_BINDING"):
            self.fx.prepare()
        self.fx.authorize_synthetic_request()
        (self.fx.capture_root / "capture.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "REPAIR_CAPTURE_SHA"):
            self.fx.prepare()

    def test_parent_pointer_manifest_and_panel_sha_each_fail_closed(self):
        for key in ("parent_pointer_sha256", "parent_manifest_sha256", "parent_panel_sha256"):
            with self.subTest(key=key):
                before = self.fx.request[key]
                self.fx.request[key] = "f"*64
                self.fx.authorize_synthetic_request()
                with self.assertRaisesRegex(ValueError, "REPAIR_PARENT_"):
                    self.fx.prepare()
                self.fx.request[key] = before
        self.fx.authorize_synthetic_request()

    def test_publication_creates_bound_revision_receipt_and_unverified_witness(self):
        old_panel = (self.fx.asset / self.fx.panel_relative).read_bytes()
        old_manifest = (self.fx.asset / self.fx.manifest_relative).read_bytes()
        result = self.fx.publish()
        self.assertEqual(result["status"], "REPAIRED_NATIVE_ROWS")
        self.assertFalse(result["reused"])
        self.assertFalse(result["formal_eligibility_verified"])
        self.assertEqual(result["new_row_count"], 2)
        self.assertEqual((self.fx.asset / self.fx.panel_relative).read_bytes(), old_panel)
        self.assertEqual((self.fx.asset / self.fx.manifest_relative).read_bytes(), old_manifest)
        manifest = json.loads((self.fx.asset / result["manifest_relative"]).read_bytes())
        receipt = json.loads((self.fx.asset / result["receipt_relative"]).read_bytes())
        self.assertEqual(manifest["source_contract"], repair.SOURCE_CONTRACT)
        self.assertEqual(manifest["parent_panel_sha256"], self.fx.request["parent_panel_sha256"])
        self.assertEqual(receipt["manifest_sha256"], result["manifest_sha256"])
        self.assertEqual(receipt["request_sha256"], sha256_json(self.fx.request))
        self.assertEqual(receipt["panel_sha256"], result["panel_sha256"])
        witness = self.fx.witness(result)
        self.assertEqual(witness["panel_sha256"], result["panel_sha256"])
        self.assertEqual(witness["price_basis"], "UNVERIFIED_NATIVE")
        self.assertEqual(witness["session_kind"], "UNVERIFIED_DAILY_RECORD")
        self.assertIsNone(witness["price_currency"])
        self.assertIsNone(witness["amount_unit"])

    def test_raw_record_publish_preserves_old_values_native_trade_and_reuses_receipt(self):
        import pandas as pd
        from v5_shadow import rebound_raw_repair
        record = self.fx.bind_synthetic_raw_fetch_record()
        raw_source = self.fx.tdx / self.fx.request["sources"][0]["relative"]
        raw_before = raw_source.read_bytes()
        parent_before = (self.fx.asset / self.fx.panel_relative).read_bytes()
        capture_before = (self.fx.capture_root / "capture.json").read_bytes()
        # Real bound decoder and original enrichment run; only owner identity/
        # model loading are stubbed by this explicitly synthetic test class.
        with patch.object(self.fx.module, "_read_vipdoc_increment", side_effect=AssertionError("RAW_MUST_NOT_USE_NATIVE_FILES")):
            result = self.fx.publish()
        self.assertEqual(result["status"], "REPAIRED_RAW_ROWS")
        self.assertFalse(result["reused"])
        self.assertFalse(result["formal_eligibility_verified"])
        self.assertIn("-raw-repair-", result["manifest_relative"])
        manifest = json.loads((self.fx.asset / result["manifest_relative"]).read_bytes())
        self.assertEqual(manifest["source_contract"], repair.RAW_SOURCE_CONTRACT)
        line = manifest["internal_gap_repair"]
        self.assertEqual(line["input_kind"], "PYTDX_SOURCE_ROWS")
        self.assertEqual(line["native_files"], {})
        self.assertEqual(line["decoder_source_sha256"], rebound_raw_repair.DECODER_SHA)
        self.assertEqual(line["capture_finished_at"], record["request_finished_at"])
        self.assertEqual(line["scale_applied"], 1)
        self.assertIsNone(line["volume_unit"])
        self.assertFalse(line["conversion_applied"])
        frame = pd.read_parquet(self.fx.asset / manifest["panel_relative"])
        pd.testing.assert_frame_equal(frame.iloc[:len(self.fx.frame)][self.fx.frame.columns].reset_index(drop=True),
                                      self.fx.frame.reset_index(drop=True), check_dtype=False, check_exact=True)
        added = frame.iloc[len(self.fx.frame):].set_index("trade_date_compact")
        self.assertEqual(added.loc["20260929", "trade"], 45276)
        self.assertEqual(added.loc["20261005", "trade"], 38090)
        self.assertEqual(added.loc["20260929", "pre_close"], 10.0)
        self.assertEqual(added.loc["20261005", "pre_close"], 14.0)
        self.assertTrue(added["amount"].isna().all())
        witness = self.fx.witness(result)
        self.assertEqual(witness["source_contract"], repair.RAW_SOURCE_CONTRACT)
        self.assertEqual(witness["price_basis"], "UNVERIFIED_NATIVE")
        files = {str(path.relative_to(self.fx.asset)): path.read_bytes()
                 for path in self.fx.asset.rglob("*") if path.is_file()}
        with patch.object(rebound_raw_repair, "decode_raw_repair", side_effect=AssertionError("MUST_REUSE_RAW_REVISION")):
            retry = self.fx.publish()
        self.assertTrue(retry["reused"])
        self.assertEqual({key: value for key, value in retry.items() if key != "reused"},
                         {key: value for key, value in result.items() if key != "reused"})
        self.assertEqual(files, {str(path.relative_to(self.fx.asset)): path.read_bytes()
                                 for path in self.fx.asset.rglob("*") if path.is_file()})
        self.assertEqual(raw_source.read_bytes(), raw_before)
        self.assertEqual((self.fx.asset / self.fx.panel_relative).read_bytes(), parent_before)
        self.assertEqual((self.fx.capture_root / "capture.json").read_bytes(), capture_before)

    def test_child_parent_and_receipt_bytes_cannot_change_after_binding(self):
        result = self.fx.publish(); expected = self.fx.bound_files(result)
        for name in expected:
            with self.subTest(name=name):
                path = self.fx.asset / name; before = path.read_bytes()
                path.write_bytes(before+b" ")
                with self.assertRaisesRegex(ValueError, "REPAIR_READER_INPUT_SHA"):
                    self.fx.witness(result, expected)
                path.write_bytes(before)
        missing = dict(expected); missing.pop(result["receipt_relative"])
        with self.assertRaisesRegex(ValueError, "REPAIR_RECEIPT_NOT_BOUND"):
            self.fx.witness(result, missing)

    def test_self_consistent_rehash_cannot_hide_tiny_old_float_change(self):
        import pandas as pd
        result = self.fx.publish()
        self.fx.witness(result)
        parent_before = (self.fx.asset / self.fx.panel_relative).read_bytes()
        manifest = json.loads((self.fx.asset / result["manifest_relative"]).read_bytes())
        receipt = json.loads((self.fx.asset / result["receipt_relative"]).read_bytes())
        frame = pd.read_parquet(self.fx.asset / manifest["panel_relative"])
        original = float(frame.at[0, "close"])
        frame.at[0, "close"] = original + 1e-10
        self.assertNotEqual(frame.at[0, "close"], original)
        # This delta is below pandas' ordinary float-comparison tolerance.
        self.assertTrue(math.isclose(frame.at[0, "close"], original, rel_tol=1e-5, abs_tol=1e-8))
        staging = self.fx.root / "SYNTHETIC_tiny_changed_old_float.parquet"
        frame.to_parquet(staging, index=False)
        panel_raw = staging.read_bytes(); panel_sha = digest(panel_raw)
        revision = "panels/"+THROUGH+"-native-repair-"+panel_sha[:12]
        panel_relative = revision+"/hkconnect_vipdoc_daily_panel.parquet"
        manifest_relative = revision+"/manifest.json"
        receipt_relative = revision+"/receipt.json"
        (self.fx.asset / revision).mkdir()
        (self.fx.asset / panel_relative).write_bytes(panel_raw)
        manifest.update(panel_relative=panel_relative, panel_sha256=panel_sha)
        write_json(self.fx.asset / manifest_relative, manifest)
        manifest_sha = digest((self.fx.asset / manifest_relative).read_bytes())
        receipt.update(panel_sha256=panel_sha, manifest_sha256=manifest_sha)
        write_json(self.fx.asset / receipt_relative, receipt)
        forged = dict(result, panel_sha256=panel_sha, manifest_relative=manifest_relative,
            manifest_sha256=manifest_sha, receipt_relative=receipt_relative,
            receipt_sha256=digest((self.fx.asset / receipt_relative).read_bytes()))
        expected = self.fx.bound_files(forged)
        self.assertEqual(expected[panel_relative], panel_sha)
        self.assertEqual(expected[manifest_relative], receipt["manifest_sha256"])
        self.assertEqual(expected[receipt_relative], forged["receipt_sha256"])
        with self.assertRaisesRegex(ValueError, "REPAIR_READER_EXISTING_VALUES_CHANGED"):
            self.fx.witness(forged, expected)
        self.assertEqual((self.fx.asset / self.fx.panel_relative).read_bytes(), parent_before)

    def test_rehashed_wrong_receipt_and_cutoff_are_rejected(self):
        result = self.fx.publish()
        path = self.fx.asset / result["receipt_relative"]
        receipt = json.loads(path.read_bytes())
        receipt["request_sha256"] = "e"*64
        write_json(path, receipt)
        with self.assertRaisesRegex(ValueError, "REPAIR_READER_LINEAGE"):
            self.fx.witness(result)
        receipt["request_sha256"] = sha256_json(self.fx.request)
        write_json(path, receipt)
        cutoff = json.loads((self.fx.capture_root / "capture.json").read_bytes())["capture_started_at"]
        with self.assertRaisesRegex(ValueError, "REPAIR_READER_LINEAGE"):
            self.fx.witness(result, cutoff=cutoff)

    def test_rehashed_lineage_cannot_change_bound_row_evidence_or_calendar(self):
        result = self.fx.publish()
        manifest_path = self.fx.asset / result["manifest_relative"]
        receipt_path = self.fx.asset / result["receipt_relative"]
        original_manifest = json.loads(manifest_path.read_bytes())
        original_receipt = json.loads(receipt_path.read_bytes())
        for mutation in ("missing_evidence", "duplicate_evidence", "wrong_code", "wrong_file", "wrong_file_sha",
                         "negative_offset", "unaligned_offset", "bool_offset", "bad_record_sha", "bad_capture_sha",
                         "bad_request_sha", "outside_prior60"):
            with self.subTest(mutation=mutation):
                manifest = copy.deepcopy(original_manifest)
                line = manifest["internal_gap_repair"]
                record = line["row_evidence"][0]
                if mutation == "missing_evidence": line["row_evidence"].pop()
                elif mutation == "duplicate_evidence": line["row_evidence"].append(dict(record))
                elif mutation == "wrong_code": record["code"] = "HK.00002"
                elif mutation == "wrong_file": record["raw_file"] = "vipdoc/ds/lday/71#00002.day"
                elif mutation == "wrong_file_sha": record["raw_file_sha256"] = "b"*64
                elif mutation == "negative_offset": record["record_offset"] = -32
                elif mutation == "unaligned_offset": record["record_offset"] = 1
                elif mutation == "bool_offset": record["record_offset"] = True
                elif mutation == "bad_record_sha": record["record_sha256"] = "not-a-sha"
                elif mutation == "bad_capture_sha": line["capture_sha256"] = "not-a-sha"
                elif mutation == "bad_request_sha": line["request_sha256"] = "not-a-sha"
                elif mutation == "outside_prior60":
                    line["repaired_keys"][0]["date"] = "20250102"
                    record["date"] = "20250102"
                write_json(manifest_path, manifest)
                receipt = copy.deepcopy(original_receipt)
                receipt.update(manifest_sha256=digest(manifest_path.read_bytes()), request_sha256=line["request_sha256"])
                write_json(receipt_path, receipt)
                with self.assertRaises(ValueError):
                    self.fx.witness(result)
        write_json(manifest_path, original_manifest)
        write_json(receipt_path, original_receipt)

    def test_idempotent_retry_after_pointer_does_not_parse_or_create_revision(self):
        first = self.fx.publish()
        files = {str(p.relative_to(self.fx.asset)): p.read_bytes() for p in self.fx.asset.rglob("*") if p.is_file()}
        with patch.object(repair, "prepare_internal_gap_repair", side_effect=AssertionError("MUST_REUSE_COMMITTED")):
            second = self.fx.publish()
        self.assertTrue(second["reused"])
        self.assertEqual({k:v for k,v in second.items() if k != "reused"},
                         {k:v for k,v in first.items() if k != "reused"})
        self.assertEqual(files, {str(p.relative_to(self.fx.asset)): p.read_bytes() for p in self.fx.asset.rglob("*") if p.is_file()})

    def test_orphan_complete_revision_is_reused_after_pointer_write_failure(self):
        pointer = (self.fx.asset / "panel_latest.json").read_bytes()
        original_replace = repair.os.replace
        def fail_pointer(source, destination, **kwargs):
            if destination == "panel_latest.json":
                raise OSError("SYNTHETIC_POINTER_RENAME_FAILED")
            return original_replace(source, destination, **kwargs)
        with patch.object(repair.os, "replace", side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, "SYNTHETIC_POINTER_RENAME_FAILED"):
                self.fx.publish()
        self.assertEqual((self.fx.asset / "panel_latest.json").read_bytes(), pointer)
        revisions = list((self.fx.asset / "panels").glob("*-native-repair-*"))
        self.assertEqual(len(revisions), 1)
        before = {p.name:p.read_bytes() for p in revisions[0].iterdir() if p.is_file()}
        result = self.fx.publish()
        self.assertFalse(result["reused"])
        self.assertEqual(before, {p.name:p.read_bytes() for p in revisions[0].iterdir() if p.is_file()})
        self.fx.witness(result)

    def test_manifest_write_failure_keeps_old_pointer_and_retry_completes(self):
        pointer = (self.fx.asset / "panel_latest.json").read_bytes()
        original_write = repair._write_once
        def fail_manifest(directory, name, raw):
            if name == "manifest.json":
                raise OSError("SYNTHETIC_MANIFEST_WRITE_FAILED")
            return original_write(directory, name, raw)
        with patch.object(repair, "_write_once", side_effect=fail_manifest):
            with self.assertRaisesRegex(OSError, "SYNTHETIC_MANIFEST_WRITE_FAILED"):
                self.fx.publish()
        self.assertEqual((self.fx.asset / "panel_latest.json").read_bytes(), pointer)
        self.fx.witness(self.fx.publish())

    def test_pointer_cas_fault_preserves_competing_pointer_and_cleans_temporary(self):
        competing = canonical_bytes(dict(manifest_relative=self.fx.manifest_relative, competing_owner_revision="SYNTHETIC"))
        original_write = repair._write_once
        def switch_before_cas(directory, name, raw):
            result = original_write(directory, name, raw)
            if name.startswith(".panel-latest-"):
                (self.fx.asset / "panel_latest.json").write_bytes(competing)
            return result
        with patch.object(repair, "_write_once", side_effect=switch_before_cas):
            with self.assertRaisesRegex(ValueError, "REPAIR_POINTER_CAS_CONFLICT"):
                self.fx.publish()
        self.assertEqual((self.fx.asset / "panel_latest.json").read_bytes(), competing)
        self.assertEqual(list(self.fx.asset.glob(".panel-latest-*.tmp")), [])
        self.assertEqual(digest((self.fx.asset / self.fx.panel_relative).read_bytes()), self.fx.request["parent_panel_sha256"])

    def test_existing_owner_lock_blocks_normal_update_and_repair(self):
        with repair._writer_lock(self.fx.asset):
            with self.assertRaisesRegex(ValueError, "REPAIR_OWNER_BUSY"):
                self.fx.publish()
            with self.assertRaisesRegex(ValueError, "REPAIR_OWNER_BUSY"):
                repair.update_hk_0_2_panel_from_vipdoc(self.fx.module, self.fx.asset,
                    tdx_root=self.fx.tdx, through_date=THROUGH)
        self.fx.module.update_hk_0_2_panel_from_vipdoc.assert_not_called()


REAL_OWNER_SCRIPT = r'''
import hashlib, importlib, json, sys
from pathlib import Path
from v5_shadow import hk_preselection, rebound_panel_repair as repair
sources = hk_preselection._source_bytes()
sys.meta_path.insert(0, hk_preselection._HKLoader(sources))
owner = importlib.import_module('upstreams.v3_shared_data.shared_data.hk_0_2')
before = hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest()
repair._verify_owner(owner)
original = owner._read_vipdoc_increment
owner._read_vipdoc_increment = lambda *a, **k: ([], 0)
try:
    repair._verify_owner(owner)
except ValueError as error:
    assert str(error).startswith('REPAIR_OWNER_FUNCTION_'), str(error)
else:
    raise AssertionError('MODIFIED_OWNER_FUNCTION_ACCEPTED')
owner._read_vipdoc_increment = original
repair._verify_owner(owner)
assert hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest() == before
original_normalize = owner._normalize_code
owner._normalize_code = lambda value: 'HK.99999'
try:
    try:
        repair._verify_owner(owner)
    except ValueError as error:
        assert str(error).startswith('REPAIR_OWNER_FUNCTION_'), str(error)
    else:
        raise AssertionError('MODIFIED_NORMALIZE_HELPER_ACCEPTED')
finally:
    owner._normalize_code = original_normalize
repair._verify_owner(owner)
original_hash = owner.sha256_file
hash_source = Path(sys.modules[original_hash.__module__].__file__)
hash_before = hashlib.sha256(hash_source.read_bytes()).hexdigest()
class CallableHash:
    def __call__(self, path):
        return original_hash(path)
owner.sha256_file = CallableHash()
try:
    try:
        repair._verify_owner(owner)
    except ValueError as error:
        assert str(error) == 'REPAIR_OWNER_IMPORTED_HELPER_IDENTITY', str(error)
    else:
        raise AssertionError('IMPORTED_HASH_CALLABLE_OBJECT_ACCEPTED')
finally:
    owner.sha256_file = original_hash
repair._verify_owner(owner)
assert hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest() == before
assert hashlib.sha256(hash_source.read_bytes()).hexdigest() == hash_before
print(json.dumps({'original_sha256': before, 'owner_file_unchanged': True,
    'normalize_helper_replacement_rejected': True, 'imported_hash_callable_rejected': True,
    'imported_hash_source_unchanged': True}))
'''


# Local binding JSON: {asset_root,tdx_root,request,capture_root,capture_relative,
# capture_sha256,approved_request_sha256}. It must be created by the existing
# owner after its real raw capture/approval; this test never generates it.
REAL_ASSET_SCRIPT = r'''
import hashlib, importlib, json, shutil, sys, tempfile
from pathlib import Path
from v5_shadow import hk_preselection, rebound_panel_repair as repair
from v5_shadow.composition import no_symlinks
from v5_shadow.source_capsule import checked_path
sources = hk_preselection._source_bytes()
sys.meta_path.insert(0, hk_preselection._HKLoader(sources))
owner = importlib.import_module('upstreams.v3_shared_data.shared_data.hk_0_2')
repair._verify_owner(owner)
config = json.loads(Path(sys.argv[1]).read_bytes())
asset = no_symlinks(Path(config['asset_root']).resolve())
tdx = no_symlinks(Path(config['tdx_root']).resolve())
capture = no_symlinks(Path(config['capture_root']).resolve())
request = config['request']
original_assets = owner.load_frozen_hk_0_2_assets(asset)
names = {'panel_latest.json', 'model_latest.json'}
for pointer, payload in (('panel_latest.json','panel_relative'), ('model_latest.json','bundle_relative'),
                         ('name_latest.json','dictionary_relative')):
    if pointer == 'name_latest.json' and not (asset/pointer).exists():
        continue
    names.add(pointer)
    data = json.loads(checked_path(asset,pointer).read_bytes())
    name = data['manifest_relative']; names.add(name)
    manifest = json.loads(checked_path(asset,name).read_bytes())
    names.add(manifest[payload])
names.update((request['parent_manifest_relative'],request['parent_panel_relative']))
before = {name:hashlib.sha256(checked_path(asset,name).read_bytes()).hexdigest() for name in names}
native_before = {name:hashlib.sha256(checked_path(tdx,name).read_bytes()).hexdigest() for name in request['native_files']}
capture_before = hashlib.sha256(checked_path(capture,config['capture_relative']).read_bytes()).hexdigest()
source_before = hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest()
with tempfile.TemporaryDirectory(prefix='v5-repair-real-private-') as directory:
    private = Path(directory).resolve()
    private_asset=private/'assets'; private_native=private/'native'; private_capture=private/'capture'
    for root,names_to_copy,destination in ((asset,names,private_asset),
        (tdx,request['native_files'],private_native),
        (capture,[config['capture_relative']],private_capture)):
        for name in names_to_copy:
            target=destination/name; target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(checked_path(root,name),target)
    authority=repair.OwnerRepairAuthority(private_asset, config['approved_request_sha256'],
        private_capture, config['capture_relative'], config['capture_sha256'])
    built=repair.prepare_internal_gap_repair(owner,private_asset,tdx_root=private_native,
        request=request,authority=authority)
    result=repair.update_hk_0_2_panel_from_vipdoc(owner,private_asset,tdx_root=private_native,
        through_date=request['through_date'],repair=request,authority=authority)
    child=json.loads((private_asset/result['manifest_relative']).read_bytes())
    paths=(result['manifest_relative'],child['panel_relative'],result['receipt_relative'],
           request['parent_manifest_relative'],request['parent_panel_relative'])
    expected={name:hashlib.sha256((private_asset/name).read_bytes()).hexdigest() for name in paths}
    from datetime import datetime,timezone
    witness=repair.read_repaired_panel_witness(private_asset,result['manifest_relative'],
        expected_files=expected,cutoff=datetime.now(timezone.utc).isoformat())
    assert result['new_row_count']==len(request['keys'])
    assert witness['price_basis']=='UNVERIFIED_NATIVE'
    assert owner.load_frozen_hk_0_2_assets(private_asset).panel_manifest==child
    assert repair.update_hk_0_2_panel_from_vipdoc(owner,private_asset,tdx_root=private_native,
        through_date=request['through_date'],repair=request,authority=authority)['reused'] is True
assert before=={name:hashlib.sha256(checked_path(asset,name).read_bytes()).hexdigest() for name in names}
assert native_before=={name:hashlib.sha256(checked_path(tdx,name).read_bytes()).hexdigest() for name in request['native_files']}
assert hashlib.sha256(checked_path(capture,config['capture_relative']).read_bytes()).hexdigest()==capture_before
assert hashlib.sha256(Path(owner.__file__).read_bytes()).hexdigest()==source_before
print(json.dumps({'original_sha256':source_before,'model_sha256':owner.HK_0_2_MODEL_SHA256,
    'owner_inputs_unchanged':True,'private_repaired_rows':result['new_row_count'],
    'formal_eligibility_verified':False}))
'''


@unittest.skipUnless(os.environ.get("V5_REBOUND_REPAIR_ORIGINAL_TESTS") == "1", "Mac explicit original-owner opt-in only")
class ReboundPanelRepairOriginalMacCandidates(unittest.TestCase):
    def child(self, script, *arguments):
        bootstrap = "import sys; sys.path.insert(0,"+repr(str(BASE / "src"))+");\n"+script
        process = subprocess.run([sys.executable, "-I", "-B", "-c", bootstrap, *arguments],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=300, check=False)
        self.assertEqual(process.returncode, 0, process.stderr[-12000:])
        return json.loads(process.stdout)

    def test_real_frozen_owner_identity_and_modified_function_rejection(self):
        result = self.child(REAL_OWNER_SCRIPT)
        self.assertEqual(result["original_sha256"], ORIGINAL_SHA)
        self.assertTrue(result["owner_file_unchanged"])
        self.assertTrue(result["normalize_helper_replacement_rejected"])
        self.assertTrue(result["imported_hash_callable_rejected"])
        self.assertTrue(result["imported_hash_source_unchanged"])

    def test_real_model_assets_and_approved_raw_repair_only_in_private_copy(self):
        binding = os.environ.get("V5_REBOUND_REPAIR_REAL_INPUT")
        if not binding:
            raise RuntimeError("V5_REBOUND_REPAIR_REAL_REQUEST_REQUIRED_NO_SKIP")
        result = self.child(REAL_ASSET_SCRIPT, str(Path(binding).resolve()))
        self.assertTrue(result["owner_inputs_unchanged"])
        self.assertEqual(result["original_sha256"], ORIGINAL_SHA)
        self.assertEqual(result["model_sha256"], "3b0d5d5239342439cabf25b30012365a64d78839bc3cd4d90bad7be6ff4aaa07")
        self.assertGreater(result["private_repaired_rows"], 0)
        self.assertFalse(result["formal_eligibility_verified"])


if __name__ == "__main__":
    unittest.main()
