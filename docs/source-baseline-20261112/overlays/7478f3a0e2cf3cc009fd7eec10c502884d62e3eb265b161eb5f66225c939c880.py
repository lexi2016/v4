from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from shared_data import hk_0_2
from shared_data.store import StoreError


class TestHK02MembershipFilter(unittest.TestCase):
    def test_score_filters_nonmember_before_top100_and_replaces_it(self) -> None:
        eligible = {f"HK.{index:05d}" for index in range(10000, 10500)}
        rows = [
            {
                "trade_date_compact": "20260827",
                "code_norm": "HK.03308",
                "raw_score": 999.0,
                "close": 10.0,
                "pre_close": 9.0,
                "pct_chg": 1.0,
            }
        ]
        rows.extend(
            {
                "trade_date_compact": "20260827",
                "code_norm": code,
                "raw_score": float(index),
                "close": 10.0,
                "pre_close": 9.0,
                "pct_chg": 1.0,
            }
            for index, code in enumerate(sorted(eligible), start=1)
        )
        frame = pd.DataFrame(rows)
        assets = hk_0_2.FrozenHK02Assets(
            root=Path("/tmp/hk02-test"),
            panel_path=Path("/tmp/panel.parquet"),
            panel_manifest={},
            model_path=Path("/tmp/models.joblib"),
            model_manifest={"feature_columns": []},
            name_dictionary_path=None,
        )

        def fake_score(predict, models, feature_columns):
            out = predict.copy()
            out["score_prob_active"] = out["raw_score"]
            return out

        with (
            patch.object(hk_0_2, "load_frozen_hk_0_2_assets", return_value=assets),
            patch.object(pd, "read_parquet", return_value=frame),
            patch.object(hk_0_2, "_add_daily_features", side_effect=lambda value: value),
            patch.object(hk_0_2, "_add_proxy_labels", return_value=(frame, {})),
            patch.object(hk_0_2, "_add_proxy_memory", side_effect=lambda value, proxy: value),
            patch.object(hk_0_2, "_load_models", return_value={}),
            patch.object(hk_0_2, "_score_with_strategies", side_effect=fake_score),
        ):
            scored = hk_0_2.score_frozen_hk_0_2(
                assets.root,
                signal_date="20260827",
                target_date="20260828",
                eligible_codes=eligible,
            )

        self.assertEqual(len(scored), 100)
        self.assertEqual([row["rank"] for row in scored], list(range(1, 101)))
        self.assertNotIn("HK.03308", {row["code_norm"] for row in scored})
        self.assertEqual(scored[-1]["code_norm"], "HK.10400")

    def test_materializer_uses_verified_membership_and_fails_closed_on_eligible_name(self) -> None:
        security_master = {"HK.10000": {"name": ""}}
        captured: set[str] = set()

        def fake_score(*args, eligible_codes=None, **kwargs):
            captured.update(eligible_codes or ())
            return [{"code_norm": "HK.10000", "name": ""}]

        assets = hk_0_2.FrozenHK02Assets(
            root=Path("/tmp/hk02-test"),
            panel_path=Path("/tmp/panel.parquet"),
            panel_manifest={"panel_sha256": "panel"},
            model_path=Path("/tmp/models.joblib"),
            model_manifest={},
            name_dictionary_path=None,
        )
        with (
            patch.object(hk_0_2, "load_frozen_hk_0_2_assets", return_value=assets),
            patch.object(
                hk_0_2,
                "_load_verified_security_master",
                return_value=(security_master, {"run_id": "run", "artifact_sha256": "a" * 64}),
            ),
            patch.object(hk_0_2, "score_frozen_hk_0_2", side_effect=fake_score),
        ):
            with self.assertRaisesRegex(StoreError, "HK security master name missing: HK.10000"):
                hk_0_2.materialize_frozen_hk_0_2(
                    Path(tempfile.mkdtemp()),
                    assets.root,
                    signal_date="20260827",
                    target_date="20260828",
                )

        self.assertEqual(captured, set(security_master))


if __name__ == "__main__":
    unittest.main()
