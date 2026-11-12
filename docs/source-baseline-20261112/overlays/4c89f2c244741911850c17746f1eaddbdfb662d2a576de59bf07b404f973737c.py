"""Read-only, generation-bound inventory of actual launchd and Main owners."""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
from datetime import datetime, timezone


def sha(raw): return hashlib.sha256(raw).hexdigest()


def observe_job(path, *, run=subprocess.run, disabled=None):
    raw = path.read_bytes(); payload = plistlib.loads(raw); label = payload["Label"]
    result = run(["/bin/launchctl", "print", f"gui/{os.getuid()}/{label}"], capture_output=True, text=True, timeout=12)
    text = result.stdout
    missing = result.returncode != 0 and "Could not find service" in result.stderr
    loaded = result.returncode == 0
    def field(pattern):
        match = re.search(pattern, text, re.M)
        return match[1] if match else None
    env = payload.get("EnvironmentVariables", {})
    observed_env = dict(re.findall(r"^\s*([^\n]+?) => ([^\n]*)$", text, re.M))
    keys = ("V4_APP_ROOT", "V4_RELEASE_ID", "V4_RELEASE_MANIFEST_PATH", "V4_RELEASE_MANIFEST_SHA256")
    effective_identity = {k: observed_env.get(k) for k in keys}
    process_exit = field(r"^\s*last exit code = (\d+)\s*$")
    manifest = Path(env["V4_RELEASE_MANIFEST_PATH"]) if env.get("V4_RELEASE_MANIFEST_PATH") else None
    metadata = json.loads(manifest.read_bytes()) if manifest and manifest.is_file() else {}
    return {"node_id": label, "owner": label, "kind": "LAUNCH_AGENT", "plist_path": str(path), "source_sha256": sha(raw),
        "exists": True, "loaded": loaded if loaded or missing else None,
        "enabled": (not disabled[label]) if disabled is not None and label in disabled else (not payload.get("Disabled", False) if disabled is not None else None),
        "loaded_observation_status": "OBSERVED" if loaded or missing else "CANNOT_CONFIRM",
        "state": field(r"^\s*state = ([^\n]+)$"), "pid": field(r"^\s*pid = (\d+)\s*$"),
        "last_process_exit_code": int(process_exit) if process_exit is not None else None,
        "business_success": None, "business_noop": None,
        "disk_identity": {k: env.get(k) for k in keys}, "effective_identity": effective_identity,
        "loaded_identity_matches_disk": all(effective_identity[k] == env.get(k) for k in keys) if loaded else None,
        "release_metadata": {k: metadata.get(k) for k in ("activation_status", "deployment_status")},
        "times": {k: payload.get(k) for k in ("StartCalendarInterval", "StartInterval", "RunAtLoad", "KeepAlive")},
        "input": {k: v for k, v in env.items() if k.endswith(("ROOT", "POINTER", "CONFIG", "CONFIG_PATH", "MANIFEST_PATH"))},
        "output": {k: payload.get(k) for k in ("StandardOutPath", "StandardErrorPath")},
        "locks": [], "retry": {"ThrottleInterval": payload.get("ThrottleInterval")}, "consumers": [],
        "argv": payload.get("ProgramArguments"), "working_directory": payload.get("WorkingDirectory")}


def publication_checks(*, stage_app: Path, api_manual: Path, inventory_module: Path):
    spec = importlib.util.spec_from_file_location("runtime_publication_inventory", inventory_module)
    inv = importlib.util.module_from_spec(spec); spec.loader.exec_module(inv)
    cfg = json.loads((stage_app / "stage_center_tick_config.json").read_bytes())
    manual = json.loads(api_manual.read_bytes())
    if manual["stage_owner_root"] != str(stage_app): raise ValueError("MANUAL_STAGE_BINDING_MISMATCH")
    checks = []
    for binding in [cfg["research_owner_binding"], *cfg.get("research_historical_owner_bindings", [])]:
        app = Path(binding["app_root"]); path = app.parent / "release-manifest.json"
        raw = path.read_bytes()
        if sha(raw) != binding["manifest_sha256"]: raise ValueError("PRODUCER_MANIFEST_SHA_CHANGED")
        manifest = json.loads(raw)
        if binding["release_id"] != app.parent.name: raise ValueError("PRODUCER_RELEASE_ID_MISMATCH")
        rows = inv.inventory_tree(app)
        if manifest["application_inventory"] != {"entries": rows, "entry_count": len(rows), "aggregate_sha256": inv.inventory_digest(rows)}:
            raise ValueError("PRODUCER_RELEASE_INVENTORY_CHANGED")
        checks.append({"producer_release": binding["release_id"], "producer_manifest_sha256": sha(raw),
            "consumer_config_sha256": sha((stage_app / "stage_center_tick_config.json").read_bytes()),
            "manual_reference_sha256": sha(api_manual.read_bytes()), "receipt_publication": "NOT_RUN"})
    return checks


def build(*, launch_agents: Path, graph_path: Path | None = None, tasks_path: Path | None = None):
    disabled_result = subprocess.run(["/bin/launchctl", "print-disabled", f"gui/{os.getuid()}"], capture_output=True, text=True, timeout=12)
    disabled = dict((key, value == "true") for key, value in re.findall(r'"([^"\n]+)" => (true|false)', disabled_result.stdout)) if disabled_result.returncode == 0 else None
    nodes = [observe_job(path, disabled=disabled) for path in sorted(launch_agents.glob("com.lexi.*.plist"))]
    main = next(row for row in nodes if row["node_id"] == "com.lexi.v4.scheduler")
    app = Path(main["disk_identity"]["V4_APP_ROOT"])
    catalog_path = app / "contracts/runtime_workloads.json"; raw = catalog_path.read_bytes(); catalog = json.loads(raw)
    for row in catalog["workloads"]:
        nodes.append({"node_id": row["workload_id"], "kind": "MAIN_CATALOG", "owner": row["owner_id"],
            "generation": main["disk_identity"]["V4_RELEASE_ID"], "source_sha256": sha(raw),
            "exists": True, "loaded": main["loaded"], "enabled": row["enabled"],
            "business_success": None, "business_noop": None, "times": row["slots"],
            "input": {k: row[k] for k in ("scheduled_date_role", "signal_date_role", "target_date_role", "market_scope")},
            "output": list(row["command"]), "locks": ["ExecutionLedger.try_claim_workload"],
            "retry": "existing dispatcher failure_class/backoff/max_attempts", "consumers": []})
    hooks = []; parsed = []
    hook_files = ["ops/run_v4_macos_scheduler_daemon.py", "ops/run_stage_center_nodes.py", "v4/manager_workbench/supervisor.py"]
    hook_files += [str(path.relative_to(app)) for path in sorted((app / "infrastructure/scheduling").glob("executor_registry*.py"))]
    for relative in hook_files:
        path = app / relative
        if not path.exists(): continue
        body = path.read_bytes()
        tree = ast.parse(body)
        parsed.append({"path": str(path), "source_sha256": sha(body), "parse_status": "PASS"})
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and any(token in node.name.lower() for token in ("after_stage", "recapture", "milestone", "completion", "hook")):
                hooks.append({"owner": main["node_id"], "file": str(path), "line": node.lineno, "end_line": node.end_lineno, "name": node.name, "kind": type(node).__name__, "source_sha256": sha(body)})
    prior_graph = json.loads(graph_path.read_bytes()) if graph_path else None
    reused_tasks = []
    if tasks_path:
        prior_tasks = json.loads(tasks_path.read_bytes())
        def references(value):
            if isinstance(value, dict):
                if "path" in value and "sha256" in value: yield value
                for nested in value.values(): yield from references(nested)
            elif isinstance(value, list):
                for nested in value: yield from references(nested)
        for task in prior_tasks["tasks"]:
            sources = []
            for ref in references(task):
                path = Path(ref["path"])
                try:
                    digest = sha(path.read_bytes())
                    sources.append({"path": str(path), "source_sha256": digest, "matches_prior": digest == ref.get("sha256")})
                except OSError:
                    sources.append({"path": str(path), "source_sha256": None, "matches_prior": False})
            owner_label = task.get("parent") or task["owner"]
            parent = next((row for row in nodes if row["node_id"] in {owner_label, task["id"]}), None)
            reused_tasks.append({"node_id": task["id"], "owner": task["owner"], "kind": task["kind"],
                "generation": (parent or main)["disk_identity"]["V4_RELEASE_ID"], "source_sha256": sha(tasks_path.read_bytes()),
                "sources": sources, "source_status": "MATCHED_PRIOR_SCOPE" if all(r["matches_prior"] for r in sources) else "CANNOT_CONFIRM_DRIFT",
                "exists": True, "loaded": parent["loaded"] if parent else None, "enabled": task["enabled"],
                "business_success": None, "business_noop": None, "times": task["slots"],
                "input": task["inputs"], "output": task["products"], "locks": task["read_write_locks"],
                "retry": task["retry"], "consumers": task["consumers"]})
    identity = {"nodes": nodes, "registered_tasks": reused_tasks, "internal_hooks": hooks, "fresh_hook_source_files": parsed, "catalog_sha256": sha(raw),
                "reused_graph_sha256": sha(graph_path.read_bytes()) if graph_path else None}
    generation = sha(json.dumps(identity, sort_keys=True).encode())
    return {"schema_version": "v4.runtime_governance_registry.v1", "generated_at": datetime.now(timezone.utc).isoformat(),
        "generation": generation, **identity, "previous_graph_file_count": len(prior_graph.get("nodes", [])) if prior_graph else None,
        "status": "OBSERVATIONAL_ONLY", "RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--launch-agents", type=Path, default=Path.home() / "Library/LaunchAgents")
    parser.add_argument("--graph", type=Path)
    parser.add_argument("--tasks", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(launch_agents=args.launch_agents, graph_path=args.graph, tasks_path=args.tasks)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out: json.dump(result, out, ensure_ascii=False, indent=2)
    print(json.dumps({"generation": result["generation"], "node_count": len(result["nodes"]), "output": str(args.output)}))
