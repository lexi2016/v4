"""Candidate-bound read compatibility tests for the exact US close receipt form."""
from __future__ import annotations

import copy
import hashlib
import importlib
import importlib.util
import json
from pathlib import Path
from pathlib import PurePosixPath
import sys
import tempfile
import unittest


CANDIDATE_APP = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/releases/"
    "us-receipt-compat-api-20261017-r1/app"
).resolve()
CANDIDATE_MANIFEST = CANDIDATE_APP.parent / "release-manifest.json"
LIVE_DATA_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v4.local/state/data"
)
LIVE_RELEASE_MANIFEST_SHA256 = (
    "3b1a3edef0919fcda17b401f443bf71433ac98aff1c2c374814c0128c2e6d05c"
)
EXPECTED_PAYLOAD_SHA256 = (
    "bb79cb28341c83e7e4c1b96eb2b1cc411332efd9d96301f226b7845d23d1bd0f"
)
EXPECTED_RECEIPT_SHA256 = (
    "2efaa324645d0d9de3226ca13e9709b0239d2f10947ba2b879fa0d17be4e999d"
)
PAYLOAD_RELATIVE = "research/peripherals/20261017/external_finance.json"
RECEIPT_RELATIVE = "receipts/research/peripherals/20261017/external_finance.json"
MANIFEST_RELATIVE = "research/peripherals/manifest.json"
HANDOFF_ROOT = Path(
    "/Users/lexi/Desktop/学习/v4_app/docs/handoffs/"
    "us_entry_count_repair_20261017/manual_20261016"
)
EXTENSION_FIELDS = (
    "capture_origin",
    "market_snapshot_captured_at",
    "market_snapshot_source_response_sha256",
    "original_time_capture",
    "quote_capture_status",
    "rss_item_count",
    "rss_raw_item_count",
    "rss_status",
)
CAPTURE_EXTENSION_FIELDS = (
    "capture_origin",
    "original_time_capture",
    "quote_capture_status",
    "rss_item_count",
    "rss_raw_item_count",
    "rss_status",
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _temporary_directory() -> tempfile.TemporaryDirectory:
    """Place test data under the non-reparse-point handoff tree on this host."""
    return tempfile.TemporaryDirectory(prefix=".receipt-compat-test-", dir=HANDOFF_ROOT)


if Path.cwd().resolve() != CANDIDATE_APP:
    raise RuntimeError("TEST_CWD_MUST_BE_CANDIDATE_APP")
if not CANDIDATE_MANIFEST.is_file():
    raise RuntimeError("CANDIDATE_MANIFEST_MISSING")
if _sha256(CANDIDATE_MANIFEST.read_bytes()) != LIVE_RELEASE_MANIFEST_SHA256:
    raise RuntimeError("CANDIDATE_MANIFEST_SHA_MISMATCH")
_candidate_manifest = json.loads(CANDIDATE_MANIFEST.read_text(encoding="utf-8"))
_candidate_store_entry = next(
    item for item in _candidate_manifest["application_inventory"]["entries"]
    if item["path"] == "infrastructure/research_peripheral_store.py"
)
sys.path.insert(0, str(CANDIDATE_APP))
_store_spec = importlib.util.find_spec("infrastructure.research_peripheral_store")
if _store_spec is None or _store_spec.origin is None:
    raise RuntimeError("CANDIDATE_STORE_IMPORT_SPEC_MISSING")
if Path(_store_spec.origin).resolve() != CANDIDATE_APP / "infrastructure/research_peripheral_store.py":
    raise RuntimeError("CANDIDATE_STORE_IMPORT_SHADOWED:" + str(_store_spec.origin))
if _sha256(Path(_store_spec.origin).read_bytes()) != _candidate_store_entry["sha256"]:
    raise RuntimeError("CANDIDATE_STORE_MODULE_SHA_MISMATCH")
store_module = importlib.import_module("infrastructure.research_peripheral_store")
if Path(store_module.__file__).resolve() != Path(_store_spec.origin).resolve():
    raise RuntimeError("CANDIDATE_STORE_MODULE_FILE_CHANGED_AFTER_IMPORT")
if _sha256(Path(store_module.__file__).read_bytes()) != _candidate_store_entry["sha256"]:
    raise RuntimeError("CANDIDATE_STORE_MODULE_HASH_CHANGED_AFTER_IMPORT")

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _canonical_json(value: object) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False,
    )


def _extended_receipt(payload: dict) -> dict:
    digest = store_module._sha256(payload)
    result = store_module.ResearchPeripheralStore._receipt(payload, digest)
    snapshot = payload["market_snapshot"]
    late_capture = next(
        row for row in reversed(payload["us_session_captures"])
        if isinstance(row, dict) and row.get("late") is True
    )
    result.update(
        {
            "market_snapshot_captured_at": snapshot["captured_at"],
            "market_snapshot_source_response_sha256": snapshot["source_response_sha256"],
            **{field: late_capture[field] for field in CAPTURE_EXTENSION_FIELDS},
        }
    )
    return result


def _live_hashes(root: Path) -> dict[str, str | dict]:
    payload_path = root / PAYLOAD_RELATIVE
    receipt_path = root / RECEIPT_RELATIVE
    manifest_path = root / MANIFEST_RELATIVE
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    return {
        "payload_sha256": _sha256(payload_path.read_bytes()),
        "receipt_sha256": _sha256(receipt_path.read_bytes()),
        "manifest_sha256": _sha256(manifest_bytes),
        "manifest_entry": manifest.get(PAYLOAD_RELATIVE),
        "manifest": manifest,
    }


class UsReceiptReadCompatibilityCandidateTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.payload_path = LIVE_DATA_ROOT / PAYLOAD_RELATIVE
        cls.receipt_path = LIVE_DATA_ROOT / RECEIPT_RELATIVE
        cls.manifest_path = LIVE_DATA_ROOT / MANIFEST_RELATIVE
        raw = cls.payload_path.read_bytes()
        if _sha256(raw) != EXPECTED_PAYLOAD_SHA256:
            raise RuntimeError("LIVE_TARGET_PAYLOAD_SHA_CHANGED_STOP")
        receipt_raw = cls.receipt_path.read_bytes()
        if _sha256(receipt_raw) != EXPECTED_RECEIPT_SHA256:
            raise RuntimeError("LIVE_TARGET_RECEIPT_SHA_CHANGED_STOP")
        cls.payload = json.loads(raw)
        cls.live_receipt = json.loads(receipt_raw)
        cls.live_manifest = json.loads(cls.manifest_path.read_text(encoding="utf-8"))
        if cls.live_manifest.get(PAYLOAD_RELATIVE) != EXPECTED_PAYLOAD_SHA256:
            raise RuntimeError("LIVE_TARGET_MANIFEST_ENTRY_CHANGED_STOP")
        if _canonical_json(_extended_receipt(cls.payload)) != _canonical_json(cls.live_receipt):
            raise RuntimeError("LIVE_TARGET_RECEIPT_NOT_THE_KNOWN_EXTENDED_FORM")

    def _store(self, root: Path, payload: dict | None = None, *, extended: bool = False):
        source = copy.deepcopy(self.payload if payload is None else payload)
        store = store_module.ResearchPeripheralStore(root)
        store.publish(source)
        if extended:
            store._write(RECEIPT_RELATIVE, _extended_receipt(source))
        return store

    def _snapshot(self, root: Path, source: str = "external_finance") -> dict[str, object]:
        date = "20261017"
        payload_relative = store_module.ResearchPeripheralStore._relative(date, source)
        receipt_relative = store_module.ResearchPeripheralStore._receipt_relative(date, source)
        manifest_path = root / MANIFEST_RELATIVE
        manifest_bytes = manifest_path.read_bytes()
        return {
            "payload": _sha256((root / payload_relative).read_bytes()),
            "receipt": _sha256((root / receipt_relative).read_bytes()),
            "manifest": _sha256(manifest_bytes),
            "manifest_bytes": manifest_bytes,
        }

    def _assert_read_unchanged(self, store, root: Path, action, *, source: str = "external_finance"):
        before = self._snapshot(root, source)
        value = action()
        after = self._snapshot(root, source)
        self.assertEqual(before["payload"], after["payload"])
        self.assertEqual(before["receipt"], after["receipt"])
        self.assertEqual(before["manifest"], after["manifest"])
        return value

    def _assert_live_read_unchanged(self, action):
        before = _live_hashes(LIVE_DATA_ROOT)
        value = action()
        after = _live_hashes(LIVE_DATA_ROOT)
        self.assertEqual(before["payload_sha256"], after["payload_sha256"])
        self.assertEqual(before["receipt_sha256"], after["receipt_sha256"])
        self.assertEqual(before["manifest_entry"], after["manifest_entry"])
        if before["manifest_sha256"] != after["manifest_sha256"]:
            before_manifest = before["manifest"]
            after_manifest = after["manifest"]
            self.assertIsInstance(before_manifest, dict)
            self.assertIsInstance(after_manifest, dict)
            self.assertFalse(set(before_manifest) - set(after_manifest), "shared manifest entry removed during read")
            changed = {
                key for key in set(before_manifest) | set(after_manifest)
                if before_manifest.get(key) != after_manifest.get(key)
            }
            self.assertNotIn(PAYLOAD_RELATIVE, changed)
            for key in changed:
                relative = PurePosixPath(key)
                self.assertFalse(relative.is_absolute())
                self.assertNotIn("..", relative.parts)
                self.assertTrue(key.startswith("research/peripherals/"))
                self.assertIsInstance(after_manifest.get(key), str)
                path = LIVE_DATA_ROOT.joinpath(*relative.parts)
                self.assertTrue(path.is_file())
                payload = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(store_module._sha256(payload), after_manifest[key])
        return value

    def _assert_rejected_without_store_mutation(self, store, root: Path, *, source: str = "external_finance"):
        before = self._snapshot(root, source)
        with self.assertRaises(ValueError):
            store.read_exact("20261017", source)
        after = self._snapshot(root, source)
        self.assertEqual(before, after)

    def test_exact_legacy_receipt_remains_readable_without_mutation(self) -> None:
        with _temporary_directory() as temporary:
            root = Path(temporary)
            store = self._store(root, extended=False)
            payload = self._assert_read_unchanged(
                store, root, lambda: store.read_exact("20261017", "external_finance")
            )
            self.assertEqual(payload, self.payload)

    def test_exact_eight_field_extension_is_readable_without_mutation(self) -> None:
        with _temporary_directory() as temporary:
            root = Path(temporary)
            store = self._store(root, extended=True)
            payload = self._assert_read_unchanged(
                store, root, lambda: store.read_exact("20261017", "external_finance")
            )
            self.assertEqual(payload, self.payload)

    def test_each_extension_field_must_be_present_and_exact(self) -> None:
        for field in EXTENSION_FIELDS:
            with self.subTest(field=field, mutation="altered"):
                with _temporary_directory() as temporary:
                    root = Path(temporary)
                    store = self._store(root, extended=True)
                    receipt = json.loads((root / RECEIPT_RELATIVE).read_text(encoding="utf-8"))
                    value = receipt[field]
                    if type(value) is bool:
                        receipt[field] = not value
                    elif type(value) is int:
                        receipt[field] = value + 1
                    else:
                        receipt[field] = str(value) + "-tampered"
                    store._write(RECEIPT_RELATIVE, receipt)
                    self._assert_rejected_without_store_mutation(store, root)
            with self.subTest(field=field, mutation="missing"):
                with _temporary_directory() as temporary:
                    root = Path(temporary)
                    store = self._store(root, extended=True)
                    receipt = json.loads((root / RECEIPT_RELATIVE).read_text(encoding="utf-8"))
                    receipt.pop(field)
                    store._write(RECEIPT_RELATIVE, receipt)
                    self._assert_rejected_without_store_mutation(store, root)

    def test_unknown_shared_field_and_boolean_integer_alias_are_rejected(self) -> None:
        mutations = (
            ("unknown", lambda receipt: receipt.__setitem__("unrecognized_extra", "x")),
            ("shared", lambda receipt: receipt.__setitem__("trade_date", "20261016")),
            ("bool_int_alias", lambda receipt: receipt.__setitem__("production_allowed", 0)),
        )
        for name, mutate in mutations:
            with self.subTest(name=name), _temporary_directory() as temporary:
                root = Path(temporary)
                store = self._store(root, extended=True)
                receipt = json.loads((root / RECEIPT_RELATIVE).read_text(encoding="utf-8"))
                mutate(receipt)
                store._write(RECEIPT_RELATIVE, receipt)
                self._assert_rejected_without_store_mutation(store, root)

    def test_manifest_payload_sha_and_requested_identity_mismatches_are_rejected(self) -> None:
        with _temporary_directory() as temporary:
            root = Path(temporary)
            store = self._store(root)
            altered = copy.deepcopy(self.payload)
            altered["status"] = "PARTIAL"
            store._write(PAYLOAD_RELATIVE, altered)
            self._assert_rejected_without_store_mutation(store, root)

        with _temporary_directory() as temporary:
            root = Path(temporary)
            store = self._store(root)
            manifest = json.loads((root / MANIFEST_RELATIVE).read_text(encoding="utf-8"))
            manifest[PAYLOAD_RELATIVE] = "0" * 64
            store._write(MANIFEST_RELATIVE, manifest)
            self._assert_rejected_without_store_mutation(store, root)

        for field, value in (("trade_date", "20261016"), ("source", "ai_news")):
            with self.subTest(identity_field=field), _temporary_directory() as temporary:
                root = Path(temporary)
                store = self._store(root)
                altered = copy.deepcopy(self.payload)
                altered[field] = value
                digest = store_module._sha256(altered)
                store._write(PAYLOAD_RELATIVE, altered)
                manifest = json.loads((root / MANIFEST_RELATIVE).read_text(encoding="utf-8"))
                manifest[PAYLOAD_RELATIVE] = digest
                store._write(MANIFEST_RELATIVE, manifest)
                store._write(
                    RECEIPT_RELATIVE,
                    store_module.ResearchPeripheralStore._receipt(altered, digest),
                )
                self._assert_rejected_without_store_mutation(store, root)

    def test_ai_news_and_hk_industry_do_not_accept_the_us_extension(self) -> None:
        ai_news = {
            "schema_version": "v3_5.research_peripheral.v1",
            "trade_date": "20261017",
            "source": "ai_news",
            "status": "READY",
            "source_url": "https://example.invalid/fixture",
            "fetched_at": "2026-10-17T15:35:31Z",
            "raw_item_count": 1,
            "item_count": 1,
            "overview": [],
            "details": [],
            "items": [{"title": "fixture"}],
            "cannot_confirm": [],
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        with _temporary_directory() as temporary:
            root = Path(temporary)
            store = store_module.ResearchPeripheralStore(root)
            store.publish(ai_news)
            receipt_path = root / store_module.ResearchPeripheralStore._receipt_relative(
                "20261017", "ai_news"
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt.update({field: _extended_receipt(self.payload)[field] for field in EXTENSION_FIELDS})
            store._write(receipt_path.relative_to(root).as_posix(), receipt)
            with self.assertRaises(ValueError):
                store.read_exact("20261017", "ai_news")

        hk_industry = {
            "schema_version": "v3_5.research_peripheral.v1",
            "trade_date": "20261017",
            "source": store_module.HK_INDUSTRY_SOURCE,
            "status": "CANNOT_CONFIRM",
            "source_url": "https://example.invalid/fixture",
            "fetched_at": "2026-10-17T15:35:31Z",
            "raw_item_count": 0,
            "item_count": 0,
            "overview": [],
            "details": [],
            "items": [],
            "cannot_confirm": ["FIXTURE_FAILURE"],
            "write_policy": "read_only",
            "recommendation_status": "RESEARCH_ONLY",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "source_id": "EASTMONEY_F10_RPT_HKF10_INFO_ORGPROFILE",
            "provider": "EASTMONEY_F10",
            "captured_at": "2026-10-17T15:35:31Z",
            "source_asof": None,
            "source_asof_status": "UNKNOWN",
            "source_date_semantics": "CAPTURED_ON_OR_BEFORE_TARGET_DATE_SOURCE_ASOF_UNKNOWN",
            "market": "HK_CONNECT",
            "scope_type": "HK_CONNECT_FULL_MARKET",
            "scope_codes": ["HK.00001"],
            "scope_count": 1,
            "scope_codes_sha256": store_module._sha256(["HK.00001"]),
            "membership_codes_sha256": store_module._sha256(
                {"market": "HK_CONNECT", "codes": ["HK.00001"]}
            ),
            "membership_artifact_sha256": "1" * 64,
            "membership_owner": "fixture",
            "membership_relative": "fixture/membership.json",
            "membership_available_at": "2026-10-17T15:35:31Z",
            "membership_effective_from": "20261017",
            "membership_effective_through": "20261017",
            "membership_source_root": "/fixture/source",
            "membership_source_refs": [
                {"source_local_path": "/fixture/membership.json", "relative": "fixture/membership.json", "sha256": "2" * 64}
            ],
            "requested_codes": ["HK.00001"],
            "raw_responses": [],
            "failures": [
                {
                    "symbol": "HK.00001",
                    "error_code": "FIXTURE_FAILURE",
                    "request_url": "https://datacenter.eastmoney.com/securities/api/data/v1/get?fixture=1",
                    "http_status": 500,
                    "captured_at": "2026-10-17T15:35:31Z",
                }
            ],
            "batch_response_sha256": "3" * 64,
        }
        with _temporary_directory() as temporary:
            root = Path(temporary)
            store = store_module.ResearchPeripheralStore(root)
            store.publish(hk_industry)
            receipt_path = root / store_module.ResearchPeripheralStore._receipt_relative(
                "20261017", store_module.HK_INDUSTRY_SOURCE
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt.update({field: _extended_receipt(self.payload)[field] for field in EXTENSION_FIELDS})
            store._write(receipt_path.relative_to(root).as_posix(), receipt)
            with self.assertRaises(ValueError):
                store.read_exact("20261017", store_module.HK_INDUSTRY_SOURCE)

    def test_testclient_projects_exact_snapshot_and_preserves_safety_and_lineage(self) -> None:
        with _temporary_directory() as temporary:
            root = Path(temporary)
            store = self._store(root, extended=True)
            before = self._snapshot(root)
            route_spec = importlib.util.find_spec("apps.api.v35_api.research_lane_router")
            if route_spec is None or route_spec.origin is None:
                self.fail("CANDIDATE_ROUTE_IMPORT_SPEC_MISSING")
            route_path = CANDIDATE_APP / "apps/api/v35_api/research_lane_router.py"
            self.assertEqual(Path(route_spec.origin).resolve(), route_path)
            route_entry = next(
                item for item in _candidate_manifest["application_inventory"]["entries"]
                if item["path"] == "apps/api/v35_api/research_lane_router.py"
            )
            self.assertEqual(_sha256(route_path.read_bytes()), route_entry["sha256"])
            from apps.api.v35_api.research_lane_router import create_research_lane_router

            app = FastAPI()
            app.include_router(create_research_lane_router(root, us_market_data_root=root))
            with TestClient(app) as client:
                response = client.get("/api/v3/research/us-market?research_date=20261017")
            self.assertEqual(response.status_code, 200)
            projection = response.json()
            after = self._snapshot(root)
            self.assertEqual(before, after)
            self.assertEqual(projection["research_date"], "20261017")
            self.assertEqual(projection["target_trade_date"], "20261017")
            self.assertEqual(projection["artifact_trade_date"], "20261017")
            self.assertEqual(projection["source_date"], "20261016")
            self.assertEqual(projection["us_session_date"], "20261016")
            self.assertEqual(projection["capture_session_date"], "20261016")
            self.assertEqual(projection["capture_id"], "0db4106c8805f7f82906ab34")
            self.assertEqual(projection["capture_phase"], "POST_CLOSE")
            self.assertTrue(projection["late"])
            self.assertEqual(projection["capture_mode"], "CONTROLLED_LATE_POST_CLOSE")
            self.assertEqual(projection["reason"], "NATURAL_SLOT_MISSED_CONTROLLED_RECOVERY")
            self.assertEqual(projection["capture_origin"], "ORIGINAL_TIME_CAPTURE")
            self.assertTrue(projection["original_time_capture"])
            self.assertEqual(projection["captured_at"], "2026-10-17T15:35:31Z")
            self.assertEqual(projection["status"], "PARTIAL")
            self.assertEqual(projection["available_board_count"], 12)
            self.assertEqual(projection["requested_board_count"], 24)
            self.assertEqual(projection["futu_board_snapshot"]["status"], "PARTIAL")
            self.assertEqual(projection["legacy_proxy_status"], "READY")
            self.assertEqual(projection["proxy_available_symbol_count"], 48)
            self.assertEqual(len(projection["proxy_quotes"]), 48)
            self.assertEqual(projection["recommendation_status"], "RESEARCH_ONLY")
            self.assertIs(projection["production_allowed"], False)
            self.assertIs(projection["buy_gate_updated"], False)
            self.assertIs(projection["orders_sent"], False)
            self.assertEqual(projection["artifact"]["sha256"], EXPECTED_PAYLOAD_SHA256)
            self.assertNotEqual(
                projection["source_response_sha256"],
                projection["proxy_source_response_sha256"],
            )

    def test_live_target_read_is_read_only_and_keeps_concurrent_manifest_changes_scoped(self) -> None:
        before = _live_hashes(LIVE_DATA_ROOT)
        self.assertEqual(before["payload_sha256"], EXPECTED_PAYLOAD_SHA256)
        self.assertEqual(before["receipt_sha256"], EXPECTED_RECEIPT_SHA256)
        store = store_module.ResearchPeripheralStore(LIVE_DATA_ROOT)
        payload = self._assert_live_read_unchanged(
            lambda: store.read_exact("20261017", "external_finance")
        )
        self.assertEqual(payload, self.payload)
        self.assertEqual(payload["trade_date"], "20261017")
        self.assertEqual(payload["us_session_captures"][-1]["us_session_date"], "20261016")


if __name__ == "__main__":
    unittest.main(verbosity=2)
