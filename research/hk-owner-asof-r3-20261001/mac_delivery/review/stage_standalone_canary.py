"""Synthetic-only standalone Stage HK D-1 validation canary.

Runs against the assembled Stage app (actual release dependencies plus the
candidate HK validator patch). All pool writes are confined to this review
directory; no provider or live service is used.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "isolated/stage_app"
OUT = ROOT / "review/stage_standalone_canary"
TARGET = "20261008"
PRICE = "20261007"
sys.path.insert(0, str(APP))

from infrastructure.preselection_pool_store import PreselectionPoolStore  # noqa: E402
from stage_center import runner  # noqa: E402

SAFETY_FLAGS = ("production_allowed", "buy_gate_updated", "orders_sent")


def h(char: str) -> str:
    return char * 64


def payload() -> dict:
    source_sha = h("a")
    manifest_sha = h("b")
    receipt_sha = h("c")
    rows = []
    for i in range(1, 101):
        code = f"HK.{i:05d}"
        rows.append(
            {
                "market": "HK",
                "symbol": code,
                "code": code,
                "signal_date": PRICE,
                "trade_date": TARGET,
                "target_date": TARGET,
                "selected_strategy": "prob_active",
                "weekly_tuning_selected_strategy": "prob_active",
                "production_allowed": False,
                "buy_gate_updated": False,
                "orders_sent": False,
            }
        )
    qualification = {
        "schema_version": "v4.hk_eligibility_asof.v1",
        "source_date": PRICE,
        "captured_at": "2026-10-07T17:20:00+08:00",
        "validity": "EXACT_CAPTURE_DATE_ONLY",
        "source_role": "FUTU_HKCONNECT_PLATE_MEMBERSHIP",
        "source_sha256": h("d"),
        "codes_sha256": h("e"),
        "code_count": 651,
        "authority_run_id": "synthetic-authority-run",
        "authority_artifact_sha256": h("f"),
        "authority_manifest_sha256": h("1"),
        "authority_receipt_sha256": h("2"),
        "authority_current_sha256": h("3"),
        "security_master_run_id": "synthetic-security-master-run",
        "security_master_artifact_sha256": h("4"),
        "security_master_captured_at": "2026-10-07T17:21:00+08:00",
        **{flag: False for flag in SAFETY_FLAGS},
    }
    return {
        "schema_version": "v3_5.preselection_pool.v1",
        "trade_date": TARGET,
        "pool_id": "hkconnect_d1_top100",
        "display_name": "Synthetic HK D-1 Top100",
        "market": "HK",
        "status": "STRICT_0_2_READY",
        "producer_id": "v3_shared_hk_0_2_consumer_v1",
        "source_role": "SHARED_VERIFIED_HK_0_2",
        "source_path": "synthetic://review-only/hk-d1",
        "source_sha256": source_sha,
        "source_artifact_sha256": source_sha,
        "source_run_id": "synthetic-d1-run",
        "source_manifest_sha256": manifest_sha,
        "source_receipt_sha256": receipt_sha,
        "source_row_count": 651,
        "signal_date": PRICE,
        "target_date": TARGET,
        "stage_selection_eligible": True,
        "rows": rows,
        "cannot_confirm": [],
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
        "historical_provenance": {
            "schema_version": "v4.hk_d1_eligibility_asof.v2",
            "price_signal_date": PRICE,
            "eligibility_source_date": PRICE,
            "d1_source_run_id": "synthetic-d1-run",
            "d1_source_artifact_sha256": source_sha,
            "d1_source_manifest_sha256": manifest_sha,
            "d1_source_receipt_sha256": receipt_sha,
            "eligibility_asof": qualification,
        },
    }


def run_case(name: str, mutate, *, expected_error: str | None) -> dict:
    case_root = OUT / name
    source_root = case_root / "source"
    primary_root = case_root / "primary"
    source_root.mkdir(parents=True)
    primary_root.mkdir(parents=True)
    value = payload()
    if mutate:
        mutate(value)
    PreselectionPoolStore(source_root).materialize(value)
    try:
        path, digest = runner._validate_hk_d1(
            primary_root, TARGET, preselection_source_root=source_root
        )
    except Exception as error:
        if expected_error is None:
            raise
        message = str(error)
        if expected_error not in message:
            raise AssertionError(
                f"{name}: expected {expected_error!r}, received {type(error).__name__}: {message}"
            ) from error
        return {"case": name, "result": "REJECTED_AS_EXPECTED", "error": message}
    if expected_error is not None:
        raise AssertionError(f"{name}: invalid artifact unexpectedly accepted at {path}")
    actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != actual_digest:
        raise AssertionError(f"{name}: returned digest did not bind artifact bytes")
    return {
        "case": name,
        "result": "ACCEPTED",
        "artifact": str(path),
        "artifact_sha256": digest,
    }


def module_record(module) -> dict:
    path = Path(module.__file__).resolve()
    return {
        "module": module.__name__,
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"Refusing to overwrite existing canary output: {OUT}")
    OUT.mkdir(parents=True)
    cases = [
        run_case("valid", None, expected_error=None),
        run_case(
            "wrong_capture_date",
            lambda value: value["historical_provenance"]["eligibility_asof"].update(
                captured_at="2026-10-06T17:20:00+08:00"
            ),
            expected_error="capture source-date mismatch",
        ),
        run_case(
            "wrong_d1_manifest_identity",
            lambda value: value["historical_provenance"].update(
                d1_source_manifest_sha256=h("9")
            ),
            expected_error="eligibility provenance identity mismatch",
        ),
    ]
    import stage_center._runner_parts.hk_input_validation as hk_validation  # noqa: E402
    import contracts.trading_calendar as trading_calendar  # noqa: E402
    import contracts.research_day_product as safety_contract  # noqa: E402
    import infrastructure.preselection_pool_store as pool_store  # noqa: E402

    result = {
        "status": "PASS",
        "interpreter": sys.executable,
        "python_version": sys.version,
        "target_date": TARGET,
        "price_signal_date": PRICE,
        "stage_app": str(APP),
        "cases": cases,
        "loaded_dependencies": [
            module_record(runner),
            module_record(hk_validation),
            module_record(pool_store),
            module_record(trading_calendar),
            module_record(safety_contract),
        ],
    }
    (OUT / "receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
