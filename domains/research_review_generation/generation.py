"""Single V4 generation facade with exact-date publication.

Legacy Vibe source inspection is reference-only. Execution requires explicit
V4-owned runtime dependencies; no external package, HOME cache or module patch
is loaded. The injected backend remains a labelled offline testing seam.
"""

from __future__ import annotations

import ast
from copy import deepcopy
from datetime import date as _date
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping, Sequence

from . import _owned_io
from infrastructure.interprocess_lock import owned_interprocess_lock


GENERATOR_SOURCE_ROOT_ENV = "V4_RESEARCH_REVIEW_SOURCE_ROOT"
REVIEW_ROOT_ENV = "V4_DAILY_REVIEW_ROOT"
SCHEMA_VERSION = "v4.research_review_generation.v1"
ARTIFACT_SCHEMA_VERSION = "daily_review"

_MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_SOURCE_FILES = (
    "main.py",
    "duanxian/__init__.py",
    "duanxian/review_graph.py",
    "duanxian/review_store.py",
    "duanxian/preflight.py",
    "duanxian/data.py",
    "duanxian/roles.py",
    "duanxian/analysts.py",
    "duanxian/synthesizer.py",
    "duanxian/config.py",
    "duanxian/reflection.py",
)
_DATA_FUNCTIONS = (
    "get_sentiment_data",
    "get_emotion_metrics",
    "get_market_facts",
    "get_capital_data",
    "get_macro_sector_data",
    "get_theme_reasons",
    "get_dragon_tiger_data",
    "get_leader_data",
)
_REQUIRED_SECTIONS = (
    ("market_facts", "breadth"),
    ("market_facts", "feedback_matrix"),
    ("market_facts", "loss_effect"),
    ("market_facts", "theme_tree"),
    ("market_facts", "event_ledger"),
    ("emotion_metrics", "money_effect"),
    ("emotion_metrics", "promotion"),
    ("emotion_metrics", "ladder_gap"),
)
_FORBIDDEN_IMPORTS = frozenset(
    {
        "server",
        "app",
        "astock",
        "account",
        "portfolio",
        "vr",
        "vr.app",
        "vr.account",
        "vr.portfolio",
    }
)
_SENSITIVE_TEXT = re.compile(
    r"(?i)(?:api[_ -]?key|token|secret|password|passwd|credential)\s*[=:]\s*[^\s,;]+"
)


class GenerationRefused(RuntimeError):
    """A source, date, data, or output boundary did not pass."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalise_date(value: str) -> tuple[str, str]:
    candidate = str(value or "").strip()
    if len(candidate) == 8 and candidate.isdigit():
        parsed = datetime.strptime(candidate, "%Y%m%d").date()
    elif len(candidate) == 10 and candidate[4] == "-" and candidate[7] == "-":
        parsed = datetime.strptime(candidate, "%Y-%m-%d").date()
    else:
        raise GenerationRefused("date must use YYYYMMDD or YYYY-MM-DD")
    if parsed > _date.today():
        raise GenerationRefused("future review dates are refused")
    return parsed.strftime("%Y%m%d"), parsed.isoformat()


def _resolve_directory(value: Path | str | None, *, env: str, label: str) -> Path:
    configured = os.fspath(value) if value is not None else os.environ.get(env, "")
    configured = str(configured).strip()
    if not configured:
        raise GenerationRefused(f"{label} is not configured ({env})")
    candidate = Path(configured)
    if not candidate.is_absolute():
        raise GenerationRefused(f"{label} must be absolute")
    if ".." in candidate.parts:
        raise GenerationRefused(f"{label} must not contain traversal")
    return candidate


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def _redact(text: object) -> str:
    value = str(text or "")
    return _SENSITIVE_TEXT.sub(lambda m: m.group(0).split("=", 1)[0] + "=<redacted>", value)[:240]


def _safe_error(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {_redact(exc)}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _path_observation(path: Path) -> dict[str, object]:
    record: dict[str, object] = {
        "path": str(path),
        "exists": path.exists() or path.is_symlink(),
        "is_symlink": path.is_symlink(),
    }
    if path.is_symlink():
        try:
            record["link_target"] = os.readlink(path)
        except OSError:
            record["link_target"] = "<unreadable>"
    try:
        resolved = path.resolve(strict=False)
        record["resolved_target"] = str(resolved)
        record["resolved_exists"] = resolved.exists()
        if resolved.exists() and resolved.is_file():
            record["bytes"] = resolved.stat().st_size
    except OSError:
        record["resolved_exists"] = False
    return record


def _module_name(value: str) -> str:
    return value.split(".", 1)[0]


def inspect_generator_source(source_root: Path | str) -> dict[str, object]:
    """Inspect the legacy seed files for REFERENCE_ONLY comparison.

    This retains the historical eleven-file seed comparison only. It does not
    establish the external import closure or authorize execution of that tree.
    """

    root = _resolve_directory(source_root, env=GENERATOR_SOURCE_ROOT_ENV, label="generator source root")
    entries: list[dict[str, object]] = []
    missing: list[str] = []
    forbidden: list[dict[str, object]] = []
    for relative in _SOURCE_FILES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            missing.append(relative)
            continue
        entry: dict[str, object] = {
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, SyntaxError) as exc:
            entry["parse_status"] = "ERROR"
            entry["parse_error"] = _safe_error(exc)
            forbidden.append({"path": relative, "reason": "SOURCE_PARSE_ERROR"})
        else:
            imports: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports.update(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imports.add(node.module)
            blocked = sorted(
                item
                for item in imports
                if item in _FORBIDDEN_IMPORTS or _module_name(item) in {"server", "app", "astock", "vr"}
            )
            entry["explicit_imports"] = sorted(imports)
            entry["forbidden_explicit_imports"] = blocked
            if blocked:
                forbidden.append({"path": relative, "imports": blocked})
        entries.append(entry)
    status = "REFERENCE_ONLY" if not missing and not forbidden else "CANNOT_CONFIRM"
    return {
        "status": status,
        "root": str(root),
        "files": entries,
        "missing_files": missing,
        "forbidden_imports": forbidden,
        "runtime_execution_allowed": False,
        "runtime_source_closure": "CANNOT_CONFIRM_LEGACY_REFERENCE_ONLY",
        "boundary": {
            "server_import": False,
            "account_import": False,
            "lifecycle_import": False,
            "vr_provider": "REFERENCE_ONLY; this candidate never imports an external vr provider",
        },
    }


def _normalise_warnings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item).strip()]


def _validate_payload(payload: Mapping[str, Any], compact: str, iso: str) -> None:
    for field in ("target_date", "trade_date"):
        observed = payload.get(field)
        try:
            observed_compact, observed_iso = _normalise_date(str(observed))
        except GenerationRefused as exc:
            raise GenerationRefused(f"payload {field} is invalid") from exc
        if observed_compact != compact or observed_iso != iso:
            raise GenerationRefused(f"payload {field} does not match {iso}")
    for parent_key, child_key in _REQUIRED_SECTIONS:
        parent = payload.get(parent_key)
        if not isinstance(parent, Mapping) or not isinstance(parent.get(child_key), Mapping):
            raise GenerationRefused(f"payload section is missing: {parent_key}.{child_key}")


def _assert_research_flags(value: object) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).casefold() in {"production_allowed", "buy_gate_updated", "orders_sent"} and nested is not False:
                raise GenerationRefused("unsafe nested research capability flag")
            _assert_research_flags(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            _assert_research_flags(nested)


def prepare_payload(
    trade_date: str,
    payload: Mapping[str, Any],
    *,
    mode: str,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate and decorate one serialized review without changing facts."""

    compact, iso = _normalise_date(trade_date)
    if not isinstance(payload, Mapping):
        raise GenerationRefused("serialized review must be an object")
    _assert_research_flags(payload)
    _assert_research_flags(provenance)
    output = deepcopy(dict(payload))
    _validate_payload(output, compact, iso)
    output["trade_date"] = iso
    output["target_date"] = iso
    output.setdefault("warnings", [])
    output["v4_generation"] = {
        "schema_version": SCHEMA_VERSION,
        "owner": "v4_app.domains.research_review_generation",
        "mode": mode,
        "generated_at_utc": _utc_now(),
        "source_provenance": deepcopy(dict(provenance or {})),
        "write_policy": "exact_date_only_no_latest_pointer",
        "production_allowed": False,
        "research_only": True,
        "natural_generation": "CANNOT_CONFIRM",
    }
    # These flags are envelope metadata only.  They cannot widen the existing
    # research-only contract and make the output self-describing to later
    # consumers.
    output["research_only"] = True
    output["production_allowed"] = False
    output["buy_gate_updated"] = False
    output["orders_sent"] = False
    return output


def write_exact_review(
    review_root: Path | str,
    trade_date: str,
    payload: Mapping[str, Any],
    *,
    mode: str = "mock",
    provenance: Mapping[str, Any] | None = None,
    replace: bool = False,
) -> dict[str, object]:
    """Write the same exact-date contract, without following directories/links."""
    compact, iso = _normalise_date(trade_date)
    root = _resolve_directory(review_root, env=REVIEW_ROOT_ENV, label="review output root")
    prepared = prepare_payload(iso, payload, mode=mode, provenance=provenance)
    try:
        encoded = (json.dumps(prepared, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        if len(encoded) > _MAX_ARTIFACT_BYTES:
            raise GenerationRefused("serialized review exceeds bounded artifact size")
        with _owned_io.directory(root, create=True) as fd:
            _owned_io.write_bytes(fd, f"{iso}.json", encoded, replace=replace)
    except (OSError, ValueError) as exc:
        raise GenerationRefused(f"review artifact write refused: {exc}") from exc
    return {
        "status": "READY_FOR_REVIEW", "trade_date": compact, "target_date": iso,
        "artifact_path": str(root / f"{iso}.json"),
        "artifact_sha256": hashlib.sha256(encoded).hexdigest(), "artifact_bytes": len(encoded),
        "mode": mode, "latest_pointer_written": False, "production_allowed": False,
        "buy_gate_updated": False, "orders_sent": False, "research_only": True,
        "natural_generation": "CANNOT_CONFIRM",
    }


def _unpack_backend_result(value: object) -> tuple[Mapping[str, Any], dict[str, object]]:
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], Mapping):
        return value[0], dict(value[1]) if isinstance(value[1], Mapping) else {}
    if isinstance(value, Mapping) and isinstance(value.get("payload"), Mapping):
        metadata = value.get("metadata")
        return value["payload"], dict(metadata) if isinstance(metadata, Mapping) else {}
    if isinstance(value, Mapping):
        return value, {}
    raise GenerationRefused("generator backend did not return a serialized review object")


def run_generation(
    trade_date: str,
    *,
    review_root: Path | str | None = None,
    source_root: Path | str | None = None,
    backend: Callable[[str], object] | None = None,
    runtime: object | None = None,
    replace: bool = False,
) -> dict[str, object]:
    """Generate using explicit owned dependencies; legacy auto-import is retired.

    ``backend`` is an offline testing seam, not accepted as source ownership.
    The local Writer must bind a VibeRuntime before the manual CLI is activated.
    """
    if runtime is not None and backend is not None:
        raise GenerationRefused("runtime and test backend are mutually exclusive")
    if runtime is None and backend is None:
        raise GenerationRefused("explicit V4 VibeRuntime required; external Vibe bridge is reference-only")
    compact, iso = _normalise_date(trade_date)
    output_root = _resolve_directory(review_root, env=REVIEW_ROOT_ENV, label="review output root")
    source: Path | None = None
    if source_root is not None:
        source = _resolve_directory(
            source_root,
            env=GENERATOR_SOURCE_ROOT_ENV,
            label="generator source root",
        )
        if _is_within(output_root, source) or _is_within(source, output_root):
            raise GenerationRefused("review output root must be separate from generator source root")
    if runtime is not None:
        if source is not None:
            raise GenerationRefused("owned runtime must not be combined with an external source root")
        from .owned_runtime import VibeRuntime
        from .assembly import RuntimeAssembly
        if not isinstance(runtime, (VibeRuntime, RuntimeAssembly)):
            raise GenerationRefused("owned runtime has invalid type")
        state_root = Path(runtime.state_root)
        if not state_root.is_absolute() or ".." in state_root.parts or output_root != state_root / "reviews":
            raise GenerationRefused("review root must match the explicit V4-owned state binding")
        code_root = Path(__file__).parent
        if _is_within(state_root, code_root) or _is_within(code_root, state_root):
            raise GenerationRefused("state and code roots must be separate")
    try:
        with owned_interprocess_lock(
            output_root / ".generation" / (iso + ".lock"),
            timeout_seconds=600.0,
            timeout_message="same-date generation owner is still active",
            timeout_error=GenerationRefused,
        ):
            try:
                with _owned_io.directory(output_root, create=True) as fd:
                    _owned_io.check_destination(fd, iso + ".json", replace=replace)
            except (OSError, ValueError) as exc:
                raise GenerationRefused(str(exc)) from exc
            if runtime is not None:
                try:
                    payload, metadata = runtime.run(iso, output_root)
                except (OSError, ValueError) as exc:
                    raise GenerationRefused(str(exc)) from exc
                mode = "v4_owned_graph_candidate"
            else:
                raw = backend(iso)
                payload, metadata = _unpack_backend_result(raw)
                mode = "mock_or_injected_backend"
            result = write_exact_review(
                output_root,
                iso,
                payload,
                mode=mode,
                provenance=metadata,
                replace=replace,
            )
            result.update(
                {
                    "generator_schema_version": SCHEMA_VERSION,
                    "source_root": str(metadata.get("source", {}).get("root", "")) if runtime is not None else str(source or ""),
                    "review_root": str(output_root),
                    "source_status": metadata.get("source", {}).get("status") if isinstance(metadata.get("source"), Mapping) else "INJECTED",
                    "provider_deduplication": metadata.get("snapshot", {}).get("lower_level_provider_deduplication") if isinstance(metadata.get("snapshot"), Mapping) else "CANNOT_CONFIRM_M4_SHARED_PROVIDER_BINDING",
                }
            )
            return result
    except (OSError, ValueError) as exc:
        raise GenerationRefused(f"generation boundary refused: {type(exc).__name__}") from exc


__all__ = [
    "GENERATOR_SOURCE_ROOT_ENV",
    "GenerationRefused",
    "inspect_generator_source",
    "prepare_payload",
    "run_generation",
    "write_exact_review",
]
