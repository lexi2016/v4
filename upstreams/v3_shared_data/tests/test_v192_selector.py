from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from shared_data import v192_oracle_bundle, v192_selector
from shared_data.hashing import sha256_file, sha256_json
from shared_data.store import StoreError
from shared_data.v192_selector import (
    CANONICAL_FORMULA_SOURCE,
    FROZEN_ORACLE_SHA256S,
    _PREMARKET_SOURCE_FIELDS,
    V192_ENTRY_FIELDS,
    V192_INTERMEDIATE_FIELDS,
    V192_LEGACY_ROLE,
    V192_PREVIOUS_ROLE,
    V192_RANK_BOUNDARY,
    V192_ROLE,
    _read_selector_panel_source_rows,
    publish_v192_rows,
    read_verified_v192_pool,
    run_frozen_v192_oracle,
    verify_local_oracle_bundle,
    verify_oracle_sources,
)


# These paths are test-only semantic references.  Runtime selector code must
# never resolve or import them; the local bundle is the production closure.
_REFERENCE_ORACLE_SOURCES = {
    "feature_vector": Path(
        "/Users/lexi/Desktop/学习/牛股学习/A股研究/formula_backtests/"
        "v192_transparent_backtest_20260730/"
        "run_v192_transparent_backtest_20260730.py"
    ),
    "score_v19_multihead": Path(
        "/Users/lexi/Desktop/学习/牛股学习/A股研究/_legacy_research_review/"
        "99_model_discovery_experiments/bull_agent_self_iteration_workbench_20260514/"
        "small_test_multihead_vs_v19_20260516/"
        "run_small_test_multihead_vs_v19_20260516.py"
    ),
    "fmla04_role": Path(
        "/Users/lexi/Desktop/学习/牛股学习/A股研究/_legacy_research_review/"
        "99_model_discovery_experiments/bull_agent_self_iteration_workbench_20260514/"
        "fmla04_return_driven_self_iteration_20260518/"
        "run_fmla04_return_driven_self_iteration_20260518.py"
    ),
}
_REFERENCE_ORACLE_SHAS = {
    "feature_vector": "1685327e016ce7a12ff7982379b91463c7c2bfb311e0b892385e692926970e74",
    "score_v19_multihead": "2a28049399043194b2f8523c8a2da7248708bf49e01f1d7e167fed933b92e4f2",
    "fmla04_role": "950b14447cb61049fb44efa46a10dfa6b3d5374188e212f8aff06fee1ab326c1",
}


def _load_reference_oracle(name: str):
    path = _REFERENCE_ORACLE_SOURCES[name]
    expected_sha = _REFERENCE_ORACLE_SHAS[name]
    if sha256_file(path) != expected_sha:
        raise AssertionError(f"reference oracle SHA changed: {name}")
    spec = importlib.util.spec_from_file_location(
        f"test_only_v192_reference_{name}", path
    )
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load test-only reference: {name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_long_oracle_fixture(path: Path) -> list[str]:
    dates = pd.bdate_range("2026-01-05", periods=140).strftime("%Y%m%d").tolist()
    rows: list[dict[str, object]] = []
    for symbol_index, code in enumerate(("000001.SZ", "600000.SH")):
        for index, trade_date in enumerate(dates):
            close = 10.0 + symbol_index * 3.0 + index * 0.025
            row: dict[str, object] = {
                column: False if column in v192_oracle_bundle.BOOL_COLUMNS else 0.0
                for column in v192_oracle_bundle.REQUIRED_BASE_COLUMNS
            }
            row.update(
                {
                    "trade_date": trade_date,
                    "ts_code": code,
                    "name": f"fixture-{symbol_index}",
                    "open": close - 0.05,
                    "high": close + 0.12,
                    "low": close - 0.14,
                    "close": close,
                    "volume": 1_000_000.0 + index * 1_000.0,
                    "amount": 10_000_000.0 + index * 10_000.0,
                    "pre_close": close - 0.025,
                    "pct_chg": 0.25,
                    "amplitude_pct": 2.6,
                    "bar_close_pos": 0.7,
                    "upper_shadow_pct": 1.1,
                    "lower_shadow_pct": 1.3,
                    "amount_ratio_20": 1.0,
                    "high_20_prev": close,
                    "BBI": close - 0.03,
                    "zge_white_line": close - 0.04,
                    "zge_yellow_line": close - 0.08,
                    "J": 40.0,
                    "zge_rsi3": 40.0,
                    "ma20": close - 0.02,
                    "gold_brick_context": "none",
                }
            )
            rows.append(row)
    pd.DataFrame(rows).to_parquet(path, index=False)
    return dates


def _candidate(code: str = "000661.SZ") -> dict[str, object]:
    return {
        "ts_code": code,
        "stock_code": code.split(".", 1)[0],
        "stock_name": "test",
        "candidate_role": "TEST_ONLY_BUY_CANDIDATE",
        "multi_head_final_role": "B2_FRESH_ENTRY",
        "entry_pool": True,
        "review_rank_v19": 1,
        "final_score": 91.5,
        "fresh_b2_entry_score": 80,
        "continuation_entry_score": 0,
        "risk_chase_score": 12,
        "rank_usage_boundary": V192_RANK_BOUNDARY,
        "formal_recommendation_allowed": False,
        # The shared materializer must retain the explicit selector fields
        # used by the frozen V3 premarket-pool score.  V3.5 consumes this
        # value directly; it must never substitute final_score/selector
        # metadata at the stage-card boundary.
        "primary_buy_signal": 1,
        "secondary_buy_signal": 0,
        "gold_brick_context": "none",
        "brick_resonance_context": 0,
        "brick_buy": 0,
        "brick_buy1_low_absorb": 0,
        "brick_buy2_attack": 0,
        "brick_resonance1": 0,
        "brick_resonance2": 0,
        "brick_resonance": 0,
        "ref_hold_score": 4,
        "B1": 0,
        "B2": 1,
        "B3": 0,
        "BG": 1,
        "amount": 1_500_000_000,
        "formula_source": CANONICAL_FORMULA_SOURCE,
        "field_contract_version": "formula_signal_v2_reference_score",
    }


class TestV192SharedSelector(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="v3sd_v192_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.panel = self.tmp / "selector_ready.parquet"
        self.panel.write_bytes(b"frozen-panel")
        self.store = self.tmp / "store"

    def test_v3_role_is_distinct_and_reader_has_no_v2_or_v1_fallback(self) -> None:
        self.assertEqual(V192_LEGACY_ROLE, "A_SHARE_V192_PREMARKET_POOL")
        self.assertEqual(V192_PREVIOUS_ROLE, "A_SHARE_V192_PREMARKET_POOL_V2")
        self.assertEqual(V192_ROLE, "A_SHARE_V192_PREMARKET_POOL_V3")
        (self.store).mkdir(parents=True, exist_ok=True)
        (self.store / "latest.json").write_text(
            '{"schema_version":"v3_shared_data.latest.v1","entries":{'
            '"20260810/A_SHARE_V192_PREMARKET_POOL_V2":{"run_id":"previous"},'
            '"20260810/A_SHARE_V192_PREMARKET_POOL":{"run_id":"legacy"}}}',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(StoreError, "no latest run"):
            read_verified_v192_pool(
                self.store,
                target_date="20260810",
                expected_signal_date="20260807",
            )

    def test_publish_and_read_verified_pool(self) -> None:
        outcome = publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )

        pool = read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )

        self.assertEqual(outcome["run_id"], pool.run.verification["run_id"])
        self.assertIn(f"20260810/{V192_ROLE}/", pool.run.verification["artifact_relative"])
        self.assertEqual(pool.run.receipt["owner"], "v3_shared_data")
        self.assertEqual(pool.run.manifest["signal_date"], "20260807")
        self.assertEqual(pool.run.manifest["trade_date"], "20260810")
        self.assertEqual(pool.run.manifest["provenance"]["panel_sha256"], sha256_file(self.panel))
        self.assertEqual([row["ts_code"] for row in pool.rows], ["000661.SZ"])
        self.assertEqual(pool.rows[0]["premarket_pool_score"], "134.0")
        self.assertEqual(pool.rows[0]["premarket_score_formula"], "V3_PREMARKET_POOL_V1")
        self.assertEqual(
            pool.run.manifest["provenance"]["premarket_score_formula"],
            "V3_PREMARKET_POOL_V1",
        )
        self.assertIs(pool.production_allowed, False)
        self.assertIs(pool.buy_gate_updated, False)
        self.assertIs(pool.orders_sent, False)

    def test_publish_freezes_v3_role_and_safety_flags_in_manifest_and_receipt(self) -> None:
        publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        pool = read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )

        for payload in (pool.run.manifest, pool.run.receipt):
            self.assertEqual(payload["role"], V192_ROLE)
            self.assertIs(payload["production_allowed"], False)
            self.assertIs(payload["buy_gate_updated"], False)
            self.assertIs(payload["orders_sent"], False)

    def test_reader_rejects_manifest_role_mismatch_with_authoritative_receipt(self) -> None:
        publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        pool = read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )
        manifest = json.loads(pool.run.manifest_path.read_text(encoding="utf-8"))
        manifest["role"] = V192_PREVIOUS_ROLE
        pool.run.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        receipt = json.loads(pool.run.receipt_path.read_text(encoding="utf-8"))
        receipt["manifest_sha256"] = sha256_json(manifest)
        pool.run.receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False), encoding="utf-8"
        )

        with self.assertRaisesRegex(StoreError, "manifest role"):
            read_verified_v192_pool(
                self.store,
                target_date="20260810",
                expected_signal_date="20260807",
            )

    def test_reader_rejects_receipt_role_mismatch_for_v3_slot(self) -> None:
        publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        pool = read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )
        receipt = json.loads(pool.run.receipt_path.read_text(encoding="utf-8"))
        receipt["role"] = V192_PREVIOUS_ROLE
        pool.run.receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False), encoding="utf-8"
        )

        with self.assertRaisesRegex(StoreError, "receipt role"):
            read_verified_v192_pool(
                self.store,
                target_date="20260810",
                expected_signal_date="20260807",
            )

    def test_reader_rejects_manifest_safety_flag_not_false(self) -> None:
        publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        pool = read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )
        manifest = json.loads(pool.run.manifest_path.read_text(encoding="utf-8"))
        manifest["orders_sent"] = True
        pool.run.manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        receipt = json.loads(pool.run.receipt_path.read_text(encoding="utf-8"))
        receipt["manifest_sha256"] = sha256_json(manifest)
        pool.run.receipt_path.write_text(
            json.dumps(receipt, ensure_ascii=False), encoding="utf-8"
        )

        with self.assertRaisesRegex(StoreError, "manifest safety flag"):
            read_verified_v192_pool(
                self.store,
                target_date="20260810",
                expected_signal_date="20260807",
            )

    def test_same_input_is_idempotent(self) -> None:
        first = publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        second = publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertIs(second["already_exists"], True)

    def test_premarket_score_derives_primary_from_b_fields_when_signals_are_zero(self) -> None:
        row = _candidate("603983.SH")
        row.update(
            primary_buy_signal=0,
            secondary_buy_signal=0,
            brick_buy=1,
            ref_hold_score=3,
            B1=0,
            B2=1,
            B3=0,
            BG=1,
            amount=216_986_448,
        )
        outcome = publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[row],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        pool = read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )

        self.assertEqual(outcome["run_id"], pool.run.verification["run_id"])
        self.assertEqual(pool.rows[0]["premarket_pool_score"], "128.16986448")
        self.assertEqual(pool.rows[0]["primary_buy_signal"], "1.0")
        self.assertEqual(pool.rows[0]["secondary_buy_signal"], "0.0")

    def test_explicit_signal_on_any_day_row_disables_b_field_derivation_for_zero_rows(self) -> None:
        explicit = _candidate("000661.SZ")
        explicit.update(
            primary_buy_signal=1,
            secondary_buy_signal=0,
            ref_hold_score=4,
            B1=0,
            B2=1,
            B3=0,
            BG=1,
            amount=1_500_000_000,
        )
        zero_signal = _candidate("603983.SH")
        zero_signal.update(
            primary_buy_signal=0,
            secondary_buy_signal=0,
            brick_buy=1,
            ref_hold_score=3,
            B1=0,
            B2=1,
            B3=0,
            BG=1,
            amount=216_986_448,
        )
        publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[explicit, zero_signal],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        pool = read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )
        by_code = {row["ts_code"]: row for row in pool.rows}

        assert by_code["603983.SH"]["primary_buy_signal"] == "0.0"
        assert by_code["603983.SH"]["premarket_pool_score"] == "28.16986448"

    def test_full_selector_panel_source_rows_retain_ref_hold_score(self) -> None:
        panel = self.tmp / "selector_ready_full.parquet"
        pd.DataFrame(
            [
                {
                    "trade_date": 20260807,
                    "ts_code": "603983.SH",
                    "ref_hold_score": 3,
                    "B1": 0,
                    "B2": 1,
                    "B3": 0,
                    "BG": 1,
                    "primary_buy_signal": 0,
                    "secondary_buy_signal": 0,
                    "amount": 216_986_448,
                }
            ]
        ).to_parquet(panel, index=False)

        rows = _read_selector_panel_source_rows(panel, "20260807")

        self.assertEqual(rows["603983.SH"]["ref_hold_score"], 3)
        self.assertEqual(rows["603983.SH"]["amount"], 216_986_448)

    def test_exact_signal_date_panel_fields_override_stale_frozen_scorer_fields(self) -> None:
        signal_date = "20260811"
        code = "000001.SZ"
        canonical = {
            "trade_date": signal_date,
            "ts_code": code,
            "primary_buy_signal": 0,
            "secondary_buy_signal": 0,
            "gold_brick_context": "none",
            "brick_resonance_context": 0,
            "brick_buy": 0,
            "brick_buy1_low_absorb": 0,
            "brick_buy2_attack": 0,
            "brick_resonance1": 0,
            "brick_resonance2": 0,
            "brick_resonance": 0,
            "ref_hold_score": 2,
            "B1": 1,
            "B2": 0,
            "B3": 0,
            "BG": 1,
            "amount": 749_686_464.0,
            "pct_chg": -0.2657,
            "route_context": "B1",
            "brick_context": "1",
            "formula_source": CANONICAL_FORMULA_SOURCE,
            "field_contract_version": "authoritative_field_contract_v0_2_phase1",
        }
        panel = self.tmp / "selector_ready_canonical.parquet"
        pd.DataFrame([canonical]).to_parquet(panel, index=False)

        stale = dict(canonical)
        stale.update(
            {
                "gold_brick_context": 7,
                "formula_source": "daily_formula_increment_update_v1_formula_direct",
                "primary_buy_signal": 1,
                "secondary_buy_signal": 1,
            }
        )

        class FakeFeature:
            @staticmethod
            def read_window(_path, _start, _end):
                return pd.DataFrame([stale])

            @staticmethod
            def vector_prepare_features(frame):
                return frame.copy()

        class FakeScorer:
            @staticmethod
            def score_v19(frame):
                return frame.copy()

            @staticmethod
            def score_multi_head(frame):
                scored = frame.copy()
                scored["date8"] = signal_date
                scored["stock_code"] = "000001"
                scored["stock_name"] = "test"
                scored["multi_head_final_role"] = "B2_FRESH_ENTRY"
                scored["final_score"] = 99.0
                scored["multi_entry_score"] = 88.0
                scored["multi_entry_risk_adjusted_score"] = 77.0
                scored["fresh_b2_entry_score"] = 66.0
                scored["continuation_entry_score"] = 0.0
                scored["hold_through_main_wave_score"] = 55.0
                scored["risk_chase_score"] = 1.0
                return scored

        class FakeRoles:
            @staticmethod
            def entry_pool(frame):
                return pd.Series(True, index=frame.index)

            @staticmethod
            def base_fmla04_role(frame):
                return pd.Series("TEST_ONLY_BUY_CANDIDATE", index=frame.index)

        with patch.object(
            v192_oracle_bundle, "read_window", FakeFeature.read_window
        ), patch.object(
            v192_oracle_bundle,
            "vector_prepare_features",
            FakeFeature.vector_prepare_features,
        ), patch.object(
            v192_oracle_bundle, "score_v19", FakeScorer.score_v19
        ), patch.object(
            v192_oracle_bundle,
            "score_multi_head",
            FakeScorer.score_multi_head,
        ), patch.object(
            v192_oracle_bundle, "entry_pool", FakeRoles.entry_pool
        ), patch.object(
            v192_oracle_bundle,
            "base_fmla04_role",
            FakeRoles.base_fmla04_role,
        ):
            output = run_frozen_v192_oracle(
                panel,
                signal_date,
            )

        result = output[0]
        for field, expected in canonical.items():
            if field not in {"trade_date", "ts_code"}:
                self.assertEqual(result[field], expected, field)
        self.assertEqual(result["final_score"], 99.0)
        self.assertEqual(result["multi_head_final_role"], "B2_FRESH_ENTRY")

    def test_missing_exact_panel_source_field_fails_closed_in_frozen_oracle(self) -> None:
        signal_date = "20260811"
        code = "000001.SZ"
        canonical = {
            "trade_date": signal_date,
            "ts_code": code,
            **{
                field: ("none" if field == "gold_brick_context" else 0)
                for field in _PREMARKET_SOURCE_FIELDS
                if field not in {"trade_date", "ts_code", "formula_source"}
            },
            "formula_source": CANONICAL_FORMULA_SOURCE,
        }
        canonical.pop("formula_source")
        panel = self.tmp / "selector_ready_missing_formula.parquet"
        pd.DataFrame([canonical]).to_parquet(panel, index=False)

        stale = dict(canonical)
        stale["formula_source"] = "daily_formula_increment_update_v1_formula_direct"
        stale["primary_buy_signal"] = 1

        class FakeFeature:
            @staticmethod
            def read_window(_path, _start, _end):
                return pd.DataFrame([stale])

            @staticmethod
            def vector_prepare_features(frame):
                return frame.copy()

        class FakeScorer:
            @staticmethod
            def score_v19(frame):
                return frame.copy()

            @staticmethod
            def score_multi_head(frame):
                scored = frame.copy()
                scored["date8"] = signal_date
                scored["stock_code"] = "000001"
                scored["stock_name"] = "test"
                scored["multi_head_final_role"] = "B2_FRESH_ENTRY"
                scored["final_score"] = 99.0
                scored["risk_chase_score"] = 1.0
                return scored

        class FakeRoles:
            @staticmethod
            def entry_pool(frame):
                return pd.Series(True, index=frame.index)

            @staticmethod
            def base_fmla04_role(frame):
                return pd.Series("TEST_ONLY_BUY_CANDIDATE", index=frame.index)

        with patch.object(
            v192_oracle_bundle, "read_window", FakeFeature.read_window
        ), patch.object(
            v192_oracle_bundle,
            "vector_prepare_features",
            FakeFeature.vector_prepare_features,
        ), patch.object(
            v192_oracle_bundle, "score_v19", FakeScorer.score_v19
        ), patch.object(
            v192_oracle_bundle,
            "score_multi_head",
            FakeScorer.score_multi_head,
        ), patch.object(
            v192_oracle_bundle, "entry_pool", FakeRoles.entry_pool
        ), patch.object(
            v192_oracle_bundle,
            "base_fmla04_role",
            FakeRoles.base_fmla04_role,
        ):
            with self.assertRaisesRegex(StoreError, "selector panel source field missing"):
                run_frozen_v192_oracle(
                    panel,
                    signal_date,
                )

    def test_present_but_empty_panel_source_fields_fail_closed(self) -> None:
        signal_date = "20260811"
        code = "000001.SZ"
        source = {
            "trade_date": int(signal_date),
            "ts_code": code,
            **{
                field: (
                    "none"
                    if field == "gold_brick_context"
                    else "B2"
                    if field == "route_context"
                    else "1"
                    if field == "brick_context"
                    else CANONICAL_FORMULA_SOURCE
                    if field == "formula_source"
                    else "formula_signal_v2_reference_score"
                    if field == "field_contract_version"
                    else 0
                )
                for field in _PREMARKET_SOURCE_FIELDS
            },
        }
        panel = self.tmp / "selector_ready_present_but_empty.parquet"

        class FakeFeature:
            @staticmethod
            def read_window(_path, _start, _end):
                return pd.DataFrame([{"ts_code": code}])

            @staticmethod
            def vector_prepare_features(frame):
                return frame.copy()

        class FakeScorer:
            @staticmethod
            def score_v19(frame):
                return frame.copy()

            @staticmethod
            def score_multi_head(frame):
                scored = frame.copy()
                scored["date8"] = signal_date
                scored["stock_code"] = "000001"
                scored["stock_name"] = "test"
                scored["multi_head_final_role"] = "B2_FRESH_ENTRY"
                scored["final_score"] = 99.0
                scored["multi_entry_score"] = 88.0
                scored["multi_entry_risk_adjusted_score"] = 77.0
                scored["fresh_b2_entry_score"] = 66.0
                scored["continuation_entry_score"] = 0.0
                scored["hold_through_main_wave_score"] = 55.0
                scored["risk_chase_score"] = 1.0
                return scored

        class FakeRoles:
            @staticmethod
            def entry_pool(frame):
                return pd.Series(True, index=frame.index)

            @staticmethod
            def base_fmla04_role(frame):
                return pd.Series("TEST_ONLY_BUY_CANDIDATE", index=frame.index)

        with patch.object(
            v192_oracle_bundle, "read_window", FakeFeature.read_window
        ), patch.object(
            v192_oracle_bundle,
            "vector_prepare_features",
            FakeFeature.vector_prepare_features,
        ), patch.object(
            v192_oracle_bundle, "score_v19", FakeScorer.score_v19
        ), patch.object(
            v192_oracle_bundle,
            "score_multi_head",
            FakeScorer.score_multi_head,
        ), patch.object(
            v192_oracle_bundle, "entry_pool", FakeRoles.entry_pool
        ), patch.object(
            v192_oracle_bundle,
            "base_fmla04_role",
            FakeRoles.base_fmla04_role,
        ):
            for field in _PREMARKET_SOURCE_FIELDS:
                row = dict(source)
                row[field] = "  "
                pd.DataFrame([row]).to_parquet(panel, index=False)
                with self.subTest(field=field):
                    with self.assertRaisesRegex(
                        StoreError,
                        f"selector panel source field missing:.*{field}",
                    ):
                        run_frozen_v192_oracle(panel, signal_date)

    def test_old_contract_without_premarket_formula_cannot_be_read_as_new(self) -> None:
        publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        pool = read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )
        manifest_path = pool.run.manifest_path
        receipt_path = pool.run.receipt_path
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["provenance"].pop("premarket_score_formula", None)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["manifest_sha256"] = sha256_json(manifest)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False), encoding="utf-8")

        with self.assertRaisesRegex(StoreError, "premarket_score_formula"):
            read_verified_v192_pool(
                self.store,
                target_date="20260810",
                expected_signal_date="20260807",
            )

    def test_v192_artifact_retains_all_original_entry_fields(self) -> None:
        publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )

        pool = read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )

        self.assertTrue(set(V192_ENTRY_FIELDS).issubset(pool.rows[0]))
        self.assertEqual(pool.rows[0]["formula_source"], CANONICAL_FORMULA_SOURCE)

    def test_missing_original_entry_field_fails_closed(self) -> None:
        row = _candidate()
        row.pop("brick_buy")

        with self.assertRaisesRegex(StoreError, "entry fields missing"):
            publish_v192_rows(
                self.store,
                panel_path=self.panel,
                signal_date="20260807",
                target_date="20260810",
                rows=[row],
                oracle_sha256s=FROZEN_ORACLE_SHA256S,
            )

    def test_nan_entry_signal_fails_closed_as_missing(self) -> None:
        for empty in (float("nan"), pd.NA):
            with self.subTest(value=type(empty).__name__):
                row = _candidate()
                row["brick_buy"] = empty
                with self.assertRaisesRegex(StoreError, "signal field missing: brick_buy"):
                    publish_v192_rows(
                        self.store,
                        panel_path=self.panel,
                        signal_date="20260807",
                        target_date="20260810",
                        rows=[row],
                        oracle_sha256s=FROZEN_ORACLE_SHA256S,
                    )

    def test_direct_daily_formula_source_is_not_a_v192_artifact(self) -> None:
        row = _candidate()
        row["formula_source"] = "daily_formula_increment_update_v1_formula_direct"

        with self.assertRaisesRegex(StoreError, "formula_source"):
            publish_v192_rows(
                self.store,
                panel_path=self.panel,
                signal_date="20260807",
                target_date="20260810",
                rows=[row],
                oracle_sha256s=FROZEN_ORACLE_SHA256S,
            )

    def test_old_gold_text_does_not_satisfy_entry_pool(self) -> None:
        row = _candidate()
        for field in V192_ENTRY_FIELDS:
            row[field] = "none" if field == "gold_brick_context" else 0
        row["gold_brick_context"] = "old_gold_candidate"
        row["entry_pool"] = True

        with self.assertRaisesRegex(StoreError, "entry_pool"):
            publish_v192_rows(
                self.store,
                panel_path=self.panel,
                signal_date="20260807",
                target_date="20260810",
                rows=[row],
                oracle_sha256s=FROZEN_ORACLE_SHA256S,
            )

    def test_local_bundle_contract_keeps_origin_and_source_sha_layers(self) -> None:
        contract = verify_local_oracle_bundle()

        self.assertEqual(contract["origin_sha256s"], _REFERENCE_ORACLE_SHAS)
        self.assertEqual(FROZEN_ORACLE_SHA256S, _REFERENCE_ORACLE_SHAS)
        self.assertEqual(
            contract["origin_bundle_sha256"],
            "d356394cc163851e5b5b1fbd3c1f491bfc5a264a21bd589fc962764e814698e9",
        )
        self.assertEqual(
            contract["origin_bundle_sha256"], sha256_json(FROZEN_ORACLE_SHA256S)
        )
        self.assertEqual(
            contract["local_bundle_sha256"], v192_oracle_bundle.local_bundle_sha256()
        )
        self.assertNotEqual(
            contract["local_bundle_sha256"], contract["origin_bundle_sha256"]
        )
        self.assertEqual(
            tuple(v192_oracle_bundle.required_local_symbols()),
            (
                "read_window",
                "vector_prepare_features",
                "score_v19",
                "score_multi_head",
                "entry_pool",
                "base_fmla04_role",
            ),
        )
        self.assertEqual(verify_oracle_sources(), FROZEN_ORACLE_SHA256S)

    def test_local_bundle_rejects_changed_origin_map(self) -> None:
        changed = dict(FROZEN_ORACLE_SHA256S)
        changed["feature_vector"] = "0" * 64
        with patch.object(v192_oracle_bundle, "ORACLE_ORIGIN_SHA256S", changed):
            with self.assertRaisesRegex(StoreError, "oracle sha"):
                verify_local_oracle_bundle()

    def test_runtime_selector_contains_no_legacy_dynamic_loader(self) -> None:
        runtime_text = "\n".join(
            (
                Path(v192_oracle_bundle.__file__).read_text(encoding="utf-8"),
                Path(v192_selector.__file__).read_text(encoding="utf-8"),
            )
        )
        for forbidden in (
            "importlib.util",
            "spec_from_file_location",
            "/Users/lexi/Desktop/学习/牛股学习",
            "DATA_INTERFACE_PATH",
            "SELECTOR_POINTER",
            "LEGACY_SCORE_SOURCE",
            "LEGACY_ROLE_SOURCE",
        ):
            self.assertNotIn(forbidden, runtime_text)

    def test_long_window_reference_parity_in_features_scores_roles_and_candidates(self) -> None:
        panel = self.tmp / "long_window.parquet"
        dates = _write_long_oracle_fixture(panel)
        reference_feature = _load_reference_oracle("feature_vector")
        reference_scorer = _load_reference_oracle("score_v19_multihead")
        reference_roles = _load_reference_oracle("fmla04_role")

        reference_raw = reference_feature.read_window(panel, 20260101, int(dates[-1]))
        local_raw = v192_oracle_bundle.read_window(panel, 20260101, int(dates[-1]))
        pd.testing.assert_frame_equal(
            reference_raw.reset_index(drop=True),
            local_raw.reset_index(drop=True),
            check_dtype=False,
            check_exact=True,
        )

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
            reference_prepared = reference_feature.vector_prepare_features(reference_raw.copy())
            local_prepared = v192_oracle_bundle.vector_prepare_features(local_raw.copy())
        pd.testing.assert_frame_equal(
            reference_prepared,
            local_prepared,
            check_dtype=False,
            check_exact=True,
        )

        reference_scored = reference_scorer.score_multi_head(
            reference_scorer.score_v19(reference_prepared)
        )
        local_scored = v192_oracle_bundle.score_multi_head(
            v192_oracle_bundle.score_v19(local_prepared)
        )
        pd.testing.assert_frame_equal(
            reference_scored,
            local_scored,
            check_dtype=False,
            check_exact=True,
        )

        reference_entry = reference_roles.entry_pool(reference_scored)
        local_entry = v192_oracle_bundle.entry_pool(local_scored)
        pd.testing.assert_series_equal(
            reference_entry,
            local_entry,
            check_dtype=False,
            check_exact=True,
        )
        reference_role = reference_roles.base_fmla04_role(reference_scored)
        local_role = v192_oracle_bundle.base_fmla04_role(local_scored)
        pd.testing.assert_series_equal(
            reference_role,
            local_role,
            check_dtype=False,
            check_exact=True,
        )

        reference_candidates = reference_scored.loc[
            reference_entry & reference_role.eq("TEST_ONLY_BUY_CANDIDATE"),
            ["ts_code", "multi_head_final_role", "final_score"],
        ].reset_index(drop=True)
        local_candidates = local_scored.loc[
            local_entry & local_role.eq("TEST_ONLY_BUY_CANDIDATE"),
            ["ts_code", "multi_head_final_role", "final_score"],
        ].reset_index(drop=True)
        pd.testing.assert_frame_equal(
            reference_candidates,
            local_candidates,
            check_dtype=False,
            check_exact=True,
        )

    def test_read_window_matches_trade_date_arrow_literal_type(self) -> None:
        source = self.tmp / "date_type_source.parquet"
        _write_long_oracle_fixture(source)
        original = pd.read_parquet(source)
        variants = {
            "string": original["trade_date"],
            "int64": pd.to_numeric(original["trade_date"]).astype("int64"),
            "date": pd.to_datetime(original["trade_date"], format="%Y%m%d").dt.date,
            "timestamp": pd.to_datetime(original["trade_date"], format="%Y%m%d"),
            "timestamp_tz": pd.to_datetime(original["trade_date"], format="%Y%m%d").dt.tz_localize("UTC"),
        }
        expected_dates = {"20260105", "20260106"}
        for label, values in variants.items():
            panel = self.tmp / f"date_type_{label}.parquet"
            variant = original.copy()
            variant["trade_date"] = values
            variant.to_parquet(panel, index=False)
            observed = v192_oracle_bundle.read_window(panel, 20260105, 20260106)
            self.assertEqual(len(observed), 4, label)
            normalized_dates = {
                pd.Timestamp(value).strftime("%Y%m%d")
                if not isinstance(value, (int, np.integer))
                else str(int(value))
                for value in observed["trade_date"]
            }
            self.assertEqual(normalized_dates, expected_dates, label)

    def test_local_bundle_runs_candidates_without_reference_loader(self) -> None:
        panel = self.tmp / "local_candidate.parquet"
        dates = _write_long_oracle_fixture(panel)
        frame = pd.read_parquet(panel)
        frame = frame.assign(
            brick_resonance1=0,
            brick_resonance2=0,
            brick_resonance=0,
            ref_hold_score=4,
            route_context="B2",
            brick_context="1",
            formula_source=CANONICAL_FORMULA_SOURCE,
            field_contract_version="formula_signal_v2_reference_score",
        )
        target = frame["trade_date"].eq(dates[-1])
        for field in (
            "B2",
            "primary_buy_signal",
            "brick_buy2_attack",
            "ref_score_close_up",
            "ref_score_above_bbi",
            "ref_score_no_giant_true_yin",
            "ref_score_trend_up",
            "ref_score_j_no_dead_cross",
        ):
            frame.loc[target, field] = True
        frame.to_parquet(panel, index=False)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", pd.errors.PerformanceWarning)
            rows = run_frozen_v192_oracle(panel, dates[-1])

        self.assertEqual([row["ts_code"] for row in rows], ["000001.SZ", "600000.SH"])
        self.assertTrue(
            all(row["candidate_role"] == "TEST_ONLY_BUY_CANDIDATE" for row in rows)
        )
        self.assertTrue(all(row["entry_pool"] is True for row in rows))

        # Re-run the public function in a fresh interpreter with an explicit
        # V4-only import path. The guards make an accidental read of the old
        # learning-root sources fail instead of relying on the static scan.
        script = """
import builtins
import sys
from pathlib import Path

import shared_data.v192_selector as selector

legacy_marker = "牛股学习"
real_open = builtins.open
real_path_open = Path.open

def guarded_open(file, *args, **kwargs):
    if legacy_marker in str(file):
        raise AssertionError("legacy source read")
    return real_open(file, *args, **kwargs)

def guarded_path_open(self, *args, **kwargs):
    if legacy_marker in str(self):
        raise AssertionError("legacy source read")
    return real_path_open(self, *args, **kwargs)

builtins.open = guarded_open
Path.open = guarded_path_open
if any(legacy_marker in entry for entry in sys.path):
    raise AssertionError("legacy root leaked into sys.path")
rows = selector.run_frozen_v192_oracle(Path(sys.argv[1]), sys.argv[2])
assert len(rows) == 2
assert all(row["candidate_role"] == "TEST_ONLY_BUY_CANDIDATE" for row in rows)
"""
        repo_root = Path(__file__).resolve().parents[3]
        env = {
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": os.pathsep.join(
                (str(repo_root / "upstreams/v3_shared_data"), str(repo_root))
            ),
        }
        subprocess.run(
            [
                "/Users/lexi/Desktop/学习/runtime/venvs/v3.5-mac/bin/python",
                "-c",
                script,
                str(panel),
                dates[-1],
            ],
            cwd=repo_root,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

        target_date = (
            pd.Timestamp(dates[-1]) + pd.offsets.BDay()
        ).strftime("%Y%m%d")
        publish_v192_rows(
            self.store,
            panel_path=panel,
            signal_date=dates[-1],
            target_date=target_date,
            rows=rows,
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        pool = read_verified_v192_pool(
            self.store,
            target_date=target_date,
            expected_signal_date=dates[-1],
        )
        self.assertEqual(len(pool.rows), len(rows))
        binary_fields = (
            tuple(
                field
                for field in V192_ENTRY_FIELDS
                if field not in {"gold_brick_context", "primary_buy_signal", "secondary_buy_signal"}
            )
            + V192_INTERMEDIATE_FIELDS
            + ("entry_pool", "formal_recommendation_allowed")
        )
        for row in pool.rows:
            for field in binary_fields:
                self.assertIn(row[field], {"0", "1"}, field)
            # The frozen score projection intentionally retains its existing
            # numeric 0.0/1.0 representation; source bools above must not be
            # serialized as true/false.
            for field in ("primary_buy_signal", "secondary_buy_signal"):
                self.assertIn(row[field], {"0.0", "1.0"}, field)

    def test_observation_row_cannot_be_published_as_v192(self) -> None:
        row = _candidate()
        row["candidate_role"] = "ADVISOR_GENERATED_D_MINUS_1_SELECTOR_OBSERVATION_POOL"
        with self.assertRaisesRegex(StoreError, "candidate_role"):
            publish_v192_rows(
                self.store,
                panel_path=self.panel,
                signal_date="20260807",
                target_date="20260810",
                rows=[row],
                oracle_sha256s=FROZEN_ORACLE_SHA256S,
            )

    def test_wrong_oracle_hash_fails_closed(self) -> None:
        hashes = dict(FROZEN_ORACLE_SHA256S)
        hashes["score_v19_multihead"] = "0" * 64
        with self.assertRaisesRegex(StoreError, "oracle sha"):
            publish_v192_rows(
                self.store,
                panel_path=self.panel,
                signal_date="20260807",
                target_date="20260810",
                rows=[_candidate()],
                oracle_sha256s=hashes,
            )

    def test_signal_target_date_mismatch_fails_closed(self) -> None:
        publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        with self.assertRaisesRegex(StoreError, "signal_date"):
            read_verified_v192_pool(
                self.store,
                target_date="20260810",
                expected_signal_date="20260806",
            )

    def test_consumer_is_read_only(self) -> None:
        publish_v192_rows(
            self.store,
            panel_path=self.panel,
            signal_date="20260807",
            target_date="20260810",
            rows=[_candidate()],
            oracle_sha256s=FROZEN_ORACLE_SHA256S,
        )
        before = {
            path.relative_to(self.store).as_posix(): (sha256_file(path), path.stat().st_mtime_ns)
            for path in self.store.rglob("*")
            if path.is_file()
        }
        read_verified_v192_pool(
            self.store,
            target_date="20260810",
            expected_signal_date="20260807",
        )
        after = {
            path.relative_to(self.store).as_posix(): (sha256_file(path), path.stat().st_mtime_ns)
            for path in self.store.rglob("*")
            if path.is_file()
        }
        self.assertEqual(before, after)
        self.assertIn(f"20260810/{V192_ROLE}", (self.store / "latest.json").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()


class TestRouteContextConditionalContract(unittest.TestCase):
    """Independent 4-row receipt proves a source-field gate, not selected ranks."""

    def source(self, *, route="", **changes):
        row = {name: 0 for name in _PREMARKET_SOURCE_FIELDS}
        row.update(route_context=route, formula_source=CANONICAL_FORMULA_SOURCE,
                   field_contract_version="authoritative_field_contract_v0_2_phase1",
                   gold_brick_context="none", brick_context="none")
        row.update(changes)
        return row

    def missing(self, row):
        helper = getattr(v192_selector, "_missing_premarket_source_fields", None)
        self.assertTrue(callable(helper), "consumer needs one conditional source-field gate")
        return helper(row)

    def test_four_row_independent_receipt_subgate(self):
        # Only relevant fields from route_context-minimal.jsonl. These are source
        # examples; no assertion about the model's first selected code or rank.
        examples = [
            ("000001.SZ", "B2", dict(B2=1, primary_buy_signal=1)),
            ("603439.SH", "B2", dict(B2=1, primary_buy_signal=1, secondary_buy_signal=1)),
            ("000561.SZ", "", dict(primary_buy_signal=1, brick_buy=1)),
            ("000722.SZ", "", dict(secondary_buy_signal=1)),
        ]
        for code, route, signals in examples:
            with self.subTest(code=code):
                row = self.source(route=route, **signals)
                before = dict(row)
                self.assertEqual(self.missing(row), [])
                self.assertEqual(row, before, "do not fill a default context")

    def test_b1_b2_b3_require_context(self):
        for field in ("B1", "B2", "B3"):
            for value in (1, 1.0, True, "1", "1.0", "true"):
                with self.subTest(field=field, value=value):
                    self.assertIn("route_context", self.missing(self.source(**{field: value})))

    def test_bg_does_not_invent_a_b123_route(self):
        self.assertEqual(self.missing(self.source(BG=1)), [])

    def test_physical_column_and_null_gates_preserved(self):
        row = self.source()
        del row["route_context"]
        self.assertIn("route_context", self.missing(row))
        for value in (None, float("nan")):
            self.assertIn("route_context", self.missing(self.source(route=value)))
        self.assertIn("route_context", self.missing(self.source(route=" ")))

    def test_every_other_required_field_keeps_original_gate(self):
        for field in _PREMARKET_SOURCE_FIELDS:
            if field == "route_context":
                continue
            for mode in ("absent", "empty", "null"):
                row = self.source(route="B2", B2=1)
                if mode == "absent":
                    del row[field]
                else:
                    row[field] = "" if mode == "empty" else None
                with self.subTest(field=field, mode=mode):
                    self.assertIn(field, self.missing(row))

    def test_nonblank_rows_equal_original_gate_and_callsite_is_bound(self):
        import ast
        for context in ("B1", "B2", "B3", "B1|B2", "none"):
            row = self.source(route=context, B2=1)
            old = [f for f in _PREMARKET_SOURCE_FIELDS
                   if f not in row or v192_selector._is_empty(row[f])]
            self.assertEqual(self.missing(row), old)
        tree = ast.parse(Path(v192_selector.__file__).read_text())
        oracle = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == "run_frozen_v192_oracle")
        self.assertTrue(any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                            and n.func.id == "_missing_premarket_source_fields"
                            for n in ast.walk(oracle)))
