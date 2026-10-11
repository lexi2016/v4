from __future__ import annotations

import hashlib
import io
import json
import unittest
import tempfile
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd

from domains.preselection_materializer import (
    _artifact,
    build_expected_missing_pool,
    build_shared_hk_0_2_pool,
)
from infrastructure.preselection_pool_store import PreselectionPoolStore
from ops import materialize_scheduled_preselection as scheduled_preselection
from ops.materialize_scheduled_preselection import _formal_pool_gate
from shared_data import hk_0_2


class TestHKPartialRows(unittest.TestCase):
    def _tempdir(self):
        # Keep filesystem fixtures inside the isolated task tree; the owned
        # path guard intentionally rejects system temporary roots on macOS.
        return tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[4] / "receipts"
        )

    def test_score_keeps_available_rows_when_eligible_panel_is_under_500(self) -> None:
        eligible = {f"HK.{index:05d}" for index in range(10000, 10010)}
        frame = pd.DataFrame(
            [
                {
                    "trade_date_compact": "20261008",
                    "code_norm": code,
                    "raw_score": float(index),
                    "close": 10.0,
                    "pre_close": 9.0,
                    "pct_chg": 1.0,
                }
                for index, code in enumerate(sorted(eligible), start=1)
            ]
        )
        assets = hk_0_2.FrozenHK02Assets(
            root=Path("/tmp/hk02-partial"),
            panel_path=Path("/tmp/panel.parquet"),
            panel_manifest={},
            model_path=Path("/tmp/models.joblib"),
            model_manifest={"feature_columns": []},
            name_dictionary_path=None,
        )

        def fake_score(predict, _models, _feature_columns):
            out = predict.copy()
            out["score_prob_active"] = out["raw_score"]
            return out

        with (
            patch.object(hk_0_2, "load_frozen_hk_0_2_assets", return_value=assets),
            patch.object(pd, "read_parquet", return_value=frame),
            patch.object(hk_0_2, "_add_daily_features", side_effect=lambda value: value),
            patch.object(hk_0_2, "_add_proxy_labels", return_value=(frame, {})),
            patch.object(hk_0_2, "_add_proxy_memory", side_effect=lambda value, _proxy: value),
            patch.object(hk_0_2, "_load_models", return_value={}),
            patch.object(hk_0_2, "_score_with_strategies", side_effect=fake_score),
        ):
            scored = hk_0_2.score_frozen_hk_0_2(
                assets.root,
                signal_date="20261008",
                target_date="20261009",
                eligible_codes=eligible,
            )

        self.assertEqual(len(scored), 10)
        self.assertEqual([row["rank"] for row in scored], list(range(1, 11)))
        self.assertEqual(scored[0]["code_norm"], "HK.10009")

    def test_exact_hk_empty_placeholder_can_upgrade_to_verified_partial_rows(self) -> None:
        trade_date = "20261009"
        with self._tempdir() as temporary:
            store = PreselectionPoolStore(Path(temporary))
            missing = build_expected_missing_pool(
                trade_date,
                pool_id="hkconnect_d1_top100",
                display_name="港股通 0.2 D-1 Top100",
                market="HK",
                reason="HK_0_2_EXACT_INPUT_MISSING",
            )
            store.materialize(missing)
            artifact_sha = "a" * 64
            rows = [
                {
                    "code": f"HK.{index:05d}",
                    "symbol": f"HK.{index:05d}",
                    "market": "HK",
                    "signal_date": "20261008",
                    "target_date": trade_date,
                    "trade_date": trade_date,
                    "pool_rank": index,
                    "pool_score": 0.9 - index / 100,
                    "selected_strategy": "prob_active",
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
                for index in range(1, 4)
            ]
            partial = _artifact(
                trade_date=trade_date,
                pool_id="hkconnect_d1_top100",
                display_name="港股通 0.2 D-1 Top100",
                market="HK",
                status="PARTIAL_WITH_ROWS",
                producer_id="v3_shared_hk_0_2_consumer_v1",
                source_role="UPSTREAM_PRODUCER_ARTIFACT",
                source_path=f"runs/{trade_date}/HK_CONNECT_D1_TOP100_0_2/{trade_date}-hk-connect-d1-top100-0-2-abcdef123456/artifact.csv",
                source_sha256=artifact_sha,
                rows=rows,
                cannot_confirm=["HK_0_2_SIGNAL_ROWS_MISSING:HK.10004"],
            )
            partial.update(
                source_artifact_sha256=artifact_sha,
                source_run_id=f"{trade_date}-hk-connect-d1-top100-0-2-abcdef123456",
                source_row_count=3,
                signal_date="20261008",
                target_date=trade_date,
                stage_selection_eligible=True,
            )

            store.materialize(partial)
            snapshot = store.read_pool_snapshot(trade_date, "hkconnect_d1_top100")
            self.assertEqual(snapshot["artifact"]["status"], "PARTIAL_WITH_ROWS")
            self.assertEqual(snapshot["artifact"]["source_role"], "UPSTREAM_PRODUCER_ARTIFACT")
            self.assertEqual(len(snapshot["artifact"]["rows"]), 3)
            self.assertEqual(snapshot["artifact"]["cannot_confirm"], ["HK_0_2_SIGNAL_ROWS_MISSING:HK.10004"])
            self.assertIs(snapshot["artifact"]["production_allowed"], False)
            self.assertEqual(hashlib.sha256(b"").hexdigest(), missing["source_sha256"])
            revisions = list(
                (Path(temporary) / "preselection_revisions" / trade_date).glob("*.json")
            )
            archived_payloads = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in revisions
                if not path.name.endswith(".receipt.json")
            ]
            self.assertTrue(
                any(
                    payload.get("source_role") == "EXPECTED_MISSING" and not payload.get("rows")
                    for payload in archived_payloads
                )
            )

    def test_empty_or_unbound_hk_partial_cannot_upgrade_placeholder(self) -> None:
        trade_date = "20261009"
        with self._tempdir() as temporary:
            store = PreselectionPoolStore(Path(temporary))
            store.materialize(
                build_expected_missing_pool(
                    trade_date,
                    pool_id="hkconnect_d1_top100",
                    display_name="港股通 0.2 D-1 Top100",
                    market="HK",
                    reason="HK_0_2_EXACT_INPUT_MISSING",
                )
            )
            invalid = _artifact(
                trade_date=trade_date,
                pool_id="hkconnect_d1_top100",
                display_name="港股通 0.2 D-1 Top100",
                market="HK",
                status="PARTIAL_WITH_ROWS",
                producer_id="graph_expected_missing_v1",
                source_role="UPSTREAM_PRODUCER_ARTIFACT",
                source_path="",
                source_sha256="b" * 64,
                rows=[],
                cannot_confirm=["HK_0_2_SIGNAL_ROWS_MISSING"],
            )
            with self.assertRaises(ValueError):
                store.materialize(invalid)

    def test_producer_publishes_partial_rows_with_explicit_source_diagnostic(self) -> None:
        codes = ("HK.00001", "HK.00002")
        rows = []
        for index, code in enumerate(codes, start=1):
            row = {field: "" for field in hk_0_2._OUTPUT_FIELDS}
            row.update(
                trade_date="20261009",
                bar_time="17:30",
                rank=str(index),
                code=code,
                code_norm=code,
                ts_code=f"{code.removeprefix('HK.')}.HK_CONNECT",
                name=f"Name {index}",
                signal_date="20261008",
                target_date="20261009",
                selected_strategy="prob_active",
                weekly_tuning_selected_strategy="prob_active",
                production_allowed="False",
                score_prob_active=str(1.0 - index / 10),
                d1_freshness_status="PASS",
                cannot_confirm="",
            )
            rows.append(row)
        master_manifest = {"run_id": "hk-master-test", "artifact_sha256": "b" * 64}
        with self._tempdir() as temporary, patch.object(
            hk_0_2,
            "_load_verified_security_master",
            return_value=({code: {"name": f"Name {index}"} for index, code in enumerate(codes, 1)}, master_manifest),
        ):
            hk_0_2.publish_hk_0_2_rows(
                Path(temporary),
                signal_date="20261008",
                target_date="20261009",
                rows=rows,
                panel_sha256="c" * 64,
                partial_reasons=["HK_0_2_SIGNAL_ROW_MISSING:HK.00003"],
            )
            verified = hk_0_2.read_verified_hk_0_2_pool(
                Path(temporary),
                target_date="20261009",
                expected_signal_date="20261008",
            )

        self.assertEqual(verified.run.verification["status"], "CANNOT_CONFIRM")
        self.assertEqual(len(verified.rows), 2)
        self.assertEqual(verified.run.manifest["issues"], [])
        self.assertIs(verified.run.manifest["temporal_cutoff_safe"], True)
        self.assertEqual(
            verified.run.manifest["cannot_confirm"],
            [
                "HK_0_2_SIGNAL_ROW_MISSING:HK.00003",
                "HK_0_2_TOP100_ROWS_MISSING:98",
            ],
        )

    def test_verified_partial_projection_is_research_ready_without_formal_upgrade(self) -> None:
        raw_rows = [
            {
                "code_norm": f"HK.{index:05d}",
                "rank": index,
                "score_prob_active": 1.0 - index / 10,
                "signal_date": "20261008",
                "target_date": "20261009",
                "selected_strategy": "prob_active",
                "d1_freshness_status": "PASS",
                "name": f"Name {index}",
            }
            for index in range(1, 4)
        ]
        source_sha = "d" * 64
        source_run_id = "20261009-hk-connect-d1-top100-0-2-abcdef123456"
        source = SimpleNamespace(
            rows=tuple(raw_rows),
            run=SimpleNamespace(
                verification={
                    "status": "CANNOT_CONFIRM",
                    "artifact_relative": f"runs/20261009/HK_CONNECT_D1_TOP100_0_2/{source_run_id}/artifact.csv",
                    "artifact_sha256": source_sha,
                    "run_id": source_run_id,
                    "row_count": len(raw_rows),
                },
                receipt={
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                },
                manifest={
                    "cannot_confirm": ["HK_0_2_SIGNAL_ROW_MISSING:HK.00004"]
                },
            ),
        )
        artifact = build_shared_hk_0_2_pool(
            Path("/not-used"),
            trade_date="20261009",
            signal_date="20261008",
            reader=lambda *_args, **_kwargs: source,
        )
        gate = _formal_pool_gate(
            [
                {
                    "pool_id": "a_d1_premarket_pool",
                    "status": "V192_CANDIDATE_READY",
                    "rows": [{}],
                },
                artifact,
            ]
        )

        self.assertEqual(artifact["status"], "PARTIAL_WITH_ROWS")
        self.assertEqual(artifact["source_role"], "UPSTREAM_PRODUCER_ARTIFACT")
        self.assertEqual(len(artifact["rows"]), 3)
        self.assertEqual(gate["status"], "PARTIAL_WITH_ROWS")
        self.assertIs(gate["required"]["hkconnect_d1_top100"]["ready"], False)
        self.assertIs(gate["required"]["hkconnect_d1_top100"]["research_ready"], True)

        a_pool = {
            "pool_id": "a_d1_premarket_pool",
            "status": "V192_CANDIDATE_READY",
            "rows": [{}],
        }
        with self._tempdir() as temporary:
            output = io.StringIO()
            with (
                patch.object(scheduled_preselection, "build_scheduled_artifacts", return_value=[a_pool, artifact]),
                patch.object(scheduled_preselection, "materialize_preselection_date", return_value=[]),
                redirect_stdout(output),
            ):
                exit_code = scheduled_preselection.main(
                    [
                        "--trade-date", "20261009",
                        "--signal-date", "20261008",
                        "--input-root", temporary,
                        "--data-root", str(Path(temporary) / "store"),
                        "--shared-data-root", temporary,
                        "--shared-package-root", temporary,
                    ]
                )
        scheduler_payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(scheduler_payload["status"], "PARTIAL_WITH_ROWS")
        self.assertIs(scheduler_payload["production_allowed"], False)
        self.assertIs(scheduler_payload["buy_gate_updated"], False)
        self.assertIs(scheduler_payload["orders_sent"], False)

        empty_gate = _formal_pool_gate(
            [
                a_pool,
                {**artifact, "rows": [], "source_row_count": 0},
            ]
        )
        self.assertEqual(empty_gate["status"], "FAILED")


if __name__ == "__main__":
    unittest.main()
