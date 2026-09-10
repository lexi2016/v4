from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from shared_data.hashing import sha256_file, sha256_json
from shared_data.store import StoreError
from shared_data.v192_selector import (
    CANONICAL_FORMULA_SOURCE,
    DEFAULT_ORACLE_PATHS,
    FROZEN_ORACLE_SHA256S,
    _PREMARKET_SOURCE_FIELDS,
    V192_ENTRY_FIELDS,
    V192_LEGACY_ROLE,
    V192_PREVIOUS_ROLE,
    V192_RANK_BOUNDARY,
    V192_ROLE,
    _read_selector_panel_source_rows,
    publish_v192_rows,
    read_verified_v192_pool,
    resolve_default_oracle_paths,
    run_frozen_v192_oracle,
    verify_oracle_sources,
)


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

        modules = {
            "v3sd_v192_feature_oracle": FakeFeature,
            "v3sd_v192_score_oracle": FakeScorer,
            "v3sd_v192_role_oracle": FakeRoles,
        }
        fake_paths = {
            "feature_vector": self.tmp / "feature.py",
            "score_v19_multihead": self.tmp / "score.py",
            "fmla04_role": self.tmp / "roles.py",
        }
        with patch(
            "shared_data.v192_selector.verify_oracle_sources",
            return_value=FROZEN_ORACLE_SHA256S,
        ), patch(
            "shared_data.v192_selector._load_module",
            side_effect=lambda name, _path: modules[name],
        ):
            output = run_frozen_v192_oracle(
                panel,
                signal_date,
                oracle_paths=fake_paths,
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

        modules = {
            "v3sd_v192_feature_oracle": FakeFeature,
            "v3sd_v192_score_oracle": FakeScorer,
            "v3sd_v192_role_oracle": FakeRoles,
        }
        fake_paths = {
            "feature_vector": self.tmp / "feature.py",
            "score_v19_multihead": self.tmp / "score.py",
            "fmla04_role": self.tmp / "roles.py",
        }
        with patch(
            "shared_data.v192_selector.verify_oracle_sources",
            return_value=FROZEN_ORACLE_SHA256S,
        ), patch(
            "shared_data.v192_selector._load_module",
            side_effect=lambda name, _path: modules[name],
        ):
            with self.assertRaisesRegex(StoreError, "selector panel source field missing"):
                run_frozen_v192_oracle(
                    panel,
                    signal_date,
                    oracle_paths=fake_paths,
                )

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

    def test_real_frozen_oracle_paths_match_sha_contract(self) -> None:
        self.assertTrue(all(path.is_file() for path in DEFAULT_ORACLE_PATHS.values()))
        self.assertEqual(verify_oracle_sources(), FROZEN_ORACLE_SHA256S)

    def test_mac_default_oracle_paths_resolve_from_learning_root(self) -> None:
        paths = resolve_default_oracle_paths(
            platform="darwin", home=Path("/Users/lexi")
        )
        expected_root = Path("/Users/lexi/Desktop/学习/牛股学习/A股研究")
        self.assertEqual(
            paths,
            {
                "feature_vector": expected_root
                / "formula_backtests"
                / "v192_transparent_backtest_20260730"
                / "run_v192_transparent_backtest_20260730.py",
                "score_v19_multihead": expected_root
                / "_legacy_research_review"
                / "99_model_discovery_experiments"
                / "bull_agent_self_iteration_workbench_20260514"
                / "small_test_multihead_vs_v19_20260516"
                / "run_small_test_multihead_vs_v19_20260516.py",
                "fmla04_role": expected_root
                / "_legacy_research_review"
                / "99_model_discovery_experiments"
                / "bull_agent_self_iteration_workbench_20260514"
                / "fmla04_return_driven_self_iteration_20260518"
                / "run_fmla04_return_driven_self_iteration_20260518.py",
            },
        )

    def test_windows_default_oracle_paths_keep_original_contract(self) -> None:
        paths = resolve_default_oracle_paths(platform="win32", home=Path("/Users/lexi"))
        self.assertEqual(
            str(paths["feature_vector"]),
            r"C:\Users\huang\Desktop\学习\牛股学习\A股研究\formula_backtests\v192_transparent_backtest_20260730\run_v192_transparent_backtest_20260730.py",
        )
        self.assertEqual(
            str(paths["score_v19_multihead"]),
            r"C:\Users\huang\Desktop\学习\牛股学习\A股研究\_legacy_research_review\99_model_discovery_experiments\bull_agent_self_iteration_workbench_20260514\small_test_multihead_vs_v19_20260516\run_small_test_multihead_vs_v19_20260516.py",
        )
        self.assertEqual(
            str(paths["fmla04_role"]),
            r"C:\Users\huang\Desktop\学习\牛股学习\A股研究\_legacy_research_review\99_model_discovery_experiments\bull_agent_self_iteration_workbench_20260514\fmla04_return_driven_self_iteration_20260518\run_fmla04_return_driven_self_iteration_20260518.py",
        )

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
