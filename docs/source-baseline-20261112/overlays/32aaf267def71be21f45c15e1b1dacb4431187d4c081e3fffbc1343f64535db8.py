"""Contracts for the fixed A/H shared stage acquisition bundle."""
from __future__ import annotations

import json
import csv
import shutil
import tempfile
import unittest
from pathlib import Path

from shared_data.consumer import read_verified_latest
from shared_data.hashing import canonical_bytes, sha256_file, sha256_json
from shared_data.store import ConflictError
from shared_data.bundles import publish_bundle_receipt
from scripts.acquire_stage_bundle import main, run_stage_bundle
from scripts.live_acquisition.orchestrator import persist_stage_result
from scripts.live_acquisition.contracts import StageSourceResult, market_role
from scripts.live_acquisition.universe import (
    HK_CONNECT_MIN_FULL_COUNT,
    UNIVERSE_SCHEMA_VERSION_V1,
    UNIVERSE_SCHEMA_VERSION_V2,
    normalize_symbol,
    resolve_stage_universe,
    universe_manifest_legacy_path,
    universe_manifest_path,
)

TRADE_DATE = "20260806"
STAGE_ID = "STAGE_0930_0935"


def _row(code: str, *, price: float = 10.0) -> dict:
    return {
        "batch_index": 1,
        "code": code,
        "name": code,
        "update_time": "2026-08-06 09:35:00",
        "last_price": price,
        "open_price": price,
        "high_price": price,
        "low_price": price,
        "prev_close_price": price,
        "turnover": 1000.0,
        "volume": 100.0,
        "bid_price": "",
        "ask_price": "",
        "bid_vol": "",
        "ask_vol": "",
        "window_start": "2026-08-06 09:31:00",
        "window_end": "2026-08-06 09:35:00",
        "bar_count": 5,
        "temporal_cutoff_safe": True,
    }


def _write_universe(root: Path, market: str, codes: list[str], *, scope: str) -> Path:
    path = universe_manifest_path(root, TRADE_DATE, market)
    is_a_v2 = market == "A_SHARE" and path.name == "A_SHARE_STAGE_CANDIDATES_V2.json"
    payload = {
        "schema_version": UNIVERSE_SCHEMA_VERSION_V2 if is_a_v2 else UNIVERSE_SCHEMA_VERSION_V1,
        "trade_date": TRADE_DATE,
        "market": market,
        "scope": scope,
        "codes": codes,
        "code_count": len(codes),
        "codes_sha256": sha256_json(codes),
        "source_role": (
            "A_SHARE_STAGE_ACQUISITION_UNIVERSE_V2"
            if is_a_v2
            else "SELECTOR_READY_CURRENT"
        ),
        "source_sha256": "a" * 64,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    if is_a_v2:
        payload.update(
            artifact_role="A_SHARE_STAGE_CANDIDATES_V2",
            artifact_version="V2",
            source_projection_sha256="b" * 64,
            source_merge_role="STAGE_ACQUISITION_INPUT",
            stage_selection_eligible=True,
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(payload))
    return path


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="v3sd_bundle_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.store = self.tmp / "store"
        self.python = self.tmp / "python.exe"
        self.python.write_text("", encoding="utf-8")
        self.a_codes = ["SH.600036", "SZ.000429"]
        self.hk_codes = [f"HK.{value:05d}" for value in range(1, HK_CONNECT_MIN_FULL_COUNT + 1)]
        _write_universe(self.store, "A_SHARE", self.a_codes, scope="STAGE_CANDIDATES")
        _write_universe(self.store, "HK_CONNECT", self.hk_codes, scope="FULL_MARKET")


class TestUniverseContract(_Base):
    def test_role_and_symbol_normalization(self) -> None:
        self.assertEqual(market_role("A_SHARE", STAGE_ID), "A_SHARE_1MIN_STAGE_0930_0935")
        self.assertEqual(market_role("HK_CONNECT", STAGE_ID), "HK_CONNECT_1MIN_STAGE_0930_0935")
        self.assertEqual(normalize_symbol("600036.SH", "A_SHARE"), "SH.600036")
        self.assertEqual(normalize_symbol("000429.SZ", "A_SHARE"), "SZ.000429")
        self.assertEqual(normalize_symbol("A.920275", "A_SHARE"), "BJ.920275")
        self.assertEqual(normalize_symbol("00656.HK_CONNECT", "HK_CONNECT"), "HK.00656")
        self.assertEqual(normalize_symbol("HK.00656", "HK_CONNECT"), "HK.00656")

    def test_fixed_paths_and_verified_full_hk_market(self) -> None:
        a = resolve_stage_universe(self.store, TRADE_DATE, "A_SHARE")
        hk = resolve_stage_universe(self.store, TRADE_DATE, "HK_CONNECT")
        self.assertEqual(a.codes, tuple(self.a_codes))
        self.assertEqual(hk.codes, tuple(self.hk_codes))
        self.assertEqual(
            a.path,
            self.store / "universes" / TRADE_DATE / "A_SHARE_STAGE_CANDIDATES_V2.json",
        )
        self.assertEqual(hk.path, self.store / "universes" / TRADE_DATE / "HK_CONNECT_FULL_MARKET.json")

    def test_legacy_v1_is_readable_only_when_v2_is_absent(self) -> None:
        v2 = universe_manifest_path(self.store, TRADE_DATE, "A_SHARE")
        v2.unlink()
        legacy = universe_manifest_legacy_path(self.store, TRADE_DATE)
        legacy_payload = {
            "schema_version": UNIVERSE_SCHEMA_VERSION_V1,
            "trade_date": TRADE_DATE,
            "market": "A_SHARE",
            "scope": "STAGE_CANDIDATES",
            "codes": ["SH.600036"],
            "code_count": 1,
            "codes_sha256": sha256_json(["SH.600036"]),
            "source_role": "LEGACY_V1",
            "source_sha256": "d" * 64,
            "source_date": TRADE_DATE,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(canonical_bytes(legacy_payload))
        resolved = resolve_stage_universe(self.store, TRADE_DATE, "A_SHARE")
        self.assertEqual(resolved.path, legacy)
        self.assertEqual(resolved.codes, ("SH.600036",))

    def test_top100_or_tampered_manifest_fails_closed(self) -> None:
        _write_universe(
            self.store,
            "HK_CONNECT",
            [f"HK.{value:05d}" for value in range(1, 101)],
            scope="FULL_MARKET",
        )
        with self.assertRaises(ValueError):
            resolve_stage_universe(self.store, TRADE_DATE, "HK_CONNECT")
        path = _write_universe(self.store, "A_SHARE", self.a_codes, scope="STAGE_CANDIDATES")
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["codes_sha256"] = "0" * 64
        path.write_bytes(canonical_bytes(payload))
        with self.assertRaises(ValueError):
            resolve_stage_universe(self.store, TRADE_DATE, "A_SHARE")


class TestBundleAcquisition(_Base):
    def test_historical_backfill_supersedes_ready_and_preserves_old_bytes(self) -> None:
        first = run_stage_bundle(
            self.store,
            TRADE_DATE,
            STAGE_ID,
            self.python,
            futu_collector=self._collector([], source_id="futu"),
            pytdx_collector=self._collector([], source_id="pytdx"),
        )
        self.assertTrue(first["ok"])
        old_component = {
            market: read_verified_latest(
                self.store, TRADE_DATE, market_role(market, STAGE_ID)
            )
            for market in ("A_SHARE", "HK_CONNECT")
        }
        old_component_bytes = {
            market: {
                "artifact": run.artifact_path.read_bytes(),
                "manifest": run.manifest_path.read_bytes(),
                "receipt": run.receipt_path.read_bytes(),
            }
            for market, run in old_component.items()
        }
        old_bundle_latest = json.loads(
            (self.store / "bundle_latest.json").read_text(encoding="utf-8")
        )
        old_bundle_entry = old_bundle_latest["entries"][f"{TRADE_DATE}/{STAGE_ID}"]
        old_bundle_receipt_path = self.store / old_bundle_entry["receipt_relative"]
        old_bundle_receipt_bytes = old_bundle_receipt_path.read_bytes()

        # Simulate the authoritative recovery universe growing beyond the old
        # READY run; historical_backfill must bypass the normal reuse guard.
        self.a_codes = ["SH.600036", "SZ.000429", "SH.600881"]
        _write_universe(self.store, "A_SHARE", self.a_codes, scope="STAGE_CANDIDATES")

        def recovered(source_id: str, display_name: str, fidelity: str):
            def collect(python_path, trade_date, stage_id, codes, *, market,
                        process_runner, timeout_seconds=45):
                return StageSourceResult(
                    source_id=source_id,
                    display_name=display_name,
                    status="READ_OK",
                    fidelity=fidelity,
                    rows=[_row(code, price=20.0 + index) for index, code in enumerate(codes)],
                    requested_code_count=len(codes),
                    completed_code_count=len(codes),
                )
            return collect

        recovered_run = run_stage_bundle(
            self.store,
            TRADE_DATE,
            STAGE_ID,
            self.python,
            historical_backfill=True,
            futu_collector=recovered(
                "futu", "Futu OpenD", "FUTU_A_SHARE_1MIN_CUTOFF_SAFE"
            ),
            pytdx_hq_collector=recovered(
                "pytdx_hq", "TDXPy HQ", "TDXPY_HQ_A_SHARE_1MIN_CUTOFF_SAFE"
            ),
            pytdx_collector=recovered(
                "pytdx", "TDXPy ExHQ", "TDXPY_EXHQ_HK_1MIN_CUTOFF_SAFE"
            ),
        )
        self.assertTrue(recovered_run["ok"])
        self.assertNotEqual(recovered_run["bundle_id"], first["bundle_id"])

        new_bundle_latest = json.loads(
            (self.store / "bundle_latest.json").read_text(encoding="utf-8")
        )
        new_bundle_entry = new_bundle_latest["entries"][f"{TRADE_DATE}/{STAGE_ID}"]
        self.assertNotEqual(new_bundle_entry["bundle_id"], old_bundle_entry["bundle_id"])
        self.assertTrue(new_bundle_entry.get("supersession_relative"))
        supersession_path = self.store / new_bundle_entry["supersession_relative"]
        self.assertTrue(supersession_path.is_file())

        for market, run in old_component.items():
            self.assertEqual(run.artifact_path.read_bytes(), old_component_bytes[market]["artifact"])
            self.assertEqual(run.manifest_path.read_bytes(), old_component_bytes[market]["manifest"])
            self.assertEqual(run.receipt_path.read_bytes(), old_component_bytes[market]["receipt"])
        self.assertEqual(old_bundle_receipt_path.read_bytes(), old_bundle_receipt_bytes)

        latest_a = read_verified_latest(
            self.store, TRADE_DATE, market_role("A_SHARE", STAGE_ID)
        )
        self.assertEqual(latest_a.manifest["row_count"], len(self.a_codes))

        repeated = run_stage_bundle(
            self.store,
            TRADE_DATE,
            STAGE_ID,
            self.python,
            historical_backfill=True,
            futu_collector=recovered(
                "futu", "Futu OpenD", "FUTU_A_SHARE_1MIN_CUTOFF_SAFE"
            ),
            pytdx_hq_collector=recovered(
                "pytdx_hq", "TDXPy HQ", "TDXPY_HQ_A_SHARE_1MIN_CUTOFF_SAFE"
            ),
            pytdx_collector=recovered(
                "pytdx", "TDXPy ExHQ", "TDXPY_EXHQ_HK_1MIN_CUTOFF_SAFE"
            ),
        )
        self.assertEqual(repeated["bundle_id"], recovered_run["bundle_id"])
        self.assertTrue(repeated["already_exists"])

        with self.assertRaises(ConflictError):
            persist_stage_result(
                self.store,
                TRADE_DATE,
                STAGE_ID,
                StageSourceResult(
                    source_id="manual",
                    display_name="manual",
                    status="READ_OK",
                    fidelity="TEST",
                    rows=[_row(self.a_codes[0], price=77.0)],
                ),
                market="A_SHARE",
                historical_backfill=True,
                expected_previous={"run_id": "wrong-expected-run"},
            )

    def test_historical_backfill_routes_all_a_to_pytdx_hq_and_hk_to_exhq(self) -> None:
        calls: list[dict] = []

        def futu(python_path, trade_date, stage_id, codes, *, market,
                 process_runner, timeout_seconds=45):
            calls.append({"source": "futu", "market": market, "codes": list(codes)})
            return StageSourceResult(
                source_id="futu", display_name="Futu OpenD", status="READ_OK",
                fidelity="FUTU_A_SHARE_1MIN_CUTOFF_SAFE",
                rows=[_row(code) for code in codes],
            )

        def pytdx_hq(python_path, trade_date, stage_id, codes, *, market,
                     process_runner, timeout_seconds=45):
            calls.append({"source": "pytdx_hq", "market": market, "codes": list(codes)})
            return StageSourceResult(
                source_id="pytdx_hq", display_name="TDXPy HQ", status="READ_OK",
                fidelity="TDXPY_HQ_A_SHARE_1MIN_CUTOFF_SAFE",
                rows=[_row(code) for code in codes],
            )

        def pytdx_exhq(python_path, trade_date, stage_id, codes, *, market,
                       process_runner, timeout_seconds=45):
            calls.append({"source": "pytdx_exhq", "market": market, "codes": list(codes)})
            return StageSourceResult(
                source_id="pytdx", display_name="TDXPy ExHQ", status="READ_OK",
                fidelity="TDXPY_EXHQ_HK_1MIN_CUTOFF_SAFE",
                rows=[_row(code) for code in codes],
            )

        outcome = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            historical_backfill=True,
            futu_collector=futu,
            pytdx_hq_collector=pytdx_hq,
            pytdx_collector=pytdx_exhq,
        )
        self.assertTrue(outcome["ok"])
        self.assertEqual(calls[0], {
            "source": "pytdx_hq",
            "market": "A_SHARE",
            "codes": self.a_codes,
        })
        self.assertEqual(calls[1]["source"], "pytdx_exhq")
        self.assertEqual(calls[1]["market"], "HK_CONNECT")
        self.assertEqual(calls[1]["codes"], self.hk_codes)

    def test_a_stage_splits_bj_to_pytdx_hq_and_preserves_universe_order(self) -> None:
        self.a_codes = ["SH.600036", "BJ.920275", "SZ.000429"]
        _write_universe(self.store, "A_SHARE", self.a_codes, scope="STAGE_CANDIDATES")
        calls: list[dict] = []

        def futu(python_path, trade_date, stage_id, codes, *, market,
                 process_runner, timeout_seconds=45):
            calls.append({"source": "futu", "market": market, "codes": list(codes)})
            rows = [_row(code, price=10.0 + index) for index, code in enumerate(codes)]
            return StageSourceResult(
                source_id="futu", display_name="Futu OpenD", status="READ_OK",
                fidelity="FUTU_A_SHARE_1MIN_CUTOFF_SAFE", rows=rows,
                requested_code_count=len(codes), completed_code_count=len(codes),
            )

        def pytdx_hq(python_path, trade_date, stage_id, codes, *, market,
                     process_runner, timeout_seconds=45):
            calls.append({"source": "pytdx_hq", "market": market, "codes": list(codes)})
            rows = [_row(code, price=20.0) for code in codes]
            return StageSourceResult(
                source_id="pytdx_hq", display_name="TDXPy HQ", status="READ_OK",
                fidelity="TDXPY_HQ_A_SHARE_1MIN_CUTOFF_SAFE", rows=rows,
                requested_code_count=len(codes), completed_code_count=len(codes),
            )

        outcome = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=futu,
            pytdx_hq_collector=pytdx_hq,
            pytdx_collector=self._collector([], source_id="pytdx"),
        )
        self.assertTrue(outcome["ok"])
        self.assertEqual(calls[:2], [
            {"source": "futu", "market": "A_SHARE", "codes": ["SH.600036", "SZ.000429"]},
            {"source": "pytdx_hq", "market": "A_SHARE", "codes": ["BJ.920275"]},
        ])
        run = read_verified_latest(self.store, TRADE_DATE, market_role("A_SHARE", STAGE_ID))
        with run.artifact_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([row["code"] for row in rows], self.a_codes)

    def test_large_live_a_stage_routes_all_codes_to_pytdx_hq(self) -> None:
        self.a_codes = [f"SH.{600000 + index:06d}" for index in range(101)]
        _write_universe(self.store, "A_SHARE", self.a_codes, scope="STAGE_CANDIDATES")
        calls: list[dict] = []

        def futu(*args, **kwargs):
            self.fail("large A-share universe must not hit Futu subscription quota")

        def pytdx_hq(python_path, trade_date, stage_id, codes, *, market,
                     process_runner, timeout_seconds=45):
            calls.append({"source": "pytdx_hq", "market": market, "codes": list(codes)})
            return StageSourceResult(
                source_id="pytdx_hq", display_name="TDXPy HQ", status="READ_OK",
                fidelity="TDXPY_HQ_A_SHARE_1MIN_CUTOFF_SAFE",
                rows=[_row(code) for code in codes],
                requested_code_count=len(codes), completed_code_count=len(codes),
            )

        outcome = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=futu,
            pytdx_hq_collector=pytdx_hq,
            pytdx_collector=self._collector([], source_id="pytdx"),
        )
        self.assertTrue(outcome["ok"])
        self.assertEqual(calls, [{
            "source": "pytdx_hq", "market": "A_SHARE", "codes": self.a_codes,
        }])

    def _collector(
        self,
        calls: list[dict],
        *,
        source_id: str,
        fail_market: str = "",
    ):
        def fake(python_path, trade_date, stage_id, codes, *, market,
                 process_runner, timeout_seconds=45):
            calls.append({
                "python_path": Path(python_path),
                "trade_date": trade_date,
                "stage_id": stage_id,
                "codes": list(codes),
                "market": market,
                "timeout_seconds": timeout_seconds,
            })
            if market == fail_market:
                return StageSourceResult(
                    source_id=source_id,
                    display_name="Futu OpenD" if source_id == "futu" else "TDXPy ExHQ",
                    status="READ_FAILED",
                    fidelity=f"{source_id.upper()}_{market}_1MIN_CUTOFF_SAFE",
                    rows=[], error="planned failure", cannot_confirm=["planned failure"],
                )
            rows = [_row(code, price=10.0 + index) for index, code in enumerate(codes)]
            return StageSourceResult(
                source_id=source_id,
                display_name="Futu OpenD" if source_id == "futu" else "TDXPy ExHQ",
                status="READ_OK",
                fidelity=f"{source_id.upper()}_{market}_1MIN_CUTOFF_SAFE", rows=rows,
                error="", cannot_confirm=[],
            )
        return fake

    def test_stage_bundle_prefers_v2_codes_when_legacy_v1_also_exists(self) -> None:
        legacy = universe_manifest_legacy_path(self.store, TRADE_DATE)
        legacy_payload = {
            "schema_version": UNIVERSE_SCHEMA_VERSION_V1,
            "trade_date": TRADE_DATE,
            "market": "A_SHARE",
            "scope": "STAGE_CANDIDATES",
            "codes": ["SH.699999"],
            "code_count": 1,
            "codes_sha256": sha256_json(["SH.699999"]),
            "source_role": "LEGACY_V1",
            "source_sha256": "d" * 64,
            "source_date": TRADE_DATE,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_bytes(canonical_bytes(legacy_payload))
        calls: list[dict] = []
        outcome = run_stage_bundle(
            self.store,
            TRADE_DATE,
            STAGE_ID,
            self.python,
            futu_collector=self._collector(calls, source_id="futu"),
            pytdx_collector=self._collector(calls, source_id="pytdx"),
        )
        self.assertTrue(outcome["ok"])
        self.assertEqual(calls[0]["codes"], self.a_codes)

    def test_success_persists_both_markets_and_atomic_bundle_receipt(self) -> None:
        calls: list[dict] = []
        outcome = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=self._collector(calls, source_id="futu"),
            pytdx_collector=self._collector(calls, source_id="pytdx"),
        )
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["status"], "READY")
        self.assertEqual([call["market"] for call in calls], ["A_SHARE", "HK_CONNECT"])
        self.assertEqual(calls[0]["codes"], self.a_codes)
        self.assertEqual(calls[1]["codes"], self.hk_codes)
        self.assertGreaterEqual(calls[1]["timeout_seconds"], 120)
        for market in ("A_SHARE", "HK_CONNECT"):
            role = market_role(market, STAGE_ID)
            run = read_verified_latest(self.store, TRADE_DATE, role)
            self.assertEqual(run.receipt["status"], "READY")
            self.assertEqual(run.manifest["market"], market)
        bundle_latest = json.loads((self.store / "bundle_latest.json").read_text(encoding="utf-8"))
        latest = bundle_latest["entries"][f"{TRADE_DATE}/{STAGE_ID}"]
        receipt = json.loads((self.store / latest["receipt_relative"]).read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "READY")
        self.assertEqual(set(receipt["markets"]), {"A_SHARE", "HK_CONNECT"})
        for key in ("production_allowed", "buy_gate_updated", "orders_sent"):
            self.assertIs(receipt[key], False)

    def test_hk_code_only_rows_use_verified_shared_name_dictionary(self) -> None:
        asset_root = self.store / "assets" / "hk_0_2"
        dictionary = asset_root / "names" / "hk_name_dictionary.csv"
        dictionary.parent.mkdir(parents=True)
        dictionary.write_text("code,name\nHK.00001,测试港股\n", encoding="utf-8-sig")
        manifest = {
            "dictionary_relative": "names/hk_name_dictionary.csv",
            "dictionary_sha256": sha256_file(dictionary),
        }
        (asset_root / "names" / "manifest.json").write_bytes(canonical_bytes(manifest))
        (asset_root / "name_latest.json").write_bytes(
            canonical_bytes({"manifest_relative": "names/manifest.json"})
        )

        run_stage_bundle(
            self.store,
            TRADE_DATE,
            STAGE_ID,
            self.python,
            futu_collector=self._collector([], source_id="futu"),
            pytdx_collector=self._collector([], source_id="pytdx"),
        )

        run = read_verified_latest(
            self.store, TRADE_DATE, market_role("HK_CONNECT", STAGE_ID)
        )
        with run.artifact_path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(rows[0]["name"], "测试港股")
        self.assertEqual(
            run.manifest["provenance"]["name_dictionary_sha256"],
            sha256_file(dictionary),
        )

    def test_same_bundle_is_idempotent(self) -> None:
        calls: list[dict] = []
        first = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=self._collector(calls, source_id="futu"),
            pytdx_collector=self._collector(calls, source_id="pytdx"),
        )
        first_call_count = len(calls)
        second = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=self._collector(calls, source_id="futu"),
            pytdx_collector=self._collector(calls, source_id="pytdx"),
        )
        self.assertEqual(second["bundle_id"], first["bundle_id"])
        self.assertTrue(second["already_exists"])
        self.assertTrue(second["reused"])
        self.assertEqual(len(calls), first_call_count, "READY slot must not call Futu twice")

    def test_partial_market_writes_failure_receipt_but_no_component_latest_then_retry_succeeds(self) -> None:
        failed = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=self._collector([], source_id="futu"),
            pytdx_collector=self._collector(
                [], source_id="pytdx", fail_market="HK_CONNECT"
            ),
        )
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["status"], "FAILED")
        self.assertFalse((self.store / "latest.json").exists())
        latest = json.loads((self.store / "bundle_latest.json").read_text(encoding="utf-8"))
        self.assertEqual(latest["entries"][f"{TRADE_DATE}/{STAGE_ID}"]["status"], "FAILED")
        succeeded = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=self._collector([], source_id="futu"),
            pytdx_collector=self._collector([], source_id="pytdx"),
        )
        self.assertTrue(succeeded["ok"])
        self.assertEqual(succeeded["status"], "READY")

    def test_ready_slot_is_immutable_and_does_not_probe_changed_collector(self) -> None:
        first = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=self._collector([], source_id="futu"),
            pytdx_collector=self._collector([], source_id="pytdx"),
        )
        calls = 0

        def changed(python_path, trade_date, stage_id, codes, *, market,
                    process_runner, timeout_seconds=45):
            nonlocal calls
            calls += 1
            rows = [_row(code, price=99.0) for code in codes]
            return StageSourceResult(
                source_id="futu", display_name="Futu OpenD", status="READ_OK",
                fidelity=f"FUTU_{market}_1MIN_CUTOFF_SAFE", rows=rows,
                error="", cannot_confirm=[],
            )

        second = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=changed,
        )
        self.assertEqual(second["bundle_id"], first["bundle_id"])
        self.assertTrue(second["reused"])
        self.assertEqual(calls, 0)

    def test_1545_slot_is_hk_only_and_needs_no_a_manifest(self) -> None:
        universe_manifest_path(self.store, TRADE_DATE, "A_SHARE").unlink()
        calls: list[dict] = []

        def hk_collector(python_path, trade_date, stage_id, codes, *, market,
                         process_runner, timeout_seconds=45):
            calls.append({"market": market, "stage_id": stage_id, "codes": list(codes)})
            rows = []
            for index, code in enumerate(codes):
                row = _row(code, price=10.0 + index)
                row.update(
                    update_time="2026-08-06 15:55:00",
                    window_start="2026-08-06 15:46:00",
                    window_end="2026-08-06 15:55:00",
                    bar_count=10,
                )
                rows.append(row)
            return StageSourceResult(
                source_id="pytdx", display_name="TDXPy ExHQ", status="READ_OK",
                fidelity="TDXPY_EXHQ_HK_1MIN_CUTOFF_SAFE", rows=rows,
                error="", cannot_confirm=[],
            )

        outcome = run_stage_bundle(
            self.store, TRADE_DATE, "STAGE_1545_1555", self.python,
            pytdx_collector=hk_collector,
        )
        self.assertTrue(outcome["ok"])
        self.assertEqual(calls, [{
            "market": "HK_CONNECT",
            "stage_id": "STAGE_1545_1555",
            "codes": self.hk_codes,
        }])
        self.assertEqual(set(outcome["markets"]), {"HK_CONNECT"})

    def test_full_hk_market_uses_pytdx_without_attempting_futu_subscription(self) -> None:
        futu_calls: list[str] = []
        pytdx_calls: list[str] = []

        def futu_collector(python_path, trade_date, stage_id, codes, *, market,
                           process_runner, timeout_seconds=45):
            futu_calls.append(market)
            rows = [_row(code, price=10.0 + index) for index, code in enumerate(codes)]
            return StageSourceResult(
                source_id="futu", display_name="Futu OpenD", status="READ_OK",
                fidelity=f"FUTU_{market}_1MIN_CUTOFF_SAFE", rows=rows,
            )

        def pytdx_collector(python_path, trade_date, stage_id, codes, *, market,
                            process_runner, timeout_seconds=45):
            pytdx_calls.append(market)
            rows = [_row(code, price=10.0 + index) for index, code in enumerate(codes[:-1])]
            return StageSourceResult(
                source_id="pytdx", display_name="TDXPy ExHQ", status="READ_OK",
                fidelity="TDXPY_EXHQ_HK_1MIN_CUTOFF_SAFE", rows=rows,
                requested_code_count=len(codes), completed_code_count=len(codes),
                no_data_codes=[codes[-1]],
            )

        outcome = run_stage_bundle(
            self.store, TRADE_DATE, STAGE_ID, self.python,
            futu_collector=futu_collector,
            pytdx_collector=pytdx_collector,
        )

        self.assertTrue(outcome["ok"])
        self.assertEqual(futu_calls, ["A_SHARE"])
        self.assertEqual(pytdx_calls, ["HK_CONNECT"])
        self.assertEqual(outcome["markets"]["HK_CONNECT"]["source_id"], "pytdx")
        self.assertEqual(outcome["markets"]["HK_CONNECT"]["requested_code_count"], len(self.hk_codes))
        self.assertEqual(outcome["markets"]["HK_CONNECT"]["no_data_code_count"], 1)
        self.assertEqual(
            outcome["markets"]["HK_CONNECT"]["no_data_codes"],
            [self.hk_codes[-1]],
        )
        run = read_verified_latest(
            self.store, TRADE_DATE, market_role("HK_CONNECT", STAGE_ID)
        )
        provenance = run.manifest["provenance"]
        self.assertEqual(provenance["requested_code_count"], str(len(self.hk_codes)))
        self.assertEqual(provenance["no_data_code_count"], "1")
        self.assertEqual(
            provenance["no_data_codes_sha256"], sha256_json([self.hk_codes[-1]])
        )


class TestFixedCli(_Base):
    def test_only_date_stage_and_dry_run_are_accepted(self) -> None:
        env = {
            "V3_SHARED_DATA_STORE_ROOT": str(self.store),
            "V3_SHARED_FUTU_PYTHON": str(self.python),
        }
        outcome = main(
            ["--trade-date", TRADE_DATE, "--stage-id", STAGE_ID, "--dry-run"],
            env=env,
        )
        self.assertTrue(outcome["ok"])
        self.assertEqual(outcome["status"], "VALIDATED")
        for forbidden in ("--codes-json", "--store-root", "--python", "--source-path"):
            with self.subTest(option=forbidden):
                rejected = main(
                    ["--trade-date", TRADE_DATE, "--stage-id", STAGE_ID,
                     forbidden, "anything"],
                    env=env,
                )
                self.assertFalse(rejected["ok"])
                self.assertEqual(rejected["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
