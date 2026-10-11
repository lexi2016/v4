from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path

from stage_center import runner as stage_runner
from stage_center.acquisition import SourceResult
from stage_center.contracts import SAFETY_FLAGS
from infrastructure.preselection_pool_store import PreselectionPoolStore


TRADE_DATE = "20261009"
SIGNAL_DATE = "20261008"
CODES = ("HK.00001", "HK.00002", "HK.00003")
MISSING_CODE = "HK.00004"


def _temporary_root():
    from tempfile import TemporaryDirectory

    return TemporaryDirectory(dir=Path(__file__).resolve().parents[4] / "receipts")


def _write_partial_d1(data_root: Path, *, trade_date: str = TRADE_DATE) -> Path:
    signal_date = "20261008" if trade_date == TRADE_DATE else "20261009"
    rows = [
        {
            "code": code,
            "symbol": code,
            "market": "HK",
            "signal_date": signal_date,
            "target_date": trade_date,
            "trade_date": trade_date,
            "pool_rank": index,
            "pool_score": 1.0 - index / 10,
            "selected_strategy": "prob_active",
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
        }
        for index, code in enumerate(CODES, start=1)
    ]
    payload = {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": trade_date,
        "pool_id": "hkconnect_d1_top100",
        "display_name": "港股通 0.2 D-1 Top100",
        "market": "HK",
        "status": "PARTIAL_WITH_ROWS",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "UPSTREAM_PRODUCER_ARTIFACT",
        "source_path": f"runs/{trade_date}/HK_CONNECT_D1_TOP100_0_2/{trade_date}-hk-connect-d1-top100-0-2-abcdef123456/artifact.csv",
        "source_sha256": "a" * 64,
        "source_artifact_sha256": "a" * 64,
        "source_run_id": f"{trade_date}-hk-connect-d1-top100-0-2-abcdef123456",
        "source_row_count": len(rows),
        "signal_date": signal_date,
        "target_date": trade_date,
        "stage_selection_eligible": True,
        "rows": rows,
        "cannot_confirm": [f"HK_0_2_SIGNAL_ROWS_MISSING:{MISSING_CODE}"],
        **SAFETY_FLAGS,
    }
    PreselectionPoolStore(data_root).materialize(payload)
    path = data_root / "preselection_pools" / trade_date / "hkconnect_d1_top100.json"
    return path


class TestHKPartialRows(unittest.TestCase):
    def test_partial_d1_binds_only_available_codes_with_partial_evidence(self) -> None:
        with _temporary_root() as temporary:
            data_root = Path(temporary)
            root = data_root / "preselection_pools"
            path = _write_partial_d1(data_root)
            validated_path, digest = stage_runner._validate_hk_d1(root, TRADE_DATE)
            codes, code_digest = stage_runner._hk_selection_codes(root, TRADE_DATE)
            binding = stage_runner._build_hk_d1_binding(root, TRADE_DATE)

            self.assertEqual(validated_path, path)
            self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(code_digest, digest)
            self.assertEqual(codes, set(CODES))
            self.assertEqual(set(binding.codes), set(CODES))
            self.assertIn("hk_d1_status=PARTIAL_WITH_ROWS", binding.evidence)
            self.assertIn("hk_d1_membership=available_source_rows", binding.evidence)
            self.assertNotIn("hk_d1_membership=exact_date_top100", binding.evidence)

    def test_hk_authority_does_not_label_partial_d1_as_strict(self) -> None:
        with _temporary_root() as temporary:
            data_root = Path(temporary)
            root = data_root / "preselection_pools"
            _write_partial_d1(data_root)
            source = SourceResult(
                "fixture",
                "PARTIAL_WITH_ROWS",
                rows=({"code": CODES[0], "name": "source name"},),
                requested_rows=4,
                missing_symbols=(MISSING_CODE,),
            )
            enriched = stage_runner._attach_hk_authority(
                source,
                d1_root=root,
                second_root=None,
                preselection_source_root=None,
                trade_date=TRADE_DATE,
                stage_id="STAGE_0930_0935",
            )

            self.assertEqual(enriched.status, "PARTIAL_WITH_ROWS")
            self.assertIn("hk_d1_status=PARTIAL_WITH_ROWS", enriched.source_evidence)
            self.assertIn("hk_d1_membership=available_source_rows", enriched.source_evidence)
            self.assertFalse(any("STRICT_0_2_READY" in item for item in enriched.source_evidence))

    def test_other_target_date_with_same_partial_contract_is_supported(self) -> None:
        other_date = "20261012"
        with _temporary_root() as temporary:
            data_root = Path(temporary)
            root = data_root / "preselection_pools"
            _write_partial_d1(data_root, trade_date=other_date)
            _path, _digest = stage_runner._validate_hk_d1(root, other_date)
            codes, _codes_sha = stage_runner._hk_selection_codes(root, other_date)
            self.assertEqual(codes, set(CODES))


if __name__ == "__main__":
    unittest.main()
