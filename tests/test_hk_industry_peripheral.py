from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from infrastructure.data_store import _sha256
from infrastructure.http_transport import FetchResult
from infrastructure.research_peripheral_store import (
    HK_INDUSTRY_SOURCE,
    ResearchPeripheralStore,
)
from ops.materialize_research_peripherals import (
    _capture_hk_industry_response,
    _hk_industry_url,
    build_hk_industry_peripheral_payload,
    seed_hk_industry_response_cache,
)
from v4.manager_workbench.inputs.source_bindings import hk_industry_classification


CAPTURED_AT = "2026-10-14T01:33:13.850926Z"
MEMBERSHIP_CODES = ["HK.00300", "HK.00700", "HK.00941"]
MEMBERSHIP_SHA = "a" * 64
MEMBERSHIP_OWNER = "v35_dispatcher.research_panel_daily_hk"


def _provider_body(code: str, name: str, industry: str) -> bytes:
    provider_code = f"{code}.HK"
    payload = {
        "version": "test-version",
        "result": {
            "pages": 1,
            "data": [{
                "SECUCODE": provider_code,
                "SECURITY_CODE": code,
                "ORG_NAME": name,
                "BELONG_INDUSTRY": industry,
            }],
            "count": 1,
        },
        "success": True,
        "message": "ok",
        "code": 0,
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _membership() -> dict:
    refs = [{
        "source_local_path": "/scope/root",
        "relative": "universes/20261013/HK_CONNECT_FULL_MARKET.json",
        "sha256": MEMBERSHIP_SHA,
    }]
    return {
        "codes": MEMBERSHIP_CODES,
        "scope_codes_sha256": _sha256(MEMBERSHIP_CODES),
        "codes_sha256": _sha256({"market": "HK_CONNECT", "codes": MEMBERSHIP_CODES}),
        "membership_artifact_sha256": MEMBERSHIP_SHA,
        "membership_owner": MEMBERSHIP_OWNER,
        "membership_relative": refs[0]["relative"],
        "membership_source_root": "/scope/root",
        "membership_available_at": "2026-10-01T00:00:00Z",
        "membership_effective_from": "20261001",
        "membership_effective_through": "20261031",
        "membership_source_refs": refs,
    }


def _outcome(symbol: str, raw: bytes) -> dict:
    digest = hashlib.sha256(raw).hexdigest()
    return {
        "symbol": symbol,
        "provider_code": f"{symbol[3:]}.HK",
        "request_url": _hk_industry_url(symbol),
        "http_status": 200,
        "transport_receipt": {"http_status": 200, "error": None, "proxy_used": True, "fallback_used": False, "elapsed_ms": 8},
        "captured_at": CAPTURED_AT,
        "source_asof": None,
        "source_asof_status": "UNKNOWN",
        "raw_response_sha256": digest,
        "raw_body_base64": base64.b64encode(raw).decode("ascii"),
        "error_code": None,
        "error_detail": None,
        "cache_status": "MISS",
    }


def _member_pin() -> dict:
    refs = _membership()["membership_source_refs"]
    return {
        "owner": MEMBERSHIP_OWNER,
        "artifact_relative": refs[0]["relative"],
        "artifact_sha256": MEMBERSHIP_SHA,
        "projection": {
            "codes": MEMBERSHIP_CODES,
            "available_at": "2026-10-01T00:00:00Z",
            "effective_from": "20261001",
            "effective_to": "20261031",
        },
        "checked_files": refs,
    }


def test_hk_industry_store_and_v4_consumer_verify_owner_manifest_and_receipt(tmp_path: Path) -> None:
    raw = _provider_body("00300", "美的集团股份有限公司", "家庭电器及用品")
    payload = build_hk_industry_peripheral_payload(
        trade_date="20261013",
        membership=_membership(),
        requested_codes=MEMBERSHIP_CODES,
        outcomes=[
            _outcome("HK.00300", raw),
            _outcome("HK.00700", _provider_body("00700", "腾讯控股有限公司", "互联网服务")),
            _outcome("HK.00941", _provider_body("00941", "中国移动有限公司", "电讯服务")),
        ],
        fetched_at="2026-10-14T01:34:00Z",
    )
    store = ResearchPeripheralStore(tmp_path)
    published = store.publish(payload)
    loaded = store.read_exact("20261013", HK_INDUSTRY_SOURCE)
    assert loaded == payload
    assert published["payload_sha256"] == _sha256(loaded)

    context = SimpleNamespace(
        target_date="20261013",
        cutoff="2026-10-14T02:00:00Z",
        scope_refs={"owner_bindings": {"membership": _member_pin()}},
    )
    binding = hk_industry_classification(
        SimpleNamespace(shared_root=tmp_path, source_bindings={}), context
    )
    assert binding["status"] == "READY"
    assert binding["artifact"]["source_asof"] is None
    assert binding["artifact"]["source_asof_status"] == "UNKNOWN"
    assert binding["artifact"]["rows"][0]["mapping_type"] == "EXACT_PROVIDER_INDUSTRY"
    assert len(binding["artifact"]["rows"]) == 3
    assert {item["relative"] for item in binding["checked_files"]} >= {
        "research/peripherals/manifest.json",
        "research/peripherals/20261013/hk_industry_classification.json",
        "receipts/research/peripherals/20261013/hk_industry_classification.json",
    }

    receipt_path = tmp_path / published["receipt_path"]
    receipt_path.write_text("{}", encoding="utf-8")
    broken = hk_industry_classification(
        SimpleNamespace(shared_root=tmp_path, source_bindings={}), context
    )
    assert broken["status"] == "UNAVAILABLE"
    assert "manifest or receipt mismatch" in broken["gap"]


def test_hk_industry_partial_failure_is_preserved_per_symbol(tmp_path: Path) -> None:
    raw = _provider_body("00300", "美的集团股份有限公司", "家庭电器及用品")
    outcomes = [
        _outcome("HK.00300", raw),
        {
            "symbol": "HK.00700",
            "request_url": _hk_industry_url("HK.00700"),
            "http_status": 429,
            "captured_at": CAPTURED_AT,
            "error_code": "HTTP_STATUS_429",
            "error_detail": "HTTP 429",
            "cache_status": "HIT",
        },
        _outcome("HK.00941", _provider_body("00941", "中国移动有限公司", "电讯服务")),
    ]
    payload = build_hk_industry_peripheral_payload(
        trade_date="20261013", membership=_membership(),
        requested_codes=MEMBERSHIP_CODES, outcomes=outcomes,
    )
    assert payload["status"] == "PARTIAL"
    assert payload["failures"][0]["error_code"] == "HTTP_STATUS_429"
    assert payload["cannot_confirm"] == ["HK.00700:HTTP_STATUS_429"]
    ResearchPeripheralStore(tmp_path).publish(payload)


def test_hk_industry_seed_cache_hit_verifies_sha_without_network(tmp_path: Path) -> None:
    raw_path = tmp_path / "midea.json"
    raw_path.write_bytes(_provider_body("00300", "美的集团股份有限公司", "家庭电器及用品"))
    digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    seed_hk_industry_response_cache(
        cache_root=tmp_path / "cache", trade_date="20261013",
        symbol="HK.00300", raw_response_path=raw_path,
        captured_at=CAPTURED_AT, expected_sha256=digest,
    )

    class NoNetwork:
        def fetch(self, *args, **kwargs):
            raise AssertionError("a verified cache hit must not request the provider")

    cached = _capture_hk_industry_response(
        trade_date="20261013", symbol="HK.00300", cache_root=tmp_path / "cache",
        transport=NoNetwork(), timeout=1,
    )
    assert cached["cache_status"] == "HIT"
    assert cached["raw_response_sha256"] == digest

    cache_path = tmp_path / "cache" / "20261013" / "HK.00300.json"
    value = json.loads(cache_path.read_text(encoding="utf-8"))
    value["raw_body_base64"] = base64.b64encode(b"tampered").decode("ascii")
    cache_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="HK_INDUSTRY_CACHE_SHA_MISMATCH"):
        _capture_hk_industry_response(
            trade_date="20261013", symbol="HK.00300", cache_root=tmp_path / "cache",
            transport=NoNetwork(), timeout=1,
        )
