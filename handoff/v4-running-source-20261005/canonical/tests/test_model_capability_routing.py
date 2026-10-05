from __future__ import annotations

import json
from pathlib import Path


CONTRACT = Path("contracts/migration/model_capability_routing_v1.json")


def test_model_capability_routing_keeps_one_writer_and_independent_read_only_gates() -> None:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert payload["schema_version"] == "v3_5.model_capability_routing.v1"
    assert payload["controller"] == "codex_sol"
    assert payload["sole_writer"] == "codex_sol"
    assert payload["roles"] == {
        "codex_sol": {
            "responsibilities": ["scope", "architecture", "implementation", "integration", "final_decision"],
            "write_access": "V3_5_ALLOWED_PATHS_ONLY",
        },
        "luna_explorer": {
            "responsibilities": ["legacy_graph", "data_lineage", "path_and_identity_evidence"],
            "write_access": "NONE",
        },
        "reviewer": {
            "responsibilities": ["correctness", "security", "acceptance_gate"],
            "write_access": "NONE",
        },
        "deterministic_python": {
            "responsibilities": ["sha256", "counts", "parity_metrics", "performance_metrics"],
            "write_access": "EVIDENCE_OUTPUTS_ONLY",
        },
        "terra": {
            "responsibilities": ["future_isolated_implementation_only"],
            "write_access": "DISABLED_IN_CURRENT_BATCH",
        },
        "gem": {
            "responsibilities": ["future_hypothesis_and_falsification_only"],
            "write_access": "NONE",
        },
    }


def test_model_routing_does_not_delegate_business_or_numeric_decisions_to_llm_workers() -> None:
    payload = json.loads(CONTRACT.read_text(encoding="utf-8"))

    assert payload["rules"] == {
        "worker_ready_is_completion": False,
        "controller_revalidates_evidence": True,
        "llm_may_change_model_or_threshold": False,
        "llm_may_override_deterministic_metrics": False,
        "subagent_may_modify_formal_files": False,
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }
