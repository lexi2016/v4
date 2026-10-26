"""V3-compatible runtime-graph API backed only by V3.5-owned data."""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import secrets
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from infrastructure.runtime_graph.repair import MAX_REQUEST_BYTES, parse_repair_request_bytes
from infrastructure.runtime_graph.service import RuntimeGraphService


_NO_CACHE_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"}
ADMIN_KEY_ENV = "V35_ADMIN_KEY"
ADMIN_HEADER = "X-8872-Admin-Key"

# This is the plist that launches the API-only process.  It is a fixed local
# control-plane locator, rather than a request or environment supplied path.
# The environment declarations below are deliberately allowlisted: identity
# must never become an environment dump or a credential echo.
API_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / "com.lexi.v35.api-only.plist"
_IDENTITY_ENV_KEYS = (
    "V35_APP_ROOT",
    "V35_RELEASE_ID",
    "V35_RELEASE_MANIFEST_SHA256",
    "V35_RUNTIME_ROOT",
    "V35_RUNTIME_INVENTORY_SHA256",
    "V35_RUNTIME_DEPENDENCY_MANIFEST_SHA256",
)
_IDENTITY_MAX_TEXT = 512
_IDENTITY_MAX_SYS_PATH = 64
_IDENTITY_MAX_MODULES = 24
_IDENTITY_MAX_FILE_BYTES = 16 * 1024 * 1024
_RECEIPT_KEYS = (
    "acceptance_receipt",
    "activation_receipt",
    "deployment_receipt",
    "review_receipt",
    "integration_receipt",
    "receipt_path",
    "receipt",
)
_INVENTORY_FILENAMES = (
    "runtime-inventory.json",
    "runtime_inventory.json",
    "app-inventory.json",
    "candidate-inventory.json",
)
_DEPENDENCY_MANIFEST_FILENAMES = (
    "runtime-dependency-manifest.json",
    "runtime_dependency_manifest.json",
    "dependency-manifest.json",
    "dependency_manifest.json",
    "DEPENDENCY_MANIFEST.json",
)
_MODULE_PREFIXES = (
    "apps.api.v35_api",
    "infrastructure.runtime_graph",
    "infrastructure.runtime",
    "domains.runtime_policy",
    "stage_center",
)


def _repair_http_status(status: str) -> int:
    if status == "REPAIR_PASS" or status.startswith("REPAIR_FAILED_"):
        return 200
    if status == "REPAIR_CIRCUIT_OPEN":
        return 429
    if status == "REPAIR_BUSY":
        return 409
    if status.startswith("REPAIR_DENIED_"):
        return 403
    return 409


async def _read_bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length", "")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                raise ValueError("REPAIR_REQUEST_SIZE_INVALID")
        except (TypeError, ValueError) as error:
            raise ValueError("REPAIR_REQUEST_SIZE_INVALID") from error
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        if not isinstance(chunk, bytes):
            raise ValueError("REPAIR_REQUEST_SIZE_INVALID")
        size += len(chunk)
        if size > MAX_REQUEST_BYTES:
            raise ValueError("REPAIR_REQUEST_SIZE_INVALID")
        chunks.append(chunk)
    if not chunks:
        raise ValueError("REPAIR_REQUEST_SIZE_INVALID")
    return b"".join(chunks)


def _request_admin_key(request: Request) -> str:
    direct = request.headers.get(ADMIN_HEADER, "").strip()
    if direct:
        return direct
    authorization = request.headers.get("Authorization", "").strip()
    if authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


def _admin_allowed(request: Request) -> tuple[bool, str]:
    configured = os.environ.get(ADMIN_KEY_ENV, "").strip()
    if not configured:
        return False, "ADMIN_AUTH_DISABLED"
    submitted = _request_admin_key(request)
    if not submitted:
        return False, "ADMIN_KEY_REQUIRED"
    if not secrets.compare_digest(submitted, configured):
        return False, "ADMIN_KEY_INVALID"
    return True, "ADMIN_AUTH_OK"


def _admin_denied_response(reason: str) -> JSONResponse:
    status_code = 403 if reason == "ADMIN_AUTH_DISABLED" else 401
    response = JSONResponse(
        {
            "ok": False,
            "status": reason,
            "detail": "runtime graph repair requires the configured admin key",
            "auth_header": ADMIN_HEADER,
        },
        status_code=status_code,
        headers=_NO_CACHE_HEADERS,
    )
    response.headers["WWW-Authenticate"] = "API-Key"
    return response


def _bounded_identity_text(value: Any) -> Any:
    """Keep process metadata bounded before it becomes an API payload."""
    if not isinstance(value, str):
        return value
    if len(value) <= _IDENTITY_MAX_TEXT:
        return value
    return value[:_IDENTITY_MAX_TEXT] + "…[TRUNCATED]"


def _canonical_identity_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _resolved_path(value: Any) -> Path | None:
    if not isinstance(value, (str, os.PathLike)) or not str(value).strip():
        return None
    try:
        return Path(value).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _path_within(path: Any, roots: Iterable[Path]) -> Path | None:
    candidate = _resolved_path(path)
    if candidate is None:
        return None
    for root in roots:
        resolved_root = _resolved_path(root)
        if resolved_root is None:
            continue
        try:
            if candidate == resolved_root or resolved_root in candidate.parents:
                return candidate
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
    return None


def _file_sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        size = path.stat().st_size
        if size > _IDENTITY_MAX_FILE_BYTES or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except (OSError, ValueError):
        return None


def _read_metadata(path: Path | None) -> bytes | None:
    if path is None:
        return None
    try:
        if not path.is_file() or path.stat().st_size > _IDENTITY_MAX_FILE_BYTES:
            return None
        return path.read_bytes()
    except (OSError, ValueError):
        return None


def _module_app_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _identity_roots(actual_app_root: Path, declared_app_root: Path | None, runtime_root: Path | None) -> list[Path]:
    roots: list[Path] = [actual_app_root]
    if declared_app_root is not None:
        roots.append(declared_app_root)
    if runtime_root is not None:
        roots.append(runtime_root)
    # Release metadata is adjacent to ``app``.  Keep this derived from
    # declared/serving roots; do not search the whole home directory.
    for app_root in (actual_app_root, declared_app_root):
        if app_root is not None and app_root.name == "app":
            roots.append(app_root.parent)
    return roots


def _declared_metadata_path(env_name: str, roots: Iterable[Path]) -> tuple[Path | None, str]:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return None, "MISSING"
    path = _path_within(raw, roots)
    if path is None:
        # Do not echo a caller supplied path outside the local release roots.
        return None, "REJECTED_OUTSIDE_RELEASE_ROOT"
    return path, "DECLARED"


def _known_metadata_path(
    roots: Iterable[Path],
    filenames: Iterable[str],
    *,
    preferred_root: Path | None = None,
) -> Path | None:
    candidates: list[Path] = []
    if preferred_root is not None:
        candidates.extend(preferred_root / name for name in filenames)
    for root in roots:
        candidates.extend(root / name for name in filenames)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate.resolve()
        except (OSError, RuntimeError):
            continue
    return None


def _hash_evidence(
    *,
    label: str,
    declared_sha256: str | None,
    path: Path | None,
    locator_status: str = "MISSING",
) -> dict[str, Any]:
    actual_sha256 = _file_sha256(path)
    if actual_sha256 and declared_sha256:
        status = "VERIFIED" if actual_sha256 == declared_sha256 else "DRIFT"
    elif actual_sha256:
        status = "FILE_VERIFIED_DECLARATION_MISSING"
    elif declared_sha256:
        status = "DECLARED_ONLY"
    elif locator_status == "REJECTED_OUTSIDE_RELEASE_ROOT":
        status = "CANNOT_CONFIRM"
    else:
        status = "MISSING"
    return {
        "label": label,
        "path": str(path) if path is not None else None,
        "sha256": actual_sha256,
        "declared_sha256": declared_sha256,
        "status": status,
        "evidence_status": "VERIFIED" if actual_sha256 else "CANNOT_CONFIRM",
        "locator_status": locator_status,
    }


def _manifest_receipt_path(
    manifest: Mapping[str, Any],
    manifest_path: Path,
    roots: Iterable[Path],
) -> tuple[Path | None, str, str | None]:
    """Resolve an immutable receipt locator carried by a release manifest.

    A receipt is read only when the locator comes from the already-read
    manifest and is within a declared release/evidence root.  The manifest
    itself is never treated as a receipt, avoiding a circular self-hash.
    """
    root_list = list(roots)
    evidence_root = Path.home() / "Desktop" / "学习" / "agents调试" / "助手" / "v35_repair_20260907"
    root_list.append(evidence_root)
    def iter_declared_receipts(value: Any) -> Iterable[tuple[str, Any]]:
        if isinstance(value, Mapping):
            for nested_key, nested_value in value.items():
                if nested_key in _RECEIPT_KEYS:
                    yield str(nested_key), nested_value
                elif isinstance(nested_value, (Mapping, list, tuple)):
                    yield from iter_declared_receipts(nested_value)
        elif isinstance(value, (list, tuple)):
            for nested_value in value:
                yield from iter_declared_receipts(nested_value)

    receipt_candidates = list(iter_declared_receipts(manifest))
    receipt_candidates.sort(key=lambda pair: _RECEIPT_KEYS.index(pair[0]))
    for key, value in receipt_candidates:
        values = value if isinstance(value, list) else [value]
        for item in values:
            if isinstance(item, Mapping):
                item = item.get("path") or item.get("locator")
            if not isinstance(item, str) or not item.strip():
                continue
            raw_path = Path(item).expanduser()
            candidate = raw_path if raw_path.is_absolute() else manifest_path.parent / raw_path
            safe_path = _path_within(candidate, root_list)
            if safe_path is None:
                continue
            if safe_path == manifest_path.resolve():
                continue
            if not safe_path.name.lower().endswith(("receipt.json", "receipt.sha256")) and "receipt" not in safe_path.name.lower():
                continue
            declared = None
            for sha_key in (f"{key}_sha256", "receipt_sha256", "review_sha256", "activation_sha256"):
                maybe = manifest.get(sha_key)
                if isinstance(maybe, str) and len(maybe) == 64:
                    declared = maybe
                    break
            return safe_path, "DECLARED", declared
    return None, "MISSING", None


def _selected_imported_modules(roots: Iterable[Path]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    modules = sys.modules
    # Keep activation-critical facts visible under the existing fixed cap as
    # unrelated lazy imports grow. Missing modules remain missing: this only
    # orders names already present in this process, and never imports them.
    required = {"apps.api.v35_api.runtime_graph_router", "infrastructure.runtime_graph.service"}
    for module_name in sorted(modules, key=lambda name: (name not in required, name)):
        if not module_name.startswith(_MODULE_PREFIXES):
            continue
        module = modules.get(module_name)
        module_file = getattr(module, "__file__", None)
        path = _resolved_path(module_file)
        if path is None:
            continue
        safe_path = _path_within(path, roots)
        module_sha = _file_sha256(safe_path)
        selected.append(
            {
                "module": _bounded_identity_text(module_name),
                "__file__": _bounded_identity_text(str(path)),
                "path": _bounded_identity_text(str(path)),
                "sha256": module_sha,
                "status": "VERIFIED" if module_sha else "CANNOT_CONFIRM",
            }
        )
        if len(selected) >= _IDENTITY_MAX_MODULES:
            break
    return selected


def _runtime_identity() -> dict[str, Any]:
    """Return bounded same-process identity without changing graph semantics."""
    actual_app_root = _module_app_root()
    declared_app_root = _resolved_path(os.environ.get("V35_APP_ROOT"))
    runtime_root = _resolved_path(os.environ.get("V35_RUNTIME_ROOT"))
    roots = _identity_roots(actual_app_root, declared_app_root, runtime_root)
    declared = {key: os.environ.get(key) or None for key in _IDENTITY_ENV_KEYS}

    manifest_path, manifest_locator_status = _declared_metadata_path("V35_RELEASE_MANIFEST_PATH", roots)
    if manifest_path is None and manifest_locator_status == "MISSING":
        manifest_path = _known_metadata_path(
            roots,
            ("release-manifest.json",),
            preferred_root=declared_app_root.parent if declared_app_root and declared_app_root.name == "app" else None,
        )
        if manifest_path is not None:
            manifest_locator_status = "VERIFIED"
    elif manifest_path is not None and manifest_locator_status == "DECLARED":
        try:
            manifest_locator_status = "VERIFIED" if manifest_path.is_file() else "DECLARED_MISSING"
        except OSError:
            manifest_locator_status = "DECLARED_MISSING"
    manifest_bytes = _read_metadata(manifest_path)
    manifest_sha = _file_sha256(manifest_path)
    manifest: dict[str, Any] = {}
    manifest_parse_status = "MISSING"
    if manifest_bytes is not None:
        try:
            parsed = json.loads(manifest_bytes.decode("utf-8"))
            if isinstance(parsed, dict):
                manifest = parsed
                manifest_parse_status = "VERIFIED"
            else:
                manifest_parse_status = "CANNOT_CONFIRM"
        except (UnicodeDecodeError, json.JSONDecodeError):
            manifest_parse_status = "CANNOT_CONFIRM"
    manifest_release_id = manifest.get("release_id") if isinstance(manifest.get("release_id"), str) else None
    declared_release_id = declared.get("V35_RELEASE_ID")
    release_id_status = (
        "VERIFIED"
        if manifest_release_id and declared_release_id and manifest_release_id == declared_release_id
        else "DRIFT"
        if manifest_release_id and declared_release_id
        else "FILE_VERIFIED_DECLARATION_MISSING"
        if manifest_release_id
        else "DECLARED_ONLY"
        if declared_release_id
        else "CANNOT_CONFIRM"
    )
    manifest_hash = _hash_evidence(
        label="release_manifest",
        declared_sha256=declared.get("V35_RELEASE_MANIFEST_SHA256"),
        path=manifest_path,
        locator_status=manifest_locator_status,
    )

    receipt_path, receipt_locator_status, declared_receipt_sha = _manifest_receipt_path(
        manifest,
        manifest_path,
        roots,
    ) if manifest_path is not None and manifest else (None, "MISSING", None)
    receipt = _hash_evidence(
        label="acceptance_or_activation_receipt",
        declared_sha256=declared_receipt_sha,
        path=receipt_path,
        locator_status=receipt_locator_status,
    )

    inventory_path, inventory_locator_status = _declared_metadata_path("V35_RUNTIME_INVENTORY_PATH", roots)
    if inventory_path is None and inventory_locator_status == "MISSING":
        inventory_path, inventory_locator_status = _declared_metadata_path("V35_RUNTIME_INVENTORY", roots)
    if inventory_path is None and inventory_locator_status == "MISSING":
        inventory_path = _known_metadata_path(roots, _INVENTORY_FILENAMES, preferred_root=runtime_root)
    dependency_path, dependency_locator_status = _declared_metadata_path(
        "V35_RUNTIME_DEPENDENCY_MANIFEST_PATH", roots
    )
    if dependency_path is None and dependency_locator_status == "MISSING":
        dependency_path, dependency_locator_status = _declared_metadata_path("V35_RUNTIME_DEPENDENCY_MANIFEST", roots)
    if dependency_path is None and dependency_locator_status == "MISSING":
        dependency_path = _known_metadata_path(roots, _DEPENDENCY_MANIFEST_FILENAMES, preferred_root=runtime_root)
    inventory = _hash_evidence(
        label="runtime_inventory",
        declared_sha256=declared.get("V35_RUNTIME_INVENTORY_SHA256"),
        path=inventory_path,
        locator_status=inventory_locator_status,
    )
    dependency_manifest = _hash_evidence(
        label="runtime_dependency_manifest",
        declared_sha256=declared.get("V35_RUNTIME_DEPENDENCY_MANIFEST_SHA256"),
        path=dependency_path,
        locator_status=dependency_locator_status,
    )

    plist_bytes = _read_metadata(API_PLIST_PATH)
    plist_sha = _file_sha256(API_PLIST_PATH if plist_bytes is not None else None)
    plist_env: Mapping[str, Any] = {}
    plist_parse_status = "MISSING"
    if plist_bytes is not None:
        try:
            parsed_plist = plistlib.loads(plist_bytes)
            maybe_env = parsed_plist.get("EnvironmentVariables", {}) if isinstance(parsed_plist, dict) else {}
            if isinstance(maybe_env, dict):
                plist_env = maybe_env
                plist_parse_status = "VERIFIED"
            else:
                plist_parse_status = "CANNOT_CONFIRM"
            # API-only launchers may use ``/usr/bin/env KEY=value ...`` rather
            # than an EnvironmentVariables dictionary.  Parse only the same
            # fixed allowlist; never surface the complete launch arguments.
            if isinstance(parsed_plist, dict):
                arguments = parsed_plist.get("ProgramArguments", [])
                if isinstance(arguments, list):
                    parsed_arguments = dict(plist_env)
                    for argument in arguments:
                        if not isinstance(argument, str) or "=" not in argument:
                            continue
                        key, value = argument.split("=", 1)
                        if key in _IDENTITY_ENV_KEYS:
                            parsed_arguments[key] = value
                    plist_env = parsed_arguments
        except (plistlib.InvalidFileException, OSError, ValueError, TypeError):
            plist_parse_status = "CANNOT_CONFIRM"
    plist_bindings: dict[str, dict[str, Any]] = {}
    for key in _IDENTITY_ENV_KEYS:
        env_value = declared.get(key)
        plist_value = plist_env.get(key)
        plist_bindings[key] = {
            "environment": env_value,
            "plist": plist_value,
            "status": "MATCH" if env_value and plist_value == env_value else "DRIFT" if env_value and plist_value else "CANNOT_CONFIRM",
        }
    plist_binding_statuses = [str(item.get("status")) for item in plist_bindings.values()]
    plist_binding_status = (
        "DRIFT"
        if "DRIFT" in plist_binding_statuses
        else "VERIFIED"
        if plist_binding_statuses and all(item == "MATCH" for item in plist_binding_statuses)
        else "CANNOT_CONFIRM"
    )
    app_root_status = (
        "VERIFIED"
        if declared_app_root is not None and declared_app_root == actual_app_root
        else "DRIFT"
        if declared_app_root is not None
        else "DECLARED_ONLY"
    )
    selected_modules = _selected_imported_modules(roots)
    sys_path = [_bounded_identity_text(str(item)) for item in sys.path[:_IDENTITY_MAX_SYS_PATH]]
    if len(sys.path) > _IDENTITY_MAX_SYS_PATH:
        sys_path.append("…[TRUNCATED]")
    selected_module_statuses = [str(item.get("status")) for item in selected_modules]
    selected_modules_status = (
        "DRIFT"
        if "DRIFT" in selected_module_statuses
        else "VERIFIED"
        if selected_module_statuses and all(item == "VERIFIED" for item in selected_module_statuses)
        else "CANNOT_CONFIRM"
    )
    identity: dict[str, Any] = {
        "schema_version": "v35.runtime_identity.v1",
        "status": "CANNOT_CONFIRM",
        "pid": os.getpid(),
        "process_id": os.getpid(),
        "executable": _bounded_identity_text(sys.executable),
        "sys.executable": _bounded_identity_text(sys.executable),
        "cwd": _bounded_identity_text(os.getcwd()),
        "app_root": _bounded_identity_text(str(actual_app_root)),
        "serving_app_root": _bounded_identity_text(str(actual_app_root)),
        "declared_app_root": _bounded_identity_text(str(declared_app_root)) if declared_app_root else None,
        "app_root_status": app_root_status,
        "sys.path": sys_path,
        "sys_path": sys_path,
        "selected_imported_modules": selected_modules,
        "selected_imported_module___file__": selected_modules,
        "loaded_modules": selected_modules,
        "release_id": manifest_release_id or declared_release_id,
        "release_id_declared": declared_release_id,
        "release_id_verified": manifest_release_id,
        "release_id_status": release_id_status,
        "release_manifest_path": _bounded_identity_text(str(manifest_path)) if manifest_path else None,
        "release_manifest_locator_status": manifest_locator_status,
        "release_manifest_sha256": manifest_sha,
        "release_manifest_sha256_declared": declared.get("V35_RELEASE_MANIFEST_SHA256"),
        "release_manifest_sha_status": manifest_hash.get("status"),
        "release_manifest_status": manifest_parse_status if manifest_sha else "CANNOT_CONFIRM",
        "release_manifest": {
            "path": _bounded_identity_text(str(manifest_path)) if manifest_path else None,
            "sha256": manifest_sha,
            "declared_sha256": manifest_hash.get("declared_sha256"),
            "sha256_status": manifest_hash.get("status"),
            "status": manifest_parse_status if manifest_sha else "CANNOT_CONFIRM",
        },
        "receipt": receipt,
        "receipt_path": receipt.get("path"),
        "receipt_sha256": receipt.get("sha256"),
        "receipt_status": receipt.get("status"),
        "plist_path": _bounded_identity_text(str(API_PLIST_PATH)),
        "plist_sha256": plist_sha,
        "plist_status": plist_parse_status if plist_sha else "CANNOT_CONFIRM",
        "plist_bindings": plist_bindings,
        "plist_binding_status": plist_binding_status,
        "selected_modules_status": selected_modules_status,
        "runtime_root": _bounded_identity_text(str(runtime_root)) if runtime_root else None,
        "runtime_inventory": inventory,
        "runtime_inventory_path": inventory.get("path"),
        "runtime_inventory_sha256": inventory.get("sha256"),
        "runtime_inventory_sha256_declared": inventory.get("declared_sha256"),
        "runtime_inventory_status": inventory.get("status"),
        "dependency_inventory_sha256": inventory.get("sha256"),
        "dependency_inventory_sha256_declared": inventory.get("declared_sha256"),
        "runtime_dependency_manifest": dependency_manifest,
        "runtime_dependency_manifest_path": dependency_manifest.get("path"),
        "runtime_dependency_manifest_sha256": dependency_manifest.get("sha256"),
        "runtime_dependency_manifest_sha256_declared": dependency_manifest.get("declared_sha256"),
        "runtime_dependency_manifest_status": dependency_manifest.get("status"),
        "declared_environment": declared,
        "safety": {"RESEARCH_ONLY": True, "production_allowed": False, "buy_gate_updated": False, "orders_sent": False},
    }
    statuses = [
        app_root_status,
        release_id_status,
        identity["release_manifest_locator_status"],
        identity["release_manifest_status"],
        identity["release_manifest_sha_status"],
        identity["receipt_status"],
        identity["plist_status"],
        identity["plist_binding_status"],
        identity["selected_modules_status"],
        inventory["status"],
        dependency_manifest["status"],
    ]
    identity["status"] = "DRIFT" if "DRIFT" in statuses else "VERIFIED" if all(item == "VERIFIED" for item in statuses) else "CANNOT_CONFIRM"
    identity["identity_payload_sha256"] = hashlib.sha256(_canonical_identity_bytes(identity)).hexdigest()
    return identity


def create_runtime_graph_router(data_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/v3/runtime-graph", tags=["runtime-graph"])
    # This binding belongs only to the graph.  The API's NativeDataStore and
    # every business reader retain their original data_root.
    declared_root = os.environ.get("V35_RUNTIME_GRAPH_DATA_ROOT", "").strip()
    graph_root = Path(declared_root) if declared_root else Path(data_root)
    if declared_root and not graph_root.is_absolute():
        raise ValueError("RUNTIME_GRAPH_DATA_ROOT_MUST_BE_ABSOLUTE")
    service = RuntimeGraphService(graph_root)

    @router.get("/snapshot", response_model=dict)
    def runtime_graph_snapshot() -> JSONResponse:
        return JSONResponse(service.snapshot(), headers=_NO_CACHE_HEADERS)

    @router.get("/status", response_model=dict)
    def runtime_graph_status() -> JSONResponse:
        payload = service.status()
        # Runtime identity is collected in this serving process, independently
        # of the graph snapshot.  A stale/corrupt/missing snapshot therefore
        # cannot hide the release binding evidence or change the graph status.
        identity = _runtime_identity()
        payload["runtime_identity"] = identity
        headers = dict(_NO_CACHE_HEADERS)
        headers["X-V35-Runtime-Identity-SHA256"] = str(identity["identity_payload_sha256"])
        return JSONResponse(payload, headers=headers)

    @router.get("/events", response_model=dict)
    def runtime_graph_events(
        node_id: str = Query(..., min_length=1, max_length=256),
        limit: int = Query(100, ge=1, le=500),
    ) -> JSONResponse:
        return JSONResponse(service.events(node_id, limit), headers=_NO_CACHE_HEADERS)

    @router.post("/repair", response_model=dict)
    async def runtime_graph_repair(request: Request) -> JSONResponse:
        authorized, reason = _admin_allowed(request)
        if not authorized:
            return _admin_denied_response(reason)
        try:
            parsed = parse_repair_request_bytes(await _read_bounded_body(request))
        except (ValueError, OverflowError):
            raise HTTPException(status_code=422, detail="REPAIR_REQUEST_INVALID") from None
        result = await run_in_threadpool(
            service.repair_controller.handle,
            parsed,
            authorization_verified=authorized,
        )
        return JSONResponse(
            result.to_payload(),
            status_code=_repair_http_status(result.status),
            headers=_NO_CACHE_HEADERS,
        )

    return router
