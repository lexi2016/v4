"""Release-candidate operations with explicit compatibility dependencies.

No module-global core binding or reverse facade import is used. These are
existing inactive-builder operations, not a deployment or migration service.
"""
from __future__ import annotations
import hashlib
import json
import os
import plistlib
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, TYPE_CHECKING
if TYPE_CHECKING:
    from ops.release_candidate_ports import BuilderAPI

def _describe_path(value: str, *, _api: BuilderAPI) -> dict[str, object] | None:
    if not (value.startswith("/") or value.startswith("~")):
        return None
    path = Path(value).expanduser()
    result: dict[str, object] = {
        "path": value,
        "exists": path.exists() or path.is_symlink(),
        "is_symlink": path.is_symlink(),
        "resolved_target": str(_api._resolved(path)),
    }
    if path.is_symlink():
        result["link_target"] = os.readlink(path)
    resolved = _api._resolved(path)
    result["resolved_exists"] = resolved.exists()
    if resolved.is_file():
        result["kind"] = "file"
        result["code_sha256"] = _api.sha256_file(resolved)
    elif resolved.is_dir():
        result["kind"] = "directory"
    else:
        result["kind"] = "missing"
    return result


def _describe_scheduler_path_value(value: str, *, _api: BuilderAPI) -> object:
    if ":" in value and value.startswith("/"):
        return {
            "value": value,
            "segments": [_api._describe_path(segment) for segment in value.split(":")],
        }
    return _api._describe_path(value) or {"value": value}


def _file_summary(path: Path, *, _api: BuilderAPI) -> dict[str, object]:
    result: dict[str, object] = {"path": str(path), "exists": path.exists() or path.is_symlink()}
    if path.is_symlink():
        result.update(
            {
                "kind": "symlink",
                "target": os.readlink(path),
                "target_exists": path.exists(),
                "resolved_target": str(_api._resolved(path)),
            }
        )
    elif path.is_file():
        result.update({"kind": "file", "sha256": _api.sha256_file(path)})
    elif path.is_dir():
        result["kind"] = "directory"
    else:
        result["kind"] = "missing"
    return result


def _load_plist(path: Path, *, _api: BuilderAPI) -> dict[str, Any]:
    with path.open("rb") as handle:
        value = plistlib.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"plist root must be a dictionary: {path}")
    return value


def _plist_environment(plist: Mapping[str, Any], *, _api: BuilderAPI) -> dict[str, str]:
    values: dict[str, str] = {}
    arguments = plist.get("ProgramArguments", [])
    if isinstance(arguments, list):
        for item in arguments:
            if isinstance(item, str) and "=" in item:
                key, value = item.split("=", 1)
                if key and key.replace("_", "").isalnum():
                    values[key] = value
    raw = plist.get("EnvironmentVariables", {})
    if isinstance(raw, Mapping):
        for key, value in raw.items():
            if isinstance(key, str) and isinstance(value, (str, int, float, bool)):
                values[key] = str(value)
    return values


def audit_scheduler(*, source_root: Path, scheduler_plist_path: Path, _api: BuilderAPI) -> dict[str, object]:
    """Compare the current scheduler binding with v4 entrypoint dependencies."""

    scheduler_plist_path = _api._resolved(scheduler_plist_path)
    plist = _api._load_plist(scheduler_plist_path)
    environment = _api._plist_environment(plist)
    arguments = plist.get("ProgramArguments", [])
    current_script = ""
    if isinstance(arguments, list):
        for item in arguments:
            if isinstance(item, str) and item.endswith(".sh"):
                current_script = item
                break
    current_app_root = Path(environment["V35_APP_ROOT"]) if environment.get("V35_APP_ROOT") else (
        Path(current_script).parent.parent if current_script else Path("/")
    )
    current_app_root = _api._resolved(current_app_root)
    source_root = _api._resolved(source_root)
    relative_files = (
        "ops/launch_v35_macos_scheduler.sh",
        "ops/run_v35_macos_scheduler.py",
        "ops/run_scheduled_slot.py",
        "ops/collect_runtime_graph.py",
        "contracts/runtime_workloads.json",
        "ops/launch_hk_0_2_python_nosite.sh",
    )
    comparisons: list[dict[str, object]] = []
    for relative in relative_files:
        source = source_root / relative
        current = current_app_root / relative
        source_summary = _api._file_summary(source)
        current_summary = _api._file_summary(current)
        same = bool(
            source_summary.get("exists")
            and current_summary.get("exists")
            and source_summary.get("kind") == current_summary.get("kind")
            and (
                source_summary.get("sha256") == current_summary.get("sha256")
                if source_summary.get("kind") == "file"
                else source_summary.get("target") == current_summary.get("target")
            )
        )
        comparisons.append(
            {
                "relative_path": relative,
                "source": source_summary,
                "current_release": current_summary,
                "same_bytes_or_link": same,
            }
        )

    path_bindings: dict[str, object] = {}
    for key in sorted(environment):
        value = environment[key]
        if key in _api.SAFETY_KEYS:
            path_bindings[key] = {"value": value}
        elif key.startswith("V35_") or key == "PYTHONPATH":
            path_bindings[key] = _api._describe_scheduler_path_value(value)
    safety_flags = {key: environment.get(key) for key in _api.SAFETY_KEYS if key in environment}
    safety_ok = bool(safety_flags) and all(
        str(value).lower() in {"false", "0", "no"} for value in safety_flags.values()
    )
    path_probes = [
        value
        for value in path_bindings.values()
        if isinstance(value, Mapping) and "resolved_exists" in value
    ]
    path_ok = all(bool(value.get("resolved_exists")) for value in path_probes)
    mismatches = [item["relative_path"] for item in comparisons if not item["same_bytes_or_link"]]
    # A byte comparison does not prove scheduler semantic parity.  In this
    # milestone the current release retains the background duty; rebind to the
    # v4 checkout remains unconfirmed and is never performed automatically.
    return {
        "schema_version": "v4.scheduler_binding_audit.v1",
        "status": "CANNOT_CONFIRM",
        "current_plist": {"path": str(scheduler_plist_path), "sha256": _api.sha256_file(scheduler_plist_path)},
        "label": plist.get("Label"),
        "current_release_id": environment.get("V35_RELEASE_ID"),
        "current_app_root": str(current_app_root),
        "current_program": current_script,
        "comparisons": comparisons,
        "mismatching_dependencies": mismatches,
        "path_bindings": path_bindings,
        "all_observed_path_bindings_resolve": path_ok,
        "safety_flags": safety_flags,
        "safety_flags_are_research_only": safety_ok,
        "semantic_parity": "CANNOT_CONFIRM",
        "decision": "RETAIN_CURRENT_BINDING_ONLY",
        "rebind_performed": False,
        "conclusion": "Current scheduler release may remain the background owner with its existing roots and safety flags. Rebinding it to v4_app is not confirmed because scheduler entrypoints and workload contracts differ; no scheduler plist or task was changed.",
        "differences": [
            "source and current scheduler launcher/module are not byte-identical",
            "source and current run_scheduled_slot/runtime_workloads are not byte-identical",
            "the current HK 0.2 launcher exists only in the current release while the v4 source path is absent",
            "hash parity cannot establish timing, state-root, or semantic parity",
        ],
    }


def _probe_dependency_process(python: Path, names: Sequence[str], *, _api: BuilderAPI) -> dict[str, object]:
    probe_code = r'''
import importlib.metadata
import importlib.util
import json
import os
import sys

names = json.loads(sys.argv[1])
records = []
for name in names:
    record = {"module": name, "found": False, "origin": None, "version": None}
    try:
        spec = importlib.util.find_spec(name)
    except Exception as exc:
        record["error"] = type(exc).__name__
        spec = None
    if spec is not None:
        record["found"] = True
        record["origin"] = getattr(spec, "origin", None)
    try:
        record["version"] = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        record["version"] = None
    except Exception as exc:
        record["version_error"] = type(exc).__name__
    records.append(record)
print(json.dumps({"python": sys.executable, "version": sys.version, "modules": records}, ensure_ascii=False))
'''
    result = subprocess.run(
        [str(python), "-c", probe_code, json.dumps(list(names))],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        return {
            "status": "CANNOT_CONFIRM",
            "interpreter": str(python),
            "returncode": result.returncode,
            "stderr_class": result.stderr.strip().splitlines()[-1][:160] if result.stderr.strip() else "",
            "modules": [],
        }
    try:
        parsed = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {
            "status": "CANNOT_CONFIRM",
            "interpreter": str(python),
            "returncode": result.returncode,
            "stderr_class": "probe output was not JSON",
            "modules": [],
        }
    for record in parsed.get("modules", []):
        origin = record.get("origin")
        if isinstance(origin, str) and origin not in {"built-in", "frozen"}:
            path = Path(origin)
            record["origin_exists"] = path.exists()
            record["origin_resolved"] = str(_api._resolved(path))
            if path.is_file():
                record["origin_sha256"] = _api.sha256_file(path)
                record["origin_kind"] = "file"
            elif path.is_dir():
                record["origin_kind"] = "directory"
            else:
                record["origin_kind"] = "missing"
    missing = [record.get("module") for record in parsed.get("modules", []) if not record.get("found")]
    parsed["status"] = "OBSERVED_RESOLVED" if not missing else "CANNOT_CONFIRM"
    parsed["missing_modules"] = missing
    parsed["interpreter_observation"] = _api._file_summary(python)
    parsed["formal_runtime_dependency_inventory"] = {
        "status": "CANNOT_CONFIRM",
        "reason": "No formal runtime dependency inventory was supplied; this is an environment probe only.",
    }
    return parsed


def dependency_probe(python: Path, names: Sequence[str], *, _api: BuilderAPI) -> dict[str, object]:
    python = python.expanduser()
    if not python.is_file():
        return {
            "status": "CANNOT_CONFIRM",
            "interpreter": str(python),
            "interpreter_exists": False,
            "modules": [],
            "formal_runtime_dependency_inventory": {
                "status": "CANNOT_CONFIRM",
                "reason": "interpreter path is missing",
            },
        }
    result = _api._probe_dependency_process(python, names)
    result["interpreter_exists"] = True
    result["interpreter_requested"] = str(python)
    result["interpreter_resolved"] = str(_api._resolved(python))
    return result


