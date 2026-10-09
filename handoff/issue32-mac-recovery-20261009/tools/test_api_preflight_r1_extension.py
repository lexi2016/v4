#!/usr/bin/env python3
"""Target regression for the pinned additive R1 analysis extension.

Reads the active API's three historical-product endpoints once, keeps their
bytes only in memory, then checks both the accepted exact extension and a
rejected unlisted extension against the unchanged R2 baseline.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path("/Users/lexi/Desktop/学习/agents调试/V4_ISSUE32_MAC_20261009")
PUBLISHER = ROOT / "tools/api_only_cutover_issue32_r4.py"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def main() -> None:
    spec = importlib.util.spec_from_file_location("issue32_api_publisher", PUBLISHER)
    if spec is None or spec.loader is None:
        raise RuntimeError("publisher import unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    baseline = module._load_product_baseline()
    expected_rows = baseline["rows"]
    cached: dict[str, tuple[int, bytes]] = {}
    for name in ("current_analysis", "legacy_analysis", "current_workspace"):
        path = expected_rows[name]["path"]
        status, raw = module._http_get(path)
        if status != 200:
            raise AssertionError(f"active GET failed for {name}: HTTP {status}")
        cached[path] = (status, raw)

    current_expected = expected_rows["current_analysis"]
    current_path = current_expected["path"]
    current_status, current_raw = cached[current_path]
    current_payload = module._json_loads(current_raw, "CURRENT_ANALYSIS_REGRESSION")
    extension = current_payload.get("consumption_validation")
    stripped, extension_count = module._strip_top_level_json_member(current_raw, "consumption_validation")
    if extension_count != 1:
        raise AssertionError("expected exactly one top-level consumption_validation extension")
    if sha(stripped) != current_expected.get("response_sha256"):
        raise AssertionError("stripping the additive extension does not reproduce the pinned R2 response")
    product_sha = current_expected["analysis"]["product_sha256"]
    accepted = module._validate_consumption_validation(
        "current_analysis", extension, current_expected, product_sha)

    malicious = dict(extension)
    malicious["unlisted_extension"] = "must be rejected"
    try:
        module._validate_consumption_validation(
            "current_analysis", malicious, current_expected, product_sha)
    except ValueError as exc:
        rejection = str(exc)
        if rejection != "HISTORICAL_ANALYSIS_CONSUMPTION_VALIDATION_SCHEMA_MISMATCH:current_analysis":
            raise
    else:
        raise AssertionError("an unlisted extension field was accepted")

    module._http_get = lambda path: cached[path]
    product_readback = module._verify_historical_product_readback(
        allow_r1_consumption_validation=True)
    if product_readback.get("status") != "HISTORICAL_ANALYSIS_PRODUCTS_VERIFIED_WORKSPACE_CANNOT_CONFIRM":
        raise AssertionError("historical product readback status changed")
    print(json.dumps({
        "status": "PASS_R1_EXTENSION_STRICT_ALLOWLIST",
        "baseline_path": baseline["path"],
        "baseline_sha256": baseline["sha256"],
        "current_analysis_http_status": current_status,
        "current_analysis_raw_response_sha256": sha(current_raw),
        "current_analysis_stripped_response_sha256": sha(stripped),
        "current_analysis_pinned_response_sha256": current_expected["response_sha256"],
        "extension_count": extension_count,
        "accepted_extension_summary": accepted,
        "malicious_extension_result": rejection,
        "historical_product_readback_status": product_readback["status"],
        "workspace_status": product_readback["workspace_status"],
        "payload_bytes_persisted_or_printed": False,
        "service_or_pointer_mutation_called": False,
    }, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
