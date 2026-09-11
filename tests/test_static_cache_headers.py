"""Static delivery keeps HTML revalidating so deploys never strand a cache."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.v35_api.app import create_app


DIST = Path(__file__).resolve().parents[1] / "apps" / "web" / "dist"


@pytest.mark.skipif(not DIST.is_dir(), reason="frontend dist is not built in this checkout")
def test_html_entry_points_revalidate_and_assets_keep_default_caching(tmp_path: Path) -> None:
    client = TestClient(create_app(data_root=tmp_path / "data"))

    index = client.get("/")
    assert index.status_code == 200
    assert index.headers["content-type"].startswith("text/html")
    assert index.headers.get("cache-control") == "no-cache"

    assets = sorted((DIST / "assets").glob("*.js"))
    assert assets, "expected built assets"
    asset = client.get(f"/assets/{assets[0].name}")
    assert asset.status_code == 200
    assert asset.headers.get("cache-control") != "no-cache"
