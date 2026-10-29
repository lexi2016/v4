import asyncio
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from apps.api.v4_api.research_router import create_research_router
from infrastructure.research_lane_source import ResearchLaneSource


def _ref(path: Path) -> dict:
    return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def _rebind_product(root: Path, event: dict) -> None:
    manifest_path = Path(event["manifest"]["path"])
    manifest = json.loads(manifest_path.read_text())
    manifest["artifact"] = _ref(Path(event["artifact"]["path"]))
    manifest_path.write_text(json.dumps(manifest))
    index_path = root / "daily_products" / "a_share" / "index.json"
    index = json.loads(index_path.read_text())
    index["dates"][event["data_date"]] = _ref(manifest_path)
    index_path.write_text(json.dumps(index))


def _fixture_product_tree(root: Path) -> tuple[ResearchLaneSource, dict, dict]:
    root = root.resolve()
    data_date = "20261029"
    generation = "a" * 64
    input_sha = "b" * 64
    product_root = root / "daily_products" / "a_share"
    manifest_dir = product_root / "versions" / data_date / generation / ("c" * 64)
    checkpoint_dir = product_root / "checkpoints" / data_date / generation
    manifest_dir.mkdir(parents=True)
    checkpoint_dir.mkdir(parents=True)

    symbol = "600025.SH"
    checkpoint = {
        "schema_version": "v4.a_share.daily_product_row.v1",
        "symbol": symbol,
        "data_date": data_date,
        "qualification": {"source_generation": generation, "symbol": symbol, "target_date": data_date},
        "RESEARCH_ONLY": True,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "historical_coverage": {"evaluated_count": 1, "evaluated_dates": [data_date], "known_full_history": False,
                               "missing": ["HISTORICAL_FULL_CONDITION_BOOTSTRAP"], "historical_PIT": False},
        "statistics": {
            "status": "DESCRIPTIVE_STATS_COMPUTED",
            "asof": "2026-10-29",
            "price_distribution": {
                "near_250": {"percentile_le": 0.44, "n": 250, "start_date": "2025-10-29", "end_date": "2026-10-29"},
                "all_history": {"percentile_le": 0.51, "n": 2150, "start_date": "2017-12-15", "end_date": "2026-10-29"},
            },
            "groups": [{
                "group_id": "nav_breakout",
                "rule_sha256": "e" * 64,
                "identity_status": "BOUND",
                "source_identity": {"generation": generation, "input": input_sha,
                                    "formula": "d35c9a30d7133420272ee5a2014f67ce64c0c7cd5a5ef9c16b846c025e2a05ac",
                                    "rule_sha256": "e" * 64, "asof": "2026-10-29", "market": "SH",
                                    "basis": "QFQ_ASOF", "pit_status": "NONPIT"},
                "eligible_event_count": 1,
                "horizons": {
                    "d2": {"total": 1, "valid": 0, "positive": 0, "negative": 0, "flat": 0,
                            "not_matured": 1, "missing_price": 0, "mean_return_pct": None, "median_return_pct": None,
                            "cases": [{"event_date": "2026-10-29", "target_date": "2026-11-02",
                                       "status": "not_matured", "detail_status": "TARGET_AFTER_ASOF", "return_pct": None}]},
                },
            }],
        },
    }
    checkpoint_path = checkpoint_dir / "600025.SH.json"
    checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
    row_ref = _ref(checkpoint_path)
    config_path = root / "source_config.json"
    config_path.write_text(json.dumps({"formula": {"sha256": checkpoint["statistics"]["groups"][0]["source_identity"]["formula"]}}))

    product = {
        "schema_version": "v4.a_share.daily_product.v1", "status": "PARTIAL_WITH_ROWS",
        "data_date": data_date, "source_generation": generation,
        "source_identity": {"generation": generation, "asof": int(data_date), "input_sha256": input_sha},
        "source_config": _ref(config_path),
        "sample_only": False, "processed_count": 3, "source_universe_count": 3,
        "processed_universe": [symbol, "000878.SZ", "920005.BJ"], "unique_count": 1,
        "group_counts": {"original": 0, "nav_smallk": 0, "nav_pullback": 0, "nav_breakout": 1},
        "rows": [{"symbol": symbol, "groups": "nav_breakout", "pending_groups": "", "data_date": data_date}],
        "row_refs": {symbol: row_ref}, "RESEARCH_ONLY": True, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False,
    }
    product_path = manifest_dir / "product.json"
    product_path.write_text(json.dumps(product), encoding="utf-8")
    artifact_ref = _ref(product_path)
    manifest = {
        "schema_version": "v4.a_share.daily_product_manifest.v1", "data_date": data_date,
        "source_generation": generation, "input_sha256": input_sha, "sample_only": False,
        "processed_count": 3, "source_universe_count": 3, "status": "PARTIAL_WITH_ROWS", "artifact": artifact_ref,
        "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    manifest_path = manifest_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    manifest_ref = _ref(manifest_path)

    index_path = product_root / "index.json"
    index_path.write_text(json.dumps({"latest_date": data_date, "dates": {data_date: manifest_ref}}), encoding="utf-8")
    event = {
        "schema_version": "v4.a_share.daily_completion.v1", "event_id": "f" * 64,
        "data_date": data_date, "source_generation": generation, "input_sha256": input_sha,
        "status": "PARTIAL_WITH_ROWS", "processed_count": 3, "source_universe_count": 3,
        "manifest": manifest_ref, "artifact": artifact_ref, "RESEARCH_ONLY": True,
        "production_allowed": False, "buy_gate_updated": False, "orders_sent": False,
    }
    events_dir = product_root / "events"
    events_dir.mkdir()
    (events_dir / "latest.json").write_text(json.dumps(event), encoding="utf-8")
    return ResearchLaneSource(root / "research", a_share_daily_root=root), event, product


class CompletionSSETests(unittest.TestCase):
    def test_event_is_emitted_only_when_all_current_product_refs_match(self):
        import apps.api.v4_api.research_lane_router as lane

        with tempfile.TemporaryDirectory() as td:
            source, event, _ = _fixture_product_tree(Path(td) / "source")
            product = source.read_a_daily_product()
            self.assertTrue(lane._daily_completion_matches_current_product(event, product))
            self.assertFalse(lane._daily_completion_matches_current_product(
                {**event, "manifest": {**event["manifest"], "sha256": "0" * 64}}, product))

            class Request:
                query_params = {}
                checks = 0

                async def is_disconnected(self):
                    self.checks += 1
                    return self.checks > 1

            async def collect(endpoint):
                response = await endpoint(Request())
                return "".join([part async for part in response.body_iterator])

            router = lane.create_research_lane_router(Path(td) / "research", a_share_daily_root=Path(td) / "source")
            endpoint = next(route.endpoint for route in router.routes if route.path == "/api/v4/research/events")
            with patch.object(lane, "ResearchLaneSource", return_value=source), patch.object(lane.asyncio, "sleep", new=AsyncMock()):
                wire = asyncio.run(collect(endpoint))
        self.assertIn(f"id: {event['event_id']}\nevent: a_share_daily_completed", wire)
        self.assertIn(event["artifact"]["sha256"], wire)

    def test_mismatched_product_ref_is_not_published(self):
        import apps.api.v4_api.research_lane_router as lane

        with tempfile.TemporaryDirectory() as td:
            source, event, product = _fixture_product_tree(Path(td) / "source")
            bad_product = source.read_a_daily_product()
            bad_product = {**bad_product, "artifact": {**bad_product["artifact"], "sha256": "0" * 64}}
            self.assertFalse(lane._daily_completion_matches_current_product(event, bad_product))

    def test_exact_symbol_read_returns_hash_bound_checkpoint_statistics(self):
        with tempfile.TemporaryDirectory() as td:
            source, event, product = _fixture_product_tree(Path(td) / "source")
            latest_event = source.read_a_daily_latest_event()
            latest_product = source.read_a_daily_product()
            row_answer = source.read_a_daily_product("20261029", "600025.SH")
        self.assertEqual(latest_event, event)
        self.assertEqual(latest_product["artifact"], event["artifact"])
        self.assertEqual(row_answer["row"]["statistics"]["price_distribution"]["near_250"]["percentile_le"], 0.44)
        self.assertEqual(row_answer["row"]["historical_coverage"]["missing"], ["HISTORICAL_FULL_CONDITION_BOOTSTRAP"])
        self.assertEqual(row_answer["row"]["statistics"]["groups"][0]["horizons"]["d2"]["not_matured"], 1)

    def test_public_product_api_returns_exact_row_ref_bound_statistics(self):
        with tempfile.TemporaryDirectory() as td:
            source_root = Path(td) / "source"
            source, event, _ = _fixture_product_tree(source_root)
            app = FastAPI()
            app.include_router(create_research_router(Path(td) / "consumer", shared_data_root=source_root))
            client = TestClient(app)

            product = client.get("/api/v4/research/a-share/daily-product", params={"date": event["data_date"]})
            detail = client.get("/api/v4/research/a-share/daily-product",
                                params={"date": event["data_date"], "symbol": "600025.SH"})

        self.assertEqual(product.status_code, 200)
        self.assertEqual(product.json()["data_date"], "20261029")
        self.assertEqual(product.json()["artifact"], event["artifact"])
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["row"]["symbol"], "600025.SH")
        self.assertEqual(detail.json()["row"]["statistics"]["price_distribution"]["near_250"]["percentile_le"], 0.44)
        self.assertEqual(detail.json()["row"]["historical_coverage"]["missing"], ["HISTORICAL_FULL_CONDITION_BOOTSTRAP"])

    def test_malformed_product_index_returns_typed_cannot_confirm(self):
        with tempfile.TemporaryDirectory() as td:
            source_root = Path(td) / "source"
            _fixture_product_tree(source_root)
            (source_root / "daily_products" / "a_share" / "index.json").write_text("[]", encoding="utf-8")
            app = FastAPI()
            app.include_router(create_research_router(Path(td) / "consumer", shared_data_root=source_root))
            response = TestClient(app, raise_server_exceptions=False).get(
                "/api/v4/research/a-share/daily-product", params={"date": "20261029"}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "CANNOT_CONFIRM")
        self.assertIn("A_DAILY_PRODUCT_INDEX_INVALID", response.json()["cannot_confirm"][0])

    def test_non_mapping_source_identity_returns_typed_cannot_confirm(self):
        for identity in ([], None, "invalid"):
            with self.subTest(identity=identity), tempfile.TemporaryDirectory() as td:
                source_root = Path(td) / "source"
                _, event, _ = _fixture_product_tree(source_root)
                product_path = Path(event["artifact"]["path"])
                product = json.loads(product_path.read_text())
                product["source_identity"] = identity
                product_path.write_text(json.dumps(product))
                _rebind_product(source_root, event)
                app = FastAPI()
                app.include_router(create_research_router(Path(td) / "consumer", shared_data_root=source_root))
                response = TestClient(app, raise_server_exceptions=False).get(
                    "/api/v4/research/a-share/daily-product", params={"date": "20261029"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "CANNOT_CONFIRM")
                self.assertIn("A_DAILY_PRODUCT_SOURCE_IDENTITY_INVALID", response.json()["cannot_confirm"][0])

    def test_stale_or_unbound_checkpoint_never_exposes_statistics(self):
        def stale_checkpoint(row):
            row["qualification"]["source_generation"] = "0" * 64
            for group in row["statistics"]["groups"]:
                group["source_identity"]["generation"] = "0" * 64

        def stale_statistics(row):
            row["statistics"]["groups"][0]["source_identity"]["generation"] = "0" * 64

        def wrong_input(row):
            row["statistics"]["groups"][0]["source_identity"]["input"] = "0" * 64

        def missing_qualification(row):
            row.pop("qualification")

        def missing_statistics_identity(row):
            row["statistics"]["groups"][0].pop("source_identity")

        for mutate in (stale_checkpoint, stale_statistics, wrong_input, missing_qualification, missing_statistics_identity):
            with self.subTest(case=mutate.__name__), tempfile.TemporaryDirectory() as td:
                source_root = Path(td) / "source"
                _, event, product = _fixture_product_tree(source_root)
                product_path = Path(event["artifact"]["path"])
                checkpoint_path = Path(product["row_refs"]["600025.SH"]["path"])
                checkpoint = json.loads(checkpoint_path.read_text())
                mutate(checkpoint)
                checkpoint_path.write_text(json.dumps(checkpoint))
                product["row_refs"]["600025.SH"] = _ref(checkpoint_path)
                product_path.write_text(json.dumps(product))
                _rebind_product(source_root, event)
                app = FastAPI()
                app.include_router(create_research_router(Path(td) / "consumer", shared_data_root=source_root))
                response = TestClient(app, raise_server_exceptions=False).get(
                    "/api/v4/research/a-share/daily-product", params={"date": "20261029", "symbol": "600025.SH"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "CANNOT_CONFIRM")
                self.assertIn("A_DAILY_SYMBOL_DETAIL_SOURCE_IDENTITY_CONFLICT", response.json()["cannot_confirm"][0])
                self.assertNotIn("row", response.json())
                self.assertNotIn("statistics", response.json())

    def test_formula_identity_requires_hash_bound_source_config(self):
        cases = ("foreign_group_formula", "missing_group_formula", "invalid_group_formula",
                 "missing_config_ref", "invalid_config_ref", "config_sha_drift", "missing_config_file",
                 "config_list", "missing_config_formula", "config_formula_list",
                 "missing_config_formula_sha", "invalid_config_formula_sha")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as td:
                source_root = Path(td) / "source"
                _, event, product = _fixture_product_tree(source_root)
                checkpoint_path = Path(product["row_refs"]["600025.SH"]["path"])
                checkpoint = json.loads(checkpoint_path.read_text())
                config_path = Path(product["source_config"]["path"])
                binding = checkpoint["statistics"]["groups"][0]["source_identity"]
                if case == "foreign_group_formula":
                    binding["formula"] = "0" * 64
                elif case == "missing_group_formula":
                    binding.pop("formula")
                elif case == "invalid_group_formula":
                    binding["formula"] = []
                elif case == "missing_config_ref":
                    product.pop("source_config")
                elif case == "invalid_config_ref":
                    product["source_config"] = []
                elif case == "missing_config_file":
                    config_path.unlink()
                else:
                    malformed = {"config_sha_drift": {"formula": {"sha256": "0" * 64}},
                                 "config_list": [], "missing_config_formula": {}, "config_formula_list": {"formula": []},
                                 "missing_config_formula_sha": {"formula": {}},
                                 "invalid_config_formula_sha": {"formula": {"sha256": []}}}[case]
                    config_path.write_text(json.dumps(malformed))
                    if case != "config_sha_drift":
                        product["source_config"] = _ref(config_path)
                checkpoint_path.write_text(json.dumps(checkpoint))
                product["row_refs"]["600025.SH"] = _ref(checkpoint_path)
                Path(event["artifact"]["path"]).write_text(json.dumps(product))
                _rebind_product(source_root, event)
                app = FastAPI()
                app.include_router(create_research_router(Path(td) / "consumer", shared_data_root=source_root))
                response = TestClient(app, raise_server_exceptions=False).get(
                    "/api/v4/research/a-share/daily-product", params={"date": "20261029", "symbol": "600025.SH"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["status"], "CANNOT_CONFIRM")
                self.assertNotIn("row", response.json())
                self.assertNotIn("statistics", response.json())

    def test_missing_candidate_checkpoint_reference_returns_specific_cannot_confirm(self):
        with tempfile.TemporaryDirectory() as td:
            source_root = Path(td) / "source"
            _, event, _ = _fixture_product_tree(source_root)
            product_path = Path(event["artifact"]["path"])
            product = json.loads(product_path.read_text(encoding="utf-8"))
            product["row_refs"].pop("600025.SH")
            product_path.write_text(json.dumps(product), encoding="utf-8")
            artifact_ref = _ref(product_path)

            manifest_path = Path(event["manifest"]["path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["artifact"] = artifact_ref
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            index_path = source_root / "daily_products" / "a_share" / "index.json"
            index = json.loads(index_path.read_text(encoding="utf-8"))
            index["dates"]["20261029"] = _ref(manifest_path)
            index_path.write_text(json.dumps(index), encoding="utf-8")

            app = FastAPI()
            app.include_router(create_research_router(Path(td) / "consumer", shared_data_root=source_root))
            response = TestClient(app).get(
                "/api/v4/research/a-share/daily-product",
                params={"date": "20261029", "symbol": "600025.SH"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "CANNOT_CONFIRM")
        self.assertIn("A_DAILY_SYMBOL_DETAIL_REFERENCE_MISSING", response.json()["cannot_confirm"][0])

    def test_malformed_daily_event_does_not_break_sse_connection(self):
        import apps.api.v4_api.research_lane_router as lane

        with tempfile.TemporaryDirectory() as td:
            source_root = Path(td) / "source"
            source, _, _ = _fixture_product_tree(source_root)
            (source_root / "daily_products" / "a_share" / "events" / "latest.json").write_text("[]", encoding="utf-8")

            class Request:
                query_params = {}
                checks = 0

                async def is_disconnected(self):
                    self.checks += 1
                    return self.checks > 1

            async def collect(endpoint):
                response = await endpoint(Request())
                return "".join([part async for part in response.body_iterator])

            router = lane.create_research_lane_router(Path(td) / "research", a_share_daily_root=source_root)
            endpoint = next(route.endpoint for route in router.routes if route.path == "/api/v4/research/events")
            with patch.object(lane, "ResearchLaneSource", return_value=source), patch.object(lane.asyncio, "sleep", new=AsyncMock()):
                wire = asyncio.run(collect(endpoint))

        self.assertIn(": connected", wire)
        self.assertNotIn("a_share_daily_completed", wire)
