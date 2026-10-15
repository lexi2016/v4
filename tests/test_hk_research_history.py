import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pyarrow as pa
import pyarrow.parquet as pq
from fastapi import FastAPI
from fastapi.testclient import TestClient

from v4.hk_research_history import (
    DuplicateKeyError,
    HKResearchHistory,
    InvalidKeyError,
    OwnedHKResearchHistory,
    QueryValidationError,
    SourceIdentityError,
    normalize_date,
    normalize_symbol,
    source_descriptor_sha256,
)
from v4.manager_workbench.api import create_router


B_COLUMNS = ("code", "date", "open", "high", "low", "close", "trade", "amount")


def _b_row(code, day, open_value, *, amount=100.0, trade=10):
    return {
        "code": code,
        "date": day,
        "open": open_value,
        "high": open_value + 1,
        "low": open_value - 1,
        "close": open_value,
        "trade": trade,
        "amount": amount,
    }


def _c_row(code, day, open_value, *, amount=100.0, trade=10):
    return {
        "code_norm": code,
        "trade_date": day,
        "open": open_value,
        "high": open_value + 1,
        "low": open_value - 1,
        "close": open_value,
        "amount": amount,
        "trade": trade,
        "source_path": "/fixture/original.parquet",
    }


class HKResearchHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hk-history-test-")
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def _adapter(self, b_rows, c_rows):
        b_path = self.root / "b.parquet"
        c_path = self.root / "c.parquet"
        self._write_b(b_path, b_rows)
        self._write_c(c_path, c_rows)
        b_identity = self._identity(b_path)
        c_identity = self._identity(c_path)
        descriptor = {
            "schema_version": 1,
            "market": "HK",
            "rtol": 1e-6,
            "atol": 1e-6,
            "sources": {
                "B": {**b_identity, "row_count": len(b_rows), "columns": list(B_COLUMNS)},
                "C": {**c_identity, "row_count": len(c_rows), "columns": pq.read_schema(c_path).names},
            },
        }
        return HKResearchHistory(descriptor), descriptor

    @staticmethod
    def _write_b(path, rows):
        pq.write_table(pa.Table.from_pylist(rows, schema=pa.schema([
            pa.field("code", pa.string()), pa.field("date", pa.string()),
            pa.field("open", pa.float64()), pa.field("high", pa.float64()),
            pa.field("low", pa.float64()), pa.field("close", pa.float64()),
            pa.field("trade", pa.int64()), pa.field("amount", pa.float64()),
        ])), path)

    @staticmethod
    def _write_c(path, rows):
        c_schema = pa.schema([
            pa.field("code_norm", pa.string()), pa.field("trade_date", pa.int64()),
            pa.field("open", pa.float64()), pa.field("high", pa.float64()),
            pa.field("low", pa.float64()), pa.field("close", pa.float64()),
            pa.field("amount", pa.float64()), pa.field("trade", pa.int64()),
            pa.field("source_path", pa.string()),
        ])
        pq.write_table(pa.Table.from_pylist(rows, schema=c_schema), path)

    @staticmethod
    def _identity(path):
        raw = path.read_bytes()
        return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}

    def _owned_fixture(self, b_rows, c_rows):
        _, static_descriptor = self._adapter(b_rows, c_rows)
        owner_root = self.root / "assets" / "hk_0_2"
        panel_dir = owner_root / "panels" / "v1"
        panel_dir.mkdir(parents=True)
        panel_path = panel_dir / "panel.parquet"
        self._write_c(panel_path, c_rows)
        panel_relative = panel_path.relative_to(owner_root).as_posix()
        manifest_path = panel_dir / "manifest.json"
        self._write_panel_manifest(manifest_path, panel_path, panel_relative, len(c_rows))
        pointer = owner_root / "panel_latest.json"
        pointer.write_text(json.dumps({"manifest_relative": manifest_path.relative_to(owner_root).as_posix()}), encoding="utf-8")
        metadata_only = []
        for item_id in ("A_feature", "A_label", "B_operator_feature", "B_operator_label"):
            metadata_only.append({
                "id": item_id,
                "path": "/metadata/" + item_id + ".parquet",
                "sha256": "a" * 64,
                "size_bytes": 0,
                "read_policy": "METADATA_ONLY",
                "label_values_read": False if item_id.endswith("label") else None,
            })
        descriptor = {
            "schema_version": 1,
            "market": "HK",
            "rtol": 1e-6,
            "atol": 1e-6,
            "owner": {
                "asset_id": "hk_0_2",
                "pointer_relative": "panel_latest.json",
                "manifest_relative_field": "manifest_relative",
                "asset_schema_version": OwnedHKResearchHistory.ASSET_SCHEMA_VERSION,
            },
            "sources": {
                "B": static_descriptor["sources"]["B"],
                "C": {"owner": "hk_0_2", "dynamic": True},
            },
            "metadata_only": metadata_only,
        }
        document = {
            "source_descriptor": descriptor,
            "descriptor_sha256": source_descriptor_sha256(descriptor),
        }
        (owner_root / "research_history.json").write_text(json.dumps(document), encoding="utf-8")
        return owner_root, pointer, c_rows

    def _write_panel_manifest(self, manifest_path, panel_path, panel_relative, row_count):
        panel_sha = hashlib.sha256(panel_path.read_bytes()).hexdigest()
        manifest = {
            "asset_schema_version": OwnedHKResearchHistory.ASSET_SCHEMA_VERSION,
            "research_only": True,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "panel_rows": row_count,
            "panel_sha256": panel_sha,
            "panel_relative": panel_relative,
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        return manifest

    def test_normalizes_only_hk_key_and_rejects_bad_values(self):
        self.assertEqual(normalize_symbol("HK.00001"), 1)
        self.assertEqual(normalize_symbol("00001.HK"), 1)
        self.assertEqual(normalize_date("2026-01-02"), 20260102)
        self.assertEqual(normalize_date(20260102), 20260102)
        with self.assertRaises(InvalidKeyError):
            normalize_symbol("AAPL")
        with self.assertRaises(InvalidKeyError):
            normalize_date("2026-02-30")

    def test_reconciles_each_b_row_once_and_keeps_c_on_overlap(self):
        b_rows = [
            _b_row("HK.00001", "2026-01-02", 10.0),
            _b_row("HK.00002", "2026-01-02", 20.0, amount=12.0, trade=5),
            _b_row("HK.00003", "2026-01-03", 30.0),
        ]
        c_rows = [
            _c_row("HK.00001", 20260102, 10.0),
            _c_row("HK.00002", 20260102, 21.0, amount=0.0, trade=0),
            _c_row("HK.00004", 20260104, 40.0),
        ]
        adapter, _ = self._adapter(b_rows, c_rows)
        report = adapter.reconcile()
        self.assertEqual(report["status"], "PASS_CANARY")
        self.assertEqual(report["classification_counts"], {
            "B-only": 1,
            "raw_matching_overlap": 1,
            "raw_conflicting_overlap": 1,
            "invalid_key": 0,
        })
        self.assertEqual(report["row_counts"]["B_classified_rows"], len(b_rows))
        self.assertEqual(report["key_partition"]["C_only"], 1)
        self.assertFalse(report["raw_market_rows_exported"])
        self.assertFalse(report["scoring_allowed"])

    def test_bounded_query_tags_sources_and_preserves_raw_overlap_values(self):
        b_rows = [
            _b_row("HK.00002", "2026-01-02", 20.0, amount=12.0, trade=5),
            _b_row("HK.00003", "2026-01-03", 30.0, amount=33.0, trade=7),
        ]
        c_rows = [_c_row("HK.00002", 20260102, 21.0, amount=0.0, trade=0)]
        adapter, _ = self._adapter(b_rows, c_rows)
        conflict = adapter.query_union("00002.HK", "20260102", "20260102", limit=5)["rows"][0]
        self.assertEqual(conflict["source"], "C")
        self.assertEqual(conflict["overlap_status"], "raw_conflicting_overlap")
        self.assertEqual(conflict["raw_fields"]["open"], 21.0)
        self.assertEqual(conflict["raw_fields"]["trade"], 0)
        self.assertEqual(conflict["raw_fields"]["amount"], 0.0)
        self.assertEqual(conflict["raw_fields"]["source_path"], "/fixture/original.parquet")
        self.assertEqual(conflict["units_status"], "UNKNOWN")
        self.assertFalse(conflict["scoring_allowed"])

        b_only = adapter.query_union("HK.00003", "20260101", "20260131")["rows"][0]
        self.assertEqual(b_only["source"], "B")
        self.assertEqual(b_only["overlap_status"], "B-only")
        self.assertEqual(b_only["raw_fields"]["trade"], 7)
        with self.assertRaises(QueryValidationError):
            adapter.query_union("HK.00003", "20260101", "20260131", limit=1_001)

    def test_duplicate_and_malformed_keys_are_explicit_failures(self):
        duplicate = _b_row("HK.00001", "2026-01-02", 10.0)
        adapter, _ = self._adapter([duplicate, dict(duplicate)], [_c_row("HK.00001", 20260102, 10.0)])
        with self.assertRaises(DuplicateKeyError):
            adapter.reconcile()
        with self.assertRaises(DuplicateKeyError):
            adapter.query_union("HK.00001", "20260102", "20260102")

        unrelated_duplicate = _b_row("HK.00002", "2026-01-02", 20.0)
        adapter, _ = self._adapter(
            [_b_row("HK.00001", "2026-01-02", 10.0), unrelated_duplicate, dict(unrelated_duplicate)],
            [_c_row("HK.00001", 20260102, 10.0)],
        )
        with self.assertRaises(DuplicateKeyError):
            adapter.query_union("HK.00001", "20260102", "20260102")

        malformed = _b_row("HK.00001", "not-a-date", 10.0)
        adapter, _ = self._adapter([malformed], [])
        report = adapter.reconcile()
        self.assertEqual(report["classification_counts"]["invalid_key"], 1)
        self.assertEqual(report["status"], "FAIL_CANARY")
        with self.assertRaises(InvalidKeyError):
            adapter.query_union("HK.00001", "20260102", "20260102")

    def test_source_and_descriptor_hashes_are_enforced(self):
        adapter, descriptor = self._adapter(
            [_b_row("HK.00001", "2026-01-02", 10.0)],
            [_c_row("HK.00001", 20260102, 10.0)],
        )
        b_path = Path(descriptor["sources"]["B"]["path"])
        b_path.write_bytes(b_path.read_bytes() + b"changed")
        with self.assertRaises(SourceIdentityError):
            adapter.verify_inputs()

        descriptor_path = self.root / "descriptor.json"
        descriptor["sources"]["B"]["sha256"] = "0" * 64
        document = {
            "source_descriptor": descriptor,
            "descriptor_sha256": source_descriptor_sha256(descriptor),
        }
        descriptor_path.write_text(json.dumps(document), encoding="utf-8")
        self.assertEqual(
            json.loads(descriptor_path.read_text(encoding="utf-8"))["descriptor_sha256"],
            source_descriptor_sha256(descriptor),
        )
        document["descriptor_sha256"] = "f" * 64
        descriptor_path.write_text(json.dumps(document), encoding="utf-8")
        with self.assertRaises(SourceIdentityError):
            HKResearchHistory.from_path(descriptor_path)

    def test_dynamic_owner_tracks_c_updates_and_c_owns_overlaps(self):
        b_rows = [
            _b_row("HK.00001", "2026-01-02", 10.0),
            _b_row("HK.00002", "2026-01-03", 20.0),
        ]
        c_rows = [_c_row("HK.00001", 20260102, 10.0)]
        owner_root, pointer, _ = self._owned_fixture(b_rows, c_rows)
        history = OwnedHKResearchHistory(owner_root)
        initial = history.query_union("HK.00001", "20260102", "20260102")["rows"][0]
        self.assertEqual(initial["source"], "C")
        self.assertEqual(initial["raw_fields"]["open"], 10.0)

        next_dir = owner_root / "panels" / "v2"
        next_dir.mkdir()
        next_panel = next_dir / "panel.parquet"
        self._write_c(next_panel, [_c_row("HK.00001", 20260102, 11.0)])
        next_manifest = next_dir / "manifest.json"
        self._write_panel_manifest(
            next_manifest,
            next_panel,
            next_panel.relative_to(owner_root).as_posix(),
            1,
        )
        next_manifest_relative = next_manifest.relative_to(owner_root).as_posix()
        pointer.write_text(json.dumps({"manifest_relative": next_manifest_relative}), encoding="utf-8")

        updated = history.query_union("HK.00001", "20260102", "20260102")
        updated_row = updated["rows"][0]
        self.assertEqual(updated_row["source"], "C")
        self.assertEqual(updated_row["overlap_status"], "raw_conflicting_overlap")
        self.assertEqual(updated_row["raw_fields"]["open"], 11.0)
        self.assertEqual(updated_row["source_sha256"], hashlib.sha256(next_panel.read_bytes()).hexdigest())
        self.assertEqual(updated["owner_snapshot"]["manifest_relative"], next_manifest_relative)

        b_only = history.query_union("HK.00002", "20260103", "20260103")["rows"][0]
        self.assertEqual(b_only["source"], "B")
        self.assertEqual(b_only["overlap_status"], "B-only")
        self.assertFalse(b_only["scoring_allowed"])

    def test_dynamic_owner_rejects_pointer_traversal_and_mid_query_tamper(self):
        owner_root, pointer, _ = self._owned_fixture(
            [_b_row("HK.00001", "2026-01-02", 10.0)],
            [_c_row("HK.00001", 20260102, 10.0)],
        )
        history = OwnedHKResearchHistory(owner_root)
        pointer.write_text(json.dumps({"manifest_relative": "../outside/manifest.json"}), encoding="utf-8")
        with self.assertRaises(SourceIdentityError):
            history.query_union("HK.00001", "20260102", "20260102")

        valid_relative = "panels/v1/manifest.json"
        pointer.write_text(json.dumps({"manifest_relative": valid_relative}), encoding="utf-8")
        original_query = HKResearchHistory.query_union

        def mutate_pointer(adapter, *args, **kwargs):
            result = original_query(adapter, *args, **kwargs)
            pointer.write_text(json.dumps({"manifest_relative": valid_relative}, indent=2), encoding="utf-8")
            return result

        with patch.object(HKResearchHistory, "query_union", new=mutate_pointer):
            with self.assertRaises(SourceIdentityError):
                history.query_union("HK.00001", "20260102", "20260102")

    def test_candidate_api_route_reads_dynamic_owner_with_bounded_hk_parameters(self):
        owner_root, _, _ = self._owned_fixture(
            [
                _b_row("HK.00001", "2026-01-02", 10.0),
                _b_row("HK.00002", "2026-01-03", 20.0),
            ],
            [_c_row("HK.00001", 20260102, 11.0)],
        )
        app = FastAPI()
        service = SimpleNamespace(config=SimpleNamespace(shared_root=self.root))
        app.include_router(create_router(service))
        with TestClient(app) as client:
            response = client.get(
                "/api/v4/manager-workbench/hk-history",
                params={
                    "symbol": "HK.00001",
                    "start": "20260102",
                    "end": "20260102",
                    "offset": 0,
                    "limit": 20,
                },
            )
            invalid = client.get(
                "/api/v4/manager-workbench/hk-history",
                params={"symbol": "AAPL", "start": "20260102", "end": "20260102"},
            )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["state"], "READY")
        self.assertFalse(body["production_allowed"])
        self.assertFalse(body["buy_gate_updated"])
        self.assertFalse(body["orders_sent"])
        self.assertTrue(body["data"]["research_only"])
        rows = body["data"]["rows"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "C")
        self.assertEqual(rows[0]["raw_fields"]["open"], 11.0)
        self.assertEqual(rows[0]["raw_fields"]["source_path"], "[REDACTED_LOCAL_REFERENCE]")
        self.assertEqual(invalid.status_code, 422)


if __name__ == "__main__":
    unittest.main()
