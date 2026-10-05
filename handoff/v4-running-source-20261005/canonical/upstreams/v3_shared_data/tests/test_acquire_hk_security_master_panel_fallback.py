import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as parquet

from scripts.acquire_hk_security_master import ensure_hk_security_master


def test_security_master_uses_exact_date_hk_panel_when_universe_manifest_is_missing(
    tmp_path: Path,
) -> None:
    asset_root = tmp_path / "assets" / "hk_0_2"
    panel_dir = asset_root / "panels" / "20260817-test"
    panel_dir.mkdir(parents=True)
    panel_path = panel_dir / "hkconnect_vipdoc_daily_panel.parquet"
    parquet.write_table(
        pa.table(
            {
                "trade_date_compact": ["20260817"] * 500,
                "code_norm": [f"HK.{index:05d}" for index in range(1, 501)],
            }
        ),
        panel_path,
    )
    manifest_path = panel_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "panel_max_date": "20260817",
                "panel_relative": "panels/20260817-test/hkconnect_vipdoc_daily_panel.parquet",
                "panel_code_count": 500,
                "through_date_code_count": 500,
            }
        ),
        encoding="utf-8",
    )
    (asset_root / "panel_latest.json").write_text(
        json.dumps({"manifest_relative": "panels/20260817-test/manifest.json"}),
        encoding="utf-8",
    )
    observed: list[str] = []

    def collector(_python_path: Path, codes: list[str]) -> list[dict[str, object]]:
        observed.extend(codes)
        return [
            {
                "code": code,
                "name": f"name-{code}",
                "outstanding_shares": 1,
                "circular_market_val": 1,
                "listing_date": "2020-01-01",
            }
            for code in codes
        ]

    result = ensure_hk_security_master(
        tmp_path,
        "20260817",
        tmp_path / "python",
        collector=collector,
    )

    assert result["ok"] is True
    assert result["status"] == "READY"
    assert result["row_count"] == 500
    assert observed[0] == "HK.00001"
    assert observed[-1] == "HK.00500"
    assert len(observed) == 500
