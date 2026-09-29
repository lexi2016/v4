from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = (
    ROOT
    / "contracts"
    / "migration"
    / "phase6_hourly_research_idempotency_contract_v1.json"
)
EVIDENCE = (
    ROOT
    / "docs"
    / "evidence"
    / "phase6-hourly-research-idempotency-20260801.json"
)
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "research"
FIXTURE_MANIFEST = FIXTURE_ROOT / "manifest.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _semantic_hash(payload: dict) -> str:
    body = {key: value for key, value in payload.items() if key != "semantic_hash"}
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _evidence_semantic_hash(payload: dict) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key != "evidence_semantic_hash"
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def _fixture_manifest() -> dict:
    manifest = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "v3_5.research_test_fixture_manifest.v1"
    assert manifest["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
    return manifest


def _fixture_file(commit: str, relative: str) -> Path:
    manifest = _fixture_manifest()
    entry = manifest["commits"][commit]["files"][relative]
    path = FIXTURE_ROOT / entry["relative_path"]
    assert path.is_file(), path
    assert _sha(path) == entry["sha256"]
    return path


def _assert_commit_exists(commit: str) -> None:
    assert re.fullmatch(r"[0-9a-f]{7,40}", commit)
    commit_entry = _fixture_manifest()["commits"].get(commit)
    assert commit_entry is not None, commit
    for relative in commit_entry["files"]:
        _fixture_file(commit, relative)


def _contract_at_commit(commit: str) -> dict:
    relative = CONTRACT.relative_to(ROOT).as_posix()
    return json.loads(_fixture_file(commit, relative).read_text(encoding="utf-8"))


def _file_sha_at_commit(commit: str, relative: str) -> str:
    return _sha(_fixture_file(commit, relative))


def test_phase6_contract_was_frozen_before_the_optimization() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert contract["schema_version"] == "v3_5.phase6_performance_contract.v1"
    assert contract["status"] == "FROZEN_BEFORE_CHANGE"
    assert contract["semantic_hash"] == _semantic_hash(contract)
    assert contract["frozen_baseline"]["git_commit"] == (
        "a6fbf96e0d422fb1024a3374c37a8ef4a3c72577"
    )
    assert contract["pass_signal"]["minimum_median_speedup_ratio"] == 0.2
    assert contract["safety"] == {
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def test_phase6_projection_matches_original_frozen_decisions() -> None:
    projection = json.loads(CONTRACT.read_text(encoding="utf-8"))
    freeze_commit = projection["frozen_baseline"]["contract_freeze_commit"]
    original = _contract_at_commit(freeze_commit)

    assert original["semantic_hash"] == _semantic_hash(original)
    assert original["semantic_hash"] == projection["frozen_baseline"][
        "original_contract_semantic_hash"
    ]
    for field in (
        "allowed_paths",
        "benchmark",
        "business_contract_sha256",
        "forbidden_changes",
        "goal",
        "hypothesis",
        "optimization_id",
        "pass_signal",
        "rejection_conditions",
        "safety",
        "schema_version",
        "status",
        "stop_rule",
        "writer",
    ):
        assert projection[field] == original[field]
    for field in (
        "git_commit",
        "graph_baseline_semantic_hash",
        "inventory_v2_semantic_hash",
    ):
        assert projection["frozen_baseline"][field] == original[
            "frozen_baseline"
        ][field]
    original_source = dict(original["frozen_source"])
    original_path = original_source.pop("path")
    projected_source = dict(projection["frozen_source"])
    assert projected_source.pop("locator") == "EXPLICIT_READ_ONLY_SOURCE_ARGUMENT"
    assert projected_source.pop("path_identity_sha256") == hashlib.sha256(
        original_path.encode("utf-8")
    ).hexdigest()
    assert projected_source == original_source
    assert projection["projection"] == {
        "changed_field": "frozen_source.path",
        "decision_fields_unchanged": True,
        "kind": "POST_FREEZE_ABSOLUTE_PATH_REDACTION",
        "replacement_fields": [
            "frozen_source.locator",
            "frozen_source.path_identity_sha256",
        ],
    }


def test_phase6_business_contract_hashes_match_the_optimized_commit() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    optimized_commit = evidence["optimized"]["code_commit"]

    assert {
        path: _file_sha_at_commit(optimized_commit, path)
        for path in contract["business_contract_sha256"]
    } == contract["business_contract_sha256"]


def _validate_before_after_evidence(contract: dict, evidence: dict) -> None:
    assert evidence["evidence_semantic_hash"] == _evidence_semantic_hash(
        evidence
    )
    assert evidence["status"] == "PASS"
    assert evidence["contract_projection_semantic_hash"] == contract[
        "semantic_hash"
    ]
    assert evidence["original_contract_semantic_hash"] == contract[
        "frozen_baseline"
    ]["original_contract_semantic_hash"]
    assert evidence["contract_freeze_commit"] == contract["frozen_baseline"][
        "contract_freeze_commit"
    ]
    _assert_commit_exists(evidence["contract_freeze_commit"])
    baseline = evidence["baseline"]
    optimized = evidence["optimized"]
    evaluation = evidence["evaluation"]
    assert baseline["code_commit"] == contract["frozen_baseline"]["git_commit"]
    _assert_commit_exists(baseline["code_commit"])
    _assert_commit_exists(optimized["code_commit"])
    _assert_commit_exists(evidence["exploratory_attempt"]["code_commit"])
    for result in (baseline, optimized):
        assert result["source_sha256"] == contract["frozen_source"]["sha256"]
        assert result["derived_source_sha256"] == contract["benchmark"][
            "derived_input_sha256"
        ]
        assert result["iterations"] == contract["benchmark"]["iterations"]
        assert result["warmup_iterations"] == contract["benchmark"][
            "warmup_iterations"
        ]
        assert len(result["durations_seconds"]) == result["iterations"]
        assert all(value > 0 for value in result["durations_seconds"])
        assert result["median_seconds"] == statistics.median(
            result["durations_seconds"]
        )
        assert result["p95_seconds"] == _p95(result["durations_seconds"])
        assert result["source_read_only"] is True
        assert result["production_allowed"] is False
        assert result["buy_gate_updated"] is False
        assert result["orders_sent"] is False
    assert baseline["payload_sha256"] == optimized["payload_sha256"]
    assert baseline["artifact_canonical_sha256"] == optimized[
        "artifact_canonical_sha256"
    ]
    assert (baseline["article_count"], baseline["stock_pool_count"]) == (
        optimized["article_count"],
        optimized["stock_pool_count"],
    )
    speedup = (
        baseline["median_seconds"] - optimized["median_seconds"]
    ) / baseline["median_seconds"]
    p95_ratio = optimized["p95_seconds"] / baseline["p95_seconds"]
    assert evaluation["median_speedup_ratio"] == speedup
    assert evaluation["median_speedup_threshold"] == contract[
        "pass_signal"
    ]["minimum_median_speedup_ratio"]
    assert speedup >= contract["pass_signal"]["minimum_median_speedup_ratio"]
    assert evaluation["p95_to_baseline_ratio"] == p95_ratio
    assert evaluation["p95_to_baseline_ratio_limit"] == contract[
        "pass_signal"
    ]["optimized_p95_to_baseline_p95_max_ratio"]
    assert p95_ratio <= contract["pass_signal"][
        "optimized_p95_to_baseline_p95_max_ratio"
    ]
    assert optimized["p95_seconds"] < contract["pass_signal"][
        "optimized_p95_must_be_below_seconds"
    ]
    for field in (
        "artifact_canonical_sha256_unchanged",
        "business_contract_sha256_unchanged",
        "derived_input_sha256_unchanged",
        "p95_seconds_below_schedule_window",
        "payload_sha256_unchanged",
        "safety_flags_remain_false",
        "source_sha256_unchanged",
    ):
        assert evaluation[field] is True
    assert evidence["safety"] == contract["safety"]


def test_phase6_before_after_evidence_passes_the_frozen_gate() -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))

    _validate_before_after_evidence(contract, evidence)


@pytest.mark.parametrize(
    "mutation",
    ("duration", "source_sha", "code_commit"),
)
def test_phase6_gate_rejects_rehashed_evidence_tamper(mutation: str) -> None:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    evidence = json.loads(EVIDENCE.read_text(encoding="utf-8"))
    if mutation == "duration":
        evidence["optimized"]["durations_seconds"][0] = 999.0
    elif mutation == "source_sha":
        evidence["baseline"]["source_sha256"] = "f" * 64
        evidence["optimized"]["source_sha256"] = "f" * 64
    else:
        evidence["baseline"]["code_commit"] = "bogus"
        evidence["optimized"]["code_commit"] = "bogus"
    evidence["evidence_semantic_hash"] = _evidence_semantic_hash(evidence)

    with pytest.raises(AssertionError):
        _validate_before_after_evidence(contract, evidence)
