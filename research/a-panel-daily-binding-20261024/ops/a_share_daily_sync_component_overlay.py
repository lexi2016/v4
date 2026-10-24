"""Pinned bridge for the future A-only daily-sync component overlay.

This module prepares a reviewable candidate.  Importing or running the bridge
does not start a sync; the generated fixed-path shim only loads the facade.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime, time
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping
from zoneinfo import ZoneInfo


SOURCE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/A23_SIX_QUOTES_REPAIR_20261024/"
    "execution/manual-a-child-release/app"
)
SOURCE_MANIFEST = Path(
    "/Users/lexi/Desktop/学习/agents调试/A23_SIX_QUOTES_REPAIR_20261024/"
    "execution/manual-a-child-release/source-manifest.json"
)
SOURCE_MANIFEST_SHA256 = "0c3b5fd117ec612168450ff956679eb9ff16109a48270fa3f862447ac986e569"
SOURCE_MANIFEST_ENTRY_COUNT = 514

FIXED_ENTRYPOINT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "20260915-us-owner-handoff-disabled/app/ops/a_share_daily_sync.py"
)
BASE_RELEASE_MANIFEST = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "20260915-us-owner-handoff-disabled/release-manifest.json"
)
BASE_FIXED_ENTRY_SHA256 = "a29dec6ad8d7c1a409318553b393cc6355ae253a9f130cf62c60801af3a85eff"
BASE_RELEASE_MANIFEST_SHA256 = "bc2632c345d070f7366a88495f3db40768b51f7cfb72f2882a63bbe32655fa7a"
BASE_RELEASE_ID = "20260915-us-owner-handoff-disabled"

COMPONENT_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/releases/"
    "a-share-daily-sync-component-20261024-r1"
)
EVIDENCE_ROOT = Path(
    "/Users/lexi/Desktop/学习/agents调试/研究面板修复_20261024/"
    "future-binding/implementation"
)
R3_CONTROLLER_REVIEWED_IDLE_MANIFEST_NAME = "R3_CONTROLLER_REVIEWED_IDLE_MANIFEST.json"
R3_CONTROLLER_REVIEWED_IDLE_MANIFEST_SHA256 = "86e2c4132b8f1dae7ab18033935faba29515746b6cec5b798faa9569c8b00087"
R3_FROZEN_MANUAL_TARGET_DATE = "20261023"
R3_EXPECTED_A_MISSING_RECEIPT_PAIR_COUNT = 2
R3_EXPECTED_NO_A_TERMINAL_DISPATCH_COUNT = 18

WORKLOAD_ID = "research_panel_daily_a"
OWNER_ID = "v35_dispatcher.research_panel_daily_a"
SLOT = "1700"
SHANGHAI = ZoneInfo("Asia/Shanghai")
DISPATCH_LEDGER_ROOT = Path(
    "/Users/lexi/Library/Application Support/com.lexi.v35.local/state/dispatcher"
)

# These are the completed top-level receipt statuses emitted by the pinned
# V3.5 dispatcher.  RUNNING, STARTED, and any future/unknown status fail closed.
NATIVE_TERMINAL_DISPATCH_STATUSES = frozenset(
    {
        "NO_DUE_WORKLOADS",
        "NON_TRADING_DAY_CADENCE",
        "NON_TRADING_DAY",
        "NO_ELIGIBLE_WORKLOADS",
        "DRY_RUN_SELECTED",
        "SUCCEEDED",
        "FAILED",
        "DUPLICATE_WORKLOAD_SKIPPED",
    }
)

SOURCE_PINS: tuple[dict[str, Any], ...] = (
    {"path": "ops/_a_share_daily_sync_parts/__init__.py", "sha256": "29b3765f63f15078432ca53a34b28cb726c961e7dd0839022b8a87b3d8b373d8", "bytes": 70},
    {"path": "ops/_a_share_daily_sync_parts/_namespace.py", "sha256": "45da791482883c7c371268a99056960c577f299b43a5629394b3178fbea9f8b1", "bytes": 527},
    {"path": "ops/_a_share_daily_sync_parts/cli_runtime.py", "sha256": "9da0144d0750be48a17e25937de15651540c4f03133513ac7861ef56deeece4c", "bytes": 9232},
    {"path": "ops/_a_share_daily_sync_parts/day_file_format.py", "sha256": "a49564253c9b493c148e6bf0910dc4654dd6c13a7ca890c7690a0a2aab965545", "bytes": 5277},
    {"path": "ops/_a_share_daily_sync_parts/field_rules.py", "sha256": "6a553b1a1948ec964e9009a4dcadab9ffe7ede89784696af03489f8aa906f25d", "bytes": 4946},
    {"path": "ops/_a_share_daily_sync_parts/network_session.py", "sha256": "77dcb01e5ba315adf654c4ffc9b0df0193cde9c34366f9ada2c4ce23ffb89586", "bytes": 8141},
    {"path": "ops/_a_share_daily_sync_parts/progress.py", "sha256": "df948bef15b7ca1bcf6f514d7bb01e2ede992c3afb721b6250adc469431e505a", "bytes": 6318},
    {"path": "ops/_a_share_daily_sync_parts/rebuild.py", "sha256": "a5f751c32812263ff67829d8fe0db8df6ae52782f45e49bb8ccef9d9b50a83cc", "bytes": 11760},
    {"path": "ops/_a_share_daily_sync_parts/response_capture.py", "sha256": "ba0c47c85196c4d8f46f6c8a215bd081f6e90430f242d2ee80c4ff2d4fea991e", "bytes": 5470},
    {"path": "ops/_a_share_daily_sync_parts/scope_validation.py", "sha256": "0cc7d65cde16d953a294a948dfec41e6b83e1a1b8319bd479e241b1f7e06e9f4", "bytes": 4349},
    {"path": "ops/_a_share_daily_sync_parts/sync_workflow.py", "sha256": "8654d5d673abcd5e2c091e89c903e276b38f02656455f6d21db0ea4e6de0e4d8", "bytes": 57536},
    {"path": "ops/_a_share_daily_sync_parts/tdx_mac_adapter.py", "sha256": "f8d32c3f762294866ce8e4522a5c8bee90b578034a774c3514ff56ec1ed7087c", "bytes": 4979},
    {"path": "ops/_a_share_daily_sync_parts/trusted_cas.py", "sha256": "072acb3abad0b39e1ac74b34e3d753c4367d47f1123cf77ff64032eb2e36cfe8", "bytes": 24266},
    {"path": "ops/a_share_daily_sync.py", "sha256": "c41913bdbedf36b32eebc4f54056e4464e4e5f00bc686ba1023cef3ef5669fa9", "bytes": 28763},
)


class OverlayError(RuntimeError):
    """A required pin or install precondition could not be confirmed."""


def _canonical_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_regular(path: Path) -> bytes:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise OverlayError(f"required file unavailable: {path}") from error
    if not stat.S_ISREG(mode):
        raise OverlayError(f"required path is not a regular file: {path}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise OverlayError(f"required file unreadable: {path}") from error


def _require_directory(path: Path) -> None:
    try:
        mode = path.lstat().st_mode
    except OSError as error:
        raise OverlayError(f"required directory unavailable: {path}") from error
    if not stat.S_ISDIR(mode):
        raise OverlayError(f"required path is not a directory: {path}")


def _write_new(path: Path, data: bytes, *, mode: int = 0o644) -> None:
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, mode)
    except OSError as error:
        raise OverlayError(f"refusing to overwrite existing candidate path: {path}") from error
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        raise


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def component_manifest_payload() -> dict[str, Any]:
    return {
        "schema_version": "a_share_daily_sync_component_manifest.v1",
        "component_id": "a-share-daily-sync-component-20261024-r1",
        "source_manifest_path": str(SOURCE_MANIFEST),
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "source_manifest_entry_count": SOURCE_MANIFEST_ENTRY_COUNT,
        "file_count": len(SOURCE_PINS),
        "files": [dict(item) for item in SOURCE_PINS],
    }


def _verify_source_snapshot(source_root: Path = SOURCE_ROOT, source_manifest: Path = SOURCE_MANIFEST) -> None:
    raw_manifest = _read_regular(source_manifest)
    if _sha256(raw_manifest) != SOURCE_MANIFEST_SHA256:
        raise OverlayError("source manifest SHA mismatch")
    try:
        manifest = json.loads(raw_manifest)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OverlayError("source manifest is not valid JSON") from error
    entries = manifest.get("files") if isinstance(manifest, Mapping) else None
    if not isinstance(entries, list) or len(entries) != SOURCE_MANIFEST_ENTRY_COUNT:
        raise OverlayError("source manifest entry count mismatch")
    for pin in SOURCE_PINS:
        source = source_root / pin["path"]
        raw = _read_regular(source)
        if len(raw) != pin["bytes"] or _sha256(raw) != pin["sha256"]:
            raise OverlayError(f"source pin mismatch: {pin['path']}")


def _validate_ops_tree(component_root: Path) -> None:
    expected_files = {pin["path"] for pin in SOURCE_PINS}
    expected_dirs = {"ops", "ops/_a_share_daily_sync_parts"}
    seen_files: set[str] = set()
    seen_dirs: set[str] = {"ops"}
    ops_root = component_root / "ops"
    _require_directory(ops_root)
    for path in ops_root.rglob("*"):
        relative = path.relative_to(component_root).as_posix()
        mode = path.lstat().st_mode
        if stat.S_ISLNK(mode):
            raise OverlayError(f"symlink forbidden in component tree: {relative}")
        if stat.S_ISDIR(mode):
            seen_dirs.add(relative)
        elif stat.S_ISREG(mode):
            seen_files.add(relative)
        else:
            raise OverlayError(f"unsupported component path type: {relative}")
    if seen_files != expected_files or seen_dirs != expected_dirs:
        raise OverlayError("component ops tree does not contain exactly the 14 pinned files")


def verify_component(component_root: Path, *, expected_manifest_sha256: str | None = None) -> str:
    component_root = Path(component_root)
    _require_directory(component_root)
    manifest_path = component_root / "component-manifest.json"
    raw_manifest = _read_regular(manifest_path)
    digest = _sha256(raw_manifest)
    if expected_manifest_sha256 is not None and digest != expected_manifest_sha256:
        raise OverlayError("component manifest SHA mismatch")
    try:
        manifest = json.loads(raw_manifest)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OverlayError("component manifest is not valid JSON") from error
    if manifest != component_manifest_payload():
        raise OverlayError("component manifest content does not match frozen pins")
    _validate_ops_tree(component_root)
    for pin in SOURCE_PINS:
        raw = _read_regular(component_root / pin["path"])
        if len(raw) != pin["bytes"] or _sha256(raw) != pin["sha256"]:
            raise OverlayError(f"component file pin mismatch: {pin['path']}")
    return digest


def render_entry_shim(
    *,
    component_root: Path,
    fixed_entry_path: Path,
    component_manifest_sha256: str,
    base_release_manifest_path: Path = BASE_RELEASE_MANIFEST,
) -> bytes:
    """Render the stdlib-only fixed-path shim with its component pins embedded."""
    replacements = {
        "@COMPONENT_ROOT@": json.dumps(str(Path(component_root)), ensure_ascii=False),
        "@FIXED_ENTRY@": json.dumps(str(Path(fixed_entry_path)), ensure_ascii=False),
        "@COMPONENT_MANIFEST_SHA@": json.dumps(component_manifest_sha256),
        "@BASE_MANIFEST@": json.dumps(str(Path(base_release_manifest_path)), ensure_ascii=False),
        "@BASE_MANIFEST_SHA@": json.dumps(BASE_RELEASE_MANIFEST_SHA256),
        "@BASE_ENTRY_SHA@": json.dumps(BASE_FIXED_ENTRY_SHA256),
        "@SOURCE_MANIFEST_SHA@": json.dumps(SOURCE_MANIFEST_SHA256),
        "@PINS@": json.dumps([dict(item) for item in SOURCE_PINS], ensure_ascii=False, sort_keys=True),
    }
    source = textwrap.dedent(
        '''\
        """Reviewed A-only fixed-entry shim. It loads the pinned facade only."""
        from __future__ import annotations

        import hashlib
        import importlib
        import json
        import os
        import stat
        import sys
        from pathlib import Path

        _COMPONENT_ROOT = Path(@COMPONENT_ROOT@)
        _FIXED_ENTRY = Path(@FIXED_ENTRY@)
        _COMPONENT_MANIFEST_SHA = @COMPONENT_MANIFEST_SHA@
        _BASE_MANIFEST = Path(@BASE_MANIFEST@)
        _BASE_MANIFEST_SHA = @BASE_MANIFEST_SHA@
        _BASE_ENTRY_SHA = @BASE_ENTRY_SHA@
        _SOURCE_MANIFEST_SHA = @SOURCE_MANIFEST_SHA@
        _PINS = @PINS@

        def _regular_bytes(path):
            if not stat.S_ISREG(path.lstat().st_mode):
                raise RuntimeError("pinned overlay path is not a regular file: " + str(path))
            return path.read_bytes()

        def _sha(data):
            return hashlib.sha256(data).hexdigest()

        def _verify_overlay():
            shim_path = Path(__file__)
            if shim_path.resolve() != _FIXED_ENTRY.resolve():
                raise RuntimeError("fixed A entry path mismatch")
            module = sys.modules.get(__name__)
            if module is None or module.__dict__ is not globals():
                raise RuntimeError("fixed A entry is not executing in the loader-created module")
            shim_sha = _sha(_regular_bytes(shim_path))
            if _sha(_regular_bytes(_BASE_MANIFEST)) != _BASE_MANIFEST_SHA:
                raise RuntimeError("base release manifest SHA mismatch")
            preimage = _COMPONENT_ROOT / "preimage" / "a_share_daily_sync.py"
            if _sha(_regular_bytes(preimage)) != _BASE_ENTRY_SHA:
                raise RuntimeError("fixed A entry preimage SHA mismatch")
            manifest_path = _COMPONENT_ROOT / "component-manifest.json"
            manifest_bytes = _regular_bytes(manifest_path)
            if _sha(manifest_bytes) != _COMPONENT_MANIFEST_SHA:
                raise RuntimeError("component manifest SHA mismatch")
            manifest = json.loads(manifest_bytes)
            if manifest.get("source_manifest_sha256") != _SOURCE_MANIFEST_SHA:
                raise RuntimeError("source manifest provenance mismatch")
            if manifest.get("files") != _PINS or manifest.get("file_count") != len(_PINS):
                raise RuntimeError("component manifest file list mismatch")
            expected_files = {item["path"] for item in _PINS}
            expected_dirs = {"ops", "ops/_a_share_daily_sync_parts"}
            observed_files = set()
            observed_dirs = {"ops"}
            ops_root = _COMPONENT_ROOT / "ops"
            for path in ops_root.rglob("*"):
                relative = path.relative_to(_COMPONENT_ROOT).as_posix()
                mode = path.lstat().st_mode
                if stat.S_ISLNK(mode):
                    raise RuntimeError("component symlink forbidden: " + relative)
                if stat.S_ISDIR(mode):
                    observed_dirs.add(relative)
                elif stat.S_ISREG(mode):
                    observed_files.add(relative)
                else:
                    raise RuntimeError("unsupported component path: " + relative)
            if observed_files != expected_files or observed_dirs != expected_dirs:
                raise RuntimeError("component tree is not the exact pinned ops overlay")
            for pin in _PINS:
                raw = _regular_bytes(_COMPONENT_ROOT / pin["path"])
                if len(raw) != pin["bytes"] or _sha(raw) != pin["sha256"]:
                    raise RuntimeError("component file pin mismatch: " + pin["path"])
            overlay_path = _COMPONENT_ROOT / "overlay-manifest.json"
            overlay = json.loads(_regular_bytes(overlay_path))
            checks = {
                "base_release_id": "20260915-us-owner-handoff-disabled",
                "base_manifest_path": str(_BASE_MANIFEST),
                "base_manifest_sha256": _BASE_MANIFEST_SHA,
                "fixed_entry_path": str(_FIXED_ENTRY),
                "preimage_path": str(_COMPONENT_ROOT / "preimage" / "a_share_daily_sync.py"),
                "preimage_sha256": _BASE_ENTRY_SHA,
                "installed_shim_sha256": shim_sha,
                "component_root": str(_COMPONENT_ROOT),
                "component_manifest_path": str(manifest_path),
                "component_manifest_sha256": _COMPONENT_MANIFEST_SHA,
                "source_manifest_sha256": _SOURCE_MANIFEST_SHA,
                "protocol": "mac",
                "effective_scope": "A_ONLY",
            }
            if any(overlay.get(key) != value for key, value in checks.items()):
                raise RuntimeError("overlay sidecar does not bind this fixed A entry")
            return _COMPONENT_ROOT / "ops" / "a_share_daily_sync.py"

        _facade = _verify_overlay()
        os.environ["V35_A_SYNC_TDX_PROTOCOL"] = "mac"
        _component_import_root = str(_COMPONENT_ROOT)
        sys.path[:] = [_component_import_root] + [entry for entry in sys.path if entry != _component_import_root]
        importlib.invalidate_caches()
        globals()["__file__"] = str(_facade)
        _source = _regular_bytes(_facade)
        exec(compile(_source, str(_facade), "exec"), globals(), globals())
        '''
    )
    for marker, value in replacements.items():
        source = source.replace(marker, value)
    if "@" in source:
        raise OverlayError("entry shim template contains an unresolved token")
    return source.encode("utf-8")


def _overlay_payload(
    *,
    component_root: Path,
    fixed_entry_path: Path,
    base_release_manifest_path: Path,
    component_manifest_sha256: str,
    shim_sha256: str,
    created_at: datetime,
) -> dict[str, Any]:
    return {
        "schema_version": "a_share_daily_sync_overlay_manifest.v1",
        "base_release_id": BASE_RELEASE_ID,
        "base_manifest_path": str(base_release_manifest_path),
        "base_manifest_sha256": BASE_RELEASE_MANIFEST_SHA256,
        "fixed_entry_path": str(fixed_entry_path),
        "preimage_path": str(component_root / "preimage" / "a_share_daily_sync.py"),
        "preimage_sha256": BASE_FIXED_ENTRY_SHA256,
        "installed_shim_sha256": shim_sha256,
        "component_root": str(component_root),
        "component_manifest_path": str(component_root / "component-manifest.json"),
        "component_manifest_sha256": component_manifest_sha256,
        "source_manifest_path": str(SOURCE_MANIFEST),
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "protocol": "mac",
        "effective_scope": "A_ONLY",
        "created_at": created_at.astimezone(SHANGHAI).isoformat(timespec="seconds"),
        "created_at_null_reason": None,
        "base_release_manifest_semantics": (
            "The original manifest remains the preimage release record and does not fully "
            "describe the fixed A entry after this overlay is activated."
        ),
    }


def _validate_overlay_sidecar(
    *,
    component_root: Path,
    fixed_entry_path: Path,
    base_release_manifest_path: Path,
    component_manifest_sha256: str,
) -> tuple[dict[str, Any], bytes]:
    sidecar_path = component_root / "overlay-manifest.json"
    raw = _read_regular(sidecar_path)
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OverlayError("overlay sidecar is not valid JSON") from error
    required = {
        "base_release_id": BASE_RELEASE_ID,
        "base_manifest_path": str(base_release_manifest_path),
        "base_manifest_sha256": BASE_RELEASE_MANIFEST_SHA256,
        "fixed_entry_path": str(fixed_entry_path),
        "preimage_path": str(component_root / "preimage" / "a_share_daily_sync.py"),
        "preimage_sha256": BASE_FIXED_ENTRY_SHA256,
        "component_root": str(component_root),
        "component_manifest_path": str(component_root / "component-manifest.json"),
        "component_manifest_sha256": component_manifest_sha256,
        "source_manifest_path": str(SOURCE_MANIFEST),
        "source_manifest_sha256": SOURCE_MANIFEST_SHA256,
        "protocol": "mac",
        "effective_scope": "A_ONLY",
    }
    if not isinstance(payload, Mapping) or any(payload.get(k) != v for k, v in required.items()):
        raise OverlayError("overlay sidecar does not match the frozen A-only binding")
    semantic_text = payload.get("base_release_manifest_semantics")
    if not isinstance(semantic_text, str) or "does not fully describe" not in semantic_text:
        raise OverlayError("overlay sidecar does not explain the original manifest boundary")
    if not isinstance(payload.get("created_at"), str) or payload.get("created_at_null_reason") is not None:
        raise OverlayError("overlay sidecar lacks a creation timestamp")
    if not isinstance(payload.get("installed_shim_sha256"), str) or len(payload["installed_shim_sha256"]) != 64:
        raise OverlayError("overlay sidecar lacks an exact shim hash")
    return dict(payload), raw


def verify_prepared_candidate(
    component_root: Path = COMPONENT_ROOT,
    *,
    fixed_entry_path: Path = FIXED_ENTRYPOINT,
    base_release_manifest_path: Path = BASE_RELEASE_MANIFEST,
) -> dict[str, Any]:
    component_sha = verify_component(component_root)
    base_manifest = _read_regular(base_release_manifest_path)
    if _sha256(base_manifest) != BASE_RELEASE_MANIFEST_SHA256:
        raise OverlayError("original release manifest SHA mismatch")
    preimage = _read_regular(Path(component_root) / "preimage" / "a_share_daily_sync.py")
    if _sha256(preimage) != BASE_FIXED_ENTRY_SHA256:
        raise OverlayError("fixed A preimage SHA mismatch")
    sidecar, _ = _validate_overlay_sidecar(
        component_root=Path(component_root),
        fixed_entry_path=Path(fixed_entry_path),
        base_release_manifest_path=Path(base_release_manifest_path),
        component_manifest_sha256=component_sha,
    )
    shim = render_entry_shim(
        component_root=Path(component_root),
        fixed_entry_path=Path(fixed_entry_path),
        component_manifest_sha256=component_sha,
        base_release_manifest_path=Path(base_release_manifest_path),
    )
    if _sha256(shim) != sidecar["installed_shim_sha256"]:
        raise OverlayError("generated shim hash does not match overlay sidecar")
    return {
        "component_manifest_sha256": component_sha,
        "overlay_manifest_sha256": _sha256(_read_regular(Path(component_root) / "overlay-manifest.json")),
        "preimage_sha256": _sha256(preimage),
        "shim_sha256": _sha256(shim),
        "shim_bytes": shim,
    }


def _write_evidence_file(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = _read_regular(path)
        if existing != data:
            raise OverlayError(f"evidence path exists with different bytes: {path}")
        return
    _write_new(path, data)
    _fsync_directory(path.parent)


def prepare_component(
    component_root: Path = COMPONENT_ROOT,
    *,
    fixed_entry_path: Path = FIXED_ENTRYPOINT,
    base_release_manifest_path: Path = BASE_RELEASE_MANIFEST,
    source_root: Path = SOURCE_ROOT,
    source_manifest_path: Path = SOURCE_MANIFEST,
    evidence_root: Path | None = EVIDENCE_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Create the exact inactive component, refusing to replace any existing bytes."""
    component_root = Path(component_root)
    fixed_entry_path = Path(fixed_entry_path)
    base_release_manifest_path = Path(base_release_manifest_path)
    _verify_source_snapshot(Path(source_root), Path(source_manifest_path))
    base_entry = _read_regular(fixed_entry_path)
    if _sha256(base_entry) != BASE_FIXED_ENTRY_SHA256:
        raise OverlayError("fixed A entrypoint preimage SHA mismatch")
    base_manifest = _read_regular(base_release_manifest_path)
    if _sha256(base_manifest) != BASE_RELEASE_MANIFEST_SHA256:
        raise OverlayError("original release manifest SHA mismatch")

    if not component_root.exists():
        _require_directory(component_root.parent)
        component_root.mkdir()
        (component_root / "ops").mkdir()
        (component_root / "ops" / "_a_share_daily_sync_parts").mkdir()
        (component_root / "preimage").mkdir()
        for pin in SOURCE_PINS:
            raw = _read_regular(Path(source_root) / pin["path"])
            _write_new(component_root / pin["path"], raw)
        component_bytes = _canonical_json(component_manifest_payload())
        _write_new(component_root / "component-manifest.json", component_bytes)
        _write_new(component_root / "preimage" / "a_share_daily_sync.py", base_entry)
        component_sha = _sha256(component_bytes)
        shim = render_entry_shim(
            component_root=component_root,
            fixed_entry_path=fixed_entry_path,
            component_manifest_sha256=component_sha,
            base_release_manifest_path=base_release_manifest_path,
        )
        timestamp = now or datetime.now(SHANGHAI)
        overlay_bytes = _canonical_json(
            _overlay_payload(
                component_root=component_root,
                fixed_entry_path=fixed_entry_path,
                base_release_manifest_path=base_release_manifest_path,
                component_manifest_sha256=component_sha,
                shim_sha256=_sha256(shim),
                created_at=timestamp,
            )
        )
        _write_new(component_root / "overlay-manifest.json", overlay_bytes)
        _fsync_directory(component_root / "ops" / "_a_share_daily_sync_parts")
        _fsync_directory(component_root / "ops")
        _fsync_directory(component_root / "preimage")
        _fsync_directory(component_root)
    else:
        _require_directory(component_root)

    verified = verify_prepared_candidate(
        component_root,
        fixed_entry_path=fixed_entry_path,
        base_release_manifest_path=base_release_manifest_path,
    )
    shim = verified.pop("shim_bytes")
    if _sha256(_read_regular(fixed_entry_path)) != BASE_FIXED_ENTRY_SHA256:
        raise OverlayError("fixed A entrypoint changed while preparing candidate")
    if _sha256(_read_regular(base_release_manifest_path)) != BASE_RELEASE_MANIFEST_SHA256:
        raise OverlayError("original release manifest changed while preparing candidate")
    if evidence_root is not None:
        _write_evidence_file(Path(evidence_root) / "entrypoint-shim.py", shim)
    return {
        "status": "CANDIDATE_PREPARED_INACTIVE",
        "component_root": str(component_root),
        "fixed_entrypoint_still_preimage": True,
        **verified,
    }


def _default_process_snapshot() -> list[str]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise OverlayError("cannot confirm active A child process state") from error
    return result.stdout.splitlines()


def active_a_child_processes(
    fixed_entry_path: Path = FIXED_ENTRYPOINT,
    *,
    process_rows: Iterable[str] | None = None,
) -> tuple[str, ...]:
    rows = list(_default_process_snapshot() if process_rows is None else process_rows)
    fixed_text = str(Path(fixed_entry_path).resolve())
    matches: list[str] = []
    for row in rows:
        pid_text, separator, command = row.strip().partition(" ")
        if not separator:
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        is_fixed_entry = fixed_text in command
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = []
        is_scheduled_a_module = False
        for index, token in enumerate(tokens[:-1]):
            if token != "-m" or tokens[index + 1] != "ops.macos_research_panel_daily":
                continue
            lane_values: list[str] = []
            for arg_index, arg in enumerate(tokens):
                if arg == "--lane" and arg_index + 1 < len(tokens):
                    lane_values.append(tokens[arg_index + 1].upper())
                elif arg.startswith("--lane="):
                    lane_values.append(arg.partition("=")[2].upper())
            # The scheduler invokes the module with an explicit lane. Treat a
            # missing or ambiguous lane as active, while an explicit HK-only
            # invocation does not own the A fixed entrypoint.
            is_scheduled_a_module = not (len(lane_values) == 1 and lane_values[0] == "HK")
            break
        if pid != os.getpid() and (is_fixed_entry or is_scheduled_a_module):
            matches.append(row.strip())
    return tuple(matches)


def _pid_is_alive(pid: Any) -> bool:
    if isinstance(pid, bool):
        return False
    try:
        value = int(pid)
    except (TypeError, ValueError):
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError as error:
        if error.errno == errno.ESRCH:
            return False
        return True
    return True


def _read_json_object(path: Path) -> dict[str, Any]:
    raw = _read_regular(path)
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OverlayError(f"claim or receipt is not valid JSON: {path}") from error
    if not isinstance(value, dict):
        raise OverlayError(f"claim or receipt is not an object: {path}")
    return value


def _ledger_digest(payload: Mapping[str, Any]) -> str:
    body = {key: value for key, value in payload.items() if key != "ledger_sha256"}
    raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256(raw)


def _require_bound_dispatch_ledger(ledger_root: Path) -> Path:
    """Require the confirmed V3.5 dispatcher ledger (tests patch the binding)."""
    try:
        configured = Path(DISPATCH_LEDGER_ROOT).resolve(strict=True)
        supplied = Path(ledger_root).resolve(strict=True)
    except OSError as error:
        raise OverlayError("configured dispatcher ledger root is unavailable") from error
    if supplied != configured:
        raise OverlayError("ledger root does not match the configured V3.5 dispatcher ledger")
    _require_directory(supplied)
    return supplied


def _finished_receipt_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _has_terminal_dispatch_receipt(ledger_root: Path, claim: Mapping[str, Any]) -> bool:
    run_id = str(claim.get("run_id") or "")
    mode = str(claim.get("mode") or "").lower()
    business_date = str(claim.get("business_date") or "")
    slot = str(claim.get("slot") or "")
    if not all((run_id, mode, business_date, slot)):
        return False
    path = ledger_root / "receipts" / mode / business_date / slot / f"{run_id}.dispatch-receipt.json"
    if not path.exists():
        return False
    try:
        receipt = _read_json_object(path)
    except OverlayError:
        return False
    expected_receipt_path = (
        f"receipts/{mode}/{business_date}/{slot}/"
        f"{run_id}.dispatch-receipt.json"
    )
    if receipt.get("schema_version") != "v3_5.dispatch.v1":
        return False
    if receipt.get("ledger_sha256") != _ledger_digest(receipt):
        return False
    if any(
        str(receipt.get(field) or "") != str(claim.get(field) or "")
        for field in (
            "run_id",
            "scheduled_date",
            "business_date",
            "target_date",
            "slot",
            "mode",
        )
    ):
        return False
    if receipt.get("receipt_path") != expected_receipt_path:
        return False
    selected = receipt.get("selected_workload_ids")
    if not isinstance(selected, list) or WORKLOAD_ID not in selected:
        return False
    if not _finished_receipt_timestamp(receipt.get("finished_at")):
        return False
    if any(receipt.get(field) is not False for field in ("production_allowed", "buy_gate_updated", "orders_sent")):
        return False
    status = receipt.get("status")
    return isinstance(status, str) and status in NATIVE_TERMINAL_DISPATCH_STATUSES


def _load_controller_reviewed_idle_manifest(
    manifest_sha256: str | None,
) -> dict[str, Any] | None:
    """Load only the one frozen R3 inventory when its explicit token is supplied."""
    if manifest_sha256 is None:
        return None
    if manifest_sha256 != R3_CONTROLLER_REVIEWED_IDLE_MANIFEST_SHA256:
        raise OverlayError("controller-reviewed idle manifest digest is not approved")
    manifest_path = EVIDENCE_ROOT / R3_CONTROLLER_REVIEWED_IDLE_MANIFEST_NAME
    raw = _read_regular(manifest_path)
    if _sha256(raw) != R3_CONTROLLER_REVIEWED_IDLE_MANIFEST_SHA256:
        raise OverlayError("controller-reviewed idle manifest changed")
    try:
        manifest = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise OverlayError("controller-reviewed idle manifest is not valid JSON") from error
    if not isinstance(manifest, dict):
        raise OverlayError("controller-reviewed idle manifest is not an object")
    pairs = manifest.get("inactive_a_missing_receipt_pairs")
    non_a = manifest.get("verified_no_a_workload_terminal_dispatches")
    if (
        manifest.get("schema_version") != "r3_controller_reviewed_a_idle_manifest.v1"
        or manifest.get("frozen_manual_target_date") != R3_FROZEN_MANUAL_TARGET_DATE
        or manifest.get("reviewed_exception_count") != R3_EXPECTED_A_MISSING_RECEIPT_PAIR_COUNT
        + R3_EXPECTED_NO_A_TERMINAL_DISPATCH_COUNT
        or not isinstance(pairs, list)
        or len(pairs) != R3_EXPECTED_A_MISSING_RECEIPT_PAIR_COUNT
        or not isinstance(non_a, list)
        or len(non_a) != R3_EXPECTED_NO_A_TERMINAL_DISPATCH_COUNT
    ):
        raise OverlayError("controller-reviewed idle manifest scope is invalid")
    pair_paths: set[str] = set()
    for entry in pairs:
        if not isinstance(entry, dict):
            raise OverlayError("controller-reviewed A claim pair is invalid")
        date_value = entry.get("business_date")
        if (
            entry.get("kind") != "INACTIVE_A_MISSING_RECEIPT_PAIR"
            or not _historical_date_before_target(date_value, R3_FROZEN_MANUAL_TARGET_DATE)
            or entry.get("expected_receipt_state") != "ABSENT"
            or entry.get("pid_absent_at_inventory") is not True
            or entry.get("workload_id") != WORKLOAD_ID
            or any(not isinstance(entry.get(key), str) or not entry.get(key) for key in (
                "run_id", "workload_claim_path", "workload_claim_sha256",
                "dispatch_claim_path", "dispatch_claim_sha256", "receipt_path",
            ))
        ):
            raise OverlayError("controller-reviewed A claim pair identity is invalid")
        if entry["workload_claim_path"] in pair_paths or entry["dispatch_claim_path"] in pair_paths:
            raise OverlayError("controller-reviewed idle manifest contains duplicate paths")
        pair_paths.update((entry["workload_claim_path"], entry["dispatch_claim_path"]))
    non_a_paths: set[str] = set()
    for entry in non_a:
        if not isinstance(entry, dict):
            raise OverlayError("controller-reviewed non-A dispatch record is invalid")
        selected = entry.get("selected_workload_ids")
        started = entry.get("started_workload_ids")
        if (
            entry.get("kind") != "VERIFIED_NO_A_WORKLOAD_TERMINAL"
            or not _historical_date_before_target(entry.get("business_date"), R3_FROZEN_MANUAL_TARGET_DATE)
            or entry.get("pid_absent_at_inventory") is not True
            or entry.get("schema_version") != "v3_5.dispatch_claim.v1"
            or entry.get("mode") != "LIVE"
            or entry.get("slot") != SLOT
            or not isinstance(selected, list)
            or WORKLOAD_ID in selected
            or not isinstance(started, list)
            or WORKLOAD_ID in started
            or entry.get("receipt_status") not in NATIVE_TERMINAL_DISPATCH_STATUSES
            or any(not isinstance(entry.get(key), str) or not entry.get(key) for key in (
                "run_id", "claim_path", "claim_sha256", "receipt_path", "receipt_sha256",
            ))
        ):
            raise OverlayError("controller-reviewed non-A dispatch identity is invalid")
        if entry["claim_path"] in non_a_paths:
            raise OverlayError("controller-reviewed idle manifest contains duplicate dispatch paths")
        non_a_paths.add(entry["claim_path"])
    return manifest


def _historical_date_before_target(value: Any, target: str) -> bool:
    if not isinstance(value, str) or len(value) != 8 or not value.isdigit():
        return False
    try:
        parsed = datetime.strptime(value, "%Y%m%d").strftime("%Y%m%d")
    except ValueError:
        return False
    return parsed == value and value < target


def _manifest_entry_matches_claim(
    entry: Mapping[str, Any], claim_path: Path, claim: Mapping[str, Any], raw: bytes
) -> bool:
    return (
        entry.get("claim_path") == str(claim_path)
        and entry.get("claim_sha256") == _sha256(raw)
        and all(str(entry.get(key) or "") == str(claim.get(key) or "") for key in (
            "run_id", "scheduled_date", "business_date", "target_date", "slot", "mode", "pid",
        ))
    )


def _reviewed_inactive_a_pair_matches(
    ledger_root: Path,
    claim_path: Path,
    claim: Mapping[str, Any],
    manifest: Mapping[str, Any] | None,
    *,
    pid_alive: Callable[[Any], bool],
) -> bool:
    if manifest is None:
        return False
    try:
        raw = _read_regular(claim_path)
    except OverlayError:
        return False
    for entry in manifest["inactive_a_missing_receipt_pairs"]:
        if entry.get("workload_claim_path") != str(claim_path) or entry.get("workload_claim_sha256") != _sha256(raw):
            continue
        business_date = entry["business_date"]
        run_id = entry["run_id"]
        if (
            claim.get("schema_version") != "v3_5.workload_claim.v1"
            or claim.get("workload_id") != WORKLOAD_ID
            or claim.get("mode") != "LIVE"
            or claim.get("slot") != SLOT
            or str(claim.get("business_date") or "") != business_date
            or str(claim.get("scheduled_date") or "") != business_date
            or str(claim.get("target_date") or "") != business_date
            or claim.get("run_id") != run_id
            or claim.get("pid") != entry.get("pid")
            or not _historical_date_before_target(business_date, R3_FROZEN_MANUAL_TARGET_DATE)
            or pid_alive(claim.get("pid"))
        ):
            return False
        dispatch_path = ledger_root / "claims" / "live" / business_date / SLOT / "dispatch.claim.json"
        try:
            dispatch_raw = _read_regular(dispatch_path)
            dispatch = json.loads(dispatch_raw)
        except (OverlayError, UnicodeError, json.JSONDecodeError):
            return False
        if (
            str(dispatch_path) != entry.get("dispatch_claim_path")
            or _sha256(dispatch_raw) != entry.get("dispatch_claim_sha256")
            or not isinstance(dispatch, dict)
            or dispatch.get("schema_version") != "v3_5.dispatch_claim.v1"
            or dispatch.get("run_id") != run_id
            or dispatch.get("business_date") != business_date
            or dispatch.get("scheduled_date") != business_date
            or dispatch.get("target_date") != business_date
            or dispatch.get("mode") != "LIVE"
            or dispatch.get("slot") != SLOT
            or dispatch.get("pid") != entry.get("pid")
            or pid_alive(dispatch.get("pid"))
        ):
            return False
        receipt_path = ledger_root / "receipts" / "live" / business_date / SLOT / f"{run_id}.dispatch-receipt.json"
        return str(receipt_path) == entry.get("receipt_path") and not os.path.lexists(receipt_path)
    return False


def _reviewed_no_a_terminal_dispatch_matches(
    ledger_root: Path,
    claim_path: Path,
    claim: Mapping[str, Any],
    manifest: Mapping[str, Any] | None,
    *,
    workload_run_dates: Mapping[str, str],
    pid_alive: Callable[[Any], bool],
) -> bool:
    if manifest is None:
        return False
    try:
        claim_raw = _read_regular(claim_path)
    except OverlayError:
        return False
    for entry in manifest["verified_no_a_workload_terminal_dispatches"]:
        if not _manifest_entry_matches_claim(entry, claim_path, claim, claim_raw):
            continue
        run_id = str(claim.get("run_id") or "")
        business_date = str(claim.get("business_date") or "")
        if (
            run_id in workload_run_dates
            or claim.get("schema_version") != "v3_5.dispatch_claim.v1"
            or claim.get("mode") != "LIVE"
            or claim.get("slot") != SLOT
            or claim.get("scheduled_date") != business_date
            or claim.get("target_date") != business_date
            or not _historical_date_before_target(business_date, R3_FROZEN_MANUAL_TARGET_DATE)
            or pid_alive(claim.get("pid"))
        ):
            return False
        receipt_path = ledger_root / "receipts" / "live" / business_date / SLOT / f"{run_id}.dispatch-receipt.json"
        if str(receipt_path) != entry.get("receipt_path"):
            return False
        try:
            receipt_raw = _read_regular(receipt_path)
            receipt = json.loads(receipt_raw)
        except (OverlayError, UnicodeError, json.JSONDecodeError):
            return False
        selected = receipt.get("selected_workload_ids") if isinstance(receipt, dict) else None
        started = receipt.get("started_workload_ids") if isinstance(receipt, dict) else None
        expected_receipt_path = f"receipts/live/{business_date}/{SLOT}/{run_id}.dispatch-receipt.json"
        if (
            not isinstance(receipt, dict)
            or _sha256(receipt_raw) != entry.get("receipt_sha256")
            or receipt.get("schema_version") != "v3_5.dispatch.v1"
            or receipt.get("ledger_sha256") != _ledger_digest(receipt)
            or any(str(receipt.get(field) or "") != str(claim.get(field) or "") for field in (
                "run_id", "scheduled_date", "business_date", "target_date", "slot", "mode",
            ))
            or receipt.get("receipt_path") != expected_receipt_path
            or receipt.get("status") != entry.get("receipt_status")
            or receipt.get("status") not in NATIVE_TERMINAL_DISPATCH_STATUSES
            or selected != entry.get("selected_workload_ids")
            or started != entry.get("started_workload_ids")
            or not isinstance(selected, list)
            or not isinstance(started, list)
            or WORKLOAD_ID in selected
            or WORKLOAD_ID in started
            or not _finished_receipt_timestamp(receipt.get("finished_at"))
            or any(receipt.get(field) is not False for field in ("production_allowed", "buy_gate_updated", "orders_sent"))
        ):
            return False
        return True
    return False


def _claim_is_live_or_unfinished(
    ledger_root: Path,
    claim_path: Path,
    *,
    expected_workload_id: str | None,
    pid_alive: Callable[[Any], bool],
) -> bool:
    claim = _read_json_object(claim_path)
    if claim.get("mode") != "LIVE" or claim.get("slot") != SLOT:
        raise OverlayError(f"unexpected same-owner claim identity: {claim_path}")
    if not all(
        isinstance(claim.get(field), str) and claim.get(field)
        for field in ("run_id", "scheduled_date", "business_date", "target_date")
    ):
        raise OverlayError(f"same-owner claim lacks dated run identity: {claim_path}")
    if expected_workload_id is not None:
        if claim.get("schema_version") != "v3_5.workload_claim.v1" or claim.get("workload_id") != expected_workload_id:
            raise OverlayError(f"unexpected A workload claim schema or identity: {claim_path}")
    elif claim.get("schema_version") != "v3_5.dispatch_claim.v1":
        raise OverlayError(f"unexpected A dispatch claim schema: {claim_path}")
    if _has_terminal_dispatch_receipt(ledger_root, claim):
        return False
    if pid_alive(claim.get("pid")):
        return True
    # Dead claims without a verified terminal receipt are unresolved. Keep
    # them in place and fail closed instead of silently reclaiming history.
    return True


def assert_same_owner_idle(
    ledger_root: Path,
    *,
    now: datetime,
    pid_alive: Callable[[Any], bool] = _pid_is_alive,
    controller_reviewed_idle_manifest_sha256: str | None = None,
) -> None:
    """Read the existing live O_EXCL ledger; never mutate or remove claims."""
    ledger_root = _require_bound_dispatch_ledger(ledger_root)
    if now.tzinfo is None:
        raise OverlayError("claim inspection time must be timezone-aware")
    reviewed_manifest = _load_controller_reviewed_idle_manifest(controller_reviewed_idle_manifest_sha256)
    workload_claims = sorted(
        (ledger_root / "workloads" / "live").glob(f"*/{SLOT}/{WORKLOAD_ID}.workload-claim.json")
    )
    workload_run_dates: dict[str, str] = {}
    workload_run_paths: dict[str, Path] = {}
    for claim_path in workload_claims:
        claim = _read_json_object(claim_path)
        business_date = claim_path.parents[1].name
        if claim.get("business_date") != business_date:
            raise OverlayError(f"A workload claim date/path mismatch: {claim_path}")
        run_id = str(claim.get("run_id") or "")
        if not run_id:
            raise OverlayError(f"A workload claim lacks run_id: {claim_path}")
        if run_id in workload_run_dates:
            raise OverlayError(f"duplicate same-owner A workload run_id: {claim_path}")
        workload_run_dates[run_id] = business_date
        workload_run_paths[run_id] = claim_path
        if _claim_is_live_or_unfinished(
            ledger_root,
            claim_path,
            expected_workload_id=WORKLOAD_ID,
            pid_alive=pid_alive,
        ) and not _reviewed_inactive_a_pair_matches(
            ledger_root, claim_path, claim, reviewed_manifest, pid_alive=pid_alive
        ):
            raise OverlayError(f"unfinished same-owner A workload claim: {claim_path}")
        dispatch_path = ledger_root / "claims" / "live" / business_date / SLOT / "dispatch.claim.json"
        if dispatch_path.exists():
            dispatch = _read_json_object(dispatch_path)
            if dispatch.get("business_date") != business_date or dispatch.get("run_id") != run_id:
                raise OverlayError(f"A dispatch claim/workload identity mismatch: {dispatch_path}")

    # A dispatch can hold the shared 1700 claim just before the A workload
    # claim is created. Scan the retained live slot claims across dates too:
    # an interrupted orphan from an earlier date is still unresolved until a
    # valid terminal receipt exists. Completed claims remain untouched.
    dispatch_claims = sorted(
        (ledger_root / "claims" / "live").glob(f"*/{SLOT}/dispatch.claim.json")
    )
    for dispatch_path in dispatch_claims:
        business_date = dispatch_path.parents[1].name
        dispatch = _read_json_object(dispatch_path)
        if dispatch.get("business_date") != business_date:
            raise OverlayError(f"A dispatch claim date/path mismatch: {dispatch_path}")
        dispatch_run_id = str(dispatch.get("run_id") or "")
        workload_date = workload_run_dates.get(dispatch_run_id)
        if workload_date is not None and workload_date != business_date:
            raise OverlayError(f"A dispatch claim/workload date mismatch: {dispatch_path}")
        unfinished = _claim_is_live_or_unfinished(
            ledger_root,
            dispatch_path,
            expected_workload_id=None,
            pid_alive=pid_alive,
        )
        if unfinished:
            if dispatch_run_id in workload_run_dates:
                workload_path = workload_run_paths[dispatch_run_id]
                workload_claim = _read_json_object(workload_path)
                reviewed = _reviewed_inactive_a_pair_matches(
                    ledger_root,
                    workload_path,
                    workload_claim,
                    reviewed_manifest,
                    pid_alive=pid_alive,
                )
            else:
                reviewed = _reviewed_no_a_terminal_dispatch_matches(
                    ledger_root,
                    dispatch_path,
                    dispatch,
                    reviewed_manifest,
                    workload_run_dates=workload_run_dates,
                    pid_alive=pid_alive,
                )
            if not reviewed:
                raise OverlayError(f"unfinished same-owner A dispatch claim: {dispatch_path}")


def _validate_activation_window(now: datetime) -> None:
    if now.tzinfo is None:
        raise OverlayError("activation time must be timezone-aware")
    local = now.astimezone(SHANGHAI)
    if local.time() >= time(17, 0):
        raise OverlayError("activation is outside the pre-1700 A window")


def _atomic_compare_and_replace(
    path: Path,
    *,
    expected_before_sha256: str,
    replacement: bytes,
    expected_after_sha256: str,
    before_replace: Callable[[], None] | None = None,
) -> None:
    original = _read_regular(path)
    if _sha256(original) != expected_before_sha256:
        raise OverlayError(f"fixed entry preimage CAS failed: {path}")
    mode = stat.S_IMODE(path.lstat().st_mode)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".candidate", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "wb") as output:
            output.write(replacement)
            output.flush()
            os.fsync(output.fileno())
        if before_replace is not None:
            before_replace()
        if _sha256(_read_regular(path)) != expected_before_sha256:
            raise OverlayError(f"fixed entry changed before atomic replace: {path}")
        os.replace(temporary, path)
        _fsync_directory(path.parent)
        if _sha256(_read_regular(path)) != expected_after_sha256:
            raise OverlayError(f"fixed entry postimage readback failed: {path}")
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def install_fixed_entrypoint(
    component_root: Path = COMPONENT_ROOT,
    *,
    fixed_entry_path: Path = FIXED_ENTRYPOINT,
    base_release_manifest_path: Path = BASE_RELEASE_MANIFEST,
    shim_path: Path | None = None,
    ledger_root: Path,
    review_pass_verified: bool,
    manual_run_terminal_verified: bool,
    now: datetime | None = None,
    process_rows: Iterable[str] | Callable[[], Iterable[str]] | None = None,
    pid_alive: Callable[[Any], bool] = _pid_is_alive,
    controller_reviewed_idle_manifest_sha256: str | None = None,
) -> str:
    """CAS-install the reviewed shim when every controller gate is explicit."""
    if not review_pass_verified or not manual_run_terminal_verified:
        raise OverlayError("activation requires Reviewer PASS and terminated manual A run")
    ledger_root = _require_bound_dispatch_ledger(ledger_root)
    component_root = Path(component_root)
    fixed_entry_path = Path(fixed_entry_path)
    base_release_manifest_path = Path(base_release_manifest_path)
    evidence = verify_prepared_candidate(
        component_root,
        fixed_entry_path=fixed_entry_path,
        base_release_manifest_path=base_release_manifest_path,
    )
    shim = evidence["shim_bytes"]
    if shim_path is not None and _read_regular(Path(shim_path)) != shim:
        raise OverlayError("reviewed shim bytes differ from generated candidate")
    if _sha256(_read_regular(fixed_entry_path)) != BASE_FIXED_ENTRY_SHA256:
        raise OverlayError("fixed A entrypoint is not the expected original preimage")
    if not _read_regular(base_release_manifest_path) or _sha256(_read_regular(base_release_manifest_path)) != BASE_RELEASE_MANIFEST_SHA256:
        raise OverlayError("original release manifest is not the pinned preimage")

    def current_time() -> datetime:
        return now if now is not None else datetime.now(SHANGHAI)

    def process_snapshot() -> Iterable[str]:
        if callable(process_rows):
            return process_rows()
        return _default_process_snapshot() if process_rows is None else process_rows

    def recheck_gates() -> None:
        _validate_activation_window(current_time())
        active = active_a_child_processes(fixed_entry_path, process_rows=process_snapshot())
        if active:
            raise OverlayError("active A child process is present: " + active[0])
        assert_same_owner_idle(
            ledger_root,
            now=current_time(),
            pid_alive=pid_alive,
            controller_reviewed_idle_manifest_sha256=controller_reviewed_idle_manifest_sha256,
        )
        if _sha256(_read_regular(base_release_manifest_path)) != BASE_RELEASE_MANIFEST_SHA256:
            raise OverlayError("original release manifest changed before activation")

    recheck_gates()
    _atomic_compare_and_replace(
        fixed_entry_path,
        expected_before_sha256=BASE_FIXED_ENTRY_SHA256,
        replacement=shim,
        expected_after_sha256=evidence["shim_sha256"],
        before_replace=recheck_gates,
    )
    if _sha256(_read_regular(base_release_manifest_path)) != BASE_RELEASE_MANIFEST_SHA256:
        # Do not overwrite a changed release manifest; the fixed entry remains
        # an independently hash-pinned postimage for controller investigation.
        raise OverlayError("original release manifest changed after activation")
    return evidence["shim_sha256"]


def restore_preimage(
    component_root: Path = COMPONENT_ROOT,
    *,
    fixed_entry_path: Path = FIXED_ENTRYPOINT,
    base_release_manifest_path: Path = BASE_RELEASE_MANIFEST,
    ledger_root: Path,
    now: datetime | None = None,
    process_rows: Iterable[str] | Callable[[], Iterable[str]] | None = None,
    pid_alive: Callable[[Any], bool] = _pid_is_alive,
    controller_reviewed_idle_manifest_sha256: str | None = None,
) -> str:
    """Restore the exact postimage only inside the guarded idle window."""
    ledger_root = _require_bound_dispatch_ledger(ledger_root)
    component_root = Path(component_root)
    fixed_entry_path = Path(fixed_entry_path)
    base_release_manifest_path = Path(base_release_manifest_path)
    verified = verify_prepared_candidate(
        component_root,
        fixed_entry_path=fixed_entry_path,
        base_release_manifest_path=base_release_manifest_path,
    )
    preimage = _read_regular(component_root / "preimage" / "a_share_daily_sync.py")

    def current_time() -> datetime:
        return now if now is not None else datetime.now(SHANGHAI)

    def process_snapshot() -> Iterable[str]:
        if callable(process_rows):
            return process_rows()
        return _default_process_snapshot() if process_rows is None else process_rows

    def recheck_gates() -> None:
        _validate_activation_window(current_time())
        active = active_a_child_processes(fixed_entry_path, process_rows=process_snapshot())
        if active:
            raise OverlayError("active A child process is present during rollback: " + active[0])
        assert_same_owner_idle(
            ledger_root,
            now=current_time(),
            pid_alive=pid_alive,
            controller_reviewed_idle_manifest_sha256=controller_reviewed_idle_manifest_sha256,
        )
        if _sha256(_read_regular(base_release_manifest_path)) != BASE_RELEASE_MANIFEST_SHA256:
            raise OverlayError("original release manifest is not the pinned preimage before rollback")

    recheck_gates()
    _atomic_compare_and_replace(
        fixed_entry_path,
        expected_before_sha256=verified["shim_sha256"],
        replacement=preimage,
        expected_after_sha256=BASE_FIXED_ENTRY_SHA256,
        before_replace=recheck_gates,
    )
    if _sha256(_read_regular(base_release_manifest_path)) != BASE_RELEASE_MANIFEST_SHA256:
        raise OverlayError("original release manifest changed during rollback")
    return BASE_FIXED_ENTRY_SHA256


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Prepare or conditionally install the A-only daily-sync overlay")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("prepare", help="create or verify the inactive component candidate")
    activate = subparsers.add_parser("activate", help="CAS-install after controller release")
    activate.add_argument("--ledger-root", type=Path, required=True)
    activate.add_argument("--review-pass-verified", action="store_true")
    activate.add_argument("--manual-run-terminal-verified", action="store_true")
    activate.add_argument("--controller-reviewed-idle-manifest-sha256")
    rollback = subparsers.add_parser("rollback", help="restore the exact preimage if the shim is still installed")
    rollback.add_argument("--ledger-root", type=Path, required=True)
    rollback.add_argument("--acknowledge-controller-release", action="store_true")
    rollback.add_argument("--controller-reviewed-idle-manifest-sha256")
    args = parser.parse_args(argv)

    if args.command == "prepare":
        result = prepare_component()
    elif args.command == "activate":
        result = {
            "installed_shim_sha256": install_fixed_entrypoint(
                ledger_root=args.ledger_root,
                review_pass_verified=args.review_pass_verified,
                manual_run_terminal_verified=args.manual_run_terminal_verified,
                controller_reviewed_idle_manifest_sha256=args.controller_reviewed_idle_manifest_sha256,
                shim_path=EVIDENCE_ROOT / "entrypoint-shim.py",
            )
        }
    else:
        if not args.acknowledge_controller_release:
            parser.error("rollback requires --acknowledge-controller-release")
        result = {
            "restored_preimage_sha256": restore_preimage(
                ledger_root=args.ledger_root,
                controller_reviewed_idle_manifest_sha256=args.controller_reviewed_idle_manifest_sha256,
            )
        }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
