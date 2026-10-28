"""Pure activation-gate checks shared by isolated Mac canary tools."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from datetime import datetime, timezone
from typing import Iterable, Mapping, Sequence
from uuid import UUID, uuid4

_SANDBOX_IDENTITY_SCHEMA = "v4.manager_research.canary_sandbox_identity.v1"
_SANDBOX_PREFIX = {
    "announcement": ("manager-state-canary-",),
    "materializer": ("manager-state-canary-", "manager-materializer-replay-canary-"),
    "us": ("manager-us-activation-canary-",),
}
_CANARY_ENTRYPOINTS = {
    "announcement": "ops/run_manager_announcement_owner_canary.py",
    "materializer": "ops/run_manager_materializer_offline_replay.py",
    "us": "ops/run_manager_us_activation_canary.py",
}
# The replay worker and the replayed 15:30 writer are intentionally allowed to
# live in different app roots.  Worker identity is pinned by sandbox/command
# identity; materializer input identity must contain only files actually loaded
# from the spec-selected writer root.
_MATERIALIZER_REPLAY_WORKER_FILES = (
    "ops/run_manager_materializer_offline_replay.py",
    "v4/manager_research/activation_canary.py",
    "v4/manager_research/materializer_replay.py",
)
_MATERIALIZER_RUNTIME_FILES = (
    "ops/materialize_manager_close_discovery.py",
    "apps/api/v35_api/manager_workbench_router.py",
    "contracts/trading_calendar.py",
    "contracts/market_calendar_2026.json",
    "domains/manager_close_discovery.py",
    "domains/manager_catalyst_tracking.py",
    "domains/manager_research_evidence.py",
    "domains/manager_close_rebound.py",
    "infrastructure/manager_input_attestation.py",
    "infrastructure/interprocess_lock.py",
    "infrastructure/owned_io.py",
    "upstreams/v3_shared_data/shared_data/hk_auction_0920.py",
    # Importing shared_data.hk_auction_0920 first executes the shared_data
    # package initializer, which imports constants/store; store imports
    # collectors, allowlist, hashing and paths. hk_0_2 reaches the same local
    # registry, consumer, hash, path and store modules. Pin the complete local
    # Python import closure, rather than only the first imported file.
    "upstreams/v3_shared_data/shared_data/__init__.py",
    "upstreams/v3_shared_data/shared_data/allowlist.py",
    "upstreams/v3_shared_data/shared_data/collectors.py",
    "upstreams/v3_shared_data/shared_data/constants.py",
    "upstreams/v3_shared_data/shared_data/consumer.py",
    "upstreams/v3_shared_data/shared_data/hashing.py",
    "upstreams/v3_shared_data/shared_data/hk_0_2.py",
    "upstreams/v3_shared_data/shared_data/hk_security_master.py",
    "upstreams/v3_shared_data/shared_data/paths.py",
    "upstreams/v3_shared_data/shared_data/store.py",
    # Executed package initializers for the other imported writer modules.
    "apps/__init__.py",
    "apps/api/__init__.py",
    "apps/api/v35_api/__init__.py",
    "contracts/__init__.py",
    "infrastructure/__init__.py",
)
# Compatibility name retained for canary worker inventory.
_MATERIALIZER_APP_FILES = _MATERIALIZER_REPLAY_WORKER_FILES + _MATERIALIZER_RUNTIME_FILES


def _materializer_app_inventory(
    app: Path, *, tolerate_missing: bool=False, include_worker_files: bool=True,
) -> dict[str, str]:
    from infrastructure.owned_io import SafeRoot
    app=Path(app)
    io=SafeRoot(app)
    inventory={}
    source_files = _MATERIALIZER_APP_FILES if include_worker_files else _MATERIALIZER_RUNTIME_FILES
    for rel in source_files:
        path=app/rel
        if path.is_symlink():
            if tolerate_missing:
                inventory[rel]="SYMLINK"
                continue
            raise ValueError("MATERIALIZER_APP_SOURCE_SYMLINK")
        if not path.is_file():
            if tolerate_missing:
                inventory[rel]="MISSING"
                continue
            raise ValueError("MATERIALIZER_APP_SOURCE_MISSING:"+rel)
        inventory[rel]=hashlib.sha256(io.read_bytes(rel,max_bytes=16*1024*1024)).hexdigest()
    return inventory


def _safe_tree_identity(root: Path) -> str:
    root = Path(root)
    if not root.is_absolute() or root.resolve() != root or root.is_symlink() or not root.is_dir():
        raise ValueError("CANARY_IDENTITY_TREE_ROOT_INVALID")
    rows: dict[str, str] = {}
    total = 0
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ValueError("CANARY_IDENTITY_TREE_SYMLINK")
        if not path.is_file():
            continue
        raw = path.read_bytes()
        total += len(raw)
        if len(rows) >= 8192 or total > 64 * 1024 * 1024:
            raise ValueError("CANARY_IDENTITY_TREE_BUDGET_EXCEEDED")
        rows[path.relative_to(root).as_posix()] = hashlib.sha256(raw).hexdigest()
    return _digest_mapping(rows)


def _exact_path(value: str | Path, code: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts or path.resolve() != path or path.is_symlink():
        raise ValueError(code)
    return path


def _sandbox_locations(kind: str, data_root: str | Path, receipt_path: str | Path,
                       identity_path: str | Path) -> tuple[Path, Path, Path, Path]:
    prefixes = _SANDBOX_PREFIX.get(kind)
    if prefixes is None:
        raise ValueError("CANARY_SANDBOX_KIND_INVALID")
    data = _exact_path(data_root, "CANARY_SANDBOX_DATA_ROOT_INVALID")
    sandbox = data.parent
    temp_root = Path(tempfile.gettempdir()).resolve()
    if (sandbox.parent != temp_root or not any(re.fullmatch(re.escape(prefix) + r"[a-z0-9_]{8}", sandbox.name) for prefix in prefixes)
            or sandbox.resolve() != sandbox or sandbox.is_symlink() or not sandbox.is_dir()):
        raise ValueError("CANARY_SANDBOX_TEMP_ROOT_REQUIRED")
    if not data.is_dir() or data.parent != sandbox:
        raise ValueError("CANARY_SANDBOX_DATA_ROOT_INVALID")
    receipt = _exact_path(receipt_path, "CANARY_SANDBOX_RECEIPT_PATH_INVALID")
    identity = _exact_path(identity_path, "CANARY_SANDBOX_IDENTITY_PATH_INVALID")
    for path in (receipt, identity):
        if sandbox not in path.parents or data == path or data in path.parents or path == sandbox:
            raise ValueError("CANARY_SANDBOX_SIDECAR_PATH_INVALID")
        cursor = path.parent
        while cursor != sandbox:
            if sandbox not in cursor.parents or cursor.is_symlink():
                raise ValueError("CANARY_SANDBOX_SIDECAR_PATH_INVALID")
            cursor = cursor.parent
        if not path.parent.is_dir():
            raise ValueError("CANARY_SANDBOX_SIDECAR_PARENT_MISSING")
    if receipt == identity:
        raise ValueError("CANARY_SANDBOX_SIDECAR_PATH_INVALID")
    return sandbox, data, receipt, identity


def _canary_app_inventory(app: Path, kind: str) -> dict[str, str]:
    if kind == "materializer":
        return _materializer_app_inventory(app)
    from infrastructure.owned_io import SafeRoot
    io = SafeRoot(app)
    from infrastructure.scheduling.manager_announcement_supervisor import binding_inventory
    inventory = binding_inventory(app)
    paths = ["ops/run_manager_announcement_owner_canary.py"]
    if kind == "us":
        paths.extend(("ops/run_manager_us_activation_canary.py", "ops/us_market_digest.py",
            "ops/materialize_research_peripherals.py"))
    for rel in paths:
        inventory[rel] = hashlib.sha256(io.read_bytes(rel, max_bytes=16 * 1024 * 1024)).hexdigest()
    return inventory


def _sandbox_argv(argv: Sequence[str], *, identity_path: Path, receipt_path: Path,
                  data_root: Path, kind: str, security_master_root: Path | None) -> list[str]:
    result = list(argv)
    if any(not isinstance(part, str) for part in result):
        raise ValueError("CANARY_SANDBOX_COMMAND_INVALID")
    data_flag = "--data-root" if kind == "us" else "--state-root"
    for flag, expected, placeholder in (
        (data_flag, str(data_root), None),
        ("--sandbox-identity", str(identity_path), "{sandbox_identity}"),
        ("--receipt", str(receipt_path), None),
    ):
        if result.count(flag) != 1:
            raise ValueError("CANARY_SANDBOX_COMMAND_IDENTITY_MISMATCH")
        index = result.index(flag) + 1
        if index >= len(result) or result[index] != expected:
            raise ValueError("CANARY_SANDBOX_COMMAND_IDENTITY_MISMATCH")
        if placeholder is not None:
            result[index] = placeholder
    if kind == "announcement":
        if result.count("--security-master-root") != 1 or security_master_root is None:
            raise ValueError("CANARY_SANDBOX_COMMAND_IDENTITY_MISMATCH")
        index = result.index("--security-master-root") + 1
        if index >= len(result) or Path(result[index]).expanduser() != security_master_root:
            raise ValueError("CANARY_SANDBOX_COMMAND_IDENTITY_MISMATCH")
    elif result.count("--security-master-root"):
        raise ValueError("CANARY_SANDBOX_COMMAND_IDENTITY_MISMATCH")
    return result


def write_canary_sandbox_identity(identity_path: str | Path, kind: str, *, data_root: str | Path,
                                  receipt_path: str | Path, app_root: str | Path,
                                  argv: Sequence[str], security_master_root: str | Path | None = None) -> dict:
    """Persist a per-run identity before an owner canary may write.

    The state/data root, receipt and identity must all belong to a unique
    direct child of the OS temporary directory. The identity binds the exact
    owner entrypoint, source bytes, static input tree and invocation arguments.
    A marker file alone can never authorize a writer.
    """
    from infrastructure.owned_io import SafeRoot

    app = _exact_path(app_root, "CANARY_SANDBOX_APP_ROOT_INVALID")
    sandbox, data, receipt, identity = _sandbox_locations(kind, data_root, receipt_path, identity_path)
    owner = _exact_path(app / _CANARY_ENTRYPOINTS[kind], "CANARY_SANDBOX_OWNER_INVALID")
    if owner.parent.parent != app or not owner.is_file():
        raise ValueError("CANARY_SANDBOX_OWNER_INVALID")
    master = (_exact_path(security_master_root, "CANARY_SANDBOX_SECURITY_MASTER_INVALID")
              if security_master_root is not None else None)
    if kind == "announcement":
        if (master is None or not master.is_dir() or master == data
                or data in master.parents or master in data.parents):
            raise ValueError("CANARY_SANDBOX_SECURITY_MASTER_INVALID")
    elif master is not None:
        raise ValueError("CANARY_SANDBOX_SECURITY_MASTER_INVALID")
    if identity.exists() or receipt.exists():
        raise ValueError("CANARY_SANDBOX_OUTPUT_ALREADY_EXISTS")
    if identity.with_name(identity.name + ".started").exists():
        raise ValueError("CANARY_SANDBOX_OUTPUT_ALREADY_EXISTS")
    normalized_argv = _sandbox_argv(argv, identity_path=identity, receipt_path=receipt,
                                    data_root=data, kind=kind, security_master_root=master)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    doc = {
        "schema_version": _SANDBOX_IDENTITY_SCHEMA,
        "kind": kind,
        "run_id": uuid4().hex,
        "created_at_utc": created,
        "sandbox_root": str(sandbox),
        "data_root": str(data),
        "identity_path": str(identity),
        "receipt_path": str(receipt),
        "app_root": str(app),
        "owner_entrypoint": str(owner),
        "owner_entrypoint_sha256": hashlib.sha256(owner.read_bytes()).hexdigest(),
        "app_inventory_sha256": _digest_mapping(_canary_app_inventory(app, kind)),
        "data_tree_sha256": _safe_tree_identity(data),
        "security_master_root": str(master) if master is not None else None,
        "security_master_tree_sha256": _safe_tree_identity(master) if master is not None else None,
        "argv_template": normalized_argv,
        "argv_sha256": hashlib.sha256(json.dumps(normalized_argv, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    }
    SafeRoot(identity.parent).write_bytes(identity.name,
        (json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8"),
        require_absent=True)
    return doc


def validate_canary_sandbox_identity(identity_path: str | Path, kind: str, *, data_root: str | Path,
                                     receipt_path: str | Path, app_root: str | Path,
                                     argv: Sequence[str], security_master_root: str | Path | None = None) -> dict:
    """Revalidate every per-run path/source/input/argv identity before import of a writer."""
    from infrastructure.owned_io import SafeRoot

    app = _exact_path(app_root, "CANARY_SANDBOX_APP_ROOT_INVALID")
    sandbox, data, receipt, identity = _sandbox_locations(kind, data_root, receipt_path, identity_path)
    try:
        raw = SafeRoot(identity.parent).read_bytes(identity.name, max_bytes=1024 * 1024)
        doc = json.loads(raw)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("CANARY_SANDBOX_IDENTITY_INVALID") from exc
    if not isinstance(doc, dict) or doc.get("schema_version") != _SANDBOX_IDENTITY_SCHEMA or doc.get("kind") != kind:
        raise ValueError("CANARY_SANDBOX_IDENTITY_INVALID")
    try:
        run_id = str(doc.get("run_id") or "")
        if UUID(run_id).version != 4 or len(run_id) != 32 or run_id != run_id.lower():
            raise ValueError
        created = datetime.fromisoformat(str(doc.get("created_at_utc") or ""))
        if created.tzinfo is None:
            raise ValueError
        age = (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds()
        if age < -30 or age > 15 * 60:
            raise ValueError
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("CANARY_SANDBOX_IDENTITY_EXPIRED_OR_INVALID") from exc
    master = (_exact_path(security_master_root, "CANARY_SANDBOX_SECURITY_MASTER_INVALID")
              if security_master_root is not None else None)
    if kind == "announcement":
        if (master is None or not master.is_dir() or master == data
                or data in master.parents or master in data.parents):
            raise ValueError("CANARY_SANDBOX_SECURITY_MASTER_INVALID")
    elif master is not None:
        raise ValueError("CANARY_SANDBOX_SECURITY_MASTER_INVALID")
    owner = _exact_path(app / _CANARY_ENTRYPOINTS[kind], "CANARY_SANDBOX_OWNER_INVALID")
    app_inventory = _canary_app_inventory(app, kind)
    normalized_argv = _sandbox_argv(argv, identity_path=identity, receipt_path=receipt,
                                    data_root=data, kind=kind, security_master_root=master)
    argv_sha = hashlib.sha256(json.dumps(normalized_argv, ensure_ascii=False,
        sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    if doc.get("argv_template") != normalized_argv or doc.get("argv_sha256") != argv_sha:
        raise ValueError("CANARY_SANDBOX_COMMAND_IDENTITY_MISMATCH")
    if (doc.get("sandbox_root") != str(sandbox) or doc.get("data_root") != str(data)
            or doc.get("identity_path") != str(identity) or doc.get("receipt_path") != str(receipt)
            or doc.get("app_root") != str(app) or doc.get("owner_entrypoint") != str(owner)
            or doc.get("owner_entrypoint_sha256") != hashlib.sha256(owner.read_bytes()).hexdigest()
            or doc.get("app_inventory_sha256") != _digest_mapping(app_inventory)
            or doc.get("data_tree_sha256") != _safe_tree_identity(data)
            or doc.get("security_master_root") != (str(master) if master is not None else None)
            or doc.get("security_master_tree_sha256") != (_safe_tree_identity(master) if master is not None else None)
            or receipt.exists() or identity.with_name(identity.name + ".started").exists()):
        raise ValueError("CANARY_SANDBOX_IDENTITY_INVALID")
    return {
        "status": "VERIFIED",
        "run_id": run_id,
        "kind": kind,
        "sandbox_root": str(sandbox),
        "data_root": str(data),
        "identity_path": str(identity),
        "receipt_path": str(receipt),
        "app_root": str(app),
        "owner_entrypoint_sha256": doc["owner_entrypoint_sha256"],
        "app_inventory_sha256": doc["app_inventory_sha256"],
        "data_tree_sha256": doc["data_tree_sha256"],
        "argv_sha256": argv_sha,
        "identity_sha256": hashlib.sha256(raw).hexdigest(),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def claim_canary_sandbox_identity(identity_path: str | Path, kind: str, **kwargs) -> dict:
    """Validate and atomically consume an identity before importing a writer."""
    from infrastructure.owned_io import SafeRoot
    verified = validate_canary_sandbox_identity(identity_path, kind, **kwargs)
    identity = _exact_path(identity_path, "CANARY_SANDBOX_IDENTITY_PATH_INVALID")
    started = identity.with_name(identity.name + ".started")
    claim = {"run_id": verified["run_id"], "identity_sha256": verified["identity_sha256"],
             "started_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    SafeRoot(started.parent).write_bytes(started.name,
        (json.dumps(claim, sort_keys=True, separators=(",", ":")) + "\n").encode(), require_absent=True)
    return verified


def _parts(path: str) -> list[str]:
    value=str(path)
    if not value or value.startswith("/") or "\\" in value:
        return []
    parts=value.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return []
    return parts


def _namespace(path: str) -> str:
    parts=_parts(path)
    return "/".join(parts[:2]) if len(parts)>=2 else (parts[0] if parts else "")


def _directory(path: str) -> str:
    parts=_parts(path)
    return "/".join(parts[:-1]) if len(parts)>=2 else ""


def evaluate_writer_namespaces(*, announcement_paths: Iterable[str], materializer_paths: Iterable[str], concurrent_paths: Iterable[str]) -> dict:
    announcement = {str(path) for path in announcement_paths}
    materializer = {str(path) for path in materializer_paths}
    concurrent = {str(path) for path in concurrent_paths}
    overlap = sorted(announcement & materializer)
    invalid=sorted(path for path in announcement|materializer|concurrent
        if len(_parts(path))<2 or not _directory(path))
    announcement_ns={_namespace(path) for path in announcement if _namespace(path)}
    materializer_ns={_namespace(path) for path in materializer if _namespace(path)}
    concurrent_ns={_namespace(path) for path in concurrent if _namespace(path)}
    allowed_ns=announcement_ns | materializer_ns
    unexpected_ns=sorted(concurrent_ns-allowed_ns)
    missing_ns=sorted(allowed_ns-concurrent_ns)
    namespace_overlap=sorted(announcement_ns & materializer_ns)
    announcement_dirs={_directory(path) for path in announcement if _directory(path)}
    materializer_dirs={_directory(path) for path in materializer if _directory(path)}
    concurrent_dirs={_directory(path) for path in concurrent if _directory(path)}
    allowed_dirs=announcement_dirs | materializer_dirs
    unexpected_dirs=sorted(concurrent_dirs-allowed_dirs)
    missing_dirs=sorted(allowed_dirs-concurrent_dirs)
    status = "PASS" if (
        announcement and materializer and concurrent and not invalid and not overlap
        and not namespace_overlap and not unexpected_ns and not missing_ns
        and not unexpected_dirs and not missing_dirs
    ) else "STOP"
    return {
        "schema_version": "v4.manager_research.activation_canary_decision.v2",
        "status": status,
        "overlap": overlap,
        "namespace_overlap": namespace_overlap,
        "directory_overlap": sorted(announcement_dirs & materializer_dirs),
        "invalid_paths": invalid,
        "unexpected_concurrent_namespaces": unexpected_ns,
        "missing_concurrent_namespaces": missing_ns,
        "unexpected_concurrent_directories": unexpected_dirs,
        "missing_concurrent_directories": missing_dirs,
        "announcement_namespaces": sorted(announcement_ns),
        "materializer_namespaces": sorted(materializer_ns),
        "concurrent_namespaces": sorted(concurrent_ns),
        "announcement_write_count": len(announcement),
        "materializer_write_count": len(materializer),
        "concurrent_write_count": len(concurrent),
        "production_allowed": False,
        "buy_gate_updated": False,
        "orders_sent": False,
    }


def _valid_announcement_recovery_witness(value: object) -> bool:
    if not isinstance(value, Mapping) or value.get("schema_version") != "v4.manager_research.announcement_recovery_witness.v1":
        return False
    date = str(value.get("target_trade_date") or "")
    interrupted = value.get("interrupted") if isinstance(value.get("interrupted"), Mapping) else {}
    recovered = value.get("recovered") if isinstance(value.get("recovered"), Mapping) else {}
    return (bool(re.fullmatch(r"\d{8}", date))
        and bool(re.fullmatch(r"[0-9a-f]{32}", str(interrupted.get("run_id") or "")))
        and bool(re.fullmatch(r"[0-9a-f]{32}", str(recovered.get("run_id") or "")))
        and interrupted.get("run_id") != recovered.get("run_id")
        and interrupted.get("state") == "RUNNING" and recovered.get("state") == "PARTIAL")


def evaluate_recovery(*, interruption_observed: bool, announcement_returncode: int, materializer_returncode: int,
                      recovery_paths: Iterable[str], allowed_paths: Iterable[str], pre_interrupt_change_observed: bool = False,
                      owner_transaction_state: object | None = None) -> dict:
    recovery={str(path) for path in recovery_paths}
    allowed={str(path) for path in allowed_paths}
    allowed_dirs={_directory(path) for path in allowed if _directory(path)}
    invalid=sorted(path for path in recovery|allowed
        if len(_parts(path))<2 or not _directory(path))
    unexpected=sorted(path for path in recovery if _directory(path) not in allowed_dirs)
    gaps=[]
    if interruption_observed is not True:gaps.append("INTERRUPTION_NOT_OBSERVED")
    if pre_interrupt_change_observed is not True:gaps.append("PRE_INTERRUPT_CHANGE_NOT_OBSERVED")
    if not _valid_announcement_recovery_witness(owner_transaction_state):
        gaps.append("OWNER_TRANSACTION_STATE_UNVERIFIED")
    if not recovery:gaps.append("RECOVERY_NO_WRITES_OBSERVED")
    if invalid:gaps.append("RECOVERY_PATH_INVALID")
    if announcement_returncode != 0:gaps.append("ANNOUNCEMENT_RECOVERY_FAILED")
    if materializer_returncode != 0:gaps.append("MATERIALIZER_RECOVERY_FAILED")
    if unexpected:gaps.append("RECOVERY_WROTE_OUTSIDE_VERIFIED_DIRECTORIES")
    hard_failures={"INTERRUPTION_NOT_OBSERVED", "PRE_INTERRUPT_CHANGE_NOT_OBSERVED",
        "RECOVERY_NO_WRITES_OBSERVED", "RECOVERY_PATH_INVALID", "ANNOUNCEMENT_RECOVERY_FAILED",
        "MATERIALIZER_RECOVERY_FAILED", "RECOVERY_WROTE_OUTSIDE_VERIFIED_DIRECTORIES"}
    if hard_failures.intersection(gaps):
        status="STOP"
    elif "OWNER_TRANSACTION_STATE_UNVERIFIED" in gaps:
        status="CANNOT_CONFIRM"
    else:
        status="PASS"
    return {
        "schema_version":"v4.manager_research.writer_recovery_decision.v3",
        "status":status,
        "gaps":sorted(set(gaps)),
        "allowed_directories":sorted(allowed_dirs),
        "unexpected_recovery_writes":unexpected,
        "production_allowed":False,"buy_gate_updated":False,"orders_sent":False,
    }


def evaluate_us_activation(raw: dict) -> dict:
    import re
    evidence=dict(raw)
    gaps=[]
    if raw.get("producer_invoked") is not True:gaps.append("US_PRODUCER_NOT_INVOKED")
    if raw.get("producer_status") not in {"READY","PARTIAL"}:gaps.append("US_PRODUCER_NOT_READY")
    payload=str(raw.get("payload_sha256") or "")
    lineage=raw.get("reader_lineage") if isinstance(raw.get("reader_lineage"),dict) else {}
    if not re.fullmatch(r"[0-9a-f]{64}",payload):gaps.append("US_PRODUCER_PAYLOAD_SHA_INVALID")
    if lineage.get("status")!="VERIFIED":gaps.append("US_MANAGER_READER_LINEAGE_UNVERIFIED")
    if payload and lineage.get("payload_sha256")!=payload:gaps.append("US_PRODUCER_MANAGER_PAYLOAD_MISMATCH")
    for key in ("receipt_sha256","manifest_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}",str(lineage.get(key) or "")):gaps.append("US_MANAGER_READER_"+key.upper()+"_INVALID")
    if raw.get("bridge_status") not in {"READY","PARTIAL"}:gaps.append("US_MANAGER_BRIDGE_NOT_READY")
    if raw.get("expected_us_session")!=raw.get("producer_us_session"):gaps.append("US_SESSION_IDENTITY_MISMATCH")
    if raw.get("source_unchanged") is not True:gaps.append("US_CANARY_SOURCE_MUTATED")
    return {"schema_version":"v4.manager_research.us_activation_decision.v1","status":"PASS" if not gaps else "STOP",
            "gaps":sorted(set(gaps)),"evidence":evidence,"production_allowed":False,"buy_gate_updated":False,"orders_sent":False}


def _digest_mapping(value: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def _changed(before: dict[str, str], after: dict[str, str]) -> set[str]:
    return {key for key in set(before)|set(after) if before.get(key)!=after.get(key)}


def _stored_command_identity(value: object, role: str, app: Path, *,
                             expected_security_master_root: Path | None = None) -> bool:
    import re
    if not isinstance(value,dict) or value.get("role")!=role:
        return False
    argv=value.get("argv_template")
    if not isinstance(argv,list) or not argv or any(not isinstance(part,str) for part in argv):
        return False
    argv_sha=str(value.get("argv_sha256") or "")
    expected_argv_sha=hashlib.sha256(json.dumps(argv,ensure_ascii=False,sort_keys=True,indent=2).encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{64}",argv_sha) or argv_sha!=expected_argv_sha:
        return False
    executable=Path(str(value.get("executable_path") or ""))
    resolved=Path(str(value.get("executable_resolved") or ""))
    if (not executable.is_absolute() or not resolved.is_absolute() or not executable.is_file()
            or executable.resolve()!=resolved or not re.fullmatch(r"[0-9a-f]{64}",str(value.get("executable_sha256") or ""))):
        return False
    try:
        if hashlib.sha256(resolved.read_bytes()).hexdigest()!=value.get("executable_sha256"):
            return False
    except OSError:
        return False
    state_positions=[i for i,part in enumerate(argv) if part=="{state_root}"]
    if len(state_positions)!=1 or state_positions[0]==0 or argv[state_positions[0]-1]!="--state-root":
        return False
    if argv.count("--state-root")!=1 or argv.count("--trade-date")!=1:
        return False
    if argv[0]!=str(executable):
        return False
    date_i=argv.index("--trade-date")+1
    if date_i>=len(argv) or not re.fullmatch(r"\d{8}",argv[date_i]):
        return False
    if any(option in argv for option in {"--universe-only","--universe-root","--universe-owner-root",
            "--data-root","--futu-python","--news-owner-root","--rebound-authority-root"}):
        return False
    entrypoint=Path(str(value.get("entrypoint_path") or ""))
    entrypoint_sha=str(value.get("entrypoint_sha256") or "")
    if (not entrypoint.is_absolute() or entrypoint.resolve()!=entrypoint or not entrypoint.is_file()
            or entrypoint.is_symlink() or not re.fullmatch(r"[0-9a-f]{64}",entrypoint_sha)):
        return False
    try:
        if hashlib.sha256(entrypoint.read_bytes()).hexdigest()!=entrypoint_sha:
            return False
    except OSError:
        return False
    if role=="announcement":
        expected=(app/"ops/run_manager_announcement_owner_canary.py").resolve()
        if value.get("entrypoint_kind")=="module":
            has_entrypoint=argv.count("-m")==1 and argv[argv.index("-m")+1:argv.index("-m")+2]==["ops.run_manager_announcement_owner_canary"]
        else:
            has_entrypoint=any(Path(part).is_absolute() and Path(part).resolve()==expected for part in argv)
        if argv.count("--security-master-root")!=1:
            return False
        master_i=argv.index("--security-master-root")+1
        master=Path(argv[master_i]).expanduser() if master_i<len(argv) else Path()
        identity_i=argv.index("--sandbox-identity")+1 if argv.count("--sandbox-identity")==1 else -1
        receipt_i=argv.index("--receipt")+1 if argv.count("--receipt")==1 else -1
        canary_paths=(identity_i>=0 and receipt_i>=0 and identity_i<len(argv) and receipt_i<len(argv)
            and argv[identity_i]=="{sandbox_identity}" and argv[receipt_i]=="{receipt}")
        return (has_entrypoint and canary_paths and master.is_absolute() and master.resolve()==master and master.is_dir()
            and expected_security_master_root is not None and master==expected_security_master_root.resolve()
            and entrypoint.resolve()==expected
            and value.get("entrypoint_name")=="ops.run_manager_announcement_owner_canary")
    expected=(app/"ops/run_manager_materializer_offline_replay.py").resolve()
    if value.get("entrypoint_kind")=="module":
        has_entrypoint=argv.count("-m")==1 and argv[argv.index("-m")+1:argv.index("-m")+2]==["ops.run_manager_materializer_offline_replay"]
    else:
        has_entrypoint=any(Path(part).is_absolute() and Path(part).resolve()==expected for part in argv)
    if argv.count("--sandbox-identity")!=1 or argv.count("--receipt")!=1:
        return False
    identity_i=argv.index("--sandbox-identity")+1; receipt_i=argv.index("--receipt")+1
    if (identity_i>=len(argv) or receipt_i>=len(argv) or argv[identity_i]!="{sandbox_identity}" or argv[receipt_i]!="{receipt}"):
        return False
    if argv.count("--replay-spec")!=1 or argv.count("--replay-spec-sha256")!=1:
        return False
    spec_i=argv.index("--replay-spec")+1; sha_i=argv.index("--replay-spec-sha256")+1
    if spec_i>=len(argv) or sha_i>=len(argv):
        return False
    spec=Path(argv[spec_i]).expanduser(); replay_sha=argv[sha_i]
    if (not spec.is_absolute() or spec.resolve()!=spec or spec.is_symlink() or not spec.is_file()
            or not re.fullmatch(r"[0-9a-f]{64}",replay_sha) or hashlib.sha256(spec.read_bytes()).hexdigest()!=replay_sha):
        return False
    return (has_entrypoint and entrypoint.resolve()==expected and entrypoint.name=="run_manager_materializer_offline_replay.py"
        and value.get("entrypoint_name")=="ops.run_manager_materializer_offline_replay"
        and value.get("replay_spec_path")==str(spec) and value.get("replay_spec_sha256")==replay_sha)


def _announcement_result_valid(value: object) -> bool:
    if not isinstance(value,dict) or value.get("returncode")!=0 or value.get("timed_out") is not False:
        return False
    for line in reversed(str(value.get("stdout_tail") or "").splitlines()):
        try:
            result=json.loads(line)
        except (ValueError,TypeError):
            continue
        sandbox=result.get("sandbox_identity") if isinstance(result,dict) else None
        identity_valid=(isinstance(sandbox,dict) and sandbox.get("status")=="VERIFIED"
            and sandbox.get("kind")=="announcement"
            and bool(re.fullmatch(r"[0-9a-f]{32}",str(sandbox.get("run_id") or "")))
            and all(re.fullmatch(r"[0-9a-f]{64}",str(sandbox.get(key) or ""))
                for key in ("identity_sha256","owner_entrypoint_sha256","app_inventory_sha256","data_tree_sha256","argv_sha256")))
        return (isinstance(result,dict) and identity_valid
            and result.get("schema_version")=="v4.manager_research.announcement_owner_canary.v2"
            and result.get("status") in {"PARTIAL","SUCCEEDED","SUCCEEDED_EMPTY"}
            and result.get("production_allowed") is False
            and result.get("buy_gate_updated") is False
            and result.get("orders_sent") is False)
    return False


def _materializer_result_valid(value: object) -> bool:
    if not isinstance(value,dict) or value.get("returncode")!=0 or value.get("timed_out") is not False:
        return False
    for line in reversed(str(value.get("stdout_tail") or "").splitlines()):
        try:
            result=json.loads(line)
        except (ValueError,TypeError):
            continue
        sandbox=result.get("sandbox_identity") if isinstance(result,dict) else None
        identity_valid=(isinstance(sandbox,dict) and sandbox.get("status")=="VERIFIED"
            and sandbox.get("kind")=="materializer"
            and bool(re.fullmatch(r"[0-9a-f]{32}",str(sandbox.get("run_id") or "")))
            and all(re.fullmatch(r"[0-9a-f]{64}",str(sandbox.get(key) or ""))
                for key in ("identity_sha256","owner_entrypoint_sha256","app_inventory_sha256","data_tree_sha256","argv_sha256")))
        return (isinstance(result,dict) and identity_valid
            and result.get("schema_version")=="v4.manager_research.materializer_offline_replay.v1"
            and result.get("status")=="SAFE_REPLAY_SUCCEEDED"
            and result.get("snapshot_fetch_calls")==0 and result.get("external_process_calls")==0
            and result.get("network_calls")==0 and result.get("input_unchanged") is True
            and bool(re.fullmatch(r"[0-9a-f]{64}",str(result.get("input_identity_sha256") or "")))
            and result.get("production_allowed") is False and result.get("buy_gate_updated") is False
            and result.get("orders_sent") is False)
    return False


def _materializer_input_identity_valid(value: object) -> bool:
    if not isinstance(value,dict) or value.get("input_unchanged") is not True:
        return False
    before=value.get("input_identity_before");after=value.get("input_identity_after")
    if not isinstance(before,dict) or before!=after:
        return False
    digest=hashlib.sha256(json.dumps(before,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    if digest!=value.get("input_identity_sha256"):
        return False
    app_sources=before.get("materializer_app_sources")
    if (not isinstance(app_sources,dict) or set(app_sources)!=set(_MATERIALIZER_RUNTIME_FILES)
            or any(not re.fullmatch(r"[0-9a-f]{64}",str(sha)) for sha in app_sources.values())):
        return False
    universe_tree=before.get("universe_date_tree")
    if not isinstance(universe_tree,dict):return False
    for rel,sha in universe_tree.items():
        path=Path(rel) if isinstance(rel,str) else Path(".")
        if (not isinstance(rel,str) or not rel or "\\" in rel or "\x00" in rel
                or re.match(r"^[A-Za-z]:",rel) or path.is_absolute() or path.as_posix()!=rel
                or any(part in {"",".",".."} for part in path.parts)
                or not isinstance(sha,str) or not re.fullmatch(r"[0-9a-f]{64}",sha)):
            return False
    news=before.get("news_inputs")
    if not isinstance(news,dict) or not isinstance(news.get("files"),dict):
        return False
    for rel,sha in news["files"].items():
        path=Path(rel)
        if (not isinstance(rel,str) or path.is_absolute() or ".." in path.parts
                or not rel.startswith("research/incoming/") or not re.fullmatch(r"[0-9a-f]{64}",str(sha))):
            return False
    for key in ("state_inputs","rebound_inputs"):
        rows=before.get(key)
        if not isinstance(rows,dict) or any(not re.fullmatch(r"[0-9a-f]{64}",str(sha)) for sha in rows.values()):
            return False
    return all(re.fullmatch(r"[0-9a-f]{64}",str(before.get(key) or ""))
        for key in ("universe_owner_source_sha256","news_owner_source_sha256","materializer_source_sha256"))


def _activation_invocation_evidence_valid(raw: dict, artifacts: dict, command_identity: dict,
                                         results: dict, recovery: dict, app: Path, seed: dict) -> bool:
    from infrastructure.owned_io import SafeRoot
    expected_ids={
        "announcement":{"announcement","concurrent-announcement","recovery-interrupted","recovery-after-interrupt"},
        "materializer":{"materializer","concurrent-materializer","recovery-materializer"},
    }
    prepared={}
    for role,key in (("announcement","prepared_announcement_invocations"),
                     ("materializer","prepared_materializer_invocations")):
        rows=raw.get(key)
        if not isinstance(rows,list) or len(rows)!=len(expected_ids[role]):return False
        prepared[role]={}
        for row in rows:
            if not isinstance(row,dict) or row.get("invocation_id") in prepared[role]:return False
            prepared[role][row["invocation_id"]]=row
        if set(prepared[role])!=expected_ids[role]:return False
    expected_results={
        "announcement":(results.get("announcement") or [{}])[0],
        "materializer":(results.get("materializer") or [{}])[0],
        "concurrent-announcement":(results.get("concurrent") or [{},{}])[0],
        "concurrent-materializer":(results.get("concurrent") or [{},{}])[1],
        "recovery-interrupted":recovery.get("interrupted_result") or {},
        "recovery-after-interrupt":recovery.get("announcement_result") or {},
        "recovery-materializer":recovery.get("materializer_result") or {},
    }
    bundle=artifacts.get("invocation_evidence.json")
    if (not isinstance(bundle,dict) or bundle.get("schema_version")!="v4.manager_research.canary_invocation_evidence.v1"
            or bundle.get("capture_status")!="COMPLETE" or not isinstance(bundle.get("invocations"),list)):
        return False
    rows=bundle["invocations"]
    if len(rows)!=7 or {row.get("invocation_id") for row in rows if isinstance(row,dict)}!=set(expected_results):return False
    io=SafeRoot(Path(str(raw.get("scenario_evidence_root") or "")))
    witness=artifacts.get("announcement_recovery_witness.json")
    for item in rows:
        if not isinstance(item,dict):return False
        invocation_id=item.get("invocation_id");role=item.get("role")
        if role not in expected_ids or invocation_id not in expected_ids[role]:return False
        prepared_row=prepared[role][invocation_id]; result=expected_results[invocation_id]
        if (item.get("data_root")!=prepared_row.get("data_root")
                or item.get("identity_path")!=prepared_row.get("identity_path")
                or item.get("owner_receipt_path")!=prepared_row.get("owner_receipt_path")
                or item.get("run_id")!=prepared_row.get("run_id")
                or item.get("argv_sha256")!=prepared_row.get("argv_sha256")
                or item.get("result_sha256")!=hashlib.sha256(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2).encode()).hexdigest()):
            return False
        data=Path(str(item["data_root"]));sandbox=data.parent
        identity_path=sandbox/"identities"/(str(invocation_id)+".json")
        receipt_path=sandbox/"receipts"/(str(invocation_id)+".json")
        if (data.parent!=sandbox or sandbox.parent!=Path(tempfile.gettempdir()).resolve()
                or not any(re.fullmatch(re.escape(prefix)+r"[a-z0-9_]{8}",sandbox.name) for prefix in _SANDBOX_PREFIX[role])
                or Path(str(item["identity_path"]))!=identity_path or Path(str(item["owner_receipt_path"]))!=receipt_path):
            return False
        files={}
        for name,key in (("identity","identity_file"),("started","started_file")):
            rel=item.get(key);digest=str(item.get(name+"_sha256") or "")
            if not isinstance(rel,str) or not re.fullmatch(r"[0-9a-f]{64}",digest):return False
            content=io.read_bytes(rel,max_bytes=1024*1024)
            if hashlib.sha256(content).hexdigest()!=digest:return False
            files[name]=(content,json.loads(content))
        identity_raw,identity=files["identity"];started_raw,started=files["started"]
        if (not isinstance(identity,dict) or not isinstance(started,dict)
                or identity.get("schema_version")!=_SANDBOX_IDENTITY_SCHEMA or identity.get("kind")!=role
                or identity.get("run_id")!=item.get("run_id") or identity.get("data_root")!=str(data)
                or identity.get("sandbox_root")!=str(sandbox) or identity.get("identity_path")!=str(identity_path)
                or identity.get("receipt_path")!=str(receipt_path) or identity.get("app_root")!=str(app)
                or identity.get("argv_sha256")!=item.get("argv_sha256")
                or started.get("run_id")!=item.get("run_id")
                or started.get("identity_sha256")!=item.get("identity_sha256")
                or not isinstance(started.get("started_at_utc"),str)):
            return False
        expected_template=[]
        command=command_identity.get(role,{}).get("argv_template")
        if not isinstance(command,list):return False
        for part in command:
            expected_template.append(str(data) if part=="{state_root}" else str(receipt_path) if part=="{receipt}" else part)
        owner=app/_CANARY_ENTRYPOINTS[role]
        inventory=_canary_app_inventory(app,role)
        if (identity.get("argv_template")!=expected_template
                or hashlib.sha256(json.dumps(expected_template,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()!=item.get("argv_sha256")
                or identity.get("owner_entrypoint")!=str(owner)
                or identity.get("owner_entrypoint_sha256")!=hashlib.sha256(owner.read_bytes()).hexdigest()
                or identity.get("app_inventory_sha256")!=_digest_mapping(inventory)
                or identity.get("data_tree_sha256")!=_digest_mapping(seed)):
            return False
        date_args=command_identity[role]["argv_template"]
        date=date_args[date_args.index("--trade-date")+1]
        if role=="announcement":
            master=Path(date_args[date_args.index("--security-master-root")+1])
            if (identity.get("security_master_root")!=str(master)
                    or identity.get("security_master_tree_sha256")!=_safe_tree_identity(master)):
                return False
        elif identity.get("security_master_root") is not None or identity.get("security_master_tree_sha256") is not None:
            return False
        identity_sha=hashlib.sha256(identity_raw).hexdigest()
        claim={"status":"VERIFIED","run_id":item["run_id"],"kind":role,"sandbox_root":str(sandbox),
            "data_root":str(data),"identity_path":str(identity_path),"receipt_path":str(receipt_path),
            "app_root":str(app),"owner_entrypoint_sha256":identity["owner_entrypoint_sha256"],
            "app_inventory_sha256":identity["app_inventory_sha256"],"data_tree_sha256":identity["data_tree_sha256"],
            "argv_sha256":identity["argv_sha256"],"identity_sha256":identity_sha,
            "production_allowed":False,"buy_gate_updated":False,"orders_sent":False}
        if item.get("identity_sha256")!=identity_sha:return False
        receipt_rel=item.get("owner_receipt_file");attempt_rel=item.get("owner_attempt_file")
        if invocation_id=="recovery-interrupted":
            if (result.get("returncode")==0 or result.get("timed_out") is not False
                    or recovery.get("interruption_observed") is not True
                    or recovery.get("pre_interrupt_change_observed") is not True
                    or not isinstance(attempt_rel,str)):
                return False
            attempt_raw=io.read_bytes(attempt_rel,max_bytes=8*1024*1024)
            if hashlib.sha256(attempt_raw).hexdigest()!=item.get("owner_attempt_sha256"):return False
            from v4.manager_research.workspace import validate_attempt
            attempt=validate_attempt(json.loads(attempt_raw),date)
            interrupted=witness.get("interrupted") if isinstance(witness,dict) else None
            expected_attempt_path=data/"workspace_announcement_runs"/date/"latest.json"
            if (item.get("owner_attempt_source_path")!=str(expected_attempt_path)
                    or not isinstance(interrupted,dict) or any(attempt.get(key)!=interrupted.get(key)
                    for key in ("run_id","state","execution_kind","started_at"))):
                return False
            if receipt_rel is not None:
                receipt_raw=io.read_bytes(str(receipt_rel),max_bytes=8*1024*1024)
                if hashlib.sha256(receipt_raw).hexdigest()!=item.get("owner_receipt_sha256"):
                    return False
                child=json.loads(receipt_raw)
                if not isinstance(child,dict) or child.get("sandbox_identity")!=claim:return False
        else:
            if not isinstance(receipt_rel,str) or attempt_rel is not None:return False
            receipt_raw=io.read_bytes(receipt_rel,max_bytes=8*1024*1024)
            if hashlib.sha256(receipt_raw).hexdigest()!=item.get("owner_receipt_sha256"):return False
            child=json.loads(receipt_raw)
            if not isinstance(child,dict) or child.get("sandbox_identity")!=claim:return False
            emitted=None
            for line in reversed(str(result.get("stdout_tail") or "").splitlines()):
                try:emitted=json.loads(line);break
                except (ValueError,TypeError):continue
            if role=="materializer":
                if not _materializer_input_identity_valid(child):return False
                summary={key:child.get(key) for key in (
                    "schema_version","status","materializer_result","snapshot_fetch_calls",
                    "external_process_calls","network_calls","input_unchanged","input_identity_sha256",
                    "sandbox_identity","production_allowed","buy_gate_updated","orders_sent","RESEARCH_ONLY")}
                if emitted!=summary:return False
            elif emitted!=child:return False
        if result.get("timed_out") is not False:return False
    return True


def _activation_receipt_path(path: object, kind: str):
    from infrastructure.owned_io import SafeRoot
    if not isinstance(path,(str,Path)):
        raise ValueError(f"{str(kind).upper()}_ACTIVATION_RECEIPT_INVALID")
    receipt=Path(path)
    if not receipt.is_absolute() or ".." in receipt.parts or receipt.resolve()!=receipt or receipt.is_symlink():
        raise ValueError(f"{str(kind).upper()}_ACTIVATION_RECEIPT_PATH_INVALID")
    try:
        raw=SafeRoot(receipt.parent).read_bytes(receipt.name,max_bytes=8*1024*1024)
        value=json.loads(raw)
    except (OSError,ValueError,TypeError) as exc:
        raise ValueError(f"{str(kind).upper()}_ACTIVATION_RECEIPT_INVALID") from exc
    if not isinstance(value,dict):
        raise ValueError(f"{str(kind).upper()}_ACTIVATION_RECEIPT_INVALID")
    return receipt,value


def _claimed_sandbox_identity_valid(value: object, kind: str, receipt_path: Path) -> bool:
    from infrastructure.owned_io import SafeRoot
    if not isinstance(value, dict) or value.get("status") != "VERIFIED" or value.get("kind") != kind:
        return False
    try:
        sandbox, data, receipt, identity = _sandbox_locations(
            kind, value.get("data_root"), value.get("receipt_path"), value.get("identity_path"))
        app = _exact_path(value.get("app_root"), "CANARY_SANDBOX_APP_ROOT_INVALID")
        if receipt != receipt_path or value.get("sandbox_root") != str(sandbox):
            return False
        raw = SafeRoot(identity.parent).read_bytes(identity.name, max_bytes=1024 * 1024)
        doc = json.loads(raw)
        identity_sha = hashlib.sha256(raw).hexdigest()
        started_raw = SafeRoot(identity.parent).read_bytes(identity.name + ".started", max_bytes=1024 * 1024)
        started = json.loads(started_raw)
        if (not isinstance(doc, dict) or not isinstance(started, dict)
                or identity_sha != value.get("identity_sha256")
                or doc.get("run_id") != value.get("run_id") or started.get("run_id") != value.get("run_id")
                or started.get("identity_sha256") != identity_sha
                or doc.get("sandbox_root") != str(sandbox) or doc.get("data_root") != str(data)
                or doc.get("identity_path") != str(identity) or doc.get("receipt_path") != str(receipt)
                or doc.get("app_root") != str(app)):
            return False
        argv = doc.get("argv_template")
        if not isinstance(argv, list) or argv.count("--sandbox-identity") != 1:
            return False
        argv = list(argv)
        identity_index = argv.index("--sandbox-identity") + 1
        if identity_index >= len(argv) or argv[identity_index] != "{sandbox_identity}":
            return False
        argv[identity_index] = str(identity)
        normalized = _sandbox_argv(argv, identity_path=identity, receipt_path=receipt,
            data_root=data, kind=kind,
            security_master_root=Path(doc["security_master_root"]) if doc.get("security_master_root") else None)
        argv_sha = hashlib.sha256(json.dumps(normalized, ensure_ascii=False,
            sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        owner = _exact_path(app / _CANARY_ENTRYPOINTS[kind], "CANARY_SANDBOX_OWNER_INVALID")
        app_inventory = _canary_app_inventory(app, kind)
        return (normalized == doc.get("argv_template") and argv_sha == doc.get("argv_sha256")
            and hashlib.sha256(owner.read_bytes()).hexdigest() == doc.get("owner_entrypoint_sha256")
            and _digest_mapping(app_inventory) == doc.get("app_inventory_sha256")
            and value.get("owner_entrypoint_sha256") == doc.get("owner_entrypoint_sha256")
            and value.get("app_inventory_sha256") == doc.get("app_inventory_sha256")
            and value.get("argv_sha256") == argv_sha)
    except (OSError, ValueError, TypeError, KeyError):
        return False


def validate_activation_receipt(receipt_path: str | Path, kind: str, *, expected_app_root: Path | None=None,
                                 expected_app_files: dict[str,str] | None=None,
                                 expected_source_state_root: Path | None=None,
                                 expected_security_master_root: Path | None=None) -> dict:
    """Read a persisted activation receipt and verify its retained evidence.

    In-memory PASS-shaped dictionaries are deliberately not accepted. The
    announcement result must have scenario manifests on disk, with their
    checksums, changed paths, app inventory and writer results recomputed.
    """
    import re
    from infrastructure.owned_io import SafeRoot

    prefix=str(kind).lower()
    receipt,raw=_activation_receipt_path(receipt_path,prefix)
    safe=(raw.get("production_allowed") is False and raw.get("buy_gate_updated") is False
          and raw.get("orders_sent") is False)
    decision=raw.get("decision") if isinstance(raw.get("decision"),dict) else {}
    if not safe or decision.get("status")!="PASS":
        raise ValueError(f"{prefix.upper()}_ACTIVATION_RECEIPT_INVALID")

    if prefix=="announcement":
        valid=(raw.get("schema_version")=="v4.manager_research.shared_root_canary.v7"
            and raw.get("simulated") is False and raw.get("natural_run_verified") is False
            and raw.get("activation_scope")=="WRITER_COMPATIBILITY_ONLY"
            and raw.get("materializer_mode")=="OFFLINE_EXACT_INPUT_REPLAY"
            and raw.get("source_unchanged") is True
            and raw.get("app_unchanged") is True and raw.get("environment_policy")=="SANITIZED_V2")
        source=Path(str(raw.get("source_state_root") or ""))
        replay_seed=Path(str(raw.get("replay_seed_root") or ""))
        app=Path(str(raw.get("app_root") or ""))
        if (not source.is_absolute() or source.resolve()!=source or source.is_symlink()
                or not replay_seed.is_absolute() or replay_seed.resolve()!=replay_seed or replay_seed.is_symlink()
                or not app.is_absolute() or app.resolve()!=app
                or not app.is_dir()):
            valid=False
        if expected_app_root is not None and app!=expected_app_root.resolve():
            valid=False
        if expected_source_state_root is not None:
            expected_source=Path(expected_source_state_root)
            if (not expected_source.is_absolute() or expected_source.resolve()!=expected_source
                    or expected_source.is_symlink() or source!=expected_source):
                valid=False
        canary_tool=app/"ops/run_manager_state_compatibility_canary.py"
        canary_tool_sha=str(raw.get("canary_tool_sha256") or "")
        if (canary_tool.resolve()!=canary_tool or not canary_tool.is_file() or canary_tool.is_symlink()
                or not re.fullmatch(r"[0-9a-f]{64}",canary_tool_sha)):
            valid=False
        else:
            try:
                if hashlib.sha256(canary_tool.read_bytes()).hexdigest()!=canary_tool_sha:
                    valid=False
            except OSError:
                valid=False
        artifact_root=Path(str(receipt)+".evidence")
        if (raw.get("scenario_evidence_root")!=str(artifact_root) or artifact_root.resolve()!=artifact_root
                or not artifact_root.is_dir() or artifact_root.is_symlink()):
            valid=False
        if source.is_absolute() and app.is_absolute():
            if (receipt==source or source in receipt.parents or receipt==app or app in receipt.parents
                    or artifact_root==source or source in artifact_root.parents or artifact_root==app or app in artifact_root.parents):
                valid=False
        if replay_seed.is_absolute() and app.is_absolute():
            if (replay_seed==app or replay_seed in app.parents or app in replay_seed.parents
                    or receipt==replay_seed or replay_seed in receipt.parents
                    or artifact_root==replay_seed or replay_seed in artifact_root.parents):
                valid=False

        artifact_hashes=raw.get("scenario_artifacts_sha256") if isinstance(raw.get("scenario_artifacts_sha256"),dict) else {}
        required_files={"seed_manifest.json","source_manifests.json","app_inventory.json","command_identity.json",
                        "announcement.json","materializer.json","concurrent.json","recovery.json",
                        "announcement_recovery_witness.json","invocation_evidence.json","seed_origin.json"}
        artifacts={}
        if set(artifact_hashes)!=required_files:
            valid=False
        try:
            io=SafeRoot(artifact_root)
            for name in sorted(required_files):
                raw_file=io.read_bytes(name,max_bytes=16*1024*1024)
                expected_hash=str(artifact_hashes.get(name) or "")
                if not re.fullmatch(r"[0-9a-f]{64}",expected_hash) or hashlib.sha256(raw_file).hexdigest()!=expected_hash:
                    valid=False
                artifacts[name]=json.loads(raw_file)
        except (OSError,ValueError,TypeError):
            valid=False
            artifacts={}

        seed=artifacts.get("seed_manifest.json") if isinstance(artifacts.get("seed_manifest.json"),dict) else {}
        source_maps=artifacts.get("source_manifests.json") if isinstance(artifacts.get("source_manifests.json"),dict) else {}
        origin_evidence=artifacts.get("seed_origin.json") if isinstance(artifacts.get("seed_origin.json"),dict) else {}
        app_maps=artifacts.get("app_inventory.json") if isinstance(artifacts.get("app_inventory.json"),dict) else {}
        command_identity=artifacts.get("command_identity.json") if isinstance(artifacts.get("command_identity.json"),dict) else {}
        try:
            from v4.manager_research.materializer_replay import validate_replay_origin_evidence
            checked_origin=validate_replay_origin_evidence(origin_evidence,
                expected_source_state_root=source,expected_replay_seed_root=replay_seed,
                expected_trade_date=str(origin_evidence.get("trade_date") or ""))
        except (OSError,ValueError,TypeError,KeyError):
            checked_origin={}
            valid=False
        if (not seed or not checked_origin
                or seed!=origin_evidence.get("seed_manifest_before")
                or seed!=origin_evidence.get("seed_manifest_after")
                or source_maps.get("before")!=origin_evidence.get("origin_inputs_before")
                or source_maps.get("after")!=origin_evidence.get("origin_inputs_after")
                or raw.get("source_state_root")!=origin_evidence.get("source_state_root")
                or raw.get("replay_seed_root")!=origin_evidence.get("replay_seed_root")
                or raw.get("seed_origin_receipt_path")!=origin_evidence.get("bundle_receipt_path")
                or raw.get("seed_origin_receipt_sha256")!=origin_evidence.get("bundle_receipt_sha256")
                or _digest_mapping(seed)!=raw.get("seed_manifest_sha256")
                or _digest_mapping(source_maps.get("before",{}))!=raw.get("source_manifest_before_sha256")
                or _digest_mapping(source_maps.get("after",{}))!=raw.get("source_manifest_after_sha256")):
            valid=False

        actual_writes={}
        for name in ("announcement","materializer","concurrent"):
            row=artifacts.get(name+".json") if isinstance(artifacts.get(name+".json"),dict) else {}
            before=row.get("before") if isinstance(row.get("before"),dict) else {}
            after=row.get("after") if isinstance(row.get("after"),dict) else {}
            if before!=seed:
                valid=False
            actual_writes[name]=sorted(_changed(before,after))
        writes=raw.get("writes") if isinstance(raw.get("writes"),dict) else {}
        if any(writes.get(name)!=actual_writes[name] for name in actual_writes):
            valid=False
        recomputed=evaluate_writer_namespaces(announcement_paths=actual_writes.get("announcement",()),
            materializer_paths=actual_writes.get("materializer",()),concurrent_paths=actual_writes.get("concurrent",()))
        if recomputed.get("status")!="PASS":
            valid=False

        recovery_artifact=artifacts.get("recovery.json") if isinstance(artifacts.get("recovery.json"),dict) else {}
        recovery_before=recovery_artifact.get("before") if isinstance(recovery_artifact.get("before"),dict) else {}
        recovery_pre_interrupt=recovery_artifact.get("pre_interrupt") if isinstance(recovery_artifact.get("pre_interrupt"),dict) else {}
        recovery_after=recovery_artifact.get("after") if isinstance(recovery_artifact.get("after"),dict) else {}
        pre_interrupt_paths=sorted(_changed(recovery_before,recovery_pre_interrupt))
        recovery_paths=sorted(_changed(recovery_before,recovery_after))
        recovery=raw.get("recovery") if isinstance(raw.get("recovery"),dict) else {}
        witness_artifact=artifacts.get("announcement_recovery_witness.json") if isinstance(artifacts.get("announcement_recovery_witness.json"),dict) else {}
        if recovery.get("owner_transaction_state") != witness_artifact or not _valid_announcement_recovery_witness(witness_artifact):
            valid=False
        ann_result=recovery.get("announcement_result") if isinstance(recovery.get("announcement_result"),dict) else {}
        mat_result=recovery.get("materializer_result") if isinstance(recovery.get("materializer_result"),dict) else {}
        interrupted_result=recovery.get("interrupted_result") if isinstance(recovery.get("interrupted_result"),dict) else {}
        if (recovery_before!=seed or not pre_interrupt_paths or not set(pre_interrupt_paths)<=set(recovery_paths)
                or recovery.get("writes")!=recovery_paths or recovery.get("pre_interrupt_changed_paths")!=pre_interrupt_paths):
            valid=False
        recomputed_recovery=evaluate_recovery(
            interruption_observed=recovery.get("interruption_observed") is True,
            pre_interrupt_change_observed=recovery.get("pre_interrupt_change_observed") is True,
            announcement_returncode=int(ann_result.get("returncode",-999)),
            materializer_returncode=int(mat_result.get("returncode",-999)),
            recovery_paths=recovery_paths,
            allowed_paths=set(actual_writes.get("announcement",()))|set(actual_writes.get("materializer",())),
            owner_transaction_state=recovery.get("owner_transaction_state"),
        )
        if (recovery.get("decision",{}).get("status")!="PASS" or recomputed_recovery.get("status")!="PASS"
                or interrupted_result.get("returncode",0)==0 or interrupted_result.get("timed_out") is not False):
            valid=False

        results=raw.get("results") if isinstance(raw.get("results"),dict) else {}
        for name,count in (("announcement",1),("materializer",1),("concurrent",2)):
            rows=results.get(name)
            if (not isinstance(rows,list) or len(rows)!=count
                    or any(not isinstance(row,dict) or row.get("returncode")!=0 or row.get("timed_out") is not False for row in rows)):
                valid=False
        app_before=app_maps.get("before") if isinstance(app_maps.get("before"),dict) else {}
        app_after=app_maps.get("after") if isinstance(app_maps.get("after"),dict) else {}
        if (not app_before or app_before!=app_after or _digest_mapping(app_before)!=raw.get("app_inventory_sha256_before")
                or _digest_mapping(app_after)!=raw.get("app_inventory_sha256_after")):
            valid=False
        if expected_app_files is not None and app_before!=expected_app_files:
            valid=False
        elif expected_app_files is None and app.is_dir():
            try:
                from infrastructure.scheduling.manager_announcement_supervisor import binding_inventory
                if binding_inventory(app)!=app_before:
                    valid=False
            except (OSError,ValueError):
                valid=False
        concurrent_rows=results.get("concurrent") if isinstance(results.get("concurrent"),list) else []
        recovery_ann=recovery.get("announcement_result") if isinstance(recovery.get("announcement_result"),dict) else {}
        command_dates=[]
        for role in ("announcement","materializer"):
            argv=command_identity.get(role,{}).get("argv_template") if isinstance(command_identity.get(role),dict) else None
            if isinstance(argv,list) and argv.count("--trade-date")==1 and argv.index("--trade-date")+1<len(argv):
                command_dates.append(argv[argv.index("--trade-date")+1])
        if (set(command_identity)!={"announcement","materializer"}
                or not _stored_command_identity(command_identity.get("announcement"),"announcement",app,
                    expected_security_master_root=expected_security_master_root)
                or not _stored_command_identity(command_identity.get("materializer"),"materializer",app)
                or len(command_dates)!=2 or command_dates[0]!=command_dates[1]
                or command_dates[0]!=origin_evidence.get("trade_date")
                or raw.get("command_identity")!=command_identity
                or not results.get("announcement") or not _announcement_result_valid(results["announcement"][0])
                or not results.get("materializer") or not _materializer_result_valid(results["materializer"][0])
                or len(concurrent_rows)!=2 or not _announcement_result_valid(concurrent_rows[0])
                or not _materializer_result_valid(concurrent_rows[1])
                or not _announcement_result_valid(recovery_ann) or not _materializer_result_valid(mat_result)):
            valid=False
        try:
            invocation_evidence_valid=_activation_invocation_evidence_valid(
                raw,artifacts,command_identity,results,recovery,app,seed)
        except Exception:
            invocation_evidence_valid=False
        if not invocation_evidence_valid:
            valid=False
        # Optional locale/certificate roots are allowed, while arbitrary
        # inherited application credentials and runtime roots are not.
        import os
        expected_env={"PATH":os.defpath,"PYTHONNOUSERSITE":"1","PYTHONDONTWRITEBYTECODE":"1",
            "PRODUCTION_ALLOWED":"false","BUY_GATE_UPDATED":"false","ORDERS_SENT":"false",
            "TMPDIR":str(Path(tempfile.gettempdir()).resolve()),"LANG":"C","LC_ALL":"C"}
        required_env=set(expected_env)
        environment_keys=raw.get("environment_keys") if isinstance(raw.get("environment_keys"),list) else []
        environment_values=raw.get("environment_values") if isinstance(raw.get("environment_values"),dict) else {}
        if set(environment_keys)!=required_env or environment_values!=expected_env:
            valid=False
        if not valid:
            raise ValueError("ANNOUNCEMENT_ACTIVATION_RECEIPT_INVALID")
    elif prefix=="us":
        evidence=decision.get("evidence") if isinstance(decision.get("evidence"),dict) else {}
        producer=raw.get("producer") if isinstance(raw.get("producer"),dict) else {}
        bridge=raw.get("bridge") if isinstance(raw.get("bridge"),dict) else {}
        recomputed=evaluate_us_activation(evidence)
        valid=(raw.get("schema_version")=="v4.manager_research.us_activation_canary.v2"
            and recomputed.get("status")=="PASS" and producer.get("payload_sha256")==evidence.get("payload_sha256")
            and producer.get("market_snapshot_status")==evidence.get("producer_status")
            and bridge.get("status")==evidence.get("bridge_status")
            and bridge.get("expected_us_session")==evidence.get("expected_us_session")
            and _claimed_sandbox_identity_valid(raw.get("sandbox_identity"),"us",receipt))
        if not valid:
            raise ValueError("US_ACTIVATION_RECEIPT_INVALID")
    else:
        raise ValueError(f"{prefix.upper()}_ACTIVATION_RECEIPT_INVALID")

    return {"schema_version":"v4.manager_research.activation_receipt_validation.v3","kind":prefix,"status":"PASS",
        "receipt_sha256":hashlib.sha256(receipt.read_bytes()).hexdigest(),
        "production_allowed":False,"buy_gate_updated":False,"orders_sent":False}


__all__ = ["evaluate_writer_namespaces", "evaluate_recovery", "evaluate_us_activation", "validate_activation_receipt"]
