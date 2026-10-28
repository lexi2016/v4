from __future__ import annotations

import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from domains.preselection_materializer import build_shared_hk_0_2_pool


def _legacy_pool():
    rows = [
        {
            "code_norm": f"HK.{rank:05d}",
            "name": f"Name {rank}",
            "rank": rank,
            "score_prob_active": 1.0 - rank / 1000,
            "signal_date": "20260924",
            "target_date": "20260925",
            "selected_strategy": "prob_active",
            "d1_freshness_status": "PASS",
        }
        for rank in range(1, 101)
    ]
    verification = {
        "run_id": "legacy-run",
        "artifact_relative": "runs/20260925/pool/artifact.csv",
        "artifact_sha256": "a" * 64,
        "manifest_sha256": "b" * 64,
        "receipt_sha256": "c" * 64,
        "row_count": 100,
    }
    run = SimpleNamespace(
        verification=verification,
        receipt={"production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
        manifest={"provenance": {}},
    )
    return SimpleNamespace(rows=rows, run=run)


def test_default_consumer_keeps_legacy_reader_signature() -> None:
    calls = []

    def reader(root, **kwargs):
        calls.append((Path(root), dict(kwargs)))
        return _legacy_pool()

    result = build_shared_hk_0_2_pool(
        Path("/tmp/read-only-source"),
        trade_date="20260925",
        signal_date="20260924",
        reader=reader,
    )

    assert len(result["rows"]) == 100
    assert calls == [
        (
            Path("/tmp/read-only-source"),
            {"target_date": "20260925", "expected_signal_date": "20260924"},
        )
    ]


@pytest.mark.skipif(
    not os.environ.get("HK_0_2_CONSUMER_CANARY_STORE")
    or not os.environ.get("HK_0_2_CONSUMER_CANARY_SHARED_PACKAGE_ROOT"),
    reason="requires the verified 20260925 HK 0.2 r4 source run",
)
def test_explicit_optin_projects_verified_supplement_and_default_rejects_it() -> None:
    shared_root = Path(os.environ["HK_0_2_CONSUMER_CANARY_STORE"])
    shared_package_root = Path(os.environ["HK_0_2_CONSUMER_CANARY_SHARED_PACKAGE_ROOT"])
    kwargs = {
        "trade_date": "20260925",
        "signal_date": "20260924",
        "shared_package_root": shared_package_root,
    }

    with pytest.raises(Exception, match="HK 0.2 research name supplement opt-in mismatch"):
        build_shared_hk_0_2_pool(shared_root, **kwargs)

    result = build_shared_hk_0_2_pool(
        shared_root,
        research_name_supplement=True,
        **kwargs,
    )
    raw_root = shared_root / "runs" / "20260925" / "HK_CONNECT_D1_TOP100_0_2"
    run_dir = next(raw_root.iterdir())
    source_receipt_path = run_dir / "receipt.json"
    source_receipt = json.loads(source_receipt_path.read_text(encoding="utf-8"))
    additions = source_receipt["research_name_supplement"]["added_names"]
    by_code = {row["symbol"]: row for row in result["rows"]}

    assert result["status"] == "STRICT_0_2_READY"
    assert result["source_run_id"] == source_receipt["run_id"]
    assert result["source_sha256"] == source_receipt["artifact_sha256"]
    assert result["source_manifest_sha256"] == source_receipt["manifest_sha256"]
    assert len(result["rows"]) == 100
    assert len({row["symbol"] for row in result["rows"]}) == 100
    assert all(
        by_code[f"HK.{addition['code'][3:]}"]["stock_name"] == addition["name"]
        for addition in additions
    )
    assert result["production_allowed"] is False
    assert result["buy_gate_updated"] is False
    assert result["orders_sent"] is False
