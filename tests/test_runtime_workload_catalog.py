from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest

from contracts.runtime_tasks import MarketScope, RunPolicy, SessionRequirement
from infrastructure.scheduling.catalog import load_workload_catalog
from ops.migration.task_registration import build_task_spec_registrations
from ops.migration.task_registration import build_catalog_with_task_registrations


REPO = Path(__file__).resolve().parents[1]
PHASE5_AUDIT = (
    REPO
    / "contracts"
    / "migration"
    / "phase5_runtime_governance_audit_v1.json"
)


def test_catalog_has_one_owner_per_workload() -> None:
    catalog = load_workload_catalog()

    workloads = catalog.workloads
    assert len({row.workload_id for row in workloads}) == len(workloads)
    assert len({row.owner_id for row in workloads if row.enabled}) == len(
        [row for row in workloads if row.enabled]
    )
    hourly = next(row for row in workloads if row.workload_id == "hourly_research")
    assert hourly.enabled is True
    assert hourly.run_policy is RunPolicy.A_OR_HK_CONNECT_TRADE_DAY
    assert hourly.market_scope is MarketScope.CROSS_MARKET
    assert hourly.session_requirement is SessionRequirement.DAY_ELIGIBILITY_ONLY
    assert hourly.slots == ("0700", "1200", "1800", "2300")
    assert hourly.aliases == (
        "hourly_research_delta",
        "v3_hourly_research_delta_0730_1530",
    )
    assert hourly.command == (
        "python",
        "-m",
        "ops.run_hourly_research",
        "--data-root",
        "{data_root}",
        "--date",
        "{business_date}",
        "--target-date",
        "{target_date}",
        "--slot",
        "{slot}",
        "--mode",
        "{mode}",
    )
    assert all(row.safety.production_allowed is False for row in workloads)
    assert len(catalog.retired_owners) == 6
    assert catalog.schema_version == "v3_5.runtime_workloads.v2"
    assert len(catalog.task_registrations) == 34
    assert all(row.enabled is False for row in catalog.task_registrations)
    assert all(row.execution_allowed is False for row in catalog.task_registrations)
    assert all(row.status == "CANNOT_CONFIRM" for row in catalog.task_registrations)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update({"unexpected": True}),
        lambda payload: payload["workloads"][0].pop("owner_id"),
        lambda payload: payload["workloads"][0].update({"enabled": "yes"}),
        lambda payload: payload["workloads"][0].update({"run_policy": "NATURAL_DAY"}),
        lambda payload: payload["workloads"][1].update(
            {"owner_id": payload["workloads"][0]["owner_id"]}
        ),
        lambda payload: payload["workloads"][1].update(
            {"aliases": [payload["workloads"][0]["aliases"][0]]}
        ),
        lambda payload: payload["workloads"][0].update({"extra": "field"}),
        lambda payload: payload["task_registrations"][0].update({"enabled": True}),
        lambda payload: payload["task_registrations"][0].update(
            {"execution_allowed": True}
        ),
        lambda payload: payload["task_registrations"][0].update(
            {"status": "DEFERRED"}
        ),
        lambda payload: payload["task_registrations"][0].update(
            {"graph_task_spec_id": "task_spec:wrong"}
        ),
        lambda payload: payload["task_registrations"][0].update(
            {"command": ["python", "-m", "forbidden"]}
        ),
        lambda payload: payload["task_registrations"].append(
            deepcopy(payload["task_registrations"][0])
        ),
        lambda payload: payload["task_registrations"].pop(),
        lambda payload: payload["task_registrations"][0].update(
            {
                "legacy_task_id": "FakeGraphTask",
                "graph_task_spec_id": "task_spec:FakeGraphTask",
            }
        ),
        lambda payload: payload["task_registrations"][0]["safety"].update(
            {"production_allowed": True}
        ),
    ],
)
def test_catalog_rejects_malformed_or_ambiguous_rows(tmp_path, mutate) -> None:
    source = load_workload_catalog().source_payload
    payload = deepcopy(source)
    mutate(payload)
    path = tmp_path / "runtime_workloads.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_workload_catalog(path)


def test_catalog_source_payload_is_detached_from_runtime_types() -> None:
    first = load_workload_catalog()
    second = load_workload_catalog()
    first.source_payload["workloads"][0]["aliases"].append("mutated")

    assert "mutated" not in second.source_payload["workloads"][0]["aliases"]


def test_task_registrations_are_reproducible_graph_bound_non_dispatchable_rows() -> None:
    catalog = load_workload_catalog()
    audit = json.loads(PHASE5_AUDIT.read_text(encoding="utf-8"))
    source_rows = catalog.source_payload["task_registrations"]

    assert source_rows == build_task_spec_registrations(audit)
    assert [row.legacy_task_id for row in catalog.task_registrations] == sorted(
        row.legacy_task_id for row in catalog.task_registrations
    )
    assert len({row.graph_task_spec_id for row in catalog.task_registrations}) == 34
    assert all(
        row.graph_task_spec_id == f"task_spec:{row.legacy_task_id}"
        for row in catalog.task_registrations
    )
    assert all(not hasattr(row, "command") for row in catalog.task_registrations)
    assert all(not hasattr(row, "slots") for row in catalog.task_registrations)
    assert "OpeningAdvisorV3_HourlyResearch_0700_2359" not in {
        row.legacy_task_id for row in catalog.task_registrations
    }
    missing_launchers = {
        row.legacy_task_id
        for row in catalog.task_registrations
        if not row.legacy_launcher_paths
    }
    assert missing_launchers == {
        "OpeningAdvisorV3_1605_HKModelReview",
        "OpeningAdvisorV3_2130_WQ101Prewarm",
    }


def test_builder_rejects_a_self_hashed_alternate_graph_identity() -> None:
    catalog = load_workload_catalog().source_payload
    audit = json.loads(PHASE5_AUDIT.read_text(encoding="utf-8"))
    unresolved = next(
        row
        for row in audit["canonical_tasks"]
        if row["mapping_status"] == "CANNOT_CONFIRM_CATALOG_OWNER"
    )
    unresolved["legacy_task_id"] = "FakeGraphTask"
    unresolved["graph_task_spec_id"] = "task_spec:FakeGraphTask"
    audit.pop("semantic_hash")
    audit["semantic_hash"] = hashlib.sha256(
        json.dumps(
            audit,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()

    with pytest.raises(ValueError, match="do not match approved contract"):
        build_catalog_with_task_registrations(catalog, audit)
