from __future__ import annotations

import hashlib
import json
import math
import statistics
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "contracts"
    / "migration"
    / "phase6_current_checkout_rebenchmark_v1.json"
)
EVIDENCE = (
    ROOT
    / "docs"
    / "evidence"
    / "phase6-current-checkout-rebenchmark-20260801.json"
)
SOURCE = Path(
    r"C:\Users\huang\Desktop\学习\v3_system\研报模块"
    r"\runtime_outputs\latest\20260730\research_lane_snapshot.json"
)


def _raw_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_hash(payload: dict, field: str) -> str:
    body = {key: value for key, value in payload.items() if key != field}
    return hashlib.sha256(
        json.dumps(
            body,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _file_sha_at_commit(commit: str, relative: str) -> str:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    return hashlib.sha256(completed.stdout).hexdigest()


def test_phase6_current_rebenchmark_contract_is_frozen_before_run() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["schema_version"] == (
        "v3_5.phase6_current_checkout_rebenchmark_contract.v1"
    )
    assert contract["status"] == "FROZEN_BEFORE_CURRENT_RUN"
    assert contract["semantic_hash"] == _semantic_hash(contract, "semantic_hash")
    commit = contract["frozen_current_checkout"]["git_commit"]
    frozen_files = {
        **contract["business_contract_sha256"],
        **contract["frozen_current_checkout"]["implementation_sha256"],
    }
    assert {
        path: _file_sha_at_commit(commit, path)
        for path in frozen_files
    } == frozen_files
    assert _raw_sha(SOURCE) == contract["frozen_source"]["sha256"]
    assert SOURCE.stat().st_size == contract["frozen_source"]["bytes"]
    assert hashlib.sha256(str(SOURCE).encode("utf-8")).hexdigest() == (
        contract["frozen_source"]["path_identity_sha256"]
    )
    assert contract["benchmark"]["iterations"] == 7
    assert contract["benchmark"]["warmup_iterations"] == 1
    assert contract["pass_signal"]["current_median_to_v3_success_max_ratio"] == 1.0
    assert contract["pass_signal"]["current_p95_to_v3_success_max_ratio"] == 1.1
    assert contract["safety"] == {
        "buy_gate_updated": False,
        "orders_sent": False,
        "production_allowed": False,
        "v3_written": False,
        "windows_tasks_changed": False,
    }


def test_phase6_current_rebenchmark_passes_frozen_v3_gate() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    assert evidence["schema_version"] == (
        "v3_5.phase6_current_checkout_rebenchmark_evidence.v1"
    )
    assert evidence["status"] == "PASS"
    assert evidence["evidence_semantic_hash"] == _semantic_hash(
        evidence, "evidence_semantic_hash"
    )
    assert evidence["contract"] == {
        "path": CONTRACT.relative_to(ROOT).as_posix(),
        "raw_sha256": _raw_sha(CONTRACT),
        "semantic_hash": contract["semantic_hash"],
    }
    current = evidence["current"]
    reference = evidence["reference_v3_success"]
    evaluation = evidence["evaluation"]
    assert current["code_commit"] == contract["frozen_current_checkout"]["git_commit"]
    assert current["iterations"] == contract["benchmark"]["iterations"]
    assert current["warmup_iterations"] == contract["benchmark"]["warmup_iterations"]
    assert len(current["durations_seconds"]) == current["iterations"]
    assert current["median_seconds"] == statistics.median(
        current["durations_seconds"]
    )
    assert current["p95_seconds"] == sorted(current["durations_seconds"])[
        math.ceil(current["iterations"] * 0.95) - 1
    ]
    assert current["source_sha256"] == contract["frozen_source"]["sha256"]
    assert current["derived_source_sha256"] == contract["benchmark"][
        "derived_input_sha256"
    ]
    assert current["payload_sha256"] == reference["payload_sha256"]
    assert current["artifact_canonical_sha256"] == reference[
        "artifact_canonical_sha256"
    ]
    assert (current["article_count"], current["stock_pool_count"]) == (
        reference["article_count"],
        reference["stock_pool_count"],
    )
    median_ratio = current["median_seconds"] / reference["median_seconds"]
    p95_ratio = current["p95_seconds"] / reference["p95_seconds"]
    assert evaluation["current_median_to_v3_success_ratio"] == median_ratio
    assert evaluation["current_p95_to_v3_success_ratio"] == p95_ratio
    assert median_ratio <= contract["pass_signal"][
        "current_median_to_v3_success_max_ratio"
    ]
    assert p95_ratio <= contract["pass_signal"][
        "current_p95_to_v3_success_max_ratio"
    ]
    assert current["p95_seconds"] < contract["pass_signal"][
        "p95_must_be_below_seconds"
    ]
    assert {
        path: _raw_sha(ROOT / path)
        for path in contract["business_contract_sha256"]
    } == contract["business_contract_sha256"]
    assert {
        path: _raw_sha(ROOT / path)
        for path in contract["frozen_current_checkout"]["implementation_sha256"]
    } == contract["frozen_current_checkout"]["implementation_sha256"]
    assert all(
        evaluation[field] is True
        for field in (
            "artifact_canonical_sha256_unchanged",
            "business_contract_sha256_unchanged",
            "derived_input_sha256_unchanged",
            "p95_below_schedule_window",
            "payload_sha256_unchanged",
            "safety_flags_remain_false",
            "source_sha256_unchanged",
        )
    )
    assert evidence["safety"] == contract["safety"]
    assert evidence["invocation_adjustment"]["sample_or_threshold_changed"] is False
