from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from ops import run_stage_center_nodes as nodes
from stage_center import runner as stage_runner
from stage_center.acquisition import StageUniverseBinding


TRADE_DATE = "20261009"
STAGE_ID = "STAGE_0935_0940"
NOW = datetime(2026, 10, 9, 9, 42, tzinfo=ZoneInfo("Asia/Shanghai"))


def _receipt() -> dict[str, object]:
    return {
        "schema_version": "stage_center.runner.receipt.v1",
        "trade_date": TRADE_DATE,
        "stage_id": STAGE_ID,
        "node_id": STAGE_ID,
        "status": "CANNOT_CONFIRM",
        "first_failed_layer": "EXACT_SELECTION_INPUT_BINDING",
        "node_attempt_count": 3,
        "retry_exhausted": True,
        "dispatch_mode": "RECOVERY",
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "markets": {
            "HK_CONNECT": {
                "status": "CANNOT_CONFIRM",
                "selected_rows": 0,
                "cannot_confirm": ["exact-date input missing: hkconnect_d1_top100.json"],
            }
        },
    }


def _partial_binding(*, codes: tuple[str, ...]) -> StageUniverseBinding:
    digest = "a" * 64
    return StageUniverseBinding.ready(
        market="HK_CONNECT",
        trade_date=TRADE_DATE,
        role="HK_CONNECT_D1_TOP100",
        codes=codes,
        source_run_id=f"hk-d1-{digest[:16]}",
        sha256=digest,
        evidence=(
            "hk_d1_status=PARTIAL_WITH_ROWS",
            "hk_d1_membership=available_source_rows",
        ),
    )


class TestHKPartialDependencyRearm(unittest.TestCase):
    def test_due_stage_rearms_once_when_partial_exact_d1_appears(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[4] / "receipts"
        ) as temporary:
            root = Path(temporary)
            config = {
                "receipt_root": str(root / "receipts"),
                "hk_d1_root": str(root / "preselection_pools"),
                "node_max_attempts": 3,
                "node_retry_backoff_seconds": 60,
                "safety": {
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                },
            }
            receipt_path = nodes._receipt_path(config, TRADE_DATE, STAGE_ID)
            receipt_path.parent.mkdir(parents=True)
            receipt_path.write_text(json.dumps(_receipt()), encoding="utf-8")

            binding = _partial_binding(
                codes=("HK.00001", "HK.00002", "HK.00003")
            )
            calls: list[str] = []
            decision = SimpleNamespace(
                stage_id=STAGE_ID,
                status="DUE",
                trade_date=TRADE_DATE,
                scheduled_at=NOW,
            )
            runner = SimpleNamespace(
                config=SimpleNamespace(receipt_root=root / "receipts"),
                due_decisions=lambda *_args, **_kwargs: [decision],
                _receipt_path=lambda trade_date, stage_id: nodes._receipt_path(
                    config, trade_date, stage_id
                ),
            )

            def write_receipt(value, trade_date, stage_id):
                persisted = {
                    **value,
                    "trade_date": trade_date,
                    "stage_id": stage_id,
                    "node_id": stage_id,
                    "schema_version": "stage_center.runner.receipt.v1",
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }
                nodes._receipt_path(config, trade_date, stage_id).write_text(
                    json.dumps(persisted), encoding="utf-8"
                )
                return persisted

            def run_one(_decision):
                calls.append(STAGE_ID)
                return {
                    "status": "PARTIAL_WITH_ROWS",
                    "write_performed": True,
                    "markets": {
                        "HK_CONNECT": {
                            "status": "PARTIAL_WITH_ROWS",
                            "selected_rows": 2,
                            "cannot_confirm": ["HK_0_2_SIGNAL_ROWS_MISSING:HK.00004"],
                        }
                    },
                    "production_allowed": False,
                    "buy_gate_updated": False,
                    "orders_sent": False,
                }

            runner._write_receipt = write_receipt
            runner._run_one = run_one
            with (
                patch.object(nodes, "_calendar_gate", return_value={"status": "ELIGIBLE"}),
                patch.object(nodes, "_rearm_wall_now", return_value=NOW),
                patch.object(stage_runner, "_build_hk_d1_binding", return_value=binding),
                patch.object(nodes._deadline, "checkpoint", return_value=None),
                patch.object(nodes._deadline, "due", return_value=None),
                patch.object(nodes._deadline, "event", return_value=None),
                patch.object(
                    nodes._deadline,
                    "complete_receipt",
                    side_effect=lambda _path, value, rewrite: value,
                ),
            ):
                result = nodes._dispatch_stage(
                    config,
                    TRADE_DATE,
                    STAGE_ID,
                    NOW,
                    mode="RECOVERY",
                    runner=runner,
                )

                self.assertEqual(result["status"], "PARTIAL_WITH_ROWS")
                self.assertEqual(result["node_attempt_count"], 4)
                self.assertEqual(result["dependency_rearm_count"], 1)
                self.assertEqual(calls, [STAGE_ID])
                self.assertTrue(receipt_path.parent.joinpath("dependency_rearm.json").is_file())
                self.assertIsNone(
                    nodes._exact_hk_d1_dependency_rearm(
                        config, TRADE_DATE, _receipt(), NOW
                    )
                )
                for flag in ("production_allowed", "buy_gate_updated", "orders_sent"):
                    self.assertIs(result[flag], False)

    def test_existing_exact_100_binding_keeps_rearm_support(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[4] / "receipts"
        ) as temporary:
            root = Path(temporary)
            config = {
                "receipt_root": str(root / "receipts"),
                "hk_d1_root": str(root / "preselection_pools"),
                "node_max_attempts": 3,
            }
            digest = "b" * 64
            strict_binding = StageUniverseBinding.ready(
                market="HK_CONNECT",
                trade_date=TRADE_DATE,
                role="HK_CONNECT_D1_TOP100",
                codes=tuple(f"HK.{index:05d}" for index in range(1, 101)),
                source_run_id=f"hk-d1-{digest[:16]}",
                sha256=digest,
                evidence=(
                    "hk_d1_status=STRICT_0_2_READY",
                    "hk_d1_membership=exact_date_top100",
                ),
            )
            with patch.object(nodes, "_rearm_wall_now", return_value=NOW), patch.object(
                stage_runner, "_build_hk_d1_binding", return_value=strict_binding
            ):
                result = nodes._exact_hk_d1_dependency_rearm(
                    config, TRADE_DATE, _receipt(), NOW
                )
            self.assertEqual(result["dependency_rearm_count"], 1)
            self.assertEqual(result["dependency_rearm_source_sha256"], digest)

    def test_partial_binding_requires_rows_and_both_provenance_markers(self) -> None:
        with tempfile.TemporaryDirectory(
            dir=Path(__file__).resolve().parents[4] / "receipts"
        ) as temporary:
            root = Path(temporary)
            config = {
                "receipt_root": str(root / "receipts"),
                "hk_d1_root": str(root / "preselection_pools"),
                "node_max_attempts": 3,
            }
            receipt = _receipt()
            malformed = StageUniverseBinding.ready(
                market="HK_CONNECT",
                trade_date=TRADE_DATE,
                role="HK_CONNECT_D1_TOP100",
                codes=("HK.00001",),
                source_run_id="hk-d1-" + "a" * 16,
                sha256="a" * 64,
                evidence=("hk_d1_status=PARTIAL_WITH_ROWS",),
            )
            oversized = _partial_binding(
                codes=tuple(f"HK.{index:05d}" for index in range(1, 102))
            )
            duplicate = _partial_binding(codes=("HK.00001", "HK.00001"))
            with patch.object(nodes, "_rearm_wall_now", return_value=NOW):
                for binding in (malformed, oversized, duplicate):
                    with patch.object(stage_runner, "_build_hk_d1_binding", return_value=binding):
                        self.assertIsNone(
                            nodes._exact_hk_d1_dependency_rearm(
                                config, TRADE_DATE, receipt, NOW
                            )
                        )


if __name__ == "__main__":
    unittest.main()
