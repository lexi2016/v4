#!/usr/bin/env python3
"""Replay the frozen RED, isolated date GREEN, and separately deferred nested P2.

Requires Python with pytest. All dependencies needed by the real PoolStore are
bundled as pinned read-only support; no service, Mac path, network or repo cwd
is required. Exit zero means every selected expected outcome was observed;
DEFERRED_P2 probes are expected failures, never reported as passing tests.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parent
DATE_RED_NAMES = {
    "test_future_source_date_is_rejected_before_materialization[split-eligibility_source_date-20261008]",
    "test_future_source_date_is_rejected_before_materialization[split-price_signal_date-20261008]",
    "test_future_source_date_is_rejected_before_materialization[asof-eligibility_source_date-20261001]",
    "test_future_source_date_is_rejected_before_materialization[asof-price_signal_date-20261001]",
    "test_optional_target_field_does_not_disable_trade_date_upper_bound",
}
NESTED_RED_NAMES = {
    "test_unregistered_nested_object_extension_is_rejected[eligibility_asof]",
    "test_unregistered_nested_object_extension_is_rejected[price_recovery]",
}
MODES = {
    "before": ("before", [], 13, DATE_RED_NAMES, "EXPECTED_DATE_RED"),
    "after": ("after", [], 13, set(), "DATE_SUITE_PASS"),
    "nested_before": (
        "before", ["probes/test_nested_unknown_keys_contract_gap.py"], 2,
        NESTED_RED_NAMES, "DEFERRED_P2_REPRODUCED",
    ),
    "nested_after": (
        "after", ["probes/test_nested_unknown_keys_contract_gap.py"], 2,
        NESTED_RED_NAMES, "DEFERRED_P2_REPRODUCED",
    ),
}


def verify_inputs() -> None:
    identities = json.loads((ROOT / "SOURCE_IDENTITIES.json").read_text(encoding="utf-8"))
    for item in identities["files"]:
        path = ROOT / item["path"]
        raw = path.read_bytes()
        if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise RuntimeError(f"pinned validation input changed: {item['path']}")


def run_mode(name: str, logs: Path) -> dict:
    source, paths, expected_total, expected_failures, status = MODES[name]
    xml_path = logs / f"{name}.xml"
    command = [
        sys.executable, "-B", "-m", "pytest", "-q", "-o",
        f"cache_dir={logs / (name + '-cache')}",
        f"--basetemp={logs / (name + '-tmp')}",
        f"--junitxml={xml_path}", *paths,
    ]
    result = subprocess.run(
        command, cwd=ROOT,
        env={
            **os.environ,
            "PYTHONDONTWRITEBYTECODE": "1",
            "HISTORICAL_POOL_SOURCE_ROOT": str(ROOT / source),
        },
        text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=120,
    )
    (logs / f"{name}.log").write_text(result.stdout, encoding="utf-8")
    cases = ET.parse(xml_path).getroot().findall(".//testcase") if xml_path.exists() else []
    failures = {case.attrib["name"]: case.find("failure") for case in cases if case.find("failure") is not None}
    errors = [case.attrib["name"] for case in cases if case.find("error") is not None]
    skips = [case.attrib["name"] for case in cases if case.find("skipped") is not None]
    red_reason_ok = all("DID NOT RAISE" in failure.attrib.get("message", "") for failure in failures.values())
    expected_exit = 1 if expected_failures else 0
    expected_observed = (
        result.returncode == expected_exit and len(cases) == expected_total
        and set(failures) == expected_failures and not errors and not skips and red_reason_ok
    )
    source_file = ROOT / source / "infrastructure/preselection_pool_store.py"
    record = {
        "mode": name,
        "classification": status if expected_observed else "UNEXPECTED_RESULT",
        "command": command,
        "cwd": str(ROOT),
        "selected_source": str(source_file),
        "selected_source_sha256": hashlib.sha256(source_file.read_bytes()).hexdigest(),
        "pytest_returncode": result.returncode,
        "tests": len(cases),
        "passed": len(cases) - len(failures) - len(errors) - len(skips),
        "failed": len(failures),
        "failure_names": sorted(failures),
        "errors": errors,
        "skipped": skips,
        "expected_result_observed": expected_observed,
        "log": str(logs / f"{name}.log"),
        "junit_xml": str(xml_path),
    }
    print(json.dumps(record, ensure_ascii=False))
    if not expected_observed:
        print(result.stdout)
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=[*MODES, "all"], default="all")
    parser.add_argument("--log-dir", type=Path, default=ROOT / "logs" / "replay")
    args = parser.parse_args()
    logs = args.log_dir.resolve()
    logs.mkdir(parents=True, exist_ok=True)
    verify_inputs()
    modes = list(MODES) if args.mode == "all" else [args.mode]
    results = [run_mode(name, logs) for name in modes]
    verify_inputs()
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "platform": platform.platform(),
        "pytest": importlib.metadata.version("pytest"),
        "results": results,
        "nested_unknown_key_p2": "DEFERRED_PENDING_ORIGINAL_PRODUCER_SCHEMA_AND_OUTPUTS",
        "deployed": False,
    }
    (logs / "RESULTS.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return 0 if all(item["expected_result_observed"] for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
