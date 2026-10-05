"""Deterministic V3.5 runtime-selection/research topology generation.

This module extends the existing ``infrastructure.runtime_graph`` package with
the V3.5 timeline contract.  The old V3 timeline is read only and contributes
design-time migration semantics; it is never treated as a live data source.
The generated graph is deliberately static.  Live launchd/release/state
evidence belongs in :mod:`v35_bindings` and is a separate snapshot.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "v35_runtime_graph_topology.v1"
BASELINE_SHA = "c0cf5f917665473cfb22476f10b120399f79e8a43746e0ef06792c68b7baa1fe"
BASELINE_ROLE = "design_only_migration_semantics"
ALLOWED_NODE_TYPES = frozenset(
    {
        "launcher",
        "workload",
        "executor",
        "producer",
        "store",
        "artifact_trio",
        "current",
        "API",
        "page",
        "safety",
    }
)
ALLOWED_EDGE_KINDS = frozenset(
    {
        "migrated_from",
        "schedules",
        "invokes",
        "reads",
        "writes",
        "validates",
        "projects",
        "renders",
        "binds",
    }
)
SAFETY = {
    "production_allowed": False,
    "buy_gate_updated": False,
    "orders_sent": False,
}
CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "v35_runtime_graph_topology.json"
_STAGE_RE = re.compile(
    r'\{\s*id:\s*"(?P<id>[^"]+)",\s*label:\s*"(?P<label>[^"]+)",\s*timeline:\s*"(?P<timeline>[^"]+)"\s*\}'
)
_CLOSING_RE = re.compile(r'^\s*"(?P<timeline>\d+\.\s+[^"\n]+)"\s*,?\s*$', re.MULTILINE)
_TIME_RE = re.compile(r"(?<!\d)(\d{2}):(\d{2})(?!\d)")

# This is a small semantic alias table, not a second timeline.  The 19
# positions and labels are always parsed from App.vue; this table only joins
# UI language to the already registered workload IDs and source roles.
_CLOSING_WORKLOAD_HINTS: tuple[tuple[str, str], ...] = (
    ("收盘：", "hk_connect_close_review"),
    ("收盘前总结", "fupan_close_materials"),
    ("收盘后复盘启动", "fupan_review_start"),
    ("A股收盘数据", "a_share_close_review"),
    ("最新复盘视频检查", "fupan_video_check"),
    ("视频下载与转写", "fupan_video_download_asr"),
    ("股票字典校正", "fupan_stockdict"),
    ("视频表格OCR/ASR/新闻对齐", "fupan_video_table_ocr_align"),
    ("页面复盘对视频差距", "fupan_video_gap"),
    ("第三版复盘发布", "fupan_v3_publish"),
    ("8871 刷新与页面验收", "fupan_8771_verify"),
)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def canonical_payload(payload: dict[str, Any]) -> bytes:
    """Return the semantic bytes used by ``semantic_sha``.

    Hashing excludes only the self-referential ``semantic_sha`` field.  The
    contract is otherwise fully covered, including source fingerprints and
    safety declarations.
    """

    return _canonical_json({key: value for key, value in payload.items() if key != "semantic_sha"})


def _sha256_path(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _source_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path(__file__).resolve().parents[2]).as_posix()
    except ValueError:
        return path.as_posix()


def _extract_timeline(app_path: Path) -> list[dict[str, str]]:
    """Parse the two App.vue timeline arrays, retaining their source order."""

    source = app_path.read_text(encoding="utf-8")
    stages_match = re.search(r"const stageDefinitions:.*?=\s*\[(?P<body>.*?)\n\];", source, re.DOTALL)
    closing_match = re.search(r"const closingTimeline\s*=\s*\[(?P<body>.*?)\n\];", source, re.DOTALL)
    if not stages_match or not closing_match:
        raise ValueError("V35_TIMELINE_SOURCE_NOT_FOUND")
    stages = [
        {
            "position": str(index),
            "id": match.group("id"),
            "label": match.group("label"),
            "timeline": match.group("timeline"),
            "kind": "stage",
        }
        for index, match in enumerate(_STAGE_RE.finditer(stages_match.group("body")), start=1)
    ]
    if len(stages) != 8:
        raise ValueError("V35_STAGE_TIMELINE_COUNT_INVALID")
    closing = [
        {
            "position": str(8 + index),
            "id": f"CLOSING_{index:02d}",
            "label": match.group("timeline").split(". ", 1)[1],
            "timeline": match.group("timeline"),
            "kind": "closing",
        }
        for index, match in enumerate(_CLOSING_RE.finditer(closing_match.group("body")), start=1)
    ]
    if len(closing) != 11:
        raise ValueError("V35_CLOSING_TIMELINE_COUNT_INVALID")
    return stages + closing


def _workload_index(workloads_path: Path) -> dict[str, dict[str, Any]]:
    payload = _load_json(workloads_path)
    result: dict[str, dict[str, Any]] = {}
    for raw in payload.get("workloads", []):
        if not isinstance(raw, dict) or not isinstance(raw.get("workload_id"), str):
            continue
        result[raw["workload_id"]] = raw
    return result


def _workload_for(item: dict[str, str], workloads: dict[str, dict[str, Any]]) -> tuple[str, str]:
    if item["kind"] == "stage":
        workload_id = "stage_workbench"
        stage_slots = workloads[workload_id].get("slots", [])
        stage_slot_by_id = {
            "STAGE_0925": "0925",
            "STAGE_0930_0935": "0935",
            "STAGE_0935_0940": "0940",
            "STAGE_0940_0945": "0945",
            "STAGE_0945_1030": "1030",
            "STAGE_1300_1315": "1315",
            "STAGE_1445_1500": "1500",
            "STAGE_1545_1555": "1555",
        }
        slot = stage_slot_by_id.get(item["id"])
        if slot not in stage_slots:
            raise ValueError(f"V35_STAGE_SLOT_NOT_REGISTERED:{item['id']}")
        return workload_id, slot
    label = item["label"]
    workload_id = next((candidate for hint, candidate in _CLOSING_WORKLOAD_HINTS if hint in label), None)
    if workload_id is None or workload_id not in workloads:
        raise ValueError(f"V35_CLOSING_WORKLOAD_NOT_REGISTERED:{label}")
    registered = [str(slot) for slot in workloads[workload_id].get("slots", [])]
    times = [f"{hour}{minute}" for hour, minute in _TIME_RE.findall(label)]
    slot = next((candidate for candidate in times if candidate in registered), None)
    if slot is None:
        # The UI title for the HK close review says 16:05 while the actual
        # workload is intentionally scheduled at 16:08.  Contract authority
        # is the workload slot, not a display typo.
        slot = registered[0] if registered else ""
    if not slot:
        raise ValueError(f"V35_WORKLOAD_SLOT_NOT_REGISTERED:{workload_id}")
    return workload_id, slot


def _command_module(workload: dict[str, Any]) -> str:
    command = workload.get("command") or []
    if isinstance(command, list):
        try:
            module_index = command.index("-m") + 1
        except ValueError:
            module_index = -1
        if module_index > 0 and module_index < len(command):
            return str(command[module_index])
    return f"workloads.{workload.get('workload_id', 'unknown')}"


def _old_v3_events(baseline_path: Path, *, slot: str, workload_id: str) -> list[dict[str, Any]]:
    baseline = _load_json(baseline_path)
    events: list[dict[str, Any]] = []
    for task in baseline.get("windows_tasks", []):
        if not isinstance(task, dict):
            continue
        start = str((task.get("schedule") or {}).get("start", "")).replace(":", "")
        if start == slot:
            events.append({"task_name": task.get("task_name"), "nodes": task.get("nodes", []), "event": task.get("description", "")})
    # A small semantic bridge covers slots whose old task name was historical
    # (16:08 close review and the 16:05/17:10 A-share review pair).
    aliases = {
        "hk_connect_close_review": ("OpeningAdvisorV3_1605_HKModelReview", "hkconnect_model_selection_review"),
        "a_share_close_review": ("OpeningAdvisorV3_1605_FupanStructure", "FUPAN_A_SHARE_STRUCTURE"),
    }
    if not events and workload_id in aliases:
        task_name, node_id = aliases[workload_id]
        events.append({"task_name": task_name, "nodes": [node_id], "event": "semantic workload migration alias"})
    if not events:
        # The old timeline sometimes carried a shared stage task at a nearby
        # boundary; preserving an explicit design-only relation is preferable
        # to inventing a current runtime result.
        stage_alias = {
            "stage_workbench": "v3_opening_intraday_stage_select_0925_1500",
            "fupan_close_materials": "FUPAN_CLOSE_MATERIALS",
            "fupan_review_start": "FUPAN_REVIEW_START",
            "fupan_video_check": "FUPAN_VIDEO_CHECK",
            "fupan_video_download_asr": "FUPAN_VIDEO_DOWNLOAD_ASR",
            "fupan_stockdict": "FUPAN_STOCKDICT",
            "fupan_video_table_ocr_align": "FUPAN_VIDEO_TABLE_OCR_ALIGN",
            "fupan_video_gap": "FUPAN_VIDEO_GAP",
            "fupan_v3_publish": "FUPAN_V3_PUBLISH",
            "fupan_8771_verify": "FUPAN_8771_VERIFY",
        }
        node_id = stage_alias.get(workload_id)
        if node_id:
            events.append({"task_name": f"legacy:{workload_id}", "nodes": [node_id], "event": "semantic workload migration alias"})
    return events


def _route_for(workload_id: str, item: dict[str, str]) -> str:
    if workload_id == "stage_workbench":
        return f"/api/v3/workbench/stage?date={{business_date}}&stage={item['id']}&limit=50"
    if workload_id == "preselection_pools":
        return "/api/v3/preselection-pools?date={target_date}&limit=200"
    if workload_id == "hourly_research":
        return "/api/v3/research/lane?research_date={business_date}"
    if workload_id.startswith("fupan_") or workload_id.endswith("close_review"):
        return "/api/v3/review?date={business_date}"
    return "/api/v1/runs/date-list"


def _page_for(workload_id: str) -> str:
    if workload_id == "stage_workbench":
        return "apps/web/src/App.vue#timeline-grid"
    if workload_id == "preselection_pools":
        return "apps/web/src/App.vue#preselection-pools"
    if workload_id == "hourly_research":
        return "apps/web/src/views/ResearchView.vue#research-lane"
    return "apps/web/src/views/ReviewView.vue#review"


def _store_for(workload_id: str) -> str:
    if workload_id == "stage_workbench":
        return "stage_center/store.py"
    if workload_id == "preselection_pools":
        return "infrastructure/preselection_pool_store.py"
    if workload_id == "hourly_research":
        return "infrastructure/research_peripheral_store.py"
    return "infrastructure/review_store.py"


def _producer_for(workload_id: str, workload: dict[str, Any]) -> str:
    if workload_id == "stage_workbench":
        return "stage_center/runner.py"
    if workload_id == "preselection_pools":
        return "domains/preselection_materializer.py"
    module = _command_module(workload)
    return module.replace(".", "/") + ".py"


def _role_nodes(item: dict[str, str], workload_id: str, slot: str, workload: dict[str, Any], old_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    position = int(item["position"])
    prefix = f"timeline_{position:02d}"
    release = "immutable_v35_release:{deployment_id}"
    artifact_base = f"{{data_root}}/{workload_id}/{slot}"
    route = _route_for(workload_id, item)
    page = _page_for(workload_id)
    store = _store_for(workload_id)
    producer = _producer_for(workload_id, workload)
    nodes = [
        {
            "node_id": f"legacy_{position:02d}",
            "type": "producer",
            "label": "旧 V3 设计语义（只读）",
            "timeline_position": position,
            "design_only": True,
            "source": "old_v3_timeline_nodes.json",
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_launcher",
            "type": "launcher",
            "label": "V3.5 macOS scheduler launcher",
            "timeline_position": position,
            "path": "ops/run_v35_macos_scheduler.py",
            "plist": "~/Library/LaunchAgents/com.lexi.v35.scheduler.plist",
            "release_binding": release,
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_workload",
            "type": "workload",
            "label": item["timeline"],
            "timeline_position": position,
            "workload_id": workload_id,
            "slot": slot,
            "owner_id": workload.get("owner_id"),
            "command": workload.get("command", []),
            "run_policy": workload.get("run_policy"),
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_dispatcher",
            "type": "executor",
            "component_role": "dispatcher",
            "label": "typed dispatcher",
            "timeline_position": position,
            "path": "infrastructure/scheduling/dispatcher.py",
            "mode_boundary": ["LIVE", "BACKFILL"],
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_executor",
            "type": "executor",
            "component_role": "executor",
            "label": "executor registry",
            "timeline_position": position,
            "path": "infrastructure/scheduling/executor_registry.py",
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_producer",
            "type": "producer",
            "label": "exact-date producer",
            "timeline_position": position,
            "path": producer,
            "workload_id": workload_id,
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_store",
            "type": "store",
            "label": "authoritative store",
            "timeline_position": position,
            "path": store,
            "write_policy": "immutable_artifact_then_CAS_current",
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_artifact_trio",
            "type": "artifact_trio",
            "label": "artifact / manifest / receipt",
            "timeline_position": position,
            "artifact": f"{artifact_base}/artifact/{{date}}.json",
            "manifest": f"{artifact_base}/manifest/{{date}}.json",
            "receipt": f"{{dispatcher_root}}/receipts/{workload_id}/{slot}/{{date}}.json",
            "sha256_required": True,
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_current",
            "type": "current",
            "label": "current pointer",
            "timeline_position": position,
            "role": "current",
            "path": f"{artifact_base}/current.json",
            "cas": True,
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_latest",
            "type": "current",
            "label": "latest pointer",
            "timeline_position": position,
            "role": "latest",
            "path": f"{artifact_base}/latest.json",
            "cas": True,
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_api",
            "type": "API",
            "label": "read-only API projection",
            "timeline_position": position,
            "route": route,
            "date_binding": "explicit_business_or_target_date",
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_page",
            "type": "page",
            "label": "page consumer",
            "timeline_position": position,
            "consumer": page,
            "safety": dict(SAFETY),
        },
        {
            "node_id": f"{prefix}_safety",
            "type": "safety",
            "label": "research-only safety boundary",
            "timeline_position": position,
            "production_allowed": False,
            "buy_gate_updated": False,
            "orders_sent": False,
            "safety": dict(SAFETY),
        },
    ]
    return nodes


def _role_edges(position: int) -> list[dict[str, str]]:
    prefix = f"timeline_{position:02d}"
    return [
        {"source": f"legacy_{position:02d}", "target": f"{prefix}_workload", "kind": "migrated_from"},
        {"source": f"{prefix}_launcher", "target": f"{prefix}_workload", "kind": "schedules"},
        {"source": f"{prefix}_workload", "target": f"{prefix}_dispatcher", "kind": "invokes"},
        {"source": f"{prefix}_dispatcher", "target": f"{prefix}_executor", "kind": "invokes"},
        {"source": f"{prefix}_executor", "target": f"{prefix}_producer", "kind": "invokes"},
        {"source": f"{prefix}_producer", "target": f"{prefix}_store", "kind": "writes"},
        {"source": f"{prefix}_producer", "target": f"{prefix}_artifact_trio", "kind": "writes"},
        {"source": f"{prefix}_store", "target": f"{prefix}_artifact_trio", "kind": "validates"},
        {"source": f"{prefix}_artifact_trio", "target": f"{prefix}_current", "kind": "writes"},
        {"source": f"{prefix}_artifact_trio", "target": f"{prefix}_latest", "kind": "writes"},
        {"source": f"{prefix}_api", "target": f"{prefix}_current", "kind": "reads"},
        {"source": f"{prefix}_api", "target": f"{prefix}_latest", "kind": "reads"},
        {"source": f"{prefix}_current", "target": f"{prefix}_api", "kind": "projects"},
        {"source": f"{prefix}_latest", "target": f"{prefix}_api", "kind": "projects"},
        {"source": f"{prefix}_api", "target": f"{prefix}_page", "kind": "renders"},
        {"source": f"{prefix}_api", "target": f"{prefix}_safety", "kind": "binds"},
        {"source": f"{prefix}_page", "target": f"{prefix}_safety", "kind": "binds"},
    ]


def build_v35_topology(*, workloads_path: Path, app_path: Path, baseline_path: Path) -> dict[str, Any]:
    """Derive the static V3.5 topology from the workload contract and App AST/text."""

    if _sha256_path(baseline_path) != BASELINE_SHA:
        raise ValueError("V35_GRAPH_BASELINE_SHA_MISMATCH")
    workload_map = _workload_index(workloads_path)
    timeline = _extract_timeline(app_path)
    if len(timeline) != 19:
        raise ValueError("V35_TIMELINE_COUNT_INVALID")
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, str]] = []
    timeline_nodes: list[dict[str, Any]] = []
    timeline_chains: list[dict[str, Any]] = []
    for item in timeline:
        workload_id, slot = _workload_for(item, workload_map)
        workload = workload_map[workload_id]
        events = _old_v3_events(baseline_path, slot=slot, workload_id=workload_id)
        role_nodes = _role_nodes(item, workload_id, slot, workload, events)
        role_edges = _role_edges(int(item["position"]))
        nodes.extend(role_nodes)
        edges.extend(role_edges)
        position = int(item["position"])
        chain_ids = [node["node_id"] for node in role_nodes if not node["node_id"].startswith("legacy_")]
        timeline_nodes.append(
            {
                "position": position,
                "id": item["id"],
                "type": "workload",
                "label": item["label"],
                "timeline": item["timeline"],
                "planned_slot": slot,
                "workload_id": workload_id,
                "slot": slot,
                "migrated_from": {
                    "baseline_sha": BASELINE_SHA,
                    "events": events,
                },
                "launcher": {
                    "path": "ops/run_v35_macos_scheduler.py",
                    "plist": "~/Library/LaunchAgents/com.lexi.v35.scheduler.plist",
                    "release_binding": "immutable_v35_release:{deployment_id}",
                },
                "workload": {
                    "workload_id": workload_id,
                    "slot": slot,
                    "owner_id": workload.get("owner_id"),
                },
                "dispatcher": "infrastructure/scheduling/dispatcher.py",
                "executor": "infrastructure/scheduling/executor_registry.py",
                "producer": _producer_for(workload_id, workload),
                "store": _store_for(workload_id),
                "artifact_trio": {
                    "artifact": f"{{data_root}}/{workload_id}/{slot}/artifact/{{date}}.json",
                    "manifest": f"{{data_root}}/{workload_id}/{slot}/manifest/{{date}}.json",
                    "receipt": f"{{dispatcher_root}}/receipts/{workload_id}/{slot}/{{date}}.json",
                    "sha256_fields": {
                        "artifact": "artifact_sha256",
                        "manifest": "manifest_sha256",
                        "receipt": "receipt_sha256",
                    },
                },
                "current": f"{{data_root}}/{workload_id}/{slot}/current.json",
                "latest": f"{{data_root}}/{workload_id}/{slot}/latest.json",
                "api_route": _route_for(workload_id, item),
                "page_consumer": _page_for(workload_id),
                "chain_node_ids": chain_ids,
                "safety": dict(SAFETY),
            }
        )
        timeline_chains.append(
            {
                "position": position,
                "timeline_id": item["id"],
                "nodes": [{"id": node["node_id"], "type": node["type"]} for node in role_nodes],
                "edges": role_edges,
            }
        )
    nodes.sort(key=lambda node: node["node_id"])
    edges.sort(key=lambda edge: (edge["source"], edge["target"], edge["kind"]))
    source_inputs = {
        "workloads": {"path": _source_relative(workloads_path), "sha256": _sha256_path(workloads_path)},
        "app": {"path": _source_relative(app_path), "sha256": _sha256_path(app_path)},
        "old_v3": {"path": baseline_path.as_posix(), "sha256": BASELINE_SHA, "role": BASELINE_ROLE},
    }
    payload: dict[str, Any] = {
        "schema": "v35.runtime_graph.topology",
        "schema_version": SCHEMA_VERSION,
        "version": "2026-08-20.v1",
        "baseline_sha": BASELINE_SHA,
        "baseline_role": BASELINE_ROLE,
        "semantic_sha": "",
        "source_inputs": source_inputs,
        "safety": dict(SAFETY),
        "graph_policy": {
            "runtime_binding": "separate_live_snapshot",
            "deployment_claim": "design_contract_only_until_live_snapshot_is_verified",
            "mode": "RESEARCH_ONLY",
        },
        "node_types": sorted(ALLOWED_NODE_TYPES),
        "edge_kinds": sorted(ALLOWED_EDGE_KINDS),
        "timeline_nodes": timeline_nodes,
        "nodes": nodes,
        "edges": edges,
        "timeline_chains": timeline_chains,
    }
    payload["semantic_sha"] = hashlib.sha256(canonical_payload(payload)).hexdigest()
    validate_v35_topology(payload)
    return payload


def validate_v35_topology(payload: dict[str, Any]) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("V35_GRAPH_SCHEMA_INVALID")
    if payload.get("baseline_sha") != BASELINE_SHA:
        raise ValueError("V35_GRAPH_BASELINE_INVALID")
    if payload.get("baseline_role") != BASELINE_ROLE:
        raise ValueError("V35_GRAPH_BASELINE_ROLE_INVALID")
    if payload.get("safety") != SAFETY:
        raise ValueError("V35_GRAPH_SAFETY_INVALID")
    if payload.get("graph_policy", {}).get("mode") != "RESEARCH_ONLY":
        raise ValueError("V35_GRAPH_MODE_INVALID")
    timeline_nodes = payload.get("timeline_nodes")
    if not isinstance(timeline_nodes, list) or len(timeline_nodes) != 19:
        raise ValueError("V35_GRAPH_TIMELINE_COUNT_INVALID")
    positions = [node.get("position") for node in timeline_nodes]
    if positions != list(range(1, 20)):
        raise ValueError("V35_GRAPH_TIMELINE_ORDER_INVALID")
    for node in timeline_nodes:
        if not node.get("planned_slot") or not node.get("workload_id") or node.get("safety") != SAFETY:
            raise ValueError("V35_GRAPH_TIMELINE_NODE_INVALID")
        migration = node.get("migrated_from")
        if not isinstance(migration, dict) or migration.get("baseline_sha") != BASELINE_SHA or not migration.get("events"):
            raise ValueError("V35_GRAPH_MIGRATION_INVALID")
    graph_nodes = payload.get("nodes")
    if not isinstance(graph_nodes, list) or not graph_nodes:
        raise ValueError("V35_GRAPH_NODES_INVALID")
    node_ids = [node.get("node_id") for node in graph_nodes]
    if any(not isinstance(node_id, str) or not node_id for node_id in node_ids) or len(node_ids) != len(set(node_ids)):
        raise ValueError("V35_GRAPH_NODE_IDS_INVALID")
    if node_ids != sorted(node_ids):
        raise ValueError("V35_GRAPH_NODE_ORDER_INVALID")
    if any(node.get("type") not in ALLOWED_NODE_TYPES for node in graph_nodes):
        raise ValueError("V35_GRAPH_NODE_TYPE_INVALID")
    if any(node.get("safety") != SAFETY for node in graph_nodes):
        raise ValueError("V35_GRAPH_NODE_SAFETY_INVALID")
    edges = payload.get("edges")
    if not isinstance(edges, list):
        raise ValueError("V35_GRAPH_EDGES_INVALID")
    edge_keys = [(edge.get("source"), edge.get("target"), edge.get("kind")) for edge in edges]
    if any(source not in node_ids or target not in node_ids or kind not in ALLOWED_EDGE_KINDS for source, target, kind in edge_keys):
        raise ValueError("V35_GRAPH_EDGE_INVALID")
    if edge_keys != sorted(set(edge_keys)):
        raise ValueError("V35_GRAPH_EDGE_ORDER_INVALID")
    chains = payload.get("timeline_chains")
    if not isinstance(chains, list) or len(chains) != 19:
        raise ValueError("V35_GRAPH_CHAINS_INVALID")
    for chain in chains:
        chain_nodes = chain.get("nodes")
        chain_edges = chain.get("edges")
        chain_types = {node.get("type") for node in chain_nodes or []}
        if not {"launcher", "workload", "executor", "producer", "store", "artifact_trio", "current", "API", "page", "safety"} <= chain_types:
            raise ValueError("V35_GRAPH_CHAIN_ROLE_MISSING")
        if not chain_edges:
            raise ValueError("V35_GRAPH_CHAIN_EDGE_MISSING")
    expected_sha = hashlib.sha256(canonical_payload(payload)).hexdigest()
    if payload.get("semantic_sha") != expected_sha:
        raise ValueError("V35_GRAPH_SEMANTIC_SHA_INVALID")


def load_v35_topology(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    payload = _load_json(path)
    validate_v35_topology(payload)
    return payload


def write_v35_topology(path: Path = CONTRACT_PATH, *, workloads_path: Path | None = None, app_path: Path | None = None, baseline_path: Path | None = None) -> dict[str, Any]:
    root = Path(__file__).resolve().parents[2]
    payload = build_v35_topology(
        workloads_path=workloads_path or root / "contracts" / "runtime_workloads.json",
        app_path=app_path or root / "apps" / "web" / "src" / "App.vue",
        baseline_path=baseline_path or Path("/Users/lexi/Desktop/学习/v3_system/_ops/v3_timeline_nodes.json"),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload


__all__ = [
    "ALLOWED_EDGE_KINDS",
    "ALLOWED_NODE_TYPES",
    "BASELINE_ROLE",
    "BASELINE_SHA",
    "CONTRACT_PATH",
    "SCHEMA_VERSION",
    "build_v35_topology",
    "canonical_payload",
    "load_v35_topology",
    "validate_v35_topology",
    "write_v35_topology",
]
